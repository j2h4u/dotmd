from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from dotmd.storage.surreal import (
    SurrealConnection,
    SurrealRecordIdCodec,
    SurrealStoreConfig,
    SurrealVectorStore,
    SurrealVectorStoreConfig,
)

pytestmark = pytest.mark.real_schema_check


def test_config_from_env_reads_aliases_and_defaults(monkeypatch) -> None:
    monkeypatch.delenv("SURREAL_URL", raising=False)
    monkeypatch.setenv("SURREALDB_URL", "ws://surrealdb:8000/rpc")
    monkeypatch.delenv("SURREAL_USER", raising=False)
    monkeypatch.setenv("SURREALDB_USER", "root")
    monkeypatch.delenv("SURREAL_PASS", raising=False)
    monkeypatch.setenv("SURREALDB_PASS", "secret")

    config = SurrealStoreConfig.from_env()

    assert config.url == "ws://surrealdb:8000/rpc"
    assert config.namespace == "dotmd"
    assert config.database == "phase43"
    assert config.username == "root"
    assert config.password == "secret"


def test_config_from_env_uses_string_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SURREAL_URL", "SURREALDB_URL", "SURREAL_USER", "SURREALDB_USER"):
        monkeypatch.delenv(name, raising=False)
    for name in ("SURREAL_PASS", "SURREALDB_PASS"):
        monkeypatch.delenv(name, raising=False)

    config = SurrealStoreConfig.from_env()

    assert config.url == "ws://127.0.0.1:8000/rpc"
    assert isinstance(config.url, str)
    assert config.namespace == "dotmd"
    assert config.database == "phase43"
    assert config.username is None
    assert config.password is None


def test_record_id_codec_uses_surreal_safe_base32() -> None:
    codec = SurrealRecordIdCodec()

    record_id = codec.record_id("documents", "a/b+c? d")
    table, decoded = codec.parse_record_id(record_id)

    assert table == "documents"
    assert decoded == "a/b+c? d"
    assert record_id.startswith("documents:")
    encoded = record_id.split(":", 1)[1]
    assert "/" not in encoded
    assert "+" not in encoded
    assert "=" not in encoded
    assert "-" not in encoded
    assert "_" not in encoded


