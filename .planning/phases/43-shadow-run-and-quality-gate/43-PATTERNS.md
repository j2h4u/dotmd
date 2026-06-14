# Phase 43: Shadow run and quality gate - Pattern Map

**Mapped:** 2026-06-14
**Files analyzed:** 10
**Analogs found:** 10 / 10

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/devtools/surreal_shadow_runner.py` | utility | batch | `backend/devtools/surreal_migration_runner.py` | role-match |
| `backend/devtools/surreal_shadow_runner.py` | utility | request-response | `backend/devtools/surreal_eval_runner.py` | role-match |
| `backend/tests/devtools/test_surreal_shadow_runner.py` | test | batch | `backend/tests/devtools/test_surreal_migration_runner.py` | role-match |
| `backend/tests/devtools/test_surreal_shadow_runner.py` | test | request-response | `backend/tests/devtools/test_surreal_eval_runner.py` | role-match |
| `backend/tests/search/test_surreal_shadow_metrics.py` | test | transform | `backend/tests/search/test_surreal_retrieval_parity.py` | role-match |
| `.planning/phases/43-shadow-run-and-quality-gate/artifacts/source-capture.json` | config | file-I/O | Phase 41 `source_capture_manifest` JSON emitted by `backend/devtools/surreal_migration_runner.py` | exact |
| `.planning/phases/43-shadow-run-and-quality-gate/artifacts/baseline-results.jsonl` | config | file-I/O | Phase 40 `EvalResult` JSONL loaded by `backend/src/dotmd/search/surreal_eval.py` | exact |
| `.planning/phases/43-shadow-run-and-quality-gate/artifacts/candidate-results.jsonl` | config | file-I/O | Phase 40 `EvalResult` JSONL loaded by `backend/src/dotmd/search/surreal_eval.py` | exact |
| `.planning/phases/43-shadow-run-and-quality-gate/artifacts/accepted-diffs.jsonl` | config | file-I/O | acceptance JSONL loaded by `backend/devtools/surreal_eval_runner.py`, plus Phase 43 runner metadata sentinel filtering | close |
| `.planning/phases/43-shadow-run-and-quality-gate/artifacts/scale-metrics.json` | config | file-I/O | `evaluate_surreal_scale_gate()` output in `backend/src/dotmd/search/surreal_parity.py` | exact |

## Pattern Assignments

### `backend/devtools/surreal_shadow_runner.py` (utility, batch + request-response)

**Primary analog:** `backend/devtools/surreal_migration_runner.py`
**Secondary analog:** `backend/devtools/surreal_eval_runner.py`
**Support analogs:** `backend/src/dotmd/search/surreal_parity.py`, `backend/src/dotmd/search/surreal_native.py`, `backend/src/dotmd/api/service.py`

**Imports and standalone bootstrap** from [backend/devtools/surreal_eval_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/devtools/surreal_eval_runner.py:14) and [backend/devtools/surreal_migration_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/devtools/surreal_migration_runner.py:16):
```python
from dotmd.search.surreal_eval import (
    DiffAcceptance,
    SurrealEvalDiffRow,
    SurrealEvalSummary,
    classify_difference,
    load_eval_results,
    load_golden_queries,
    summarize_diffs,
    validate_required_category_coverage,
)
```
```python
from dotmd.ingestion.migrate_surreal import (
    SurrealMigrationManifest,
    SurrealMigrationMode,
    SurrealOverwritePolicy,
    SurrealTargetMode,
    SurrealVerificationDepth,
    build_surreal_migration_manifest,
    run_surreal_migration,
    verify_surreal_migration_target,
)
from dotmd.storage.surreal_ops import (
    SurrealImportCounts,
    SurrealMigrationEvidenceReport,
    SurrealRestoreManifest,
    build_surreal_restore_manifest,
    classify_surreal_migration_report,
    write_surreal_migration_evidence_reports,
)
```

**Config dataclass pattern** from [backend/devtools/surreal_eval_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/devtools/surreal_eval_runner.py:26) and [backend/devtools/surreal_migration_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/devtools/surreal_migration_runner.py:36):
```python
@dataclass(slots=True, frozen=True)
class EvalRunnerConfig:
    golden_queries: Path
    baseline_results: Path
    candidate_results: Path
    output_jsonl: Path
    summary_markdown: Path
    acceptance: Path | None = None
```
```python
@dataclass(slots=True, frozen=True)
class SurrealMigrationRunnerConfig:
    mode: str
    target_mode: str
    sqlite_snapshot: Path
    source_capture_manifest_json: Path | None
    graph_export_json: Path
    feedback_export_json: Path
    target_url: str
