"""Tests for graph-based search enrichment semantics."""

from __future__ import annotations

from pathlib import Path

from dotmd.core.models import Chunk
from dotmd.search.graph_search import GraphSearchEngine


class _FakeGraphStore:
    def __init__(self) -> None:
        self.requested: list[str] = []

    def get_related_sections(self, chunk_id: str) -> list[tuple[str, str, float]]:
        self.requested.append(chunk_id)
        return [
            ("chunk-2", "MENTIONS", 1.0),
            ("missing", "MENTIONS", 1.0),
            (chunk_id, "MENTIONS", 1.0),
        ]


class _FakeMetadataStore:
    def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]:
        return [
            Chunk(
                chunk_id=chunk_id,
                file_paths=[Path("doc.md")],
                text="text",
                chunk_index=0,
            )
            for chunk_id in chunk_ids
            if chunk_id == "chunk-2"
        ]


def test_graph_search_uses_related_sections_and_filters_invalid_chunks() -> None:
    graph_store = _FakeGraphStore()
    engine = GraphSearchEngine(graph_store, _FakeMetadataStore())  # type: ignore[arg-type]

    results = engine.search("query", top_k=10, seed_chunk_ids=["chunk-1"])

    assert graph_store.requested == ["chunk-1"]
    assert results == [("chunk-2", 1.0)]