@dataclass
class FakeSurreal:
    url: str
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = field(
        init=False, default_factory=list
    )

    def signin(self, credentials: dict[str, str]) -> None:
        self.calls.append(("signin", (credentials,), {}))

    def use(self, namespace: str, database: str) -> None:
        self.calls.append(("use", (namespace, database), {}))

    def query(self, statement: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append(("query", (statement, variables), {}))
        return {"kind": "query", "statement": statement, "variables": variables}

    def query_raw(
        self, statement: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.calls.append(("query_raw", (statement, variables), {}))
        return {"kind": "query_raw", "statement": statement, "variables": variables}

    def select(self, record: Any) -> dict[str, Any]:
        self.calls.append(("select", (record,), {}))
        return {"kind": "select", "record": record}

    def create(self, target: Any, data: Any = None) -> dict[str, Any]:
        self.calls.append(("create", (target, data), {}))
        return {"kind": "create", "target": target, "data": data}

    def delete(self, target: Any) -> dict[str, Any]:
        self.calls.append(("delete", (target,), {}))
        return {"kind": "delete", "target": target}

    def upsert(self, target: Any, data: Any = None) -> dict[str, Any]:
        self.calls.append(("upsert", (target, data), {}))
        return {"kind": "upsert", "target": target, "data": data}

    def insert(self, table: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls.append(("insert", (table, rows), {}))
        return {"kind": "insert", "table": table, "rows": rows}

    def close(self) -> None:
        self.calls.append(("close", (), {}))
        raise NotImplementedError


def test_connection_delegates_and_suppresses_close_error() -> None:
    config = SurrealStoreConfig(
        url="ws://example.invalid/rpc",
        namespace="dotmd",
        database="phase43",
        username="root",
        password="secret",
    )

    connection = SurrealConnection(config, connection_factory=FakeSurreal)

    assert connection.query("SELECT 1")["kind"] == "query"
    assert connection.query_raw("SELECT 2")["kind"] == "query_raw"
    assert connection.select("documents:abc")["kind"] == "select"
    assert connection.create("documents", {"title": "doc"})["kind"] == "create"
    assert connection.delete("documents:abc")["kind"] == "delete"
    assert connection.upsert("documents:abc", {"title": "doc"})["kind"] == "upsert"
    assert connection.insert_rows("documents", [{"title": "doc"}])["kind"] == "insert"

    connection.close()

    assert connection.client.calls == [
        ("signin", ({"username": "root", "password": "secret"},), {}),
        ("use", ("dotmd", "phase43"), {}),
        ("query", ("SELECT 1", None), {}),
        ("query_raw", ("SELECT 2", None), {}),
        ("select", ("documents:abc",), {}),
        ("create", ("documents", {"title": "doc"}), {}),
        ("delete", ("documents:abc",), {}),
        ("upsert", ("documents:abc", {"title": "doc"}), {}),
        ("insert", ("documents", [{"title": "doc"}]), {}),
        ("close", (), {}),
    ]


@dataclass
class FakeSurrealVectorConnection:
    config: SurrealStoreConfig
    calls: list[tuple[str, dict[str, Any] | None]] = field(default_factory=list)
    closed: bool = False

    def query(self, statement: str, variables: dict[str, Any] | None = None) -> Any:
        self.calls.append((statement, variables))
        if "count()" in statement:
            return [{"count": 149834}]
        assert "FROM embeddings WITH INDEX embeddings_vector_hnsw" in statement
        assert "WHERE vector <|3,80|> $query_vector TIMEOUT 30s" in statement
        assert variables == {"query_vector": [0.1, 0.2]}
        return [
            {"chunk_id": "chunk-a", "distance": 0.0},
            {"chunk_id": "chunk-b", "distance": 0.25},
            {"chunk_id": "chunk-c", "distance": "bad"},
        ]

    def close(self) -> None:
        self.closed = True


def test_surreal_vector_store_search_uses_forced_index_and_scores() -> None:
    holder: dict[str, FakeSurrealVectorConnection] = {}

    def factory(config: SurrealStoreConfig) -> FakeSurrealVectorConnection:
        connection = FakeSurrealVectorConnection(config)
        holder["connection"] = connection
        return connection

    store = SurrealVectorStore(
        SurrealStoreConfig(url="ws://example.invalid/rpc"),
        SurrealVectorStoreConfig(index_name="embeddings_vector_hnsw"),
        connection_factory=factory,
    )

    assert store.search([0.1, 0.2], top_k=3) == [
        ("chunk-a", 1.0),
        ("chunk-b", 0.75),
    ]
    assert holder["connection"].closed is True


def test_surreal_vector_store_count() -> None:
    store = SurrealVectorStore(
        SurrealStoreConfig(url="ws://example.invalid/rpc"),
        connection_factory=FakeSurrealVectorConnection,
    )

    assert store.count() == 149834


def test_surreal_vector_store_rejects_invalid_config() -> None:
    with pytest.raises(ValueError, match="invalid SurrealDB index name"):
        SurrealVectorStoreConfig(index_name="bad-index")


def test_surreal_vector_store_is_read_only() -> None:
    store = SurrealVectorStore(SurrealStoreConfig(url="ws://example.invalid/rpc"))

    with pytest.raises(NotImplementedError, match="read-only"):
        store.add_chunks([], [])
    with pytest.raises(NotImplementedError, match="read-only"):
        store.delete_all()
    with pytest.raises(NotImplementedError, match="read-only"):
        store.delete_vectors_by_chunk_ids(["chunk-a"])