```

**Fail-closed JSON/file validation** from [backend/devtools/surreal_migration_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/devtools/surreal_migration_runner.py:123) and [backend/devtools/surreal_eval_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/devtools/surreal_eval_runner.py:48):
```python
def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} line {exc.lineno} column {exc.colno}: invalid JSON") from exc
```
```python
with path.open(encoding="utf-8") as handle:
    for line_number, raw_line in enumerate(handle, start=1):
        ...
        raise ValueError(f"{path} line {line_number}: invalid JSON") from exc
```

**Orchestration shape** from [backend/devtools/surreal_migration_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/devtools/surreal_migration_runner.py:367) and [backend/devtools/surreal_eval_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/devtools/surreal_eval_runner.py:151):
```python
manifest = build_surreal_migration_manifest(...)
...
migration_report = run_surreal_migration(...)
restore_manifest = _rehearse_restore(...)
evidence = _build_evidence_report(...)
...
write_surreal_migration_evidence_reports(...)
return SurrealMigrationRunnerResult(..., exit_code=0 if evidence.report_status == "verified" else 1)
```
```python
golden_queries = load_golden_queries(config.golden_queries)
validate_required_category_coverage(golden_queries, path=config.golden_queries)
baseline_results = {row.query_id: row for row in load_eval_results(config.baseline_results)}
candidate_results = {row.query_id: row for row in load_eval_results(config.candidate_results)}
...
summary = summarize_diffs(raw_rows, acceptances=acceptances)
_write_jsonl(config.output_jsonl, summary.rows)
config.summary_markdown.write_text(_build_summary_markdown(summary), encoding="utf-8")
```

**Explicit Surreal candidate wiring** from [backend/src/dotmd/search/surreal_native.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_native.py:18) and [backend/src/dotmd/api/service.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/api/service.py:1339):
```python
overrides = build_surreal_native_engine_overrides(
    connection,
    settings,
    embedding_dimension=embedding_dimension,
)
pool = service._collect_candidate_pool(
    search_query=query,
    original_query=query,
    mode=mode,
    pool_size=pool_size,
    engine_overrides=overrides,
)
```
Use the same override keys only: `semantic`, `keyword`, `graph_direct`, optional `graph`.

**Scale gate payload shape** from [backend/src/dotmd/search/surreal_parity.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_parity.py:435):
```python
return {
    "passed": True,
    "failure_category": None,
    "recommendation_gate": "pass",
    "missing": (),
    "record_counts": dict(record_counts),
    "hnsw_build_seconds": float(hnsw_build_seconds),
    "surrealkv_file_size_bytes": int(surrealkv_file_size_bytes),
    "query_latency_p50_ms": latency_p50,
    "query_latency_p95_ms": latency_p95,
}
```

**Quality diff classification** from [backend/src/dotmd/search/surreal_eval.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_eval.py:430):
```python
if unreadable_approved:
    classification = AcceptedDifference.REGRESSION
elif lost_approved:
    classification = AcceptedDifference.REGRESSION
elif candidate_evidence_failure or baseline_evidence_failure:
    classification = AcceptedDifference.UNCLEAR
elif gained_relevant:
    classification = AcceptedDifference.IMPROVEMENT
elif candidate_matched == baseline_matched and candidate_matched:
    classification = AcceptedDifference.HARMLESS_REORDER
...
cutover_gate=contract.cutover_gate_for(classification)
```

**CLI parser pattern** from [backend/devtools/surreal_migration_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/devtools/surreal_migration_runner.py:474) and [backend/devtools/surreal_eval_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/devtools/surreal_eval_runner.py:189):
```python
parser = argparse.ArgumentParser(description="...")
parser.add_argument("--mode", required=True, choices=(...))
parser.add_argument("--target-mode", required=True, choices=(...))
parser.add_argument("--report-json", type=Path, default=None)
parser.add_argument("--report-markdown", type=Path, default=None)
```
Keep the runner file-oriented and return `0` only when the quality and evidence gate passes.

### `backend/tests/devtools/test_surreal_shadow_runner.py` (test, batch + request-response)

**Analog:** `backend/tests/devtools/test_surreal_migration_runner.py`
**Secondary analog:** `backend/tests/devtools/test_surreal_eval_runner.py`

**Fixture/file helper pattern** from [backend/tests/devtools/test_surreal_eval_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/devtools/test_surreal_eval_runner.py:15) and [backend/tests/devtools/test_surreal_migration_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/devtools/test_surreal_migration_runner.py:27):
```python
def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )
```
```python
def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
```

**End-to-end artifact assertion pattern** from [backend/tests/devtools/test_surreal_eval_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/devtools/test_surreal_eval_runner.py:61):
```python
result = run_eval(EvalRunnerConfig(...))
rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
assert result.exit_code == 0
assert rows[0]["classification"] == AcceptedDifference.HARMLESS_REORDER.value
markdown = summary.read_text(encoding="utf-8")
assert "Accepted semantic changes" in markdown
```

**Safety/fail-closed assertion pattern** from [backend/tests/devtools/test_surreal_migration_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/devtools/test_surreal_migration_runner.py:163) and [backend/tests/devtools/test_surreal_eval_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/devtools/test_surreal_eval_runner.py:253):
```python
with pytest.raises(ValueError, match="gate_report is required for apply mode"):
    run_migration_command(...)
