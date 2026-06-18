"""Bounded SurrealDB HNSW diagnostic harness.

The harness creates throwaway SurrealKV databases with synthetic vectors and
measures where HNSW index creation starts failing. It is intentionally separate
from the Phase 43 candidate target.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotmd.ingestion.migrate_surreal import iter_sqlite_embedding_rows_for_surreal
from dotmd.storage.surreal import SurrealConnection, SurrealStoreConfig
from surreal_index_build_runner import _surreal_runtime_env_snapshot, _surrealkv_file_snapshot


@dataclass(slots=True, frozen=True)
class HnswDiagnosticCase:
    name: str
    count: int
    dimension: int
    source_kind: str
    vector_type: str
    distance: str
    m: int
    efc: int
    insert_batch_size: int
    segment_size: int | None


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


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _parse_positive_ints(raw: str, *, field_name: str) -> tuple[int, ...]:
    values: list[int] = []
    for item in raw.split(","):
        stripped = item.strip()
        if not stripped:
            continue
        value = int(stripped)
        if value <= 0:
            raise ValueError(f"{field_name} must contain positive integers")
        values.append(value)
    if not values:
        raise ValueError(f"{field_name} must not be empty")
    return tuple(values)


def _case_name(case: HnswDiagnosticCase) -> str:
    segment = "default" if case.segment_size is None else str(case.segment_size)
    return (
        f"{case.source_kind}_n{case.count}_d{case.dimension}_{case.vector_type.lower()}_"
        f"{case.distance.lower()}_m{case.m}_efc{case.efc}_seg{segment}"
    )


def _vector_for(row_index: int, dimension: int) -> list[float]:
    return [
        round(math.sin((row_index + 1) * (dim + 1) * 0.017) * 0.5 + 0.5, 6)
        for dim in range(dimension)
    ]


def _embedding_rows(case: HnswDiagnosticCase, *, offset: int, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    upper_bound = min(case.count, offset + limit)
    for row_index in range(offset, upper_bound):
        rows.append(
            {
                "id": f"embeddings:diag_{row_index}",
                "chunk_id": f"chunks:diag_{row_index}",
                "chunk_strategy": "diagnostic",
                "embedding_model": f"diagnostic-{case.dimension}",
                "text_hash": f"hash-{row_index}",
                "embedding": _vector_for(row_index, case.dimension),
            }
        )
    return rows


def _actual_embedding_batches(
    case: HnswDiagnosticCase,
    source_sqlite: Path,
) -> Iterator[tuple[int, list[dict[str, Any]]]]:
    batch: list[dict[str, Any]] = []
    inserted = 0
    for row in iter_sqlite_embedding_rows_for_surreal(
        source_sqlite,
        batch_size=case.insert_batch_size,
    ):
        payload = dict(row)
        payload["id"] = f"embeddings:real_{inserted}"
        batch.append(payload)
        inserted += 1
        if len(batch) >= case.insert_batch_size:
            yield inserted, batch
            batch = []
        if inserted >= case.count:
            break
    if batch:
        yield inserted, batch


def _hnsw_statement(case: HnswDiagnosticCase) -> str:
    return (
        "DEFINE INDEX embeddings_vector_hnsw ON TABLE embeddings FIELDS vector "
        f"HNSW DIMENSION {case.dimension} DIST {case.distance} TYPE {case.vector_type} "
        f"EFC {case.efc} M {case.m};"
    )


def _prepare_case_database(
    case: HnswDiagnosticCase,
    *,
    target_url: str,
    source_sqlite: Path | None,
) -> dict[str, Any]:
    started = time.monotonic()
    inserted = 0
    with SurrealConnection(
        SurrealStoreConfig(url=target_url, namespace="dotmd_diag", database="hnsw_diag")
    ) as connection:
        connection.query("DEFINE TABLE embeddings SCHEMALESS;")
        if case.source_kind == "actual":
            if source_sqlite is None:
                raise ValueError("actual source cases require --source-sqlite")
            for inserted, rows in _actual_embedding_batches(case, source_sqlite):
                connection.query("INSERT INTO embeddings $rows;", {"rows": rows})
                if inserted % max(case.insert_batch_size, 5000) == 0:
                    print(
                        json.dumps(
                            {
                                "phase": "insert",
                                "case": case.name,
                                "inserted": inserted,
                                "elapsed_seconds": round(time.monotonic() - started, 3),
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
        else:
            for offset in range(0, case.count, case.insert_batch_size):
                connection.query(
                    "INSERT INTO embeddings $rows;",
                    {"rows": _embedding_rows(case, offset=offset, limit=case.insert_batch_size)},
                )
                inserted = min(case.count, offset + case.insert_batch_size)
                if inserted % max(case.insert_batch_size, 5000) == 0:
                    print(
                        json.dumps(
                            {
                                "phase": "insert",
                                "case": case.name,
                                "inserted": inserted,
                                "elapsed_seconds": round(time.monotonic() - started, 3),
                            },
                            sort_keys=True,
                        ),
                        flush=True,
                    )
    return {
        "status": "inserted",
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "row_count": inserted,
        "sample_record_json_bytes": None
        if case.source_kind == "actual"
        else len(json.dumps(_embedding_rows(case, offset=0, limit=1)[0], ensure_ascii=False)),
    }


def _worker_main(args: argparse.Namespace) -> int:
    payload = json.loads(args.worker_input.read_text(encoding="utf-8"))
    started = time.monotonic()
    result: dict[str, Any] = {
        "operation": "define_hnsw",
        "statement": payload["statement"],
        "runtime_env": _surreal_runtime_env_snapshot(),
        "started_at": _utc_now(),
    }
    try:
        with SurrealConnection(
            SurrealStoreConfig(
                url=payload["target_url"],
                namespace=payload["namespace"],
                database=payload["database"],
            )
        ) as connection:
            connection.query(payload["statement"])
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


def _run_define_hnsw(
    case: HnswDiagnosticCase,
    *,
    case_dir: Path,
    target_url: str,
    heartbeat_seconds: float,
    timeout_seconds: float,
) -> dict[str, Any]:
    worker_input = case_dir / "define-hnsw-input.json"
    worker_result = case_dir / "define-hnsw-result.json"
    heartbeat_path = case_dir / "heartbeat.jsonl"
    statement = _hnsw_statement(case)
    _write_json(
        worker_input,
        {
            "target_url": target_url,
            "namespace": "dotmd_diag",
            "database": "hnsw_diag",
            "statement": statement,
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
            "state": "waiting_define_hnsw",
            "case": case.name,
            "elapsed_seconds": round(elapsed, 3),
            "timeout_seconds": timeout_seconds,
            "surrealkv_file_snapshot": _surrealkv_file_snapshot(target_url),
            "updated_at": _utc_now(),
        }
        _append_jsonl(heartbeat_path, heartbeat)
        if elapsed >= timeout_seconds:
            process.kill()
            _stdout, stderr = process.communicate(timeout=5)
            result = {
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
            "status": "failed",
            "error": "worker exited without result file",
            "returncode": process.returncode,
            "stderr": stderr[-2000:],
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "finished_at": _utc_now(),
        }
    result["stderr"] = stderr[-2000:] if stderr else ""
    return result


def _build_cases(args: argparse.Namespace) -> list[HnswDiagnosticCase]:
    counts = _parse_positive_ints(args.counts, field_name="--counts")
    dimensions = _parse_positive_ints(args.dimensions, field_name="--dimensions")
    m_values = _parse_positive_ints(args.m_values, field_name="--m-values")
    efc_values = _parse_positive_ints(args.efc_values, field_name="--efc-values")
    segment_sizes = (
        (None,)
        if args.segment_sizes == "default"
        else tuple(
            None if value == 0 else value
            for value in _parse_positive_ints(args.segment_sizes, field_name="--segment-sizes")
        )
    )
    cases: list[HnswDiagnosticCase] = []
    for count in counts:
        for dimension in dimensions:
            for m in m_values:
                for efc in efc_values:
                    for segment_size in segment_sizes:
                        case = HnswDiagnosticCase(
                            name="",
                            count=count,
                            dimension=dimension,
                            source_kind=args.source_kind,
                            vector_type=args.vector_type,
                            distance=args.distance,
                            m=m,
                            efc=efc,
                            insert_batch_size=args.insert_batch_size,
                            segment_size=segment_size,
                        )
                        cases.append(
                            HnswDiagnosticCase(
                                name=_case_name(case),
                                count=case.count,
                                dimension=case.dimension,
                                source_kind=case.source_kind,
                                vector_type=case.vector_type,
                                distance=case.distance,
                                m=case.m,
                                efc=case.efc,
                                insert_batch_size=case.insert_batch_size,
                                segment_size=case.segment_size,
                            )
                        )
    return cases[: args.max_cases] if args.max_cases else cases


def _run_case(case: HnswDiagnosticCase, *, output_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    case_dir = output_dir / case.name
    target_dir = case_dir / "target.surreal.db"
    if case_dir.exists() and not args.keep_existing:
        shutil.rmtree(case_dir)
    case_dir.mkdir(parents=True, exist_ok=True)
    target_url = f"surrealkv://{target_dir}"
    previous_segment_size = os.environ.get("SURREAL_SURREALKV_MAX_SEGMENT_SIZE")
    if case.segment_size is not None:
        os.environ["SURREAL_SURREALKV_MAX_SEGMENT_SIZE"] = str(case.segment_size)
    elif "SURREAL_SURREALKV_MAX_SEGMENT_SIZE" in os.environ:
        del os.environ["SURREAL_SURREALKV_MAX_SEGMENT_SIZE"]

    try:
        plan = {
            "case": asdict(case),
            "target_url": target_url,
            "runtime_env": _surreal_runtime_env_snapshot(),
            "started_at": _utc_now(),
            "hnsw_statement": _hnsw_statement(case),
        }
        _write_json(case_dir / "case-plan.json", plan)
        insert_result = _prepare_case_database(
            case,
            target_url=target_url,
            source_sqlite=args.source_sqlite,
        )
        before_index_snapshot = _surrealkv_file_snapshot(target_url)
        define_result = _run_define_hnsw(
            case,
            case_dir=case_dir,
            target_url=target_url,
            heartbeat_seconds=args.heartbeat_seconds,
            timeout_seconds=args.timeout_seconds,
        )
        after_index_snapshot = _surrealkv_file_snapshot(target_url)
        result = {
            "case": asdict(case),
            "status": define_result.get("status", "failed"),
            "target_url": target_url,
            "runtime_env": _surreal_runtime_env_snapshot(),
            "insert_result": insert_result,
            "define_result": define_result,
            "before_index_snapshot": before_index_snapshot,
            "after_index_snapshot": after_index_snapshot,
            "finished_at": _utc_now(),
        }
        _write_json(case_dir / "case-result.json", result)
        return result
    finally:
        if previous_segment_size is None:
            os.environ.pop("SURREAL_SURREALKV_MAX_SEGMENT_SIZE", None)
        else:
            os.environ["SURREAL_SURREALKV_MAX_SEGMENT_SIZE"] = previous_segment_size


def run_diagnostics(args: argparse.Namespace) -> int:
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    cases = _build_cases(args)
    summary_path = output_dir / "summary.jsonl"
    if summary_path.exists() and not args.append_summary:
        summary_path.unlink()
    _write_json(
        output_dir / "run-plan.json",
        {
            "started_at": _utc_now(),
            "case_count": len(cases),
            "runtime_env": _surreal_runtime_env_snapshot(),
            "cases": [asdict(case) for case in cases],
        },
    )
    failed = False
    for index, case in enumerate(cases, start=1):
        print(f"hnsw-diagnostics case {index}/{len(cases)} {case.name}", flush=True)
        result = _run_case(case, output_dir=output_dir, args=args)
        _append_jsonl(summary_path, result)
        print(
            "hnsw-diagnostics "
            f"{case.name}: status={result['status']} "
            f"insert={result['insert_result']['elapsed_seconds']}s "
            f"define={result['define_result'].get('elapsed_seconds')}s",
            flush=True,
        )
        if result["status"] not in {"applied"}:
            failed = True
            if args.stop_on_failure:
                break
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=False)
    parser.add_argument("--counts", default="1000")
    parser.add_argument("--dimensions", default="128")
    parser.add_argument("--m-values", default="12")
    parser.add_argument("--efc-values", default="64")
    parser.add_argument("--segment-sizes", default="default")
    parser.add_argument("--vector-type", choices=("F32", "F64"), default="F32")
    parser.add_argument("--source-kind", choices=("synthetic", "actual"), default="synthetic")
    parser.add_argument("--source-sqlite", type=Path)
    parser.add_argument("--distance", choices=("COSINE", "EUCLIDEAN", "MANHATTAN"), default="COSINE")
    parser.add_argument("--insert-batch-size", type=int, default=1000)
    parser.add_argument("--heartbeat-seconds", type=float, default=10.0)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--max-cases", type=int, default=0)
    parser.add_argument("--stop-on-failure", action="store_true")
    parser.add_argument("--append-summary", action="store_true")
    parser.add_argument("--keep-existing", action="store_true")
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
    if args.output_dir is None:
        raise ValueError("--output-dir is required")
    if args.insert_batch_size <= 0:
        raise ValueError("--insert-batch-size must be positive")
    if args.heartbeat_seconds <= 0:
        raise ValueError("--heartbeat-seconds must be positive")
    if args.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be positive")
    if args.source_kind == "actual" and args.source_sqlite is None:
        raise ValueError("--source-sqlite is required when --source-kind=actual")
    return run_diagnostics(args)


if __name__ == "__main__":
    raise SystemExit(main())
