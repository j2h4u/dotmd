"""Targeted backfill for missing SurrealDB embeddings.

Run the production/default flow inside the dotMD container network, where
``DOTMD_EMBEDDING__URL=http://embeddings:80`` and
``DOTMD_SURREAL_RETRIEVAL__URL=http://surrealdb:8000`` are already valid.
Use host URL overrides only for local dev/debug runs.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import blake3

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotmd.core.config import Settings
from dotmd.ingestion.surreal_delta_sync import (
    SurrealDeltaChange,
    SurrealDeltaStoreWriter,
    _stable_vector_rowid,
)
from dotmd.search.semantic import EmbeddingEncoder
from dotmd.storage.surreal import SurrealConnection, SurrealRecordIdCodec, SurrealStoreConfig

_DEFAULT_CHUNK_STRATEGY = "heading_512_50"

_HELP_EPILOG = """Examples:

Production/default, inside the container network:
  docker exec dotmd sh -lc 'cd /mnt/home/repos/j2h4u/dotmd/backend && python3 devtools/surreal_embedding_backfill.py --chunk-id <chunk-id> --apply'
  docker compose exec dotmd sh -lc 'cd /mnt/home/repos/j2h4u/dotmd/backend && python3 devtools/surreal_embedding_backfill.py --chunk-id <chunk-id> --apply'

Dev/debug only, from the host:
  DOTMD_EMBEDDING__URL=http://127.0.0.1:8088 DOTMD_SURREAL_RETRIEVAL__URL=ws://127.0.0.1:8000 uv run python devtools/surreal_embedding_backfill.py --chunk-id <chunk-id> --apply
