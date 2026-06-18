"""Timed SurrealDB vector KNN gate for the standalone migration."""

from __future__ import annotations

import argparse
import json
import re
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
except ModuleNotFoundError:  # pragma: no cover - import-time path fallback
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from dotmd.storage.surreal import SurrealConnection, SurrealStoreConfig


class SurrealKnnConnection(Protocol):
    def query(self, statement: str, variables: dict[str, Any] | None = None) -> Any: ...

    def close(self) -> Any: ...


@dataclass(frozen=True, slots=True)
class KnnGateConfig:
    k: int = 5
    ef: int = 80
    db_timeout_seconds: int = 30
    max_seconds: float = 5.0
    explain: bool = False
    index_name: str | None = None


@dataclass(frozen=True, slots=True)
class KnnGateResult:
    sample_seconds: float
    knn_seconds: float
    row_count: int
    passed: bool


def _default_connection_factory(config: SurrealStoreConfig) -> SurrealKnnConnection:
    return SurrealConnection(config)


def _close_quietly(connection: SurrealKnnConnection) -> None:
    try:
        connection.close()
    except NotImplementedError:
        return


def _emit(printer: Callable[..., None], message: str) -> None:
    printer(message, flush=True)


def _knn_statement(config: KnnGateConfig) -> str:
    if config.index_name and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", config.index_name):
        raise ValueError(f"invalid index name: {config.index_name}")
    index_clause = f" WITH INDEX {config.index_name}" if config.index_name else ""
    statement = (
        f"SELECT id, chunk_id FROM embeddings{index_clause} "
        f"WHERE vector <|{config.k},{config.ef}|> $query_vector "
        f"TIMEOUT {config.db_timeout_seconds}s"
    )
    if config.explain:
        statement += " EXPLAIN FULL"
    return statement + ";"


def _result_row_count(result: Any) -> int:
    if isinstance(result, list):
        return len(result)
    if isinstance(result, dict) and isinstance(result.get("total_rows"), int):
        return result["total_rows"]
    return 0


def run_gate(
    store_config: SurrealStoreConfig,
    gate_config: KnnGateConfig,
    *,
    connection_factory: Callable[[SurrealStoreConfig], SurrealKnnConnection] = _default_connection_factory,
    printer: Callable[..., None] = print,
    clock: Callable[[], float] = time.monotonic,
) -> KnnGateResult:
    _emit(
        printer,
        (
            "surreal knn gate: connecting "
            f"url={store_config.url} namespace={store_config.namespace} "
            f"database={store_config.database}"
        ),
    )
    _emit(
        printer,
        (
            "surreal knn gate: config "
            f"k={gate_config.k} ef={gate_config.ef} "
            f"db_timeout={gate_config.db_timeout_seconds}s "
            f"max_seconds={gate_config.max_seconds:.3f} explain={gate_config.explain} "
            f"index_name={gate_config.index_name or 'auto'}"
        ),
    )
    connection = connection_factory(store_config)
    try:
        sample_started = clock()
        rows = connection.query("SELECT id, vector FROM embeddings LIMIT 1;")
        sample_seconds = clock() - sample_started
        _emit(
            printer,
            f"surreal knn gate: sample rows={len(rows)} elapsed={sample_seconds:.3f}s",
        )
        if not rows:
            raise RuntimeError("embeddings table is empty")
        vector = rows[0].get("vector")
        if not isinstance(vector, list):
            raise RuntimeError("sample embedding row did not contain a vector list")
        _emit(printer, f"surreal knn gate: vector_dim={len(vector)}")

        knn_started = clock()
        result = connection.query(_knn_statement(gate_config), {"query_vector": vector})
        knn_seconds = clock() - knn_started
        row_count = _result_row_count(result)
        passed = knn_seconds <= gate_config.max_seconds and row_count > 0
        if gate_config.explain:
            _emit(
                printer,
                "surreal knn gate: explain "
                + json.dumps(result, ensure_ascii=False, default=str),
            )
        _emit(
            printer,
            (
                "surreal knn gate: "
                f"knn rows={row_count} elapsed={knn_seconds:.3f}s "
                f"status={'pass' if passed else 'fail'}"
            ),
        )
        return KnnGateResult(
            sample_seconds=sample_seconds,
            knn_seconds=knn_seconds,
            row_count=row_count,
            passed=passed,
        )
    finally:
        _close_quietly(connection)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--ef", type=int, default=80)
    parser.add_argument("--db-timeout-seconds", type=int, default=30)
    parser.add_argument("--max-seconds", type=float, default=5.0)
    parser.add_argument("--explain", action="store_true")
    parser.add_argument("--index-name")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_gate(
        SurrealStoreConfig.from_env(),
        KnnGateConfig(
            k=args.k,
            ef=args.ef,
            db_timeout_seconds=args.db_timeout_seconds,
            max_seconds=args.max_seconds,
            explain=args.explain,
            index_name=args.index_name,
        ),
    )
    return 0 if result.passed else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
