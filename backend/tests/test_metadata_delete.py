"""Tests for metadata store delete methods — per-file chunk deletion.

Updated for Phase 16 M2M schema:
  - Chunk.file_paths replaces Chunk.file_path (no char_offset)
  - get_chunk_ids_by_file(strategy, file_path) takes strategy as first arg
  - idx_chunks_file_path removed (file_path column gone from chunks_*);
    M2M index idx_chunk_file_paths_<strategy>_file_path replaces it
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dotmd.core.models import Chunk
from dotmd.storage.metadata import SQLiteMetadataStore


STRATEGY = "heading_512_50"


def _make_chunk(chunk_id: str, file_path: str, text: str = "sample") -> Chunk:
    """Create a minimal Chunk for testing."""
    return Chunk(
        chunk_id=chunk_id,
        file_paths=[Path(file_path)],
        heading_hierarchy=["Test"],
        level=1,
        text=text,
        chunk_index=0,
    )


class TestGetChunkIdsByFile:
    """Tests for get_chunk_ids_by_file."""

    def test_returns_correct_ids(self, metadata_store: SQLiteMetadataStore) -> None:
        """Should return chunk IDs matching the given file_path."""
        chunks = [
            _make_chunk("c1", "/docs/a.md", "chunk 1"),
            _make_chunk("c2", "/docs/a.md", "chunk 2"),
            _make_chunk("c3", "/docs/b.md", "chunk 3"),
        ]
        metadata_store.save_chunks(chunks)

        ids = metadata_store.get_chunk_ids_by_file(STRATEGY, "/docs/a.md")

        assert sorted(ids) == ["c1", "c2"]

    def test_returns_empty_for_unknown_file(
        self, metadata_store: SQLiteMetadataStore
    ) -> None:
        """Should return empty list for a file_path not in the store."""
        ids = metadata_store.get_chunk_ids_by_file(STRATEGY, "/nonexistent.md")
        assert ids == []


class TestDeleteChunksByFile:
    """Tests for delete_chunks_by_file."""

    def test_removes_chunks_and_returns_count(
        self, metadata_store: SQLiteMetadataStore
    ) -> None:
        """Should delete matching chunks and return the count."""
        chunks = [
            _make_chunk("c1", "/docs/a.md"),
            _make_chunk("c2", "/docs/a.md"),
            _make_chunk("c3", "/docs/b.md"),
        ]
        metadata_store.save_chunks(chunks)

        deleted = metadata_store.delete_chunks_by_file("/docs/a.md")

        assert deleted == 2
        # Verify chunks are actually gone
        assert metadata_store.get_chunk("c1") is None
        assert metadata_store.get_chunk("c2") is None

    def test_does_not_affect_other_files(
        self, metadata_store: SQLiteMetadataStore
    ) -> None:
        """Deleting chunks for one file should not touch another file's chunks."""
        chunks = [
            _make_chunk("c1", "/docs/a.md"),
            _make_chunk("c2", "/docs/b.md"),
        ]
        metadata_store.save_chunks(chunks)

        metadata_store.delete_chunks_by_file("/docs/a.md")

        # b.md chunk should still exist
        assert metadata_store.get_chunk("c2") is not None


class TestM2MFilePathIndex:
    """Test that the M2M table has an index on file_path (replaces old idx_chunks_file_path)."""

    def test_m2m_index_exists(self, metadata_store: SQLiteMetadataStore) -> None:
        """The idx_chunk_file_paths_<strategy>_file_path index should exist."""
        expected_name = f"idx_chunk_file_paths_{STRATEGY}_file_path"
        cur = metadata_store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            (expected_name,),
        )
        row = cur.fetchone()
        assert row is not None, f"Expected {expected_name} index to exist"
