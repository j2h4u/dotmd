"""Shadow metric contract tests for the Phase 43 shadow runner."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest


def _module() -> Any:
    from dotmd.search import surreal_shadow_metrics

    return surreal_shadow_metrics


def _make_memory_metrics(
    *,
    label: str = "baseline",
    wall_clock_seconds: float = 1.5,
    process_cpu_seconds: float = 0.75,
    max_rss_bytes: int = 1_073_741_824,
    current_python_heap_bytes: int = 524_288,
    peak_python_heap_bytes: int = 1_048_576,
) -> Any:
    module = _module()
    return module.ShadowMemoryMetrics(
        label=label,
        wall_clock_seconds=wall_clock_seconds,
        process_cpu_seconds=process_cpu_seconds,
        max_rss_bytes=max_rss_bytes,
        current_python_heap_bytes=current_python_heap_bytes,
        peak_python_heap_bytes=peak_python_heap_bytes,
    )


def _make_guardrails() -> Any:
    module = _module()
    return module.DEFAULT_SHADOW_MEMORY_GUARDRAILS


def _make_bundle(
    *,
    baseline: Any | None = None,
    candidate: Any | None = None,
    guardrails: Any | None = None,
    overrides: dict[str, object] | None = None,
) -> Any:
    module = _module()
    payload: dict[str, object] = {
        "passed": True,
        "failure_category": None,
        "recommendation_gate": "pass",
        "missing": (),
        "record_counts": {"chunks": 149_739, "embeddings": 149_739},
        "hnsw_build_seconds": 12.5,
        "surrealkv_file_size_bytes": 987_654_321,
        "query_latency_p50_ms": 4.2,
        "query_latency_p95_ms": 9.9,
        "memory": {
            "baseline": baseline or _make_memory_metrics(label="baseline"),
            "candidate": candidate or _make_memory_metrics(
                label="candidate",
                max_rss_bytes=1_127_432_192,
                current_python_heap_bytes=786_432,
                peak_python_heap_bytes=1_310_720,
            ),
        },
        "guardrails": guardrails or _make_guardrails(),
        "samples": {
            "ref": "filesystem:/mnt/заметки/договорённости.md",
            "title": "Договорённости по shadow-run",
        },
    }
    if overrides:
        payload.update(overrides)
    return module.ShadowMetricBundle(**payload)


def test_shadow_memory_metrics_serializes_explicit_numeric_fields() -> None:
    metrics = _make_memory_metrics(label="candidate")

    assert asdict(metrics) == {
        "label": "candidate",
        "wall_clock_seconds": 1.5,
        "process_cpu_seconds": 0.75,
        "max_rss_bytes": 1_073_741_824,
        "current_python_heap_bytes": 524_288,
        "peak_python_heap_bytes": 1_048_576,
    }


def test_shadow_memory_guardrails_serialize_expected_defaults() -> None:
    guardrails = _make_guardrails()

    assert asdict(guardrails) == {
        "candidate_rss_growth_ratio": 1.25,
        "rss_slack_bytes": 268_435_456,
        "candidate_python_heap_growth_ratio": 1.25,
        "python_heap_slack_bytes": 134_217_728,
    }


def test_guardrails_pass_under_ratio() -> None:
    module = _module()

    result = module.evaluate_shadow_memory_guardrails(
        _make_memory_metrics(
            label="baseline",
            max_rss_bytes=1_000,
            peak_python_heap_bytes=1_000,
        ),
        _make_memory_metrics(
            label="candidate",
            max_rss_bytes=1_200,
            peak_python_heap_bytes=1_240,
        ),
        _make_guardrails(),
    )

    assert result["passed"] is True
    assert result["rss"]["passed"] is True
    assert result["rss"]["ratio"] == pytest.approx(1.2)
    assert result["python_heap"]["passed"] is True
    assert result["python_heap"]["ratio"] == pytest.approx(1.24)


def test_guardrails_pass_via_slack_when_ratio_exceeded() -> None:
    module = _module()

    result = module.evaluate_shadow_memory_guardrails(
        _make_memory_metrics(
            label="baseline",
            max_rss_bytes=1_000,
            peak_python_heap_bytes=1_000,
        ),
        _make_memory_metrics(
            label="candidate",
            max_rss_bytes=2_000,
            peak_python_heap_bytes=2_000,
        ),
        _make_guardrails(),
    )

    assert result["passed"] is True
    assert result["rss"]["ratio"] > 1.25
    assert result["rss"]["delta_bytes"] <= 268_435_456
    assert result["rss"]["passed"] is True
    assert result["python_heap"]["ratio"] > 1.25
    assert result["python_heap"]["delta_bytes"] <= 134_217_728
    assert result["python_heap"]["passed"] is True


def test_guardrails_fail_when_ratio_and_slack_exceeded() -> None:
    module = _module()

    result = module.evaluate_shadow_memory_guardrails(
        _make_memory_metrics(
            label="baseline",
            max_rss_bytes=10_000_000_000,
            peak_python_heap_bytes=5_000_000_000,
        ),
        _make_memory_metrics(
            label="candidate",
            max_rss_bytes=13_000_000_000,
            peak_python_heap_bytes=7_000_000_000,
        ),
        _make_guardrails(),
    )

    assert result["passed"] is False
    assert result["rss"]["passed"] is False
    assert result["rss"]["ratio"] > 1.25
    assert result["rss"]["delta_bytes"] > 268_435_456
    assert result["python_heap"]["passed"] is False
    assert result["python_heap"]["ratio"] > 1.25
    assert result["python_heap"]["delta_bytes"] > 134_217_728


def test_validation_rejects_unpaired_memory_payload() -> None:
    module = _module()
    bundle = _make_bundle(
        candidate=_make_memory_metrics(label="candidate"),
        overrides={"memory": {"baseline": None, "candidate": _make_memory_metrics(label="candidate")}},
    )

    with pytest.raises(ValueError, match="memory\\.baseline"):
        module.validate_shadow_metric_bundle(bundle)


@pytest.mark.parametrize(
    ("field_name", "baseline_kwargs"),
    [
        (
            "baseline.max_rss_bytes",
            {"label": "baseline", "max_rss_bytes": 0},
        ),
        (
            "baseline.peak_python_heap_bytes",
            {"label": "baseline", "peak_python_heap_bytes": -1},
        ),
    ],
)
def test_guardrails_reject_zero_baseline_field(
    field_name: str,
    baseline_kwargs: dict[str, object],
) -> None:
    module = _module()

    with pytest.raises(ValueError, match=field_name):
        module.evaluate_shadow_memory_guardrails(
            _make_memory_metrics(**baseline_kwargs),
            _make_memory_metrics(label="candidate"),
            _make_guardrails(),
        )


@pytest.mark.parametrize(
    ("override_key", "override_value", "match"),
    [
        ("passed", None, "passed"),
        ("surrealkv_file_size_bytes", None, "surrealkv_file_size_bytes"),
        ("query_latency_p95_ms", None, "query_latency_p95_ms"),
        ("record_counts", None, "record_counts"),
        ("guardrails", None, "guardrails"),
    ],
)
def test_validation_rejects_missing_required_fields(
    override_key: str,
    override_value: object,
    match: str,
) -> None:
    module = _module()
    bundle = _make_bundle(overrides={override_key: override_value})

    with pytest.raises(ValueError, match=match):
        module.validate_shadow_metric_bundle(bundle)


def test_validation_allows_missing_hnsw_build_time_only_as_failed_scale_evidence() -> None:
    module = _module()
    bundle = _make_bundle(
        overrides={
            "passed": False,
            "failure_category": "fail: unavailable scale evidence",
            "recommendation_gate": "fail",
            "missing": ("HNSW build time",),
            "hnsw_build_seconds": None,
        }
    )

    payload = module.validate_shadow_metric_bundle(bundle)

    assert payload["passed"] is False
    assert payload["recommendation_gate"] == "fail"
    assert payload["missing"] == ["HNSW build time"]
    assert payload["hnsw_build_seconds"] is None


def test_capture_starts_tracemalloc_so_heap_is_nonzero() -> None:
    module = _module()

    def _allocate() -> list[str]:
        return ["shadow-run"] * 10_000

    result, metrics = module.capture_shadow_memory_metrics("candidate", _allocate)

    assert len(result) == 10_000
    assert metrics.label == "candidate"
    assert metrics.peak_python_heap_bytes > 0
    assert metrics.wall_clock_seconds >= 0.0
    assert metrics.process_cpu_seconds >= 0.0


def test_validate_shadow_metric_bundle_returns_json_ready_payload() -> None:
    module = _module()
    bundle = _make_bundle()

    payload = module.validate_shadow_metric_bundle(bundle)

    assert payload["passed"] is True
    assert payload["failure_category"] is None
    assert payload["recommendation_gate"] == "pass"
    assert payload["memory"]["baseline"]["label"] == "baseline"
    assert payload["memory"]["candidate"]["label"] == "candidate"
    assert payload["memory_guardrails"]["passed"] is True


def test_write_shadow_metric_json_preserves_utf8_sorted_keys_and_trailing_newline(
    tmp_path: Path,
) -> None:
    module = _module()
    bundle = _make_bundle()
    payload = module.validate_shadow_metric_bundle(bundle)
    output_path = tmp_path / "artifacts" / "shadow-metrics.json"

    module.write_shadow_metric_json(output_path, payload)

    raw = output_path.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert "Договорённости по shadow-run" in raw

    parsed = json.loads(raw)
    assert parsed["samples"]["ref"] == "filesystem:/mnt/заметки/договорённости.md"

    first_lines = raw.splitlines()[:5]
    assert first_lines == sorted(first_lines)
