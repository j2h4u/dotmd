"""Minimal standalone SurrealDB connection foundation.

This module intentionally keeps the surface small:

- configuration comes from environment variables or explicit values;
- the connection wrapper delegates directly to the SurrealDB Python SDK;
- record identifiers are encoded with base32 for Surreal-friendly IDs;
- no embedded SurrealKV or sharding helpers are introduced here.
"""

from __future__ import annotations

import base64
import logging
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from dotmd.core.models import Chunk

DEFAULT_SURREAL_URL = "ws://127.0.0.1:8000/rpc"
DEFAULT_SURREAL_NAMESPACE = "dotmd"
DEFAULT_SURREAL_DATABASE = "phase43"

logger = logging.getLogger(__name__)


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
    """Encode and decode record IDs with Surreal-safe base32."""

    @staticmethod
    def encode(value: str | bytes) -> str:
        data = value.encode("utf-8") if isinstance(value, str) else value
        return base64.b32encode(data).decode("ascii").rstrip("=")

    @staticmethod
    def decode(value: str) -> str:
        padded = value + "=" * (-len(value) % 8)
        return base64.b32decode(padded).decode("utf-8")

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


@dataclass(frozen=True, slots=True)
class SurrealVectorStoreConfig:
    """Read-side vector search settings for migrated SurrealDB embeddings."""

    index_name: str = "embeddings_vector_hnsw"
    k_ef: int = 80
    query_timeout_seconds: int = 30

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.index_name):
            raise ValueError(f"invalid SurrealDB index name: {self.index_name}")
        if self.k_ef <= 0:
            raise ValueError("k_ef must be positive")
        if self.query_timeout_seconds <= 0:
            raise ValueError("query_timeout_seconds must be positive")


class SurrealVectorStore:
    """Read-only vector store backed by migrated standalone SurrealDB embeddings."""

    def __init__(
        self,
        store_config: SurrealStoreConfig | None = None,
        vector_config: SurrealVectorStoreConfig | None = None,
        *,
        connection_factory: Callable[[SurrealStoreConfig], SurrealConnection] = SurrealConnection,
    ) -> None:
        self._store_config = store_config or SurrealStoreConfig.from_env()
        self._vector_config = vector_config or SurrealVectorStoreConfig()
        self._connection_factory = connection_factory

    def add_chunks(
        self,
        chunks: list[Chunk],
        embeddings: list[list[float]],
        *,
        overwrite: bool = True,
        text_hashes: dict[str, str] | None = None,
    ) -> None:
        raise NotImplementedError("SurrealVectorStore is read-only during standalone cutover")

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
    ) -> list[tuple[str, float]]:
        if not query_embedding or top_k <= 0:
            return []
        query = (
            "SELECT chunk_id, vector::distance::knn() AS distance "
            f"FROM embeddings WITH INDEX {self._vector_config.index_name} "
            f"WHERE vector <|{top_k},{self._vector_config.k_ef}|> $query_vector "
            f"TIMEOUT {self._vector_config.query_timeout_seconds}s;"
        )
        connection = self._connection_factory(self._store_config)
        try:
            rows = connection.query(query, {"query_vector": query_embedding})
        except (RuntimeError, ValueError, TypeError):
            logger.warning("Surreal vector search query failed", exc_info=True)
            return []
        finally:
            connection.close()

        results: list[tuple[str, float]] = []
        for row in rows if isinstance(rows, list) else []:
            chunk_id = row.get("chunk_id")
            distance = row.get("distance")
            if not isinstance(chunk_id, str) or not isinstance(distance, int | float):
                continue
            results.append((chunk_id, 1.0 - float(distance)))
        return results

    def delete_all(self) -> None:
        raise NotImplementedError("SurrealVectorStore is read-only during standalone cutover")

    def delete_vectors_by_chunk_ids(self, chunk_ids: list[str]) -> int:
        raise NotImplementedError("SurrealVectorStore is read-only during standalone cutover")

    def count(self) -> int:
        connection = self._connection_factory(self._store_config)
        try:
            rows = connection.query("SELECT count() FROM embeddings GROUP ALL;")
        except (RuntimeError, ValueError, TypeError):
            logger.warning("Surreal vector count query failed", exc_info=True)
            return 0
        finally:
            connection.close()
        if not isinstance(rows, list) or not rows:
            return 0
        count = rows[0].get("count")
        return int(count) if isinstance(count, int | float) else 0
