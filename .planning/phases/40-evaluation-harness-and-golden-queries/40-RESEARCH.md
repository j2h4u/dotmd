# Phase 40: Evaluation Harness and Golden Queries - Research

**Researched:** 2026-06-13
**Domain:** Search-quality evaluation harness for SurrealDB cutover
**Confidence:** HIGH

## User Constraints

- Build only the Phase 40 research artifact at `/home/j2h4u/repos/j2h4u/dotmd/.planning/phases/40-evaluation-harness-and-golden-queries/40-RESEARCH.md`.
- Phase 40 must answer what to build for evaluation, not implement migration, runtime cutover, or legacy deletion.
- No compatibility mode, no fallback backend, no reindex/reembed requirement in Phase 40, and the old stack remains baseline/evaluator only.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SURR-EVAL-01 | A golden query set covers title-heavy, tag-heavy, body-heavy, semantic, graph/entity, hybrid, source-ref, and mixed RU/EN queries. | Use a JSONL golden-query ledger with explicit `category`, `primary_surface`, approved `relevant`/`maybe` labels, and per-query review notes. [CITED: .planning/REQUIREMENTS.md] |
| SURR-EVAL-02 | Old-vs-Surreal diff reports classify changed results as improvement, harmless reorder, regression, or unclear. | Reuse `AcceptedDifference` and `CutoverGate` from `backend/src/dotmd/search/surreal_contract.py` and emit one machine-readable diff row per query plus an aggregate summary. [CITED: .planning/REQUIREMENTS.md; backend/src/dotmd/search/surreal_contract.py] |
| SURR-EVAL-03 | Regressions block cutover unless fixed or explicitly accepted as a deliberate search semantics change. | Make the aggregate gate fail on any unaccepted `regression`; allow `improvement` and `harmless_reorder`; require a review ledger entry for `unclear`. [CITED: .planning/REQUIREMENTS.md; docs/surrealdb-native-retrieval-contract.md] |

## Summary

Phase 40 should deliver a repo-local evaluation surface, not a runtime feature: one approved golden-query corpus, one typed diff/classification module, one runner that compares baseline-vs-Surreal outputs and writes JSONL plus Markdown reports, and tests that prove the gate blocks regressions while allowing non-parity improvements. This follows the v1.8 roadmap boundary where Phase 40 is the quality harness, while schema/import remains Phase 41, Surreal retrieval implementation remains Phase 42, and live shadow-run evidence remains Phase 43. [CITED: .planning/ROADMAP.md; .planning/REQUIREMENTS.md; docs/surrealdb-native-retrieval-contract.md]

The strongest reuse path is already in the repo: Phase 39 contributed the typed difference vocabulary and cutover gates in `backend/src/dotmd/search/surreal_contract.py`, Phase 38 contributed callable-based comparison/report patterns in `backend/src/dotmd/search/surreal_parity.py`, and Phase 21 contributed the approved JSONL-label plus review-ledger pattern in `.planning/milestones/v1.4-phases/21-reranker-quality-benchmark/21-LABELS.jsonl` and `21-LABELS-REVIEW.md`. Phase 40 should combine those three patterns instead of reviving exact-parity gates or reintroducing the deleted Phase 11 standalone HTTP scripts. [CITED: backend/src/dotmd/search/surreal_contract.py; backend/src/dotmd/search/surreal_parity.py; .planning/milestones/v1.4-phases/21-reranker-quality-benchmark/21-LABELS.jsonl; .planning/milestones/v1.4-phases/21-reranker-quality-benchmark/21-LABELS-REVIEW.md; .planning/milestones/v1.4-phases/11-embedding-model-swap/11-01-SUMMARY.md]

The key planning decision is to gate on user-visible relevance and readability, not on score or rank parity. Phase 38 rejected migrate-ready parity because weighted FTS and hybrid attribution diverged even when some top hits overlapped; Phase 39 replaced that posture with accepted-difference classes. Phase 40 therefore needs a classifier that can say “better,” “same enough,” “worse,” or “needs human judgment” for each query, and an aggregate report that blocks only the bad class. [CITED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-03-RETRIEVAL-PARITY.md; .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-RECOMMENDATION.md; .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md]

