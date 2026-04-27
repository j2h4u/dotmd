"""UI-agnostic service facade for dotMD.

Provides a high-level API for indexing and searching that hides all
storage, extraction, and fusion details from calling code.
"""

from __future__ import annotations

import logging
from pathlib import Path

from dotmd.core.config import Settings
from dotmd.core.models import IndexStats, SearchMode, SearchResult
from dotmd.ingestion.pipeline import IndexingPipeline
from dotmd.ingestion.trickle import TrickleIndexer
from dotmd.search.fusion import build_search_results, fuse_results
from dotmd.search.graph_direct import GraphDirectEngine
from dotmd.search.graph_search import GraphSearchEngine
from dotmd.search.query import QueryExpander
from dotmd.search.reranker import Reranker
from dotmd.search.semantic import SemanticSearchEngine

logger = logging.getLogger(__name__)


class DotMDService:
    """High-level service facade for indexing and searching markdown files.

    All storage backends, search engines, and extraction components are
    created internally based on the provided :class:`Settings`.

    Parameters
    ----------
    settings:
        Application configuration.  When ``None`` a default
        :class:`Settings` instance is created.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()

        # Indexing pipeline (also creates storage backends and extractors).
        self._pipeline = IndexingPipeline(self._settings)

        # Search engines -- reuse stores and shared connection from pipeline.
        self._semantic_engine = SemanticSearchEngine(
            self._pipeline.vector_store,
            self._settings.embedding_model,
            score_floor=self._settings.semantic_score_floor,
            embedding_url=self._settings.embedding_url,
            tei_batch_size=self._settings.tei_batch_size,
            use_prefix=self._settings.needs_embedding_prefix,
            query_instruction=self._settings.query_instruction,
        )
        self._keyword_engine = self._pipeline.keyword_engine
        self._graph_engine = GraphSearchEngine(
            self._pipeline.graph_store,
            self._pipeline.metadata_store,
        )
        self._graph_direct_engine = GraphDirectEngine(
            self._pipeline.graph_store,
        )

        # Load acronym dictionary if available
        acronym_dict = self._load_acronyms()

        # Query expansion and reranking.
        self._query_expander = QueryExpander(
            acronym_dict=acronym_dict,
        )
        self._reranker = Reranker(
            model_name=self._settings.reranker_model,
            length_penalty=self._settings.reranker_length_penalty,
            min_length=self._settings.reranker_min_length,
        )

        # Background trickle indexer
        self._trickle_indexer = TrickleIndexer(self._settings, self._pipeline)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def trickle_indexer(self) -> TrickleIndexer:
        return self._trickle_indexer

    def warmup(self) -> None:
        """Eagerly load ML models so first query is fast."""
        logger.info("Warming up models...")
        self._semantic_engine.warmup()
        self._reranker._load_model()
        self._keyword_engine.load_index()
        self._graph_direct_engine.load_catalog()
        self._check_embedding_model()
        logger.info("Models ready")

    def _check_embedding_model(self) -> None:
        """Warn if the active embedding model differs from what built the index.

        Compares the model name stored in vec_config (written during indexing)
        against the model actually served by TEI (queried via /info).
        This catches silent search degradation when someone swaps the TEI
        model without re-encoding vectors.
        """
        vs = self._pipeline.vector_store
        if not hasattr(vs, "get_model_name"):
            return
        stored = vs.get_model_name()
        if not stored:
            return
        active = self._semantic_engine.get_tei_model_id()
        if active and stored != active:
            logger.warning(
                "Embedding model mismatch: index was built with %r, "
                "but TEI is serving %r. Run `dotmd reindex vectors` to rebuild.",
                stored,
                active,
            )
        if hasattr(vs, "get_distance_metric"):
            metric = vs.get_distance_metric()
            if metric and metric != "cosine":
                logger.warning(
                    "Distance metric mismatch: index uses %r, but code expects 'cosine'. "
                    "Run `dotmd reindex vectors` to rebuild.",
                    metric,
                )

    def index(self, directory: Path, *, force: bool = False) -> IndexStats:
        """Index all markdown files under *directory*.

        Delegates entirely to :class:`IndexingPipeline`.

        Parameters
        ----------
        directory:
            Root directory to scan.
        force:
            When ``True``, bypass incremental change detection and
            re-index all files from scratch.  When ``False`` (default),
            only new and modified files are processed.

        Returns
        -------
        IndexStats
            Summary statistics for the completed index.
        """
        return self._pipeline.index(directory, force=force)

    def reindex(self, store: str) -> int:
        """Rebuild a single store from metadata chunks.

        Parameters
        ----------
        store:
            Which store to rebuild: ``"vectors"``, ``"fts5"``,
            ``"graph"``, or ``"all"``.

        Returns
        -------
        int
            Number of chunks processed.
        """
        if store == "all":
            n = self._pipeline.reindex_fts5()
            self._pipeline.reindex_vectors()
            self._pipeline.reindex_graph()
            return n
        method = {
            "vectors": self._pipeline.reindex_vectors,
            "fts5": self._pipeline.reindex_fts5,
            "graph": self._pipeline.reindex_graph,
        }.get(store)
        if method is None:
            raise ValueError(f"Unknown store: {store!r}")
        return method()

    def search(
        self,
        query: str,
        top_k: int = 10,
        mode: SearchMode | str = SearchMode.HYBRID,
        rerank: bool = True,
        expand: bool = True,
    ) -> list[SearchResult]:
        """Search the index and return ranked results.

        Parameters
        ----------
        query:
            Natural-language search query.
        top_k:
            Maximum number of results to return.
        mode:
            Search strategy.  One of ``"semantic"``, ``"keyword"``,
            ``"graph"``, or ``"hybrid"`` (default).
        rerank:
            If ``True`` the top candidates are re-scored with a
            cross-encoder model before final ranking.
        expand:
            If ``True`` the query is expanded via :class:`QueryExpander`
            before being sent to the search engines.

        Returns
        -------
        list[SearchResult]
            Ranked search results, at most *top_k* items.

        Side effect: appends one row to ``search_log`` in ``index.db`` on every call.
        """
        logger.info("search: query=%r mode=%s top_k=%d rerank=%s", query[:100], mode, top_k, rerank)

        # -- Optional query expansion -----------------------------------------
        search_query = query
        if expand:
            expanded = self._query_expander.expand(query)
            search_query = expanded.expanded_text or query
            logger.debug(
                "Expanded query: %r -> %r",
                query,
                search_query,
            )

        # -- Determine pool size for reranking --------------------------------
        pool_size = self._settings.rerank_pool_size if rerank else top_k

        try:
            return self._execute_search(
                search_query=search_query,
                original_query=query,
                top_k=top_k,
                mode=mode,
                rerank=rerank,
                pool_size=pool_size,
            )
        except Exception:
            logger.error("search failed: query=%r mode=%s", query[:100], mode, exc_info=True)
            raise

    def _execute_search(
        self,
        search_query: str,
        original_query: str,
        top_k: int,
        mode: SearchMode | str,
        rerank: bool,
        pool_size: int,
    ) -> list[SearchResult]:
        """Core retrieval + fusion + reranking pipeline.

        Separated from :meth:`search` so tests can patch this method to inject
        stub results without running the full engine stack.

        Parameters
        ----------
        search_query:
            Possibly-expanded query string for engine calls.
        original_query:
            The original (unexpanded) query used for snippet extraction.
        top_k, mode, rerank, pool_size:
            Same as :meth:`search`.
        """
        # -- Stage 1: Primary retrieval ----------------------------------------
        semantic_hits: list[tuple[str, float]] = []
        keyword_hits: list[tuple[str, float]] = []
        graph_direct_hits: list[tuple[str, float]] = []

        if mode in (SearchMode.SEMANTIC, SearchMode.HYBRID, SearchMode.GRAPH):
            semantic_hits = self._semantic_engine.search(search_query, top_k=pool_size)

        if mode in (SearchMode.KEYWORD, SearchMode.HYBRID, SearchMode.GRAPH):
            keyword_hits = self._keyword_engine.search(search_query, top_k=pool_size)

        # Graph-direct: entity matching (pre-fusion peer, not seed-based)
        if mode in (SearchMode.GRAPH, SearchMode.HYBRID):
            graph_direct_hits = self._graph_direct_engine.search(
                original_query, top_k=pool_size,
            )

        if not semantic_hits and not keyword_hits and not graph_direct_hits:
            return []

        # -- Stage 2: RRF fusion (all primary engines) -------------------------
        engine_results: dict[str, list[tuple[str, float]]] = {}
        if semantic_hits:
            engine_results["semantic"] = semantic_hits
        if keyword_hits:
            engine_results["keyword"] = keyword_hits
        if graph_direct_hits:
            engine_results["graph_direct"] = graph_direct_hits

        fused = fuse_results(
            engine_results,
            k=self._settings.fusion_k,
        )

        # -- Stage 3: Graph enrichment (post-fusion, not a peer) ---------------
        if mode in (SearchMode.GRAPH, SearchMode.HYBRID) and fused:
            seed_ids = [cid for cid, _ in fused[:pool_size]]
            graph_hits = self._graph_engine.search(
                search_query, top_k=pool_size, seed_chunk_ids=seed_ids,
            )
            if graph_hits:
                # Graph-discovered chunks get appended below primary results.
                # Score: fraction of the lowest fused score so they never
                # outrank direct hits.
                fused_floor = fused[-1][1] if fused else 0.0
                fused_ids = {cid for cid, _ in fused}
                for cid, gscore in graph_hits:
                    if cid not in fused_ids:
                        fused.append((cid, fused_floor * 0.5))
                        fused_ids.add(cid)
                engine_results["graph"] = graph_hits

        # -- Optional reranking -----------------------------------------------
        if rerank and fused:
            rerank_candidates = fused[:pool_size]
            chunk_ids = [cid for cid, _ in rerank_candidates]
            fused_scores = {cid: score for cid, score in fused}  # ALL fused, not just pool_size
            reranked = self._reranker.rerank(
                search_query,
                chunk_ids,
                self._pipeline.metadata_store,
                top_k=pool_size,
            )
            # Reranker found nothing relevant — cross-encoder says no match
            if not reranked:
                return []
            # Blend reranker scores with fusion scores via min-max normalization
            if reranked:
                re_scores = [s for _, s in reranked]
                re_min, re_max = min(re_scores), max(re_scores)
                re_range = re_max - re_min if re_max > re_min else 1.0

                fused_vals = [fused_scores[cid] for cid, _ in reranked if cid in fused_scores]
                fused_min = min(fused_vals) if fused_vals else 0.0
                fused_max = max(fused_vals) if fused_vals else 1.0
                fused_range = fused_max - fused_min if fused_max > fused_min else 1.0

                blended = []
                for cid, re_score in reranked:
                    norm_re = (re_score - re_min) / re_range
                    raw_fused = fused_scores.get(cid, fused_min)
                    norm_fused = (raw_fused - fused_min) / fused_range
                    blended.append((cid, 0.4 * norm_fused + 0.6 * norm_re))

                # Merge back fusion candidates not scored by reranker
                reranked_ids = {cid for cid, _ in blended}
                for cid, fused_score in fused:
                    if cid not in reranked_ids:
                        norm_fused = (fused_score - fused_min) / fused_range
                        blended.append((cid, 0.4 * norm_fused))

                blended.sort(key=lambda x: x[1], reverse=True)
                fused = blended

                # Diagnostic: how many keyword-only matches survived reranking
                kw_ids = {cid for cid, _ in keyword_hits}
                semantic_ids = {cid for cid, _ in semantic_hits}
                kw_only_ids = kw_ids - semantic_ids
                kw_in_final = sum(1 for cid, _ in fused if cid in kw_only_ids)
                logger.debug(
                    "Reranked %d candidates (pool_size=%d, fused=%d); "
                    "%d keyword-only matches in final list",
                    len(reranked),
                    pool_size,
                    len(fused),
                    kw_in_final,
                )

        # -- Build final SearchResult list ------------------------------------
        results = build_search_results(
            fused[:top_k],
            per_engine=engine_results,
            metadata_store=self._pipeline.metadata_store,
            query=original_query,
            top_k=top_k,
            snippet_length=self._settings.snippet_length,
        )

        # Log search for observability and future auto-calibration (Phase 999.12)
        try:
            _reranked = rerank and bool(self._reranker)
            self._pipeline.log_search(
                query=original_query,
                weights_used=self._settings.parsed_embedding_weights,
                top_results=[
                    {
                        "chunk_id": r.chunk_id,
                        "score": float(r.fused_score),
                        "engine": r.matched_engines[0] if r.matched_engines else "unknown",
                    }
                    for r in results[:top_k]
                ],
                mode=mode if isinstance(mode, str) else str(mode),
                reranked=_reranked,
            )
        except Exception:
            logger.warning("search log failed — non-fatal", exc_info=True)

        return results

    def drill(self, file_path: str) -> dict:
        """Return metadata for a file path from search results.

        Reads frontmatter from disk, chunk count from the active strategy's
        M2M table, and entity names from the graph.
        """
        from dotmd.ingestion.reader import parse_frontmatter, read_file

        path = Path(file_path)
        try:
            frontmatter, _ = parse_frontmatter(read_file(path))
        except Exception:
            frontmatter = {}

        chunk_ids = self._pipeline.metadata_store.get_chunk_ids_by_file(
            self._settings.chunk_strategy, file_path
        )
        entities = self._pipeline.graph_store.get_entities_by_file(file_path)

        return {
            "file_path": file_path,
            "frontmatter": frontmatter,
            "chunk_count": len(chunk_ids),
            "entities": entities,
        }

    def status(self, live_diff: bool = True) -> IndexStats:
        """Return the current index statistics.

        Always returns an ``IndexStats`` instance (never ``None``) so that
        trickle indexer progress is available even before any explicit
        ``dotmd index`` command has been run.

        When a previous data_dir is known and the directory still exists,
        runs a live file diff to populate pending change counts.
        Pass ``live_diff=False`` to skip the scan (e.g. from MCP tools).

        Returns
        -------
        IndexStats
            The most recent index statistics enriched with trickle state.
        """
        stats = self._pipeline.metadata_store.get_stats()
        if stats is None:
            stats = IndexStats()
        # Live counts from actual tables (stats table may be stale/empty)
        try:
            conn = self._pipeline.conn
            chunks_table = self._pipeline._chunks_table
            stats.total_chunks = conn.execute(
                f"SELECT COUNT(*) FROM {chunks_table}"
            ).fetchone()[0]
            # Phase 16 P5: file count from M2M table (chunks_* has no file_path column)
            strategy = chunks_table.removeprefix("chunks_")
            m2m_table = f"chunk_file_paths_{strategy}"
            stats.total_files = conn.execute(
                f"SELECT COUNT(DISTINCT file_path) FROM {m2m_table}"
            ).fetchone()[0]
        except Exception:
            logger.debug("live chunk/file count failed", exc_info=True)
        # Change detection: run live diff against all known paths (skip for MCP)
        if live_diff:
            try:
                if self._settings.indexing_paths:
                    from dotmd.ingestion.reader import discover_files_multi

                    files = discover_files_multi(
                        self._settings.indexing_paths,
                        self._settings.indexing_exclude,
                    )
                elif stats.data_dir:
                    data_path = Path(stats.data_dir)
                    if data_path.is_dir():
                        from dotmd.ingestion.reader import discover_files

                        files = discover_files(data_path)
                    else:
                        files = []
                else:
                    files = []

                if files:
                    diff = self._pipeline.chunk_tracker.diff(files)
                    stats.new_files = len(diff.new)
                    stats.modified_files = len(diff.modified)
                    stats.deleted_files = len(diff.deleted)
                    stats.unchanged_files = len(diff.unchanged)
            except Exception as e:
                logger.warning("Change detection failed: %s", e, exc_info=True)

        # Trickle indexer progress
        trickle_state = self._trickle_indexer.state
        stats.trickle_status = trickle_state.status
        stats.trickle_indexed = trickle_state.indexed_count
        stats.trickle_total = trickle_state.total_files
        stats.trickle_current_file = trickle_state.current_file
        stats.trickle_chunks_per_hour = (
            round(trickle_state.chunks_per_hour, 1)
            if trickle_state.chunks_per_hour > 0
            else None
        )
        stats.trickle_files_per_hour = (
            round(trickle_state.files_per_hour, 1)
            if trickle_state.files_per_hour > 0
            else None
        )
        stats.trickle_eta_minutes = (
            round(trickle_state.eta_minutes, 1)
            if trickle_state.eta_minutes is not None
            else None
        )

        return stats

    def graph_data(self) -> dict:
        """Return all graph nodes and edges for visualization."""
        return self._pipeline.graph_store.get_graph_data()

    def drop_vectors(self) -> None:
        """Drop vec tables + embed fingerprints for current (strategy, model).

        Chunks, FTS5, and graph remain intact so BM25 and graph search
        continue to work.
        """
        self._pipeline.drop_vectors()

    def drop_chunks(self) -> None:
        """Drop chunks + FTS5 + graph + ALL vec for current strategy.

        CASCADE operation: everything derived from chunks under the
        current strategy is removed.
        """
        self._pipeline.drop_chunks()

    def clear(self) -> None:
        """Remove all indexed data from every backing store.

        .. deprecated::
            Use :meth:`drop_vectors` or :meth:`drop_chunks` for granular
            cleanup.  Retained temporarily for backward compatibility.
        """
        self._pipeline.clear()

    def _load_acronyms(self) -> dict[str, list[str]] | None:
        """Load acronym dictionary from disk if available.

        Returns
        -------
        dict[str, list[str]] | None
            Acronym dictionary, or None if file doesn't exist.
        """
        import json

        if not self._settings.acronyms_path.exists():
            return None

        try:
            with open(self._settings.acronyms_path) as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Failed to load acronyms: %s", e, exc_info=True)
            return None
