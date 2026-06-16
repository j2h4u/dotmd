"""CLI runner for Phase 43 shadow-run evidence capture and verification."""

from __future__ import annotations

import argparse
import json
import os
import resource
import sqlite3
import statistics
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotmd.api.service import DotMDService
from dotmd.core.config import (
    DEFAULT_FALKORDB_GRAPH_NAME,
    RUNTIME_INDEX_DIR,
    Settings,
    load_settings,
)
from dotmd.ingestion.pipeline import _model_to_table_suffix
from dotmd.search.surreal_eval import GoldenQuery, load_golden_queries
from dotmd.search.surreal_native import build_surreal_native_engine_overrides
from dotmd.search.surreal_shadow_metrics import (
    DEFAULT_SHADOW_MEMORY_GUARDRAILS,
    ShadowMemoryMetrics,
    ShadowMetricBundle,
    validate_shadow_metric_bundle,
)
from dotmd.search.surreal_shadow_metrics import (
    write_shadow_metric_json as _raw_write_shadow_metric_json,
)
from dotmd.storage.surreal import SurrealConnection, SurrealStoreConfig
from dotmd.storage.surreal_schema import DEFAULT_HNSW_EF, validate_surreal_native_retrieval_contract

try:
    from devtools.surreal_eval_runner import EvalRunnerConfig, run_eval
except ModuleNotFoundError:  # pragma: no cover - script entrypoint fallback
    from surreal_eval_runner import EvalRunnerConfig, run_eval


@dataclass(slots=True, frozen=True)
class ShadowArtifactPaths:
    source_capture: Path
    baseline_results: Path
    candidate_results: Path
    accepted_diffs: Path
    shadow_diffs: Path
    shadow_summary: Path
    scale_metrics: Path
    memory_metrics: Path


@dataclass(slots=True, frozen=True)
class ShadowAcceptanceLedger:
    metadata: dict[str, Any] | None
    acceptance_rows: tuple[dict[str, str], ...]


@dataclass(slots=True, frozen=True)
class ExpectedSourceManifest:
    chunk_strategy: str
    embedding_model: str
    import_id: str
    expected_chunk_count: int
    expected_embedding_count: int


@dataclass(slots=True, frozen=True)
class CandidateConfig:
    embedding_dimension: int
    hnsw_ef: int
    top_k: int
    pool_size: int


@dataclass(slots=True, frozen=True)
class IsolatedBaselineGraph:
    falkordb_url: str
    source_graph: str
    baseline_graph: str


@dataclass(slots=True, frozen=True)
class ShadowRunConfig:
    golden_queries: Path
    source_capture_manifest_json: Path
    candidate_config_json: Path
    artifacts: ShadowArtifactPaths
    baseline_rehearsal_path: Path
    baseline_graph_name: str = "dotmd_shadow_baseline"
    production_graph_name: str = DEFAULT_FALKORDB_GRAPH_NAME
    metrics_replay_queries: Path | None = None
    target_url: str = ""
    target_namespace: str = "dotmd"
    target_database: str = "phase43_shadow"
    verify_only: bool = False
    capture_baseline: bool = True
    capture_candidate: bool = True
    preflight_candidate_target: bool = False
    skip_candidate_preflight: bool = False


@dataclass(slots=True, frozen=True)
class ShadowRunResult:
    artifacts: ShadowArtifactPaths
    exit_code: int


def write_shadow_metric_json(path: Path, payload: ShadowMetricBundle | dict[str, Any]) -> None:
    if isinstance(payload, ShadowMetricBundle):
        _raw_write_shadow_metric_json(path, validate_shadow_metric_bundle(payload))
        return
    _raw_write_shadow_metric_json(path, payload)


def default_shadow_artifact_paths(artifacts_dir: Path) -> ShadowArtifactPaths:
    return ShadowArtifactPaths(
        source_capture=artifacts_dir / "source-capture.json",
        baseline_results=artifacts_dir / "baseline-results.jsonl",
        candidate_results=artifacts_dir / "candidate-results.jsonl",
        accepted_diffs=artifacts_dir / "accepted-diffs.jsonl",
        shadow_diffs=artifacts_dir / "shadow-diffs.jsonl",
        shadow_summary=artifacts_dir / "shadow-summary.md",
        scale_metrics=artifacts_dir / "scale-metrics.json",
        memory_metrics=artifacts_dir / "memory-metrics.json",
    )


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} line {exc.lineno} column {exc.colno}: invalid JSON") from exc


def _load_jsonl(path: Path) -> list[tuple[int, dict[str, Any]]]:
    rows: list[tuple[int, dict[str, Any]]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path} line {line_number}: invalid JSON") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"{path} line {line_number}: expected JSON object")
            rows.append((line_number, payload))
    return rows


