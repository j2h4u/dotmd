"""Tests for filesystem source adapter contract."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dotmd.core.models import ExtractDepth, FileInfo, SourceDocument
from dotmd.ingestion.chunker import chunk_file
from dotmd.ingestion.file_tracker import FileDiff
from dotmd.ingestion.reader import chunk_checksum, meta_checksum
from dotmd.ingestion.source import (
    FilesystemMarkdownSourceAdapter,
    filesystem_document_ref,
    source_document_to_file_info,
)


def _write_markdown(
    path: Path,
    title: str,
    tags: list[str],
    body: str,
    kind: str = "document",
) -> None:
    tags_yaml = "\n".join(f"  - {tag}" for tag in tags)
    path.write_text(
        f"---\ntitle: {title}\nkind: {kind}\ntags:\n{tags_yaml}\n---\n{body}",
        encoding="utf-8",
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


def test_source_document_converts_to_file_info_with_compatibility_fields(
    tmp_path: Path,
) -> None:
    md_path = tmp_path / "note.md"
    md_path.write_text(
        "---\n"
        "title: Compatibility Note\n"
        "kind: voicenote\n"
        "tags:\n"
        "  - source\n"
        "---\n"
        "Body text.\n",
        encoding="utf-8",
    )
    document = FilesystemMarkdownSourceAdapter().discover(tmp_path)[0]

    file_info = source_document_to_file_info(document)

    assert file_info.path == md_path
    assert file_info.title == document.title
    assert file_info.kind == document.document_type
    assert file_info.frontmatter == document.metadata_json
    assert file_info.size_bytes == md_path.stat().st_size
    assert file_info.last_modified == document.updated_at
    assert document.document_ref == str(file_info.path.resolve())


def test_body_only_change_updates_content_fingerprint_only(
    tmp_path: Path,
) -> None:
    md_path = tmp_path / "note.md"
    _write_markdown(md_path, "Stable", ["alpha"], "Original body.")
    adapter = FilesystemMarkdownSourceAdapter()
    original = adapter.discover(tmp_path)[0]

    _write_markdown(md_path, "Stable", ["alpha"], "Changed body.")
    changed = adapter.discover(tmp_path)[0]

    assert changed.content_fingerprint != original.content_fingerprint
    assert changed.metadata_fingerprint == original.metadata_fingerprint


def test_title_and_tags_change_updates_metadata_fingerprint_only(
    tmp_path: Path,
) -> None:
    md_path = tmp_path / "note.md"
    _write_markdown(md_path, "Original", ["alpha"], "Stable body.")
    adapter = FilesystemMarkdownSourceAdapter()
    original = adapter.discover(tmp_path)[0]

    _write_markdown(md_path, "Renamed", ["alpha", "beta"], "Stable body.")
    changed = adapter.discover(tmp_path)[0]

    assert changed.metadata_fingerprint != original.metadata_fingerprint
    assert changed.content_fingerprint == original.content_fingerprint


def test_pipeline_helper_builds_filesystem_chunk_provenance(
    tmp_path: Path,
) -> None:
    from dotmd.core.config import Settings
    from dotmd.ingestion.pipeline import IndexingPipeline

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    md_path = data_dir / "note.md"
    _write_markdown(md_path, "Provenance", ["source"], "Body text.")
    pipeline = IndexingPipeline(
        Settings(
            data_dir=data_dir,
            index_dir=index_dir,
            embedding_url="http://localhost:18088",
            vector_backend="sqlite-vec",
            graph_backend="ladybugdb",
            extract_depth=ExtractDepth.STRUCTURAL,
        )
    )
    normalized = pipeline._file_info_and_source_document(md_path)
    assert normalized is not None
    file_info, source_document = normalized

    provenance = pipeline._filesystem_chunk_provenance(source_document)

    document_ref = str(md_path.resolve())
    assert file_info.path == md_path
    assert provenance.namespace == "filesystem"
    assert provenance.document_ref == document_ref
    assert provenance.ref == f"filesystem:{document_ref}"
    assert provenance.parser_name == "markdown"
    assert provenance.source_unit_refs == []


def _pipeline_with_mock_embedding(data_dir: Path, index_dir: Path):
    from dotmd.core.config import Settings
    from dotmd.ingestion.pipeline import IndexingPipeline

    pipeline = IndexingPipeline(
        Settings(
            data_dir=data_dir,
            index_dir=index_dir,
            embedding_url="http://localhost:18088",
            vector_backend="sqlite-vec",
            graph_backend="ladybugdb",
            extract_depth=ExtractDepth.STRUCTURAL,
        )
    )
    mock_engine = MagicMock()
    mock_engine.encode_batch = lambda texts: [[0.1] * 768 for _ in texts]
    mock_engine.get_tei_model_id = MagicMock(return_value="test-model")
    pipeline._semantic_engine = mock_engine
    return pipeline


def _capture_indexed_chunks(pipeline) -> list:
    captured_chunks = []

    class KeywordRecorder:
        def add_chunks(self, chunks, file_meta=None):  # type: ignore[no-untyped-def]
            captured_chunks.extend(chunks)

    pipeline._keyword_engine = KeywordRecorder()
    return captured_chunks


def test_index_file_path_and_file_info_use_same_filesystem_provenance(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    md_path = data_dir / "note.md"
    _write_markdown(md_path, "Trickle", ["source"], "# Heading\n\nBody text.")

    path_pipeline = _pipeline_with_mock_embedding(data_dir, tmp_path / "path-index")
    path_chunks = _capture_indexed_chunks(path_pipeline)
    path_pipeline.index_file(md_path)

    file_info_pipeline = _pipeline_with_mock_embedding(
        data_dir,
        tmp_path / "file-info-index",
    )
    file_info_chunks = _capture_indexed_chunks(file_info_pipeline)
    normalized = file_info_pipeline._file_info_and_source_document(md_path)
    assert normalized is not None
    file_info, _ = normalized
    file_info_pipeline.index_file(file_info)

    assert path_chunks
    assert file_info_chunks
    assert path_chunks[0].provenance == file_info_chunks[0].provenance
    assert path_chunks[0].provenance is not None
    assert path_chunks[0].provenance.document_ref == str(md_path.resolve())


def test_bulk_and_index_file_use_identical_filesystem_provenance(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    md_path = data_dir / "note.md"
    _write_markdown(md_path, "Bulk", ["source"], "# Heading\n\nBody text.")

    bulk_pipeline = _pipeline_with_mock_embedding(data_dir, tmp_path / "bulk-index")
    bulk_chunks = _capture_indexed_chunks(bulk_pipeline)
    bulk_pipeline.index(data_dir)

    file_pipeline = _pipeline_with_mock_embedding(data_dir, tmp_path / "file-index")
    file_chunks = _capture_indexed_chunks(file_pipeline)
    file_pipeline.index_file(md_path)

    assert bulk_chunks
    assert file_chunks
    assert bulk_chunks[0].provenance == file_chunks[0].provenance
    assert bulk_chunks[0].provenance is not None
    document_ref = str(md_path.resolve())
    assert bulk_chunks[0].provenance.namespace == "filesystem"
    assert bulk_chunks[0].provenance.document_ref == document_ref
    assert bulk_chunks[0].provenance.ref == f"filesystem:{document_ref}"
    assert bulk_chunks[0].provenance.parser_name == "markdown"
    assert bulk_chunks[0].provenance.source_unit_refs == []


def test_successful_bulk_index_creates_active_filesystem_binding(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    md_path = data_dir / "note.md"
    _write_markdown(md_path, "Binding", ["source"], "# Heading\n\nBody text.")

    pipeline = _pipeline_with_mock_embedding(data_dir, tmp_path / "index")
    pipeline.index(data_dir)

    document_ref = str(md_path.resolve())
    binding = pipeline._metadata_store.get_resource_binding(
        "filesystem",
        document_ref,
    )
    source_document = pipeline._metadata_store.get_source_document(
        "filesystem",
        document_ref,
    )
    assert source_document is not None
    assert binding is not None
    assert binding.active is True
    assert binding.unbound_at is None
    assert binding.resource_ref == document_ref
    assert binding.document_ref == document_ref
    assert binding.ref == f"filesystem:{document_ref}"
    assert binding.content_fingerprint == source_document.content_fingerprint
    assert binding.metadata_fingerprint == source_document.metadata_fingerprint
    assert binding.source_unit_refs == []
    assert binding.metadata_json == {}


def test_successful_index_file_creates_active_filesystem_binding(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    md_path = data_dir / "note.md"
    _write_markdown(md_path, "Trickle Binding", ["source"], "Body text.")

    pipeline = _pipeline_with_mock_embedding(data_dir, tmp_path / "index")
    pipeline.index_file(md_path)

    document_ref = str(md_path.resolve())
    binding = pipeline._metadata_store.get_resource_binding(
        "filesystem",
        document_ref,
    )
    source_document = pipeline._metadata_store.get_source_document(
        "filesystem",
        document_ref,
    )
    assert source_document is not None
    assert binding is not None
    assert binding.active is True
    assert binding.content_fingerprint == source_document.content_fingerprint
    assert binding.metadata_fingerprint == source_document.metadata_fingerprint


def test_reindex_vectors_preserves_existing_provenance_and_skips_legacy_chunks(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    md_path = data_dir / "note.md"
    _write_markdown(md_path, "Reindex", ["source"], "# Heading\n\nBody text.")
    pipeline = _pipeline_with_mock_embedding(data_dir, tmp_path / "index")
    normalized = pipeline._file_info_and_source_document(md_path)
    assert normalized is not None
    file_info, source_document = normalized
    provenance = pipeline._filesystem_chunk_provenance(source_document)
    with_provenance_id = "a" * 64
    legacy_id = "b" * 64

    pipeline._metadata_store.insert_chunk(
        pipeline._strategy,
        with_provenance_id,
        ["Heading"],
        1,
        "with provenance",
    )
    pipeline._metadata_store.insert_chunk(
        pipeline._strategy,
        legacy_id,
        ["Heading"],
        1,
        "legacy",
    )
    pipeline._metadata_store.add_file_path(
        pipeline._strategy,
        with_provenance_id,
        str(file_info.path),
        chunk_index=0,
    )
    pipeline._metadata_store.add_file_path(
        pipeline._strategy,
        legacy_id,
        str(file_info.path),
        chunk_index=1,
    )
    pipeline._metadata_store.ensure_chunk_source_provenance_table(pipeline._strategy)
    pipeline._metadata_store.upsert_source_document(
        source_document,
        conn=pipeline._conn,
    )
    pipeline._metadata_store.add_chunk_provenance(
        pipeline._strategy,
        provenance,
        with_provenance_id,
        conn=pipeline._conn,
    )
    pipeline._conn.commit()

    rebuilt_count = pipeline.reindex_vectors()
    loaded = pipeline._metadata_store.get_chunk_provenance_for_chunk_ids(
        pipeline._strategy,
        [with_provenance_id, legacy_id],
    )

    assert rebuilt_count == 2
    assert sorted(loaded) == [with_provenance_id]
    assert loaded[with_provenance_id].source_unit_refs == []


def test_adapter_routed_chunks_preserve_markdown_chunk_payload(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    md_path = data_dir / "structured.md"
    content = (
        "---\n"
        "title: Structured\n"
        "kind: document\n"
        "tags:\n"
        "  - source\n"
        "---\n"
        "# Project\n\n"
        "Intro body.\n\n"
        "## Decision\n\n"
        "Keep chunk text compatibility.\n"
    )
    md_path.write_text(content, encoding="utf-8")
    pipeline = _pipeline_with_mock_embedding(data_dir, tmp_path / "index")
    documents = pipeline._discover_documents(data_dir)
    files, documents_by_path = pipeline._file_infos_by_source_document(documents)

    adapter_chunks = pipeline._chunk_files(
        files,
        "test",
        documents_by_path=documents_by_path,
    )
    direct_chunks = chunk_file(
        md_path,
        content,
        kind="document",
        chunk_strategy=pipeline._strategy,
    )

    assert adapter_chunks
    assert [
        (
            chunk.text,
            chunk.heading_hierarchy,
            chunk.level,
            chunk.chunk_index,
            chunk.file_paths,
        )
        for chunk in adapter_chunks
    ] == [
        (
            chunk.text,
            chunk.heading_hierarchy,
            chunk.level,
            chunk.chunk_index,
            chunk.file_paths,
        )
        for chunk in direct_chunks
    ]
    assert adapter_chunks[1].heading_hierarchy == ["Project", "Decision"]
    assert adapter_chunks[0].file_paths == [md_path]
    assert adapter_chunks[0].provenance is not None
    assert adapter_chunks[0].provenance.namespace == "filesystem"
    assert adapter_chunks[0].provenance.document_ref == str(md_path.resolve())
    assert adapter_chunks[0].provenance.source_unit_refs == []


def test_adapter_routed_meeting_transcript_uses_kind_handler(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    md_path = data_dir / "meeting.md"
    content = (
        "---\n"
        "title: Meeting\n"
        "kind: meeting_transcript\n"
        "tags:\n"
        "  - sync\n"
        "---\n"
        "# Standup\n\n"
        "Alice: First update.\n"
        "Bob: Second update.\n"
    )
    md_path.write_text(content, encoding="utf-8")
    pipeline = _pipeline_with_mock_embedding(data_dir, tmp_path / "index")
    documents = pipeline._discover_documents(data_dir)
    files, documents_by_path = pipeline._file_infos_by_source_document(documents)

    adapter_chunks = pipeline._chunk_files(
        files,
        "test",
        documents_by_path=documents_by_path,
    )
    direct_chunks = chunk_file(
        md_path,
        content,
        kind="meeting_transcript",
        chunk_strategy=pipeline._strategy,
    )

    assert files[0].kind == "meeting_transcript"
    assert [chunk.text for chunk in adapter_chunks] == [
        chunk.text for chunk in direct_chunks
    ]
    assert adapter_chunks[0].kind == "meeting_transcript"
    assert adapter_chunks[0].provenance is not None
    assert adapter_chunks[0].provenance.source_unit_refs == []


def test_index_file_trackers_receive_file_info_objects(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    md_path = data_dir / "note.md"
    _write_markdown(md_path, "Tracker", ["source"], "Body text.")
    pipeline = _pipeline_with_mock_embedding(data_dir, tmp_path / "index")
    path_str = str(md_path)
    tracker_inputs: list[list[FileInfo]] = []

    def record_chunk_diff(files: list[FileInfo]) -> FileDiff:
        tracker_inputs.append(files)
        return FileDiff(unchanged=[path_str])

    def record_meta_diff(files: list[FileInfo]) -> FileDiff:
        tracker_inputs.append(files)
        return FileDiff(unchanged=[path_str])

    pipeline._chunk_tracker.diff = record_chunk_diff  # type: ignore[method-assign]
    pipeline._meta_tracker.diff = record_meta_diff  # type: ignore[method-assign]

    pipeline.index_file(md_path)

    assert len(tracker_inputs) == 2
    assert all(isinstance(files[0], FileInfo) for files in tracker_inputs)


def test_discover_multi_excludes_empty_and_non_markdown_files(
    tmp_path: Path,
) -> None:
    markdown_path = tmp_path / "note.md"
    markdown_path.write_text("# Included\n", encoding="utf-8")
    (tmp_path / "empty.md").write_text("", encoding="utf-8")
    (tmp_path / "note.txt").write_text("# Excluded\n", encoding="utf-8")

    documents = FilesystemMarkdownSourceAdapter().discover_multi([str(tmp_path)])

    assert [document.file_path for document in documents] == [markdown_path]


def test_source_module_keeps_future_runtime_concepts_deferred() -> None:
    source_text = Path("src/dotmd/ingestion/source.py").read_text(encoding="utf-8")

    deferred_terms = [
        "tele" + "gram",
        "Source" + "Asset",
        "Source" + "Entity",
        "socket",
        "requests",
        "TTL",
        "second-source",
    ]
    for term in deferred_terms:
        assert term not in source_text