**Primary recommendation:** Build Phase 40 as a repo-local Python evaluation module plus devtool runner that reuses `AcceptedDifference`/`CutoverGate`, stores golden queries and diff rows as JSONL, and treats any unaccepted regression as a hard failure while allowing improvements and harmless reorders. [CITED: backend/src/dotmd/search/surreal_contract.py; backend/src/dotmd/search/surreal_parity.py; .planning/milestones/v1.4-phases/21-reranker-quality-benchmark/21-LABELS.jsonl; https://jsonlines.org/]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Golden-query corpus definition and approval | API / Backend | Database / Storage | The corpus describes backend search behavior and is stored as repo-local fixture data, not UI state. [CITED: .planning/ROADMAP.md; .planning/milestones/v1.4-phases/21-reranker-quality-benchmark/21-LABELS.jsonl] |
| Old-vs-Surreal result capture and diff classification | API / Backend | Database / Storage | The harness compares backend retrieval outputs and reads stored provenance/snippet/ref evidence, but it should not live inside request-serving code. [CITED: backend/src/dotmd/search/surreal_parity.py; backend/src/dotmd/api/service.py] |
| Regression gate and acceptance ledger | API / Backend | — | Cutover policy is backend migration policy expressed through typed enums and report aggregation. [CITED: backend/src/dotmd/search/surreal_contract.py; docs/surrealdb-native-retrieval-contract.md] |
| Source-ref readability checks | API / Backend | Database / Storage | The public result contract is `ref`-first, so the evaluator must validate readable refs and stable provenance against stored metadata. [CITED: backend/src/dotmd/core/models.py; backend/src/dotmd/api/service.py] |

## Project Constraints (from AGENTS.md)

- Work on `main`; Phase 40 planning should not assume a long-lived compatibility branch. [CITED: AGENTS.md]
- All public APIs go through `backend/src/dotmd/api/service.py`; the harness should stay as devtool/policy code, not invent a parallel runtime surface. [CITED: AGENTS.md]
- New search behavior must respect the existing search architecture: query expansion, parallel semantic/FTS5/graph retrieval, fusion, and reranking. [CITED: AGENTS.md]
- New search-engine abstractions belong behind `SearchEngineProtocol`; do not hand-wire a new production engine into the service for this phase. [CITED: AGENTS.md]
- Never reload indexes per request; evaluation code must reuse startup-loaded stores or injected callables. [CITED: AGENTS.md]
- Never run `dotmd index --force` while the container is running; Phase 40 must not require reindexing as part of evaluation setup. [CITED: AGENTS.md]
- Never restart production on small changes; live dual-stack or production shadow execution is deferred beyond this phase. [CITED: AGENTS.md]
- The production data root is locked to `/mnt`; Phase 40 should consume existing search/index surfaces, not invent a narrowed corpus path. [CITED: AGENTS.md]

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| repo-local `dotmd.search.surreal_contract` | current checkout | Canonical difference classes and cutover gates | Phase 39 already defines the accepted vocabulary, so Phase 40 should import it instead of duplicating strings or inventing a second gate model. [CITED: backend/src/dotmd/search/surreal_contract.py; .planning/phases/39-surrealdb-native-retrieval-contract/39-01-SUMMARY.md] |
| repo-local `dotmd.search.surreal_parity` | current checkout | Callable-based result comparison and aggregate reporting patterns | It already separates comparison logic from service wiring and provides deterministic report structures to extend toward quality diffs. [CITED: backend/src/dotmd/search/surreal_parity.py; backend/tests/search/test_surreal_retrieval_parity.py] |
| `pytest` | project dev dep `>=9.0.3`; local `uv run pytest` = `9.0.3` | Unit and fixture-backed evaluation tests | The repo already standardizes pytest and registers markers in `backend/pyproject.toml`, so Phase 40 should stay inside that test stack. [CITED: backend/pyproject.toml] |
| Python stdlib `json`, `argparse`, `pathlib` | Python `3.12.12` in project venv | JSONL fixtures, CLI runner, file-safe report writing | Phase 40 does not need a new eval framework or new serialization package; stdlib is sufficient and keeps the harness cheap to maintain. [CITED: backend/pyproject.toml] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest-xdist` | project dev dep `>=3.8.0` | Optional parallel test execution | Use only if the Phase 40 fixture corpus grows enough that local feedback loops become slow; it is already in dev dependencies, but it is not required to deliver the first harness. [CITED: backend/pyproject.toml] |
| repo-local `backend/devtools/reranker_quality_bench.py` patterns | current checkout | JSONL label parsing, graded metrics, pool-miss handling, Markdown summary style | Reuse its fixture/report patterns, not its reranker-specific metrics, when building the golden-query runner. [CITED: backend/devtools/reranker_quality_bench.py] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| repo-local policy module + devtool runner | resurrected Phase 11 standalone HTTP scripts | Those scripts were created for one-off embedding A/B checks, are no longer present in the repo, and lack Phase 39 difference classes, source-ref checks, and typed gate semantics. [CITED: .planning/milestones/v1.4-phases/11-embedding-model-swap/11-01-SUMMARY.md] |
| JSONL ledger for queries and diff rows | CSV or Markdown-only reports | JSONL preserves one structured object per line, supports Unicode, and is appendable and machine-readable without flattening nested diff evidence. [CITED: https://jsonlines.org/] |
| accepted-difference gate | exact old-stack parity | Exact parity was explicitly rejected by Phase 39 and already produced misleading migrate-ready pressure in Phase 38. [CITED: .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md; .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-03-RETRIEVAL-PARITY.md] |

**Installation:**
```bash
cd /home/j2h4u/repos/j2h4u/dotmd/backend
uv sync --extra dev
```

**Version verification:** Phase 40 should reuse the existing project dev stack; `backend/pyproject.toml` declares `pytest>=9.0.3` and `pytest-xdist>=3.8.0`, and the local project venv currently resolves `pytest 9.0.3` under `uv run`. [CITED: backend/pyproject.toml]

## Package Legitimacy Audit

No new third-party packages are recommended for Phase 40; reuse the existing project dev dependencies and Python stdlib instead. [CITED: backend/pyproject.toml]

## What Phase 40 Delivers

1. A versioned golden-query ledger, preferably `backend/devtools/surreal_golden_queries.jsonl`, with approved query rows spanning every required scenario class. [CITED: .planning/ROADMAP.md; .planning/REQUIREMENTS.md; .planning/milestones/v1.4-phases/21-reranker-quality-benchmark/21-LABELS.jsonl]
2. A human approval ledger, preferably `backend/devtools/surreal_golden_queries_review.md`, matching the Phase 21 “review before canonical scoring” pattern. [CITED: .planning/milestones/v1.4-phases/21-reranker-quality-benchmark/21-LABELS-REVIEW.md]
3. A repo-local evaluation module, preferably under `backend/src/dotmd/search/`, that imports `AcceptedDifference` and `CutoverGate`, classifies per-query diffs, and aggregates gate outcomes. [CITED: backend/src/dotmd/search/surreal_contract.py]
4. A CLI runner, preferably under `backend/devtools/`, that loads approved queries, calls baseline and Surreal adapters, and writes JSONL diff rows plus a concise Markdown summary. [CITED: backend/devtools/reranker_quality_bench.py; backend/src/dotmd/search/surreal_parity.py]
5. Tests proving category coverage, diff-row schema, automatic regression detection, allowed-improvement flow, harmless-reorder flow, and explicit-acceptance handling for unclear cases. [CITED: backend/tests/search/test_surreal_contract.py; backend/tests/search/test_surreal_retrieval_parity.py]

## What Stays Deferred to Phases 41-43

- Phase 41 owns production-grade Surreal schema and transform-first import; Phase 40 should not redesign migration rows, backup flows, or rollback mechanics beyond consuming current refs and stored data as evaluation inputs. [CITED: .planning/ROADMAP.md; .planning/REQUIREMENTS.md]
- Phase 42 owns real Surreal full-text, vector, graph, and hybrid retrieval implementation; Phase 40 should evaluate adapters and outputs, not build the backend. [CITED: .planning/ROADMAP.md]
- Phase 43 owns production-derived side-by-side shadow execution, latency/build/store-size evidence, and cutover resolution of every material difference; Phase 40 only builds the gate and corpus that Phase 43 will run. [CITED: .planning/ROADMAP.md; .planning/REQUIREMENTS.md]
- Reindexing, reembedding, or entity re-extraction remain out of scope for Phase 40 because the milestone explicitly rejects default recomputation and Phase 40 is not the migration phase. [CITED: .planning/REQUIREMENTS.md; docs/surrealdb-native-retrieval-contract.md]

## Architecture Patterns

### System Architecture Diagram

```text
approved golden queries (.jsonl)
        |
        v
golden-query loader -----> label/ref resolver -----> baseline adapter (old stack)
        |                            |                         |
        |                            |                         v
        |                            |                baseline SearchCandidate set
        |                            |
        |                            +--------------> candidate adapter (Surreal path)
        |                                                      |
        v                                                      v
query metadata --------------------------------------> candidate SearchCandidate set
                                                               |
                                                               v
                                           diff classifier (AcceptedDifference)
                                                               |
                                               +---------------+----------------+
                                               |                                |
                                               v                                v
                                      per-query diff row (.jsonl)      aggregate gate + summary (.md)
```

The harness should operate on result objects and review metadata, not on direct index mutation or production container restarts. [CITED: backend/src/dotmd/search/surreal_parity.py; AGENTS.md]

### Recommended Project Structure

```text
backend/
├── devtools/
│   ├── surreal_eval_runner.py          # CLI entry for baseline-vs-Surreal runs
│   ├── surreal_golden_queries.jsonl    # approved query corpus
│   └── results/
│       ├── surreal-eval-<stamp>.jsonl  # per-query diff rows
│       └── surreal-eval-<stamp>.md     # human summary
├── src/dotmd/search/
│   └── surreal_eval.py                 # typed diff rows, classifier, aggregate gate
└── tests/
    ├── search/test_surreal_eval.py
    └── devtools/test_surreal_eval_runner.py
```

This keeps evaluation logic importable and testable while keeping runner I/O in `devtools`, which matches current repo patterns. [CITED: backend/devtools/reranker_quality_bench.py; backend/src/dotmd/search/surreal_parity.py]

### Pattern 1: Golden Query Ledger + Approval Ledger

**What:** Store one query per JSONL row and require a separate review file before calling any run canonical. [CITED: .planning/milestones/v1.4-phases/21-reranker-quality-benchmark/21-LABELS.jsonl; .planning/milestones/v1.4-phases/21-reranker-quality-benchmark/21-LABELS-REVIEW.md]

**When to use:** For any evaluation set whose labels affect a release gate. [CITED: .planning/milestones/v1.4-phases/21-reranker-quality-benchmark/21-01-quality-benchmark-PLAN.md]

**Recommended row shape:**
```json
{
  "id": "sq-001",
  "query": "Hiveon tags",
  "category": "tag-heavy",
  "primary_surface": "weighted_full_text",
  "languages": ["en"],
  "relevant": [{"ref": "filesystem:/mnt/.../hiveon.md", "contains": "Hiveon"}],
  "maybe": [],
  "expected_engines": ["fts"],
  "notes": "Title/tag signal should beat body-only mentions."
}
```

Prefer `ref` plus `contains` over raw `chunk_id` as the public label anchor because the product contract is source-ref-first and user-visible acceptance is about readable refs, not internal row identity alone. [CITED: backend/src/dotmd/core/models.py; backend/src/dotmd/api/service.py]

### Pattern 2: Typed Diff Row + Aggregate Gate

**What:** Emit one structured diff row per query, then a report that derives overall gate status from those rows. [CITED: backend/src/dotmd/search/surreal_parity.py; backend/src/dotmd/search/surreal_contract.py]

**When to use:** For baseline-vs-candidate comparison where exact rank parity is not the goal. [CITED: .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md]

**Recommended diff row shape:**
```json
{
  "query_id": "sq-001",
  "query": "Hiveon tags",
  "category": "tag-heavy",
  "baseline_top_refs": ["filesystem:/mnt/.../hiveon.md"],
  "candidate_top_refs": ["filesystem:/mnt/.../hiveon.md"],
  "lost_relevant_refs": [],
  "gained_relevant_refs": [],
  "rank_deltas": {"filesystem:/mnt/.../hiveon.md": 0},
  "matched_engines": {
    "baseline": {"filesystem:/mnt/.../hiveon.md": ["fts"]},
    "candidate": {"filesystem:/mnt/.../hiveon.md": ["fts"]}
  },
  "classification": "harmless_reorder",
  "cutover_gate": "allow",
  "rationale_codes": ["same_relevant_set"],
  "accepted_by": null
}
```

Use literal values from `AcceptedDifference` and `CutoverGate`, not ad-hoc strings. [CITED: backend/src/dotmd/search/surreal_contract.py]

### Pattern 3: Callable Adapters, Not Embedded Runtime Wiring

**What:** Keep the evaluator able to compare two providers via injected callables or thin adapter objects. [CITED: backend/src/dotmd/search/surreal_parity.py]

**When to use:** For deterministic unit tests now and for Phase 43 shadow wiring later. [CITED: backend/src/dotmd/search/surreal_parity.py; .planning/ROADMAP.md]

**Example:**
```python
from dotmd.search.surreal_contract import AcceptedDifference, default_surreal_retrieval_contract

contract = default_surreal_retrieval_contract()
classification = AcceptedDifference.REGRESSION
gate = contract.cutover_gate_for(classification)
assert gate.value == "block"
```

**Source:** `backend/src/dotmd/search/surreal_contract.py`. [CITED: backend/src/dotmd/search/surreal_contract.py]

### Anti-Patterns to Avoid

- **Exact-parity gating:** Phase 38’s parity harness failed on weighted FTS and hybrid attribution for migrate-ready decisions; Phase 40 should not reuse its `passed == parity` rule as the final quality gate. [CITED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-03-RETRIEVAL-PARITY.md]
- **HTTP-only external scripts as the primary design:** The old Phase 11 standalone A/B scripts are absent from the current repo and do not encode the new cutover vocabulary. [CITED: .planning/milestones/v1.4-phases/11-embedding-model-swap/11-01-SUMMARY.md]
- **Chunk-id-only judgments:** User-visible acceptance hinges on readable refs, snippets, and result intent; chunk IDs alone can miss acceptable same-document improvements. [CITED: backend/src/dotmd/core/models.py; backend/src/dotmd/api/service.py]
- **Live-corpus mutation during evaluation:** Phase 40 should not require index rebuilds or production restarts to classify diffs. [CITED: AGENTS.md]

## Golden Query Modeling

### Minimum Scenario Matrix

| Category | What the query should prove | Label guidance |
|---------|-----------------------------|----------------|
| `title-heavy` | A title match should beat weaker body-only matches. | At least one approved `relevant` ref whose title contains the term, plus a nearby body-only distractor. [CITED: backend/src/dotmd/search/fts5.py] |
| `tag-heavy` | A tag match should be visible even when body text is weaker. | Mark the tag-driven ref as `relevant`; annotate expected engine `fts`. [CITED: backend/src/dotmd/search/fts5.py] |
| `body-heavy` | Strong body evidence should still rank when title/tags are absent. | Use `contains` anchors to pin the intended section text. [CITED: .planning/milestones/v1.4-phases/21-reranker-quality-benchmark/21-LABELS.jsonl] |
| `semantic` | Embedding similarity should surface relevant content not driven by literal token overlap. | Prefer conceptually matched refs and include literal distractors as `maybe` or irrelevant review notes. [CITED: backend/src/dotmd/search/semantic.py] |
| `graph/entity` | Entity catalog lookup and relation traversal should surface the right connected sections. | Include expected engine `graph` and at least one named-entity phrase query. [CITED: backend/src/dotmd/search/graph_direct.py] |
| `hybrid` | Fusion should preserve the right candidate set and explainable engine attribution. | Record expected engine mix and treat lost cross-engine diversity as evidence. [CITED: backend/src/dotmd/search/fusion.py; backend/src/dotmd/search/surreal_parity.py] |
| `source-ref` | Returned refs must be readable and point to the intended document/unit. | Use `ref` as the primary label key and require `can_read=true` in the diff classifier. [CITED: backend/src/dotmd/core/models.py; backend/src/dotmd/api/service.py] |
| `mixed-ru-en` | Mixed-language queries should still find the intended content and not collapse on ASCII-only token bias. | Include both Russian and English terms in one query and approve refs that contain the mixed intent. [CITED: .planning/REQUIREMENTS.md; .planning/milestones/v1.4-phases/21-reranker-quality-benchmark/21-LABELS.jsonl] |

### Additional Field Recommendations

- Add `expected_engines` so a graph/entity or hybrid query can explain why a result is an improvement or regression instead of relying on rank alone. [CITED: backend/src/dotmd/search/surreal_parity.py]
- Add `review_status` or keep approval in a separate Markdown ledger; do not run canonical reports from unreviewed rows. [CITED: .planning/milestones/v1.4-phases/21-reranker-quality-benchmark/21-LABELS-REVIEW.md]
- Add `broad_query: true` for intentionally ambiguous terms so the classifier can downgrade uncertain shifts to `unclear` instead of over-reporting regressions. [CITED: .planning/milestones/v1.4-phases/21-reranker-quality-benchmark/21-LABELS.jsonl]

## Diff Classification Model

### Automatic Classification Rules

| Class | Automatic trigger | Gate |
|------|-------------------|------|
| `improvement` | Candidate surfaces more approved `relevant` refs than baseline, improves the best approved rank without losing approved refs, fixes unreadable refs, or reduces a baseline retrieval gap. [CITED: .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md; backend/src/dotmd/core/models.py] | allow |
| `harmless_reorder` | Candidate preserves the same approved `relevant`/`maybe` set in top-k and only changes internal ordering or same-document section preference without harming readability. [CITED: .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md] | allow |
| `regression` | Candidate loses an approved `relevant` ref that baseline had, returns unreadable or wrong refs, introduces `pool_miss` on an approved query, or drops the expected graph/hybrid/source-ref behavior in a user-visible way. [CITED: .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md; backend/devtools/reranker_quality_bench.py; backend/src/dotmd/api/service.py] | block |
| `unclear` | Both systems miss approved labels, the query is intentionally broad, or evidence is mixed enough that automation cannot justify improvement/regression. [CITED: .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md] | requires explicit acceptance |

### Gate Policy

- The aggregate report fails immediately if any diff row is `regression` and has no explicit acceptance record. [CITED: backend/src/dotmd/search/surreal_contract.py]
- `improvement` and `harmless_reorder` count as green even when exact ranks differ. [CITED: backend/src/dotmd/search/surreal_contract.py]
- `unclear` must be reported separately and linked to a human acceptance note; Phase 40 should build this ledger mechanism, while Phase 43 will use it during shadow runs. [CITED: backend/src/dotmd/search/surreal_contract.py; .planning/ROADMAP.md]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Difference vocabulary | bespoke strings like `"better"` / `"bad"` | `AcceptedDifference` and `CutoverGate` | Phase 39 already codified the exact milestone contract. [CITED: backend/src/dotmd/search/surreal_contract.py] |
| Result-ledger format | free-form Markdown tables only | JSONL diff rows plus Markdown summary | JSONL is machine-readable, appendable, and Unicode-safe for mixed RU/EN queries. [CITED: https://jsonlines.org/] |
| Label-review process | ad-hoc inline comments in code | separate review ledger like Phase 21 | Human approval was already the project’s pattern for evaluation data that affects a gate. [CITED: .planning/milestones/v1.4-phases/21-reranker-quality-benchmark/21-LABELS-REVIEW.md] |
| Baseline-vs-candidate comparison wiring | runtime-specific service hacks | injected callables or thin adapters | This keeps tests deterministic and postpones live shadow plumbing to Phase 43. [CITED: backend/src/dotmd/search/surreal_parity.py; .planning/ROADMAP.md] |

**Key insight:** Phase 40 is not a “search engine implementation” phase; it is a policy-plus-evidence phase, so the highest leverage comes from reusing existing enums, review flows, and report patterns instead of introducing another mini-framework. [CITED: .planning/ROADMAP.md; backend/src/dotmd/search/surreal_contract.py]

## Common Pitfalls

### Pitfall 1: Reusing Phase 38 parity pass/fail as the new gate

**What goes wrong:** The harness reports false failures for acceptable Surreal-native improvements because it still expects exact overlap or exact engine attribution. [CITED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-03-RETRIEVAL-PARITY.md]

**Why it happens:** `RetrievalParityReport` was designed to reject migrate-ready parity gaps, not to classify qualitative acceptance categories. [CITED: backend/src/dotmd/search/surreal_parity.py]

**How to avoid:** Reuse the callable/result structure but replace the final verdict layer with `AcceptedDifference` classification. [CITED: backend/src/dotmd/search/surreal_contract.py; backend/src/dotmd/search/surreal_parity.py]

**Warning signs:** Lots of “fail” outcomes where the candidate actually surfaces the right readable ref or additional relevant evidence. [CITED: .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md]

### Pitfall 2: Labeling by chunk ID only

**What goes wrong:** The evaluator flags harmless same-document chunk changes as regressions even though the public ref and user intent are preserved. [CITED: backend/src/dotmd/core/models.py; backend/src/dotmd/api/service.py]

**Why it happens:** Chunk IDs are internal retrieval artifacts; Phase 26 made `ref` the public search-to-read key. [CITED: .planning/STATE.md; backend/src/dotmd/core/models.py]

**How to avoid:** Use `ref` as the primary approved label key and optionally add `contains` or `chunk_id` as secondary disambiguators. [CITED: .planning/milestones/v1.4-phases/21-reranker-quality-benchmark/21-LABELS.jsonl; backend/src/dotmd/core/models.py]

**Warning signs:** Diff rows show lost chunk IDs but the same document remains readable at the expected ref. [CITED: backend/src/dotmd/api/service.py]

### Pitfall 3: Counting ambiguous queries as hard regressions

**What goes wrong:** Broad terms like `индекс` or `граф` create noisy blocks because the corpus intentionally has several reasonable answers. [CITED: .planning/milestones/v1.4-phases/21-reranker-quality-benchmark/21-LABELS.jsonl]

**Why it happens:** The query set mixes precise task queries and intentionally broad discovery queries. [CITED: .planning/milestones/v1.4-phases/21-reranker-quality-benchmark/21-LABELS-REVIEW.md]

**How to avoid:** Mark broad queries explicitly and map ambiguous outcomes to `unclear`, not `regression`, unless approved relevant evidence disappears completely. [CITED: .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md]

**Warning signs:** Many candidate runs fail only on broad one-word queries while targeted queries look healthy. [CITED: .planning/milestones/v1.4-phases/21-reranker-quality-benchmark/21-LABELS.jsonl]

## Code Examples

### Parametrized Category Coverage Tests

```python
import pytest

@pytest.mark.parametrize(
    "category",
    [
        pytest.param("title-heavy", id="title-heavy"),
        pytest.param("tag-heavy", id="tag-heavy"),
        pytest.param("body-heavy", id="body-heavy"),
        pytest.param("semantic", id="semantic"),
        pytest.param("graph/entity", id="graph-entity"),
        pytest.param("hybrid", id="hybrid"),
        pytest.param("source-ref", id="source-ref"),
        pytest.param("mixed-ru-en", id="mixed-ru-en"),
    ],
)
def test_golden_query_categories_present(category: str) -> None:
    ...
```

**Source:** pytest parametrization with explicit IDs. [CITED: https://docs.pytest.org/en/stable/example/parametrize.html]

### Registered Marker for Slow or Review-Dependent Eval Runs

```toml
[tool.pytest.ini_options]
markers = [
  "eval: structured Surreal quality-eval tests",
]
```

**Source:** pytest marker registration pattern; dotMD already registers markers in `backend/pyproject.toml`. [CITED: https://docs.pytest.org/en/stable/example/markers.html; backend/pyproject.toml]

### File-Backed Fixture for JSONL Reports

```python
def test_report_writer(tmp_path):
    report = tmp_path / "surreal-eval.jsonl"
    report.write_text('{"query_id":"sq-001"}\n', encoding="utf-8")
    assert report.read_text(encoding="utf-8").endswith("\n")
```

**Source:** `tmp_path` provides a unique `pathlib.Path` per test and supports UTF-8 file writes. [CITED: https://docs.pytest.org/en/stable/how-to/tmp_path.html]

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| exact or near-parity comparison as migration evidence | accepted-difference classification against user-visible quality | 2026-06-13 in Phase 39 | Phase 40 should judge outcomes by relevance/readability, not exact order. [CITED: .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md] |
| one-off evaluation scripts over HTTP | repo-local typed harness plus reviewed corpora | Phase 21 established reviewed corpora; Phase 39 established typed cutover classes | The evaluator can now be deterministic, testable, and reusable in Phase 43 shadow runs. [CITED: .planning/milestones/v1.4-phases/21-reranker-quality-benchmark/21-LABELS.jsonl; backend/src/dotmd/search/surreal_contract.py] |

**Deprecated/outdated:**

- Exact old-stack rank parity as the success criterion is outdated for v1.8. [CITED: .planning/REQUIREMENTS.md; docs/surrealdb-native-retrieval-contract.md]
- Depending on `backend/scripts/eval_baseline.py` or `eval_compare.py` is outdated because those files are not present in the current checkout. [CITED: .planning/milestones/v1.4-phases/11-embedding-model-swap/11-01-SUMMARY.md]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `backend/devtools/surreal_golden_queries.jsonl`, `backend/devtools/surreal_eval_runner.py`, and `backend/src/dotmd/search/surreal_eval.py` are the recommended landing paths, but the exact filenames are a planning recommendation rather than an existing locked decision. [ASSUMED] | Architecture Patterns | Low — planner can rename paths without changing the design. |

## Resolved Planning Decisions

1. **Phase 40 source-ref coverage is local indexed source-ref coverage only.**
   - Decision: the approved Phase 40 corpus should prove that returned refs are
     readable and point to the intended local indexed document/unit. It should
     not require federated-only Gmail or Telegram refs.
   - Rationale: the v1.8 milestone is a storage cutover from SQLite/sqlite-vec
     and FalkorDB to SurrealDB. Federated-only connectors have different live
     scoring and availability semantics, and they are not part of the storage
     import/retrieval cutover surface. [CITED: .planning/ROADMAP.md; docs/surrealdb-native-retrieval-contract.md]
   - Follow-up: federated source-ref quality can get its own later evaluation
     set if connector cutover quality becomes a milestone goal. [ASSUMED]

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | evaluation module, devtool runner, pytest | ✓ | `3.12.12` in `uv run`; host `python3` is `3.13.5` | Use `uv run` to stay on project Python. [CITED: backend/pyproject.toml] |
| `uv` | project-managed test/runtime commands | ✓ | `0.11.19` | none — use project tooling. |
| `pytest` | validation architecture | ✓ | `9.0.3` via `uv run` | do not use host `pytest 8.3.5`; run through `uv`. [CITED: backend/pyproject.toml] |
| `ripgrep` | corpus/category verification scripts | ✓ | `15.1.0` | `grep` if needed. |

**Missing dependencies with no fallback:**

- None for Phase 40 research and harness implementation. Live Surreal/old-stack shadow infrastructure is deferred to Phase 43. [CITED: .planning/ROADMAP.md]

**Missing dependencies with fallback:**

- None identified. [CITED: .planning/ROADMAP.md]

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `pytest 9.0.3` via `uv run` [CITED: backend/pyproject.toml] |
| Config file | `backend/pyproject.toml` [CITED: backend/pyproject.toml] |
| Quick run command | `cd backend && uv run pytest tests/search/test_surreal_eval.py tests/devtools/test_surreal_eval_runner.py -x` [ASSUMED] |
| Full suite command | `just verify` [CITED: justfile] |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SURR-EVAL-01 | Golden-query corpus covers all required scenario classes and rejects missing categories. [CITED: .planning/REQUIREMENTS.md] | unit | `cd backend && uv run pytest tests/devtools/test_surreal_eval_runner.py -k coverage -x` [ASSUMED] | ❌ Wave 0 |
| SURR-EVAL-02 | Diff rows emit one of the four Phase 39 classes and preserve machine-readable fields. [CITED: .planning/REQUIREMENTS.md; backend/src/dotmd/search/surreal_contract.py] | unit | `cd backend && uv run pytest tests/search/test_surreal_eval.py -k classify -x` [ASSUMED] | ❌ Wave 0 |
| SURR-EVAL-03 | Aggregate gate blocks regressions and requires explicit acceptance for unclear rows. [CITED: .planning/REQUIREMENTS.md; backend/src/dotmd/search/surreal_contract.py] | unit | `cd backend && uv run pytest tests/search/test_surreal_eval.py -k gate -x` [ASSUMED] | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `cd backend && uv run pytest tests/search/test_surreal_eval.py tests/devtools/test_surreal_eval_runner.py -x` [ASSUMED]
- **Per wave merge:** `just unit` [CITED: justfile]
- **Phase gate:** `just verify` plus one canonical dry run of the new eval runner on the approved golden corpus. [CITED: justfile]

### Wave 0 Gaps

- [ ] `backend/tests/search/test_surreal_eval.py` — classifier and aggregate-gate contract coverage. [ASSUMED]
- [ ] `backend/tests/devtools/test_surreal_eval_runner.py` — JSONL loader, report writer, and category coverage checks. [ASSUMED]
- [ ] `backend/devtools/surreal_golden_queries.jsonl` — approved corpus scaffold. [ASSUMED]
- [ ] `backend/devtools/surreal_golden_queries_review.md` — approval checkpoint ledger. [ASSUMED]

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Phase 40 is offline/devtool evaluation, not an auth surface. [CITED: .planning/ROADMAP.md] |
| V3 Session Management | no | No session state is introduced by the harness itself. [CITED: .planning/ROADMAP.md] |
| V4 Access Control | no | The harness reads approved fixtures and result objects; it should not introduce new role-based access behavior. [CITED: .planning/ROADMAP.md] |
| V5 Input Validation | yes | Validate JSONL rows, enum values, refs, and optional `contains` anchors before running classification. [CITED: backend/src/dotmd/core/models.py; https://jsonlines.org/] |
| V6 Cryptography | no | No new cryptographic boundary is required for this phase. [CITED: .planning/ROADMAP.md] |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malformed or partial JSONL fixture/report rows | Tampering | Parse every row strictly as JSON, require UTF-8, and reject blank or schema-invalid lines. [CITED: https://jsonlines.org/] |
| Path traversal or arbitrary file reads from label anchors | Information Disclosure | Resolve only approved ref/file-path fields from the ledger and keep file-backed fixture tests inside `tmp_path`. [CITED: https://docs.pytest.org/en/stable/how-to/tmp_path.html; backend/src/dotmd/core/models.py] |
| Gate bypass via ad-hoc acceptance strings | Elevation of Privilege | Drive allowed values from `AcceptedDifference` and `CutoverGate` enums and require explicit acceptance metadata for `unclear`. [CITED: backend/src/dotmd/search/surreal_contract.py] |
| Shell injection through query text in report runners | Tampering | Keep query execution inside Python adapters and never interpolate query text into shell commands. [CITED: backend/devtools/reranker_quality_bench.py] |

## Sources

### Primary (HIGH confidence)

- `AGENTS.md` — project constraints, search/runtime boundaries, deployment guardrails.
- `.planning/STATE.md` — current milestone status and prior phase decisions affecting evaluation posture.
- `.planning/ROADMAP.md` — exact Phase 40-45 boundaries.
- `.planning/REQUIREMENTS.md` — `SURR-EVAL-01/02/03` requirements and milestone non-goals.
- `docs/surrealdb-native-retrieval-contract.md` — durable contract and accepted-difference policy.
- `.planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md` — phase-local handoff into Phase 40.
- `.planning/phases/39-surrealdb-native-retrieval-contract/39-01-SUMMARY.md` — scope and downstream consumer notes.
- `backend/src/dotmd/search/surreal_contract.py` — canonical enums and gate behavior.
- `backend/src/dotmd/search/surreal_parity.py` — reusable callable/report patterns and deterministic tie handling.
- `backend/tests/search/test_surreal_contract.py` and `backend/tests/search/test_surreal_retrieval_parity.py` — existing contract and comparison invariants.
- `backend/devtools/reranker_quality_bench.py` — JSONL label parsing, `pool_miss`, summary generation.
- `.planning/milestones/v1.4-phases/21-reranker-quality-benchmark/21-LABELS.jsonl` and `21-LABELS-REVIEW.md` — approved evaluation-data pattern.
- `.planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-03-RETRIEVAL-PARITY.md` and `38-RECOMMENDATION.md` — why exact-parity gating is insufficient for v1.8.

### Secondary (MEDIUM confidence)

- `https://docs.pytest.org/en/stable/example/parametrize.html` — parametrized tests with stable IDs.
- `https://docs.pytest.org/en/stable/example/markers.html` — registering custom markers.
- `https://docs.pytest.org/en/stable/how-to/tmp_path.html` — file-backed temporary fixtures.
- `https://jsonlines.org/` — JSONL format rules.

### Tertiary (LOW confidence)

- None.

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH - all recommended components already exist in the repo or project toolchain; no new package selection is required. [CITED: backend/pyproject.toml; justfile]
- Architecture: HIGH - Phase 40 boundary is explicit across roadmap, requirements, and Phase 39 handoff docs. [CITED: .planning/ROADMAP.md; .planning/REQUIREMENTS.md; .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md]
- Pitfalls: HIGH - they derive directly from Phase 38 parity failures, Phase 39 policy changes, and existing source-ref/search contracts. [CITED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-03-RETRIEVAL-PARITY.md; backend/src/dotmd/core/models.py; backend/src/dotmd/api/service.py]

**Research date:** 2026-06-13
**Valid until:** 2026-07-13

## RESEARCH COMPLETE
