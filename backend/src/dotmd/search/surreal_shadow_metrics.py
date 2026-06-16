"""Shadow-run metric helpers for Phase 43 evidence capture."""

from __future__ import annotations

import json
import resource
import time
import tracemalloc
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True, frozen=True)
class ShadowMemoryMetrics:
    """Observed process and Python-heap metrics for one measured capture."""

    label: str
    wall_clock_seconds: float
    process_cpu_seconds: float
    max_rss_bytes: int
    current_python_heap_bytes: int
    peak_python_heap_bytes: int


@dataclass(slots=True, frozen=True)
class ShadowMemoryGuardrails:
    """Phase 43 evidence tolerances, not production memory budgets.

    Default ratios of ``1.25`` allow the Surreal candidate to consume up to 25%
    more peak RSS or Python heap than the baseline during the same replay window
    before the ratio gate trips. The 256 MiB RSS slack and 128 MiB Python-heap
    slack keep small bounded runs from failing on allocator/runtime noise when a
    ratio alone would over-trigger. These are first-cut shadow-run tolerances and
    can be re-tuned in a later cutover phase.
    """

    candidate_rss_growth_ratio: float
    rss_slack_bytes: int
    candidate_python_heap_growth_ratio: float
    python_heap_slack_bytes: int


DEFAULT_SHADOW_MEMORY_GUARDRAILS = ShadowMemoryGuardrails(
    candidate_rss_growth_ratio=1.25,
    rss_slack_bytes=268_435_456,
    candidate_python_heap_growth_ratio=1.25,
    python_heap_slack_bytes=134_217_728,
)


@dataclass(slots=True, frozen=True)
class ShadowMetricBundle:
    """Scale-gate fields plus paired memory evidence for a shadow run."""

    passed: bool | None
    failure_category: str | None
    recommendation_gate: str | None
    missing: tuple[str, ...] | list[str] | None
    record_counts: Mapping[str, int] | None
    hnsw_build_seconds: float | None
    surrealkv_file_size_bytes: int | None
    query_latency_p50_ms: float | None
    query_latency_p95_ms: float | None
    memory: Mapping[str, object] | None
    guardrails: ShadowMemoryGuardrails | Mapping[str, object] | None
    samples: Mapping[str, object] | None = None


def capture_shadow_memory_metrics[T](
    label: str,
    callable_: Callable[[], T],
) -> tuple[T, ShadowMemoryMetrics]:
    """Run ``callable_`` and capture wall-clock, CPU, RSS, and heap metrics.

    Linux-only note: this uses ``resource.getrusage(resource.RUSAGE_SELF)``,
    whose semantics and supported ``who`` values are platform-dependent. dotMD
    runs in a Linux container, so this helper intentionally does not include a
    fallback branch for other platforms.
    """

    tracemalloc.start()
    wall_start = time.perf_counter()
    cpu_start = time.process_time()
    try:
        result = callable_()
        current_heap, peak_heap = tracemalloc.get_traced_memory()
    finally:
        wall_end = time.perf_counter()
        cpu_end = time.process_time()
        usage = resource.getrusage(resource.RUSAGE_SELF)
        tracemalloc.stop()
    metrics = ShadowMemoryMetrics(
        label=label,
        wall_clock_seconds=wall_end - wall_start,
        process_cpu_seconds=cpu_end - cpu_start,
        max_rss_bytes=int(usage.ru_maxrss) * 1024,
        current_python_heap_bytes=int(current_heap),
        peak_python_heap_bytes=int(peak_heap),
    )
    return result, metrics


def _evaluate_metric_guardrail(
    *,
    metric_name: str,
    baseline_value: int,
    candidate_value: int,
    ratio_threshold: float,
    slack_bytes: int,
) -> dict[str, object]:
    if baseline_value <= 0:
        raise ValueError(f"baseline.{metric_name} must be > 0 for ratio evaluation")

    ratio = candidate_value / baseline_value
    delta_bytes = candidate_value - baseline_value
    passed = ratio <= ratio_threshold or delta_bytes <= slack_bytes
    return {
        "passed": passed,
        "ratio": ratio,
        "ratio_threshold": ratio_threshold,
        "delta_bytes": delta_bytes,
        "slack_bytes": slack_bytes,
    }


def evaluate_shadow_memory_guardrails(
    baseline: ShadowMemoryMetrics,
    candidate: ShadowMemoryMetrics,
    guardrails: ShadowMemoryGuardrails,
) -> dict[str, object]:
    """Compare candidate memory evidence against the baseline with slack fallbacks."""

    rss = _evaluate_metric_guardrail(
        metric_name="max_rss_bytes",
        baseline_value=baseline.max_rss_bytes,
        candidate_value=candidate.max_rss_bytes,
        ratio_threshold=guardrails.candidate_rss_growth_ratio,
        slack_bytes=guardrails.rss_slack_bytes,
    )
    python_heap = _evaluate_metric_guardrail(
        metric_name="peak_python_heap_bytes",
        baseline_value=baseline.peak_python_heap_bytes,
        candidate_value=candidate.peak_python_heap_bytes,
        ratio_threshold=guardrails.candidate_python_heap_growth_ratio,
        slack_bytes=guardrails.python_heap_slack_bytes,
    )
    return {
        "passed": bool(rss["passed"]) and bool(python_heap["passed"]),
        "rss": rss,
        "python_heap": python_heap,
    }