```
```python
with pytest.raises(ValueError, match="golden query corpus missing required categories"):
    run_eval(...)
assert not output.exists()
assert not summary.exists()
```

**Non-ASCII artifact preservation** from [backend/tests/devtools/test_surreal_migration_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/devtools/test_surreal_migration_runner.py:113):
```python
assert "оператор" in payload["target"]["owner_id"]
assert "оператор" in markdown
```

### `backend/tests/search/test_surreal_shadow_metrics.py` (test, transform)

**Analog:** `backend/tests/search/test_surreal_retrieval_parity.py`

**Case-builder and report-shape pattern** from [backend/tests/search/test_surreal_retrieval_parity.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/search/test_surreal_retrieval_parity.py:20):
```python
def _make_case(
    *,
    name: str,
    retrieval_kind: str,
    query: str = "surreal search",
    top_k: int = 10,
    blocking: bool = True,
    metadata: dict[str, object] | None = None,
) -> RetrievalParityCase:
    return RetrievalParityCase(...)
```

**Metric-gate assertions** from [backend/tests/search/test_surreal_retrieval_parity.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/search/test_surreal_retrieval_parity.py:319):
```python
scale_gate = evaluate_surreal_scale_gate(
    record_counts={"chunks": 149_739, "embeddings": 149_739},
    hnsw_build_seconds=None,
    surrealkv_file_size_bytes=None,
    query_latencies_ms=[],
    representative=False,
)
assert scale_gate["passed"] is False
assert scale_gate["recommendation_gate"] == "fail"
```
Copy this style for latency/build/store completeness tests and extend it for separate memory metrics if Phase 43 adds them.

### `.planning/phases/43-shadow-run-and-quality-gate/artifacts/source-capture.json` (config, file-I/O)

**Analog:** `manifest.source_capture_manifest` emitted by [backend/devtools/surreal_migration_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/devtools/surreal_migration_runner.py:408)

**Write pattern:**
```python
config.source_capture_manifest_json.write_text(
    json.dumps(
        asdict(manifest.source_capture_manifest),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
```
Do not invent a new manifest shape for Phase 43.

### `.planning/phases/43-shadow-run-and-quality-gate/artifacts/baseline-results.jsonl` and `candidate-results.jsonl` (config, file-I/O)

**Analog:** `EvalResult` loader in [backend/src/dotmd/search/surreal_eval.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_eval.py:311)

**Required fields pattern:**
```python
EvalResult(
    query_id=query_id,
    query=query,
    category=category,
    primary_surface=primary_surface,
    top_refs=tuple(str(ref) for ref in top_refs),
    matched_engines=matched_engines,
    snippets_by_ref=_parse_str_map(...),
    read_evidence_by_ref=_parse_str_map(...),
    unreadable_refs=frozenset(_parse_str_list(...)),
)
```
Keep both baseline and candidate result files in this exact schema so Phase 40 tooling can consume them directly.

### `.planning/phases/43-shadow-run-and-quality-gate/artifacts/accepted-diffs.jsonl` (config, file-I/O)

**Analog:** `_load_acceptances()` in [backend/devtools/surreal_eval_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/devtools/surreal_eval_runner.py:48)

**Phase 43 sentinel row pattern:**
```json
{"record_type":"phase43_ledger_metadata","quality_corpus":"backend/devtools/surreal_golden_queries.jsonl","metrics_replay_window":"production-derived","memory_guardrails":{"candidate_heap_growth_max_ratio":1.25,"candidate_heap_growth_slack_bytes":134217728,"candidate_rss_growth_max_ratio":1.25,"candidate_rss_growth_slack_bytes":268435456}}
```
The Phase 43 runner must ignore `record_type="phase43_ledger_metadata"` rows before passing real acceptance rows to the Phase 40 loader. This keeps `accepted-diffs.jsonl` non-empty for `test -s` even when there are no semantic acceptances, while preserving strict Phase 40 acceptance semantics for actual query rows.

**Acceptance row pattern:**
```json
{"query_id":"sq-001","accepted_by":"maintainer","accepted_reason":"..."}
```
Validation is strict: unique `query_id`, JSON object per line, both acceptance fields required.

### `.planning/phases/43-shadow-run-and-quality-gate/artifacts/scale-metrics.json` (config, file-I/O)

**Analog:** `evaluate_surreal_scale_gate()` in [backend/src/dotmd/search/surreal_parity.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_parity.py:435)

**Field names to copy exactly:**
```python
{
    "passed": ...,
    "failure_category": ...,
    "recommendation_gate": ...,
    "missing": ...,
    "record_counts": ...,
    "hnsw_build_seconds": ...,
    "surrealkv_file_size_bytes": ...,
    "query_latency_p50_ms": ...,
    "query_latency_p95_ms": ...,
}
```

### `.planning/phases/43-shadow-run-and-quality-gate/artifacts/shadow-diffs.jsonl` and `shadow-summary.md` (config, file-I/O)

**Analog:** output writers in [backend/devtools/surreal_eval_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/devtools/surreal_eval_runner.py:88)

**JSONL and markdown pattern:**
```python
_write_jsonl(config.output_jsonl, summary.rows)
config.summary_markdown.write_text(
    _build_summary_markdown(summary),
    encoding="utf-8",
)
```
Reuse Phase 40 wording and report sections so planners do not fork the gate semantics.

### `.planning/phases/43-shadow-run-and-quality-gate/artifacts/memory-metrics.json` (config, file-I/O)

**Closest analog:** `scale-metrics.json` field discipline from `evaluate_surreal_scale_gate()`

No exact code analog exists in the repo for RSS / CPU / Python-heap reporting yet. Planner should keep this artifact separate from `scale-metrics.json` and mirror the same explicit-key style rather than hiding memory data inside a free-form note.

## Shared Patterns

### Engine Override Seam
**Source:** [backend/src/dotmd/search/surreal_native.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_native.py:18), [backend/src/dotmd/api/service.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/api/service.py:1339)
**Apply to:** Shadow candidate capture only
```python
overrides = build_surreal_native_engine_overrides(...)
pool = service._collect_candidate_pool(..., engine_overrides=overrides)
```
Do not change `DotMDService` startup defaults in Phase 43.

### Quality Gate Semantics
**Source:** [backend/src/dotmd/search/surreal_eval.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_eval.py:430), [backend/devtools/surreal_eval_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/devtools/surreal_eval_runner.py:151)
**Apply to:** Diff classification, accepted-difference handling, and final exit code
```python
summary = summarize_diffs(raw_rows, acceptances=acceptances)
exit_code = 0 if summary.passed else 1
```

### Evidence Writing
**Source:** [backend/src/dotmd/storage/surreal_ops.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal_ops.py:658)
**Apply to:** Any JSON/Markdown artifact pair in Phase 43
```python
json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
markdown_output.write_text("\n".join(lines) + "\n", encoding="utf-8")
```

### Fail-Closed Input Validation
**Source:** [backend/devtools/surreal_migration_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/devtools/surreal_migration_runner.py:375), [backend/devtools/surreal_eval_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/devtools/surreal_eval_runner.py:163)
**Apply to:** Runner CLI and all artifact loaders
```python
if mode is SurrealMigrationMode.APPLY and config.source_capture_manifest_json is None:
    raise ValueError("source_capture_manifest_json is required for apply mode")
...
if query.id not in baseline_results:
    raise ValueError(f"missing baseline result for query {query.id!r}")
```

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `.planning/phases/43-shadow-run-and-quality-gate/artifacts/memory-metrics.json` | config | file-I/O | Repo has no dedicated memory-metrics artifact schema yet; use explicit-key JSON modeled after `scale-metrics.json`, but keep wall-clock, CPU, RSS, and Python heap separate. |

## Metadata

**Analog search scope:** `backend/devtools`, `backend/src/dotmd/search`, `backend/src/dotmd/api`, `backend/src/dotmd/storage`, `backend/tests/devtools`, `backend/tests/search`, `backend/tests/api`, `.planning/phases/40-*`, `.planning/phases/41-*`, `.planning/phases/42-*`

**Files scanned:** 15

**Pattern extraction date:** 2026-06-14
