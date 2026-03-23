"""Tests for diff count reporting through IndexStats, metadata store, and pipeline."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dotmd.core.models import Chunk, ExtractionResult, FileInfo, IndexStats
from dotmd.ingestion.file_tracker import FileDiff
from dotmd.storage.metadata import SQLiteMetadataStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file_info(path: str, title: str = "Test") -> FileInfo:
    """Create a FileInfo for a real temp file."""
    p = Path(path)
    return FileInfo(
        path=p,
        title=title,
        last_modified=datetime(2026, 1, 1),
        size_bytes=p.stat().st_size,
    )


def _make_chunk(chunk_id: str, file_path: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        file_path=Path(file_path),
        heading_hierarchy=["Test"],
        level=1,
        text=f"Content of {chunk_id}",
        chunk_index=0,
        char_offset=0,
    )


def _dummy_embeddings(n: int) -> list[list[float]]:
    return [[0.1] * 4 for _ in range(n)]


# ---------------------------------------------------------------------------
# Test 1: IndexStats model fields
# ---------------------------------------------------------------------------


class TestIndexStatsModelFields:
    """IndexStats model accepts new diff fields and data_dir."""

    def test_new_files_default(self):
        stats = IndexStats()
        assert stats.new_files == 0

    def test_modified_files_default(self):
        stats = IndexStats()
        assert stats.modified_files == 0

    def test_deleted_files_default(self):
        stats = IndexStats()
        assert stats.deleted_files == 0

    def test_unchanged_files_default(self):
        stats = IndexStats()
        assert stats.unchanged_files == 0

    def test_data_dir_default(self):
        stats = IndexStats()
        assert stats.data_dir is None

    def test_all_fields_set(self):
        stats = IndexStats(
            total_files=10,
            total_chunks=50,
            total_entities=100,
            total_edges=200,
            new_files=3,
            modified_files=2,
            deleted_files=1,
            unchanged_files=4,
            data_dir="/some/path",
        )
        assert stats.new_files == 3
        assert stats.modified_files == 2
        assert stats.deleted_files == 1
        assert stats.unchanged_files == 4
        assert stats.data_dir == "/some/path"


# ---------------------------------------------------------------------------
# Test 2: Metadata store save/get round-trip with new columns
# ---------------------------------------------------------------------------


class TestMetadataStoreDiffFields:
    """SQLiteMetadataStore persists and reads diff fields and data_dir."""

    def test_save_and_get_with_diff_fields(self, metadata_store: SQLiteMetadataStore):
        now = datetime.now(tz=timezone.utc)
        stats = IndexStats(
            total_files=10,
            total_chunks=50,
            total_entities=100,
            total_edges=200,
            last_indexed=now,
            new_files=3,
            modified_files=2,
            deleted_files=1,
            unchanged_files=4,
            data_dir="/test/data",
        )
        metadata_store.save_stats(stats)

        loaded = metadata_store.get_stats()
        assert loaded is not None
        assert loaded.new_files == 3
        assert loaded.modified_files == 2
        assert loaded.deleted_files == 1
        assert loaded.unchanged_files == 4
        assert loaded.data_dir == "/test/data"
        assert loaded.total_files == 10
        assert loaded.total_chunks == 50


# ---------------------------------------------------------------------------
# Test 3: Schema migration is idempotent
# ---------------------------------------------------------------------------


class TestSchemaMigration:
    """ALTER TABLE runs without error on fresh DB and on DB with columns."""

    def test_migration_idempotent(self, tmp_dir: Path):
        """Creating two stores on same DB should not fail."""
        db_path = tmp_dir / "idempotent.db"
        store1 = SQLiteMetadataStore(db_path)
        store2 = SQLiteMetadataStore(db_path)
        # Both should work without error
        stats = IndexStats(new_files=5, data_dir="/test")
        store2.save_stats(stats)
        loaded = store2.get_stats()
        assert loaded is not None
        assert loaded.new_files == 5


# ---------------------------------------------------------------------------
# Test 4: get_stats on old-schema DB
# ---------------------------------------------------------------------------


class TestOldSchemaCompat:
    """get_stats on a DB without new columns returns defaults."""

    def test_old_schema_returns_defaults(self, tmp_dir: Path):
        db_path = tmp_dir / "old_schema.db"
        conn = sqlite3.connect(str(db_path))
        # Create the OLD schema (without new columns)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                heading_hierarchy TEXT NOT NULL DEFAULT '[]',
                level INTEGER NOT NULL DEFAULT 0,
                text TEXT NOT NULL DEFAULT '',
                chunk_index INTEGER NOT NULL DEFAULT 0,
                char_offset INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                id INTEGER PRIMARY KEY DEFAULT 1,
                total_files INTEGER NOT NULL DEFAULT 0,
                total_chunks INTEGER NOT NULL DEFAULT 0,
                total_entities INTEGER NOT NULL DEFAULT 0,
                total_edges INTEGER NOT NULL DEFAULT 0,
                last_indexed TEXT
            )
        """)
        conn.execute(
            "INSERT INTO stats (id, total_files, total_chunks, total_entities, total_edges, last_indexed) "
            "VALUES (1, 10, 50, 100, 200, '2026-01-01T00:00:00+00:00')"
        )
        conn.commit()
        conn.close()

        # Now open via SQLiteMetadataStore -- migration should add columns
        store = SQLiteMetadataStore(db_path)
        loaded = store.get_stats()
        assert loaded is not None
        assert loaded.total_files == 10
        assert loaded.total_chunks == 50
        assert loaded.new_files == 0
        assert loaded.modified_files == 0
        assert loaded.deleted_files == 0
        assert loaded.unchanged_files == 0
        assert loaded.data_dir is None