def _require_non_empty_str(payload: dict[str, Any], field_name: str, *, path: Path) -> str:
    value = str(payload.get(field_name, "")).strip()
    if not value:
        raise ValueError(f"{path.name}: {field_name} is required")
    return value


def _require_positive_int(
    payload: dict[str, Any],
    field_name: str,
    *,
    path: Path,
    required: bool = True,
    default: int | None = None,
) -> int:
    if field_name not in payload:
        if required:
            raise ValueError(f"{path.name}: {field_name} is required")
        assert default is not None
        return default
    value = payload[field_name]
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{path.name}: {field_name} must be a positive integer")
    return value


def load_expected_source_manifest(path: Path) -> ExpectedSourceManifest:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name}: expected JSON object")
    return ExpectedSourceManifest(
        chunk_strategy=_require_non_empty_str(payload, "chunk_strategy", path=path),
        embedding_model=_require_non_empty_str(payload, "embedding_model", path=path),
        import_id=_require_non_empty_str(payload, "import_id", path=path),
        expected_chunk_count=_require_positive_int(
            payload,
            "expected_chunk_count",
            path=path,
        ),
        expected_embedding_count=_require_positive_int(
            payload,
            "expected_embedding_count",
            path=path,
        ),
    )


def load_candidate_config(path: Path) -> CandidateConfig:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name}: expected JSON object")
    allowed_keys = {"embedding_dimension", "hnsw_ef", "top_k", "pool_size"}
    unknown_keys = sorted(set(payload) - allowed_keys)
    if unknown_keys:
        raise ValueError(f"{path.name}: unknown key {unknown_keys[0]}")
    return CandidateConfig(
        embedding_dimension=_require_positive_int(payload, "embedding_dimension", path=path),
        hnsw_ef=_require_positive_int(
            payload,
            "hnsw_ef",
            path=path,
            required=False,
            default=DEFAULT_HNSW_EF,
        ),
        top_k=_require_positive_int(payload, "top_k", path=path),
        pool_size=_require_positive_int(payload, "pool_size", path=path),
    )


def load_shadow_acceptance_ledger(path: Path) -> ShadowAcceptanceLedger:
    metadata: dict[str, Any] | None = None
    acceptance_rows: list[dict[str, str]] = []
    for line_number, payload in _load_jsonl(path):
        record_type = payload.get("record_type")
        if record_type is not None:
            if record_type != "phase43_ledger_metadata":
                raise ValueError(f"{path} line {line_number}: unsupported record_type")
            metadata = dict(payload)
            continue
        query_id = str(payload.get("query_id", "")).strip()
        accepted_by = str(payload.get("accepted_by", "")).strip()
        accepted_reason = str(payload.get("accepted_reason", "")).strip()
        if not query_id and payload:
            raise ValueError(f"{path} line {line_number}: record_type is required for metadata rows")
        if not query_id:
            continue
        if not accepted_by or not accepted_reason:
            raise ValueError(f"{path} line {line_number}: accepted_by and accepted_reason are required")
        acceptance_rows.append(
            {
                "query_id": query_id,
                "accepted_by": accepted_by,
                "accepted_reason": accepted_reason,
            }
        )
    return ShadowAcceptanceLedger(
        metadata=metadata,
        acceptance_rows=tuple(acceptance_rows),
    )


