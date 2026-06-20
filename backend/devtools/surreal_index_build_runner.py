"""Instrumented Surreal index build post-step for Phase 43/44 cutover readiness."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotmd.storage.surreal import SurrealConnection, SurrealStoreConfig
from dotmd.storage.surreal_schema import (
    DEFAULT_HNSW_EF,
    DEFAULT_HNSW_M,
    DEFAULT_SURREAL_HNSW_VECTOR_INDEX_TYPE,
    build_surreal_embedding_hnsw_index_statement,
    build_surreal_native_retrieval_index_plan,
    surreal_embedding_hnsw_index_name,
    surreal_embedding_shard_tables,
)

SURREAL_RUNTIME_ENV_KEYS = (
    "SURREAL_SURREALKV_MAX_SEGMENT_SIZE",
    "SURREAL_SURREALKV_MAX_VALUE_THRESHOLD",
    "SURREAL_SURREALKV_MAX_VALUE_CACHE_SIZE",
    "SURREAL_SYNC_DATA",
    "SURREAL_HNSW_CACHE_SIZE",
)

_DEFERRED_EMBEDDING_INDEX_DEFINITIONS = (
    (
        "embeddings_strategy_chunk_model_idx",
        "DEFINE INDEX embeddings_strategy_chunk_model_idx ON TABLE embeddings COLUMNS chunk_strategy, chunk_id, embedding_model UNIQUE;",
    ),
    (
        "embeddings_strategy_model_idx",
        "DEFINE INDEX embeddings_strategy_model_idx ON TABLE embeddings COLUMNS chunk_strategy, embedding_model;",
    ),
    (
        "embeddings_text_hash_idx",
        "DEFINE INDEX embeddings_text_hash_idx ON TABLE embeddings COLUMNS text_hash;",
    ),
)


@dataclass(slots=True, frozen=True)
class IndexBuildStep:
    name: str
    statement: str
    required: bool
    statement_hash: str
    table_name: str = "embeddings"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _target_size_bytes(target_url: str) -> int | None:
    if not target_url.startswith("surrealkv://"):
        return None
    target_path = Path(target_url.removeprefix("surrealkv://"))
    if not target_path.exists():
        return None
    if target_path.is_dir():
        return sum(path.stat().st_size for path in target_path.rglob("*") if path.is_file())
    if target_path.is_file():
        return target_path.stat().st_size
    return None


def _surreal_runtime_env_snapshot() -> dict[str, str]:
    return {key: value for key in SURREAL_RUNTIME_ENV_KEYS if (value := os.environ.get(key))}


def _surrealkv_file_snapshot(target_url: str) -> dict[str, Any] | None:
    if not target_url.startswith("surrealkv://"):
        return None
    target_path = Path(target_url.removeprefix("surrealkv://"))
    if not target_path.is_dir():
        return None
    files = [path for path in target_path.rglob("*") if path.is_file()]
    clog_files = [path for path in files if path.parent.name == "clog"]
    largest = max(files, key=lambda path: path.stat().st_size, default=None)
    largest_clog = max(clog_files, key=lambda path: path.stat().st_size, default=None)
    return {
        "file_count": len(files),
        "total_size_bytes": sum(path.stat().st_size for path in files),
        "clog_file_count": len(clog_files),
        "clog_total_size_bytes": sum(path.stat().st_size for path in clog_files),
        "largest_file": None
        if largest is None
        else {
            "path": str(largest.relative_to(target_path)),
            "size_bytes": largest.stat().st_size,
        },
        "largest_clog_file": None
        if largest_clog is None
        else {
            "path": str(largest_clog.relative_to(target_path)),
            "size_bytes": largest_clog.stat().st_size,
        },
    }


def _snapshot_with_delta(
    target_url: str,
    previous_snapshot: dict[str, Any] | None,
) -> dict[str, Any] | None:
    snapshot = _surrealkv_file_snapshot(target_url)
    if snapshot is None:
        return None
    if previous_snapshot is not None:
        snapshot["delta_total_size_bytes"] = int(snapshot["total_size_bytes"]) - int(
            previous_snapshot["total_size_bytes"]
        )
        snapshot["delta_clog_total_size_bytes"] = int(snapshot["clog_total_size_bytes"]) - int(
            previous_snapshot["clog_total_size_bytes"]
        )
    return snapshot


def _json_default(value: object) -> str:
    return str(value)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default)
        + "\n",
        encoding="utf-8",
    )


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _statement_hash(statement: str) -> str:
    return hashlib.sha256(statement.encode("utf-8")).hexdigest()


def _remove_index_statement(index_name: str, table_name: str) -> str:
    return f"REMOVE INDEX {index_name} ON TABLE {table_name};"


def build_index_steps(
    index_mode: str,
    *,
    embedding_dimension: int,
    hnsw_m: int = DEFAULT_HNSW_M,
    hnsw_ef: int = DEFAULT_HNSW_EF,
    vector_index_type: str = DEFAULT_SURREAL_HNSW_VECTOR_INDEX_TYPE,
    embedding_shard_count: int = 1,
) -> list[IndexBuildStep]:
    secondary_steps = [
        IndexBuildStep(
            name=name,
            statement=statement,
            required=True,
            statement_hash=_statement_hash(statement),
            table_name="embeddings",
        )
        for name, statement in _DEFERRED_EMBEDDING_INDEX_DEFINITIONS
    ]
    retrieval_plan = build_surreal_native_retrieval_index_plan(
        embedding_dimension=embedding_dimension,
        hnsw_m=hnsw_m,
        hnsw_ef=hnsw_ef,
        vector_index_type=vector_index_type,
    )
    if embedding_shard_count == 1:
        hnsw_steps = [
            IndexBuildStep(
                name=surreal_embedding_hnsw_index_name(),
                statement=retrieval_plan.hnsw_index_statement,
                required=True,
                statement_hash=_statement_hash(retrieval_plan.hnsw_index_statement),
                table_name="embeddings",
            )
        ]
    else:
        hnsw_steps = []
        for index, table_name in enumerate(surreal_embedding_shard_tables(embedding_shard_count)):
            statement = build_surreal_embedding_hnsw_index_statement(
                table_name=table_name,
                index_name=surreal_embedding_hnsw_index_name(index),
                embedding_dimension=embedding_dimension,
                hnsw_m=hnsw_m,
                hnsw_ef=hnsw_ef,
                vector_index_type=vector_index_type,
            )
            hnsw_steps.append(
                IndexBuildStep(
                    name=surreal_embedding_hnsw_index_name(index),
                    statement=statement,
                    required=True,
                    statement_hash=_statement_hash(statement),
                    table_name=table_name,
                )
            )
    if index_mode == "unique-only":
        return secondary_steps[:1]
    if index_mode == "secondary":
        return secondary_steps
    if index_mode == "hnsw":
        return hnsw_steps
    if index_mode == "all":
        return [*secondary_steps, *hnsw_steps]
    raise ValueError(f"unsupported index mode: {index_mode}")


def _index_name_present(info_payload: dict[str, Any], index_name: str) -> bool:
    return index_name in json.dumps(info_payload, default=_json_default, sort_keys=True)


def _worker_main(args: argparse.Namespace) -> int:
    worker_input = json.loads(args.worker_input.read_text(encoding="utf-8"))
    started = time.monotonic()
    result: dict[str, Any] = {
        "operation": worker_input["operation"],
        "index_name": worker_input.get("index_name"),
        "statement_hash": worker_input.get("statement_hash"),
        "table_name": worker_input.get("table_name"),
        "runtime_env": _surreal_runtime_env_snapshot(),
        "started_at": _utc_now(),
    }
    try:
        with SurrealConnection(
            SurrealStoreConfig(
                url=worker_input["target_url"],
                namespace=worker_input["target_namespace"],
                database=worker_input["target_database"],
                username=os.environ.get("DOTMD_SURREAL_RETRIEVAL_USERNAME") or None,
                password=os.environ.get("DOTMD_SURREAL_RETRIEVAL_PASSWORD") or None,
                access_token=os.environ.get("DOTMD_SURREAL_RETRIEVAL_ACCESS_TOKEN") or None,
                http_query_timeout_seconds=float(worker_input["query_timeout_seconds"]),
            )
        ) as connection:
            if worker_input["operation"] == "info_embeddings":
                table_name = str(worker_input.get("table_name") or "embeddings")
                result["info"] = connection.query_raw(f"INFO FOR TABLE {table_name};")
            else:
                connection.query(worker_input["statement"])
    except BaseException as exc:
        result.update(
            {
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "finished_at": _utc_now(),
            }
        )
        _write_json(args.worker_result, result)
        return 1
    result.update(
        {
            "status": "applied",
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "finished_at": _utc_now(),
        }
    )
    _write_json(args.worker_result, result)
    return 0


def _run_statement_with_heartbeat(
    *,
    operation: str,
    index_name: str,
    statement: str,
    statement_hash: str,
    table_name: str,
    step_index: int,
    total_steps: int,
    target_url: str,
    target_namespace: str,
    target_database: str,
    output_dir: Path,
    heartbeat_seconds: float,
    timeout_seconds: float,
    print_heartbeat: bool,
    artifact_suffix: str = "",
) -> dict[str, Any]:
    worker_input = output_dir / f"{step_index:02d}-{index_name}{artifact_suffix}-input.json"
    worker_result = output_dir / f"{step_index:02d}-{index_name}{artifact_suffix}-result.json"
    heartbeat_path = output_dir / "index-build-heartbeat.jsonl"
    _write_json(
        worker_input,
        {
            "operation": operation,
            "index_name": index_name,
            "statement": statement,
            "statement_hash": statement_hash,
            "table_name": table_name,
            "target_url": target_url,
            "target_namespace": target_namespace,
            "target_database": target_database,
            "query_timeout_seconds": timeout_seconds,
            "runtime_env": _surreal_runtime_env_snapshot(),
        },
    )

    started = time.monotonic()
    process = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            "--worker-input",
            str(worker_input),
            "--worker-result",
            str(worker_result),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    previous_snapshot: dict[str, Any] | None = None
    while process.poll() is None:
        elapsed = time.monotonic() - started
        storage_snapshot = _snapshot_with_delta(target_url, previous_snapshot)
        previous_snapshot = storage_snapshot or previous_snapshot
        heartbeat = {
            "state": f"waiting_opaque_{operation}",
            "index_name": index_name,
            "operation": operation,
            "index_ordinal": step_index,
            "total_indexes": total_steps,
            "statement_hash": statement_hash,
            "elapsed_seconds": round(elapsed, 3),
            "timeout_seconds": timeout_seconds,
            "target_size_bytes": _target_size_bytes(target_url),
            "surrealkv_file_snapshot": storage_snapshot,
            "updated_at": _utc_now(),
        }
        _append_jsonl(heartbeat_path, heartbeat)
        if print_heartbeat:
            print(
                "index-build "
                f"{step_index}/{total_steps} {index_name}: "
                f"state=waiting_opaque_{operation} elapsed={int(elapsed)}s",
                flush=True,
            )
        if elapsed >= timeout_seconds:
            process.kill()
            _stdout, stderr = process.communicate(timeout=5)
            result = {
                "index_name": index_name,
                "operation": operation,
                "statement_hash": statement_hash,
                "status": "timed_out_uncertain",
                "elapsed_seconds": round(elapsed, 3),
                "timeout_seconds": timeout_seconds,
                "stderr": stderr[-2000:],
                "finished_at": _utc_now(),
            }
            _write_json(worker_result, result)
            return result
        time.sleep(heartbeat_seconds)

    _stdout, stderr = process.communicate(timeout=5)
    if worker_result.exists():
        result = json.loads(worker_result.read_text(encoding="utf-8"))
    else:
        result = {
            "index_name": index_name,
            "operation": operation,
            "statement_hash": statement_hash,
            "status": "failed",
            "error": "worker exited without result file",
            "returncode": process.returncode,
            "stderr": stderr[-2000:],
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "finished_at": _utc_now(),
        }
    result["stderr"] = stderr[-2000:] if stderr else ""
    return result


def _run_step_with_heartbeat(
    *,
    step: IndexBuildStep,
    step_index: int,
    total_steps: int,
    target_url: str,
    target_namespace: str,
    target_database: str,
    output_dir: Path,
    heartbeat_seconds: float,
    timeout_seconds: float,
    print_heartbeat: bool,
) -> dict[str, Any]:
    return _run_statement_with_heartbeat(
        operation="define_index",
        index_name=step.name,
        statement=step.statement,
        statement_hash=step.statement_hash,
        table_name=step.table_name,
        step_index=step_index,
        total_steps=total_steps,
        target_url=target_url,
        target_namespace=target_namespace,
        target_database=target_database,
        output_dir=output_dir,
        heartbeat_seconds=heartbeat_seconds,
        timeout_seconds=timeout_seconds,
        print_heartbeat=print_heartbeat,
    )


def _run_info_with_heartbeat(
    *,
    label: str,
    table_name: str,
    target_url: str,
    target_namespace: str,
    target_database: str,
    output_dir: Path,
    heartbeat_seconds: float,
    timeout_seconds: float,
    print_heartbeat: bool,
) -> dict[str, Any]:
    worker_input = output_dir / f"{label}-input.json"
    worker_result = output_dir / f"{label}.json"
    heartbeat_path = output_dir / "index-build-heartbeat.jsonl"
    _write_json(
        worker_input,
        {
            "operation": "info_embeddings",
            "table_name": table_name,
            "target_url": target_url,
            "target_namespace": target_namespace,
            "target_database": target_database,
            "query_timeout_seconds": timeout_seconds,
            "runtime_env": _surreal_runtime_env_snapshot(),
        },
    )
    started = time.monotonic()
    process = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            "--worker-input",
            str(worker_input),
            "--worker-result",
            str(worker_result),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    while process.poll() is None:
        elapsed = time.monotonic() - started
        heartbeat = {
            "state": "waiting_opaque_info",
            "operation": label,
            "elapsed_seconds": round(elapsed, 3),
            "timeout_seconds": timeout_seconds,
            "target_size_bytes": _target_size_bytes(target_url),
            "updated_at": _utc_now(),
        }
        _append_jsonl(heartbeat_path, heartbeat)
        if print_heartbeat:
            print(
                f"index-build {label}: state=waiting_opaque_info elapsed={int(elapsed)}s",
                flush=True,
            )
        if elapsed >= timeout_seconds:
            process.kill()
            _stdout, stderr = process.communicate(timeout=5)
            result = {
            "operation": label,
            "table_name": table_name,
            "status": "timed_out_uncertain",
                "elapsed_seconds": round(elapsed, 3),
                "timeout_seconds": timeout_seconds,
                "stderr": stderr[-2000:],
                "finished_at": _utc_now(),
            }
            _write_json(worker_result, result)
            return result
        time.sleep(heartbeat_seconds)

    _stdout, stderr = process.communicate(timeout=5)
    if worker_result.exists():
        result = json.loads(worker_result.read_text(encoding="utf-8"))
    else:
        result = {
            "operation": label,
            "status": "failed",
            "error": "worker exited without result file",
            "returncode": process.returncode,
            "stderr": stderr[-2000:],
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "finished_at": _utc_now(),
        }
    result["stderr"] = stderr[-2000:] if stderr else ""
    result["captured_at"] = result.get("finished_at", _utc_now())
    result["table"] = table_name
    return result


def run_index_build(args: argparse.Namespace) -> int:
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    heartbeat_path = output_dir / "index-build-heartbeat.jsonl"
    if heartbeat_path.exists():
        heartbeat_path.unlink()
    steps = build_index_steps(
        args.index_mode,
        embedding_dimension=args.embedding_dimension,
        hnsw_m=args.hnsw_m,
        hnsw_ef=args.hnsw_ef,
        vector_index_type=args.vector_index_type,
        embedding_shard_count=args.embedding_shard_count,
    )
    runtime_env = _surreal_runtime_env_snapshot()
    (output_dir / "index-ddl.sql").write_text(
        "\n".join(step.statement for step in steps) + "\n",
        encoding="utf-8",
    )
    _write_json(
        output_dir / "index-build-plan.json",
        {
            "created_at": _utc_now(),
            "index_mode": args.index_mode,
            "target_url": args.target_url,
            "target_namespace": args.target_namespace,
            "target_database": args.target_database,
            "runtime_env": runtime_env,
            "heartbeat_seconds": args.heartbeat_seconds,
            "timeout_seconds": args.timeout_seconds,
            "embedding_shard_count": args.embedding_shard_count,
            "rebuild_existing": args.rebuild_existing,
            "steps": [asdict(step) for step in steps],
        },
    )

    results: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        before_info = _run_info_with_heartbeat(
            label=f"{index:02d}-{step.table_name}-info-before",
            table_name=step.table_name,
            target_url=args.target_url,
            target_namespace=args.target_namespace,
            target_database=args.target_database,
            output_dir=output_dir,
            heartbeat_seconds=args.heartbeat_seconds,
            timeout_seconds=args.timeout_seconds,
            print_heartbeat=not args.no_print_heartbeat,
        )
        if before_info.get("status") != "applied":
            results.append(before_info)
            break
        if _index_name_present(before_info, step.name):
            if args.rebuild_existing:
                remove_statement = _remove_index_statement(step.name, step.table_name)
                remove_result = _run_statement_with_heartbeat(
                    operation="remove_index",
                    index_name=step.name,
                    statement=remove_statement,
                    statement_hash=_statement_hash(remove_statement),
                    table_name=step.table_name,
                    step_index=index,
                    total_steps=len(steps),
                    target_url=args.target_url,
                    target_namespace=args.target_namespace,
                    target_database=args.target_database,
                    output_dir=output_dir,
                    heartbeat_seconds=args.heartbeat_seconds,
                    timeout_seconds=args.timeout_seconds,
                    print_heartbeat=not args.no_print_heartbeat,
                    artifact_suffix="-remove",
                )
                if remove_result.get("status") != "applied":
                    results.append(remove_result)
                    break
                result = _run_step_with_heartbeat(
                    step=step,
                    step_index=index,
                    total_steps=len(steps),
                    target_url=args.target_url,
                    target_namespace=args.target_namespace,
                    target_database=args.target_database,
                    output_dir=output_dir,
                    heartbeat_seconds=args.heartbeat_seconds,
                    timeout_seconds=args.timeout_seconds,
                    print_heartbeat=not args.no_print_heartbeat,
                )
                result["rebuild_existing"] = True
                result["rebuild_remove_result"] = remove_result
            else:
                result = {
                    "index_name": step.name,
                    "statement_hash": step.statement_hash,
                    "table_name": step.table_name,
                    "status": "already_present",
                    "elapsed_seconds": 0.0,
                    "finished_at": _utc_now(),
                }
                _write_json(output_dir / f"{index:02d}-{step.name}-result.json", result)
        else:
            result = _run_step_with_heartbeat(
                step=step,
                step_index=index,
                total_steps=len(steps),
                target_url=args.target_url,
                target_namespace=args.target_namespace,
                target_database=args.target_database,
                output_dir=output_dir,
                heartbeat_seconds=args.heartbeat_seconds,
                timeout_seconds=args.timeout_seconds,
                print_heartbeat=not args.no_print_heartbeat,
            )
        results.append(result)
        if result.get("status") not in {"applied", "already_present"}:
            break

    expected_indexes = [step.name for step in steps]
    info_after_results: list[dict[str, Any]] = []
    present_indexes: list[str] = []
    for step in steps:
        after_info = _run_info_with_heartbeat(
            label=f"{step.table_name}-info-after",
            table_name=step.table_name,
            target_url=args.target_url,
            target_namespace=args.target_namespace,
            target_database=args.target_database,
            output_dir=output_dir,
            heartbeat_seconds=args.heartbeat_seconds,
            timeout_seconds=args.timeout_seconds,
            print_heartbeat=not args.no_print_heartbeat,
        )
        info_after_results.append(after_info)
        if after_info.get("status") == "applied" and _index_name_present(after_info, step.name):
            present_indexes.append(step.name)
    final_status = (
        "verified"
        if len(results) == len(steps)
        and all(result.get("status") in {"applied", "already_present"} for result in results)
        and all(info.get("status") == "applied" for info in info_after_results)
        and set(present_indexes) == set(expected_indexes)
        else "blocked"
    )
    _write_json(
        output_dir / "index-build-results.json",
        {
            "status": final_status,
            "finished_at": _utc_now(),
            "target_url": args.target_url,
            "target_namespace": args.target_namespace,
            "target_database": args.target_database,
            "runtime_env": runtime_env,
            "expected_indexes": expected_indexes,
            "present_indexes": present_indexes,
            "target_size_bytes": _target_size_bytes(args.target_url),
            "results": results,
            "info_after_results": info_after_results,
        },
    )
    print(f"index-build status={final_status} present={len(present_indexes)}/{len(expected_indexes)}")
    return 0 if final_status == "verified" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-url", required=False)
    parser.add_argument("--target-namespace", default="dotmd")
    parser.add_argument("--target-database", default="production")
    parser.add_argument("--output-dir", type=Path, required=False)
    parser.add_argument(
        "--index-mode",
        choices=("unique-only", "secondary", "hnsw", "all"),
        default="all",
    )
    parser.add_argument("--heartbeat-seconds", type=float, default=60.0)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--embedding-dimension", type=int, default=1024)
    parser.add_argument("--embedding-shard-count", type=int, default=1)
    parser.add_argument(
        "--rebuild-existing",
        action="store_true",
        help="Remove and re-define existing indexes when the desired statement changes.",
    )
    parser.add_argument("--hnsw-m", type=int, default=DEFAULT_HNSW_M)
    parser.add_argument("--hnsw-ef", type=int, default=DEFAULT_HNSW_EF)
    parser.add_argument(
        "--vector-index-type",
        default=DEFAULT_SURREAL_HNSW_VECTOR_INDEX_TYPE,
        help="Surreal HNSW vector element type (for example F32, F16, or I32).",
    )
    parser.add_argument("--no-print-heartbeat", action="store_true")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--worker-input", type=Path)
    parser.add_argument("--worker-result", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.worker:
        if args.worker_input is None or args.worker_result is None:
            raise ValueError("--worker requires --worker-input and --worker-result")
        return _worker_main(args)
    if not args.target_url:
        raise ValueError("--target-url is required")
    if args.output_dir is None:
        raise ValueError("--output-dir is required")
    if args.heartbeat_seconds <= 0:
        raise ValueError("--heartbeat-seconds must be positive")
    if args.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be positive")
    if args.embedding_shard_count <= 0:
        raise ValueError("--embedding-shard-count must be positive")
    return run_index_build(args)


if __name__ == "__main__":
    raise SystemExit(main())