# ---------------------------------------------------------------------------
# Test 5: Pipeline incremental path populates diff counts
# ---------------------------------------------------------------------------


class TestPipelineIncrementalDiffCounts:
    """_incremental_index populates diff counts in IndexStats."""

    @patch("dotmd.ingestion.pipeline.discover_files")
    @patch("dotmd.ingestion.pipeline.read_file")
    @patch("dotmd.ingestion.pipeline.chunk_file")
    def test_incremental_index_has_diff_counts(
        self, mock_chunk_file, mock_read_file, mock_discover, tmp_path
    ):
        from dotmd.ingestion.pipeline import IndexingPipeline

        # Create temp files and index dir
        md_dir = tmp_path / "docs"
        md_dir.mkdir()
        (md_dir / "a.md").write_text("# File A\nContent A")
        (md_dir / "b.md").write_text("# File B\nContent B")
        index_dir = tmp_path / "index"
        index_dir.mkdir()

        settings = MagicMock()
        settings.index_dir = index_dir
        settings.sqlite_path = index_dir / "metadata.db"
        settings.sqlite_vec_path = index_dir / "vec.db"
        settings.graph_db_path = index_dir / "graphdb"
        settings.bm25_path = index_dir / "bm25_index.pkl"
        settings.acronyms_path = index_dir / "acronyms.json"
        settings.embedding_model = "test-model"
        settings.embedding_url = "http://test:8088"
        settings.extract_depth = "structural"
        settings.ner_entity_types = []
        settings.max_chunk_tokens = 512
        settings.chunk_overlap_tokens = 50
        settings.read_only = False
        settings.vector_backend = "sqlite-vec"
        settings.lancedb_path = index_dir / "lancedb"

        file_a = _make_file_info(str(md_dir / "a.md"), "File A")
        file_b = _make_file_info(str(md_dir / "b.md"), "File B")
        mock_discover.return_value = [file_a, file_b]
        mock_read_file.return_value = "# Test\nSome content."
        chunk_a = _make_chunk("a-0", str(md_dir / "a.md"))
        chunk_b = _make_chunk("b-0", str(md_dir / "b.md"))
        mock_chunk_file.side_effect = [[chunk_a], [chunk_b]]

        pipeline = IndexingPipeline(settings)
        pipeline._semantic_engine.encode_batch = MagicMock(return_value=_dummy_embeddings(2))

        # First index -- all files are new
        stats = pipeline.index(md_dir)
        assert stats.new_files == 2
        assert stats.modified_files == 0
        assert stats.deleted_files == 0
        assert stats.unchanged_files == 0

        # Modify file a
        (md_dir / "a.md").write_text("# File A\nUpdated content.")

        # Reset mocks
        mock_read_file.reset_mock()
        mock_chunk_file.reset_mock()
        mock_chunk_file.side_effect = None
        pipeline._semantic_engine.encode_batch.reset_mock()

        file_a_mod = _make_file_info(str(md_dir / "a.md"), "File A")
        mock_discover.return_value = [file_a_mod, file_b]
        chunk_a_new = _make_chunk("a-0-new", str(md_dir / "a.md"))
        mock_chunk_file.return_value = [chunk_a_new]
        mock_read_file.return_value = "# File A\nUpdated content."
        pipeline._semantic_engine.encode_batch = MagicMock(return_value=_dummy_embeddings(1))

        # Second index -- file a modified, file b unchanged
        stats = pipeline.index(md_dir)
        assert stats.new_files == 0
        assert stats.modified_files == 1
        assert stats.deleted_files == 0
        assert stats.unchanged_files == 1


# ---------------------------------------------------------------------------
# Test 6: Pipeline full_index sets new_files=len(files)
# ---------------------------------------------------------------------------


