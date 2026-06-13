# SurrealDB Evaluation Harness

Phase 40 adds a repo-local quality harness for the v1.8 SurrealDB cutover.
It evaluates captured old-stack versus candidate result rows against an approved
golden corpus and reports only user-visible retrieval differences.

## Scope

This harness is intentionally narrow.

- The current SQLite/sqlite-vec/FTS5 + FalkorDB stack is baseline/evaluator evidence only.
- Phase 40 does not add real SurrealDB schema/import/retrieval code.
- Phase 40 does not run production shadow traffic.
- Phase 40 does not reindex, rechunk, reembed through TEI, or re-extract entities.
- Phase 40 does not add runtime fallback, compatibility mode, or legacy-preservation shims.

## Inputs

The runner compares three required JSONL inputs and one optional JSONL input.

- Golden corpus: `backend/devtools/surreal_golden_queries.jsonl`
- Baseline result capture: operator-supplied JSONL with old-stack results
- Candidate result capture: operator-supplied JSONL with Surreal/native candidate results
- Acceptance metadata: optional JSONL used only when a reviewer explicitly accepts a raw regression or unclear row

Every file is parsed line by line as UTF-8 JSONL. Duplicate query IDs, unknown
categories, unknown retrieval surfaces, and malformed JSON objects fail fast
with a line-numbered `ValueError`.

## Golden Query Schema

Each golden row contains:

- `id`: stable query identifier such as `sq-001`
- `query`: the user-facing search text
- `category`: one of `title-heavy`, `tag-heavy`, `body-heavy`, `semantic`, `graph-entity`, `hybrid`, `source-ref`, `mixed-ru-en`
- `primary_surface`: one of the Phase 39 retrieval surfaces, serialized from `RetrievalSurface`
- `languages`: language tags for reviewer context
- `relevant`: approved result refs
- `maybe`: optional weaker-but-acceptable result refs
- `expected_engines`: human debugging hint only
- `broad_query`: marks intentionally ambiguous queries
- `notes`: reviewer rationale

Relevant/maybe labels use public refs, ideally `filesystem:/mnt/...`, with an
optional `contains` anchor:

```json
{
  "ref": "filesystem:/mnt/knowledgebase/voicenotes/example/transcript.md",
  "contains": "needle phrase"
}
```

`contains` is not a permission to read arbitrary files at report time. It is a
human or captured-evidence anchor only.

## Captured Result Schema

Baseline and candidate result JSONL rows are typed through `EvalResult` and
contain:

- `query_id`
- `query`
- `category`
- `primary_surface`
- `top_refs`
- `matched_engines`
- optional `snippets_by_ref`
- optional `read_evidence_by_ref`
- optional `unreadable_refs`

The runner never dereferences label refs or reads corpus filesystem paths.
`contains` is checked only against already-supplied `snippets_by_ref` or
`read_evidence_by_ref`. When no evidence is supplied, `contains` remains review
metadata and does not trigger an automatic improvement/regression/unclear
decision by itself.

## Diff Classification

`backend/src/dotmd/search/surreal_eval.py` imports the Phase 39 policy enums:

- `AcceptedDifference.IMPROVEMENT`
- `AcceptedDifference.HARMLESS_REORDER`
- `AcceptedDifference.REGRESSION`
- `AcceptedDifference.UNCLEAR`

It maps them to raw cutover gates via
`default_surreal_retrieval_contract().cutover_gate_for(...)`:

- `improvement` -> `allow`
- `harmless_reorder` -> `allow`
- `regression` -> `block`
- `unclear` -> `requires_acceptance`

Automatic triggers are intentionally conservative:

- Gained approved relevant refs without losing approved refs => `improvement`
- Same approved accepted set with ordering changes => `harmless_reorder`
- Lost approved refs or unreadable approved refs => `regression`
- Broad misses, conflicting evidence, or ambiguous changes => `unclear`

Exact rank parity is not the goal.

## Acceptance Metadata

Acceptance metadata is separate from raw classification. Each acceptance row
must include:

- `query_id`
- `accepted_by`
- `accepted_reason`

Accepted rows preserve the raw `classification` and raw `cutover_gate` in the
JSONL output. Acceptance only changes aggregate accounting:

- accepted regressions do not count as unresolved blockers
- accepted unclear rows do not count as unresolved unclear items
- accepted rows remain auditable in both JSONL and Markdown output

## Output JSONL

The runner writes one JSON object per query with stable keys:

- `query_id`
- `query`
- `category`
- `baseline_refs`
- `candidate_refs`
- `lost_relevant_refs`
- `gained_relevant_refs`
- `rank_deltas`
- `matched_engines`
- `classification`
- `cutover_gate`
- `rationale_codes`
- `accepted_by`
- `accepted_reason`

`matched_engines` is keyed by public result ref and records separate baseline
and candidate engine arrays:

```json
{
  "filesystem:/mnt/example.md": {
    "baseline": ["keyword"],
    "candidate": ["keyword", "semantic"]
  }
}
```

JSONL is written with `ensure_ascii=False` and `sort_keys=True` so Unicode
queries and deterministic diffs stay intact.

## Markdown Summary

The Markdown summary is intentionally short and operator-friendly:

- classification counts
- accepted semantic changes
- unresolved blockers
- unresolved unclear rows
- aggregate pass/fail status

## Exit Codes

- Exit `0`: no unresolved blocking rows and no unresolved unclear rows remain
- Exit `1`: at least one unresolved `regression` or unresolved `unclear` row remains

This means a plan or later migration phase can block on the summary without
requiring exact baseline rank parity.

## CLI Usage

From `backend/`:

```bash
uv run python devtools/surreal_eval_runner.py \
  --golden-queries devtools/surreal_golden_queries.jsonl \
  --baseline-results /path/to/baseline.jsonl \
  --candidate-results /path/to/candidate.jsonl \
  --output-jsonl /path/to/surreal-diffs.jsonl \
  --summary-markdown /path/to/surreal-diffs.md
```

With an explicit acceptance ledger:

```bash
uv run python devtools/surreal_eval_runner.py \
  --golden-queries devtools/surreal_golden_queries.jsonl \
  --baseline-results /path/to/baseline.jsonl \
  --candidate-results /path/to/candidate.jsonl \
  --acceptance /path/to/accepted-diffs.jsonl \
  --output-jsonl /path/to/surreal-diffs.jsonl \
  --summary-markdown /path/to/surreal-diffs.md
```

## Operational Notes

- Keep corpus refs on real indexed public surfaces, preferably `filesystem:/mnt/...`.
- Review `backend/devtools/surreal_golden_queries_review.md` whenever the corpus changes.
- Treat Gmail/other federated provider failures as separate runtime issues; they are not part of the Phase 40 harness contract unless their captured results are intentionally supplied as evaluation inputs.
