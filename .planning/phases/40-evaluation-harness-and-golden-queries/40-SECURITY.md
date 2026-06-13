---
phase: 40
slug: evaluation-harness-and-golden-queries
status: closed
threats_open: 0
asvs_level: "not-specified"
created: "2026-06-13"
verified_at: "2026-06-13T15:06:50+05:00"
block_on: open
---

# Phase 40 — Security

Per-phase security contract: threat register, accepted risks, and audit trail.

## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| JSONL corpus / result files -> evaluator | Local files influence cutover-gate evidence and must be parsed strictly. |
| Captured old-stack / Surreal result rows -> diff classifier | Result rows are evaluator inputs, not trusted runtime state. |
| Devtool CLI arguments -> filesystem report writer | Output paths and input paths come from the operator running the harness. |
| Acceptance metadata -> aggregate gate | Acceptance can resolve an otherwise blocking diff and must be explicit. |

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-40-01 | Tampering | `load_golden_queries()` / `load_eval_results()` | mitigate | Validate required JSONL fields, duplicate ids, enum values, category coverage, and UTF-8 one-row-per-line structure before classification. | closed |
| T-40-02 | Tampering | `summarize_diffs()` acceptance handling | mitigate | Require `accepted_by` and `accepted_reason`, preserve raw `AcceptedDifference` and `CutoverGate`, and count unresolved rows separately. | closed |
| T-40-03 | Information Disclosure | `surreal_eval_runner.py` report writer | mitigate | Write only to explicit report paths, avoid dereferencing arbitrary label refs or reading filesystem paths from corpus labels during report generation, and check `contains` only against supplied snippets/read evidence in captured result rows. | closed |
| T-40-04 | Tampering | query text in CLI/devtool flow | mitigate | Keep query execution outside shell commands; runner must consume JSONL through Python code and not shell-interpolate query text. | closed |
| T-40-05 | Denial of Service | large or malformed JSONL inputs | mitigate | Stream JSONL row-by-row, fail fast with line-numbered `ValueError`, and keep focused tests on malformed row handling. | closed |
| T-40-SC | Tampering | package installs | accept | No npm, pip, or cargo install task is planned; Phase 40 uses Python stdlib and existing project dev dependencies. | closed |

## Closed

| Threat ID | Evidence |
|-----------|----------|
| T-40-01 | `backend/src/dotmd/search/surreal_eval.py:40-53` defines `validate_required_category_coverage()` and raises a line-of-defense `ValueError` when any required `GoldenQueryCategory` is missing. `backend/devtools/surreal_eval_runner.py:36` makes complete category coverage strict by default, and `backend/devtools/surreal_eval_runner.py:157-171` calls the validator immediately after `load_golden_queries()` and before loading baseline/candidate result rows or entering the only non-test `classify_difference()` call path. `backend/tests/devtools/test_surreal_eval_runner.py:253-286` proves `run_eval()` rejects an incomplete corpus by default and writes no output files. `docs/surrealdb-evaluation-harness.md:30-32` documents the same strict runtime behavior. |
| T-40-02 | `backend/src/dotmd/search/surreal_eval.py:119-142` preserves raw `classification` and `cutover_gate` in `with_acceptance()`. `backend/src/dotmd/search/surreal_eval.py:513-545` requires `accepted_by` and `accepted_reason`, applies acceptances separately, and tracks unresolved blocking vs unresolved unclear rows independently. `backend/tests/search/test_surreal_eval.py:308-350` proves accepted regression/unclear rows resolve aggregate status without mutating raw values. |
| T-40-03 | `backend/devtools/surreal_eval_runner.py:88-92` and `backend/devtools/surreal_eval_runner.py:179-184` write only to explicit `output_jsonl` and `summary_markdown` paths. `backend/src/dotmd/search/surreal_eval.py:381-413` checks `contains` only against `snippets_by_ref` and `read_evidence_by_ref`; it does not dereference label refs as paths. `backend/tests/search/test_surreal_eval.py:249-279` verifies missing supplied evidence does not trigger path reads and only evidence maps affect `contains`. `docs/surrealdb-evaluation-harness.md:77-80` documents the same boundary. |
| T-40-04 | `backend/devtools/surreal_eval_runner.py:154-185` consumes operator-supplied JSONL rows through Python loaders and classifier calls only. `backend/devtools/surreal_eval_runner.py:192-219` exposes typed `Path` CLI arguments and passes them into `run_eval()`; no shell command construction exists in the runner. `backend/tests/devtools/test_surreal_eval_runner.py:179-250` uses the hostile query text `bad'; rm -rf /` and proves it is treated as inert JSONL data while the runner emits a normal diff row. |
| T-40-05 | `backend/src/dotmd/search/surreal_eval.py:180-194` parses JSONL line-by-line as UTF-8 and raises line-numbered `ValueError` on malformed rows. `backend/src/dotmd/search/surreal_eval.py:263-370` validates loader fields before classification. `backend/devtools/surreal_eval_runner.py:48-85` applies the same line-by-line, line-numbered failure mode to acceptance JSONL. `backend/tests/search/test_surreal_eval.py:69-130` and `backend/tests/devtools/test_surreal_eval_runner.py:322-349` cover malformed collection fields, malformed engine maps, and malformed acceptance JSON. `docs/surrealdb-evaluation-harness.md:17-32` documents the fail-fast contract. |
| T-40-SC | Accepted risk documented below as `AR-40-01`. The plan records this disposition at `.planning/phases/40-evaluation-harness-and-golden-queries/40-01-PLAN.md:193`. The implemented Phase 40 modules import stdlib plus existing project modules only in `backend/src/dotmd/search/surreal_eval.py:5-16` and `backend/devtools/surreal_eval_runner.py:14-23`. |

## Open

None.

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-40-01 | T-40-SC | Phase 40 deliberately adds only repo-local evaluation code, tests, corpus artifacts, and docs. No package-install step is part of the phase; residual supply-chain exposure is accepted at project dependency baseline rather than expanded here. | project owner via Phase 40 plan | 2026-06-13 |

## Unregistered Flags

None. `40-01-SUMMARY.md` does not contain a `## Threat Flags` section.

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By | Notes |
|------------|---------------|--------|------|--------|-------|
| 2026-06-13 | 6 | 5 | 1 | Codex security auditor | `cd backend && uv run pytest tests/search/test_surreal_eval.py tests/devtools/test_surreal_eval_runner.py -q` -> `16 passed in 0.27s`. No phase-local `<config>` block with `asvs_level` or `block_on` was found in the required planning artifacts, so this report records them as not specified / open. |
| 2026-06-13 | 6 | 6 | 0 | Codex security auditor | Re-ran the audit after `4691a7e`. Verified `run_eval()` now enforces complete golden corpus category coverage before loading baseline/candidate results or calling `classify_difference()`. `cd backend && uv run pytest tests/search/test_surreal_eval.py tests/devtools/test_surreal_eval_runner.py -q` -> `17 passed in 0.27s`. No phase-local `<config>` block with `asvs_level` or `block_on` was found in the required planning artifacts, so this report continues to record them as not specified / open. |

## Sign-Off

- [x] All threats have a disposition (mitigate / accept)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] Phase 40 security gate is clear to ship

**Current verdict:** secured. All six Phase 40 threats are closed or documented as accepted risk.
