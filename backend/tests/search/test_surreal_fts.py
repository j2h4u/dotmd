from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from dotmd.search.surreal_fts import SurrealFTSConfig, SurrealFTSSearchEngine


@dataclass
class FakeSurrealConnection:
    query_calls: list[tuple[str, dict[str, Any] | None]] = field(default_factory=list)
    query_raw_calls: list[tuple[str, dict[str, Any] | None]] = field(default_factory=list)
    expected_query: str = "Alpha beta"
    expected_limit: int = 4
    raw_error: Exception | None = None
    explain_error: Exception | None = None

    def query(self, statement: str, variables: dict[str, Any] | None = None) -> Any:
        self.query_calls.append((statement, variables))
        if self.explain_error is not None:
            raise self.explain_error
        if statement.startswith("EXPLAIN FULL SELECT chunk_id, search::score(0) AS score "):
            return [{"plan": {"indexes": ["chunks_title_fts", "chunks_text_fts"]}}]
        raise AssertionError(f"unexpected explain statement: {statement}")

    def query_raw(self, statement: str, variables: dict[str, Any] | None = None) -> Any:
        self.query_raw_calls.append((statement, variables))
        if self.raw_error is not None:
            raise self.raw_error
        assert statement == (
            "SELECT chunk_id, search::score(0) AS score "
            "FROM chunks WITH INDEX chunks_title_fts "
            "WHERE chunk_strategy = $chunk_strategy "
            "AND title @0@ $query "
            "ORDER BY score DESC LIMIT $limit TIMEOUT 7s; "
            "SELECT chunk_id, search::score(1) AS score "
            "FROM chunks WITH INDEX chunks_text_fts "
            "WHERE chunk_strategy = $chunk_strategy "
            "AND text @1@ $query "
            "ORDER BY score DESC LIMIT $limit TIMEOUT 7s;"
        )
        assert variables == {
            "query": self.expected_query,
            "limit": self.expected_limit,
            "chunk_strategy": "contextual_512_50",
        }
        return {
            "result": [
                {
                    "result": [
                        {"chunk_id": "chunk-a", "score": 0.9},
                        {"chunk_id": "chunk-dup", "score": 0.2},
                    ],
                    "status": "OK",
                    "time": "1ms",
                },
                {
                    "result": [
                        {"chunk_id": "chunk-dup", "score": 0.4},
                        {"chunk_id": "chunk-b", "score": 0.3},
                    ],
                    "status": "OK",
                    "time": "1ms",
                },
            ]
        }


def test_surreal_fts_search_uses_one_query_raw_roundtrip_with_weighted_fusion() -> None:
    connection = FakeSurrealConnection()
    engine = SurrealFTSSearchEngine(
        connection,
        search_config=SurrealFTSConfig(query_timeout_seconds=120, max_query_timeout_seconds=7),
    )

    results = engine.search("  Alpha; beta  ", top_k=4)

    assert results == [
        ("chunk-a", pytest.approx(4.5)),
        ("chunk-dup", pytest.approx(1.4)),
        ("chunk-b", pytest.approx(0.3)),
    ]
    assert len(connection.query_calls) == 0
    assert len(connection.query_raw_calls) == 1


def test_surreal_fts_search_returns_empty_for_blank_query() -> None:
    connection = FakeSurrealConnection()
    engine = SurrealFTSSearchEngine(connection)

    assert engine.search("  ;;;  ") == []
    assert connection.query_calls == []
    assert connection.query_raw_calls == []


def test_surreal_fts_search_returns_empty_on_query_failure() -> None:
    connection = FakeSurrealConnection(raw_error=RuntimeError("surreal failure"))
    engine = SurrealFTSSearchEngine(connection)

    assert engine.search("Alpha", top_k=3) == []
    assert len(connection.query_raw_calls) == 1


def test_surreal_fts_search_can_emit_explain_queries() -> None:
    connection = FakeSurrealConnection(expected_query="Alpha", expected_limit=2)
    engine = SurrealFTSSearchEngine(
        connection,
        search_config=SurrealFTSConfig(query_timeout_seconds=120, max_query_timeout_seconds=7, explain=True),
    )

    assert engine.search("Alpha", top_k=2) == [
        ("chunk-a", pytest.approx(4.5)),
        ("chunk-dup", pytest.approx(1.4)),
    ]
    assert len(connection.query_calls) == 1
    assert len(connection.query_raw_calls) == 1
    assert connection.query_calls[0][0].startswith("EXPLAIN FULL SELECT chunk_id, search::score(0) AS score ")
    assert connection.query_raw_calls[0][0].startswith("SELECT chunk_id, search::score(0) AS score ")