"""


@dataclass(slots=True, frozen=True)
class BackfillSettings:
    surreal_url: str
    surreal_namespace: str
    surreal_database: str
    surreal_username: str | None
    surreal_password: str | None
    surreal_access_token: str | None
    embedding_url: str
    embedding_model: str
    tei_batch_size: int
    default_chunk_strategy: str


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_default(value: object) -> str:
    return str(value)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default)
        + "\n",
        encoding="utf-8",
    )


def _log_phase(phase: str, started_at: float, **fields: Any) -> None:
    payload = {
        "phase": phase,
        "elapsed_seconds": round(time.monotonic() - started_at, 3),
        **fields,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=_json_default), file=sys.stderr, flush=True)


def _read_settings_from_env() -> BackfillSettings:
    settings = Settings()
    surreal_url = settings.surreal_retrieval.url.strip()
    surreal_namespace = settings.surreal_retrieval.namespace.strip()
    surreal_database = (settings.surreal_retrieval.database or "").strip()
    embedding_url = (settings.embedding.url or "").strip()
    embedding_model = settings.embedding.model.strip()
    if not surreal_url:
        raise ValueError("surreal_retrieval.url must be set")
    if not surreal_namespace:
        raise ValueError("surreal_retrieval.namespace must be set")
    if not surreal_database:
        raise ValueError("surreal_retrieval.database must be set")
    if not embedding_url:
        raise ValueError("embedding.url must be set")
    if not embedding_model:
        raise ValueError("embedding.model must be set")

    surreal_username = settings.surreal_retrieval.username
    surreal_password = settings.surreal_retrieval.password
    surreal_access_token = settings.surreal_retrieval.access_token
    has_username = bool(surreal_username)
    has_password = bool(surreal_password)
    if has_username != has_password:
        raise ValueError(
            "surreal_retrieval.username and surreal_retrieval.password must be set together"
        )
    if (has_username or has_password) and surreal_access_token:
        raise ValueError(
            "surreal_retrieval.access_token must not be combined with username/password auth"
        )

    tei_batch_size = settings.embedding.tei_batch_size
    if tei_batch_size <= 0:
        raise ValueError("embedding.tei_batch_size must be positive")

    default_chunk_strategy = settings.indexing.chunk_strategy.strip() or _DEFAULT_CHUNK_STRATEGY

    return BackfillSettings(
        surreal_url=surreal_url,
        surreal_namespace=surreal_namespace,
        surreal_database=surreal_database,
        surreal_username=surreal_username,
        surreal_password=surreal_password,
        surreal_access_token=surreal_access_token,
        embedding_url=embedding_url,
        embedding_model=embedding_model,
        tei_batch_size=tei_batch_size,
        default_chunk_strategy=default_chunk_strategy,
    )


def _parse_chunk_ids(args: argparse.Namespace) -> list[str]:
    chunk_ids: list[str] = []
    for chunk_id in args.chunk_id:
        value = str(chunk_id).strip()
        if value:
            chunk_ids.append(value)
    if args.chunk_ids_file is not None:
        for raw_line in args.chunk_ids_file.read_text(encoding="utf-8").splitlines():
            value = raw_line.strip()
            if value:
                chunk_ids.append(value)
    seen: set[str] = set()
    unique_chunk_ids: list[str] = []
    for chunk_id in chunk_ids:
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        unique_chunk_ids.append(chunk_id)
    if not unique_chunk_ids:
        raise ValueError("at least one --chunk-id or --chunk-ids-file entry is required")
    return unique_chunk_ids


def _stable_embedding_ref(chunk_strategy: str, embedding_model: str, chunk_id: str) -> str:
    return "\x1f".join((chunk_strategy, embedding_model, chunk_id))


def _chunk_strategy_from_row(row: dict[str, Any], default_chunk_strategy: str) -> str:
    value = row.get("chunk_strategy")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default_chunk_strategy


def _chunk_text_from_row(row: dict[str, Any]) -> str:
    value = row.get("text")
    if not isinstance(value, str):
        raise ValueError("chunk text must be a string")
    text = value.strip()
    if not text:
        raise ValueError("chunk text is empty")
    return value


def _existing_embedding_record_id(
    codec: SurrealRecordIdCodec,
    *,
    chunk_strategy: str,
    embedding_model: str,
    chunk_id: str,
) -> Any:
    return codec.encode("embeddings", _stable_embedding_ref(chunk_strategy, embedding_model, chunk_id))


def _fetch_chunk_row(connection: SurrealConnection, chunk_id: str) -> dict[str, Any] | None:
    codec = SurrealRecordIdCodec()
    selected = connection.select(codec.encode("chunks", chunk_id))
    if not isinstance(selected, dict) or not selected:
        return None
    return dict(selected)


def _fetch_existing_embedding(
    connection: SurrealConnection,
    *,
    chunk_strategy: str,
    embedding_model: str,
    chunk_id: str,
) -> dict[str, Any] | None:
    codec = SurrealRecordIdCodec()
    selected = connection.select(
        _existing_embedding_record_id(
            codec,
            chunk_strategy=chunk_strategy,
            embedding_model=embedding_model,
            chunk_id=chunk_id,
        )
    )
    if not isinstance(selected, dict) or not selected:
        return None
    return dict(selected)


def _prepare_embedding_change(
    *,
    chunk_id: str,
    chunk_strategy: str,
    embedding_model: str,
    text: str,
    vector: list[float],
) -> SurrealDeltaChange:
    text_hash = blake3.blake3(text.encode("utf-8")).hexdigest()
    return SurrealDeltaChange(
        ref=_stable_embedding_ref(chunk_strategy, embedding_model, chunk_id),
        table="embeddings",
        row={
            "chunk_id": chunk_id,
            "chunk_strategy": chunk_strategy,
            "embedding_model": embedding_model,
            "text_hash": text_hash,
            "vector_rowid": _stable_vector_rowid(chunk_strategy, embedding_model, chunk_id),
            "vector": list(vector),
            "metadata": {},
        },
    )


def _run_backfill(args: argparse.Namespace) -> dict[str, Any]:
    started_at = time.monotonic()
    started_at_iso = _utc_now()
    settings = _read_settings_from_env()
    chunk_ids = _parse_chunk_ids(args)
    _log_phase("settings_loaded", started_at, chunk_ids=len(chunk_ids), mode="apply" if args.apply else "dry_run")

    connection = SurrealConnection(
        SurrealStoreConfig(
            url=settings.surreal_url,
            namespace=settings.surreal_namespace,
            database=settings.surreal_database,
            username=settings.surreal_username,
            password=settings.surreal_password,
            access_token=settings.surreal_access_token,
        )
    )
    try:
        encoder = EmbeddingEncoder(
            model_name=settings.embedding_model,
            embedding_url=settings.embedding_url,
            tei_batch_size=settings.tei_batch_size,
        )
        writer = SurrealDeltaStoreWriter(connection=connection)

        requested: list[dict[str, Any]] = []
        missing_for_encode: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        _log_phase("chunk_fetch_start", started_at, chunk_ids=len(chunk_ids))
        for chunk_id in chunk_ids:
            row = _fetch_chunk_row(connection, chunk_id)
            if row is None:
                errors.append({"chunk_id": chunk_id, "status": "missing_chunk"})
                requested.append({"chunk_id": chunk_id, "status": "missing_chunk"})
                continue
            try:
                text = _chunk_text_from_row(row)
            except ValueError as exc:
                errors.append({"chunk_id": chunk_id, "status": "empty_text", "error": str(exc)})
                requested.append({"chunk_id": chunk_id, "status": "empty_text", "error": str(exc)})
                continue

            chunk_strategy = _chunk_strategy_from_row(row, settings.default_chunk_strategy)
            existing = _fetch_existing_embedding(
                connection,
                chunk_strategy=chunk_strategy,
                embedding_model=settings.embedding_model,
                chunk_id=chunk_id,
            )
            if existing is not None:
                requested.append(
                    {
                        "chunk_id": chunk_id,
                        "chunk_strategy": chunk_strategy,
                        "status": "already_present",
                    }
                )
                continue

            item = {
                "chunk_id": chunk_id,
                "chunk_strategy": chunk_strategy,
                "text": text,
            }
            requested.append(item)
            missing_for_encode.append(item)

        _log_phase(
            "chunk_fetch_complete",
            started_at,
            requested=len(requested),
            missing=len(missing_for_encode),
            skipped=len(errors),
        )

        encoded_vectors: list[list[float]] = []
        if missing_for_encode:
            _log_phase("embed_start", started_at, missing=len(missing_for_encode))
            encoded_vectors = encoder.encode_batch([item["text"] for item in missing_for_encode])
            if len(encoded_vectors) != len(missing_for_encode):
                raise RuntimeError(
                    f"encoder returned {len(encoded_vectors)} vectors for {len(missing_for_encode)} chunks"
                )
            _log_phase("embed_complete", started_at, missing=len(missing_for_encode))

        planned_changes: list[SurrealDeltaChange] = []
        for item, vector in zip(missing_for_encode, encoded_vectors, strict=False):
            planned_changes.append(
                _prepare_embedding_change(
                    chunk_id=item["chunk_id"],
                    chunk_strategy=item["chunk_strategy"],
                    embedding_model=settings.embedding_model,
                    text=item["text"],
                    vector=vector,
                )
            )

        applied = 0
        if args.apply and planned_changes:
            _log_phase("write_start", started_at, planned=len(planned_changes))
            applied = writer.write_embeddings(planned_changes)
            _log_phase("write_complete", started_at, applied=applied, planned=len(planned_changes))

        chunk_results: list[dict[str, Any]] = []
        for item in requested:
            if item.get("status") == "already_present":
                chunk_results.append(item)
                continue
            if item.get("status") in {"missing_chunk", "empty_text"}:
                chunk_results.append(item)
                continue
            result = {
                "chunk_id": item["chunk_id"],
                "chunk_strategy": item["chunk_strategy"],
                "status": "written" if args.apply else "dry_run_planned",
                "text_hash": blake3.blake3(item["text"].encode("utf-8")).hexdigest(),
            }
            chunk_results.append(result)

        status = "blocked" if errors or (args.apply and applied != len(planned_changes)) else "verified"

        result = {
            "status": status,
            "mode": "apply" if args.apply else "dry_run",
            "started_at": started_at_iso,
            "finished_at": _utc_now(),
            "elapsed_seconds": round(time.monotonic() - started_at, 3),
            "embedding_model": settings.embedding_model,
            "default_chunk_strategy": settings.default_chunk_strategy,
            "requested_chunk_ids": chunk_ids,
            "chunk_count": len(chunk_ids),
            "found_chunks": len(requested) - len(errors),
            "already_present": sum(1 for item in requested if item.get("status") == "already_present"),
            "planned_writes": len(planned_changes),
            "applied_writes": applied,
            "skipped": errors,
            "chunk_results": chunk_results,
        }
        _log_phase(
            "complete",
            started_at,
            status=status,
            planned_writes=len(planned_changes),
            applied_writes=applied,
        )
        return result
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_HELP_EPILOG,
    )
    parser.add_argument(
        "--chunk-id",
        action="append",
        default=[],
        help="Chunk ID to backfill; repeat for multiple chunks.",
    )
    parser.add_argument(
        "--chunk-ids-file",
        type=Path,
        default=None,
        help="Path to a newline-delimited file of chunk IDs.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write missing embeddings back to SurrealDB instead of running a dry run.",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="Optional path to write the JSON report.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = _run_backfill(args)
    if args.json_output is not None:
        _write_json(args.json_output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=_json_default), flush=True)
    return 0 if result["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
