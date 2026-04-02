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

import hashlib
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
from dotmd.ingestion.chunker import chunk_file
from dotmd.ingestion.content_handlers import get_handler
from dotmd.ingestion.file_tracker import FileDiff, FileTracker
from dotmd.ingestion.reader import chunk_checksum, discover_files, embed_checksum, parse_frontmatter, read_file
from dotmd.search.fts5 import FTS5SearchEngine
from dotmd.search.semantic import SemanticSearchEngine
from dotmd.storage.base import GraphStoreProtocol, VectorStoreProtocol
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
            graph_name=settings.falkordb_graph_name,
        )
    from dotmd.storage.graph import LadybugDBGraphStore

    return LadybugDBGraphStore(
        settings.graph_db_path, read_only=settings.read_only,
    )


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

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

        # Ensure the index directory exists.
        settings.index_dir.mkdir(parents=True, exist_ok=True)

        # -- Unified SQLite connection ----------------------------------------
        # ONE connection shared by metadata store, vec store, FTS5, and
        # file trackers.  sqlite-vec extension loaded once here.
        self._conn = sqlite3.connect(
            str(settings.index_db_path), check_same_thread=False,
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
        embed_fp_table = f"embed_fingerprints_{strategy}{model_suffix}"

        # -- storage backends --------------------------------------------------
        self._metadata_store = SQLiteMetadataStore(
            conn=self._conn,
            table_name=self._chunks_table,
            fts_table_name=self._fts_table,
        )

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
        # embed_tracker: hash(body + kind + title + tags) → also detects metadata
        #   changes → re-embed + FTS5 + graph (skip re-chunking)
        # This prevents 26hr full reindex when only tags/title change.
        self._chunk_tracker = FileTracker(
            self._conn, table_name=chunk_fp_table, checksum_fn=chunk_checksum,
        )
        self._embed_tracker = FileTracker(
            self._conn, table_name=embed_fp_table, checksum_fn=embed_checksum,
        )

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
        self._ner_extractor: NERExtractor | None = None
        if settings.extract_depth == ExtractDepth.NER:
            self._ner_extractor = NERExtractor(settings.ner_entity_types)

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
            embed_diff = self._embed_tracker.diff(files)
            embed_needed = set(embed_diff.new) | set(embed_diff.modified)
            if not embed_needed:
                logger.info("[%s] no changes — skipping (%.2fs total)", run_id, time.perf_counter() - t_start)
                stats = self._metadata_store.get_stats()
                if stats is None:
                    stats = IndexStats()
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
            stats = self._metadata_store.get_stats()
            if stats is None:
                stats = IndexStats()
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
        """Drop vec tables + embed_fingerprints for current (strategy, model).

        Removes only the vector-layer data.  Chunks, FTS5, and graph remain
        intact so BM25 and graph search continue to work.
        """
        strategy = self._strategy
        model_suffix = self._model_suffix

        vec_table = f"vec_chunks_{strategy}{model_suffix}"
        meta_table = f"vec_meta_{strategy}{model_suffix}"
        config_table = f"vec_config_{strategy}{model_suffix}"
        embed_fp_table = f"embed_fingerprints_{strategy}{model_suffix}"

        for table in (vec_table, meta_table, config_table):
            self._conn.execute(f"DROP TABLE IF EXISTS {table}")
        try:
            self._conn.execute(f"DELETE FROM {embed_fp_table}")
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

        # 3. CASCADE: drop ALL vec_*_{strategy}_* and embed_fp_{strategy}_*
        #    Discover tables via sqlite_master.
        prefix_vec = f"vec_chunks_{strategy}_"
        prefix_meta = f"vec_meta_{strategy}_"
        prefix_config = f"vec_config_{strategy}_"
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

    def _enrich_for_embedding(self, chunk: Chunk, fm_cache: dict[Path, dict]) -> str:
        """Enrich chunk text for embedding using kind-appropriate handler.

        Reads frontmatter from the source file (cached per-file) and
        delegates to the handler's ``enrich`` function.
        """
        file_path = chunk.file_path
        if file_path not in fm_cache:
            try:
                content = read_file(file_path)
                fm_cache[file_path], _ = parse_frontmatter(content)
            except OSError:
                logger.warning("Cannot read %s for enrichment, embedding without metadata", file_path)
                fm_cache[file_path] = {}
        handler = get_handler(chunk.kind)
        return handler.enrich(chunk.text, fm_cache[file_path])

    def _embed_chunks(
        self, chunks: list[Chunk],
    ) -> tuple[list[list[float]], dict[str, str]]:
        """Embed chunks with context prefix injection and text_hash reuse.

        Each chunk's text is enriched via kind-appropriate handler before
        encoding. The text_hash is computed on the ENRICHED text so that
        cache reuse is correct (same text + same title = same embedding).

        Returns ``(embeddings, text_hashes)`` where *text_hashes* maps
        ``chunk_id → md5_hex``.
        """
        if not chunks:
            return [], {}

        # Enrich texts using kind-aware handlers (frontmatter cached per file)
        fm_cache: dict[Path, dict] = {}
        enriched_texts: dict[str, str] = {
            c.chunk_id: self._enrich_for_embedding(c, fm_cache) for c in chunks
        }

        # text_hash on enriched text (prefix changes embedding → different hash)
        text_hashes: dict[str, str] = {
            cid: hashlib.md5(text.encode()).hexdigest()
            for cid, text in enriched_texts.items()
        }

        # Lookup existing embeddings by text_hash (same model, any strategy)
        existing: dict[str, list[float]] = {}
        if hasattr(self._vector_store, "lookup_embeddings_by_text_hash"):
            existing = self._vector_store.lookup_embeddings_by_text_hash(
                list(text_hashes.values()),
            )

        hits = 0
        to_encode_indices: list[int] = []
        embeddings: list[list[float] | None] = [None] * len(chunks)

        for i, chunk in enumerate(chunks):
            th = text_hashes[chunk.chunk_id]
            if th in existing:
                embeddings[i] = existing[th]
                hits += 1
            else:
                to_encode_indices.append(i)

        if to_encode_indices:
            texts_to_encode = [
                enriched_texts[chunks[i].chunk_id] for i in to_encode_indices
            ]
            new_embeddings = self._semantic_engine.encode_batch(texts_to_encode)
            for j, idx in enumerate(to_encode_indices):
                embeddings[idx] = new_embeddings[j]

        total = len(chunks)
        logger.info(
            "embed: %d chunks, %d cache hits (%.1f%%), %d computed",
            total,
            hits,
            hits / total * 100 if total else 0,
            len(to_encode_indices),
        )

        # Type narrowing: all None slots are now filled.
        return embeddings, text_hashes  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Granular reindex (rebuild one store from metadata chunks)
    # ------------------------------------------------------------------

    def reindex_vectors(self) -> int:
        """Rebuild vector store from stored chunks. Returns chunk count."""
        all_chunks = self._metadata_store.get_all_chunks()
        if not all_chunks:
            logger.info("reindex_vectors: no chunks in metadata")
            return 0
        self._vector_store.delete_all()
        embeddings, text_hashes = self._embed_chunks(all_chunks)
        self._vector_store.add_chunks(
            all_chunks, embeddings, overwrite=True,
            text_hashes=text_hashes,
        )
        if hasattr(self._vector_store, "set_model_name"):
            model_id = self._semantic_engine.get_tei_model_id() or self._settings.embedding_model
            self._vector_store.set_model_name(model_id)
            self._vector_store.set_distance_metric("cosine")
        logger.info("reindex_vectors: %d chunks re-embedded", len(all_chunks))
        return len(all_chunks)

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
        for fp in sorted({str(c.file_path) for c in all_chunks}):
            title = Path(fp).stem
            try:
                content = read_file(Path(fp))
                frontmatter, _ = parse_frontmatter(content)
                title = frontmatter.get("title", title)
            except OSError:
                pass
            self._graph_store.add_file_node(
                file_path=fp, title=str(title), checksum="",
            )

        # Section nodes + CONTAINS edges
        for chunk in all_chunks:
            self._graph_store.add_section_node(
                chunk_id=chunk.chunk_id,
                heading=chunk.heading,
                level=chunk.level,
                file_path=str(chunk.file_path),
                text_preview=chunk.text[:200],
            )
            self._graph_store.add_edge(
                source_id=str(chunk.file_path),
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
        self._embed_tracker.clear()
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
            embed_diff = self._embed_tracker.diff(unchanged_files)
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
            chunks.extend(chunk_file(
                fi.path, content,
                max_tokens=self._settings.max_chunk_tokens,
                overlap_tokens=self._settings.chunk_overlap_tokens,
                kind=fi.kind,
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
        """Save chunks to metadata, embed, store vectors, update FTS5."""
        t0 = time.perf_counter()
        self._metadata_store.save_chunks(chunks)
        logger.info("[%s] metadata_save: %d chunks (%.2fs)", run_id, len(chunks), time.perf_counter() - t0)

        t0 = time.perf_counter()
        embeddings, text_hashes = self._embed_chunks(chunks)
        t_embed = time.perf_counter() - t0
        logger.info("[%s] embed: %d chunks (%.1fs, %.0f chunks/s)", run_id, len(chunks), t_embed, len(chunks) / t_embed if t_embed > 0 else 0)

        t0 = time.perf_counter()
        self._vector_store.add_chunks(
            chunks, embeddings, overwrite=overwrite_vectors,
            text_hashes=text_hashes,
        )
        logger.info("[%s] vector_store: %d vectors (%.2fs)", run_id, len(chunks), time.perf_counter() - t0)
        if hasattr(self._vector_store, "set_model_name"):
            self._vector_store.set_model_name(self._settings.embedding_model)

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
        """Save chunk + embed fingerprints after successful ingestion."""
        t0 = time.perf_counter()
        self._update_chunk_fingerprints(files)
        self._update_embed_fingerprints(files)
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

    def index_file(self, file_info: FileInfo) -> int:
        """Index a single file through the two-phase pipeline.

        Phase 1 (chunk): check chunk_tracker, re-chunk if needed, save
        chunk fingerprint.  Phase 2 (embed): check embed_tracker,
        text_hash lookup, encode misses, save embed fingerprint.

        Used by the trickle indexer for one-at-a-time background processing.

        Returns the number of chunks created/updated.
        """
        path_str = str(file_info.path)
        needs_embed = False

        # --- Phase 1: Chunk ---
        chunk_diff = self._chunk_tracker.diff([file_info])
        if path_str in chunk_diff.new or path_str in chunk_diff.modified:
            # Purge old derived data (FTS5, graph, current vec) but NOT
            # chunks (overwritten by UPSERT with deterministic IDs).
            old_chunk_ids = self._metadata_store.get_chunk_ids_by_file(path_str)
            if old_chunk_ids:
                self._keyword_engine.remove_chunks(old_chunk_ids)
                self._vector_store.delete_vectors_by_chunk_ids(old_chunk_ids)
                self._graph_store.delete_file_subgraph(path_str)
                logger.debug(
                    "Purged derived data for %s (%d chunks)",
                    file_info.path.name, len(old_chunk_ids),
                )

            content = read_file(file_info.path)
            chunks = chunk_file(
                file_info.path,
                content,
                max_tokens=self._settings.max_chunk_tokens,
                overlap_tokens=self._settings.chunk_overlap_tokens,
                kind=file_info.kind,
            )

            if not chunks:
                # File produced no chunks (empty or filtered out).
                # Still save fingerprint so we don't re-process next time.
                self._save_chunk_fingerprint(file_info)
                return 0

            # UPSERT chunks — safe with deterministic chunk_ids.
            self._metadata_store.save_chunks(chunks)
            _trickle_tags = file_info.frontmatter.get("tags", [])
            _trickle_tags_csv = ", ".join(str(t) for t in _trickle_tags) if _trickle_tags else ""
            _trickle_meta = {str(file_info.path): (file_info.title, _trickle_tags_csv)}
            self._keyword_engine.add_chunks(chunks, file_meta=_trickle_meta)

            extraction = self._run_extraction(chunks)
            self._populate_graph([file_info], chunks, extraction)
            self._frontmatter_to_graph([file_info])

            # Save chunk fingerprint BEFORE embed (crash-safe split point).
            self._save_chunk_fingerprint(file_info)
            needs_embed = True
        else:
            # Chunks unchanged — check if embedding needed.
            chunks = []

        # --- Phase 2: Embed + metadata refresh ---
        # ADR: embed_tracker uses embed_checksum (body+kind+title+tags).
        # When only title/tags changed (chunk_diff=unchanged, embed_diff=modified),
        # we skip re-chunking but still re-embed, update FTS5 columns, and
        # refresh graph metadata. This is the "lightweight metadata update" path.
        metadata_only = False
        if not needs_embed:
            embed_diff = self._embed_tracker.diff([file_info])
            needs_embed = (
                path_str in embed_diff.new or path_str in embed_diff.modified
            )
            metadata_only = needs_embed  # True = triggered by metadata, not content

        if needs_embed:
            # Fetch chunks from DB (guaranteed to exist from phase 1 or prior run).
            if not chunks:
                chunk_ids = self._metadata_store.get_chunk_ids_by_file(path_str)
                chunks = self._metadata_store.get_chunks(chunk_ids) if chunk_ids else []

            if chunks:
                embeddings, text_hashes = self._embed_chunks(chunks)
                self._vector_store.add_chunks(
                    chunks, embeddings, overwrite=False,
                    text_hashes=text_hashes,
                )

                # Metadata-only change: also refresh FTS5 and graph
                # (Phase 1 already handles these when content changes)
                if metadata_only:
                    file_meta = self._build_file_meta_from_fileinfo([file_info])
                    self._keyword_engine.add_chunks(chunks, file_meta=file_meta)
                    self._frontmatter_to_graph([file_info])
                    logger.info(
                        "Metadata-only update for %s: FTS5 + graph + embeddings refreshed",
                        file_info.path.name,
                    )

            # Save embed fingerprint after successful embedding.
            self._save_embed_fingerprint(file_info)

        return len(chunks) if chunks else 0

    # ------------------------------------------------------------------
    # Per-file purge
    # ------------------------------------------------------------------

    def _purge_file(self, file_path: str) -> None:
        """Remove all indexed data for a single file from all stores.

        ORDERING MATTERS: chunk_ids must be fetched from metadata BEFORE
        metadata rows are deleted, because vector deletion needs them.

        Only cleans the CURRENT (strategy, model) pair's vec + fingerprints.
        Other models' data for this file becomes stale but self-heals when
        that model's pipeline runs next (embed_diff detects "modified").
        """
        chunk_ids = self._metadata_store.get_chunk_ids_by_file(file_path)
        if chunk_ids:
            self._vector_store.delete_vectors_by_chunk_ids(chunk_ids)
            self._keyword_engine.remove_chunks(chunk_ids)
        self._metadata_store.delete_chunks_by_file(file_path)
        self._graph_store.delete_file_subgraph(file_path)
        self._chunk_tracker.remove_fingerprint(file_path)
        self._embed_tracker.remove_fingerprint(file_path)

    def purge_orphaned_files(
        self, discovered_paths: set[str],
    ) -> tuple[int, int, int]:
        """Remove indexed data for files not in *discovered_paths*.

        Compares ``SELECT DISTINCT file_path`` from the chunks table against
        the set of paths currently on disk.  Any file_path present in the
        database but absent from *discovered_paths* is purged from all stores
        (chunks, FTS5, vectors, graph, fingerprints).

        Processes orphans in batches of 100 to keep transactions bounded.

        Returns ``(files_removed, chunks_removed, vectors_removed)``.
        """
        # Discover stored file paths from the chunks table
        try:
            rows = self._conn.execute(
                f"SELECT DISTINCT file_path FROM {self._chunks_table}",
            ).fetchall()
        except sqlite3.OperationalError:
            # Table doesn't exist yet (fresh install)
            return 0, 0, 0

        stored_paths = {row[0] for row in rows}
        orphan_paths = stored_paths - discovered_paths

        if not orphan_paths:
            return 0, 0, 0

        logger.info(
            "Orphan cleanup: %d stored files, %d discovered, %d orphans to remove",
            len(stored_paths), len(discovered_paths), len(orphan_paths),
        )

        files_removed = 0
        chunks_removed = 0
        vectors_removed = 0

        orphan_list = sorted(orphan_paths)
        batch_size = 100

        for i in range(0, len(orphan_list), batch_size):
            batch = orphan_list[i : i + batch_size]

            for file_path in batch:
                chunk_ids = self._metadata_store.get_chunk_ids_by_file(file_path)
                n_chunks = len(chunk_ids)

                if chunk_ids:
                    # Delete vectors from ALL vec_meta tables for current model
                    n_vecs = self._vector_store.delete_vectors_by_chunk_ids(
                        chunk_ids,
                    )
                    vectors_removed += n_vecs if isinstance(n_vecs, int) else n_chunks
                    self._keyword_engine.remove_chunks(chunk_ids)

                self._metadata_store.delete_chunks_by_file(file_path)
                self._graph_store.delete_file_subgraph(file_path)
                self._chunk_tracker.remove_fingerprint(file_path)
                self._embed_tracker.remove_fingerprint(file_path)

                chunks_removed += n_chunks
                files_removed += 1

            if i + batch_size < len(orphan_list):
                logger.info(
                    "Orphan cleanup progress: %d/%d files (%d chunks)",
                    files_removed, len(orphan_list), chunks_removed,
                )

        logger.info(
            "Orphan cleanup: purged %d files (%d chunks, %d vectors)",
            files_removed, chunks_removed, vectors_removed,
        )
        return files_removed, chunks_removed, vectors_removed

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
            ner_result = self._ner_extractor.extract(chunks)
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
                checksum=file_info.checksum,
            )
        for chunk in chunks:
            self._graph_store.add_section_node(
                chunk_id=chunk.chunk_id,
                heading=chunk.heading,
                level=chunk.level,
                file_path=str(chunk.file_path),
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
            self._graph_store.add_edge(
                source_id=str(chunk.file_path),
                target_id=chunk.chunk_id,
                relation_type=RelationType.CONTAINS,
            )

    # ------------------------------------------------------------------
    # Fingerprint management
    # ------------------------------------------------------------------

    def _build_file_meta(self, chunks: list[Chunk]) -> dict[str, tuple[str, str]]:
        """Build file_meta mapping for FTS5 title/tags columns from source files."""
        file_meta: dict[str, tuple[str, str]] = {}
        for fp in {str(c.file_path) for c in chunks}:
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
        chunk_tracker uses chunk_checksum (body+kind), embed_tracker uses
        embed_checksum (body+kind+title+tags). This method delegates to the
        tracker's formula so fingerprints match the diff() comparison.
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

    def _save_embed_fingerprint(self, fi: FileInfo) -> None:
        self._save_fingerprint(self._embed_tracker, fi)

    def _update_chunk_fingerprints(self, files: list[FileInfo]) -> None:
        """Save chunk fingerprints for successfully chunked files."""
        for fi in files:
            self._save_chunk_fingerprint(fi)

    def _update_embed_fingerprints(self, files: list[FileInfo]) -> None:
        """Save embed fingerprints for successfully embedded files."""
        for fi in files:
            self._save_embed_fingerprint(fi)

    def _embed_existing_chunks(
        self,
        files: list[FileInfo],
        *,
        run_id: str = "",
    ) -> None:
        """Embed-only pass for files whose chunks already exist in DB.

        Used when embed_diff detects files that need embedding but
        chunk_diff says they are unchanged (e.g. after a model switch).
        """
        for fi in files:
            path_str = str(fi.path)
            chunk_ids = self._metadata_store.get_chunk_ids_by_file(path_str)
            if not chunk_ids:
                continue
            chunks = self._metadata_store.get_chunks(chunk_ids)
            if not chunks:
                continue

            embeddings, text_hashes = self._embed_chunks(chunks)
            self._vector_store.add_chunks(
                chunks, embeddings, overwrite=False,
                text_hashes=text_hashes,
            )
            self._save_embed_fingerprint(fi)

        logger.info(
            "[%s] embed_existing: %d files processed", run_id, len(files),
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
    def embed_tracker(self) -> FileTracker:
        """Embed-level file tracker (strategy+model-scoped)."""
        return self._embed_tracker

    @property
    def file_tracker(self) -> FileTracker:
        """Backward-compatible alias for chunk_tracker.

        Used by trickle.py and service.py for file-level change detection.
        """
        return self._chunk_tracker
