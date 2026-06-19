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


class _FakeBatchGraphStore:
    def __init__(self) -> None:
        self.requested: list[list[str]] = []

    def get_related_sections_for_seeds(
        self,
        chunk_ids: list[str],
    ) -> list[tuple[str, str, float]]:
        self.requested.append(list(chunk_ids))
        rows: list[tuple[str, str, float]] = []
        for seed_id in chunk_ids:
            rows.extend(
                [
                    ("chunk-2", "MENTIONS", 1.0),
                    ("chunk-3", "HAS_TAG", 0.5),
                    ("missing", "MENTIONS", 1.0),
                    (seed_id, "MENTIONS", 1.0),
                ]
            )
        return rows

    def get_related_sections(self, chunk_id: str) -> list[tuple[str, str, float]]:
        raise AssertionError("single-seed fallback must not be used when batch support exists")


class _FakeBoundedGraphStore:
    def __init__(self) -> None:
        self.requested: list[str] = []

    def get_related_sections(self, chunk_id: str) -> list[tuple[str, str, float]]:
        self.requested.append(chunk_id)
        return [
            ("chunk-2", "MENTIONS", 1.0),
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
            if chunk_id in {"chunk-2", "chunk-3"}
        ]


def test_graph_search_uses_related_sections_and_filters_invalid_chunks() -> None:
    graph_store = _FakeGraphStore()
    engine = GraphSearchEngine(graph_store, _FakeMetadataStore())  # type: ignore[arg-type]

    results = engine.search("query", top_k=10, seed_chunk_ids=["chunk-1"])

    assert graph_store.requested == ["chunk-1"]
    assert results == [("chunk-2", 1.0)]


def test_graph_search_uses_batched_seed_query_and_caps_seed_count() -> None:
    graph_store = _FakeBatchGraphStore()
    engine = GraphSearchEngine(graph_store, _FakeMetadataStore())  # type: ignore[arg-type]
    seed_chunk_ids = [
        "seed-0",
        "seed-0",
        "seed-1",
        "seed-2",
        "seed-3",
        "seed-4",
        "seed-5",
        "seed-6",
        "seed-7",
        "seed-8",
        "seed-9",
    ]

    results = engine.search("query", top_k=10, seed_chunk_ids=seed_chunk_ids)

    assert graph_store.requested == [
        [
            "seed-0",
            "seed-1",
            "seed-2",
            "seed-3",
            "seed-4",
            "seed-5",
            "seed-6",
            "seed-7",
        ]
    ]
    assert results == [("chunk-2", 8.0), ("chunk-3", 4.0)]


def test_graph_search_falls_back_to_bounded_single_seed_queries() -> None:
    graph_store = _FakeBoundedGraphStore()
    engine = GraphSearchEngine(graph_store, _FakeMetadataStore())  # type: ignore[arg-type]
    seed_chunk_ids = [f"seed-{index}" for index in range(12)]

    results = engine.search("query", top_k=10, seed_chunk_ids=seed_chunk_ids)

    assert graph_store.requested == seed_chunk_ids[: GraphSearchEngine.MAX_SEED_CHUNK_IDS]
    assert results == [("chunk-2", float(GraphSearchEngine.MAX_SEED_CHUNK_IDS))]
