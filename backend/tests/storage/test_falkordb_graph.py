"""Tests for FalkorDB graph query shaping."""

from __future__ import annotations

from dotmd.storage.falkordb_graph import FalkorDBGraphStore


class _FakeResult:
    def __init__(self, rows: list[list[object]]) -> None:
        self.result_set = rows


class _FakeGraph:
    def __init__(self, rows: list[list[object]]) -> None:
        self.rows = rows
        self.query_text = ""
        self.params: dict[str, object] = {}

    def ro_query(self, query: str, params: dict[str, object]) -> _FakeResult:
        self.query_text = query
        self.params = params
        return _FakeResult(self.rows)


def test_get_related_sections_uses_bounded_section_entity_section_query() -> None:
    """Two-hop enrichment must not use unbounded variable-length traversal."""
    store = FalkorDBGraphStore.__new__(FalkorDBGraphStore)
    graph = _FakeGraph(
        [
            ["chunk-2", "MENTIONS", 0.7],
            ["chunk-1", "MENTIONS", 1.0],
        ]
    )
    store.__dict__["_graph"] = graph

    neighbors = store.get_related_sections("chunk-1")

    assert "[*1.." not in graph.query_text
    assert "(:Section {id: $id})-[r1:REL]->(mid:Node)<-[r2:REL]-(s:Section)" in graph.query_text
    assert "(mid:Entity OR mid:Tag)" in graph.query_text
    assert "MENTIONS" in graph.query_text
    assert "TAGGED" not in graph.query_text
    assert graph.params == {"id": "chunk-1"}
    assert neighbors == [("chunk-2", "MENTIONS", 0.7)]


def test_get_related_sections_for_seeds_uses_a_single_bounded_batch_query() -> None:
    """Batch enrichment must stay on one query and keep explicit graph labels."""
    store = FalkorDBGraphStore.__new__(FalkorDBGraphStore)
    graph = _FakeGraph(
        [
            ["chunk-2", "MENTIONS", 0.7],
            ["chunk-3", "HAS_TAG", 0.4],
        ]
    )
    store.__dict__["_graph"] = graph

    neighbors = store.get_related_sections_for_seeds(["chunk-1", "chunk-2"])

    assert graph.query_text.startswith("UNWIND $ids AS seed_id MATCH (seed:Section {id: seed_id})")
    assert "mid:Node" in graph.query_text
    assert "(mid:Entity OR mid:Tag)" in graph.query_text
    assert "r1.rel_type IN ['MENTIONS', 'HAS_TAG']" in graph.query_text
    assert "r2.rel_type IN ['MENTIONS', 'HAS_TAG']" in graph.query_text
    assert "s.id <> seed_id" in graph.query_text
    assert graph.params == {"ids": ["chunk-1", "chunk-2"]}
    assert neighbors == [("chunk-2", "MENTIONS", 0.7), ("chunk-3", "HAS_TAG", 0.4)]
