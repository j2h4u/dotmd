"""Minimal standalone SurrealDB connection foundation.

This module intentionally keeps the surface small:

- configuration comes from environment variables or explicit values;
- the connection wrapper delegates directly to the SurrealDB Python SDK;
- record identifiers are encoded with URL-safe base64 for Surreal-friendly IDs;
- no embedded SurrealKV or sharding helpers are introduced here.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

DEFAULT_SURREAL_URL = "ws://127.0.0.1:8000/rpc"
DEFAULT_SURREAL_NAMESPACE = "dotmd"
DEFAULT_SURREAL_DATABASE = "phase43"


def _env_first(source: Mapping[str, str], *names: str, default: str = "") -> str:
    for name in names:
        value = source.get(name)
        if value:
            return value
    return default


@dataclass(frozen=True, slots=True)
class SurrealStoreConfig:
    """Connection settings for a standalone SurrealDB deployment."""

    url: str = DEFAULT_SURREAL_URL
    namespace: str = DEFAULT_SURREAL_NAMESPACE
    database: str = DEFAULT_SURREAL_DATABASE
    username: str | None = None
    password: str | None = None

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> SurrealStoreConfig:
        source = os.environ if environ is None else environ
        return cls(
            url=_env_first(source, "SURREAL_URL", "SURREALDB_URL", default=DEFAULT_SURREAL_URL),
            namespace=DEFAULT_SURREAL_NAMESPACE,
            database=DEFAULT_SURREAL_DATABASE,
            username=_env_first(source, "SURREAL_USER", "SURREALDB_USER", default="") or None,
            password=_env_first(source, "SURREAL_PASS", "SURREALDB_PASS", default="") or None,
        )


class SurrealRecordIdCodec:
    """Encode and decode record IDs with URL-safe base64."""

    @staticmethod
    def encode(value: str | bytes) -> str:
        data = value.encode("utf-8") if isinstance(value, str) else value
        return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

    @staticmethod
    def decode(value: str) -> str:
        padded = value + "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(padded).decode("utf-8")

    def record_id(self, table: str, value: str | bytes) -> str:
        return f"{table}:{self.encode(value)}"

    def parse_record_id(self, record_id: str) -> tuple[str, str]:
        table, encoded = record_id.split(":", 1)
        return table, self.decode(encoded)


def _load_surreal_factory() -> Callable[[str], Any]:
    try:
        from surrealdb import Surreal
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError(
            "install the surrealdb package before constructing a SurrealConnection"
        ) from exc
    return Surreal


@dataclass(slots=True)
class SurrealConnection:
    """Thin wrapper around ``surrealdb.Surreal``.

    The Python SDK's blocking connection is instantiated directly from the URL,
    so this wrapper does not call ``connect()``.
    """

    config: SurrealStoreConfig
    connection_factory: Callable[[str], Any] | None = None
    client: Any = field(init=False)

    def __post_init__(self) -> None:
        factory = self.connection_factory or _load_surreal_factory()
        self.client = factory(self.config.url)
        if self.config.username and self.config.password:
            self.client.signin(
                {"username": self.config.username, "password": self.config.password}
            )
        self.client.use(self.config.namespace, self.config.database)

    def query(self, statement: str, variables: dict[str, Any] | None = None) -> Any:
        return self.client.query(statement, variables)

    def query_raw(self, statement: str, variables: dict[str, Any] | None = None) -> Any:
        return self.client.query_raw(statement, variables)

    def select(self, record: Any) -> Any:
        return self.client.select(record)

    def create(self, target: Any, data: Any = None) -> Any:
        return self.client.create(target, data)

    def delete(self, target: Any) -> Any:
        return self.client.delete(target)

    def upsert(self, target: Any, data: Any = None) -> Any:
        return self.client.upsert(target, data)

    def insert_rows(self, table: str, rows: Sequence[Mapping[str, Any]]) -> Any:
        inserter = getattr(self.client, "insert_rows", None)
        if inserter is not None:
            return inserter(table, rows)
        return self.client.insert(table, rows)

    def close(self) -> None:
        try:
            self.client.close()
        except NotImplementedError:
            return
