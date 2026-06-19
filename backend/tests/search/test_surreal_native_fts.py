from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pytest
from tests.fixtures.surreal_native import (
    apply_surreal_native_retrieval_schema,
    isolated_surreal_connection,
)


@pytest.fixture(autouse=True)
def _propagate_dotmd_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(logging.getLogger("dotmd"), "propagate", True)


def _engine_class():
    from dotmd.search.surreal_fts import SurrealFTSSearchEngine

    return SurrealFTSSearchEngine


@dataclass
class _FakeFTSConnection:
    title_rows: list[dict[str, object]] = field(default_factory=list)
    text_rows: list[dict[str, object]] = field(default_factory=list)
    combined_rows: list[dict[str, object]] | None = None
    error: Exception | None = None
    calls: list[tuple[str, dict[str, object] | None]] = field(default_factory=list)

    def query(
        self,
        statement: str,
        variables: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        self.calls.append((statement, variables))
        if self.error is not None:
            raise self.error
        if statement.startswith("EXPLAIN FULL SELECT chunk_id, "):
            return [{"plan": {"indexes": ["chunks_title_fts", "chunks_text_fts"]}}]
        if "WITH INDEX chunks_title_fts, chunks_text_fts" in statement:
            if self.combined_rows is not None:
                return list(self.combined_rows)
            return [
                {"chunk_id": "chunk-a", "score": 4.5},
                {"chunk_id": "chunk-dup", "score": 2.1},
                {"chunk_id": "chunk-b", "score": 2.0},
                {"chunk_id": "chunk-c", "score": 0.2},
            ]
        return []


def test_search_returns_empty_for_blank_or_punctuation_queries_without_hitting_surreal() -> None:
    engine = _engine_class()(_FakeFTSConnection())

    assert engine.search("", top_k=5) == []
    assert engine.search("   ", top_k=5) == []
    assert engine.search("!!! ???", top_k=5) == []


def test_search_uses_one_query_with_bound_query_variables() -> None:
    connection = _FakeFTSConnection(
    )
    engine = _engine_class()(connection)

    results = engine.search('surreal: retrieval!!! "quoted"', top_k=7)

    assert results == [
        ("chunk-a", 4.5),
        ("chunk-dup", 2.1),
        ("chunk-b", 2.0),
        ("chunk-c", 0.2),
    ]
    assert len(connection.calls) == 1

    statement, variables = connection.calls[0]
    assert statement == (
        "SELECT chunk_id, "
        "(search::score(0) * $title_boost) + "
        "(search::score(1) * $text_boost) AS score "
        "FROM chunks WITH INDEX chunks_title_fts, chunks_text_fts "
        "WHERE chunk_strategy = $chunk_strategy "
        "AND (title @0@ $query OR text @1@ $query) "
        "ORDER BY score DESC, chunk_id ASC LIMIT $limit TIMEOUT 5s;"
    )
    assert variables == {
        "query": "surreal retrieval quoted",
        "chunk_strategy": "contextual_512_50",
        "limit": 7,
        "title_boost": 5.0,
        "text_boost": 1.0,
    }


def test_search_filters_to_configured_chunk_strategy() -> None:
    connection = _FakeFTSConnection(combined_rows=[{"chunk_id": "chunk-active", "score": 5.0}])
    engine = _engine_class()(connection, chunk_strategy="heading_512_50")

    assert engine.search("surreal retrieval", top_k=3) == [("chunk-active", 5.0)]

    _statement, variables = connection.calls[0]
    assert variables is not None
    assert variables["chunk_strategy"] == "heading_512_50"


def test_search_logs_and_returns_empty_on_surreal_errors(caplog: pytest.LogCaptureFixture) -> None:
    connection = _FakeFTSConnection(error=RuntimeError("surreal parse error"))
    engine = _engine_class()(connection)

    with caplog.at_level(logging.WARNING):
        results = engine.search("surreal retrieval", top_k=3)

    assert results == []
    assert len(connection.calls) == 1
    assert "query_len=17" in caplog.text
    assert "error_type=RuntimeError" in caplog.text


def test_embedded_surreal_fts_filters_to_chunk_strategy_and_returns_chunk_hits(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    with isolated_surreal_connection(tmp_path) as connection:
        apply_surreal_native_retrieval_schema(connection, embedding_dimension=3, hnsw_ef=40)
        connection.create(
            "chunks:title_tag",
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
            "chunks:body_only",
            {
                "schema_version": "42.1.0",
                "original_chunk_id": "chunk:body-only",
                "chunk_id": "chunk:body-only",
                "chunk_strategy": "heading_512_50",
                "document_ref": "doc:body-only",
                "ref": "filesystem:/tmp/body-only.md",
                "title": "General Notes",
                "tags_text": "",
                "text": "surreal retrieval appears only in the body text",
                "metadata": {},
            },
        )

        engine = _engine_class()(connection, chunk_strategy="contextual_512_50")
        results = engine.search("surreal retrieval", top_k=5)

    assert results
    assert any(chunk_id == "chunk:title-tag" for chunk_id, _score in results)
    assert all(chunk_id != "chunk:body-only" for chunk_id, _score in results)
    assert all(isinstance(score, float) for _chunk_id, score in results)
