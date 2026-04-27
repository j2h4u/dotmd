"""End-to-end indexing pipeline for dotMD.

Orchestrates file discovery, chunking, embedding, FTS5 index construction,
structural and NER extraction, and knowledge-graph population.

Supports two modes:
- **Incremental** (default): only new/modified files are processed;
  deleted files are purged; unchanged files are skipped entirely.
- **Full** (``force=True``): all stores are cleared and every file is
  re-indexed from scratch.

Table naming is two-dimensional: ``(chunk_strategy, embedding_model)``.
Chunk-derived tables use ``_{strategy}`` suffix.  Vector tables use
``_{strategy}_{model}`` suffix.  This enables safe multi-model and
multi-strategy experimentation without data collision.
"""

from __future__ import annotations

import blake3
import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass as _dataclass
from datetime import datetime, timezone
from pathlib import Path

import sqlite_vec  # type: ignore[import-untyped]

from dotmd.core.config import Settings
from dotmd.core.models import Chunk, DocKind, EntityType, ExtractDepth, ExtractionResult, FileInfo, IndexStats, RelationType
from dotmd.extraction.acronyms import extract_acronyms_from_chunks
from dotmd.extraction.keyterms import KeyTermExtractor
from dotmd.extraction.ner import NERExtractor
from dotmd.extraction.structural import StructuralExtractor
import dotmd.ingestion.chunker as _chunker_module
from dotmd.ingestion.content_handlers import get_handler
from dotmd.ingestion.file_tracker import FileDiff, FileTracker
from dotmd.ingestion.reader import chunk_checksum, meta_checksum, discover_files, parse_frontmatter, read_file
from dotmd.storage.vec_components import VecComponentStore
from dotmd.search.fts5 import FTS5SearchEngine
from dotmd.search.semantic import SemanticSearchEngine
from dotmd.storage.base import GraphStoreProtocol, VectorStoreProtocol
from dotmd.storage.cache import EmbeddingCache, ExtractionCache
from dotmd.storage.metadata import SQLiteMetadataStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


@_dataclass
class _ExtractionBundle:
    """Grouped extraction results from all extractors."""

    entities: list
    relations: list
    total_entities: int
    total_relations: int


def _model_to_table_suffix(model_name: str) -> str:
    """Derive a sqlite table name suffix from an embedding model name.

    'intfloat/multilingual-e5-large' → '_multilingual_e5_large'
    'Qwen/Qwen3-Embedding-0.6B' → '_qwen3_embedding'
    'BAAI/bge-small-en-v1.5' → '_bge_small_en_v1'

    All models get a suffix — no legacy exceptions.
    Version stripping kept for now (removal deferred to migration phase
    when tables are renamed).
    """
    import re

    if not model_name:
        return "_default"
    # Take the part after the slash (org/model → model)
    name = model_name.rsplit("/", 1)[-1]
    # Strip version suffixes like -0.6B, -v2.1
    name = re.sub(r"-[\d.]+[BbMm]?$", "", name)
    # Replace non-alphanumeric with underscore, collapse multiples
    name = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()
    return f"_{name}" if name else "_default"


def _create_graph_store(settings: Settings) -> GraphStoreProtocol:
    """Instantiate the configured graph store backend."""
    if settings.graph_backend == "falkordb":
        from dotmd.storage.falkordb_graph import FalkorDBGraphStore

        return FalkorDBGraphStore(
            url=settings.falkordb_url,
            graph_name="dotmd",
        )
    from dotmd.storage.graph import LadybugDBGraphStore

    return LadybugDBGraphStore(settings.graph_db_path)


