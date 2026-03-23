"""Tests for incremental (diff-based) indexing in IndexingPipeline."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from dotmd.core.models import Chunk, ExtractionResult, FileInfo, IndexStats
from dotmd.ingestion.file_tracker import FileDiff


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
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def md_dir(tmp_path: Path) -> Path:
    """Create a temp directory with markdown files."""
    d = tmp_path / "docs"
    d.mkdir()
    (d / "a.md").write_text("# File A\nContent of file A.")
    (d / "b.md").write_text("# File B\nContent of file B.")
    return d


@pytest.fixture
def index_dir(tmp_path: Path) -> Path:
    """Return a temp directory for index storage."""
    d = tmp_path / "index"
    d.mkdir()
    return d


@pytest.fixture
def mock_settings(index_dir: Path):
    """Return a Settings-like mock with paths pointing to temp dirs."""
    settings = MagicMock()
    settings.index_dir = index_dir
    settings.sqlite_path = index_dir / "metadata.db"
    settings.sqlite_vec_path = index_dir / "vec.db"
    settings.graph_db_path = index_dir / "graphdb"
    settings.bm25_path = index_dir / "bm25_index.pkl"
    settings.acronyms_path = index_dir / "acronyms.json"
    settings.embedding_model = "test-model"
    settings.embedding_url = None
    settings.extract_depth = "structural"  # skip NER for speed
    settings.ner_entity_types = []
    settings.max_chunk_tokens = 512
    settings.chunk_overlap_tokens = 50
    settings.read_only = False
    settings.vector_backend = "sqlite-vec"
    settings.lancedb_path = index_dir / "lancedb"
    return settings


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFirstIndex:
    """First index (no fingerprints) treats all files as new."""

    @patch("dotmd.ingestion.pipeline.discover_files")
    @patch("dotmd.ingestion.pipeline.read_file")
    @patch("dotmd.ingestion.pipeline.chunk_file")
    def test_first_index_ingests_all_files(
        self, mock_chunk_file, mock_read_file, mock_discover, md_dir, mock_settings
    ):
        from dotmd.ingestion.pipeline import IndexingPipeline

        file_a = _make_file_info(str(md_dir / "a.md"), "File A")
        file_b = _make_file_info(str(md_dir / "b.md"), "File B")
        mock_discover.return_value = [file_a, file_b]
        mock_read_file.return_value = "# Test\nSome content."
        chunk_a = _make_chunk("a-0", str(md_dir / "a.md"))
        chunk_b = _make_chunk("b-0", str(md_dir / "b.md"))
        mock_chunk_file.side_effect = [[chunk_a], [chunk_b]]

        pipeline = IndexingPipeline(mock_settings)
        # Mock the encode_batch to return dummy embeddings
        pipeline._semantic_engine.encode_batch = MagicMock(return_value=_dummy_embeddings(2))

        stats = pipeline.index(md_dir)

        assert stats.total_files == 2
        assert stats.total_chunks == 2
        # Verify chunks were saved
        assert mock_read_file.call_count == 2
        assert mock_chunk_file.call_count == 2


class TestUnchangedFiles:
    """Unchanged files are skipped entirely."""

    @patch("dotmd.ingestion.pipeline.discover_files")
    @patch("dotmd.ingestion.pipeline.read_file")
    @patch("dotmd.ingestion.pipeline.chunk_file")
    def test_unchanged_files_skip_embedding(
        self, mock_chunk_file, mock_read_file, mock_discover, md_dir, mock_settings
    ):
        from dotmd.ingestion.pipeline import IndexingPipeline

        file_a = _make_file_info(str(md_dir / "a.md"), "File A")
        file_b = _make_file_info(str(md_dir / "b.md"), "File B")
        mock_discover.return_value = [file_a, file_b]
        mock_read_file.return_value = "# Test\nSome content."
        chunk_a = _make_chunk("a-0", str(md_dir / "a.md"))
        chunk_b = _make_chunk("b-0", str(md_dir / "b.md"))
        mock_chunk_file.side_effect = [[chunk_a], [chunk_b]]

        pipeline = IndexingPipeline(mock_settings)
        pipeline._semantic_engine.encode_batch = MagicMock(return_value=_dummy_embeddings(2))

        # First index -- all files new
        pipeline.index(md_dir)

        # Reset mocks for second call
        mock_read_file.reset_mock()
        mock_chunk_file.reset_mock()
        pipeline._semantic_engine.encode_batch.reset_mock()
        mock_discover.return_value = [file_a, file_b]

        # Second index -- nothing changed
        stats = pipeline.index(md_dir)

        # No reads, no chunks, no embedding
        assert mock_read_file.call_count == 0
        assert mock_chunk_file.call_count == 0
        assert pipeline._semantic_engine.encode_batch.call_count == 0
        assert stats.total_files >= 0  # just not an error


class TestModifiedFile:
    """Modified files get purged from all stores then re-ingested."""

    @patch("dotmd.ingestion.pipeline.discover_files")
    @patch("dotmd.ingestion.pipeline.read_file")
    @patch("dotmd.ingestion.pipeline.chunk_file")
    def test_modified_file_purges_then_reingests(
        self, mock_chunk_file, mock_read_file, mock_discover, md_dir, mock_settings
    ):
        from dotmd.ingestion.pipeline import IndexingPipeline

        file_a = _make_file_info(str(md_dir / "a.md"), "File A")
        file_b = _make_file_info(str(md_dir / "b.md"), "File B")
        mock_discover.return_value = [file_a, file_b]
        mock_read_file.return_value = "# Test\nSome content."
        chunk_a = _make_chunk("a-0", str(md_dir / "a.md"))
        chunk_b = _make_chunk("b-0", str(md_dir / "b.md"))
        mock_chunk_file.side_effect = [[chunk_a], [chunk_b]]

        pipeline = IndexingPipeline(mock_settings)
        pipeline._semantic_engine.encode_batch = MagicMock(return_value=_dummy_embeddings(2))

        # First index
        pipeline.index(md_dir)

        # Modify file a
        (md_dir / "a.md").write_text("# File A\nUpdated content of file A.")

        # Reset mocks
        mock_read_file.reset_mock()
        mock_chunk_file.reset_mock()
        pipeline._semantic_engine.encode_batch.reset_mock()

        file_a_modified = _make_file_info(str(md_dir / "a.md"), "File A")
        mock_discover.return_value = [file_a_modified, file_b]
        chunk_a_new = _make_chunk("a-0-new", str(md_dir / "a.md"))
        mock_chunk_file.return_value = [chunk_a_new]
        mock_read_file.return_value = "# File A\nUpdated content of file A."
        pipeline._semantic_engine.encode_batch = MagicMock(return_value=_dummy_embeddings(1))

        stats = pipeline.index(md_dir)

        # Only file A should be re-read (modified), not file B (unchanged)
        assert mock_read_file.call_count == 1
        assert mock_chunk_file.call_count == 1
        assert stats.total_chunks >= 1


class TestDeletedFile:
    """Deleted files get purged and fingerprint removed."""

    @patch("dotmd.ingestion.pipeline.discover_files")
    @patch("dotmd.ingestion.pipeline.read_file")
    @patch("dotmd.ingestion.pipeline.chunk_file")
    def test_deleted_file_purges_and_removes_fingerprint(
        self, mock_chunk_file, mock_read_file, mock_discover, md_dir, mock_settings
    ):
        from dotmd.ingestion.pipeline import IndexingPipeline

        file_a = _make_file_info(str(md_dir / "a.md"), "File A")
        file_b = _make_file_info(str(md_dir / "b.md"), "File B")
        mock_discover.return_value = [file_a, file_b]
        mock_read_file.return_value = "# Test\nSome content."
        chunk_a = _make_chunk("a-0", str(md_dir / "a.md"))
        chunk_b = _make_chunk("b-0", str(md_dir / "b.md"))
        mock_chunk_file.side_effect = [[chunk_a], [chunk_b]]

        pipeline = IndexingPipeline(mock_settings)
        pipeline._semantic_engine.encode_batch = MagicMock(return_value=_dummy_embeddings(2))

        # First index
        pipeline.index(md_dir)

        # Delete file a
        (md_dir / "a.md").unlink()

        # Reset mocks
        mock_read_file.reset_mock()
        mock_chunk_file.reset_mock()
        pipeline._semantic_engine.encode_batch.reset_mock()

        # Only file b remains
        file_b_again = _make_file_info(str(md_dir / "b.md"), "File B")
        mock_discover.return_value = [file_b_again]

        stats = pipeline.index(md_dir)

        # No new files to read (b is unchanged)
        assert mock_read_file.call_count == 0
        # File a's fingerprint should be gone
        cursor = pipeline._metadata_store._conn.execute(
            "SELECT COUNT(*) FROM file_fingerprints WHERE file_path = ?",
            (str(md_dir / "a.md"),),
        )
        assert cursor.fetchone()[0] == 0


class TestNewFileAdded:
    """New file added is ingested without touching existing data."""

    @patch("dotmd.ingestion.pipeline.discover_files")
    @patch("dotmd.ingestion.pipeline.read_file")
    @patch("dotmd.ingestion.pipeline.chunk_file")
    def test_new_file_ingested_existing_untouched(
        self, mock_chunk_file, mock_read_file, mock_discover, md_dir, mock_settings
    ):
        from dotmd.ingestion.pipeline import IndexingPipeline

        file_a = _make_file_info(str(md_dir / "a.md"), "File A")
        mock_discover.return_value = [file_a]
        mock_read_file.return_value = "# Test\nSome content."
        chunk_a = _make_chunk("a-0", str(md_dir / "a.md"))
        mock_chunk_file.return_value = [chunk_a]

        pipeline = IndexingPipeline(mock_settings)
        pipeline._semantic_engine.encode_batch = MagicMock(return_value=_dummy_embeddings(1))

        # First index with file a only
        pipeline.index(md_dir)

        # Add file c
        (md_dir / "c.md").write_text("# File C\nBrand new file.")

        # Reset mocks
        mock_read_file.reset_mock()
        mock_chunk_file.reset_mock()
        pipeline._semantic_engine.encode_batch.reset_mock()

        file_c = _make_file_info(str(md_dir / "c.md"), "File C")
        mock_discover.return_value = [file_a, file_c]
        chunk_c = _make_chunk("c-0", str(md_dir / "c.md"))
        mock_chunk_file.return_value = [chunk_c]
        mock_read_file.return_value = "# File C\nBrand new file."
        pipeline._semantic_engine.encode_batch = MagicMock(return_value=_dummy_embeddings(1))

        stats = pipeline.index(md_dir)

        # Only file c should be read (new), not file a (unchanged)
        assert mock_read_file.call_count == 1
        assert stats.total_files == 2  # both files counted


class TestBM25RebuildAfterChanges:
    """BM25 is always rebuilt from all chunks after every incremental run."""

    @patch("dotmd.ingestion.pipeline.discover_files")
    @patch("dotmd.ingestion.pipeline.read_file")
    @patch("dotmd.ingestion.pipeline.chunk_file")
    def test_bm25_rebuilt_on_delete(
        self, mock_chunk_file, mock_read_file, mock_discover, md_dir, mock_settings
    ):
        from dotmd.ingestion.pipeline import IndexingPipeline

        file_a = _make_file_info(str(md_dir / "a.md"), "File A")
        file_b = _make_file_info(str(md_dir / "b.md"), "File B")
        mock_discover.return_value = [file_a, file_b]
        mock_read_file.return_value = "# Test\nSome content."
        chunk_a = _make_chunk("a-0", str(md_dir / "a.md"))
        chunk_b = _make_chunk("b-0", str(md_dir / "b.md"))
        mock_chunk_file.side_effect = [[chunk_a], [chunk_b]]

        pipeline = IndexingPipeline(mock_settings)
        pipeline._semantic_engine.encode_batch = MagicMock(return_value=_dummy_embeddings(2))

        # First index
        pipeline.index(md_dir)

        # Spy on bm25 build_index
        pipeline._bm25_engine.build_index = MagicMock()

        # Delete file a
        (md_dir / "a.md").unlink()
        mock_read_file.reset_mock()
        mock_chunk_file.reset_mock()

        file_b_again = _make_file_info(str(md_dir / "b.md"), "File B")
        mock_discover.return_value = [file_b_again]

        pipeline.index(md_dir)

        # BM25 should be rebuilt even though only a deletion happened
        assert pipeline._bm25_engine.build_index.call_count == 1


class TestFingerprintTiming:
    """Fingerprints are saved AFTER successful ingestion, not before."""

    @patch("dotmd.ingestion.pipeline.discover_files")
    @patch("dotmd.ingestion.pipeline.read_file")
    @patch("dotmd.ingestion.pipeline.chunk_file")
    def test_fingerprints_saved_after_ingestion(
        self, mock_chunk_file, mock_read_file, mock_discover, md_dir, mock_settings
    ):
        from dotmd.ingestion.pipeline import IndexingPipeline

        file_a = _make_file_info(str(md_dir / "a.md"), "File A")
        mock_discover.return_value = [file_a]
        mock_read_file.return_value = "# Test\nSome content."
        chunk_a = _make_chunk("a-0", str(md_dir / "a.md"))
        mock_chunk_file.return_value = [chunk_a]

        pipeline = IndexingPipeline(mock_settings)

        # Track the order of operations
        call_order = []
        original_encode = pipeline._semantic_engine.encode_batch

        def tracking_encode(texts):
            call_order.append("encode")
            return _dummy_embeddings(len(texts))

        def tracking_save_fp(*args):
            call_order.append("save_fingerprint")
            return original_save_fp(*args)

        pipeline._semantic_engine.encode_batch = tracking_encode
        original_save_fp = pipeline._file_tracker.save_fingerprint
        pipeline._file_tracker.save_fingerprint = tracking_save_fp

        pipeline.index(md_dir)

        # Fingerprint must come AFTER encoding
        assert "encode" in call_order
        assert "save_fingerprint" in call_order
        assert call_order.index("encode") < call_order.index("save_fingerprint")


class TestPurgeFileOrder:
    """_purge_file calls stores in correct order."""

    @patch("dotmd.ingestion.pipeline.discover_files")
    @patch("dotmd.ingestion.pipeline.read_file")
    @patch("dotmd.ingestion.pipeline.chunk_file")
    def test_purge_file_gets_chunk_ids_before_delete(
        self, mock_chunk_file, mock_read_file, mock_discover, md_dir, mock_settings
    ):
        from dotmd.ingestion.pipeline import IndexingPipeline

        file_a = _make_file_info(str(md_dir / "a.md"), "File A")
        mock_discover.return_value = [file_a]
        mock_read_file.return_value = "# Test\nSome content."
        chunk_a = _make_chunk("a-0", str(md_dir / "a.md"))
        mock_chunk_file.return_value = [chunk_a]

        pipeline = IndexingPipeline(mock_settings)
        pipeline._semantic_engine.encode_batch = MagicMock(return_value=_dummy_embeddings(1))

        # First index
        pipeline.index(md_dir)

        # Track call order during purge
        call_order = []
        original_get_ids = pipeline._metadata_store.get_chunk_ids_by_file
        original_delete_vecs = pipeline._vector_store.delete_vectors_by_chunk_ids
        original_delete_chunks = pipeline._metadata_store.delete_chunks_by_file
        original_delete_graph = pipeline._graph_store.delete_file_subgraph

        def track_get_ids(fp):
            call_order.append("get_chunk_ids_by_file")
            return original_get_ids(fp)

        def track_delete_vecs(ids):
            call_order.append("delete_vectors_by_chunk_ids")
            return original_delete_vecs(ids)

        def track_delete_chunks(fp):
            call_order.append("delete_chunks_by_file")
            return original_delete_chunks(fp)

        def track_delete_graph(fp):
            call_order.append("delete_file_subgraph")
            return original_delete_graph(fp)

        pipeline._metadata_store.get_chunk_ids_by_file = track_get_ids
        pipeline._vector_store.delete_vectors_by_chunk_ids = track_delete_vecs
        pipeline._metadata_store.delete_chunks_by_file = track_delete_chunks
        pipeline._graph_store.delete_file_subgraph = track_delete_graph

        pipeline._purge_file(str(md_dir / "a.md"))

        # Verify order: get_chunk_ids BEFORE delete_chunks
        assert call_order.index("get_chunk_ids_by_file") < call_order.index("delete_vectors_by_chunk_ids")
        assert call_order.index("delete_vectors_by_chunk_ids") < call_order.index("delete_chunks_by_file")
        assert call_order.index("delete_chunks_by_file") < call_order.index("delete_file_subgraph")


class TestForceReindex:
    """force=True processes all files regardless of fingerprints."""

    @patch("dotmd.ingestion.pipeline.discover_files")
    @patch("dotmd.ingestion.pipeline.read_file")
    @patch("dotmd.ingestion.pipeline.chunk_file")
    def test_force_processes_all_files(
        self, mock_chunk_file, mock_read_file, mock_discover, md_dir, mock_settings
    ):
        from dotmd.ingestion.pipeline import IndexingPipeline

        file_a = _make_file_info(str(md_dir / "a.md"), "File A")
        file_b = _make_file_info(str(md_dir / "b.md"), "File B")
        mock_discover.return_value = [file_a, file_b]
        mock_read_file.return_value = "# Test\nSome content."
        chunk_a = _make_chunk("a-0", str(md_dir / "a.md"))
        chunk_b = _make_chunk("b-0", str(md_dir / "b.md"))
        mock_chunk_file.side_effect = [[chunk_a], [chunk_b]]

        pipeline = IndexingPipeline(mock_settings)
        pipeline._semantic_engine.encode_batch = MagicMock(return_value=_dummy_embeddings(2))

        # First index
        pipeline.index(md_dir)

        # Reset mocks
        mock_read_file.reset_mock()
        mock_chunk_file.reset_mock()
        pipeline._semantic_engine.encode_batch.reset_mock()

        mock_discover.return_value = [file_a, file_b]
        mock_chunk_file.side_effect = [[chunk_a], [chunk_b]]
        pipeline._semantic_engine.encode_batch = MagicMock(return_value=_dummy_embeddings(2))

        # force=True should process all files even though nothing changed
        stats = pipeline.index(md_dir, force=True)

        assert mock_read_file.call_count == 2
        assert mock_chunk_file.call_count == 2
        assert stats.total_files == 2

    @patch("dotmd.ingestion.pipeline.discover_files")
    @patch("dotmd.ingestion.pipeline.read_file")
    @patch("dotmd.ingestion.pipeline.chunk_file")
    def test_force_clears_fingerprints(
        self, mock_chunk_file, mock_read_file, mock_discover, md_dir, mock_settings
    ):
        from dotmd.ingestion.pipeline import IndexingPipeline

        file_a = _make_file_info(str(md_dir / "a.md"), "File A")
        mock_discover.return_value = [file_a]
        mock_read_file.return_value = "# Test\nSome content."
        chunk_a = _make_chunk("a-0", str(md_dir / "a.md"))
        mock_chunk_file.return_value = [chunk_a]

        pipeline = IndexingPipeline(mock_settings)
        pipeline._semantic_engine.encode_batch = MagicMock(return_value=_dummy_embeddings(1))

        # First index
        pipeline.index(md_dir)

        # Verify fingerprint exists
        cursor = pipeline._metadata_store._conn.execute(
            "SELECT COUNT(*) FROM file_fingerprints"
        )
        assert cursor.fetchone()[0] == 1

        # Spy on file_tracker.clear
        original_clear = pipeline._file_tracker.clear
        clear_called = []

        def tracking_clear():
            clear_called.append(True)
            return original_clear()

        pipeline._file_tracker.clear = tracking_clear

        # Reset mocks for force=True run
        mock_read_file.reset_mock()
        mock_chunk_file.reset_mock()
        mock_discover.return_value = [file_a]
        mock_chunk_file.return_value = [chunk_a]
        pipeline._semantic_engine.encode_batch = MagicMock(return_value=_dummy_embeddings(1))

        pipeline.index(md_dir, force=True)

        assert len(clear_called) > 0, "file_tracker.clear() must be called during force=True"
