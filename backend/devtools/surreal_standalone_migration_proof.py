"""Load a small exported SQLite subset into standalone SurrealDB."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from surrealdb import RecordID

from dotmd.storage.surreal import SurrealConnection, SurrealRecordIdCodec, SurrealStoreConfig


@dataclass(frozen=True, slots=True)
class MigrationProofConfig:
    input_jsonl: Path
    batch_size: int = 50


@dataclass(frozen=True, slots=True)
class MigrationProofResult:
    total_records: int
    counts: dict[str, int]
    elapsed_seconds: float


def format_eta(seconds: float) -> str:
    remaining = max(0, round(seconds))
    if remaining < 60:
        return f"{remaining}s"
    minutes, secs = divmod(remaining, 60)
    if minutes > 5:
        return f"{round(remaining / 60)}m"
    if secs == 0:
        return f"{minutes}m"
    return f"{minutes}m {secs}s"


def _count_lines(path: Path) -> int:
    with path.open("rb") as fh:
        return sum(1 for _ in fh)


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at line {line_number}: {exc}") from exc
            if not isinstance(payload, dict) or "type" not in payload or "data" not in payload:
                raise ValueError(f"invalid migration record at line {line_number}")
            yield payload


def _key(*parts: object) -> str:
    return "\0".join("" if part is None else str(part) for part in parts)


def _record_id(codec: SurrealRecordIdCodec, table: str, *parts: object) -> str:
    return codec.record_id(table, _key(*parts))


def _record_ref(codec: SurrealRecordIdCodec, table: str, *parts: object) -> RecordID:
    return RecordID(table, codec.encode(_key(*parts)))


def _target_and_data(
    record: dict[str, Any],
    codec: SurrealRecordIdCodec,
) -> tuple[str, dict[str, Any]]:
    record_type = str(record["type"])
    data = dict(record["data"])
    if record_type == "document":
        target = _record_id(codec, "documents", data["namespace"], data["document_ref"])
        return target, data
    if record_type == "source_unit":
        target = _record_id(
            codec,
            "source_units",
            data["namespace"],
            data["document_ref"],
            data["unit_ref"],
        )
        data["document"] = _record_ref(codec, "documents", data["namespace"], data["document_ref"])
        return target, data
    if record_type == "source_unit_fingerprint":
        target = _record_id(
            codec,
            "source_unit_fingerprints",
            data["namespace"],
            data["document_ref"],
            data["unit_ref"],
        )
        data["document"] = _record_ref(codec, "documents", data["namespace"], data["document_ref"])
        return target, data
    if record_type == "chunk":
        target = _record_id(codec, "chunks", data["chunk_strategy"], data["chunk_id"])
        if data.get("metadata", {}).get("namespace") and data.get("document_ref"):
            data["document"] = _record_ref(
                codec,
                "documents",
                data["metadata"]["namespace"],
                data["document_ref"],
            )
        return target, data
    if record_type == "chunk_file_binding":
        target = _record_id(
            codec,
            "chunk_file_bindings",
            data["chunk_strategy"],
            data["chunk_id"],
            data["file_path"],
            data["chunk_index"],
        )
        data["chunk"] = _record_ref(codec, "chunks", data["chunk_strategy"], data["chunk_id"])
        return target, data
    if record_type == "chunk_source_provenance":
        target = _record_id(
            codec,
            "chunk_source_provenance",
            data["chunk_strategy"],
            data["chunk_id"],
            data["namespace"],
            data["document_ref"],
        )
        data["chunk"] = _record_ref(codec, "chunks", data["chunk_strategy"], data["chunk_id"])
        data["document"] = _record_ref(codec, "documents", data["namespace"], data["document_ref"])
        return target, data
    if record_type == "embedding":
        target = _record_id(
            codec,
            "embeddings",
            data["chunk_strategy"],
            data["embedding_model"],
            data["chunk_id"],
        )
        data["chunk"] = _record_ref(codec, "chunks", data["chunk_strategy"], data["chunk_id"])
        return target, data
    raise ValueError(f"unsupported migration record type: {record_type}")


def _emit(printer: Callable[..., None], message: str) -> None:
    printer(message, flush=True)


def batch_upsert(connection: SurrealConnection, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    connection.query(
        "FOR $row IN $rows { UPSERT type::record($row.id) CONTENT $row.data; };",
        {"rows": rows},
    )


def run_migration_proof(
    store_config: SurrealStoreConfig,
    proof_config: MigrationProofConfig,
    *,
    connection_factory: Callable[[SurrealStoreConfig], SurrealConnection] = SurrealConnection,
    printer: Callable[..., None] = print,
    clock: Callable[[], float] = time.monotonic,
) -> MigrationProofResult:
    total = _count_lines(proof_config.input_jsonl)
    started = clock()
    counts: dict[str, int] = {}
    codec = SurrealRecordIdCodec()
    _emit(
        printer,
        (
            "surreal migration proof: starting "
            f"records={total} batch_size={proof_config.batch_size} "
            f"url={store_config.url} namespace={store_config.namespace} "
            f"database={store_config.database}"
        ),
    )
    connection = connection_factory(store_config)
    processed = 0
    try:
        pending: list[dict[str, Any]] = []
        for record in _iter_jsonl(proof_config.input_jsonl):
            target, data = _target_and_data(record, codec)
            pending.append({"id": target, "data": data})
            processed += 1
            record_type = str(record["type"])
            counts[record_type] = counts.get(record_type, 0) + 1
            if processed % proof_config.batch_size == 0 or processed == total:
                batch_upsert(connection, pending)
                pending = []
                elapsed = max(clock() - started, 0.001)
                rate = processed / elapsed
                remaining = (total - processed) / rate if rate > 0 else 0
                percent = (processed / total * 100) if total else 100.0
                _emit(
                    printer,
                    (
                        "surreal migration proof: "
                        f"{processed}/{total} ({percent:.1f}%) "
                        f"rate={rate:.1f} records/s ETA {format_eta(remaining)}"
                    ),
                )
    finally:
        connection.close()
    return MigrationProofResult(
        total_records=processed,
        counts=counts,
        elapsed_seconds=round(clock() - started, 3),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=50)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_migration_proof(
            SurrealStoreConfig.from_env(),
            MigrationProofConfig(input_jsonl=args.input_jsonl, batch_size=args.batch_size),
        )
    except Exception as exc:
        print(f"surreal migration proof failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(
        "surreal migration proof ok: "
        f"records={result.total_records} counts={json.dumps(result.counts, sort_keys=True)} "
        f"elapsed={result.elapsed_seconds:.3f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
