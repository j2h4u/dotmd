from __future__ import annotations

import pytest
from devtools.surreal_standalone_migration_proof import (
    _target_and_data,
    format_eta,
)

from dotmd.storage.surreal import SurrealRecordIdCodec

pytestmark = pytest.mark.real_schema_check


def test_format_eta_omits_zero_seconds_and_rounds_long_minutes() -> None:
    assert format_eta(0) == "0s"
    assert format_eta(59.4) == "59s"
    assert format_eta(60) == "1m"
    assert format_eta(90) == "1m 30s"
    assert format_eta(300) == "5m"
    assert format_eta(360) == "6m"
    assert format_eta(388) == "6m"


def test_target_and_data_maps_chunk_document_to_record_id() -> None:
    codec = SurrealRecordIdCodec()
    target, data = _target_and_data(
        {
            "type": "chunk",
            "data": {
                "schema_version": 1,
                "chunk_id": "chunk-1",
                "original_chunk_id": "chunk-1",
                "chunk_strategy": "contextual_512_50",
                "document_ref": "/mnt/doc.md",
                "heading_hierarchy": [],
                "level": 0,
                "chunk_index": 0,
                "title": None,
                "text": "hello",
                "metadata": {"namespace": "filesystem"},
            },
        },
        codec,
    )

    assert target.startswith("chunks:")
    assert data["document"].table_name == "documents"
    assert data["document"].id == codec.encode("filesystem\0/mnt/doc.md")


def test_target_and_data_requires_explicit_chunk_strategy_for_file_binding() -> None:
    codec = SurrealRecordIdCodec()
    target, data = _target_and_data(
        {
            "type": "chunk_file_binding",
            "data": {
                "chunk_id": "chunk-1",
                "chunk_strategy": "contextual_512_50",
                "file_path": "/mnt/doc.md",
                "chunk_index": 0,
            },
        },
        codec,
    )

    assert target.startswith("chunk_file_bindings:")
    assert data["chunk"].table_name == "chunks"
    assert data["chunk"].id == codec.encode("contextual_512_50\0chunk-1")
