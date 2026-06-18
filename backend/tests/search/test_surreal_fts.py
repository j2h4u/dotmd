from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from dotmd.search.surreal_fts import SurrealFTSConfig, SurrealFTSSearchEngine


@dataclass
class FakeSurrealConnection:
    statements: list[tuple[str, dict[str, Any] | None]] = field(default_factory=list)
    expected_query: str = "Alpha beta"
    expected_limit: int = 4
    error: Exception | None = None

    def query(self, statement: str, variables: dict[str, Any] | None = None) -> Any:
        self.statements.append((statement, variables))
        if self.error is not None:
            raise self.error
        if statement.startswith("EXPLAIN FULL SELECT chunk_id, search::score(0)"):
            return [{"plan": {"index": "chunks_title_fts"}}]
        if statement.startswith("EXPLAIN FULL SELECT chunk_id, search::score(1)"):
            return [{"plan": {"index": "chunks_text_fts"}}]
        if "WITH INDEX chunks_title_fts" in statement:
            assert statement == (
                "SELECT chunk_id, search::score(0) AS score FROM chunks "
                "WITH INDEX chunks_title_fts WHERE chunk_strategy = $chunk_strategy "
                "AND title @0@ $query ORDER BY score DESC LIMIT $limit TIMEOUT 7s;"
            )
            assert variables == {
                "query": self.expected_query,
                "limit": self.expected_limit,
                "chunk_strategy": "contextual_512_50",
            }
            return [
                {"chunk_id": "chunk-a", "score": 0.9},
                {"chunk_id": "chunk-b", "score": 0.4},
                {"chunk_id": "chunk-dup", "score": 0.3},
            ]
        if "WITH INDEX chunks_text_fts" in statement:
            assert statement == (
                "SELECT chunk_id, search::score(1) AS score FROM chunks "
                "WITH INDEX chunks_text_fts WHERE chunk_strategy = $chunk_strategy "
                "AND text @1@ $query ORDER BY score DESC LIMIT $limit TIMEOUT 7s;"
            )
            assert variables == {
                "query": self.expected_query,
                "limit": self.expected_limit,
                "chunk_strategy": "contextual_512_50",
            }
            return [
                {"chunk_id": "chunk-dup", "score": 0.6},
                {"chunk_id": "chunk-c", "score": 0.2},
            ]
        raise AssertionError(f"unexpected statement: {statement}")


def test_surreal_fts_search_uses_title_and_text_queries_with_weighting_and_dedup() -> None:
    connection = FakeSurrealConnection()
    engine = SurrealFTSSearchEngine(
        connection,
        search_config=SurrealFTSConfig(query_timeout_seconds=120, max_query_timeout_seconds=7),
    )

    results = engine.search("  Alpha; beta  ", top_k=4)

    assert results == [
        ("chunk-a", pytest.approx(4.5)),
        ("chunk-dup", pytest.approx(2.1)),
        ("chunk-b", pytest.approx(2.0)),
        ("chunk-c", pytest.approx(0.2)),
    ]
    assert len(connection.statements) == 2
    assert all(
        not statement.startswith("EXPLAIN FULL") for statement, _ in connection.statements
    )


def test_surreal_fts_search_returns_empty_for_blank_query() -> None:
    connection = FakeSurrealConnection()
    engine = SurrealFTSSearchEngine(connection)

    assert engine.search("  ;;;  ") == []
    assert connection.statements == []


def test_surreal_fts_search_returns_empty_on_query_failure() -> None:
    connection = FakeSurrealConnection(error=RuntimeError("surreal failure"))
    engine = SurrealFTSSearchEngine(connection)

    assert engine.search("Alpha", top_k=3) == []
    assert len(connection.statements) == 1


def test_surreal_fts_search_can_emit_explain_queries() -> None:
    connection = FakeSurrealConnection(expected_query="Alpha", expected_limit=2)
    engine = SurrealFTSSearchEngine(
        connection,
        search_config=SurrealFTSConfig(query_timeout_seconds=120, max_query_timeout_seconds=7, explain=True),
    )

    assert engine.search("Alpha", top_k=2) == [
        ("chunk-a", pytest.approx(4.5)),
        ("chunk-dup", pytest.approx(2.1)),
    ]
    assert connection.statements[0][0].startswith("EXPLAIN FULL SELECT chunk_id")
    assert connection.statements[1][0].startswith("SELECT chunk_id")
    assert connection.statements[2][0].startswith("EXPLAIN FULL SELECT chunk_id")
    assert connection.statements[3][0].startswith("SELECT chunk_id")