class IndexingPipeline:
    """Orchestrates the full indexing workflow from raw files to populated stores.

    All SQLite-backed stores (metadata, vectors, FTS5, fingerprints) share
    a single ``sqlite3.Connection`` to the unified ``index.db`` database.
    Table names are derived from ``(chunk_strategy, embedding_model)`` to
    enable multi-strategy and multi-model isolation.

    Parameters
    ----------
    settings:
        Application-wide configuration.  Storage paths, model names, and
        extraction options are all derived from this object.
    """

    SCHEMA_VERSION = "2"  # Phase 999.12: text_hash=hash(body only), vec_components added

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

        # Ensure the index directory exists.
        settings.index_dir.mkdir(parents=True, exist_ok=True)

        # -- Unified SQLite connection ----------------------------------------
        # ONE connection shared by metadata store, vec store, FTS5, and
        # file trackers.  sqlite-vec extension loaded once here.
        self._conn = sqlite3.connect(
            str(settings.index_db_path), check_same_thread=False,
            isolation_level=None,  # autocommit — pipeline manages all transactions explicitly
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        self._conn.enable_load_extension(False)

        # -- Strategy + model table name derivation ---------------------------
        strategy = settings.chunk_strategy
        model_suffix = _model_to_table_suffix(settings.embedding_model)

        self._strategy = strategy
        self._model_suffix = model_suffix

        self._chunks_table = f"chunks_{strategy}"
        self._fts_table = f"chunks_fts_{strategy}"
        vec_table = f"vec_chunks_{strategy}{model_suffix}"
        chunk_fp_table = f"chunk_fingerprints_{strategy}"
        meta_fp_table = f"meta_fingerprints_{strategy}{model_suffix}"

        # -- storage backends --------------------------------------------------
        self._metadata_store = SQLiteMetadataStore(
            conn=self._conn,
            table_name=self._chunks_table,
            fts_table_name=self._fts_table,
        )
        # Ensure M2M table exists for this strategy (Phase 16).
        self._metadata_store.ensure_m2m_table(strategy)

        if settings.vector_backend == "sqlite-vec":
            from dotmd.storage.sqlite_vec import SQLiteVecVectorStore

            self._vector_store: VectorStoreProtocol = SQLiteVecVectorStore(
                conn=self._conn, table_name=vec_table,
            )
        else:
            from dotmd.storage.vector import LanceDBVectorStore

            self._vector_store = LanceDBVectorStore(settings.lancedb_path)

        self._graph_store = _create_graph_store(settings)

        # -- Two file trackers with different checksum formulas -----------------
        # ADR: Two-fingerprint architecture for granular change detection.
        # chunk_tracker: hash(body + kind) → detects content/kind changes → re-chunk
        # meta_tracker: hash(title + tags) → detects metadata-only changes →
        #   1 TEI call (e_meta) + local fusion recompute (no body re-embed)
        # This prevents 26hr full reindex when only tags/title change.
        self._chunk_tracker = FileTracker(
            self._conn, table_name=chunk_fp_table, checksum_fn=chunk_checksum,
        )
        self._meta_tracker = FileTracker(
            self._conn, table_name=meta_fp_table, checksum_fn=meta_checksum,
        )

        # -- VecComponentStore: raw per-component embedding BLOBs ---------------
        # Stores e_text (per chunk_id) and e_meta (per canonical file path)
        # for the dual-encoder architecture. Authoritative e_text source for
        # the metadata-only fast path and weight-change recompute.
        vec_components_table = f"vec_components_{strategy}{model_suffix}"
        self._vec_components = VecComponentStore(
            conn=self._conn, table_name=vec_components_table,
        )

        # -- search_log table --------------------------------------------------
        # Shared log for all (strategy, model) combos — no suffix needed.
        # mode/reranked columns included for Phase 999.15/999.16 calibration use.
        # reranked is INTEGER (0/1) — SQLite has no native BOOLEAN type.
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS search_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                query        TEXT NOT NULL,
                timestamp    TEXT NOT NULL,
                weights_used TEXT NOT NULL,
                top_results  TEXT NOT NULL,
                mode         TEXT NOT NULL DEFAULT 'hybrid',
                reranked     INTEGER NOT NULL DEFAULT 0
            )
        """)
        # id INTEGER PRIMARY KEY AUTOINCREMENT already creates an efficient rowid
        # index. The explicit index below enables efficient DELETE...ORDER BY id
        # trimming and potential future covering indexes.
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS search_log_id_idx ON search_log(id)"
        )
        self._conn.commit()

        # -- search engines (used for encoding during indexing) ----------------
        self._semantic_engine = SemanticSearchEngine(
            self._vector_store,
            settings.embedding_model,
            embedding_url=settings.embedding_url,
            tei_batch_size=settings.tei_batch_size,
            use_prefix=settings.needs_embedding_prefix,
        )
        self._keyword_engine = FTS5SearchEngine(
            self._conn, table_name=self._fts_table,
        )

        # -- extractors --------------------------------------------------------
        self._structural_extractor = StructuralExtractor()
        self._keyterm_extractor = KeyTermExtractor()
        self._extraction_cache: ExtractionCache | None = None
        self._ner_extractor: NERExtractor | None = None
        if settings.extract_depth == ExtractDepth.NER:
            entity_types = settings.ner_entity_types or []
            self._extraction_cache = ExtractionCache(
                self._conn,
                settings.ner_model_name,
                entity_types,
                threshold=0.5,  # matches NERExtractor default threshold
            )
            # should_invalidate() reads sentinel BEFORE any write — correctly detects changes.
            if self._extraction_cache.should_invalidate():
                logger.info(
                    "NER model, entity_types, or threshold changed — clearing extraction_cache"
                )
                self._extraction_cache.clear()
            else:
                self._extraction_cache.update_model_sig()
            self._ner_extractor = NERExtractor(
                entity_types,
                model_name=settings.ner_model_name,
                threshold=0.5,
                extraction_cache=self._extraction_cache,
            )

        # Global embedding cache — keyed on (text_hash, model_name).
        # Survives file moves; invalidated automatically on embedding model change.
        self._embedding_cache = EmbeddingCache(self._conn, settings.embedding_model)
        if self._embedding_cache.should_invalidate():
            logger.info(
                "Embedding model changed — clearing embedding_cache"
            )
            self._embedding_cache.clear()
        else:
            self._embedding_cache.update_model_sentinel()

        # Startup integrity checks (order matters: schema wipe first, then weights)
        self._check_schema_version()   # Must run first (may wipe state)
        self._check_weights_changed()  # Runs after schema check (uses intact state)

    # ------------------------------------------------------------------
    # Search logging
    # ------------------------------------------------------------------

    _SEARCH_LOG_MAX_ROWS = 10_000

    def log_search(
        self,
        query: str,
        weights_used: dict[str, float],
        top_results: list[dict],
        *,
        mode: str = "hybrid",
        reranked: bool = False,
    ) -> None:
        """Log a search request to search_log for observability and future calibration.

        Writes one row per search. Trims oldest rows when count exceeds
        _SEARCH_LOG_MAX_ROWS (10,000) to bound table size (~3 MB max at ~300 bytes/row).

        Non-fatal: all errors are caught; search() never fails due to logging.

        Parameters
        ----------
        query:
            Raw search query string.
        weights_used:
            Current fusion weights dict, e.g. {"text": 0.7, "meta": 0.3}.
            Logs the PARSED effective weights (not the raw env var string).
        top_results:
            List of dicts with keys: chunk_id (str), score (float), engine (str).
            Top-k results after reranking. Chunk text is NOT stored (privacy + size).
        mode:
            Search mode used: 'hybrid', 'semantic', 'keyword', 'graph'. Default: 'hybrid'.
        reranked:
            Whether cross-encoder reranking was applied. Default: False.

        Concurrent write safety: shares self._conn with trickle indexer; both operate
        on index.db in WAL mode. The try/except handles any write failure gracefully.
        """
        import json
        try:
            now = datetime.now(timezone.utc).isoformat()
            self._conn.execute(
                "INSERT INTO search_log (query, timestamp, weights_used, top_results, mode, reranked) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    query,
                    now,
                    json.dumps(weights_used, sort_keys=True),
                    json.dumps(top_results),
                    mode,
                    int(reranked),
                ),
            )
            # Trim oldest rows if over cap — uses indexed id column for efficiency
            count = self._conn.execute(
                "SELECT COUNT(*) FROM search_log"
            ).fetchone()[0]
            if count > self._SEARCH_LOG_MAX_ROWS:
                excess = count - self._SEARCH_LOG_MAX_ROWS
                self._conn.execute(
                    "DELETE FROM search_log WHERE id IN ("
                    "  SELECT id FROM search_log ORDER BY id ASC LIMIT ?"
                    ")",
                    (excess,),
                )
            self._conn.commit()
        except Exception:
            logger.warning("search_log write failed — non-fatal", exc_info=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def index(self, directory: Path, *, force: bool = False) -> IndexStats:
        """Index markdown files under *directory*.

        By default, only new and modified files are processed
        (incremental mode).  Deleted files are purged from all stores.
        Unchanged files are skipped entirely.

        Parameters
        ----------
        directory:
            Root directory to scan for markdown files.
        force:
            When ``True``, clear all stores and fingerprints, then
            re-index every file from scratch.

        Returns
        -------
        IndexStats
            Summary statistics for the completed index.
        """
        run_id = uuid.uuid4().hex[:8]
        t_start = time.perf_counter()

        t0 = time.perf_counter()
        files = discover_files(directory)
        logger.info("[%s] discover: %d files in %s (%.2fs)", run_id, len(files), directory, time.perf_counter() - t0)
        data_dir_str = str(directory)

        if force:
            stats = self._full_index(files, data_dir=data_dir_str, run_id=run_id)
            logger.info("[%s] total: %.1fs (force)", run_id, time.perf_counter() - t_start)
            return stats

        t0 = time.perf_counter()
        diff = self._chunk_tracker.diff(files)
        logger.info(
            "[%s] chunk_diff: %d new, %d modified, %d deleted, %d unchanged (%.2fs)",
            run_id, len(diff.new), len(diff.modified), len(diff.deleted), len(diff.unchanged),
            time.perf_counter() - t0,
        )

        if not diff.new and not diff.modified and not diff.deleted:
            # No chunk-level changes.  Still check if embed-only work needed
            # (e.g. after a model switch, all files need re-embedding).
            embed_diff = self._meta_tracker.diff(files)
            embed_needed = set(embed_diff.new) | set(embed_diff.modified)
            if not embed_needed:
                logger.info("[%s] no changes — skipping (%.2fs total)", run_id, time.perf_counter() - t_start)
                stats = self._metadata_store.get_stats() or IndexStats()
                stats.new_files = 0
                stats.modified_files = 0
                stats.deleted_files = 0
                stats.unchanged_files = len(diff.unchanged)
                stats.data_dir = data_dir_str
                return stats

            # Embed-only: chunks unchanged, but embeddings needed.
            logger.info(
                "[%s] chunk_diff: no changes, but %d files need embedding",
                run_id, len(embed_needed),
            )
            embed_only_files = [fi for fi in files if str(fi.path) in embed_needed]
            self._embed_existing_chunks(embed_only_files, run_id=run_id)
            stats = self._metadata_store.get_stats() or IndexStats()
            stats.new_files = 0
            stats.modified_files = 0
            stats.deleted_files = 0
            stats.unchanged_files = len(diff.unchanged)
            stats.data_dir = data_dir_str
            logger.info("[%s] total: %.1fs (embed-only)", run_id, time.perf_counter() - t_start)
            return stats

        stats = self._incremental_index(files, diff, data_dir=data_dir_str, run_id=run_id)
        logger.info("[%s] total: %.1fs (incremental)", run_id, time.perf_counter() - t_start)
        return stats

    def clear(self) -> None:
        """Delete all data from every backing store.

        .. deprecated::
            Use :meth:`drop_vectors` or :meth:`drop_chunks` for granular
            cleanup.  This method is retained temporarily for backward
            compatibility and will be removed in Wave 3.
        """
        self._metadata_store.delete_all()  # also clears chunks_fts
        self._vector_store.delete_all()
        self._graph_store.delete_all()

        # Delete acronym dictionary
        if self._settings.acronyms_path.exists():
            self._settings.acronyms_path.unlink()

        logger.info("All stores cleared")

    def drop_vectors(self) -> None:
        """Drop vec tables + meta_fingerprints for current (strategy, model).

        Removes only the vector-layer data.  Chunks, FTS5, and graph remain
        intact so BM25 and graph search continue to work.
        """
        strategy = self._strategy
        model_suffix = self._model_suffix

        vec_table = f"vec_chunks_{strategy}{model_suffix}"
        meta_table = f"vec_meta_{strategy}{model_suffix}"
        config_table = f"vec_config_{strategy}{model_suffix}"
        meta_fp_table = f"meta_fingerprints_{strategy}{model_suffix}"
        vec_components_table = f"vec_components_{strategy}{model_suffix}"

        for table in (vec_table, meta_table, config_table):
            self._conn.execute(f"DROP TABLE IF EXISTS {table}")
        try:
            self._conn.execute(f"DELETE FROM {meta_fp_table}")
        except sqlite3.OperationalError:
            pass  # table may not exist yet
        try:
            self._conn.execute(f"DELETE FROM {vec_components_table}")
        except sqlite3.OperationalError:
            pass  # table may not exist yet
        self._conn.commit()

        # Re-ensure tables so the pipeline can immediately re-index.
        if hasattr(self._vector_store, "_tables_ensured"):
            del self._vector_store._tables_ensured

        logger.info(
            "Dropped vectors for strategy=%s model=%s",
            strategy, model_suffix.lstrip("_"),
        )

    def drop_chunks(self) -> None:
        """Drop chunks + FTS5 + graph + ALL vec for current strategy.

        This is a CASCADE operation: everything derived from chunks under
        the current strategy is removed, including vector tables for ALL
        embedding models.
        """
        strategy = self._strategy
        chunks_table = f"chunks_{strategy}"
        fts_table = f"chunks_fts_{strategy}"
        chunk_fp_table = f"chunk_fingerprints_{strategy}"

        # 1. Drop chunks and FTS5
        self._conn.execute(f"DROP TABLE IF EXISTS {chunks_table}")
        self._conn.execute(f"DROP TABLE IF EXISTS {fts_table}")

        # 2. Clear chunk fingerprints
        try:
            self._conn.execute(f"DELETE FROM {chunk_fp_table}")
        except sqlite3.OperationalError:
            pass  # table may not exist

        # 3. CASCADE: drop ALL vec_*_{strategy}_* and meta_fp_{strategy}_* tables.
        #    Discover tables via sqlite_master.
        prefix_vec = f"vec_chunks_{strategy}_"
        prefix_meta = f"vec_meta_{strategy}_"
        prefix_config = f"vec_config_{strategy}_"
        prefix_meta_fp = f"meta_fingerprints_{strategy}_"
        prefix_vec_components = f"vec_components_{strategy}_"
        # Also handle legacy embed_fingerprints tables if present.
        prefix_embed_fp = f"embed_fingerprints_{strategy}_"

        tables_dropped = 0
        rows = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        for (name,) in rows:
            if (
                name.startswith(prefix_vec)
                or name.startswith(prefix_meta)
                or name.startswith(prefix_config)
                or name.startswith(prefix_meta_fp)
                or name.startswith(prefix_vec_components)
                or name.startswith(prefix_embed_fp)
            ):
                self._conn.execute(f"DROP TABLE IF EXISTS {name}")
                tables_dropped += 1

        self._conn.commit()

        # 4. Delete graph for this strategy
        self._graph_store.delete_all()

        # 5. Delete acronym dictionary (derived from chunks)
        if self._settings.acronyms_path.exists():
            self._settings.acronyms_path.unlink()

        logger.info(
            "Dropped strategy %s: %d tables cascaded, graph cleared",
            strategy, tables_dropped,
        )

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    def _embed_chunks(
        self, chunks: list[Chunk],
    ) -> tuple[list[list[float]], dict[str, str]]:
        """Embed chunk body text, return (e_text_vectors, text_hashes).

        PURE: does not write to storage. Caller is responsible for storing
        e_text in VecComponentStore and committing.

        text_hash = hash(chunk.text only) — no title/tags prefix.
        Cross-strategy reuse: same chunk body in different strategies shares hash.

        Cache ordering (three layers, innermost → outermost):
          1. VecComponentStore get_batch(chunk_ids, 'text') — authoritative e_text source.
             chunk_id is stable across metadata-only changes; body changes cause chunk_tracker
             to re-chunk, assigning new chunk_ids, so stale e_text is never served.
          2. embedding_cache.lookup(text_hashes) — global cache keyed by content hash.
             Shared across strategies/models for same text content.
          3. TEI encode_batch — computed from scratch.

        NOTE: lookup_embeddings_by_text_hash() (sqlite_vec.py) is intentionally NOT used here.
        That method JOINs vec_meta with vec0; post-Phase 999.12 vec0 stores e_fused (not e_text).
        Using it here would return e_fused instead of e_text for shared-content chunks,
        causing double-fusion and silent search quality degradation. VecComponentStore
        is the correct authoritative source for e_text after Phase 999.12.

        Returns:
            e_text_vectors: list aligned with input chunks (no None values)
            text_hashes: {chunk_id: text_hash}
        """
        if not chunks:
            return [], {}

        # text_hash on raw chunk.text (no enrichment) — true cross-strategy reuse
        text_hashes: dict[str, str] = {
            c.chunk_id: blake3.blake3(c.text.encode()).hexdigest()
            for c in chunks
        }

        # Layer 1: VecComponentStore e_text BLOB lookup (authoritative source)
        # chunk_id is stable for unchanged body content, so this hit is always safe.
        component_hits = self._vec_components.get_batch(
            [c.chunk_id for c in chunks], "text"
        )

        # Layer 2: global embedding_cache (shared across strategies/models)
        # Only look up hashes not already found in VecComponentStore.
        missing_chunk_ids_for_cache = [
            c.chunk_id for c in chunks if c.chunk_id not in component_hits
        ]
        missing_hashes = list({
            text_hashes[cid] for cid in missing_chunk_ids_for_cache
        })
        global_hits: dict[str, list[float]] = {}
        if missing_hashes:
            global_hits = self._embedding_cache.lookup(missing_hashes)

        hits = 0
        to_encode_indices: list[int] = []
        embeddings: list[list[float]] = []

        for i, chunk in enumerate(chunks):
            if chunk.chunk_id in component_hits:
                embeddings.append(component_hits[chunk.chunk_id])
                hits += 1
            else:
                th = text_hashes[chunk.chunk_id]
                if th in global_hits:
                    embeddings.append(global_hits[th])
                    hits += 1
                else:
                    embeddings.append([])  # placeholder; filled below
                    to_encode_indices.append(i)

        if to_encode_indices:
            texts_to_encode = [chunks[i].text for i in to_encode_indices]
            new_embeddings = self._semantic_engine.encode_batch(texts_to_encode)
            for j, idx in enumerate(to_encode_indices):
                embeddings[idx] = new_embeddings[j]
            # Store new embeddings in global cache (no VecComponentStore write here — caller does it)
            for j, idx in enumerate(to_encode_indices):
                th = text_hashes[chunks[idx].chunk_id]
                self._embedding_cache.store(th, new_embeddings[j])

        total = len(chunks)
        logger.info(
            "embed_text: %d chunks, %d hits (%.1f%%), %d computed",
            total, hits, hits / total * 100 if total else 0, len(to_encode_indices),
        )

        return embeddings, text_hashes

    # ------------------------------------------------------------------
    # Pure helpers: normalization, fusion, meta encoding
    # ------------------------------------------------------------------

    @staticmethod
    def _meta_entity_id(path: str | Path) -> str:
        """Return canonical entity_id for a file's meta component.

        ALL VecComponentStore store/get calls for the 'meta' component MUST use
        this helper — never raw str(path). This prevents silent normalization
        divergence between bulk run() and trickle index_file() paths, which would
        cause the metadata-only fast path to miss stored e_meta entries and fall
        back to full re-embed.

        Canonical form: absolute, symlink-resolved POSIX path string.
        Equivalent to str(pathlib.Path(path).resolve()).

        (Addresses Codex HIGH Cycle 3 concern: centralize meta entity_id generation
        so every GET call site uses the identical canonical form as the store call.)

        Call sites that MUST use this helper:
          - _embed_meta_component()         — stores meta component
          - _index_file_embed()             — reads meta component (fast path)
          - _save_and_embed_chunks()        — stores and reads meta component
          - _embed_existing_chunks()        — stores meta component (both sub-paths)
          - reindex_vectors()               — stores meta component
          - _check_weights_changed()        — reads meta component
          - run() bulk embed loop           — stores meta component
        """
        return str(Path(path).resolve())

    @staticmethod
    def _normalize_vector(v: list[float]) -> list[float]:
        """Normalize vector to unit length. Returns v unchanged if magnitude is 0."""
        import math
        mag = math.sqrt(sum(x * x for x in v))
        return [x / mag for x in v] if mag > 0.0 else list(v)

    def _fuse_vectors(
        self,
        e_text: list[float],
        e_meta: list[float],
        weights: dict[str, float],
    ) -> list[float]:
        """Compute e_fused = normalize(w_text*norm(e_text) + w_meta*norm(e_meta)).

        Pure local computation — no TEI calls. stdlib math only (no numpy).

        Raises ValueError if e_text and e_meta have different dimensions.
        Silent truncation would be data corruption: both vectors must come from
        the same TEI model with the same output dimension.
        (Addresses Codex MEDIUM review concern: raise on mismatch, do not truncate.)
        """
        if len(e_text) != len(e_meta):
            raise ValueError(
                f"_fuse_vectors: dimension mismatch — "
                f"e_text has {len(e_text)} dims, e_meta has {len(e_meta)} dims. "
                f"Both must come from the same TEI model."
            )
        w_text = weights.get("text", 0.7)
        w_meta = weights.get("meta", 0.3)
        nt = self._normalize_vector(e_text)
        nm = self._normalize_vector(e_meta)
        raw = [w_text * a + w_meta * b for a, b in zip(nt, nm)]
        return self._normalize_vector(raw)

    def _embed_meta_component(self, file_info: FileInfo) -> list[float]:
        """Encode title+tags for a file into e_meta. 1 TEI call per file.

        Does NOT commit. Caller is transaction-owner.
        Stores result in VecComponentStore keyed by (_meta_entity_id(file_info.path), 'meta').

        Entity_id always obtained via _meta_entity_id() — the single canonical path
        normalizer. Never call str(Path(...).resolve()) directly at a store/get site.
        (Addresses Codex HIGH Cycle 3 concern: centralize meta entity_id generation.)
        """
        title = file_info.frontmatter.get("title", "") if file_info.frontmatter else ""
        tags = file_info.frontmatter.get("tags", []) if file_info.frontmatter else []
        tags = tags or []
        tags_str = ", ".join(str(t) for t in tags) if tags else ""
        meta_text = f"{title} {tags_str}".strip() or str(title) or ""
        result = self._semantic_engine.encode_batch([meta_text])
        e_meta = result[0]
        # Use _meta_entity_id() — the single canonical path normalizer for meta component
        self._vec_components.store(self._meta_entity_id(file_info.path), "meta", e_meta)
        return e_meta

    def _index_file_embed(
        self,
        file_info: FileInfo,
        chunks: list[Chunk],
        *,
        body_changed: bool,
        metadata_changed: bool,
    ) -> None:
        """Embed, fuse, and store vectors for a file. Owns the full transaction.

        Call chain (trickle path):
          index_file(path)
            → _incremental_index(file_info)
                → if chunk_tracker fired: _ingest_and_finalize(file_info)
                                          then _index_file_embed(..., body_changed=True, metadata_changed=True)
                → elif meta_tracker fired: _index_file_embed(..., body_changed=False, metadata_changed=True)

        Call chain (bulk run() path):
          run() → _save_and_embed_chunks(file_info, chunks)
                → _index_file_embed(..., body_changed=True, metadata_changed=True)
          run() → _embed_existing_chunks(file_info, chunks, *, model_switch=True/False)
                → _index_file_embed(...) via internal routing (see _embed_existing_chunks)

        _index_file_embed() is the SINGLE transaction owner for embed→fuse→store.
        _ingest_and_finalize() owns chunking/FTS/graph — they are separate.
        (Addresses OpenCode HIGH-3 Cycle 3: call site was undefined.)

        Branching logic (three mutually exclusive paths):

        Case 1 — body changed (body_changed=True):
            Full path. Re-embed chunk bodies (e_text), embed metadata (e_meta),
            fuse all chunks, overwrite vec0. chunk_tracker fires this case.

        Case 2 — metadata only changed (body_changed=False, metadata_changed=True):
            Fast path. Read stored e_text BLOBs from VecComponentStore (no TEI for
            body). Embed metadata once (1 TEI call for e_meta). Fuse locally.
            Update vec0. If any e_text BLOBs are missing, fall back to full embed
            for the missing chunks.

        Case 3 — neither changed:
            Skip entirely. This method should not be called in this case (caller
            checks), but guards defensively.

        Transaction boundary: all writes (VecComponentStore, vec0, tracker) are
        wrapped in a single BEGIN...COMMIT block. TEI calls happen BEFORE the
        BEGIN so the transaction never holds a lock across network I/O.
        If any step fails, the transaction is rolled back and the error is re-raised
        so the caller can handle it (trickle marks the file as failed and retries).

        entity_id for meta component: always via self._meta_entity_id(file_info.path).
        """
        if not body_changed and not metadata_changed:
            logger.debug("_index_file_embed: no changes for %s — skipping", file_info.path)
            return

        # If caller passed no chunks, load from metadata store (metadata-only path)
        if not chunks:
            canonical = self._meta_entity_id(file_info.path)
            chunk_ids = self._metadata_store.get_chunk_ids_by_file(
                self._strategy, canonical
            )
            chunks = self._metadata_store.get_chunks(chunk_ids) if chunk_ids else []

        if not chunks:
            logger.debug("_index_file_embed: no chunks for %s", file_info.path)
            self._save_meta_fingerprint(file_info)
            return

        weights = self._settings.parsed_embedding_weights

        # ── COMPUTE VECTORS OUTSIDE TRANSACTION (TEI calls must not hold SQLite lock) ──
        # Two-phase design (addresses Codex HIGH Cycle 3: transaction scope):
        #   Phase 1 — compute all vectors (TEI calls, cache reads) outside any transaction
        #   Phase 2 — atomically write all state inside BEGIN...COMMIT
        # This prevents long-held write locks during network I/O.

        missing_chunk_ids: set[str] = set()
        e_text_map: dict[str, list[float]] = {}
        text_hashes: dict[str, str] = {}

        if body_changed:
            # Full path: encode chunk bodies + metadata
            e_text_vectors, text_hashes = self._embed_chunks(chunks)  # TEI outside tx
            e_meta = self._embed_meta_component(file_info)             # TEI outside tx
            e_fused_vectors = [
                self._fuse_vectors(e_t, e_meta, weights) for e_t in e_text_vectors
            ]
        else:
            # Metadata-only fast path: read cached e_text, encode only e_meta
            e_text_map = self._vec_components.get_batch(
                [c.chunk_id for c in chunks], "text"
            )
            missing_chunk_ids = {
                c.chunk_id for c in chunks if c.chunk_id not in e_text_map
            }
            if missing_chunk_ids:
                logger.warning(
                    "Metadata-only fast path for %s: %d/%d e_text BLOBs missing — "
                    "falling back to full embed for those chunks",
                    file_info.path, len(missing_chunk_ids), len(chunks),
                )
                missing_chunks = [c for c in chunks if c.chunk_id in missing_chunk_ids]
                missing_e_text, missing_hashes = self._embed_chunks(missing_chunks)  # TEI outside tx
                for chunk, e_text in zip(missing_chunks, missing_e_text):
                    e_text_map[chunk.chunk_id] = e_text
                text_hashes = missing_hashes
            e_meta = self._embed_meta_component(file_info)  # exactly 1 TEI call outside tx
            e_fused_vectors = [
                self._fuse_vectors(e_text_map[c.chunk_id], e_meta, weights) for c in chunks
            ]

        # ── WRITE PHASE ───────────────────────────────────────────────────────────────
        # Each store call owns its own commit. Cross-store atomicity is not achievable
        # here because SQLiteVecVectorStore.add_chunks() commits internally — wrapping
        # it in an explicit BEGIN/COMMIT causes "cannot commit - no transaction active".
        # Acceptable: trickle re-indexes the file on next run if a crash occurs mid-write.
        if body_changed:
            # Store e_text components for all chunks
            for chunk, e_text in zip(chunks, e_text_vectors):
                self._vec_components.store(chunk.chunk_id, "text", e_text)
        else:
            # Store only newly-computed fallback e_text for missing chunks
            if missing_chunk_ids:
                for chunk in chunks:
                    if chunk.chunk_id in missing_chunk_ids:
                        self._vec_components.store(
                            chunk.chunk_id, "text", e_text_map[chunk.chunk_id]
                        )

        # Store e_meta component (canonical path via _meta_entity_id)
        self._vec_components.store(
            self._meta_entity_id(file_info.path), "meta", e_meta
        )
        # Write e_fused to vec0 (add_chunks commits internally)
        self._vector_store.add_chunks(
            chunks, e_fused_vectors, overwrite=True,
            text_hashes=text_hashes if text_hashes else None,
        )
        # Save meta fingerprint
        self._save_meta_fingerprint(file_info)

        if body_changed:
            logger.info(
                "Full embed for %s: %d chunks, e_text + e_meta encoded",
                file_info.path, len(chunks),
            )
        else:
            logger.info(
                "Metadata-only fast path for %s: 1 TEI call (e_meta), "
                "%d fused vectors recomputed locally (weights=%s)",
                file_info.path, len(chunks), weights,
            )

    # ------------------------------------------------------------------
    # Granular reindex (rebuild one store from metadata chunks)
    # ------------------------------------------------------------------

    def reindex_vectors(self) -> int:
        """Rebuild vector store from stored chunks. Returns chunk count.

        Groups chunks by file (for e_meta computation), then for each file:
        embeds chunks (e_text), encodes metadata (e_meta, batched), fuses, stores.
        Uses _meta_entity_id() for canonical path normalization throughout.
        """
        # Discover all distinct file paths from M2M table
        m2m_table = f"chunk_file_paths_{self._strategy}"
        try:
            rows = self._conn.execute(
                f"SELECT DISTINCT file_path FROM {m2m_table}"
            ).fetchall()
            all_file_paths = [row[0] for row in rows]
        except Exception:
            logger.warning("reindex_vectors: cannot read M2M table — falling back to no files")
            all_file_paths = []

        if not all_file_paths:
            logger.info("reindex_vectors: no file paths in metadata")
            return 0

        # Wipe vector state before rebuild
        self._vector_store.delete_all()
        self._vec_components.delete_all()

        # Build FileInfo for all files (read frontmatter from disk)
        file_infos: list[FileInfo] = []
        for fp in all_file_paths:
            try:
                content = read_file(Path(fp))
                fm, _ = parse_frontmatter(content)
            except Exception:
                fm = {}
            file_infos.append(FileInfo(path=Path(fp), frontmatter=fm))

        # Batch encode e_meta for ALL files in a single TEI call (1 batch for all metadata)
        weights = self._settings.parsed_embedding_weights
        meta_texts: list[str] = []
        for fi in file_infos:
            title = str(fi.frontmatter.get("title", "") or "") if fi.frontmatter else ""
            tags = (fi.frontmatter.get("tags", []) or []) if fi.frontmatter else []
            tags_str = ", ".join(str(t) for t in tags) if tags else ""
            meta_texts.append(f"{title} {tags_str}".strip() or title or "")

        e_meta_all = self._semantic_engine.encode_batch(meta_texts)

        total = 0
        for fi, e_meta in zip(file_infos, e_meta_all):
            canonical_path = self._meta_entity_id(fi.path)
            self._vec_components.store(canonical_path, "meta", e_meta)
            chunk_ids = self._metadata_store.get_chunk_ids_by_file(
                self._strategy, canonical_path
            ) or []
            chunks = self._metadata_store.get_chunks(chunk_ids) if chunk_ids else []
            if not chunks:
                continue
            e_text_vectors, text_hashes = self._embed_chunks(chunks)
            for chunk, e_text in zip(chunks, e_text_vectors):
                self._vec_components.store(chunk.chunk_id, "text", e_text)
            e_fused = [
                self._fuse_vectors(e_t, e_meta, weights) for e_t in e_text_vectors
            ]
            self._vector_store.add_chunks(
                chunks, e_fused, overwrite=True, text_hashes=text_hashes
            )
            total += len(chunks)

        self._conn.commit()
        if hasattr(self._vector_store, "set_model_name"):
            model_id = self._semantic_engine.get_tei_model_id() or self._settings.embedding_model
            self._vector_store.set_model_name(model_id)  # type: ignore[attr-defined]
            self._vector_store.set_distance_metric("cosine")  # type: ignore[attr-defined]
        logger.info(
            "reindex_vectors: rebuilt %d chunks from %d files", total, len(file_infos)
        )
        return total

    def reindex_fts5(self) -> int:
        """Rebuild FTS5 keyword index from stored chunks. Returns chunk count."""
        all_chunks = self._metadata_store.get_all_chunks()
        if not all_chunks:
            logger.info("reindex_fts5: no chunks in metadata")
            return 0
        self._conn.execute(f"DELETE FROM {self._fts_table}")
        self._conn.commit()
        file_meta = self._build_file_meta(all_chunks)
        self._keyword_engine.add_chunks(all_chunks, file_meta=file_meta)
        logger.info("reindex_fts5: %d chunks re-indexed", len(all_chunks))
        return len(all_chunks)

    def reindex_graph(self) -> int:
        """Rebuild knowledge graph from stored chunks. Returns chunk count."""
        all_chunks = self._metadata_store.get_all_chunks()
        if not all_chunks:
            logger.info("reindex_graph: no chunks in metadata")
            return 0
        self._graph_store.delete_all()

        # File nodes — read frontmatter for proper title (not just filename)
        # Phase 16: Chunk has file_paths list; collect all unique paths across all chunks.
        for fp in sorted({str(p) for c in all_chunks for p in c.file_paths}):
            title = Path(fp).stem
            try:
                content = read_file(Path(fp))
                frontmatter, _ = parse_frontmatter(content)
                title = frontmatter.get("title", title)
            except OSError:
                pass
            self._graph_store.add_file_node(
                file_path=fp, title=str(title),
            )

        # Section nodes + CONTAINS edges
        # Phase 16: chunk may have multiple file_paths; use first for graph node.
        for chunk in all_chunks:
            _primary_fp = str(chunk.file_paths[0]) if chunk.file_paths else ""
            self._graph_store.add_section_node(
                chunk_id=chunk.chunk_id,
                heading=chunk.heading,
                level=chunk.level,
                file_path=_primary_fp,
                text_preview=chunk.text[:200],
            )
            self._graph_store.add_edge(
                source_id=_primary_fp,
                target_id=chunk.chunk_id,
                relation_type=RelationType.CONTAINS,
            )

        # Extraction + entity/relation nodes and edges
        extraction = self._run_extraction(all_chunks)
        for entity in extraction.entities:
            if entity.type == "tag":
                self._graph_store.add_tag_node(entity.name)
            else:
                self._graph_store.add_entity_node(
                    name=entity.name, entity_type=entity.type, source=entity.source,
                )
        for relation in extraction.relations:
            self._graph_store.add_edge(
                source_id=relation.source_id,
                target_id=relation.target_id,
                relation_type=relation.relation_type,
                weight=relation.weight,
            )

        logger.info(
            "reindex_graph: %d chunks, %d entities, %d relations",
            len(all_chunks), extraction.total_entities, extraction.total_relations,
        )
        return len(all_chunks)

    # ------------------------------------------------------------------
    # Indexing strategies
    # ------------------------------------------------------------------

    def _full_index(
        self, files: list[FileInfo], *, data_dir: str | None = None, run_id: str = "",
    ) -> IndexStats:
        """Process all files from scratch (used for force=True).

        Drops vectors and clears fingerprints, then re-processes everything.
        FTS5 is cleared before re-insert to prevent duplicates (INSERT OR
        REPLACE handles it, but explicit DELETE is a safety net).
        """
        self.drop_vectors()
        self._chunk_tracker.clear()
        self._meta_tracker.clear()
        # Clear FTS5 content before re-indexing (safety net against duplicates).
        try:
            self._conn.execute(f"DELETE FROM {self._fts_table}")
            self._conn.commit()
        except sqlite3.OperationalError:
            pass  # FTS5 table may not exist yet
        return self._ingest_and_finalize(
            files, list(files),
            diff_counts={"new": len(files), "modified": 0, "deleted": 0, "unchanged": 0},
            data_dir=data_dir, run_id=run_id,
        )

    def _incremental_index(
        self, all_files: list[FileInfo], diff: FileDiff,
        *, data_dir: str | None = None, run_id: str = "",
    ) -> IndexStats:
        """Process only changed files (chunk_diff driven)."""
        # 1. Purge deleted files
        t0 = time.perf_counter()
        for path_str in diff.deleted:
            self._purge_file(path_str)
        if diff.deleted:
            logger.info("[%s] purge_deleted: %d files (%.2fs)", run_id, len(diff.deleted), time.perf_counter() - t0)

        # 2. Purge modified files (data only, fingerprint updated after re-ingest)
        t0 = time.perf_counter()
        for path_str in diff.modified:
            self._purge_file(path_str)
        if diff.modified:
            logger.info("[%s] purge_modified: %d files (%.2fs)", run_id, len(diff.modified), time.perf_counter() - t0)

        # 3. Determine files to ingest (new + modified in chunk_diff)
        changed_paths = set(diff.new) | set(diff.modified)
        files_to_ingest = [fi for fi in all_files if str(fi.path) in changed_paths]

        # 4. Check embed_diff for files unchanged in chunk_diff.
        #    These files already have chunks but may need embedding
        #    (e.g. after a model switch).
        unchanged_files = [fi for fi in all_files if str(fi.path) not in changed_paths and str(fi.path) not in set(diff.deleted)]
        embed_only_files: list[FileInfo] = []
        if unchanged_files:
            embed_diff = self._meta_tracker.diff(unchanged_files)
            embed_needed = set(embed_diff.new) | set(embed_diff.modified)
            if embed_needed:
                embed_only_files = [fi for fi in unchanged_files if str(fi.path) in embed_needed]
                logger.info(
                    "[%s] embed_diff: %d files need embedding (unchanged chunks)",
                    run_id, len(embed_only_files),
                )

        # 5. Ingest changed files + finalize (includes embed-only pass)
        return self._ingest_and_finalize(
            all_files, files_to_ingest,
            embed_only_files=embed_only_files,
            overwrite_vectors=False,
            diff_counts={
                "new": len(diff.new),
                "modified": len(diff.modified),
                "deleted": len(diff.deleted),
                "unchanged": len(diff.unchanged),
            },
            data_dir=data_dir, run_id=run_id,
        )

    # ------------------------------------------------------------------
    # Core ingestion + finalization
    # ------------------------------------------------------------------

    def _ingest_and_finalize(
        self,
        all_files: list[FileInfo],
        files_to_ingest: list[FileInfo],
        *,
        embed_only_files: list[FileInfo] | None = None,
        overwrite_vectors: bool = True,
        diff_counts: dict[str, int] | None = None,
        data_dir: str | None = None,
        run_id: str = "",
    ) -> IndexStats:
        """Ingest *files_to_ingest* and rebuild FTS5/stats from full corpus.

        Parameters
        ----------
        embed_only_files:
            Files whose chunks are already stored but need embedding
            (e.g. after a model switch).  Only the embed phase runs
            for these files.
        """
        new_chunks = self._chunk_files(files_to_ingest, run_id)

        if new_chunks:
            self._save_and_embed_chunks(
                new_chunks, files_to_ingest,
                overwrite_vectors=overwrite_vectors, run_id=run_id,
            )

        extraction_result = self._extract_and_populate_graph(
            files_to_ingest, new_chunks, run_id,
        )

        self._save_all_fingerprints(files_to_ingest, run_id)

        if embed_only_files:
            t0 = time.perf_counter()
            self._embed_existing_chunks(embed_only_files, run_id=run_id)
            logger.info("[%s] embed_only: %d files (%.1fs)", run_id, len(embed_only_files), time.perf_counter() - t0)

        all_chunks = self._rebuild_acronyms(run_id)

        return self._compute_stats(
            all_files, all_chunks, extraction_result,
            overwrite_vectors=overwrite_vectors,
            diff_counts=diff_counts, data_dir=data_dir,
        )

    # ------------------------------------------------------------------
    # Ingest sub-phases (extracted from _ingest_and_finalize)
    # ------------------------------------------------------------------

    def _chunk_files(
        self, files: list[FileInfo], run_id: str,
    ) -> list[Chunk]:
        """Read and chunk files into Chunk objects."""
        t0 = time.perf_counter()
        chunks: list[Chunk] = []
        for fi in files:
            content = read_file(fi.path)
            chunks.extend(_chunker_module.chunk_file(
                fi.path, content,
                max_tokens=self._settings.max_chunk_tokens,
                overlap_tokens=self._settings.chunk_overlap_tokens,
                kind=fi.kind,
                chunk_strategy=self._strategy,
            ))
        logger.info("[%s] chunk: %d chunks from %d files (%.2fs)", run_id, len(chunks), len(files), time.perf_counter() - t0)
        return chunks

    def _save_and_embed_chunks(
        self,
        chunks: list[Chunk],
        files: list[FileInfo],
        *,
        overwrite_vectors: bool = True,
        run_id: str = "",
    ) -> None:
        """Save chunks to metadata, embed, fuse with file metadata, store vectors, update FTS5.

        Updated in Phase 999.12: now computes separate e_text (per chunk) and
        e_meta (per file), fuses locally, writes e_fused to vec0.

        Chunk-to-file grouping (addresses OpenCode HIGH-1 Cycle 3):
        The M2M schema allows one chunk to appear in multiple files. For fusion,
        each chunk uses the e_meta of the FileInfo that owns it in this indexing
        run (keyed by chunk.file_paths[0] matching a file's path). When a chunk
        is shared across files, the LAST file's e_meta to write to vec0 wins
        (last-write-wins — pre-existing M2M constraint, not a regression of 999.12).

        M2M shared-chunk behavior (documented per both reviewers, Cycle 3):
        If the same chunk_id appears in multiple files (same body text, different
        titles), the chunk gets one row in vec0 with e_fused computed from the
        LAST file's e_meta that writes to it (last-write-wins). This is a known
        pre-existing design constraint of the M2M content-addressed schema.
        """
        t0 = time.perf_counter()
        self._metadata_store.save_chunks(chunks)
        logger.info("[%s] metadata_save: %d chunks (%.2fs)", run_id, len(chunks), time.perf_counter() - t0)

        weights = self._settings.parsed_embedding_weights

        # Build file_path → FileInfo index for chunk grouping
        fi_by_path: dict[str, FileInfo] = {str(fi.path): fi for fi in files}

        # Group chunks by their primary file path (file_paths[0])
        # Chunks with no file_paths are assigned to the first available file.
        from collections import defaultdict
        chunks_by_file: dict[str, list[Chunk]] = defaultdict(list)
        fallback_path = str(files[0].path) if files else ""
        for chunk in chunks:
            fp = str(chunk.file_paths[0]) if chunk.file_paths else fallback_path
            chunks_by_file[fp].append(chunk)

        t0 = time.perf_counter()
        all_e_fused: list[list[float]] = []
        all_text_hashes: dict[str, str] = {}
        chunk_order: list[Chunk] = []

        for fp, file_chunks in chunks_by_file.items():
            fi = fi_by_path.get(fp) or (files[0] if files else None)
            if fi is None:
                continue
            # Embed chunk bodies (pure, no storage)
            e_text_vectors, text_hashes = self._embed_chunks(file_chunks)
            # Store e_text in VecComponentStore for future fast-path reads
            for chunk, e_text in zip(file_chunks, e_text_vectors):
                self._vec_components.store(chunk.chunk_id, "text", e_text)
            # Encode file metadata → e_meta (1 TEI call per unique file)
            e_meta = self._embed_meta_component(fi)
            # Fuse per chunk
            e_fused = [
                self._fuse_vectors(e_t, e_meta, weights) for e_t in e_text_vectors
            ]
            all_e_fused.extend(e_fused)
            all_text_hashes.update(text_hashes)
            chunk_order.extend(file_chunks)

        t_embed = time.perf_counter() - t0
        logger.info(
            "[%s] embed: %d chunks (%.1fs, %.0f chunks/s)",
            run_id, len(chunks), t_embed, len(chunks) / t_embed if t_embed > 0 else 0,
        )

        t0 = time.perf_counter()
        self._vector_store.add_chunks(
            chunk_order, all_e_fused, overwrite=overwrite_vectors,
            text_hashes=all_text_hashes,
        )
        logger.info("[%s] vector_store: %d vectors (%.2fs)", run_id, len(chunks), time.perf_counter() - t0)
        if hasattr(self._vector_store, "set_model_name"):
            self._vector_store.set_model_name(self._settings.embedding_model)  # type: ignore[attr-defined]

        t0 = time.perf_counter()
        file_meta = self._build_file_meta_from_fileinfo(files)
        self._keyword_engine.add_chunks(chunks, file_meta=file_meta)
        logger.info("[%s] fts5: %d chunks (%.2fs)", run_id, len(chunks), time.perf_counter() - t0)

    def _build_file_meta_from_fileinfo(
        self, files: list[FileInfo],
    ) -> dict[str, tuple[str, str]]:
        """Build FTS5 file_meta from FileInfo objects (no disk reads needed)."""
        file_meta: dict[str, tuple[str, str]] = {}
        for fi in files:
            tags = fi.frontmatter.get("tags", [])
            tags_str = ", ".join(str(t) for t in tags) if tags else ""
            file_meta[str(fi.path)] = (fi.title, tags_str)
        return file_meta

    def _extract_and_populate_graph(
        self,
        files: list[FileInfo],
        chunks: list[Chunk],
        run_id: str,
    ) -> _ExtractionBundle:
        """Run NER/structural extraction and populate graph."""
        t0 = time.perf_counter()
        result = self._run_extraction(chunks)
        logger.info("[%s] extraction: %d entities, %d relations (%.1fs)", run_id, result.total_entities, result.total_relations, time.perf_counter() - t0)

        t0 = time.perf_counter()
        self._populate_graph(files, chunks, result)
        self._frontmatter_to_graph(files)
        logger.info("[%s] graph: %d files, %d chunks (%.1fs)", run_id, len(files), len(chunks), time.perf_counter() - t0)
        return result

    def _save_all_fingerprints(
        self, files: list[FileInfo], run_id: str,
    ) -> None:
        """Save chunk + meta fingerprints after successful ingestion."""
        t0 = time.perf_counter()
        self._update_chunk_fingerprints(files)
        self._update_meta_fingerprints(files)
        logger.info("[%s] fingerprints: %d files (%.2fs)", run_id, len(files), time.perf_counter() - t0)

    def _rebuild_acronyms(self, run_id: str) -> list[Chunk]:
        """Rebuild acronym dictionary from full corpus. Returns all chunks."""
        t0 = time.perf_counter()
        all_chunks = self._metadata_store.get_all_chunks()
        acronym_dict = extract_acronyms_from_chunks(all_chunks)
        if acronym_dict:
            import json
            import tempfile

            self._settings.acronyms_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                dir=self._settings.acronyms_path.parent, suffix=".tmp",
            )
            try:
                with open(fd, "w") as f:
                    json.dump(acronym_dict, f, indent=2)
                Path(tmp_path).replace(self._settings.acronyms_path)
            except BaseException:
                Path(tmp_path).unlink(missing_ok=True)
                raise
        logger.info("[%s] acronyms: %d (%.2fs)", run_id, len(acronym_dict) if acronym_dict else 0, time.perf_counter() - t0)
        return all_chunks

    def _compute_stats(
        self,
        all_files: list[FileInfo],
        all_chunks: list[Chunk],
        extraction_result: _ExtractionBundle,
        *,
        overwrite_vectors: bool = True,
        diff_counts: dict[str, int] | None = None,
        data_dir: str | None = None,
    ) -> IndexStats:
        """Build and persist IndexStats from current state."""
        all_entities_count = extraction_result.total_entities
        all_edges_count = extraction_result.total_relations
        if not overwrite_vectors:
            try:
                all_entities_count = self._graph_store.node_count()
                all_edges_count = self._graph_store.edge_count()
            except Exception:
                logger.warning("Failed to fetch graph counts for stats", exc_info=True)

        _dc = diff_counts or {}
        stats = IndexStats(
            total_files=len(all_files),
            total_chunks=len(all_chunks),
            total_entities=all_entities_count,
            total_edges=all_edges_count,
            last_indexed=datetime.now(tz=timezone.utc),
            new_files=_dc.get("new", 0),
            modified_files=_dc.get("modified", 0),
            deleted_files=_dc.get("deleted", 0),
            unchanged_files=_dc.get("unchanged", 0),
            data_dir=data_dir,
        )
        self._metadata_store.save_stats(stats)
        return stats

    # ------------------------------------------------------------------
    # Single-file indexing (used by trickle indexer)
    # ------------------------------------------------------------------

    def index_file(self, file_info: FileInfo | Path) -> int:
        """Index a single file through the two-phase pipeline.

        Phase 1 (chunk): check chunk_tracker, re-chunk if needed, write
        chunks via M2M INSERT OR IGNORE path, save chunk fingerprint.
        Phase 2 (embed): check embed_tracker, text_hash lookup, encode
        misses, save embed fingerprint.

        Used by the trickle indexer for one-at-a-time background processing.

        Accepts either a ``FileInfo`` or a plain ``Path`` — when a ``Path`` is
        given, a minimal ``FileInfo`` is constructed from the file's stat.

        Returns the number of chunks created/updated.
        """
        # Normalise: accept bare Path for test convenience.
        if isinstance(file_info, Path):
            _p = file_info
            try:
                _stat = _p.stat()
            except OSError:
                logger.warning("index_file: cannot stat %s — skipping", _p)
                return 0
            try:
                _raw = read_file(_p)
                _fm, _ = parse_frontmatter(_raw)
            except OSError:
                _fm = {}
            from dotmd.core.models import DocKind
            _kind = _fm.get("kind", DocKind.DOCUMENT)
            file_info = FileInfo(
                path=_p,
                title=str(_fm.get("title", _p.stem)),
                last_modified=datetime.fromtimestamp(_stat.st_mtime, tz=timezone.utc),
                size_bytes=_stat.st_size,
                frontmatter=_fm,
                kind=_kind,
            )

        path_str = str(file_info.path)
        needs_embed = False
        prof = self._settings.profile_indexing  # gate: DOTMD_PROFILE_INDEXING=true

        # Phase beacon: write current phase to a file so external monitors
        # (docker stats samplers) can correlate CPU/IO with pipeline phase
        # in real time, not from post-hoc log parsing.
        _beacon_path = self._settings.index_dir / ".phase_beacon"
        def _beacon(phase: str) -> None:
            if prof:
                _beacon_path.write_text(f"{file_info.path}:{phase}")

        # Timing accumulators — always defined so the DONE summary can reference
        # them unconditionally regardless of which code paths were taken.
        t_file = time.perf_counter()
        t_purge = t_chunk = t_save = t_extract = t_graph = t_embed = t_vec = 0.0

        # --- Phase 1: Chunk ---
        chunk_diff = self._chunk_tracker.diff([file_info])
        if path_str in chunk_diff.new or path_str in chunk_diff.modified:
            # Holder-aware pre-purge: decrement M2M for this file, then
            # cascade-delete only chunks whose holder count dropped to 0.
            # Shared chunks (still referenced by another file) are left intact
            # in chunks_*, FTS5, and vec_meta.
            t0 = time.perf_counter()
            _beacon("purge")
            cleanup_orphans_by_strategy: dict[str, list[str]] = {}
            try:
                self._conn.execute("BEGIN")
                cleanup_orphans_by_strategy = self._holder_aware_chunk_cleanup(
                    path_str, conn=self._conn
                )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            # Post-commit graph cleanup: holder-aware path (branch b).
            # Only orphan chunk_ids are removed from the graph; the File node
            # is NOT deleted here because the file is being re-indexed (it will
            # be re-populated in the graph phase below).
            _cleanup_orphan_ids: list[str] = [
                cid
                for orphans in cleanup_orphans_by_strategy.values()
                for cid in orphans
            ]
            if _cleanup_orphan_ids:
                try:
                    self._graph_store.delete_chunks_from_graph(_cleanup_orphan_ids)
                except AttributeError:
                    # Graph store lacks narrow helper (e.g. LadybugDB) — fall
                    # back to broad subgraph delete.  The graph will be
                    # re-populated in the graph phase below.
                    try:
                        self._graph_store.delete_file_subgraph(path_str)
                    except Exception as _ge:  # noqa: BLE001
                        logger.warning(
                            "graph cleanup (fallback) failed during reindex: %s (file=%s)",
                            _ge, path_str,
                        )
                except Exception as _ge:  # noqa: BLE001
                    logger.warning(
                        "graph chunk cleanup failed during reindex: %s (file=%s)",
                        _ge, path_str,
                    )
            t_purge = time.perf_counter() - t0

            _beacon("chunk")
            t0 = time.perf_counter()
            content = read_file(file_info.path)
            chunks = _chunker_module.chunk_file(
                file_info.path,
                content,
                max_tokens=self._settings.max_chunk_tokens,
                overlap_tokens=self._settings.chunk_overlap_tokens,
                kind=file_info.kind,
                chunk_strategy=self._strategy,
            )
            t_chunk = time.perf_counter() - t0

            if not chunks:
                self._save_chunk_fingerprint(file_info)
                return 0

            t0 = time.perf_counter()
            _beacon("save+fts5")
            # Phase 16 M2M write path: INSERT OR IGNORE on chunks_* + M2M.
            # For each chunk, check payload consistency on conflict (Review-HIGH-P3).
            # Wrap the full per-file write loop in a single transaction so that
            # insert_chunk and add_file_path are atomic: a crash between the two
            # cannot leave a chunks_* row without a chunk_file_paths_* entry.
            self._metadata_store.ensure_m2m_table(self._strategy)
            self._conn.execute("BEGIN")
            try:
                for c in chunks:
                    existing = self._metadata_store.get_stored_payload(
                        self._strategy, c.chunk_id
                    )
                    if existing is not None:
                        # Content-addressed id: same id => same content.
                        # If the stored payload disagrees this is a chunker bug or
                        # a real hash collision — WARN and keep first-writer's row.
                        diverged: list[str] = []
                        if existing["text"] != c.text:
                            diverged.append("text")
                        if existing["heading_hierarchy"] != c.heading_hierarchy:
                            diverged.append("heading_hierarchy")
                        if existing["level"] != c.level:
                            diverged.append("level")
                        if diverged:
                            logger.warning(
                                "ingest_payload_mismatch chunk_id=%s file=%s diverged_fields=%s",
                                c.chunk_id,
                                path_str,
                                diverged,
                            )
                        # Fall through to INSERT OR IGNORE — first-writer's row wins.
                    self._metadata_store.insert_chunk(
                        self._strategy,
                        c.chunk_id,
                        c.heading_hierarchy,
                        c.level,
                        c.text,
                        _commit=False,
                    )
                    self._metadata_store.add_file_path(
                        self._strategy,
                        c.chunk_id,
                        path_str,
                        c.chunk_index,
                        _commit=False,
                    )
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

            # FTS5: INSERT OR REPLACE is idempotent on chunk_id (Research §Component).
            _trickle_tags = file_info.frontmatter.get("tags", [])
            _trickle_tags_csv = ", ".join(str(t) for t in _trickle_tags) if _trickle_tags else ""
            _trickle_meta = {str(file_info.path): (file_info.title, _trickle_tags_csv)}
            self._keyword_engine.add_chunks(chunks, file_meta=_trickle_meta)
            t_save = time.perf_counter() - t0

            _beacon("extraction")
            t0 = time.perf_counter()
            extraction = self._run_extraction(chunks)
            t_extract = time.perf_counter() - t0

            _beacon("graph")
            t0 = time.perf_counter()
            self._populate_graph([file_info], chunks, extraction)
            self._frontmatter_to_graph([file_info])
            t_graph = time.perf_counter() - t0

            self._save_chunk_fingerprint(file_info)
            needs_embed = True
        else:
            chunks = []

        # --- Phase 2: Embed + metadata refresh ---
        # ADR: meta_tracker uses meta_checksum (title+tags only).
        # When only title/tags changed (chunk_diff=unchanged, meta_diff=modified),
        # we skip re-chunking but still re-embed (1 TEI call for e_meta), update
        # FTS5 columns, and refresh graph metadata.
        metadata_only = False
        if not needs_embed:
            meta_diff = self._meta_tracker.diff([file_info])
            needs_embed = (
                path_str in meta_diff.new or path_str in meta_diff.modified
            )
            metadata_only = needs_embed

        if needs_embed:
            _beacon("embed")
            t0 = time.perf_counter()
            # _index_file_embed owns the full embed→fuse→store transaction.
            # body_changed=True when chunk_tracker fired (needs_embed set from chunking).
            # body_changed=False when only meta_tracker fired (metadata_only path).
            self._index_file_embed(
                file_info,
                chunks,
                body_changed=not metadata_only,
                metadata_changed=needs_embed,
            )
            t_embed = time.perf_counter() - t0

            if metadata_only:
                file_meta = self._build_file_meta_from_fileinfo([file_info])
                self._keyword_engine.add_chunks(
                    self._metadata_store.get_chunks(
                        self._metadata_store.get_chunk_ids_by_file(
                            self._strategy, path_str
                        ) or []
                    ) if not chunks else chunks,
                    file_meta=file_meta,
                )
                self._frontmatter_to_graph([file_info])

            _beacon("fingerprint")

        _beacon("idle")
        t_total = time.perf_counter() - t_file
        logger.info(
            "pipeline: %s DONE %d chunks %.1fs"
            " (chunk %.2f / save %.2f / extract %.2f / graph %.2f / embed %.2f / vec %.2f)",
            file_info.path.name,
            len(chunks) if chunks else 0,
            t_total,
            t_chunk, t_save, t_extract, t_graph, t_embed, t_vec,
        )

        return len(chunks) if chunks else 0

    # ------------------------------------------------------------------
    # Per-file purge
    # ------------------------------------------------------------------

    def _present_strategies(self, conn: sqlite3.Connection) -> list[str]:
        """Return strategy names that have a chunk_file_paths_* M2M table in the DB.

        Uses the M2M table presence (not chunks_*) so strategy switches don't
        leak: a strategy whose chunks_* was dropped but whose M2M table still
        has rows is still discovered and cleaned up.
        """
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name LIKE 'chunk_file_paths_%'"
        ).fetchall()
        return [r[0].removeprefix("chunk_file_paths_") for r in rows]

    def _holder_aware_chunk_cleanup(
        self,
        file_path: str,
        *,
        conn: sqlite3.Connection,
    ) -> dict[str, list[str]]:
        """Decrement M2M for *file_path* across all strategies, cascade-delete
        only chunk_ids whose holder count reached 0.

        This is the single shared primitive for both ``_purge_file`` and
        ``_index_file``.  It covers the four in-transaction DB-level deletes:
        M2M rows → orphan chunks_* rows → vec_meta_* rows → FTS5 rows.

        **Transaction boundary:** MUST be called inside a caller-managed
        BEGIN/COMMIT block.  This method issues no COMMIT of its own.

        **Strategies covered:** all strategies that have a
        ``chunk_file_paths_*`` M2M table in the DB at call time (discovered
        via ``_present_strategies``).  For ``_index_file`` this is typically
        one strategy; for ``_purge_file`` it covers all strategies atomically.

        Parameters
        ----------
        file_path:
            The file whose M2M associations should be decremented.
        conn:
            The open SQLite connection carrying the active transaction.

        Returns
        -------
        dict[str, list[str]]
            Mapping of ``strategy → [orphan_chunk_ids]``.  Orphans are
            chunk_ids whose holder count dropped to 0 and were cascade-deleted
            from the DB tables.  The caller uses this for post-commit external
            cleanup (graph nodes, fingerprints).
        """
        all_orphans_by_strategy: dict[str, list[str]] = {}
        for strategy in self._present_strategies(conn):
            orphans = self._metadata_store.delete_m2m_for_file(
                strategy, file_path, conn=conn
            )
            if orphans:
                self._metadata_store.delete_orphan_chunks(
                    strategy, orphans, conn=conn
                )
                self._vector_store.delete_by_chunk_ids(
                    strategy, orphans, conn=conn
                )
                # FTS5 cascade — runs inside the same transaction.
                fts_table = f"chunks_fts_{strategy}"
                try:
                    conn.executemany(
                        f"DELETE FROM {fts_table} WHERE chunk_id = ?",
                        [(cid,) for cid in orphans],
                    )
                except sqlite3.OperationalError:
                    logger.debug("FTS5 delete skipped — %s absent", fts_table)
                all_orphans_by_strategy[strategy] = orphans
        return all_orphans_by_strategy

    def _purge_file(self, file_path: str) -> None:
        """Remove all indexed data for a single file, using holder-aware cascade.

        Phase 16 rewrite (P4): decrement M2M, then cascade-delete only chunks
        whose holder count dropped to 0.  Shared chunks (still referenced by
        another file) survive.

        Transaction boundary:
            ONE sqlite3 BEGIN/COMMIT covers all strategies × {M2M delete,
            orphan cascade, vec cascade, FTS cascade} via
            ``_holder_aware_chunk_cleanup``.  On any exception inside the
            BEGIN block, ROLLBACK restores exact pre-purge state.

        Post-commit external state (graph + fingerprints):
            Runs AFTER the DB commit.  Failures are WARN-logged; they do not
            undo the DB purge.  A subsequent purge_orphaned_files sweep will
            reconcile any drift.

        Graph audit branch (b):
            delete_file_subgraph is NOT safe under M2M because Section nodes
            are MERGE'd on chunk_id, so DETACH DELETE on a Section shared by
            another file would strip MENTIONS/REL edges the other file still
            needs.  This method uses the holder-aware path: delete_chunks_from_graph
            (orphan chunk_ids only) + delete_file_node (File node only).
        """
        conn = self._conn

        # -- Single-transaction DB cascade (M2M + orphan + vec + FTS) ---------
        all_orphans_by_strategy: dict[str, list[str]] = {}
        try:
            conn.execute("BEGIN")
            all_orphans_by_strategy = self._holder_aware_chunk_cleanup(
                file_path, conn=conn
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        # -- Post-commit, best-effort external state ---------------------------
        # Graph: holder-aware path (branch b — see docstring above).
        try:
            all_orphan_ids: list[str] = [
                cid
                for orphans in all_orphans_by_strategy.values()
                for cid in orphans
            ]
            self._graph_store.delete_chunks_from_graph(all_orphan_ids)
            self._graph_store.delete_file_node(file_path)
        except AttributeError:
            # Graph store does not implement narrow helpers (e.g. LadybugDB).
            # Fall back to the broad delete_file_subgraph (pre-M2M behaviour).
            try:
                self._graph_store.delete_file_subgraph(file_path)
            except Exception as _e:  # noqa: BLE001
                logger.warning(
                    "graph cleanup (fallback) failed after DB commit: %s (file=%s)",
                    _e, file_path,
                )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "graph cleanup failed after DB commit: %s (file=%s)", e, file_path,
            )

        # Fingerprints: keyed on file_path, safe to remove unconditionally.
        try:
            self._chunk_tracker.remove_fingerprint(file_path)
            self._meta_tracker.remove_fingerprint(file_path)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "fingerprint cleanup failed after DB commit: %s (file=%s)", e, file_path,
            )

    def purge_orphaned_files(
        self,
        discovered_paths: set[str] | None = None,
    ) -> tuple[int, int, int]:
        """Remove indexed data for file_paths no longer present on disk.

        Phase 16 rewrite (P4): scans chunk_file_paths_* M2M tables (not
        chunks_* directly) so the sweep covers all strategies correctly.

        When *discovered_paths* is supplied (trickle call site), any file_path
        absent from that set is treated as an orphan.  When omitted (startup
        / test call), each stored file_path is checked via Path.exists().

        Per-file purge delegates to ``_purge_file`` which runs the full
        decrement-cascade inside a single sqlite3 transaction per file.

        Returns ``(files_discovered, files_missing, paths_purged)``.
        The return shape is kept backward-compatible:
        ``files_removed, chunks_removed, vectors_removed`` for trickle callers
        (chunks/vectors counters are 0 — _purge_file is the authoritative
        accounting point; callers care about files_removed only).
        """
        # Collect all file_paths from M2M tables across all strategies.
        strategies = self._present_strategies(self._conn)
        stored_paths: set[str] = set()
        for strat in strategies:
            m2m_table = f"chunk_file_paths_{strat}"
            try:
                rows = self._conn.execute(
                    f"SELECT DISTINCT file_path FROM {m2m_table}"
                ).fetchall()
                stored_paths.update(r[0] for r in rows)
            except sqlite3.OperationalError:
                continue

        files_discovered = len(stored_paths)

        # Determine orphan paths.
        if discovered_paths is not None:
            orphan_paths = stored_paths - discovered_paths
        else:
            # Disk-existence check — used when called without arguments.
            orphan_paths = {fp for fp in stored_paths if not Path(fp).exists()}

        files_missing = len(orphan_paths)

        logger.info(
            "purge_orphaned_files: files_discovered=%d files_missing=%d paths_purging=%d "
            "(strategies=%s)",
            files_discovered, files_missing, files_missing,
            ", ".join(strategies) if strategies else "none",
        )

        if not orphan_paths:
            return 0, 0, 0

        files_removed = 0
        for file_path in sorted(orphan_paths):
            try:
                self._purge_file(file_path)
                files_removed += 1
            except Exception:  # noqa: BLE001
                logger.exception(
                    "purge_orphaned_files: failed to purge %s — skipping", file_path,
                )

        logger.info(
            "purge_orphaned_files: purged %d/%d orphan files",
            files_removed, files_missing,
        )
        return files_removed, 0, 0

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------

    def _run_extraction(self, chunks: list[Chunk]) -> _ExtractionBundle:
        """Run all extractors on chunks. Returns bundled results."""
        structural_result = (
            self._structural_extractor.extract(chunks) if chunks
            else ExtractionResult()
        )
        ner_result = ExtractionResult()
        if self._ner_extractor is not None and chunks:
            ner_result = self._ner_extractor.extract_with_cache(chunks)
        keyterm_result = (
            self._keyterm_extractor.extract(chunks) if chunks
            else ExtractionResult()
        )

        all_entities = (
            structural_result.entities
            + ner_result.entities
            + keyterm_result.entities
        )
        all_relations = (
            structural_result.relations
            + ner_result.relations
            + keyterm_result.relations
        )

        return _ExtractionBundle(
            entities=all_entities,
            relations=all_relations,
            total_entities=len(all_entities),
            total_relations=len(all_relations),
        )

    def _frontmatter_to_graph(self, files: list[FileInfo]) -> None:
        """Inject frontmatter tags and kind-specific metadata into graph.

        ADR: Tags go directly to graph bypassing NER/structural extraction.
        Frontmatter tags are author-curated metadata with explicit semantics
        (e.g. ``person:Alice`` declares a PERSON entity). Running them through
        NER would be redundant and lossy -- NER might misclassify or miss them.
        The colon namespace convention (``type:name``) gives us typed entities
        for free without any ML model overhead.

        Kind-specific extraction (e.g. ``participants`` for meeting_transcript)
        follows the same principle: structured fields have known semantics.
        """
        for fi in files:
            if not fi.frontmatter:
                continue
            file_path_str = str(fi.path)

            # --- Tags with optional namespace ---------------------------
            tags = fi.frontmatter.get("tags", [])
            for tag in tags:
                tag_str = str(tag)
                parts = tag_str.split(":", 1)
                if len(parts) == 2 and parts[0].strip():
                    entity_type = parts[0].strip().upper()
                    name = parts[1].strip()
                else:
                    entity_type = EntityType.TAG
                    name = tag_str
                self._graph_store.add_entity_node(
                    name=name, entity_type=entity_type, source="frontmatter",
                )
                self._graph_store.add_edge(
                    source_id=file_path_str,
                    target_id=name,
                    relation_type=RelationType.HAS_TAG,
                )

            # --- Kind-specific metadata ---------------------------------
            if fi.kind == DocKind.MEETING_TRANSCRIPT:
                participants = fi.frontmatter.get("participants", [])
                for p in participants:
                    p_name = str(p).strip()
                    if not p_name:
                        continue
                    self._graph_store.add_entity_node(
                        name=p_name, entity_type=EntityType.PERSON, source="frontmatter",
                    )
                    self._graph_store.add_edge(
                        source_id=file_path_str,
                        target_id=p_name,
                        relation_type="HAS_PARTICIPANT",
                    )

    def _populate_graph(
        self,
        files: list[FileInfo],
        chunks: list[Chunk],
        extraction: _ExtractionBundle,
    ) -> None:
        """Add entity/file/section nodes and edges to graph store."""
        for entity in extraction.entities:
            if entity.type == "tag":
                self._graph_store.add_tag_node(entity.name)
            else:
                self._graph_store.add_entity_node(
                    name=entity.name,
                    entity_type=entity.type,
                    source=entity.source,
                )
        for file_info in files:
            self._graph_store.add_file_node(
                file_path=str(file_info.path),
                title=file_info.title,
            )
        # Phase 16: use first file_path for graph node (primary path).
        for chunk in chunks:
            _primary_fp = str(chunk.file_paths[0]) if chunk.file_paths else ""
            self._graph_store.add_section_node(
                chunk_id=chunk.chunk_id,
                heading=chunk.heading,
                level=chunk.level,
                file_path=_primary_fp,
                text_preview=chunk.text[:200],
            )
        for relation in extraction.relations:
            self._graph_store.add_edge(
                source_id=relation.source_id,
                target_id=relation.target_id,
                relation_type=relation.relation_type,
                weight=relation.weight,
            )
        for chunk in chunks:
            _primary_fp = str(chunk.file_paths[0]) if chunk.file_paths else ""
            self._graph_store.add_edge(
                source_id=_primary_fp,
                target_id=chunk.chunk_id,
                relation_type=RelationType.CONTAINS,
            )

    # ------------------------------------------------------------------
    # Fingerprint management
    # ------------------------------------------------------------------

    def _build_file_meta(self, chunks: list[Chunk]) -> dict[str, tuple[str, str]]:
        """Build file_meta mapping for FTS5 title/tags columns from source files."""
        file_meta: dict[str, tuple[str, str]] = {}
        # Phase 16: Chunk.file_path → file_paths list; collect all unique paths.
        for fp in {str(p) for c in chunks for p in c.file_paths}:
            if fp in file_meta:
                continue
            try:
                content = read_file(Path(fp))
                frontmatter, _ = parse_frontmatter(content)
                title = str(frontmatter.get("title", Path(fp).stem))
                tags = frontmatter.get("tags", [])
                tags_str = ", ".join(str(t) for t in tags) if tags else ""
                file_meta[fp] = (title, tags_str)
            except OSError:
                logger.warning("Cannot read %s for FTS5 metadata, using defaults", fp)
                file_meta[fp] = (Path(fp).stem, "")
        return file_meta

    def _save_fingerprint(self, tracker: FileTracker, fi: FileInfo) -> None:
        """Save a file fingerprint using the tracker's checksum function.

        ADR: Each tracker has its own checksum formula (injected at construction).
        chunk_tracker uses chunk_checksum (body+kind), meta_tracker uses
        meta_checksum (title+tags). This method delegates to the tracker's
        formula so fingerprints match the diff() comparison.
        """
        try:
            stat = fi.path.stat()
        except OSError:
            logger.warning("Cannot stat %s for fingerprint, skipping", fi.path)
            return
        tracker.save_fingerprint(
            str(fi.path), stat.st_mtime, stat.st_size,
            tracker._checksum_fn(fi.path),
        )

    def _save_chunk_fingerprint(self, fi: FileInfo) -> None:
        self._save_fingerprint(self._chunk_tracker, fi)

    def _save_meta_fingerprint(self, fi: FileInfo) -> None:
        self._save_fingerprint(self._meta_tracker, fi)

    def _update_chunk_fingerprints(self, files: list[FileInfo]) -> None:
        """Save chunk fingerprints for successfully chunked files."""
        for fi in files:
            self._save_chunk_fingerprint(fi)

    def _update_meta_fingerprints(self, files: list[FileInfo]) -> None:
        """Save meta fingerprints for successfully embedded files."""
        for fi in files:
            self._save_meta_fingerprint(fi)

    def _embed_existing_chunks(
        self,
        files: list[FileInfo],
        *,
        model_switch: bool = False,
        run_id: str = "",
    ) -> None:
        """Re-embed chunks for embed-only files (body unchanged, embedding needs update).

        Used when meta_diff detects files that need embedding but chunk_diff says
        they are unchanged (e.g. after a model switch or metadata-only update).

        Updated in Phase 999.12: now computes e_meta, fuses e_text+e_meta, writes
        all three components (e_text, e_meta, e_fused). Two sub-paths:

        model_switch=True — Full re-encoding path:
            Both e_text and e_meta are stale (different model). Re-encode both via TEI.
            Do NOT read e_text from VecComponentStore — it was encoded by a different
            model and must not be used for fusion with the new model's e_meta.
            (Addresses OpenCode HIGH-2 Cycle 3: prevents model-switch silently using
            stale e_text from VecComponentStore.)

        model_switch=False — Cached e_text path (metadata-only equivalent):
            e_text in VecComponentStore is valid (same model, body unchanged).
            Only e_meta needs encoding (1 TEI call). Read cached e_text, fuse locally.
            Same logic as _index_file_embed() fast path.
        """
        weights = self._settings.parsed_embedding_weights

        for fi in files:
            path_str = str(fi.path)
            chunk_ids = self._metadata_store.get_chunk_ids_by_file(
                self._strategy, path_str
            )
            if not chunk_ids:
                continue
            chunks = self._metadata_store.get_chunks(chunk_ids)
            if not chunks:
                continue

            if model_switch:
                # ── MODEL SWITCH: full re-encoding (both e_text and e_meta stale) ──
                # Do NOT use _embed_chunks() — it reads VecComponentStore (Layer 1) which
                # contains e_text from the OLD model and would silently return stale vectors.
                # (Addresses OpenCode HIGH-2 Cycle 3: bypass VecComponentStore for model switch.)
                # Call encode_batch directly so all chunks go through TEI regardless of cache.
                texts = [c.text for c in chunks]
                e_text_vectors = self._semantic_engine.encode_batch(texts)
                text_hashes = {
                    c.chunk_id: blake3.blake3(c.text.encode()).hexdigest()
                    for c in chunks
                }
                e_meta = self._embed_meta_component(fi)                    # TEI: 1 call
                e_fused_vectors = [
                    self._fuse_vectors(e_t, e_meta, weights) for e_t in e_text_vectors
                ]
                # Note: no explicit BEGIN here — add_chunks() commits internally.
                # VecComponentStore.store() calls are auto-committed in WAL autocommit mode.
                for chunk, e_text in zip(chunks, e_text_vectors):
                    self._vec_components.store(chunk.chunk_id, "text", e_text)
                self._vec_components.store(
                    self._meta_entity_id(fi.path), "meta", e_meta
                )
                self._conn.commit()  # Flush VecComponentStore stores before add_chunks
                self._vector_store.add_chunks(
                    chunks, e_fused_vectors, overwrite=True, text_hashes=text_hashes
                )
                logger.info(
                    "_embed_existing_chunks (model_switch): %s — %d chunks, e_text + e_meta re-encoded",
                    fi.path, len(chunks),
                )

            else:
                # ── CACHED E_TEXT: read from VecComponentStore, only encode e_meta ──
                e_text_map = self._vec_components.get_batch(
                    [c.chunk_id for c in chunks], "text"
                )
                missing = [c for c in chunks if c.chunk_id not in e_text_map]
                if missing:
                    logger.warning(
                        "_embed_existing_chunks: %d missing e_text BLOBs for %s — "
                        "falling back to full encode for missing chunks",
                        len(missing), fi.path,
                    )
                    missing_vecs, missing_hashes = self._embed_chunks(missing)
                    for chunk, e_t in zip(missing, missing_vecs):
                        e_text_map[chunk.chunk_id] = e_t
                e_meta = self._embed_meta_component(fi)  # 1 TEI call
                e_fused_vectors = [
                    self._fuse_vectors(e_text_map[c.chunk_id], e_meta, weights)
                    for c in chunks
                ]
                # Note: no explicit BEGIN here — add_chunks() commits internally.
                # VecComponentStore.store() calls are auto-committed in WAL autocommit mode.
                if missing:
                    for chunk in missing:
                        self._vec_components.store(
                            chunk.chunk_id, "text", e_text_map[chunk.chunk_id]
                        )
                self._vec_components.store(
                    self._meta_entity_id(fi.path), "meta", e_meta
                )
                self._conn.commit()  # Flush VecComponentStore stores before add_chunks
                self._vector_store.add_chunks(
                    chunks, e_fused_vectors, overwrite=True,
                )
                logger.info(
                    "_embed_existing_chunks (cached e_text): %s — 1 TEI call (e_meta), "
                    "%d fused vectors recomputed locally",
                    fi.path, len(chunks),
                )

            self._save_meta_fingerprint(fi)

        logger.info(
            "[%s] embed_existing: %d files processed (model_switch=%s)",
            run_id, len(files), model_switch,
        )

    # ------------------------------------------------------------------
    # Startup integrity checks
    # ------------------------------------------------------------------

    def _check_schema_version(self) -> None:
        """Check schema version sentinel; wipe ALL vector state if version mismatch.

        Entire wipe is wrapped in a single BEGIN...COMMIT transaction so that a
        crash mid-wipe leaves the database in a state where the sentinel is NOT
        written (schema_version != SCHEMA_VERSION), causing a clean re-wipe on
        next startup. A crash after COMMIT is safe: the state is fully wiped and
        consistent.

        Clears all 7 state components:
          1. embedding_cache (text_hash semantics changed: body-only hash)
          2. vec_components (stale e_text BLOBs encoded with old enriched text)
          3. vec0 / vec_meta (stale enriched vectors)
          4. chunk_tracker (force full re-chunk on next trickle run)
          5. meta_tracker (force full re-embed on next trickle run)
          6. weights_used sentinel (cleared; re-written by weight detection after startup)
          7. schema_version sentinel (written last, inside same transaction)

        After wipe: trickle rebuilds from scratch on next run.
        Expected rebuild time: several days on current hardware (Xeon E3-1245 V2, CPU-only TEI).
        """
        # Force vec_config table creation before reading from it.
        # SQLiteVecVectorStore creates tables lazily via _get_conn(); bypassing
        # it with self._conn directly would fail on a fresh database (#999.12).
        self._vector_store._get_conn()
        config_table = self._vector_store._CONFIG_TABLE
        row = self._conn.execute(
            f"SELECT value FROM {config_table} WHERE key = 'schema_version'"
        ).fetchone()
        stored_version = row[0] if row else None

        if stored_version == self.SCHEMA_VERSION:
            return  # Up to date

        if stored_version is None:
            # First startup with this sentinel (fresh DB or pre-999.12 DB that predates
            # SCHEMA_VERSION tracking). Write the sentinel and return — no wipe needed.
            # Future version bumps ("2" → "3") will have an explicit stored_version and
            # will correctly trigger the wipe path below.
            self._conn.execute(
                f"INSERT OR REPLACE INTO {config_table} (key, value) VALUES ('schema_version', ?)",
                (self.SCHEMA_VERSION,),
            )
            self._conn.commit()
            return

        logger.warning(
            "schema_version mismatch: stored=%r expected=%r — wiping all vector state. "
            "trickle will rebuild from scratch. Expected rebuild time: several days.",
            stored_version, self.SCHEMA_VERSION,
        )

        # Each sub-operation below commits internally (delete_all, clear all call
        # conn.commit()). An outer BEGIN/COMMIT cannot wrap them atomically.
        # Safety: each operation is idempotent. If a crash occurs mid-wipe, the
        # schema_version sentinel is NOT written (it's last), so the next startup
        # sees stored_version != SCHEMA_VERSION and repeats the wipe safely.
        try:
            # 1. Wipe embedding cache (text_hash semantics changed)
            self._embedding_cache.clear()
            # 2. Wipe vec_components (stale e_text BLOBs)
            self._vec_components.delete_all()
            # 3. Wipe vec0 + vec_meta (SQLiteVecVectorStore.delete_all handles both)
            self._vector_store.delete_all()
            # 4. Clear chunk_tracker
            self._chunk_tracker.clear()
            # 5. Clear meta_tracker
            self._meta_tracker.clear()
            # 6. Clear stored weights sentinel (re-written by _check_weights_changed)
            self._conn.execute(
                f"DELETE FROM {config_table} WHERE key = 'weights_used'"
            )
            # 7. Write new schema_version sentinel (last step — marks clean state)
            self._conn.execute(
                f"INSERT OR REPLACE INTO {config_table} (key, value) VALUES ('schema_version', ?)",
                (self.SCHEMA_VERSION,),
            )
            self._conn.commit()
        except Exception:
            logger.error("_check_schema_version: wipe failed", exc_info=True)
            raise

        logger.info(
            "schema_version sentinel written: %s. Vector rebuild in progress.", self.SCHEMA_VERSION
        )

    def _check_weights_changed(self) -> None:
        """Detect weight change; if changed, recompute e_fused from stored components.

        Changing weights is cheap: read stored e_text + e_meta BLOBs from vec_components,
        fuse locally with new weights, bulk-update vec0. No TEI calls.

        Guards:
        - If VecComponentStore is empty (e.g. fresh install or post-wipe), skip entirely.
        - Recompute is batched at 1000 files at a time to avoid OOM on large indexes.
        - Sentinel is updated ONLY if the recompute was complete (no files skipped due to
          missing components). Partial recompute leaves sentinel unchanged so the next
          startup detects the change and retries.
          (Addresses Codex MEDIUM: do not update sentinel on partial recompute.)

        Stored weights are in vec_config key 'weights_used' (JSON string).
        """
        import json as _json

        # Guard: skip if store is empty (fresh install or post schema-version wipe)
        if self._vec_components.count() == 0:
            logger.debug("_check_weights_changed: VecComponentStore is empty — skipping")
            return

        config_table = self._vector_store._CONFIG_TABLE
        current_weights = self._settings.parsed_embedding_weights
        current_weights_json = _json.dumps(current_weights, sort_keys=True)

        row = self._conn.execute(
            f"SELECT value FROM {config_table} WHERE key = 'weights_used'"
        ).fetchone()
        stored_weights_json = row[0] if row else None

        if stored_weights_json == current_weights_json:
            return  # No change

        logger.info(
            "Embedding weights changed: stored=%r current=%r — recomputing e_fused from components.",
            stored_weights_json, current_weights_json,
        )

        weights = current_weights
        # Get all distinct file paths from M2M table
        m2m_table = f"chunk_file_paths_{self._strategy}"
        try:
            rows = self._conn.execute(
                f"SELECT DISTINCT file_path FROM {m2m_table}"
            ).fetchall()
            all_file_paths = [row[0] for row in rows]
        except Exception:
            logger.warning("_check_weights_changed: cannot read M2M table — skipping")
            return

        total_recomputed = 0
        files_skipped = 0

        # Process in batches of 1000 files to avoid OOM on ~1.4M chunks (~5.6GB raw vectors)
        BATCH_SIZE = 1000
        for batch_start in range(0, len(all_file_paths), BATCH_SIZE):
            batch = all_file_paths[batch_start: batch_start + BATCH_SIZE]
            for fp in batch:
                # Always use _meta_entity_id() for canonical path normalization
                canonical_fp = self._meta_entity_id(fp)
                chunk_ids = self._metadata_store.get_chunk_ids_by_file(
                    self._strategy, canonical_fp
                ) or []
                chunks = self._metadata_store.get_chunks(chunk_ids) if chunk_ids else []
                if not chunks:
                    continue
                e_meta = self._vec_components.get(canonical_fp, "meta")
                if e_meta is None:
                    logger.warning(
                        "_check_weights_changed: no e_meta for %s — skipping file", fp
                    )
                    files_skipped += 1
                    continue
                e_text_map = self._vec_components.get_batch(
                    [c.chunk_id for c in chunks], "text"
                )
                missing = [c for c in chunks if c.chunk_id not in e_text_map]
                if missing:
                    logger.warning(
                        "_check_weights_changed: %d missing e_text BLOBs for %s — skipping file",
                        len(missing), fp,
                    )
                    files_skipped += 1
                    continue
                e_fused = [
                    self._fuse_vectors(e_text_map[c.chunk_id], e_meta, weights)
                    for c in chunks
                ]
                self._vector_store.add_chunks(chunks, e_fused, overwrite=True)
                total_recomputed += len(chunks)

        if files_skipped > 0:
            # Partial recompute — do NOT update sentinel
            # Next startup will detect weights_used != current and retry
            logger.warning(
                "_check_weights_changed: %d files skipped due to missing components — "
                "NOT updating weights_used sentinel; will retry on next startup.",
                files_skipped,
            )
            return

        # Full recompute — safe to update sentinel
        self._conn.execute(
            f"INSERT OR REPLACE INTO {config_table} (key, value) VALUES ('weights_used', ?)",
            (current_weights_json,),
        )
        self._conn.commit()
        logger.info(
            "_check_weights_changed: recomputed %d fused vectors (no TEI calls). "
            "weights_used sentinel updated.",
            total_recomputed,
        )

    # ------------------------------------------------------------------
    # Accessors (used by the service layer)
    # ------------------------------------------------------------------

    @property
    def conn(self) -> sqlite3.Connection:
        """The shared SQLite connection."""
        return self._conn

    @property
    def metadata_store(self) -> SQLiteMetadataStore:
        return self._metadata_store

    @property
    def vector_store(self) -> VectorStoreProtocol:
        return self._vector_store

    @property
    def graph_store(self) -> GraphStoreProtocol:
        return self._graph_store

    @property
    def semantic_engine(self) -> SemanticSearchEngine:
        return self._semantic_engine

    @property
    def keyword_engine(self) -> FTS5SearchEngine:
        return self._keyword_engine

    @property
    def chunk_tracker(self) -> FileTracker:
        """Chunk-level file tracker (strategy-scoped)."""
        return self._chunk_tracker

    @property
    def meta_tracker(self) -> FileTracker:
        """Meta-level file tracker (strategy+model-scoped). Detects title/tags changes."""
        return self._meta_tracker

    @property
    def file_tracker(self) -> FileTracker:
        """Backward-compatible alias for chunk_tracker.

        Used by trickle.py and service.py for file-level change detection.
        """
        return self._chunk_tracker
