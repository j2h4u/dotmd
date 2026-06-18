from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from devtools.surreal_fts_gate import FtsGateConfig, build_parser, run_gate

from dotmd.storage.surreal import SurrealStoreConfig

pytestmark = pytest.mark.real_schema_check


@dataclass
class FakeConnection:
    config: SurrealStoreConfig
    analyzer_name: str = "dotmd_fts"
    index_states: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {
            "chunks_title_fts": [
                {"building": {"status": "indexing", "initial": 100, "pending": 40, "updated": 0}},
                {"building": {"status": "ready"}},
            ],
            "chunks_text_fts": [
                {"building": {"status": "indexing", "initial": 100, "pending": 20, "updated": 0}},
                {"building": {"status": "ready"}},
            ],
        }
    )
    queries: list[tuple[str, dict[str, Any] | None]] = field(default_factory=list)
    closed: bool = False

    def _index_name(self, statement: str) -> str:
        if "chunks_title_fts" in statement:
            return "chunks_title_fts"
        if "chunks_text_fts" in statement:
            return "chunks_text_fts"
        if "custom_title_fts" in statement:
            return "custom_title_fts"
        if "custom_text_fts" in statement:
            return "custom_text_fts"
        raise AssertionError(f"could not infer index name from: {statement}")

    def query(self, statement: str, variables: dict[str, Any] | None = None) -> Any:
        self.queries.append((statement, variables))
        assert statement.endswith(";")
        if statement.startswith("DEFINE ANALYZER"):
            return []
        if statement.startswith("DEFINE INDEX"):
            return []
        if statement.startswith("INFO FOR INDEX"):
            index_name = self._index_name(statement)
            states = self.index_states.setdefault(index_name, [{"building": {"status": "ready"}}])
            return states.pop(0) if states else {"building": {"status": "ready"}}
        if statement == "SELECT id, title, text FROM chunks LIMIT 1;":
            return [{"id": "chunks:sample", "title": "Alpha title", "text": "beta text"}]
        if statement.startswith("RETURN search::analyze"):
            assert variables == {"analyzer": self.analyzer_name, "probe": "Alpha"}
            return ["alpha"]
        if "FROM chunks WHERE title @0@ $query" in statement:
            assert variables == {"query": "Alpha"}
            assert "EXPLAIN FULL" in statement
            return [
                {
                    "operation": "Iterate Index",
                    "detail": {"plan": {"index": "chunks_title_fts"}},
                }
            ]
        if "FROM chunks WHERE text @0@ $query" in statement:
            assert variables == {"query": "beta"}
            assert "EXPLAIN FULL" in statement
            return [
                {
                    "operation": "Iterate Index",
                    "detail": {"plan": {"index": "chunks_text_fts"}},
                }
            ]
        raise AssertionError(f"unexpected statement: {statement}")

    def close(self) -> None:
        self.closed = True


class FakeClock:
    def __init__(self, values: list[float]) -> None:
        self._values = values
        self.calls = 0

    def __call__(self) -> float:
        if self.calls < len(self._values):
            value = self._values[self.calls]
            self.calls += 1
            return value
        value = self._values[-1]
        return value


def test_build_parser_supports_gate_options() -> None:
    parser = build_parser()

    defaults = parser.parse_args([])

    args = parser.parse_args(
        [
            "--probe-term",
            "glossary",
            "--limit",
            "3",
            "--apply-mode",
            "blocking",
            "--db-timeout-seconds",
            "12",
            "--build-timeout-seconds",
            "90",
            "--poll-interval-seconds",
            "2.5",
            "--max-seconds",
            "2.5",
            "--no-explain",
        ]
    )

    assert args.probe_term == "glossary"
    assert args.limit == 3
    assert args.apply_mode == "blocking"
    assert args.db_timeout_seconds == 12
    assert args.build_timeout_seconds == 90
    assert args.poll_interval_seconds == 2.5
    assert args.max_seconds == 2.5
    assert args.explain is False
    assert defaults.poll_interval_seconds == 60.0