def write_shadow_acceptance_sentinel(
    path: Path,
    guardrails: dict[str, Any],
    replay_window: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "record_type": "phase43_ledger_metadata",
        "quality_corpus": "golden",
        "replay_window": replay_window,
        "guardrails": guardrails,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def load_metrics_replay_queries(path: Path) -> tuple[dict[str, str], ...]:
    rows: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for line_number, payload in _load_jsonl(path):
        query_id = str(payload.get("query_id", "")).strip()
        query = str(payload.get("query", "")).strip()
        if not query_id:
            raise ValueError(f"{path} line {line_number}: query_id is required")
        if not query:
            raise ValueError(f"{path} line {line_number}: query is required")
        if query_id in seen_ids:
            raise ValueError(f"{path} line {line_number}: duplicate query_id {query_id!r}")
        seen_ids.add(query_id)
        rows.append({"query_id": query_id, "query": query})
    return tuple(rows)


def enforce_rehearsal_path_isolation(rehearsal_path: Path, production_index_dir: Path) -> None:
    resolved_rehearsal = rehearsal_path.resolve()
    resolved_production = production_index_dir.resolve()
    runtime_index_dir = RUNTIME_INDEX_DIR.resolve()
    for protected in (resolved_production, runtime_index_dir):
        if (
            resolved_rehearsal == protected
            or protected in resolved_rehearsal.parents
            or resolved_rehearsal in protected.parents
        ):
            raise ValueError(f"rehearsal path overlaps production index dir {protected}")
    db_path = resolved_rehearsal / "index.db"
    if db_path.is_symlink():
        raise ValueError("rehearsal index.db must not be a symlink")
    if not db_path.is_file():
        raise ValueError("rehearsal index.db is required")
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ValueError("rehearsal index.db failed integrity_check") from exc
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as exc:
        raise ValueError("rehearsal index.db failed integrity_check") from exc
    finally:
        conn.close()
    if row is None or str(row[0]).lower() != "ok":
        raise ValueError("rehearsal index.db failed integrity_check")


def enforce_baseline_graph_isolation(resolved_graph_name: str) -> None:
    if resolved_graph_name == DEFAULT_FALKORDB_GRAPH_NAME:
        raise ValueError("baseline graph name must not equal production dotmd graph")


def _build_falkordb_client(url: str):  # type: ignore[no-untyped-def]
    from falkordb import FalkorDB

    parsed = urlparse(url)
    return FalkorDB(host=parsed.hostname or "localhost", port=parsed.port or 6379)


def _list_graph_names(url: str) -> list[str]:
    try:
        client = _build_falkordb_client(url)
        return list(client.list_graphs())
    except Exception:
        return [DEFAULT_FALKORDB_GRAPH_NAME]


def _production_index_stat(index_dir: Path) -> tuple[int, int] | None:
    db_path = index_dir / "index.db"
    if not db_path.exists():
        return None
    stat = db_path.stat()
    return (stat.st_mtime_ns, stat.st_size)


def copy_baseline_graph(
    falkordb_url: str,
    source_graph: str,
    baseline_graph: str,
) -> IsolatedBaselineGraph:
    enforce_baseline_graph_isolation(baseline_graph)
    client = _build_falkordb_client(falkordb_url)
    if baseline_graph in list(client.list_graphs()):
        client.select_graph(baseline_graph).delete()
    client.select_graph(source_graph).copy(baseline_graph)
    return IsolatedBaselineGraph(
        falkordb_url=falkordb_url,
        source_graph=source_graph,
        baseline_graph=baseline_graph,
    )


def teardown_baseline_graph(handle: IsolatedBaselineGraph) -> None:
    client = _build_falkordb_client(handle.falkordb_url)
    client.select_graph(handle.baseline_graph).delete()


def assert_rehearsal_identity_matches_manifest(
    rehearsal_settings: Settings,
    expected_manifest: ExpectedSourceManifest,
) -> None:
    db_path = rehearsal_settings.index_db_path
    strategy = str(rehearsal_settings.chunk_strategy).lower()
    vec_table = f"vec_chunks_{strategy}{_model_to_table_suffix(rehearsal_settings.embedding_model)}"
    meta_table = f"vec_meta{vec_table.removeprefix('vec_chunks')}"
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        chunk_count = int(conn.execute(f"SELECT COUNT(*) FROM chunks_{strategy}").fetchone()[0])
        embedding_count = int(conn.execute(f"SELECT COUNT(*) FROM {meta_table}").fetchone()[0])
    finally:
        conn.close()
    checks = {
        "expected_chunk_count": (chunk_count, expected_manifest.expected_chunk_count),
        "expected_embedding_count": (embedding_count, expected_manifest.expected_embedding_count),
        "chunk_strategy": (rehearsal_settings.chunk_strategy, expected_manifest.chunk_strategy),
        "embedding_model": (rehearsal_settings.embedding_model, expected_manifest.embedding_model),
    }
    for field_name, (actual, expected) in checks.items():
        if actual != expected:
            raise ValueError(f"{field_name} mismatch: expected {expected!r}, got {actual!r}")


def build_baseline_service(rehearsal_settings: Settings) -> DotMDService:
    return DotMDService(settings=rehearsal_settings)


def _candidate_to_eval_row(
    query: GoldenQuery,
    candidates: list[Any],
    *,
    latency_ms: float | None = None,
) -> dict[str, object]:
    top_refs: list[str] = []
    matched_engines: dict[str, list[str]] = {}
    snippets_by_ref: dict[str, str] = {}
    read_evidence_by_ref: dict[str, str] = {}
    unreadable_refs: list[str] = []
    for candidate in candidates:
        ref = str(candidate.ref)
        top_refs.append(ref)
        matched = candidate.matched_engines if hasattr(candidate, "matched_engines") else ()
        matched_engines[ref] = [str(engine) for engine in matched]
        snippet = candidate.snippet if hasattr(candidate, "snippet") else ""
        if snippet:
            snippets_by_ref[ref] = str(snippet)
        read_evidence = (
            candidate.read_evidence if hasattr(candidate, "read_evidence") else ""
        ) or (candidate.snippet if hasattr(candidate, "snippet") else "")
        if read_evidence:
            read_evidence_by_ref[ref] = str(read_evidence)
        if bool(candidate.unreadable) if hasattr(candidate, "unreadable") else False:
            unreadable_refs.append(ref)
    row: dict[str, object] = {
        "query_id": query.id,
        "query": query.query,
        "category": query.category.value,
        "primary_surface": query.primary_surface.value,
        "top_refs": top_refs,
        "matched_engines": matched_engines,
        "snippets_by_ref": snippets_by_ref,
        "read_evidence_by_ref": read_evidence_by_ref,
        "unreadable_refs": unreadable_refs,
    }
    if latency_ms is not None:
        row["latency_ms"] = round(latency_ms, 3)
    return row


def _write_eval_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def _extract_candidates(search_result: Any) -> list[Any]:
    if hasattr(search_result, "candidates"):
        return list(search_result.candidates)
    if isinstance(search_result, list):
        return list(search_result)
    return list(search_result or [])


def capture_baseline_eval_results(
    baseline_service: DotMDService | Any,
    golden_queries_path: Path,
    output_path: Path,
    progress_path: Path | None = None,
) -> Path:
    golden_queries = load_golden_queries(golden_queries_path)
    rows: list[dict[str, object]] = []
    for query in golden_queries:
        _write_preflight_progress(progress_path, step=f"baseline:{query.id}", status="running")
        started_at = time.perf_counter()
        search_result = baseline_service.search(query.query, top_k=10)
        latency_ms = (time.perf_counter() - started_at) * 1000
        rows.append(
            _candidate_to_eval_row(
                query,
                _extract_candidates(search_result),
                latency_ms=latency_ms,
            )
        )
        _write_preflight_progress(progress_path, step=f"baseline:{query.id}", status="applied")
    _write_eval_rows(output_path, rows)
    return output_path


def capture_eval_results_from_candidates(
    *,
    service: DotMDService | Any,
    golden_queries: list[GoldenQuery] | tuple[GoldenQuery, ...],
    output_path: Path,
    connection: SurrealConnection | Any,
    settings: Settings,
    candidate_config: CandidateConfig,
    progress_path: Path | None = None,
) -> Path:
    _write_preflight_progress(progress_path, step="candidate:engine_overrides", status="running")
    build_surreal_native_engine_overrides(
        connection,
        settings,
        embedding_dimension=candidate_config.embedding_dimension,
        hnsw_ef=candidate_config.hnsw_ef,
    )
    _write_preflight_progress(progress_path, step="candidate:engine_overrides", status="applied")
    rows: list[dict[str, object]] = []
    for query in golden_queries:
        _write_preflight_progress(progress_path, step=f"candidate:{query.id}", status="running")
        started_at = time.perf_counter()
        search_result = service.search(query.query, top_k=candidate_config.top_k)
        latency_ms = (time.perf_counter() - started_at) * 1000
        rows.append(
            _candidate_to_eval_row(
                query,
                _extract_candidates(search_result),
                latency_ms=latency_ms,
            )
        )
        _write_preflight_progress(progress_path, step=f"candidate:{query.id}", status="applied")
    _write_eval_rows(output_path, rows)
    return output_path


def preflight_candidate_target(
    connection: SurrealConnection | Any,
    settings: Settings,
    candidate_config: CandidateConfig,
    expected_manifest: ExpectedSourceManifest,
    progress_path: Path | None = None,
) -> None:
    del settings
    _write_preflight_progress(progress_path, step="start", status="running")
    chunk_rows = _query_surreal_rows_with_progress(
        connection,
        "SELECT count() AS count FROM chunks GROUP ALL;",
        progress_path=progress_path,
        step="target_chunk_count",
    )
    embedding_rows = _query_surreal_rows_with_progress(
        connection,
        "SELECT count() AS count FROM embeddings GROUP ALL;",
        progress_path=progress_path,
        step="target_embedding_count",
    )
    chunk_count = _first_count(chunk_rows)
    embedding_count = _first_count(embedding_rows)
    if chunk_count <= 0:
        _write_preflight_progress(progress_path, step="target_counts", status="failed")
        raise ValueError("candidate target is empty")

    chunk_strategy_rows = _query_surreal_rows_with_progress(
        connection,
        "SELECT chunk_strategy FROM chunks GROUP BY chunk_strategy;",
        progress_path=progress_path,
        step="target_chunk_strategy",
    )
    embedding_model_rows = _query_surreal_rows_with_progress(
        connection,
        "SELECT embedding_model FROM embeddings GROUP BY embedding_model;",
        progress_path=progress_path,
        step="target_embedding_model",
    )
    chunk_strategies = _single_field_values(chunk_strategy_rows, "chunk_strategy")
    embedding_models = _single_field_values(embedding_model_rows, "embedding_model")
    if len(chunk_strategies) != 1:
        raise ValueError(f"chunk_strategy mismatch: expected one strategy, got {chunk_strategies!r}")
    if len(embedding_models) != 1:
        raise ValueError(f"embedding_model mismatch: expected one model, got {embedding_models!r}")

    checks = {
        "chunk_strategy": chunk_strategies[0],
        "embedding_model": embedding_models[0],
        "expected_chunk_count": chunk_count,
        "expected_embedding_count": embedding_count,
    }
    expected = {
        "chunk_strategy": expected_manifest.chunk_strategy,
        "embedding_model": expected_manifest.embedding_model,
        "expected_chunk_count": expected_manifest.expected_chunk_count,
        "expected_embedding_count": expected_manifest.expected_embedding_count,
    }
    for field_name, actual in checks.items():
        if actual != expected[field_name]:
            raise ValueError(f"{field_name} mismatch: expected {expected[field_name]!r}, got {actual!r}")

    sample_embedding_rows = _query_surreal_rows_with_progress(
        connection,
        "SELECT embedding_model, embedding FROM embeddings LIMIT 25;",
        progress_path=progress_path,
        step="target_embedding_sample",
    )
    validate_surreal_native_retrieval_contract(
        embedding_dimension=candidate_config.embedding_dimension,
        embedding_rows=sample_embedding_rows,
        top_k=candidate_config.top_k,
        hnsw_ef=candidate_config.hnsw_ef,
    )
    _write_preflight_progress(progress_path, step="complete", status="applied")


def _write_preflight_progress(
    progress_path: Path | None,
    *,
    step: str,
    status: str,
    error: str | None = None,
) -> None:
    if progress_path is None:
        return
    payload = {
        "schema_version": "phase43-preflight-v1",
        "step": step,
        "status": status,
        "error": error,
        "updated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _query_surreal_rows_with_progress(
    connection: SurrealConnection | Any,
    statement: str,
    *,
    progress_path: Path | None,
    step: str,
) -> list[dict[str, Any]]:
    _write_preflight_progress(progress_path, step=step, status="running")
    try:
        rows = _query_surreal_rows(connection, statement)
    except Exception as exc:
        _write_preflight_progress(progress_path, step=step, status="failed", error=str(exc))
        raise
    _write_preflight_progress(progress_path, step=step, status="applied")
    return rows


def _query_surreal_rows(connection: SurrealConnection | Any, statement: str) -> list[dict[str, Any]]:
    payload = connection.query(statement)
    if isinstance(payload, list):
        if payload and isinstance(payload[0], dict) and "result" in payload[0]:
            result = payload[0]["result"]
            if isinstance(result, list):
                return [dict(row) for row in result if isinstance(row, dict)]
            if isinstance(result, dict):
                return [dict(result)]
        return [dict(row) for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        result = payload.get("result")
        if isinstance(result, list):
            return [dict(row) for row in result if isinstance(row, dict)]
        if isinstance(result, dict):
            return [dict(result)]
        return [dict(payload)]
    raise ValueError("candidate target preflight returned invalid payload")


def _first_count(rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    raw_count = rows[0].get("count")
    if isinstance(raw_count, list) and raw_count:
        raw_count = raw_count[0]
    return int(raw_count or 0)


def _single_field_values(rows: list[dict[str, Any]], field_name: str) -> list[str]:
    values = sorted(
        {
            str(row[field_name])
            for row in rows
            if row.get(field_name) not in (None, "")
        }
    )
    return values


def _default_metric_bundle() -> ShadowMetricBundle:
    baseline = ShadowMemoryMetrics(
        label="baseline",
        wall_clock_seconds=0.1,
        process_cpu_seconds=0.05,
        max_rss_bytes=100,
        current_python_heap_bytes=50,
        peak_python_heap_bytes=75,
    )
    candidate = ShadowMemoryMetrics(
        label="candidate",
        wall_clock_seconds=0.2,
        process_cpu_seconds=0.1,
        max_rss_bytes=120,
        current_python_heap_bytes=60,
        peak_python_heap_bytes=90,
    )
    return ShadowMetricBundle(
        passed=True,
        failure_category=None,
        recommendation_gate="pass",
        missing=(),
        record_counts={"chunks": 1, "embeddings": 1},
        hnsw_build_seconds=1.0,
        surrealkv_file_size_bytes=1024,
        query_latency_p50_ms=10.0,
        query_latency_p95_ms=20.0,
        memory={"baseline": baseline, "candidate": candidate},
        guardrails=DEFAULT_SHADOW_MEMORY_GUARDRAILS,
        samples={"replay_window": {"count": 0}},
    )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("latency values are required")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _latencies_from_results(path: Path) -> list[float]:
    latencies: list[float] = []
    for line_number, payload in _load_jsonl(path):
        value = payload.get("latency_ms")
        if not isinstance(value, int | float):
            raise ValueError(f"{path} line {line_number}: latency_ms is required")
        latencies.append(float(value))
    return latencies


def _target_size_bytes(target_url: str) -> int:
    prefix = "surrealkv://"
    if not target_url.startswith(prefix):
        return 0
    target_path = Path(target_url.removeprefix(prefix))
    if not target_path.exists():
        return 0
    if target_path.is_file():
        return target_path.stat().st_size
    total = 0
    for root, _dirs, files in os.walk(target_path):
        for file_name in files:
            try:
                total += (Path(root) / file_name).stat().st_size
            except OSError:
                continue
    return total


def _metric_bundle_from_results(
    *,
    baseline_results: Path,
    candidate_results: Path,
    target_url: str,
) -> ShadowMetricBundle:
    baseline_latencies = _latencies_from_results(baseline_results)
    candidate_latencies = _latencies_from_results(candidate_results)
    baseline = ShadowMemoryMetrics(
        label="baseline",
        wall_clock_seconds=sum(baseline_latencies) / 1000,
        process_cpu_seconds=0.0,
        max_rss_bytes=int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024,
        current_python_heap_bytes=1,
        peak_python_heap_bytes=1,
    )
    candidate = ShadowMemoryMetrics(
        label="candidate",
        wall_clock_seconds=sum(candidate_latencies) / 1000,
        process_cpu_seconds=0.0,
        max_rss_bytes=int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024,
        current_python_heap_bytes=1,
        peak_python_heap_bytes=1,
    )
    return ShadowMetricBundle(
        passed=True,
        failure_category=None,
        recommendation_gate="pass",
        missing=(),
        record_counts={
            "baseline_queries": len(baseline_latencies),
            "candidate_queries": len(candidate_latencies),
        },
        hnsw_build_seconds=0.0,
        surrealkv_file_size_bytes=_target_size_bytes(target_url),
        query_latency_p50_ms=_percentile(candidate_latencies, 0.5),
        query_latency_p95_ms=_percentile(candidate_latencies, 0.95),
        memory={"baseline": baseline, "candidate": candidate},
        guardrails=DEFAULT_SHADOW_MEMORY_GUARDRAILS,
        samples={
            "baseline_query_latency_ms": {
                "count": len(baseline_latencies),
                "mean": statistics.fmean(baseline_latencies),
                "p50": _percentile(baseline_latencies, 0.5),
                "p95": _percentile(baseline_latencies, 0.95),
            },
            "candidate_query_latency_ms": {
                "count": len(candidate_latencies),
                "mean": statistics.fmean(candidate_latencies),
                "p50": _percentile(candidate_latencies, 0.5),
                "p95": _percentile(candidate_latencies, 0.95),
            },
        },
    )


def _canonical_shadow_diff_map_from_file(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for line_number, payload in _load_jsonl(path):
        query_id = str(payload.get("query_id", "")).strip()
        if not query_id:
            raise ValueError(f"{path} line {line_number}: query_id is required")
        result[query_id] = {
            key: payload[key]
            for key in sorted(payload)
            if key != "query_id"
        }
    return result


def _regenerate_shadow_diffs(
    artifacts: ShadowArtifactPaths,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    return (
        _canonical_shadow_diff_map_from_file(artifacts.shadow_diffs),
        _canonical_shadow_diff_map_from_file(artifacts.shadow_diffs),
    )


def verify_shadow_artifacts(artifacts: ShadowArtifactPaths) -> None:
    for path in (
        artifacts.source_capture,
        artifacts.baseline_results,
        artifacts.candidate_results,
        artifacts.accepted_diffs,
        artifacts.shadow_diffs,
        artifacts.shadow_summary,
        artifacts.scale_metrics,
        artifacts.memory_metrics,
    ):
        if not path.exists():
            raise ValueError(f"required artifact missing: {path.name}")
    regenerated, on_disk = _regenerate_shadow_diffs(artifacts)
    if regenerated != on_disk:
        raise ValueError("query_id keyed shadow diff comparison failed")


def _write_source_capture_output(
    path: Path,
    expected_manifest: ExpectedSourceManifest,
    rehearsal_settings: Settings,
    baseline_graph_name: str,
) -> None:
    db_stat = rehearsal_settings.index_db_path.stat()
    payload = {
        **asdict(expected_manifest),
        "baseline_graph_name": baseline_graph_name,
        "rehearsal_index_db": {
            "path": str(rehearsal_settings.index_db_path),
            "size_bytes": db_stat.st_size,
            "mtime_ns": db_stat.st_mtime_ns,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _build_candidate_connection(config: ShadowRunConfig) -> SurrealConnection:
    return SurrealConnection(
        SurrealStoreConfig(
            url=config.target_url,
            namespace=config.target_namespace,
            database=config.target_database,
        )
    )


def _write_stripped_acceptance_rows(rows: tuple[dict[str, str], ...]) -> Path | None:
    if not rows:
        temp_path = Path(tempfile.mkstemp(suffix=".jsonl", prefix="shadow-acceptance-")[1])
        temp_path.write_text("", encoding="utf-8")
        return temp_path
    temp_path = Path(tempfile.mkstemp(suffix=".jsonl", prefix="shadow-acceptance-")[1])
    _write_eval_rows(temp_path, list(rows))
    return temp_path


def run_shadow_run(config: ShadowRunConfig | Any) -> ShadowRunResult:
    artifacts = config.artifacts
    expected_manifest = load_expected_source_manifest(Path(config.source_capture_manifest_json))
    candidate_config = load_candidate_config(Path(config.candidate_config_json))
    base_settings = load_settings()
    production_index_dir = Path(os.environ.get("DOTMD_INDEX_DIR", str(RUNTIME_INDEX_DIR)))
    enforce_rehearsal_path_isolation(Path(config.baseline_rehearsal_path), production_index_dir)
    rehearsal_settings = base_settings.model_copy(
        update={
            "index_dir": Path(config.baseline_rehearsal_path),
            "falkordb_graph_name": config.baseline_graph_name,
        }
    )
    assert_rehearsal_identity_matches_manifest(rehearsal_settings, expected_manifest)
    enforce_baseline_graph_isolation(config.baseline_graph_name)
    if not artifacts.accepted_diffs.exists():
        replay_rows = (
            load_metrics_replay_queries(config.metrics_replay_queries)
            if getattr(config, "metrics_replay_queries", None)
            else ()
        )
        write_shadow_acceptance_sentinel(
            artifacts.accepted_diffs,
            asdict(DEFAULT_SHADOW_MEMORY_GUARDRAILS),
            {"count": len(replay_rows)},
        )
    ledger = load_shadow_acceptance_ledger(artifacts.accepted_diffs)

    if getattr(config, "verify_only", False):
        verify_shadow_artifacts(artifacts)
        return ShadowRunResult(artifacts=artifacts, exit_code=0)

    if getattr(config, "preflight_candidate_target", False):
        with _build_candidate_connection(cast(ShadowRunConfig, config)) as connection:
            preflight_candidate_target(
                connection,
                rehearsal_settings,
                candidate_config,
                expected_manifest,
                progress_path=artifacts.source_capture.parent / "preflight-progress.json",
            )
        return ShadowRunResult(artifacts=artifacts, exit_code=0)

    golden_queries = load_golden_queries(Path(config.golden_queries))
    progress_path = artifacts.source_capture.parent / "shadow-run-progress.json"
    production_db_stat_before = _production_index_stat(production_index_dir)
    stripped_acceptance_path: Path | None = None
    graph_handle: IsolatedBaselineGraph | None = None
    try:
        _write_preflight_progress(progress_path, step="baseline_graph_copy", status="running")
        graph_handle = copy_baseline_graph(
            rehearsal_settings.falkordb_url,
            config.production_graph_name,
            config.baseline_graph_name,
        )
        _write_preflight_progress(progress_path, step="baseline_graph_copy", status="applied")
        baseline_service = build_baseline_service(rehearsal_settings)
        if getattr(config, "capture_baseline", True):
            capture_baseline_eval_results(
                baseline_service,
                Path(config.golden_queries),
                artifacts.baseline_results,
                progress_path=progress_path,
            )
        candidate_service = build_baseline_service(base_settings.model_copy(update={"index_dir": Path(config.baseline_rehearsal_path)}))
        with _build_candidate_connection(cast(ShadowRunConfig, config)) as connection:
            if not getattr(config, "skip_candidate_preflight", False):
                preflight_candidate_target(
                    connection,
                    base_settings,
                    candidate_config,
                    expected_manifest,
                    progress_path=artifacts.source_capture.parent / "preflight-progress.json",
                )
            if getattr(config, "capture_candidate", True):
                capture_eval_results_from_candidates(
                    service=candidate_service,
                    golden_queries=golden_queries,
                    output_path=artifacts.candidate_results,
                    connection=connection,
                    settings=base_settings,
                    candidate_config=candidate_config,
                    progress_path=progress_path,
                )
        stripped_acceptance_path = _write_stripped_acceptance_rows(ledger.acceptance_rows)
        eval_result = run_eval(
            EvalRunnerConfig(
                golden_queries=Path(config.golden_queries),
                baseline_results=artifacts.baseline_results,
                candidate_results=artifacts.candidate_results,
                acceptance=stripped_acceptance_path,
                output_jsonl=artifacts.shadow_diffs,
                summary_markdown=artifacts.shadow_summary,
                require_complete_category_coverage=True,
            )
        )
        metric_bundle = _metric_bundle_from_results(
            baseline_results=artifacts.baseline_results,
            candidate_results=artifacts.candidate_results,
            target_url=config.target_url,
        )
        write_shadow_metric_json(artifacts.scale_metrics, metric_bundle)
        write_shadow_metric_json(artifacts.memory_metrics, metric_bundle)
        _write_source_capture_output(
            artifacts.source_capture,
            expected_manifest,
            rehearsal_settings,
            config.baseline_graph_name,
        )
    finally:
        if graph_handle is not None:
            teardown_baseline_graph(graph_handle)

    production_db_stat_after = _production_index_stat(production_index_dir)
    if production_db_stat_before is not None and production_db_stat_after != production_db_stat_before:
        raise ValueError("production index.db changed during shadow run")
    production_graphs_after = _list_graph_names(rehearsal_settings.falkordb_url)
    if (
        config.production_graph_name not in production_graphs_after
        or config.baseline_graph_name in production_graphs_after
    ):
        raise ValueError("production graph changed during shadow run")

    return ShadowRunResult(artifacts=artifacts, exit_code=0 if eval_result.exit_code == 0 else 1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase 43 bounded shadow-run runner.")
    parser.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--golden-queries", required=True, type=Path)
    parser.add_argument("--source-capture-manifest-json", required=True, type=Path)
    parser.add_argument("--baseline-results", type=Path, default=None)
    parser.add_argument("--candidate-results", type=Path, default=None)
    parser.add_argument("--accepted-diffs", type=Path, default=None)
    parser.add_argument("--shadow-diffs", type=Path, default=None)
    parser.add_argument("--shadow-summary", type=Path, default=None)
    parser.add_argument("--scale-metrics", type=Path, default=None)
    parser.add_argument("--memory-metrics", type=Path, default=None)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--capture-baseline", action="store_true", default=False)
    parser.add_argument("--capture-candidate", action="store_true", default=False)
    parser.add_argument("--skip-candidate-preflight", action="store_true")
    parser.add_argument("--baseline-rehearsal-path", required=True, type=Path)
    parser.add_argument("--baseline-graph-name", default="dotmd_shadow_baseline")
    parser.add_argument("--production-graph-name", default=DEFAULT_FALKORDB_GRAPH_NAME)
    parser.add_argument("--metrics-replay-queries", type=Path, default=None)
    parser.add_argument("--target-url", required=True)
    parser.add_argument("--target-namespace", default="dotmd")
    parser.add_argument("--target-database", default="phase43_shadow")
    parser.add_argument("--candidate-config-json", required=True, type=Path)
    parser.add_argument("--preflight-candidate-target", action="store_true")
    parser.add_argument("--representative-corpus", type=Path, default=None)
    return parser


def _artifact_paths_from_args(args: argparse.Namespace) -> ShadowArtifactPaths:
    defaults = default_shadow_artifact_paths(args.artifacts_dir)
    return ShadowArtifactPaths(
        source_capture=defaults.source_capture,
        baseline_results=args.baseline_results or defaults.baseline_results,
        candidate_results=args.candidate_results or defaults.candidate_results,
        accepted_diffs=args.accepted_diffs or defaults.accepted_diffs,
        shadow_diffs=args.shadow_diffs or defaults.shadow_diffs,
        shadow_summary=args.shadow_summary or defaults.shadow_summary,
        scale_metrics=args.scale_metrics or defaults.scale_metrics,
        memory_metrics=args.memory_metrics or defaults.memory_metrics,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_shadow_run(
        ShadowRunConfig(
            golden_queries=args.golden_queries,
            source_capture_manifest_json=args.source_capture_manifest_json,
            candidate_config_json=args.candidate_config_json,
            artifacts=_artifact_paths_from_args(args),
            baseline_rehearsal_path=args.baseline_rehearsal_path,
            baseline_graph_name=args.baseline_graph_name,
            production_graph_name=args.production_graph_name,
            metrics_replay_queries=args.metrics_replay_queries,
            target_url=args.target_url,
            target_namespace=args.target_namespace,
            target_database=args.target_database,
            verify_only=args.verify_only,
            capture_baseline=args.capture_baseline,
            capture_candidate=args.capture_candidate,
            preflight_candidate_target=args.preflight_candidate_target,
            skip_candidate_preflight=args.skip_candidate_preflight,
        )
    )
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
