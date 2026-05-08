"""UI-agnostic service facade for dotMD.

Provides a high-level API for indexing and searching that hides all
storage, extraction, and fusion details from calling code.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, NotRequired, TypedDict, cast

from dotmd.core.config import Settings, load_settings
from dotmd.core.models import (
    ChunkProvenance,
    IndexStats,
    SearchMode,
    SearchResult,
    SourceDocument,
    SourceUnit,
)
from dotmd.ingestion.pipeline import IndexingPipeline
from dotmd.ingestion.reader import parse_frontmatter, read_file
from dotmd.ingestion.source_lifecycle import SourceRuntimeFactory
from dotmd.ingestion.source_provider import ApplicationSourceProviderProtocol
from dotmd.ingestion.trickle import TrickleIndexer
from dotmd.search.fusion import build_search_results, fuse_results
from dotmd.search.graph_direct import GraphDirectEngine
from dotmd.search.graph_search import GraphSearchEngine
from dotmd.search.query import QueryExpander
from dotmd.search.reranker import RerankerFactory
from dotmd.search.semantic import SemanticSearchEngine
from dotmd.storage.base import MetadataStoreProtocol

logger = logging.getLogger(__name__)

ACTIVE_FILTER_OVERFETCH_FACTOR = 5
TELEGRAM_REF_PREFIX = "telegram:"


class ReadPayload(TypedDict):
    ref: str
    total_chunks: int
    frontmatter: dict[str, Any]
    chunks: list[dict[str, Any]]  # each: {index: int, heading_hierarchy: list[str], text: str}
    document_ref: NotRequired[str]
    target_unit_ref: NotRequired[str]
    units: NotRequired[list[dict[str, Any]]]
    metadata: NotRequired[dict[str, Any]]


class DrillPayload(TypedDict):
    ref: str
    title: str
    source_uri: str
    document_type: str
    parser_name: str
    frontmatter: dict[str, Any]
    total_chunks: int
    document_ref: NotRequired[str]
    target_unit_ref: NotRequired[str]
    metadata: NotRequired[dict[str, Any]]
    target_metadata: NotRequired[dict[str, Any]]


class BindingDiagnostics(TypedDict):
    active: int
    inactive: int
    retained: int
    reused: int


class RerankCandidatePool(TypedDict):
    search_query: str
    original_query: str
    # Fused candidates after graph enrichment has appended candidates.
    fused: list[tuple[str, float]]
    engine_results: dict[str, list[tuple[str, float]]]
    semantic_hits: list[tuple[str, float]]
    keyword_hits: list[tuple[str, float]]
    graph_direct_hits: list[tuple[str, float]]
    pool_size: int


class RerankerRunComparison(TypedDict):
    name: str
    model_name: str
    elapsed_ms: float
    elapsed: str
    load_ms: float
    load: str
    rerank_ms: float
    rerank: str
    returned_count: int
    top_chunk_ids: list[str]
    scores: list[float]
    error: str | None


class RerankerComparison(TypedDict):
    query: str
    search_query: str
    shared_pool_size: int
    candidate_pool_chunk_ids: list[str]
    rerankers: list[RerankerRunComparison]
    overlap_reference: str | None
    overlap: dict[str, int]


def _parse_telegram_message_ref(ref: str) -> tuple[str, str]:
    """Parse a public Telegram message ref into document and unit refs."""
    if not ref.startswith(TELEGRAM_REF_PREFIX):
        raise ValueError(f"Unknown source ref: {ref}")
    body = ref.removeprefix(TELEGRAM_REF_PREFIX)
    document_ref, separator, message_id_text = body.rpartition(":message:")
    if separator == "" or not document_ref.startswith("dialog:"):
        raise ValueError(f"Unknown source ref: {ref}")
    dialog_id_text = document_ref.removeprefix("dialog:")
    try:
        int(dialog_id_text)
        int(message_id_text)
    except ValueError:
        raise ValueError(f"Unknown source ref: {ref}") from None
    return document_ref, f"{document_ref}:message:{message_id_text}"


def _is_telegram_message_ref(ref: str) -> bool:
    """Return whether *ref* uses the Telegram message-ref shape."""
    return ref.startswith("telegram:dialog:") and ":message:" in ref


def format_elapsed_ms(elapsed_ms: float) -> str:
    """Format elapsed milliseconds for human-facing diagnostics."""
    if elapsed_ms < 1000.0:
        return f"{round(elapsed_ms):.0f}ms"

    total_seconds = max(1, round(elapsed_ms / 1000.0))
    seconds = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60

    if hours:
        return f"{hours}h{minutes:02d}m{seconds:02d}s"
    if minutes:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"


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
        self._settings = settings or load_settings()

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
            cast(MetadataStoreProtocol, self._pipeline.metadata_store),
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
        self._reranker_factory = RerankerFactory(self._settings)

        # Background trickle indexer
        self._trickle_indexer = TrickleIndexer(self._settings, self._pipeline)
        self._source_provenance_ready_strategies: set[str] = set()
        self._source_runtime_factory: SourceRuntimeFactory = (
            self._pipeline.source_runtime_factory
        )
        self._telegram_provider = self._build_telegram_provider()

    def _build_telegram_provider(self) -> ApplicationSourceProviderProtocol | None:
        """Build the optional Telegram provider from the source lifecycle."""
        bundle = self._source_runtime_factory.build_if_configured("telegram")
        if bundle is None:
            return None
        if bundle.provider is None:
            raise RuntimeError("telegram lifecycle runtime has no provider")
        return bundle.provider

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
        try:
            self._reranker_factory.get().warmup()
        except Exception:
            logger.warning(
                "reranker warmup failed; search will fall back to fused ranking",
                exc_info=True,
            )
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
        vs = cast(Any, self._pipeline.vector_store)
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
        reranker_name: str | None = None,
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
        reranker_name:
            Optional stable reranker name to use for this request. When
            omitted, the configured default is used.

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
        active_pool_size = self._active_filter_pool_size(top_k, pool_size)

        try:
            return self._execute_search(
                search_query=search_query,
                original_query=query,
                top_k=top_k,
                mode=mode,
                rerank=rerank,
                reranker_name=reranker_name,
                pool_size=active_pool_size,
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
        reranker_name: str | None,
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
        top_k, mode, rerank, reranker_name, pool_size:
        Same as :meth:`search`.
        """
        self._ensure_source_provenance_ready()
        active_pool_size = self._active_filter_pool_size(top_k, pool_size)
        pool, filtered_fused, active_provenance_map, inactive_count = (
            self._collect_active_candidate_pool(
                search_query=search_query,
                original_query=original_query,
                mode=mode,
                top_k=top_k,
                pool_size=active_pool_size,
            )
        )
        fused = pool["fused"]
        if not fused:
            return []
        engine_results = pool["engine_results"]
        semantic_hits = pool["semantic_hits"]
        keyword_hits = pool["keyword_hits"]
        if len(filtered_fused) < top_k:
            logger.warning(
                "active filter underfilled: requested=%d active=%d inactive=%d candidates=%d",
                top_k,
                len(filtered_fused),
                inactive_count,
                len(fused),
            )
        fused = filtered_fused
        if not fused:
            return []

        # -- Optional reranking -----------------------------------------------
        reranked_applied = False
        if rerank and fused:
            rerank_limit = min(pool_size, len(fused))
            rerank_candidates = fused[:rerank_limit]
            chunk_ids = [cid for cid, _ in rerank_candidates]
            fused_scores = dict(fused)  # ALL fused, not just pool_size
            reranker = self._reranker_factory.get(reranker_name)
            reranked = reranker.rerank(
                search_query,
                chunk_ids,
                cast(MetadataStoreProtocol, self._pipeline.metadata_store),
                top_k=rerank_limit,
            )
            if not reranked:
                logger.info(
                    "reranker returned no candidates; falling back to fused ranking"
                )
                reranked = []
            # Blend reranker scores with fusion scores via min-max normalization
            if reranked:
                reranked_applied = True
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
                        blended.append((cid, fused_score))

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
            metadata_store=cast(MetadataStoreProtocol, self._pipeline.metadata_store),
            query=original_query,
            top_k=top_k,
            snippet_length=self._settings.snippet_length,
            provenance_map=active_provenance_map,
        )

        # Log search for observability and future auto-calibration (Phase 999.12)
        try:
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
                reranked=reranked_applied,
            )
        except Exception:
            logger.warning("search log failed — non-fatal", exc_info=True)

        return results

    def _active_filter_pool_size(self, top_k: int, pool_size: int) -> int:
        """Return candidate pool size used before active-binding filtering."""
        return max(
            pool_size,
            top_k * ACTIVE_FILTER_OVERFETCH_FACTOR,
            top_k + 50,
        )

    def _collect_active_candidate_pool(
        self,
        *,
        search_query: str,
        original_query: str,
        mode: SearchMode | str,
        top_k: int,
        pool_size: int,
    ) -> tuple[
        RerankCandidatePool,
        list[tuple[str, float]],
        dict[str, ChunkProvenance],
        int,
    ]:
        """Expand retrieval until active candidates are filled or engines exhaust."""
        active_pool_size = self._active_filter_pool_size(top_k, pool_size)
        previous_count = -1
        inactive_count = 0
        active_provenance_map: dict[str, ChunkProvenance] = {}
        filtered_fused: list[tuple[str, float]] = []

        while True:
            pool = self._collect_candidate_pool(
                search_query=search_query,
                original_query=original_query,
                mode=mode,
                pool_size=active_pool_size,
            )
            fused = pool["fused"]
            if not fused:
                return pool, [], {}, 0

            filtered_fused, active_provenance_map, inactive_count = (
                self._filter_active_fused_candidates(fused)
            )
            if len(filtered_fused) >= top_k:
                return pool, filtered_fused, active_provenance_map, inactive_count
            if len(fused) < active_pool_size:
                return pool, filtered_fused, active_provenance_map, inactive_count
            if len(fused) <= previous_count:
                return pool, filtered_fused, active_provenance_map, inactive_count

            previous_count = len(fused)
            active_pool_size *= 2

    def _filter_active_fused_candidates(
        self,
        fused: list[tuple[str, float]],
    ) -> tuple[list[tuple[str, float]], dict[str, ChunkProvenance], int]:
        """Drop inactive public candidates while preserving missing-provenance errors."""
        strategy = self._settings.chunk_strategy
        chunk_ids = [chunk_id for chunk_id, _score in fused]
        store = self._pipeline.metadata_store
        all_provenance = store.get_chunk_provenance_for_chunk_ids(strategy, chunk_ids)
        active_provenance = store.get_active_chunk_provenance_for_chunk_ids(
            strategy,
            chunk_ids,
        )

        filtered: list[tuple[str, float]] = []
        inactive_count = 0
        for chunk_id, score in fused:
            if chunk_id in active_provenance:
                filtered.append((chunk_id, score))
                continue
            if chunk_id in all_provenance:
                inactive_count += 1
                continue
            raise ValueError(f"missing source provenance for chunk_id={chunk_id}")

        return filtered, active_provenance, inactive_count

    def compare_rerankers(
        self,
        query: str,
        reranker_names: list[str] | None = None,
        top_k: int = 10,
        mode: SearchMode | str = SearchMode.HYBRID,
        expand: bool = True,
    ) -> RerankerComparison:
        """Compare configured rerankers over one shared candidate pool.

        This is a developer diagnostic path. It intentionally returns raw
        reranker ordering and scores instead of building user search results.
        """
        search_query = query
        if expand:
            expanded = self._query_expander.expand(query)
            search_query = expanded.expanded_text or query

        pool_size = self._settings.rerank_pool_size
        pool = self._collect_candidate_pool(
            search_query=search_query,
            original_query=query,
            mode=mode,
            pool_size=pool_size,
        )
        chunk_ids = [cid for cid, _score in pool["fused"][:pool_size]]
        names = reranker_names or self._settings.parsed_reranker_compare_names

        runs: list[RerankerRunComparison] = []
        for name in names:
            reranker = self._reranker_factory.get(name)
            started_total = time.perf_counter()
            load_ms = 0.0
            rerank_ms = 0.0
            load_finished = False
            try:
                reranker.warmup()
                load_finished_at = time.perf_counter()
                load_ms = (load_finished_at - started_total) * 1000.0
                load_finished = True

                reranked = reranker.rerank(
                    search_query,
                    chunk_ids,
                    cast(MetadataStoreProtocol, self._pipeline.metadata_store),
                    top_k=top_k,
                    raise_on_provider_error=True,
                )
                finished_at = time.perf_counter()
                rerank_ms = (finished_at - load_finished_at) * 1000.0
                elapsed_ms = (finished_at - started_total) * 1000.0
                runs.append(
                    {
                        "name": name,
                        "model_name": reranker.model_name,
                        "elapsed_ms": elapsed_ms,
                        "elapsed": format_elapsed_ms(elapsed_ms),
                        "load_ms": load_ms,
                        "load": format_elapsed_ms(load_ms),
                        "rerank_ms": rerank_ms,
                        "rerank": format_elapsed_ms(rerank_ms),
                        "returned_count": len(reranked),
                        "top_chunk_ids": [cid for cid, _score in reranked],
                        "scores": [float(score) for _cid, score in reranked],
                        "error": None,
                    }
                )
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - started_total) * 1000.0
                if load_finished:
                    rerank_ms = max(0.0, elapsed_ms - load_ms)
                else:
                    load_ms = elapsed_ms
                runs.append(
                    {
                        "name": name,
                        "model_name": reranker.model_name,
                        "elapsed_ms": elapsed_ms,
                        "elapsed": format_elapsed_ms(elapsed_ms),
                        "load_ms": load_ms,
                        "load": format_elapsed_ms(load_ms),
                        "rerank_ms": rerank_ms,
                        "rerank": format_elapsed_ms(rerank_ms),
                        "returned_count": 0,
                        "top_chunk_ids": [],
                        "scores": [],
                        "error": str(exc),
                    }
                )

        runs.sort(key=lambda run: (run["error"] is not None, run["rerank_ms"]))
        successful = [run for run in runs if run["error"] is None]
        overlap_reference = successful[0]["name"] if successful else None
        overlap: dict[str, int] = {}
        if successful:
            reference_ids = set(successful[0]["top_chunk_ids"])
            overlap = {
                run["name"]: len(reference_ids & set(run["top_chunk_ids"]))
                for run in successful
            }

        return {
            "query": query,
            "search_query": search_query,
            "shared_pool_size": len(chunk_ids),
            "candidate_pool_chunk_ids": chunk_ids,
            "rerankers": runs,
            "overlap_reference": overlap_reference,
            "overlap": overlap,
        }

    def _collect_candidate_pool(
        self,
        *,
        search_query: str,
        original_query: str,
        mode: SearchMode | str,
        pool_size: int,
    ) -> RerankCandidatePool:
        """Collect fused candidates after graph enrichment for reuse by rerankers."""
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
            return {
                "search_query": search_query,
                "original_query": original_query,
                "fused": [],
                "engine_results": {},
                "semantic_hits": semantic_hits,
                "keyword_hits": keyword_hits,
                "graph_direct_hits": graph_direct_hits,
                "pool_size": pool_size,
            }

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
            try:
                graph_hits = self._graph_engine.search(
                    search_query, top_k=pool_size, seed_chunk_ids=seed_ids,
                )
            except Exception:
                logger.warning(
                    "graph enrichment failed; continuing with primary fused results",
                    exc_info=True,
                )
                graph_hits = []
            if graph_hits:
                # Graph-discovered chunks get appended below primary results.
                # Score: fraction of the lowest fused score so they never
                # outrank direct hits.
                fused_floor = fused[-1][1] if fused else 0.0
                fused_ids = {cid for cid, _ in fused}
                for cid, _gscore in graph_hits:
                    if cid not in fused_ids:
                        fused.append((cid, fused_floor * 0.5))
                        fused_ids.add(cid)
                engine_results["graph"] = graph_hits

        return {
            "search_query": search_query,
            "original_query": original_query,
            "fused": fused,
            "engine_results": engine_results,
            "semantic_hits": semantic_hits,
            "keyword_hits": keyword_hits,
            "graph_direct_hits": graph_direct_hits,
            "pool_size": pool_size,
        }

    def _ensure_source_provenance_ready(self) -> None:
        """Ensure the active strategy can hydrate public source refs before search."""
        strategy = self._settings.chunk_strategy
        if strategy in self._source_provenance_ready_strategies:
            return

        store = self._pipeline.metadata_store
        try:
            missing = store.count_missing_source_provenance(strategy)
        except AttributeError:
            logger.debug("metadata store has no source provenance safety helpers")
            self._source_provenance_ready_strategies.add(strategy)
            return

        if not isinstance(missing, int):
            logger.debug("metadata store returned non-integer provenance count: %r", missing)
            self._source_provenance_ready_strategies.add(strategy)
            return

        if missing > 0:
            inserted = store.backfill_missing_source_provenance_from_file_paths(
                strategy,
                dry_run=False,
            )
            remaining = store.count_missing_source_provenance(strategy)
            if remaining > 0:
                raise ValueError(
                    "source provenance backfill incomplete: "
                    f"missing={missing} inserted={inserted} remaining={remaining}"
                )
            logger.info(
                "source provenance backfilled: strategy=%s missing=%d inserted=%d",
                strategy,
                missing,
                inserted,
            )

        # Migration guard, not a steady-state search dependency.
        #
        # Phase 27 made active resource bindings the public visibility gate:
        # chunks/provenance may be retained for reuse, but ordinary search must
        # only return resources with active source_documents/resource_bindings.
        # Phase 33 then routed filesystem construction through lifecycle, which
        # correctly writes those rows for newly indexed files. The problem this
        # guard covers is older live indexes: they can already have chunks,
        # FTS/vector rows, and chunk_source_provenance, while unchanged files
        # never re-enter the indexing path that now creates source_documents and
        # active bindings. Without this repair, the active filter would hide
        # valid indexed content even though the expensive artifacts are intact.
        #
        # Keep this path additive: it may create missing filesystem
        # source_documents and active resource_bindings from existing provenance,
        # but it must not rebuild chunks, embeddings, FTS, graph data, or
        # fingerprints. Once all supported deployments have migrated cleanly
        # and new indexing has proven it maintains the invariant by itself, this
        # guard should be removed and replaced with a hard integrity failure.
        try:
            source_doc_diagnostic = (
                self._pipeline.backfill_filesystem_source_documents_from_provenance(
                    strategy,
                    dry_run=False,
                )
            )
        except AttributeError:
            logger.debug("pipeline has no filesystem source-document backfill helper")
        else:
            inserted_docs = int(
                source_doc_diagnostic.get("inserted_source_documents", 0)
            )
            inserted_bindings = int(source_doc_diagnostic.get("inserted_bindings", 0))
            if inserted_docs or inserted_bindings:
                logger.info(
                    "filesystem source bindings backfilled: strategy=%s docs=%d "
                    "bindings=%d missing_files=%d skipped_files=%d",
                    strategy,
                    inserted_docs,
                    inserted_bindings,
                    int(source_doc_diagnostic.get("missing_files", 0)),
                    int(source_doc_diagnostic.get("skipped_files", 0)),
                )

        self._source_provenance_ready_strategies.add(strategy)

    def _parse_ref(self, ref: str) -> tuple[str, str]:
        """Split a public source ref into namespace and document_ref."""
        namespace, separator, document_ref = ref.partition(":")
        if not separator or not namespace or not document_ref:
            raise ValueError(f"Unknown source ref: {ref}")
        return namespace, document_ref

    def _resolve_source_document(self, ref: str) -> SourceDocument:
        """Resolve a public ref to its source document row."""
        namespace, document_ref = self._parse_ref(ref)
        document = self._pipeline.metadata_store.get_source_document(
            namespace,
            document_ref,
        )
        if document is not None:
            return document
        if namespace == "filesystem":
            resolved = Path(document_ref).resolve()
            active_chunk_count = self._pipeline.metadata_store.get_chunk_count_for_file(
                self._settings.chunk_strategy,
                str(resolved),
            )
            if not isinstance(active_chunk_count, int) or active_chunk_count <= 0:
                raise ValueError(f"Unknown source ref: {ref}")
            if not resolved.exists():
                raise ValueError(f"Unknown source ref: {ref}")
            return SourceDocument(
                namespace="filesystem",
                document_ref=str(resolved),
                ref=f"filesystem:{resolved}",
                source_uri=resolved.as_uri(),
                file_path=resolved,
                media_type="text/markdown",
                parser_name="markdown",
                document_type="document",
                title=resolved.stem,
                updated_at=datetime.fromtimestamp(resolved.stat().st_mtime),
                content_fingerprint="",
                metadata_fingerprint="",
                metadata_json={},
            )
        raise ValueError(f"Unknown source ref: {ref}")

    def _require_active_source_document(self, ref: str) -> SourceDocument:
        """Resolve a public ref only when its resource binding is active."""
        namespace, document_ref = self._parse_ref(ref)
        if not self._pipeline.metadata_store.is_resource_binding_active(
            namespace,
            document_ref,
        ):
            raise ValueError(f"Unknown source ref: {ref}")
        return self._resolve_source_document(ref)

    def _require_active_telegram_message_ref(self, ref: str) -> tuple[SourceDocument, str]:
        """Resolve a Telegram message ref through its active dialog binding."""
        document_ref, unit_ref = _parse_telegram_message_ref(ref)
        if not self._pipeline.metadata_store.is_resource_binding_active(
            "telegram",
            document_ref,
        ):
            raise ValueError(f"Unknown source ref: {ref}")
        document = self._pipeline.metadata_store.get_source_document(
            "telegram",
            document_ref,
        )
        if document is None or document.namespace != "telegram":
            raise ValueError(f"Unknown source ref: {ref}")
        return document, unit_ref

    def _filesystem_path_for_source(
        self,
        document: SourceDocument,
        ref: str,
    ) -> str:
        if document.namespace != "filesystem":
            raise ValueError(f"Unsupported source namespace: {document.namespace}")
        if document.file_path is None:
            raise ValueError(f"Unknown source ref: {ref}")
        path = document.file_path
        if not path.exists():
            raise ValueError(f"Unknown source ref: {ref}")
        return str(path)

    def _read_frontmatter(self, path: Path) -> dict[str, Any]:
        try:
            frontmatter, _ = parse_frontmatter(read_file(path))
        except Exception:
            logger.warning("frontmatter parse failed: %s", path, exc_info=True)
            return {}
        return frontmatter

    def _telegram_window_sizes(
        self,
        start: int,
        end: int | None,
    ) -> tuple[int, int]:
        before = max(0, min(start, 50))
        after = 5 if end is None else max(0, min(end, 50))
        return before, after

    def _telegram_unit_payload(
        self,
        unit: SourceUnit,
        target_unit_ref: str,
    ) -> dict[str, Any]:
        metadata = dict(unit.metadata_json)
        message_id = metadata.get("message_id")
        if message_id is None:
            try:
                message_id = int(unit.unit_ref.rsplit(":message:", 1)[1])
            except (IndexError, ValueError):
                message_id = None
        return {
            "unit_ref": unit.unit_ref,
            "message_id": message_id,
            "text": unit.text,
            "sender_id": metadata.get("sender_id"),
            "sender_name": metadata.get("sender_name"),
            "sent_at": metadata.get("sent_at") or unit.updated_at.isoformat(),
            "topic_id": metadata.get("topic_id"),
            "topic_title": metadata.get("topic_title"),
            "reply_to_msg_id": metadata.get("reply_to_msg_id"),
            "edit_date": metadata.get("edit_date"),
            "target": unit.unit_ref == target_unit_ref,
        }

    def _read_telegram_message(
        self,
        ref: str,
        start: int,
        end: int | None,
    ) -> ReadPayload:
        document, unit_ref = self._require_active_telegram_message_ref(ref)
        before, after = self._telegram_window_sizes(start, end)
        if self._telegram_provider is not None:
            window = self._telegram_provider.read_unit_window(
                unit_ref,
                before=before,
                after=after,
            )
            units = [
                self._telegram_unit_payload(unit, unit_ref)
                for unit in window.units
            ]
            return cast(
                ReadPayload,
                {
                    "ref": ref,
                    "document_ref": document.document_ref,
                    "target_unit_ref": unit_ref,
                    "total_chunks": len(units),
                    "frontmatter": {},
                    "units": units,
                    "chunks": [],
                    "metadata": {
                        **document.metadata_json,
                        **window.metadata_json,
                    },
                },
            )

        chunks = self._pipeline.metadata_store.get_chunks_by_source_unit_ref(
            "telegram",
            document.document_ref,
            unit_ref,
            self._settings.chunk_strategy,
        )
        if not chunks:
            raise ValueError(f"Unknown source ref: {ref}")
        chunk_payloads: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks):
            source_unit_refs = (
                chunk.provenance.source_unit_refs
                if chunk.provenance is not None
                else []
            )
            chunk_payloads.append(
                {
                    "index": index,
                    "heading_hierarchy": chunk.heading_hierarchy,
                    "text": chunk.text,
                    "target": unit_ref in source_unit_refs,
                    "source_unit_refs": source_unit_refs,
                }
            )
        return cast(
            ReadPayload,
            {
                "ref": ref,
                "document_ref": document.document_ref,
                "target_unit_ref": unit_ref,
                "total_chunks": len(chunk_payloads),
                "frontmatter": {},
                "chunks": chunk_payloads,
                "units": [],
                "metadata": document.metadata_json,
            },
        )

    def _drill_telegram_message(self, ref: str) -> DrillPayload:
        document, unit_ref = self._require_active_telegram_message_ref(ref)
        target_metadata: dict[str, Any] = {}
        if self._telegram_provider is not None:
            try:
                window = self._telegram_provider.read_unit_window(
                    unit_ref,
                    before=0,
                    after=0,
                )
            except Exception:
                logger.warning("telegram target metadata lookup failed", exc_info=True)
            else:
                for unit in window.units:
                    if unit.unit_ref == unit_ref:
                        target_metadata = self._telegram_unit_payload(unit, unit_ref)
                        break
        return cast(
            DrillPayload,
            {
                "ref": ref,
                "document_ref": document.document_ref,
                "target_unit_ref": unit_ref,
                "title": document.title,
                "source_uri": document.source_uri,
                "document_type": document.document_type,
                "parser_name": document.parser_name,
                "frontmatter": {},
                "metadata": document.metadata_json,
                "target_metadata": target_metadata,
                "total_chunks": 0,
            },
        )

    def read(self, ref: str, start: int = 0, end: int | None = None) -> ReadPayload:
        """Return frontmatter and optionally a chunk range for a source ref.

        When end is None, returns only frontmatter and total_chunks (metadata
        mode — cheap, useful for planning a subsequent ranged call).
        When end is provided, also returns chunks[start:end], capped at 50.
        """
        if _is_telegram_message_ref(ref):
            return self._read_telegram_message(ref, start, end)

        document = self._require_active_source_document(ref)
        file_path = self._filesystem_path_for_source(document, ref)
        path = Path(file_path)
        frontmatter = self._read_frontmatter(path)

        # Phase 26 read(ref) is active-strategy-only; future source adapters may add explicit strategy discovery.
        strategy = self._settings.chunk_strategy
        total_chunks = self._pipeline.metadata_store.get_chunk_count_for_file(
            strategy,
            file_path,
        )
        if total_chunks == 0:
            raise ValueError("No chunks for source ref in active strategy")

        chunks: list[dict] = []
        if end is not None:
            end = min(end, start + 50)
            chunks = self._pipeline.metadata_store.get_chunks_for_file_range(
                strategy,
                file_path,
                start,
                end,
            )

        return {
            "ref": document.ref,
            "total_chunks": total_chunks,
            "frontmatter": frontmatter,
            "chunks": chunks,
        }

    def drill(self, ref: str) -> DrillPayload:
        """Return structured source metadata for a source ref."""
        if _is_telegram_message_ref(ref):
            return self._drill_telegram_message(ref)

        document = self._require_active_source_document(ref)
        file_path = self._filesystem_path_for_source(document, ref)
        frontmatter = self._read_frontmatter(Path(file_path))
        total_chunks = self._pipeline.metadata_store.get_chunk_count_for_file(
            self._settings.chunk_strategy,
            file_path,
        )
        return {
            "ref": document.ref,
            "title": document.title,
            "source_uri": document.source_uri,
            "document_type": document.document_type,
            "parser_name": document.parser_name,
            "frontmatter": frontmatter,
            "total_chunks": total_chunks,
        }

    def binding_diagnostics(self) -> BindingDiagnostics:
        """Return binding/artifact count diagnostics without exposing inactive content."""
        binding_counts = self._pipeline.metadata_store.count_resource_bindings()
        rebind_diagnostic = getattr(self._pipeline, "_last_rebind_diagnostic", {})
        reused = self._pipeline.metadata_store.count_reused_chunks_from_bindings()
        if isinstance(rebind_diagnostic, dict):
            reused = max(reused, int(rebind_diagnostic.get("reused_chunks", 0) or 0))
        return {
            "active": int(binding_counts.get("active", 0)),
            "inactive": int(binding_counts.get("inactive", 0)),
            "retained": self._pipeline.metadata_store.count_retained_inactive_chunks(
                self._settings.chunk_strategy,
            ),
            "reused": reused,
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
        # Live graph counts (stats table is only updated by batch run(), not trickle)
        try:
            stats.total_entities = self._pipeline.graph_store.node_count()
            stats.total_edges = self._pipeline.graph_store.edge_count()
        except Exception:
            logger.debug("live graph count failed", exc_info=True)
        # Change detection: run live diff against all known paths (skip for MCP)
        if live_diff:
            try:
                if self._settings.indexing_paths:
                    from dotmd.ingestion.reader import discover_files_multi

                    files = discover_files_multi(
                        self._settings.indexing_paths,
                        self._settings.effective_indexing_exclude,
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