def test_run_gate_applies_schema_and_checks_both_indexes(capsys: pytest.CaptureFixture[str]) -> None:
    store_config = SurrealStoreConfig(
        url="ws://example.invalid/rpc",
        namespace="dotmd",
        database="phase43",
        username="root",
        password="secret",
    )
    gate_config = FtsGateConfig(max_seconds=1.0)
    holder: dict[str, FakeConnection] = {}
    clock = FakeClock([
        0.0, 0.05, 0.05, 0.10, 0.10, 0.15, 0.15, 0.20, 0.20, 0.30, 0.30, 0.40,
        0.40, 0.50, 0.50, 0.60, 0.60, 0.70, 0.70, 0.80, 0.80, 0.90, 0.90, 1.00,
    ])

    def factory(config: SurrealStoreConfig) -> FakeConnection:
        connection = FakeConnection(config)
        holder["connection"] = connection
        return connection

    result = run_gate(
        store_config,
        gate_config,
        connection_factory=factory,
        clock=clock,
        sleeper=lambda _seconds: None,
    )

    captured = capsys.readouterr().out
    assert "surreal fts gate: applying 3 schema statements" in captured
    assert "surreal fts gate: probes title='Alpha' text='beta'" in captured
    assert "surreal fts gate: index=chunks_title_fts status=indexing" in captured
    assert "surreal fts gate: index=chunks_text_fts status=indexing" in captured
    assert "surreal fts gate: index=chunks_title_fts status=ready" in captured
    assert "surreal fts gate: index=chunks_text_fts status=ready" in captured
    assert result.passed is True
    assert result.title_rows == 1
    assert result.text_rows == 1
    assert holder["connection"].closed is True
    assert len(holder["connection"].queries) == 11
    assert holder["connection"].queries[0][0] == (
        "DEFINE ANALYZER IF NOT EXISTS dotmd_fts TOKENIZERS class, punct "
        "FILTERS lowercase, ascii;"
    )
    assert holder["connection"].queries[1][0] == (
        "DEFINE INDEX IF NOT EXISTS chunks_title_fts ON TABLE chunks FIELDS title "
        "FULLTEXT ANALYZER dotmd_fts BM25(1.2,0.75) CONCURRENTLY;"
    )
    assert holder["connection"].queries[2][0] == (
        "DEFINE INDEX IF NOT EXISTS chunks_text_fts ON TABLE chunks FIELDS text "
        "FULLTEXT ANALYZER dotmd_fts BM25(1.2,0.75) CONCURRENTLY;"
    )
    assert holder["connection"].queries[3][0] == "INFO FOR INDEX chunks_title_fts ON chunks;"
    assert holder["connection"].queries[4][0] == "INFO FOR INDEX chunks_text_fts ON chunks;"
    assert holder["connection"].queries[5][0] == "INFO FOR INDEX chunks_title_fts ON chunks;"
    assert holder["connection"].queries[6][0] == "INFO FOR INDEX chunks_text_fts ON chunks;"


def test_run_gate_uses_custom_names_consistently() -> None:
    store_config = SurrealStoreConfig()
    gate_config = FtsGateConfig(
        analyzer_name="custom_fts",
        title_index_name="custom_title_fts",
        text_index_name="custom_text_fts",
        max_seconds=1.0,
    )

    class CustomNameConnection(FakeConnection):
        def query(self, statement: str, variables: dict[str, Any] | None = None) -> Any:
            if statement.startswith("DEFINE ANALYZER"):
                assert "custom_fts" in statement
            if statement.startswith("DEFINE INDEX"):
                assert "custom_title_fts" in statement or "custom_text_fts" in statement
            result = super().query(statement, variables)
            if "FROM chunks WHERE title @0@ $query" in statement:
                return [
                    {
                        "operation": "Iterate Index",
                        "detail": {"plan": {"index": "custom_title_fts"}},
                    }
                ]
            if "FROM chunks WHERE text @0@ $query" in statement:
                return [
                    {
                        "operation": "Iterate Index",
                        "detail": {"plan": {"index": "custom_text_fts"}},
                    }
                ]
            return result

    def factory(config: SurrealStoreConfig) -> CustomNameConnection:
        return CustomNameConnection(config, analyzer_name=gate_config.analyzer_name)

    clock = FakeClock([0.0, 0.05, 0.05, 0.10, 0.10, 0.15, 0.15, 0.35, 0.35, 0.45, 0.45, 0.65, 0.65, 0.85])

    result = run_gate(
        store_config,
        gate_config,
        connection_factory=factory,
        clock=clock,
        sleeper=lambda _seconds: None,
    )

    assert result.passed is True


def test_run_gate_fails_when_explain_plan_lacks_expected_index() -> None:
    store_config = SurrealStoreConfig()
    gate_config = FtsGateConfig(max_seconds=1.0)

    class MissingIndexConnection(FakeConnection):
        def query(self, statement: str, variables: dict[str, Any] | None = None) -> Any:
            result = super().query(statement, variables)
            if "FROM chunks WHERE title @0@ $query" in statement:
                return [{"operation": "Iterate Table", "detail": {"plan": {"table": "chunks"}}}]
            return result

    clock = FakeClock([0.0, 0.05, 0.05, 0.10, 0.10, 0.15, 0.15, 0.35, 0.35, 0.45, 0.45, 0.65, 0.65, 0.85])

    result = run_gate(
        store_config,
        gate_config,
        connection_factory=MissingIndexConnection,
        clock=clock,
        sleeper=lambda _seconds: None,
    )

    assert result.passed is False
