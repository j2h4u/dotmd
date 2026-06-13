---
phase: 40-evaluation-harness-and-golden-queries
reviewed: 2026-06-13T09:38:10Z
depth: standard
files_reviewed: 7
files_reviewed_list:
  - backend/src/dotmd/search/surreal_eval.py
  - backend/devtools/surreal_eval_runner.py
  - backend/devtools/surreal_golden_queries.jsonl
  - backend/devtools/surreal_golden_queries_review.md
  - backend/tests/search/test_surreal_eval.py
  - backend/tests/devtools/test_surreal_eval_runner.py
  - docs/surrealdb-evaluation-harness.md
findings:
  critical: 1
  warning: 2
  info: 0
  total: 3
status: issues
---

# Phase 40: Code Review Report

**Reviewed:** 2026-06-13T09:38:10Z
**Depth:** standard
**Files Reviewed:** 7
**Status:** issues

## Summary

Reviewed the Phase 40 evaluation harness, runner, checked-in corpus, tests, and docs against the stated focus areas: diff classification, acceptance semantics, JSONL robustness, runner safety, corpus coverage, and doc alignment.

The core phase shape is sound, but the implementation still has correctness gaps in the input loaders and diff reporting. The biggest issue is that malformed JSONL rows are sometimes silently coerced into nonsense values instead of being rejected, which makes the harness unreliable as a cutover gate.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: JSONL loaders accept malformed schema or fail with non-line-numbered exceptions

**File:** `backend/src/dotmd/search/surreal_eval.py:242-249`, `backend/src/dotmd/search/surreal_eval.py:281-305`

**Issue:** `load_golden_queries()` and `load_eval_results()` do not validate several collection-shaped fields before coercing them. This creates two bad failure modes:

- silent misparse: `languages: "en"` becomes `("e", "n")`, `expected_engines: "fts"` becomes `("f", "t", "s")`, and `matched_engines: {"ref": "semantic"}` becomes a character tuple instead of an engine list;
- opaque crash: invalid `snippets_by_ref` / `read_evidence_by_ref` values raise raw `ValueError` from `dict(...)` without the promised `path line N` context.

That breaks the Phase 40 requirement that evaluator inputs be parsed strictly and fail fast with line-numbered errors. It also means operator-supplied captures can produce misleading diff rows instead of being rejected.

The tests did not catch this because they only exercise happy-path shapes plus duplicate/enum cases; there is no coverage for malformed list/object fields in [backend/tests/search/test_surreal_eval.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/search/test_surreal_eval.py:68) or [backend/tests/devtools/test_surreal_eval_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/devtools/test_surreal_eval_runner.py:22).

**Fix:**

```python
def _require_str_list(raw: object, *, path: Path, line_number: int, field: str) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise ValueError(f"{path} line {line_number}: {field} must be a list")
    return tuple(str(item) for item in raw)


def _require_str_map(raw: object, *, path: Path, line_number: int, field: str) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError(f"{path} line {line_number}: {field} must be an object")
    return {str(key): str(value) for key, value in raw.items()}


def _require_engine_map(raw: object, *, path: Path, line_number: int) -> dict[str, tuple[str, ...]]:
    if not isinstance(raw, dict):
        raise ValueError(f"{path} line {line_number}: matched_engines must be an object")
    normalized: dict[str, tuple[str, ...]] = {}
    for ref, engines in raw.items():
        if not isinstance(engines, list):
            raise ValueError(f"{path} line {line_number}: matched_engines[{ref!r}] must be a list")
        normalized[str(ref)] = tuple(str(engine) for engine in engines)
    return normalized
```

Use helpers like these for `languages`, `expected_engines`, `matched_engines`, `snippets_by_ref`, `read_evidence_by_ref`, and `unreadable_refs`, and add explicit tests for malformed shapes.

## Warnings

### WR-01: Acceptance loader breaks the documented error contract on malformed JSON

**File:** `backend/devtools/surreal_eval_runner.py:46-80`

**Issue:** `_load_acceptances()` calls `json.loads()` directly and lets `JSONDecodeError` escape. The docs promise that JSONL inputs fail with a line-numbered `ValueError` ([docs/surrealdb-evaluation-harness.md](/home/j2h4u/repos/j2h4u/dotmd/docs/surrealdb-evaluation-harness.md:26)), but acceptance JSON is the one input path that does not honor that contract. Operators will get a raw decoder traceback instead of the same `path line N` diagnostic used by the other loaders.

**Fix:**

```python
try:
    payload = json.loads(line)
except json.JSONDecodeError as exc:
    raise ValueError(f"{path} line {line_number}: invalid JSON") from exc
```

Add a runner test that feeds malformed acceptance JSON and asserts the wrapped `ValueError`.

### WR-02: `lost_relevant_refs` can report `maybe` refs as if they were required hits

**File:** `backend/src/dotmd/search/surreal_eval.py:385-405`, `backend/src/dotmd/search/surreal_eval.py:433-440`

**Issue:** Classification intentionally treats `relevant + maybe` as the approved set, but the emitted `lost_relevant_refs` field is populated from `baseline_matched - candidate_matched`, which includes lost `maybe` refs as well. A baseline row that keeps every required `relevant` ref but drops only a `maybe` ref is currently emitted as:

- `classification = regression`
- `lost_relevant_refs = ["filesystem:/mnt/maybe.md"]`

That output is misleading for reviewers and contradicts the documented JSONL schema, which says the field contains lost relevant refs ([docs/surrealdb-evaluation-harness.md](/home/j2h4u/repos/j2h4u/dotmd/docs/surrealdb-evaluation-harness.md:123)).

**Fix:**

```python
lost_approved = tuple(sorted(baseline_matched - candidate_matched))
lost_relevant = tuple(sorted(baseline_relevant - candidate_relevant))

return SurrealEvalDiffRow(
    ...
    lost_relevant_refs=lost_relevant,
    ...
)
```

If losing `maybe` refs is still supposed to trigger regression, keep `lost_approved` for classification and rationale, but either rename the serialized field to `lost_approved_refs` or add a second field so the JSON output stays semantically accurate.

---

_Reviewed: 2026-06-13T09:38:10Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
