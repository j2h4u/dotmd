"""RED test skeletons for chunker changes (P1 — Decision #8 char_offset drop).

After Phase 16 P1 ships:
  - Chunk model has no char_offset field
  - Chunker emits file_paths as a single-element list (not file_path as Path)

These tests guard against regression in the Chunk model contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dotmd.ingestion.chunker import chunk_file  # noqa: F401
from dotmd.core.models import Chunk


class TestChunkerEmitsNoCharOffset:
    """Decision #8: char_offset is removed from Chunk model and chunker output."""

    def test_chunker_emits_no_char_offset(self, tmp_path: Path) -> None:
        """Chunk model has no char_offset attribute after P1 strips it."""
        # Attempt to construct a Chunk with char_offset — must fail (field no longer exists)
        with pytest.raises((TypeError, ValueError)):
            Chunk(
                chunk_id="a" * 64,
                file_paths=[tmp_path / "test.md"],
                heading_hierarchy=["Test"],
                level=1,
                text="Some text",
                chunk_index=0,
                char_offset=42,  # This field must be rejected by P1's Pydantic model
            )

    def test_chunk_model_has_no_char_offset_field(self) -> None:
        """Chunk model fields do not include char_offset after P1."""
        chunk_fields = Chunk.model_fields
        assert "char_offset" not in chunk_fields, (
            "char_offset field must be removed from Chunk model in Phase 16 P1 (Decision #8)"
        )


class TestChunkerEmitsFilePaths:
    """Chunker emits file_paths as a single-element list, not file_path as Path."""

    def test_chunker_emits_file_paths_as_single_element_list(
        self, tmp_path: Path
    ) -> None:
        """chunk_file() returns Chunk instances with file_paths: list[Path] (single element)."""
        md_file = tmp_path / "test.md"
        md_file.write_text("# Test Heading\n\nTest content for chunker output test.\n")

        chunks = chunk_file(md_file)
        assert len(chunks) >= 1, "chunk_file should produce at least one chunk"

        for chunk in chunks:
            # Must have file_paths (list), not file_path (singular)
            assert hasattr(chunk, "file_paths"), (
                "Chunk must have file_paths attribute after P1 (Decision #8)"
            )
            assert not hasattr(chunk, "file_path") or isinstance(
                getattr(chunk, "file_path", None), property
            ), (
                "Chunk must not have a singular file_path field after P1"
            )
            assert isinstance(chunk.file_paths, list), (
                f"file_paths must be a list, got {type(chunk.file_paths)!r}"
            )
            assert len(chunk.file_paths) == 1, (
                f"Chunker must emit single-element file_paths list, got {chunk.file_paths!r}"
            )
            assert chunk.file_paths[0] == md_file, (
                f"file_paths[0] must be the source file, got {chunk.file_paths[0]!r}"
            )
