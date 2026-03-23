"""End-to-end indexing pipeline for dotMD.

Orchestrates file discovery, chunking, embedding, BM25 index construction,
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
from dotmd.search.bm25 import BM25SearchEngine
from dotmd.search.semantic import SemanticSearchEngine
from dotmd.storage.base import VectorStoreProtocol
from dotmd.storage.graph import LadybugDBGraphStore
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
        self._graph_store = LadybugDBGraphStore(
            settings.graph_db_path, read_only=settings.read_only,
        )

        # -- file tracker (shares metadata store's connection) -----------------
        self._file_tracker = FileTracker(self._metadata_store._conn)

        # -- search engines (used for encoding during indexing) ----------------
        self._semantic_engine = SemanticSearchEngine(
            self._vector_store,
            settings.embedding_model,
            embedding_url=settings.embedding_url,
        )
        self._bm25_engine = BM25SearchEngine(settings.bm25_path)

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
        files = discover_files(directory)
        logger.info("Discovered %d files in %s", len(files), directory)
        data_dir_str = str(directory)

        if force:
            return self._full_index(files, data_dir=data_dir_str)

        diff = self._file_tracker.diff(files)
        logger.info(
            "File diff: %d new, %d modified, %d deleted, %d unchanged",
            len(diff.new), len(diff.modified), len(diff.deleted), len(diff.unchanged),
        )

        if not diff.new and not diff.modified and not diff.deleted:
            logger.info("No changes detected -- skipping indexing")
            stats = self._metadata_store.get_stats()
            if stats is None:
                stats = IndexStats()
            # Return stored totals but FRESH diff counts (Pitfall 3)
            stats.new_files = 0
            stats.modified_files = 0
            stats.deleted_files = 0
            stats.unchanged_files = len(diff.unchanged)
            stats.data_dir = data_dir_str
            return stats

        return self._incremental_index(files, diff, data_dir=data_dir_str)

    def clear(self) -> None:
        """Delete all data from every backing store."""
        self._metadata_store.delete_all()
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
        self, files: list[FileInfo], *, data_dir: str | None = None,
    ) -> IndexStats:
        """Process all files from scratch (used for force=True)."""
        self.clear()
        self._file_tracker.clear()
        return self._ingest_and_finalize(
            files, list(files),
            diff_counts={"new": len(files), "modified": 0, "deleted": 0, "unchanged": 0},
            data_dir=data_dir,
        )

    def _incremental_index(
        self, all_files: list[FileInfo], diff: FileDiff,
        *, data_dir: str | None = None,
    ) -> IndexStats:
        """Process only changed files."""
        # 1. Purge deleted files
        for path_str in diff.deleted:
            self._purge_file(path_str)
            self._file_tracker.remove_fingerprint(path_str)
            logger.info("Purged deleted file: %s", path_str)

        # 2. Purge modified files (data only, fingerprint updated after re-ingest)
        for path_str in diff.modified:
            self._purge_file(path_str)
            logger.info("Purged modified file: %s", path_str)

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
            data_dir=data_dir,
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
    ) -> IndexStats:
        """Ingest *files_to_ingest* and rebuild BM25/stats from full corpus."""
        # Read and chunk only the files to ingest
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

        logger.info(
            "Produced %d chunks from %d files",
            len(new_chunks), len(files_to_ingest),
        )

        # Save chunks to metadata
        if new_chunks:
            self._metadata_store.save_chunks(new_chunks)

        # Encode and add to vector store
        if new_chunks:
            texts = [c.text for c in new_chunks]
            logger.info("Encoding %d chunks...", len(texts))
            embeddings = self._semantic_engine.encode_batch(texts)
            self._vector_store.add_chunks(
                new_chunks, embeddings, overwrite=overwrite_vectors,
            )
            logger.info("Added %d vectors", len(new_chunks))

        # BM25 always full rebuild (IP-04)
        all_chunks = self._metadata_store.get_all_chunks()
        logger.info("Rebuilding BM25 from %d total chunks...", len(all_chunks))
        self._bm25_engine.build_index(all_chunks)

        # Extraction (structural + NER + key-terms) on NEW chunks only
        extraction_result = self._run_extraction(new_chunks)

        # Graph population for new chunks
        self._populate_graph(files_to_ingest, new_chunks, extraction_result)

        # Acronym rebuild from ALL chunks (same as BM25 -- always full)
        acronym_dict = extract_acronyms_from_chunks(all_chunks)
        if acronym_dict:
            import json

            self._settings.acronyms_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._settings.acronyms_path, "w") as f:
                json.dump(acronym_dict, f, indent=2)
            logger.info("Extracted %d acronyms", len(acronym_dict))

        # Update fingerprints AFTER successful ingestion (Pitfall 3)
        self._update_fingerprints(files_to_ingest)

        # Stats from full store (Pitfall 6)
        all_entities_count = extraction_result.total_entities
        all_edges_count = extraction_result.total_relations
        # For incremental, use graph store counts for accuracy
        if not overwrite_vectors:
            try:
                all_entities_count = self._graph_store.node_count()
                all_edges_count = self._graph_store.edge_count()
            except Exception:
                pass

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
        logger.info("Indexing complete: %s", stats)
        return stats

    # ------------------------------------------------------------------
    # Per-file purge
    # ------------------------------------------------------------------

    def _purge_file(self, file_path: str) -> None:
        """Remove all indexed data for a single file from all stores.

        ORDERING MATTERS: chunk_ids must be fetched from metadata BEFORE
        metadata rows are deleted, because vector deletion needs them.
        """
        # 1. Get chunk IDs (MUST be before metadata delete)
        chunk_ids = self._metadata_store.get_chunk_ids_by_file(file_path)
        # 2. Delete vectors (needs chunk_ids from step 1)
        if chunk_ids:
            self._vector_store.delete_vectors_by_chunk_ids(chunk_ids)
        # 3. Delete metadata chunks
        self._metadata_store.delete_chunks_by_file(file_path)
        # 4. Delete graph subgraph
        self._graph_store.delete_file_subgraph(file_path)

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
        """Return the metadata store instance."""
        return self._metadata_store

    @property
    def vector_store(self) -> VectorStoreProtocol:
        """Return the vector store instance."""
        return self._vector_store

    @property
    def graph_store(self) -> LadybugDBGraphStore:
        """Return the graph store instance."""
        return self._graph_store

    @property
    def semantic_engine(self) -> SemanticSearchEngine:
        """Return the semantic search engine instance."""
        return self._semantic_engine

    @property
    def bm25_engine(self) -> BM25SearchEngine:
        """Return the BM25 search engine instance."""
        return self._bm25_engine

    @property
    def file_tracker(self) -> FileTracker:
        """Return the file tracker instance."""
        return self._file_tracker
