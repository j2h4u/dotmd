"""Populate Surreal embedding shard tables from an existing embeddings table."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from surrealdb import SurrealError

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotmd.ingestion.migrate_surreal import iter_sqlite_embedding_rows_for_surreal
from dotmd.storage.surreal import SurrealConnection, SurrealStoreConfig
from dotmd.storage.surreal_schema import surreal_embedding_shard_tables


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _shard_index(row: dict[str, Any], shard_count: int) -> int:
    raw = "\x1f".join(
        str(row.get(key, ""))
        for key in ("chunk_strategy", "embedding_model", "chunk_id")
    )
    digest = hashlib.blake2b(raw.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % shard_count


def _copy_rows_to_shards(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    shard_tables = surreal_embedding_shard_tables(args.embedding_shard_count)
    counts = dict.fromkeys(shard_tables, 0)
    total = 0
    with SurrealConnection(
        SurrealStoreConfig(
            url=args.target_url,
            namespace=args.target_namespace,
            database=args.target_database,
        )
    ) as connection:
        if args.recreate_shards:
            for table in shard_tables:
                try:
                    connection.query(f"REMOVE TABLE {table};")
                except SurrealError as exc:
                    if "does not exist" not in str(exc):
                        raise
        for table in shard_tables:
            connection.query(f"DEFINE TABLE {table} SCHEMALESS;")

        pending: dict[str, list[dict[str, Any]]] = {table: [] for table in shard_tables}
        if args.source_sqlite is not None:
            row_iter = iter_sqlite_embedding_rows_for_surreal(
                args.source_sqlite,
                batch_size=args.batch_size,
            )
        else:
            row_iter = connection.scan_table("embeddings")
        for row in row_iter:
            if total == 0:
                print(
                    json.dumps(
                        {
                            "phase": "copy_start",
                            "source": "sqlite" if args.source_sqlite is not None else "target",
                            "elapsed_seconds": round(time.monotonic() - started, 3),
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
            shard = _shard_index(row, args.embedding_shard_count)
            table = shard_tables[shard]
            payload = dict(row)
            payload.pop("id", None)
            payload["id"] = (
                f"{table}:"
                f"{hashlib.blake2b(str(row.get('id') or row.get('chunk_id', '')).encode('utf-8'), digest_size=16).hexdigest()}"
            )
            pending[table].append(payload)
            total += 1
            if len(pending[table]) >= args.batch_size:
                connection.insert_rows(table, pending[table], batch_size=args.batch_size)
                counts[table] += len(pending[table])
                pending[table].clear()
            if total % args.progress_every == 0:
                print(
                    json.dumps(
                        {
                            "phase": "copy",
                            "copied": total,
                            "elapsed_seconds": round(time.monotonic() - started, 3),
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
        for table, batch in pending.items():
            if batch:
                connection.insert_rows(table, batch, batch_size=args.batch_size)
                counts[table] += len(batch)

        observed_counts: dict[str, int] = {}
        for table in shard_tables:
            count_rows = connection.query(f"SELECT count() AS count FROM {table} GROUP ALL;")
            observed_counts[table] = int(count_rows[0].get("count", 0)) if count_rows else 0

    return {
        "status": "verified" if sum(observed_counts.values()) == total else "blocked",
        "finished_at": _utc_now(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "source_table": "embeddings",
        "source_sqlite": str(args.source_sqlite) if args.source_sqlite is not None else None,
        "shard_tables": list(shard_tables),
        "copied_rows": total,
        "inserted_counts": counts,
        "observed_counts": observed_counts,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-url", required=True)
    parser.add_argument("--target-namespace", default="dotmd")
    parser.add_argument("--target-database", default="phase43_shadow")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--embedding-shard-count", type=int, default=3)
    parser.add_argument("--source-sqlite", type=Path)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--progress-every", type=int, default=5000)
    parser.add_argument("--recreate-shards", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.embedding_shard_count <= 1:
        raise ValueError("--embedding-shard-count must be greater than 1")
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be positive")
    if args.progress_every <= 0:
        raise ValueError("--progress-every must be positive")
    result = _copy_rows_to_shards(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(args.output_dir / "embedding-shard-results.json", result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if result["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
