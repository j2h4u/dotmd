"""End-to-end indexing pipeline for dotMD.

Orchestrates file discovery, chunking, embedding, FTS5 index construction,
structural and NER extraction, and knowledge-graph population.

Supports two modes:
- **Incremental** (default): only new/modified files are processed;
  deleted files are purged; unchanged files are skipped entirely.
- **Full** (``force=True``): all stores are cleared and every file is
  re-indexed from scratch.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from dataclasses import dataclass as _dataclass
from datetime import datetime, timezone
from pathlib import Path

from dotmd.core.config import Settings
from dotmd.core.models import Chunk, ExtractionResult, FileInfo, IndexStats
from dotmd.extraction.acronyms import extract_acronyms_from_chunks
from dotmd.extraction.keyterms import KeyTermExtractor
from dotmd.extraction.ner import NERExtractor
from dotmd.extraction.structural import StructuralExtractor
from dotmd.ingestion.chunker import chunk_file
from dotmd.ingestion.file_tracker import FileDiff, FileTracker
from dotmd.ingestion.reader import discover_files, read_file
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


def _create_vector_store(settings: Settings) -> VectorStoreProtocol:
    """Instantiate the configured vector store backend."""
    if settings.vector_backend == "sqlite-vec":
        from dotmd.storage.sqlite_vec import SQLiteVecVectorStore

        return SQLiteVecVectorStore(settings.sqlite_vec_path)

    from dotmd.storage.vector import LanceDBVectorStore

    return LanceDBVectorStore(settings.lancedb_path)


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

        # -- storage backends --------------------------------------------------
        self._metadata_store = SQLiteMetadataStore(settings.sqlite_path)
        self._vector_store = _create_vector_store(settings)
        self._graph_store = _create_graph_store(settings)

        # -- file tracker (shares metadata store's connection) -----------------
        self._file_tracker = FileTracker(self._metadata_store._conn)

        # -- search engines (used for encoding during indexing) ----------------
        self._semantic_engine = SemanticSearchEngine(
            self._vector_store,
            settings.embedding_model,
            embedding_url=settings.embedding_url,
            tei_batch_size=settings.tei_batch_size,
        )
        self._keyword_engine = FTS5SearchEngine(self._metadata_store._conn)

        # -- extractors --------------------------------------------------------
        self._structural_extractor = StructuralExtractor()
        self._keyterm_extractor = KeyTermExtractor()
        self._ner_extractor: NERExtractor | None = None
        if settings.extract_depth == "ner":
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
        diff = self._file_tracker.diff(files)
        logger.info(
            "[%s] diff: %d new, %d modified, %d deleted, %d unchanged (%.2fs)",
            run_id, len(diff.new), len(diff.modified), len(diff.deleted), len(diff.unchanged),
            time.perf_counter() - t0,
        )

        if not diff.new and not diff.modified and not diff.deleted:
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

        stats = self._incremental_index(files, diff, data_dir=data_dir_str, run_id=run_id)
        logger.info("[%s] total: %.1fs (incremental)", run_id, time.perf_counter() - t_start)
        return stats

    def clear(self) -> None:
        """Delete all data from every backing store."""
        self._metadata_store.delete_all()  # also clears chunks_fts
        self._vector_store.delete_all()
        self._graph_store.delete_all()

        # Delete acronym dictionary
        if self._settings.acronyms_path.exists():
            self._settings.acronyms_path.unlink()

        logger.info("All stores cleared")

    # ------------------------------------------------------------------
    # Indexing strategies
    # ------------------------------------------------------------------

    def _full_index(
        self, files: list[FileInfo], *, data_dir: str | None = None, run_id: str = "",
    ) -> IndexStats:
        """Process all files from scratch (used for force=True)."""
        self.clear()
        self._file_tracker.clear()
        return self._ingest_and_finalize(
            files, list(files),
            diff_counts={"new": len(files), "modified": 0, "deleted": 0, "unchanged": 0},
            data_dir=data_dir, run_id=run_id,
        )

    def _incremental_index(
        self, all_files: list[FileInfo], diff: FileDiff,
        *, data_dir: str | None = None, run_id: str = "",
    ) -> IndexStats:
        """Process only changed files."""
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

        # 3. Determine files to ingest (new + modified)
        changed_paths = set(diff.new) | set(diff.modified)
        files_to_ingest = [fi for fi in all_files if str(fi.path) in changed_paths]

        # 4. Ingest changed files + finalize
        return self._ingest_and_finalize(
            all_files, files_to_ingest, overwrite_vectors=False,
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
        overwrite_vectors: bool = True,
        diff_counts: dict[str, int] | None = None,
        data_dir: str | None = None,
        run_id: str = "",
    ) -> IndexStats:
        """Ingest *files_to_ingest* and rebuild FTS5/stats from full corpus."""
        # Read and chunk only the files to ingest
        t0 = time.perf_counter()
        new_chunks: list[Chunk] = []
        for file_info in files_to_ingest:
            content = read_file(file_info.path)
            file_chunks = chunk_file(
                file_info.path,
                content,
                max_tokens=self._settings.max_chunk_tokens,
                overlap_tokens=self._settings.chunk_overlap_tokens,
            )
            new_chunks.extend(file_chunks)
        logger.info("[%s] chunk: %d chunks from %d files (%.2fs)", run_id, len(new_chunks), len(files_to_ingest), time.perf_counter() - t0)

        # Save chunks to metadata
        if new_chunks:
            t0 = time.perf_counter()
            self._metadata_store.save_chunks(new_chunks)
            logger.info("[%s] metadata_save: %d chunks (%.2fs)", run_id, len(new_chunks), time.perf_counter() - t0)

        # Encode and add to vector store
        if new_chunks:
            texts = [c.text for c in new_chunks]
            t0 = time.perf_counter()
            embeddings = self._semantic_engine.encode_batch(texts)
            t_embed = time.perf_counter() - t0
            logger.info("[%s] embed: %d chunks (%.1fs, %.0f chunks/s)", run_id, len(texts), t_embed, len(texts) / t_embed if t_embed > 0 else 0)

            t0 = time.perf_counter()
            self._vector_store.add_chunks(
                new_chunks, embeddings, overwrite=overwrite_vectors,
            )
            logger.info("[%s] vector_store: %d vectors (%.2fs)", run_id, len(new_chunks), time.perf_counter() - t0)

        # FTS5 incremental update
        if new_chunks:
            t0 = time.perf_counter()
            self._keyword_engine.add_chunks(new_chunks)
            logger.info("[%s] fts5: %d chunks (%.2fs)", run_id, len(new_chunks), time.perf_counter() - t0)

        # Extraction (structural + NER + key-terms) on NEW chunks only
        t0 = time.perf_counter()
        extraction_result = self._run_extraction(new_chunks)
        logger.info("[%s] extraction: %d entities, %d relations (%.1fs)", run_id, extraction_result.total_entities, extraction_result.total_relations, time.perf_counter() - t0)

        # Graph population for new chunks
        t0 = time.perf_counter()
        self._populate_graph(files_to_ingest, new_chunks, extraction_result)
        logger.info("[%s] graph: %d files, %d chunks (%.1fs)", run_id, len(files_to_ingest), len(new_chunks), time.perf_counter() - t0)

        # Acronym rebuild from ALL chunks (always full corpus)
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

        # Update fingerprints AFTER successful ingestion
        t0 = time.perf_counter()
        self._update_fingerprints(files_to_ingest)
        logger.info("[%s] fingerprints: %d files (%.2fs)", run_id, len(files_to_ingest), time.perf_counter() - t0)

        # Stats from full store (incremental: query actual graph counts)
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
        """Index a single file through the full pipeline.

        Purges any existing data for the file first, then processes it
        through all stores.  Used by the trickle indexer for
        one-at-a-time background processing.

        Returns the number of chunks created.
        """
        path_str = str(file_info.path)

        # Purge existing data (handles modified files)
        chunk_ids = self._metadata_store.get_chunk_ids_by_file(path_str)
        if chunk_ids:
            self._purge_file(path_str)
            logger.debug("Purged %d existing chunks for %s", len(chunk_ids), file_info.path.name)

        content = read_file(file_info.path)
        chunks = chunk_file(
            file_info.path,
            content,
            max_tokens=self._settings.max_chunk_tokens,
            overlap_tokens=self._settings.chunk_overlap_tokens,
        )

        if not chunks:
            return 0

        self._metadata_store.save_chunks(chunks)
        self._keyword_engine.add_chunks(chunks)

        texts = [c.text for c in chunks]
        embeddings = self._semantic_engine.encode_batch(texts)
        self._vector_store.add_chunks(chunks, embeddings, overwrite=False)

        extraction = self._run_extraction(chunks)
        self._populate_graph([file_info], chunks, extraction)
        self._update_fingerprints([file_info])

        return len(chunks)

    # ------------------------------------------------------------------
    # Per-file purge
    # ------------------------------------------------------------------

    def _purge_file(self, file_path: str) -> None:
        """Remove all indexed data for a single file from all stores.

        ORDERING MATTERS: chunk_ids must be fetched from metadata BEFORE
        metadata rows are deleted, because vector deletion needs them.
        """
        chunk_ids = self._metadata_store.get_chunk_ids_by_file(file_path)
        if chunk_ids:
            self._vector_store.delete_vectors_by_chunk_ids(chunk_ids)
            self._keyword_engine.remove_chunks(chunk_ids)
        self._metadata_store.delete_chunks_by_file(file_path)
        self._graph_store.delete_file_subgraph(file_path)
        self._file_tracker.remove_fingerprint(file_path)

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
                relation_type="CONTAINS",
            )

    # ------------------------------------------------------------------
    # Fingerprint management
    # ------------------------------------------------------------------

    def _update_fingerprints(self, files: list[FileInfo]) -> None:
        """Save fingerprints for successfully ingested files."""
        for fi in files:
            stat = fi.path.stat()
            checksum = hashlib.md5(fi.path.read_bytes()).hexdigest()
            self._file_tracker.save_fingerprint(
                str(fi.path), stat.st_mtime, stat.st_size, checksum,
            )

    # ------------------------------------------------------------------
    # Accessors (used by the service layer)
    # ------------------------------------------------------------------

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
    def file_tracker(self) -> FileTracker:
        return self._file_tracker