class TestPipelineFullIndexDiffCounts:
    """_full_index sets new_files=len(files), others=0."""

    @patch("dotmd.ingestion.pipeline.discover_files")
    @patch("dotmd.ingestion.pipeline.read_file")
    @patch("dotmd.ingestion.pipeline.chunk_file")
    def test_force_index_all_new(
        self, mock_chunk_file, mock_read_file, mock_discover, tmp_path
    ):
        from dotmd.ingestion.pipeline import IndexingPipeline

        md_dir = tmp_path / "docs"
        md_dir.mkdir()
        (md_dir / "a.md").write_text("# A\nContent A")
        (md_dir / "b.md").write_text("# B\nContent B")
        (md_dir / "c.md").write_text("# C\nContent C")
        index_dir = tmp_path / "index"
        index_dir.mkdir()

        settings = MagicMock()
        settings.index_dir = index_dir
        settings.sqlite_path = index_dir / "metadata.db"
        settings.sqlite_vec_path = index_dir / "vec.db"
        settings.graph_db_path = index_dir / "graphdb"
        settings.bm25_path = index_dir / "bm25_index.pkl"
        settings.acronyms_path = index_dir / "acronyms.json"
        settings.embedding_model = "test-model"
        settings.embedding_url = "http://test:8088"
        settings.extract_depth = "structural"
        settings.ner_entity_types = []
        settings.max_chunk_tokens = 512
        settings.chunk_overlap_tokens = 50
        settings.read_only = False
        settings.vector_backend = "sqlite-vec"
        settings.lancedb_path = index_dir / "lancedb"

        file_a = _make_file_info(str(md_dir / "a.md"))
        file_b = _make_file_info(str(md_dir / "b.md"))
        file_c = _make_file_info(str(md_dir / "c.md"))
        mock_discover.return_value = [file_a, file_b, file_c]
        mock_read_file.return_value = "# Test\nContent."
        mock_chunk_file.side_effect = [
            [_make_chunk("a-0", str(md_dir / "a.md"))],
            [_make_chunk("b-0", str(md_dir / "b.md"))],
            [_make_chunk("c-0", str(md_dir / "c.md"))],
        ]

        pipeline = IndexingPipeline(settings)
        pipeline._semantic_engine.encode_batch = MagicMock(return_value=_dummy_embeddings(3))

        stats = pipeline.index(md_dir, force=True)
        assert stats.new_files == 3
        assert stats.modified_files == 0
        assert stats.deleted_files == 0
        assert stats.unchanged_files == 0


# ---------------------------------------------------------------------------
# Test 7: No-changes short-circuit returns fresh diff counts
# ---------------------------------------------------------------------------


class TestPipelineNoChangesDiffCounts:
    """No-changes short-circuit returns unchanged_files=len(unchanged), other diff fields=0."""

    @patch("dotmd.ingestion.pipeline.discover_files")
    @patch("dotmd.ingestion.pipeline.read_file")
    @patch("dotmd.ingestion.pipeline.chunk_file")
    def test_no_changes_fresh_counts(
        self, mock_chunk_file, mock_read_file, mock_discover, tmp_path
    ):
        from dotmd.ingestion.pipeline import IndexingPipeline

        md_dir = tmp_path / "docs"
        md_dir.mkdir()
        (md_dir / "a.md").write_text("# A\nContent A")
        (md_dir / "b.md").write_text("# B\nContent B")
        index_dir = tmp_path / "index"
        index_dir.mkdir()

        settings = MagicMock()
        settings.index_dir = index_dir
        settings.sqlite_path = index_dir / "metadata.db"
        settings.sqlite_vec_path = index_dir / "vec.db"
        settings.graph_db_path = index_dir / "graphdb"
        settings.bm25_path = index_dir / "bm25_index.pkl"
        settings.acronyms_path = index_dir / "acronyms.json"
        settings.embedding_model = "test-model"
        settings.embedding_url = "http://test:8088"
        settings.extract_depth = "structural"
        settings.ner_entity_types = []
        settings.max_chunk_tokens = 512
        settings.chunk_overlap_tokens = 50
        settings.read_only = False
        settings.vector_backend = "sqlite-vec"
        settings.lancedb_path = index_dir / "lancedb"

        file_a = _make_file_info(str(md_dir / "a.md"))
        file_b = _make_file_info(str(md_dir / "b.md"))
        mock_discover.return_value = [file_a, file_b]
        mock_read_file.return_value = "# Test\nContent."
        mock_chunk_file.side_effect = [
            [_make_chunk("a-0", str(md_dir / "a.md"))],
            [_make_chunk("b-0", str(md_dir / "b.md"))],
        ]

        pipeline = IndexingPipeline(settings)
        pipeline._semantic_engine.encode_batch = MagicMock(return_value=_dummy_embeddings(2))

        # First index
        pipeline.index(md_dir)

        # Reset
        mock_read_file.reset_mock()
        mock_chunk_file.reset_mock()
        mock_chunk_file.side_effect = None
        pipeline._semantic_engine.encode_batch.reset_mock()
        mock_discover.return_value = [file_a, file_b]

        # Second run -- no changes
        stats = pipeline.index(md_dir)

        # Must return FRESH diff counts, not stale stored values
        assert stats.new_files == 0
        assert stats.modified_files == 0
        assert stats.deleted_files == 0
        assert stats.unchanged_files == 2
        # data_dir should be populated
        assert stats.data_dir == str(md_dir)
