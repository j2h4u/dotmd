"""Application-source ingestion invariants shared by all providers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from dotmd.core.config import Settings
from dotmd.core.models import (
    ApplicationSourceChange,
    ApplicationSourceDescription,
    ExtractDepth,
    SourceDocument,
    SourceUnit,
)
from dotmd.ingestion.pipeline import IndexingPipeline

from .application_source_fixtures import FixtureApplicationSourceProvider

NOW = datetime(2026, 5, 8, 12, 0, tzinfo=UTC)


def _pipeline(tmp_path: Path) -> IndexingPipeline:
    data_dir = tmp_path / "data"
    index_dir = tmp_path / "index"
    data_dir.mkdir()
    index_dir.mkdir()
    pipeline = IndexingPipeline(
        Settings(
            data_dir=data_dir,
            index_dir=index_dir,
            embedding_url="http://localhost:18088",
            indexing_paths=[str(data_dir)],
            vector_backend="sqlite-vec",
            graph_backend="ladybugdb",
            extract_depth=ExtractDepth.STRUCTURAL,
        )
    )
    pipeline._semantic_engine.get_tei_model_id = lambda: "fixture-model"  # type: ignore[method-assign]
    return pipeline


def _document(document_ref: str, title: str) -> SourceDocument:
    return SourceDocument(
        namespace="fixture",
        document_ref=document_ref,
        ref=f"fixture:{document_ref}",
        title=title,
        source_uri=f"fixture://{document_ref}",
        media_type="text/plain",
        parser_name="fixture-parser",
        document_type="page",
        updated_at=NOW,
        content_fingerprint=f"{document_ref}:content",
        metadata_fingerprint=f"{document_ref}:meta",
        metadata_json={},
    )


def _unit(
    document: SourceDocument,
    index: int,
    text: str,
) -> SourceUnit:
    return SourceUnit(
        namespace=document.namespace,
        document_ref=document.document_ref,
        unit_ref=f"{document.document_ref}:unit:{index}",
        unit_type="paragraph",
        text=text,
        order_key=f"{index:020d}",
        fingerprint=f"{document.document_ref}:unit:{index}:fingerprint",
        updated_at=NOW,
        metadata_json={"speaker": f"speaker-{index}"},
        chunking_hints={},
    )


def _change(document: SourceDocument, index: int, text: str) -> ApplicationSourceChange:
    return ApplicationSourceChange(
        document=document,
        unit=_unit(document, index, text),
    )


def test_application_source_embeddings_are_chunk_batched_and_document_meta_scoped(
    tmp_path: Path,
) -> None:
    pipeline = _pipeline(tmp_path)
    encode_calls: list[list[str]] = []

    def record_encode(texts: list[str]) -> list[list[float]]:
        encode_calls.append(list(texts))
        return [[float(len(encode_calls))] * 8 for _text in texts]

    pipeline._semantic_engine.encode_batch = record_encode  # type: ignore[method-assign]
    doc_a = _document("doc:a", "Doc A")
    doc_b = _document("doc:b", "Doc B")
    provider = FixtureApplicationSourceProvider(
        ApplicationSourceDescription(
            namespace="fixture",
            source_kind="document",
            display_name="Fixture",
        ),
        [
            _change(doc_a, 1, "alpha body"),
            _change(doc_a, 2, "beta body"),
            _change(doc_b, 1, "gamma body"),
        ],
    )

    result = pipeline.ingest_application_source(provider, limit=10)

    assert result.chunks_indexed == 3
    assert [len(call) for call in encode_calls] == [3, 2]
    assert any("alpha body" in text for text in encode_calls[0])
    assert any("beta body" in text for text in encode_calls[0])
    assert any("gamma body" in text for text in encode_calls[0])
    assert encode_calls[1] == ["fixture Doc A page", "fixture Doc B page"]
    assert all("body" not in text for text in encode_calls[1])
    assert all("speaker" not in text for text in encode_calls[1])


def test_purge_application_source_removes_checkpoint_fingerprints_and_vectors(
    tmp_path: Path,
) -> None:
    pipeline = _pipeline(tmp_path)
    doc_a = _document("doc:a", "Doc A")
    provider = FixtureApplicationSourceProvider(
        ApplicationSourceDescription(
            namespace="fixture",
            source_kind="document",
            display_name="Fixture",
        ),
        [
            _change(doc_a, 1, "alpha body"),
            _change(doc_a, 2, "beta body"),
        ],
    )

    first = pipeline.ingest_application_source(provider, limit=10)
    purge = pipeline.purge_application_source("fixture")
    assert pipeline._metadata_store.get_source_checkpoint("fixture") is None
    second = pipeline.ingest_application_source(provider, limit=10)

    assert first.new_units == 2
    assert purge.chunks_deleted == 2
    assert purge.source_units_deleted == 2
    assert purge.documents_deleted == 1
    assert purge.checkpoints_deleted == 1
    assert second.new_units == 2
    assert second.skipped_units == 0
