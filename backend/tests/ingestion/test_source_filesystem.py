"""Tests for filesystem source adapter contract."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from dotmd.core.models import SourceDocument


def _source_document(path: Path, document_ref: str | None = None) -> SourceDocument:
    ref_document = document_ref or str(path.resolve())
    return SourceDocument(
        namespace="filesystem",
        document_ref=ref_document,
        ref=f"filesystem:{ref_document}",
        title="Test Document",
        source_uri=ref_document,
        media_type="text/markdown",
        parser_name="markdown",
        updated_at=datetime.now(tz=UTC),
        content_fingerprint="content",
        metadata_fingerprint="metadata",
        file_path=path,
    )


def test_filesystem_source_document_uses_resolved_document_ref(
    tmp_path: Path,
) -> None:
    md_path = tmp_path / "note.md"
    md_path.write_text("# Test Document\n", encoding="utf-8")

    document = _source_document(md_path)

    document_ref = str(md_path.resolve())
    assert document.document_ref == document_ref
    assert document.ref == f"filesystem:{document_ref}"


def test_filesystem_source_document_rejects_mismatched_file_path(
    tmp_path: Path,
) -> None:
    md_path = tmp_path / "note.md"
    md_path.write_text("# Test Document\n", encoding="utf-8")

    with pytest.raises(ValueError, match="document_ref"):
        _source_document(md_path, document_ref=str(tmp_path / "other.md"))
