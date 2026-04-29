"""Tests for incremental (diff-based) indexing in IndexingPipeline."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dotmd.core.models import Chunk, FileInfo

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
        file_paths=[Path(file_path)],
        heading_hierarchy=["Test"],
        level=1,
        text=f"Content of {chunk_id}",
        chunk_index=0,
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
    settings.index_db_path = index_dir / "index.db"
    settings.graph_db_path = index_dir / "graphdb"

    settings.acronyms_path = index_dir / "acronyms.json"
    settings.embedding_model = "test-model"
    settings.embedding_url = "http://test:8088"
    settings.extract_depth = "structural"  # skip NER for speed
    settings.ner_entity_types = []
    settings.ner_model_name = "urchade/gliner_multi-v2.1"
    settings.chunk_strategy = "heading_512_50"
    settings.max_chunk_tokens = 512
    settings.chunk_overlap_tokens = 50
    settings.read_only = False
    settings.vector_backend = "sqlite-vec"
    settings.lancedb_path = index_dir / "lancedb"
    settings.tei_batch_size = 32
    settings.needs_embedding_prefix = False
    return settings


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFirstIndex:
    """First index (no fingerprints) treats all files as new."""

    @patch("dotmd.ingestion.pipeline.discover_files")
    @patch("dotmd.ingestion.pipeline.read_file")
    @patch("dotmd.ingestion.chunker.chunk_file")
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
        # meta_tracker uses meta_checksum(title+tags) from FileInfo — no read_file call.
        # Only the chunk tracker path reads the file (once per file).
        assert mock_read_file.call_count == 2
        assert mock_chunk_file.call_count == 2


class TestUnchangedFiles:
    """Unchanged files are skipped entirely."""

    @patch("dotmd.ingestion.pipeline.discover_files")
    @patch("dotmd.ingestion.pipeline.read_file")
    @patch("dotmd.ingestion.chunker.chunk_file")
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
        assert stats.total_files == 2


class TestModifiedFile:
    """Modified files get purged from all stores then re-ingested."""

    @patch("dotmd.ingestion.pipeline.discover_files")
    @patch("dotmd.ingestion.pipeline.read_file")
    @patch("dotmd.ingestion.chunker.chunk_file")
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
        mock_chunk_file.side_effect = None  # clear exhausted iterator
        pipeline._semantic_engine.encode_batch.reset_mock()

        file_a_modified = _make_file_info(str(md_dir / "a.md"), "File A")
        mock_discover.return_value = [file_a_modified, file_b]
        chunk_a_new = _make_chunk("a-0-new", str(md_dir / "a.md"))
        mock_chunk_file.return_value = [chunk_a_new]
        mock_read_file.return_value = "# File A\nUpdated content of file A."
        pipeline._semantic_engine.encode_batch = MagicMock(return_value=_dummy_embeddings(1))

        stats = pipeline.index(md_dir)

        # Only file A should be re-read (modified), not file B (unchanged)
        # meta_tracker uses meta_checksum(title+tags) from FileInfo — no read_file call.
        assert mock_read_file.call_count == 1
        assert mock_chunk_file.call_count == 1
        assert stats.total_chunks >= 1


class TestDeletedFile:
    """Deleted files get purged and fingerprint removed."""

    @patch("dotmd.ingestion.pipeline.discover_files")
    @patch("dotmd.ingestion.pipeline.read_file")
    @patch("dotmd.ingestion.chunker.chunk_file")
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
        mock_chunk_file.side_effect = None  # clear exhausted iterator
        pipeline._semantic_engine.encode_batch.reset_mock()

        # Only file b remains
        file_b_again = _make_file_info(str(md_dir / "b.md"), "File B")
        mock_discover.return_value = [file_b_again]

        pipeline.index(md_dir)

        # No new files to read (b is unchanged)
        assert mock_read_file.call_count == 0
        # File a's fingerprint should be gone from chunk tracker table
        cursor = pipeline._metadata_store._conn.execute(
            "SELECT COUNT(*) FROM chunk_fingerprints_heading_512_50 WHERE file_path = ?",
            (str(md_dir / "a.md"),),
        )
        assert cursor.fetchone()[0] == 0


class TestNewFileAdded:
    """New file added is ingested without touching existing data."""

    @patch("dotmd.ingestion.pipeline.discover_files")
    @patch("dotmd.ingestion.pipeline.read_file")
    @patch("dotmd.ingestion.chunker.chunk_file")
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
        # meta_tracker uses meta_checksum(title+tags) from FileInfo — no read_file call.
        assert mock_read_file.call_count == 1
        assert stats.total_files == 2  # both files counted


class TestFTS5UpdateAfterChanges:
    """FTS5 index is updated incrementally on deletions.

    Phase 16 note: _purge_file handles FTS5 deletion directly via SQL inside
    its single-transaction cascade (not via keyword_engine.remove_chunks).
    The delete-from-FTS5 path is covered by test_pipeline_purge.py.
    This class is retained as a placeholder to document the design decision.
    """


class TestFingerprintTiming:
    """Fingerprints are saved AFTER successful ingestion, not before."""

    @patch("dotmd.ingestion.pipeline.discover_files")
    @patch("dotmd.ingestion.pipeline.read_file")
    @patch("dotmd.ingestion.chunker.chunk_file")
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

        def tracking_encode(texts):
            call_order.append("encode")
            return _dummy_embeddings(len(texts))

        def tracking_save_fp(*args):
            call_order.append("save_fingerprint")
            return original_save_fp(*args)

        pipeline._semantic_engine.encode_batch = tracking_encode
        original_save_fp = pipeline._chunk_tracker.save_fingerprint
        pipeline._chunk_tracker.save_fingerprint = tracking_save_fp

        pipeline.index(md_dir)

        # Fingerprint must come AFTER encoding
        assert "encode" in call_order
        assert "save_fingerprint" in call_order
        assert call_order.index("encode") < call_order.index("save_fingerprint")



# TestPurgeFileOrder removed: phase 16 _purge_file uses M2M cascade
# (delete_m2m_for_file + delete_orphan_chunks + delete_by_chunk_ids) in a
# single transaction.  The old get_chunk_ids_by_file → delete_vectors_by_chunk_ids
# → delete_chunks_by_file → delete_file_subgraph sequence no longer exists.
# Purge order is covered by test_pipeline_purge.py.


class TestForceReindex:
    """force=True processes all files regardless of fingerprints."""

    @patch("dotmd.ingestion.pipeline.discover_files")
    @patch("dotmd.ingestion.pipeline.read_file")
    @patch("dotmd.ingestion.chunker.chunk_file")
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

        # meta_tracker uses meta_checksum(title+tags) from FileInfo — no read_file call.
        assert mock_read_file.call_count == 2
        assert mock_chunk_file.call_count == 2
        assert stats.total_files == 2

    @patch("dotmd.ingestion.pipeline.discover_files")
    @patch("dotmd.ingestion.pipeline.read_file")
    @patch("dotmd.ingestion.chunker.chunk_file")
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

        # Verify fingerprint exists in chunk tracker table
        cursor = pipeline._metadata_store._conn.execute(
            "SELECT COUNT(*) FROM chunk_fingerprints_heading_512_50"
        )
        assert cursor.fetchone()[0] == 1

        # Spy on chunk_tracker.clear
        original_clear = pipeline._chunk_tracker.clear
        clear_called = []

        def tracking_clear():
            clear_called.append(True)
            return original_clear()

        pipeline._chunk_tracker.clear = tracking_clear

        # Reset mocks for force=True run
        mock_read_file.reset_mock()
        mock_chunk_file.reset_mock()
        mock_discover.return_value = [file_a]
        mock_chunk_file.return_value = [chunk_a]
        pipeline._semantic_engine.encode_batch = MagicMock(return_value=_dummy_embeddings(1))

        pipeline.index(md_dir, force=True)

        assert len(clear_called) > 0, "file_tracker.clear() must be called during force=True"
