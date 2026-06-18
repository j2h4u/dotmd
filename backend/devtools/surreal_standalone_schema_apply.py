"""Apply the minimal standalone SurrealDB schema for dotMD."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from dotmd.storage.surreal import SurrealConnection, SurrealStoreConfig
    from dotmd.storage.surreal_schema import (
        SurrealSchemaPlan,
        build_minimal_monolithic_schema_plan,
    )
except ModuleNotFoundError:  # pragma: no cover - import-time path fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from dotmd.storage.surreal import SurrealConnection, SurrealStoreConfig
    from dotmd.storage.surreal_schema import (
        SurrealSchemaPlan,
        build_minimal_monolithic_schema_plan,
    )


class SurrealSchemaConnection(Protocol):
    def query(self, statement: str, variables: dict[str, Any] | None = None) -> Any: ...

    def close(self) -> Any: ...


@dataclass(frozen=True, slots=True)
class SchemaApplyConfig:
    embedding_dimension: int = 1024
    vector_index: str = "hnsw"


@dataclass(frozen=True, slots=True)
class SchemaApplyResult:
    url: str
    namespace: str
    database: str
    embedding_dimension: int
    vector_index: str
    statement_count: int
    elapsed_seconds: float


def load_config(args: argparse.Namespace) -> tuple[SurrealStoreConfig, SchemaApplyConfig]:
    store_config = SurrealStoreConfig.from_env()
    return (
        store_config,
        SchemaApplyConfig(
            embedding_dimension=args.embedding_dimension,
            vector_index=args.vector_index,
        ),
    )


def _default_connection_factory(config: SurrealStoreConfig) -> SurrealSchemaConnection:
    return SurrealConnection(config)


def _close_quietly(connection: SurrealSchemaConnection) -> None:
    try:
        connection.close()
    except NotImplementedError:
        return


def _emit(printer: Callable[..., None], message: str) -> None:
    printer(message, flush=True)


def run_apply(
    store_config: SurrealStoreConfig,
    schema_config: SchemaApplyConfig,
    *,
    plan_builder: Callable[[int], SurrealSchemaPlan] = build_minimal_monolithic_schema_plan,
    connection_factory: Callable[[SurrealStoreConfig], SurrealSchemaConnection] = _default_connection_factory,
    printer: Callable[..., None] = print,
    clock: Callable[[], float] = time.monotonic,
) -> SchemaApplyResult:
    started = clock()
    _emit(
        printer,
        (
            "surreal standalone schema apply: connecting "
            f"url={store_config.url} namespace={store_config.namespace} "
            f"database={store_config.database}"
        ),
    )
    _emit(
        printer,
        (
            "surreal standalone schema apply: building plan "
            f"embedding_dimension={schema_config.embedding_dimension} "
            f"vector_index={schema_config.vector_index}"
        ),
    )
    plan = plan_builder(schema_config.embedding_dimension)
    statements = tuple(plan.statements(vector_index=schema_config.vector_index))

    connection: SurrealSchemaConnection | None = None
    try:
        connection = connection_factory(store_config)
        _emit(
            printer,
            (
                "surreal standalone schema apply: applying "
                f"{len(statements)} statements"
            ),
        )
        for index, statement in enumerate(statements, start=1):
            step_started = clock()
            _emit(printer, f"[{index}/{len(statements)}] applying: {statement}")
            connection.query(statement)
            elapsed = clock() - step_started
            _emit(printer, f"[{index}/{len(statements)}] done in {elapsed:.3f}s")
    finally:
        if connection is not None:
            _close_quietly(connection)
    return SchemaApplyResult(
        url=store_config.url,
        namespace=store_config.namespace,
        database=store_config.database,
        embedding_dimension=schema_config.embedding_dimension,
        vector_index=schema_config.vector_index,
        statement_count=len(statements),
        elapsed_seconds=round(clock() - started, 3),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--embedding-dimension",
        type=int,
        default=1024,
        help="vector dimension used when building the schema plan",
    )
    parser.add_argument(
        "--vector-index",
        choices=("hnsw", "diskann", "none"),
        default="hnsw",
        help="which vector index statements to apply",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        store_config, schema_config = load_config(args)
        result = run_apply(store_config, schema_config)
    except Exception as exc:
        print(
            f"surreal standalone schema apply failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    print(
        "surreal standalone schema apply ok: "
        f"url={result.url} ns={result.namespace} db={result.database} "
        f"dimension={result.embedding_dimension} vector_index={result.vector_index} "
        f"statements={result.statement_count} elapsed={result.elapsed_seconds:.3f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
