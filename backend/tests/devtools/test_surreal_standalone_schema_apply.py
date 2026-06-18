from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pytest
from devtools.surreal_standalone_schema_apply import (
    SchemaApplyConfig,
    build_parser,
    load_config,
    run_apply,
)

from dotmd.storage.surreal import SurrealStoreConfig

pytestmark = pytest.mark.real_schema_check


@dataclass
class FakeConnection:
    config: SurrealStoreConfig
    queries: list[str] = field(default_factory=list)
    closed: bool = False

    def query(self, statement: str, variables: dict[str, Any] | None = None) -> None:
        assert variables is None
        self.queries.append(statement)

    def close(self) -> None:
        self.closed = True


class FakePlan:
    def __init__(self, statements: tuple[str, ...]) -> None:
        self._statements = statements
        self.calls: list[str] = []

    def statements(self, *, vector_index: str = "hnsw") -> Sequence[str]:
        self.calls.append(vector_index)
        return self._statements


class FakeClock:
    def __init__(self, values: list[float]) -> None:
        self._values = values
        self.calls = 0

    def __call__(self) -> float:
        value = self._values[self.calls]
        self.calls += 1
        return value


def test_build_parser_supports_embedding_dimension_and_vector_index() -> None:
    parser = build_parser()

    args = parser.parse_args(["--embedding-dimension", "768", "--vector-index", "none"])

    assert args.embedding_dimension == 768
    assert args.vector_index == "none"


def test_load_config_uses_surreal_store_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SURREALDB_URL", "ws://surrealdb:8000/rpc")
    monkeypatch.setenv("SURREAL_USER", "root")
    monkeypatch.setenv("SURREAL_PASS", "secret")
    args = argparse.Namespace(embedding_dimension=1024, vector_index="diskann")

    store_config, schema_config = load_config(args)

    assert store_config.url == "ws://surrealdb:8000/rpc"
    assert store_config.namespace == "dotmd"
    assert store_config.database == "phase43"
    assert store_config.username == "root"
    assert store_config.password == "secret"
    assert schema_config == SchemaApplyConfig(embedding_dimension=1024, vector_index="diskann")


def test_run_apply_prints_progress_and_applies_each_statement(capsys: pytest.CaptureFixture[str]) -> None:
    store_config = SurrealStoreConfig(
        url="ws://example.invalid/rpc",
        namespace="dotmd",
        database="phase43",
        username="root",
        password="secret",
    )
    schema_config = SchemaApplyConfig(embedding_dimension=1024, vector_index="hnsw")
    plan = FakePlan(("DEFINE TABLE documents SCHEMAFULL;", "DEFINE TABLE chunks SCHEMAFULL;"))
    connection_holder: dict[str, FakeConnection] = {}
    clock = FakeClock([0.0, 0.2, 0.4, 0.6, 0.9, 1.0])

    def connection_factory(config: SurrealStoreConfig) -> FakeConnection:
        connection = FakeConnection(config)
        connection_holder["value"] = connection
        return connection

    result = run_apply(
        store_config,
        schema_config,
        plan_builder=lambda dimension: plan,
        connection_factory=connection_factory,
        clock=clock,
    )

    captured = capsys.readouterr().out
    assert "connecting url=ws://example.invalid/rpc" in captured
    assert "building plan embedding_dimension=1024 vector_index=hnsw" in captured
    assert "[1/2] applying: DEFINE TABLE documents SCHEMAFULL;" in captured
    assert "[1/2] done in 0.200s" in captured
    assert "[2/2] applying: DEFINE TABLE chunks SCHEMAFULL;" in captured
    assert "[2/2] done in 0.300s" in captured
    assert plan.calls == ["hnsw"]
    assert connection_holder["value"].queries == [
        "DEFINE TABLE documents SCHEMAFULL;",
        "DEFINE TABLE chunks SCHEMAFULL;",
    ]
    assert connection_holder["value"].closed is True
    assert result.statement_count == 2
    assert result.vector_index == "hnsw"


def test_run_apply_uses_none_vector_index_without_querying_index_statements(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_config = SurrealStoreConfig(
        url="ws://example.invalid/rpc",
        namespace="dotmd",
        database="phase43",
        username="root",
        password="secret",
    )
    schema_config = SchemaApplyConfig(embedding_dimension=1024, vector_index="none")
    plan = FakePlan(("DEFINE TABLE documents SCHEMAFULL;",))

    result = run_apply(
        store_config,
        schema_config,
        plan_builder=lambda dimension: plan,
        connection_factory=FakeConnection,
        clock=FakeClock([0.0, 0.1, 0.2, 0.3]),
    )

    assert plan.calls == ["none"]
    assert result.statement_count == 1
    assert "vector_index=none" in capsys.readouterr().out