def _normalize_memory_metrics(
    value: object,
    *,
    field_name: str,
) -> ShadowMemoryMetrics:
    if isinstance(value, ShadowMemoryMetrics):
        metrics = value
    elif isinstance(value, Mapping):
        metrics = ShadowMemoryMetrics(
            label=_required_field(value, "label", parent=field_name, expected_type=str),
            wall_clock_seconds=float(
                _required_field(
                    value,
                    "wall_clock_seconds",
                    parent=field_name,
                    expected_type=(int, float),
                )
            ),
            process_cpu_seconds=float(
                _required_field(
                    value,
                    "process_cpu_seconds",
                    parent=field_name,
                    expected_type=(int, float),
                )
            ),
            max_rss_bytes=int(
                _required_field(
                    value,
                    "max_rss_bytes",
                    parent=field_name,
                    expected_type=int,
                )
            ),
            current_python_heap_bytes=int(
                _required_field(
                    value,
                    "current_python_heap_bytes",
                    parent=field_name,
                    expected_type=int,
                )
            ),
            peak_python_heap_bytes=int(
                _required_field(
                    value,
                    "peak_python_heap_bytes",
                    parent=field_name,
                    expected_type=int,
                )
            ),
        )
    else:
        raise ValueError(f"{field_name} is required")
    return metrics


def _normalize_guardrails(value: object) -> ShadowMemoryGuardrails:
    if isinstance(value, ShadowMemoryGuardrails):
        return value
    if isinstance(value, Mapping):
        return ShadowMemoryGuardrails(
            candidate_rss_growth_ratio=float(
                _required_field(
                    value,
                    "candidate_rss_growth_ratio",
                    parent="guardrails",
                    expected_type=(int, float),
                )
            ),
            rss_slack_bytes=int(
                _required_field(
                    value,
                    "rss_slack_bytes",
                    parent="guardrails",
                    expected_type=int,
                )
            ),
            candidate_python_heap_growth_ratio=float(
                _required_field(
                    value,
                    "candidate_python_heap_growth_ratio",
                    parent="guardrails",
                    expected_type=(int, float),
                )
            ),
            python_heap_slack_bytes=int(
                _required_field(
                    value,
                    "python_heap_slack_bytes",
                    parent="guardrails",
                    expected_type=int,
                )
            ),
        )
    raise ValueError("guardrails is required")


def _required_field(
    mapping: Mapping[str, object],
    key: str,
    *,
    parent: str | None = None,
    expected_type: type[Any] | tuple[type[Any], ...] | None = None,
) -> object:
    field_name = f"{parent}.{key}" if parent else key
    if key not in mapping or mapping[key] is None:
        raise ValueError(f"{field_name} is required")
    value = mapping[key]
    if expected_type is not None and not isinstance(value, expected_type):
        raise ValueError(f"{field_name} is required")
    return value


def validate_shadow_metric_bundle(bundle: ShadowMetricBundle) -> dict[str, object]:
    """Validate a complete metric bundle and return a JSON-ready payload."""

    payload = asdict(bundle)
    required_scalars = (
        "passed",
        "recommendation_gate",
        "missing",
        "record_counts",
        "hnsw_build_seconds",
        "surrealkv_file_size_bytes",
        "query_latency_p50_ms",
        "query_latency_p95_ms",
        "memory",
        "guardrails",
    )
    for key in required_scalars:
        if payload.get(key) is None:
            raise ValueError(f"{key} is required")

    raw_memory = bundle.memory
    if raw_memory is None or not isinstance(raw_memory, Mapping):
        raise ValueError("memory is required")

    baseline = _normalize_memory_metrics(
        raw_memory.get("baseline"),
        field_name="memory.baseline",
    )
    candidate = _normalize_memory_metrics(
        raw_memory.get("candidate"),
        field_name="memory.candidate",
    )
    guardrails = _normalize_guardrails(bundle.guardrails)
    memory_guardrails = evaluate_shadow_memory_guardrails(baseline, candidate, guardrails)

    return {
        "passed": bool(bundle.passed),
        "failure_category": bundle.failure_category,
        "recommendation_gate": bundle.recommendation_gate,
        "missing": list(bundle.missing or ()),
        "record_counts": dict(bundle.record_counts or {}),
        "hnsw_build_seconds": float(bundle.hnsw_build_seconds),
        "surrealkv_file_size_bytes": int(bundle.surrealkv_file_size_bytes),
        "query_latency_p50_ms": float(bundle.query_latency_p50_ms),
        "query_latency_p95_ms": float(bundle.query_latency_p95_ms),
        "memory": {
            "baseline": asdict(baseline),
            "candidate": asdict(candidate),
        },
        "guardrails": asdict(guardrails),
        "memory_guardrails": memory_guardrails,
        "samples": dict(bundle.samples or {}),
    }


def write_shadow_metric_json(path: str | Path, payload: Mapping[str, object]) -> None:
    """Write deterministic UTF-8 JSON for shadow-run evidence artifacts."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "DEFAULT_SHADOW_MEMORY_GUARDRAILS",
    "ShadowMemoryGuardrails",
    "ShadowMemoryMetrics",
    "ShadowMetricBundle",
    "capture_shadow_memory_metrics",
    "evaluate_shadow_memory_guardrails",
    "validate_shadow_metric_bundle",
    "write_shadow_metric_json",
]
