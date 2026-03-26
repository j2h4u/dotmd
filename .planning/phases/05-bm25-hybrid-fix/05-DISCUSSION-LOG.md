# Phase 5: BM25 Hybrid Fix - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-27
**Phase:** 05-bm25-hybrid-fix
**Areas discussed:** Recall vs precision (expert panel), Env configurability, Diagnostic approach

---

## Recall vs Precision (Expert Panel)

Panel convened: ML/IR Engineer, Researcher, Kaizen Master

### Reranker Threshold

| Option | Description | Selected |
|--------|-------------|----------|
| Remove threshold entirely | Reranker reorders, never filters. All fusion candidates survive. | ✓ |
| Lower threshold | Keep filtering but with a less aggressive cutoff | |
| Bypass reranker for BM25-only | Skip reranking for results that only matched via BM25 | |

**User's choice:** Remove threshold entirely (panel unanimous)
**Notes:** All three experts agreed the reranker should reorder, not filter. Industry consensus from IR literature.

### Fusion Candidate Preservation

| Option | Description | Selected |
|--------|-------------|----------|
| Preserve all fusion candidates | Results not scored by reranker keep their fusion score | ✓ |
| Add floor score mechanism | Results never score worse after reranking | |
| Replace list as-is | Current behavior — reranked list replaces fusion list | |

**User's choice:** Preserve all fusion candidates (simplified per Kaizen)
**Notes:** Kaizen overruled ML/IR's floor mechanism as unnecessary complexity. Simple preservation is enough.

### Blend Weights

| Option | Description | Selected |
|--------|-------------|----------|
| Keep 0.4/0.6 | Current weights, no change | ✓ |
| Reduce reranker to 0.3-0.4 | Trust fusion more, reranker less | |
| Make configurable via env | SEARCH-F2 — env var for weights | |

**User's choice:** Keep 0.4/0.6 unchanged
**Notes:** Kaizen: no evidence to justify changing. Revisit only if BM25 results still rank too low after threshold fix. User confirmed YAGNI.

---

## Env Configurability

| Option | Description | Selected |
|--------|-------------|----------|
| Add env vars for thresholds | SEARCH-F2: configurable reranker threshold via DOTMD_* vars | |
| YAGNI — no env vars | Keep thresholds hardcoded, defer configurability | ✓ |

**User's choice:** YAGNI — no env vars
**Notes:** User's exact words: "Не надо нам никаких настроек через окружение. Зачем? Это все YAGNI."

---

## Diagnostic Approach

| Option | Description | Selected |
|--------|-------------|----------|
| Diagnostic logging first | Add logging to confirm hypothesis before implementing fix | |
| Direct fix | Root cause clear from code analysis, just fix it | |
| Diagnostics as part of fix | Add logging alongside the fix, validate with test queries | ✓ |

**User's choice:** Diagnostics as part of fix (captured as D-05)
**Notes:** User initially questioned whether we have evidence that BM25 is broken. After explanation of the code-level analysis (reranker threshold + blend replacement), accepted that the root cause is clear but wants validation alongside the fix.

---

## Claude's Discretion

- Implementation approach for preserving fusion candidates through reranking
- Test design and validation queries
- Logging format and verbosity

## Deferred Ideas

- Reranker model evaluation — ms-marco-MiniLM-L-6-v2 may be poorly suited for markdown/technical content
- SEARCH-F2: Configurable reranker threshold via env var
- Blend weight tuning with empirical data
