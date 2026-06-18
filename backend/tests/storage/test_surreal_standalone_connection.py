from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from dotmd.storage.surreal import (
    SurrealConnection,
    SurrealRecordIdCodec,
    SurrealStoreConfig,
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


def test_record_id_codec_uses_url_safe_base64() -> None:
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
