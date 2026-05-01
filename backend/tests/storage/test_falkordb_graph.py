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
    graph = _FakeGraph([
        ["chunk-2", "MENTIONS", 0.7],
        ["chunk-1", "MENTIONS", 1.0],
    ])
    store.__dict__["_graph"] = graph

    neighbors = store.get_related_sections("chunk-1")

    assert "[*1.." not in graph.query_text
    assert "(:Section {id: $id})-[r1:REL]->(mid:Node)<-[r2:REL]-(s:Section)" in graph.query_text
    assert "(mid:Entity OR mid:Tag)" in graph.query_text
    assert "MENTIONS" in graph.query_text
    assert "TAGGED" not in graph.query_text
    assert graph.params == {"id": "chunk-1"}
    assert neighbors == [("chunk-2", "MENTIONS", 0.7)]


def test_get_neighbors_remains_generic_graph_traversal() -> None:
    store = FalkorDBGraphStore.__new__(FalkorDBGraphStore)
    graph = _FakeGraph([["Python", "Entity"]])
    store.__dict__["_graph"] = graph

    neighbors = store.get_neighbors("chunk-1", max_hops=1)

    assert "MATCH (a:Node {id: $id})-[*1..1]-(b:Node)" in graph.query_text
    assert neighbors == [("Python", "Entity", 1.0)]
