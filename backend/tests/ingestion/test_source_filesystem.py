"""Tests for filesystem source adapter contract."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from dotmd.core.models import SourceDocument
from dotmd.ingestion.reader import chunk_checksum, meta_checksum
from dotmd.ingestion.source import (
    FilesystemMarkdownSourceAdapter,
    filesystem_document_ref,
)


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


def test_filesystem_markdown_adapter_maps_frontmatter_document(
    tmp_path: Path,
) -> None:
    md_path = tmp_path / "meeting.md"
    md_path.write_text(
        "---\n"
        "title: Planning Notes\n"
        "kind: meeting_transcript\n"
        "tags:\n"
        "  - alpha\n"
        "---\n"
        "# Ignored Heading\n\n"
        "Body text.\n",
        encoding="utf-8",
    )

    documents = FilesystemMarkdownSourceAdapter().discover(tmp_path)

    assert len(documents) == 1
    document = documents[0]
    document_ref = str(md_path.resolve())
    assert document.namespace == "filesystem"
    assert document.document_ref == document_ref
    assert document.ref == f"filesystem:{document_ref}"
    assert document.source_uri == document_ref
    assert document.media_type == "text/markdown"
    assert document.parser_name == "markdown"
    assert document.title == "Planning Notes"
    assert document.document_type == "meeting_transcript"
    assert document.file_path == md_path
    assert document.metadata_json["tags"] == ["alpha"]
    assert document.content_fingerprint == chunk_checksum(md_path)
    assert document.metadata_fingerprint == meta_checksum(md_path)


def test_filesystem_document_ref_matches_pipeline_meta_entity_id_rule(
    tmp_path: Path,
) -> None:
    md_path = tmp_path / "note.md"
    md_path.write_text("# Note\n", encoding="utf-8")

    assert filesystem_document_ref(md_path) == str(md_path.resolve())
