from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from devtools.surreal_knn_gate import KnnGateConfig, run_gate

from dotmd.storage.surreal import SurrealStoreConfig

pytestmark = pytest.mark.real_schema_check


@dataclass
class FakeSurrealConnection:
    config: SurrealStoreConfig
    elapsed: float
    statements: list[str] = field(default_factory=list)
    closed: bool = False

    def query(self, statement: str, variables: dict[str, Any] | None = None) -> Any:
        self.statements.append(statement)
        if "LIMIT 1" in statement:
            return [{"id": "embeddings:sample", "vector": [1.0, 2.0, 3.0, 4.0]}]
        assert "WHERE vector <|5,80|> $query_vector TIMEOUT 30s" in statement
        assert variables == {"query_vector": [1.0, 2.0, 3.0, 4.0]}
        if "EXPLAIN FULL" in statement:
            return {"operator": "Timeout", "total_rows": 1}
        return [{"id": "embeddings:sample", "chunk_id": "chunk-1"}]

    def close(self) -> None:
        self.closed = True


def test_knn_gate_passes_when_query_is_under_threshold() -> None:
    holder: dict[str, FakeSurrealConnection] = {}
    times = iter([0.0, 0.1, 0.1, 1.6])

    def factory(config: SurrealStoreConfig) -> FakeSurrealConnection:
        connection = FakeSurrealConnection(config, elapsed=1.5)
        holder["connection"] = connection
        return connection

    messages: list[str] = []
    result = run_gate(
        SurrealStoreConfig(),
        KnnGateConfig(max_seconds=2.0),
        connection_factory=factory,
        printer=lambda message, **_: messages.append(message),
        clock=lambda: next(times),
    )

    assert result.passed is True
    assert result.sample_seconds == pytest.approx(0.1)
    assert result.knn_seconds == pytest.approx(1.5)
    assert result.row_count == 1
    assert holder["connection"].closed is True
    assert "status=pass" in messages[-1]


def test_knn_gate_fails_when_query_exceeds_threshold() -> None:
    times = iter([0.0, 0.1, 0.1, 6.1])

    result = run_gate(
        SurrealStoreConfig(),
        KnnGateConfig(max_seconds=5.0),
        connection_factory=lambda config: FakeSurrealConnection(config, elapsed=6.0),
        printer=lambda *_args, **_kwargs: None,
        clock=lambda: next(times),
    )

    assert result.passed is False
    assert result.knn_seconds == pytest.approx(6.0)


def test_knn_gate_prints_explain_result() -> None:
    times = iter([0.0, 0.1, 0.1, 0.2])
    messages: list[str] = []

    result = run_gate(
        SurrealStoreConfig(),
        KnnGateConfig(explain=True),
        connection_factory=lambda config: FakeSurrealConnection(config, elapsed=0.1),
        printer=lambda message, **_: messages.append(message),
        clock=lambda: next(times),
    )

    assert result.passed is True
    assert result.row_count == 1
    assert any(message.startswith("surreal knn gate: explain ") for message in messages)
