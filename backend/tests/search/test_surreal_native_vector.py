from __future__ import annotations

import logging

import pytest
from tests.fixtures.surreal_native import (
    apply_surreal_native_retrieval_schema,
    isolated_surreal_connection,
)


@pytest.fixture(autouse=True)
def _propagate_dotmd_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(logging.getLogger("dotmd"), "propagate", True)


def _engine_class():
    from dotmd.search.surreal_vector import SurrealVectorSearchEngine

    return SurrealVectorSearchEngine


class _FakeVectorConnection:
    def __init__(
        self,
        *,
        precondition_rows: list[dict[str, object]] | None = None,
        search_rows: list[dict[str, object]] | None = None,
        search_error: Exception | None = None,
    ) -> None:
        self.precondition_rows = precondition_rows or [
            {"embedding_model": "phase42-model", "embedding_dimension": 3}
        ]
        self.search_rows = search_rows or []
        self.search_error = search_error
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def query(
        self,
        statement: str,
        variables: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        self.calls.append((statement, variables))
        if "array::len(embedding)" in statement:
            return list(self.precondition_rows)
        if self.search_error is not None:
            raise self.search_error
        return list(self.search_rows)

    def scan_table(self, table_name: str) -> list[dict[str, object]]:
        raise AssertionError(f"scan_table() must not be used in vector retrieval: {table_name}")


@pytest.mark.parametrize(
    ("query_instruction", "use_prefix", "expected"),
    [
        ("Use this instruction", True, "Use this instruction\nQuery: surreal retrieval"),
        ("", True, "query: surreal retrieval"),
        ("", False, "surreal retrieval"),
    ],
)
def test_search_normalizes_queries_like_semantic_engine(
    monkeypatch: pytest.MonkeyPatch,
    query_instruction: str,
    use_prefix: bool,
    expected: str,
) -> None:
    connection = _FakeVectorConnection()
    engine = _engine_class()(
        connection,
        model_name="phase42-model",
        embedding_dimension=3,
        query_instruction=query_instruction,
        use_prefix=use_prefix,
    )
    captured: list[str] = []

    def _fake_encode(text: str) -> list[float]:
        captured.append(text)
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr(engine, "encode", _fake_encode)

    engine.search("surreal retrieval", top_k=2)

    assert captured == [expected]


def test_search_uses_hnsw_knn_query_with_model_filter_and_cosine_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _FakeVectorConnection(
        search_rows=[
            {"chunk_id": "chunk-alpha", "score": 0.99},
            {"chunk_id": "chunk-beta", "score": 0.75},
        ]
    )
    engine = _engine_class()(
        connection,
        model_name="phase42-model",
        embedding_dimension=3,
    )
    monkeypatch.setattr(engine, "encode", lambda text: [1.0, 0.0, 0.0])

    results = engine.search("surreal retrieval", top_k=5)

    assert results == [("chunk-alpha", 0.99), ("chunk-beta", 0.75)]
    assert len(connection.calls) == 2

    statement, variables = connection.calls[-1]
    assert "SELECT chunk_id" in statement
    assert "vector::similarity::cosine(embedding, $qvec) AS score" in statement
    assert "embedding_model = $embedding_model" in statement
    assert "embedding <|5,40|> $qvec" in statement
    assert "ORDER BY score DESC, chunk_id ASC" in statement
    assert variables == {
        "embedding_model": "phase42-model",
        "qvec": [1.0, 0.0, 0.0],
        "limit": 5,
    }


@pytest.mark.parametrize("top_k", [0, 101])
def test_search_rejects_top_k_outside_phase42_bounds_before_query(
    top_k: int,
) -> None:
    connection = _FakeVectorConnection()
    engine = _engine_class()(connection, model_name="phase42-model", embedding_dimension=3)

    with pytest.raises(ValueError, match="top_k"):
        engine.search("surreal retrieval", top_k=top_k)

    assert connection.calls == []


@pytest.mark.parametrize("hnsw_ef", [9, 401])
def test_search_rejects_hnsw_ef_outside_phase42_bounds_before_query(hnsw_ef: int) -> None:
    connection = _FakeVectorConnection()
    engine = _engine_class()(
        connection,
        model_name="phase42-model",
        embedding_dimension=3,
        hnsw_ef=hnsw_ef,
    )

    with pytest.raises(ValueError, match="hnsw_ef"):
        engine.search("surreal retrieval", top_k=5)

    assert connection.calls == []


def test_search_rejects_hnsw_ef_smaller_than_top_k_before_query() -> None:
    connection = _FakeVectorConnection()
    engine = _engine_class()(
        connection,
        model_name="phase42-model",
        embedding_dimension=3,
        hnsw_ef=10,
    )

    with pytest.raises(ValueError, match="greater than or equal to top_k"):
        engine.search("surreal retrieval", top_k=11)

    assert connection.calls == []


def test_search_returns_empty_when_multiple_active_models_exist(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    connection = _FakeVectorConnection(
        precondition_rows=[
            {"embedding_model": "phase42-model", "embedding_dimension": 3},
            {"embedding_model": "other-model", "embedding_dimension": 3},
        ]
    )
    engine = _engine_class()(connection, model_name="phase42-model", embedding_dimension=3)
    monkeypatch.setattr(
        engine,
        "encode",
        lambda text: pytest.fail("encode() should not run when preconditions fail"),
    )

    with caplog.at_level(logging.WARNING):
        results = engine.search("surreal retrieval", top_k=5)

    assert results == []
    assert len(connection.calls) == 1
    assert "single active embedding_model" in caplog.text


def test_search_returns_empty_when_embedding_dimension_mismatches(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    connection = _FakeVectorConnection(
        precondition_rows=[{"embedding_model": "phase42-model", "embedding_dimension": 2}]
    )
    engine = _engine_class()(connection, model_name="phase42-model", embedding_dimension=3)
    monkeypatch.setattr(
        engine,
        "encode",
        lambda text: pytest.fail("encode() should not run when dimensions mismatch"),
    )

    with caplog.at_level(logging.WARNING):
        results = engine.search("surreal retrieval", top_k=5)

    assert results == []
    assert len(connection.calls) == 1
    assert "embedding_dimension mismatch" in caplog.text


def test_embedded_surreal_hnsw_returns_nearest_neighbor_without_scan_table(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # type: ignore[no-untyped-def]
    with isolated_surreal_connection(tmp_path) as connection:
        apply_surreal_native_retrieval_schema(connection, embedding_dimension=3, hnsw_ef=40)
        connection.create(
            "embeddings:alpha",
            {
                "schema_version": "42.1.0",
                "chunk_id": "chunk-alpha",
                "embedding_model": "phase42-model",
                "text_hash": "alpha",
                "vector_rowid": 1,
                "embedding": [1.0, 0.0, 0.0],
                "metadata": {},
            },
        )
        connection.create(
            "embeddings:beta",
            {
                "schema_version": "42.1.0",
                "chunk_id": "chunk-beta",
                "embedding_model": "phase42-model",
                "text_hash": "beta",
                "vector_rowid": 2,
                "embedding": [0.0, 1.0, 0.0],
                "metadata": {},
            },
        )

        engine = _engine_class()(connection, model_name="phase42-model", embedding_dimension=3)
        monkeypatch.setattr(engine, "encode", lambda text: [1.0, 0.0, 0.0])
        monkeypatch.setattr(
            connection,
            "scan_table",
            lambda table_name: pytest.fail(
                f"scan_table() must not be used in vector retrieval: {table_name}"
            ),
        )

        results = engine.search("nearest surreal result", top_k=2)

    assert [chunk_id for chunk_id, _score in results] == ["chunk-alpha", "chunk-beta"]
    assert results[0][1] >= results[1][1]


def test_search_applies_relative_score_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _FakeVectorConnection(
        search_rows=[
            {"chunk_id": "chunk-alpha", "score": 1.0},
            {"chunk_id": "chunk-beta", "score": 0.59},
            {"chunk_id": "chunk-gamma", "score": 0.60},
        ]
    )
    engine = _engine_class()(
        connection,
        model_name="phase42-model",
        embedding_dimension=3,
        score_floor=0.6,
    )
    monkeypatch.setattr(engine, "encode", lambda text: [1.0, 0.0, 0.0])

    results = engine.search("surreal retrieval", top_k=3)

    assert results == [("chunk-alpha", 1.0), ("chunk-gamma", 0.60)]


def test_search_propagates_encode_errors_like_semantic_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _FakeVectorConnection()
    engine = _engine_class()(connection, model_name="phase42-model", embedding_dimension=3)

    def _explode(_text: str) -> list[float]:
        raise RuntimeError("encode failed")

    monkeypatch.setattr(engine, "encode", _explode)

    with pytest.raises(RuntimeError, match="encode failed"):
        engine.search("surreal retrieval", top_k=2)

    assert len(connection.calls) == 1


def test_search_logs_and_returns_empty_on_surreal_query_errors(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    connection = _FakeVectorConnection(search_error=RuntimeError("query failed"))
    engine = _engine_class()(connection, model_name="phase42-model", embedding_dimension=3)
    monkeypatch.setattr(engine, "encode", lambda text: [1.0, 0.0, 0.0])

    with caplog.at_level(logging.WARNING):
        results = engine.search("surreal retrieval", top_k=2)

    assert results == []
    assert len(connection.calls) == 2
    assert "query_len=17" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
