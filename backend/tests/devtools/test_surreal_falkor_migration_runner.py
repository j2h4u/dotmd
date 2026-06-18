from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from devtools.surreal_falkor_migration_runner import (
    FalkorMigrationConfig,
    _edge_record,
    _node_record,
    run_falkor_migration,
)

from dotmd.storage.surreal import SurrealStoreConfig

pytestmark = pytest.mark.real_schema_check


@dataclass
class FakeNode:
    labels: list[str]
    properties: dict[str, Any]


@dataclass
class FakeRelation:
    properties: dict[str, Any]
    relation: str = "REL"


class FakeReader:
    def __init__(self, url: str, graph_name: str) -> None:
        self.url = url
        self.graph_name = graph_name

    def count_nodes(self, label: str) -> int:
        return len(self._nodes(label))

    def read_nodes(self, label: str, *, skip: int, limit: int) -> list[FakeNode]:
        return self._nodes(label)[skip : skip + limit]

    def _nodes(self, label: str) -> list[FakeNode]:
        if label == "File":
            return [FakeNode(["File", "Node"], {"id": "/mnt/doc.md", "title": "Doc"})]
        if label == "Section":
            return [FakeNode(["Section", "Node"], {"id": "chunk-1", "heading": "H"})]
        return []

    def count_edges(self) -> int:
        return len(self._edges())

    def read_edges(self, *, skip: int, limit: int) -> list[tuple[FakeNode, FakeRelation, FakeNode]]:
        return self._edges()[skip : skip + limit]

    def _edges(self) -> list[tuple[FakeNode, FakeRelation, FakeNode]]:
        return [
            (
                FakeNode(["File", "Node"], {"id": "/mnt/doc.md"}),
                FakeRelation({"rel_type": "CONTAINS", "weight": 1.0}),
                FakeNode(["Section", "Node"], {"id": "chunk-1"}),
            )
        ]


@dataclass
class FakeSurrealConnection:
    config: SurrealStoreConfig
    batches: list[list[dict[str, Any]]] = field(default_factory=list)
    closed: bool = False

    def query(self, statement: str, variables: dict[str, Any] | None = None) -> None:
        assert statement.startswith("FOR $row IN $rows")
        assert variables is not None
        self.batches.append(variables["rows"])

    def close(self) -> None:
        self.closed = True


def test_node_record_preserves_labels_and_properties() -> None:
    record = _node_record(FakeNode(["Section", "Node"], {"id": "chunk-1", "level": 2}), "Section")

    assert record == {
        "type": "graph_node",
        "data": {
            "node_id": "chunk-1",
            "labels": ["Section", "Node"],
            "primary_label": "Section",
            "properties": {"id": "chunk-1", "level": 2},
        },
    }


def test_edge_record_preserves_endpoint_labels_and_relation_properties() -> None:
    record = _edge_record(
        FakeNode(["File", "Node"], {"id": "/mnt/doc.md"}),
        FakeRelation({"rel_type": "CONTAINS", "weight": 1.0}),
        FakeNode(["Section", "Node"], {"id": "chunk-1"}),
        edge_key="42",
    )

    assert record["type"] == "graph_edge"
    assert record["data"]["source_id"] == "/mnt/doc.md"
    assert record["data"]["source_labels"] == ["File", "Node"]
    assert record["data"]["target_id"] == "chunk-1"
    assert record["data"]["target_labels"] == ["Section", "Node"]
    assert record["data"]["edge_key"] == "42"
    assert record["data"]["relation_label"] == "REL"
    assert record["data"]["relation_type"] == "CONTAINS"
    assert record["data"]["properties"] == {"rel_type": "CONTAINS", "weight": 1.0}


def test_run_falkor_migration_writes_nodes_and_edges() -> None:
    holder: dict[str, FakeSurrealConnection] = {}

    def connection_factory(config: SurrealStoreConfig) -> FakeSurrealConnection:
        connection = FakeSurrealConnection(config)
        holder["connection"] = connection
        return connection

    result = run_falkor_migration(
        SurrealStoreConfig(),
        FalkorMigrationConfig(
            falkor_url="redis://falkordb:6379",
            graph_name="dotmd",
            batch_size=2,
        ),
        graph_reader_factory=FakeReader,
        connection_factory=connection_factory,
    )

    assert result.nodes == 2
    assert result.edges == 1
    assert holder["connection"].closed is True
    flattened = [row for batch in holder["connection"].batches for row in batch]
    assert len(flattened) == 3
    assert {row["data"]["node_id"] for row in flattened if "node_id" in row["data"]} == {
        "/mnt/doc.md",
        "chunk-1",
    }
    assert [row["data"]["relation_type"] for row in flattened if "relation_type" in row["data"]] == [
        "CONTAINS"
    ]
