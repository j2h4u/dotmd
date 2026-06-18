"""Smoke-check a standalone SurrealDB server for dotMD migration work."""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol


class SurrealLike(Protocol):
    def signin(self, credentials: dict[str, str]) -> Any: ...

    def use(self, namespace: str, database: str) -> Any: ...

    def version(self) -> Any: ...

    def query(self, statement: str, variables: dict[str, Any] | None = None) -> Any: ...

    def close(self) -> Any: ...


@dataclass(slots=True, frozen=True)
class SmokeConfig:
    url: str
    username: str
    password: str
    namespace: str
    database: str
    write_probe: bool


@dataclass(slots=True, frozen=True)
class SmokeResult:
    url: str
    namespace: str
    database: str
    server_version: str
    elapsed_seconds: float
    write_probe: bool


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return default


def load_config(args: argparse.Namespace) -> SmokeConfig:
    username = args.username or _env_first("SURREAL_USER", "SURREALDB_USER", default="root")
    password = args.password or _env_first("SURREAL_PASS", "SURREALDB_PASS")
    if not password:
        raise ValueError("password is required: pass --password or set SURREAL_PASS")
    return SmokeConfig(
        url=args.url
        or _env_first("SURREAL_URL", "SURREALDB_URL", default="ws://127.0.0.1:8000/rpc"),
        username=username,
        password=password,
        namespace=args.namespace,
        database=args.database,
        write_probe=args.write_probe,
    )


def _default_connection_factory(url: str) -> SurrealLike:
    try:
        from surrealdb import Surreal
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("install the surrealdb package before running this smoke check") from exc
    return Surreal(url)


def _close_quietly(connection: SurrealLike) -> None:
    try:
        connection.close()
    except NotImplementedError:
        # surrealdb 2.x HTTP connection does not implement close().
        return


def run_smoke(
    config: SmokeConfig,
    *,
    connection_factory: Callable[[str], SurrealLike] = _default_connection_factory,
) -> SmokeResult:
    started = time.monotonic()
    connection = connection_factory(config.url)
    try:
        connection.signin({"username": config.username, "password": config.password})
        connection.use(config.namespace, config.database)
        server_version = str(connection.version())
        connection.query("INFO FOR DB;")
        if config.write_probe:
            record_id = f"dotmd_smoke:{uuid.uuid4().hex}"
            connection.query(
                "CREATE type::record($record_id) CONTENT { created_by: 'dotmd smoke' };",
                {"record_id": record_id},
            )
            rows = connection.query(
                "SELECT created_by FROM type::record($record_id);",
                {"record_id": record_id},
            )
            if not rows:
                raise RuntimeError("write probe created no readable record")
            connection.query("DELETE type::record($record_id);", {"record_id": record_id})
    finally:
        _close_quietly(connection)
    return SmokeResult(
        url=config.url,
        namespace=config.namespace,
        database=config.database,
        server_version=server_version,
        elapsed_seconds=round(time.monotonic() - started, 3),
        write_probe=config.write_probe,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=None)
    parser.add_argument("--username", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--namespace", default="dotmd")
    parser.add_argument("--database", default="phase43")
    parser.add_argument("--write-probe", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run_smoke(load_config(args))
    except Exception as exc:
        print(f"surreal standalone smoke failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(
        "surreal standalone smoke ok: "
        f"url={result.url} ns={result.namespace} db={result.database} "
        f"version={result.server_version} write_probe={result.write_probe} "
        f"elapsed={result.elapsed_seconds:.3f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
