from __future__ import annotations

import logging

import pytest

from tests.fixtures.surreal_native import (
    apply_surreal_native_retrieval_schema,
    isolated_surreal_connection,
)


def _engine_class():
    from dotmd.search.surreal_fts import SurrealFTSSearchEngine

    return SurrealFTSSearchEngine


class _FakeFTSConnection:
    def __init__(
        self,
        *,
        rows: list[dict[str, object]] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.rows = rows or []
        self.error = error
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def query(
        self,
        statement: str,
        variables: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        self.calls.append((statement, variables))
        if self.error is not None:
            raise self.error
        return list(self.rows)


def test_search_returns_empty_for_blank_or_punctuation_queries_without_hitting_surreal() -> None:
    engine = _engine_class()(_FakeFTSConnection())

    assert engine.search("", top_k=5) == []
    assert engine.search("   ", top_k=5) == []
    assert engine.search("!!! ???", top_k=5) == []


def test_search_uses_fixed_weighted_surrealql_with_bound_query_variables() -> None:
    connection = _FakeFTSConnection(
        rows=[
            {"chunk_id": "chunk-title", "score": 9.5},
            {"chunk_id": "chunk-tags", "score": 3.0},
        ]
    )
    engine = _engine_class()(connection)

    results = engine.search('surreal: retrieval!!! "quoted"', top_k=7)

    assert results == [("chunk-title", 9.5), ("chunk-tags", 3.0)]
    assert len(connection.calls) == 1

    statement, variables = connection.calls[0]
    assert "SELECT chunk_id" in statement
    assert "FROM chunks" in statement
    assert "title @1@ $query" in statement
    assert "tags_text @2@ $query" in statement
    assert "text @3@ $query" in statement
    assert "5 * search::score(1)" in statement
    assert "3 * search::score(2)" in statement
    assert "1 * search::score(3)" in statement
    assert "ORDER BY score DESC, chunk_id ASC" in statement
    assert variables == {"query": "surreal retrieval quoted", "limit": 7}
    assert "surreal: retrieval!!!" not in statement


def test_search_logs_and_returns_empty_on_surreal_errors(caplog: pytest.LogCaptureFixture) -> None:
    connection = _FakeFTSConnection(error=RuntimeError("surreal parse error"))
    engine = _engine_class()(connection)

    with caplog.at_level(logging.WARNING):
        results = engine.search("surreal retrieval", top_k=3)

    assert results == []
    assert len(connection.calls) == 1
    assert "query_len=17" in caplog.text
    assert "error_type=RuntimeError" in caplog.text


def test_embedded_surreal_fts_returns_weighted_chunk_hits(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with isolated_surreal_connection(tmp_path) as connection:
        apply_surreal_native_retrieval_schema(connection, embedding_dimension=3, hnsw_ef=40)
        connection.create(
            "chunks:title-tag",
            {
                "schema_version": "42.1.0",
                "original_chunk_id": "chunk:title-tag",
                "chunk_id": "chunk:title-tag",
                "chunk_strategy": "contextual_512_50",
                "document_ref": "doc:title-tag",
                "ref": "filesystem:/tmp/title-tag.md",
                "title": "Surreal Retrieval Guide",
                "tags_text": "surreal weighted",
                "text": "Guide body",
                "metadata": {},
            },
        )
        connection.create(
            "chunks:body-only",
            {
                "schema_version": "42.1.0",
                "original_chunk_id": "chunk:body-only",
                "chunk_id": "chunk:body-only",
                "chunk_strategy": "contextual_512_50",
                "document_ref": "doc:body-only",
                "ref": "filesystem:/tmp/body-only.md",
                "title": "General Notes",
                "tags_text": "",
                "text": "surreal retrieval appears only in the body text",
                "metadata": {},
            },
        )

        engine = _engine_class()(connection)
        results = engine.search("surreal retrieval", top_k=5)

    assert results
    assert results[0][0] == "chunk:title-tag"
    assert results[0][1] > 0.0
