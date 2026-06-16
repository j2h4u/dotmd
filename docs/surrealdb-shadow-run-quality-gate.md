# SurrealDB Shadow Run Quality Gate

Phase 43 adds a repo-local runner for one bounded shadow-evidence window. It
ties together:

- Phase 40 golden-query diffing
- Phase 41 source-capture and migration evidence
- Phase 42 explicit Surreal retrieval overrides
- Phase 43 metric and acceptance-ledger artifacts

It does not cut production over to SurrealDB.

## Scope

- The current SQLite/sqlite-vec/FTS5 + FalkorDB stack remains baseline evidence only.
- The Surreal candidate remains an explicit rehearsal target only.
- No runtime default switch is introduced.
- No runtime fallback or compatibility shim is introduced.
- No legacy deletion path is introduced.
- No `dotmd index --force` is allowed here.
- No production restart is required for small evidence changes.
- No rechunking, reembedding, or entity re-extraction is part of the intended path.

## Operator Flow

1. Prepare one immutable expected-identity manifest.
   Use the Phase 41 source-capture workflow and keep the file as `source-capture-expected.json`.

2. Prepare one rehearsal old-stack copy.
   This is the baseline SQLite/FTS5/sqlite-vec side only, pointed to by `--baseline-rehearsal-path`.

3. Prepare one isolated Surreal candidate target.
   Reuse the Phase 41 migration evidence path and the Phase 42 explicit retrieval seam.

4. Prepare one candidate-config JSON.
   Required keys: `embedding_dimension`, `top_k`, `pool_size`.
   Optional key: `hnsw_ef`.

5. Prepare an acceptance ledger path.
   The runner keeps `accepted-diffs.jsonl` non-empty by writing one sentinel metadata row even when there are no accepted semantic differences yet.

6. Run the shadow runner.
   It captures baseline results, candidate results, diffs, summary output, source-capture evidence, and metric artifacts in one directory.

7. Review diffs and acceptance state.
   Phase 40 remains the diff taxonomy and gating source of truth.

## Rehearsal Path Contract

`--baseline-rehearsal-path` must point to a directory containing `index.db` that:

- is a regular file, not a symlink
- does not overlap the production `DOTMD_INDEX_DIR`
- does not overlap `/dotmd-index`
- passes `PRAGMA integrity_check`

Operators should produce the rehearsal copy from a copied snapshot, not from the
live mutable production directory. The intended sources are:

- SQLite backup API output
- `cp -r` of a stopped-container volume snapshot

The rehearsal `index.db` covers only the SQLite/FTS5/sqlite-vec side of the old
stack. The FalkorDB graph is isolated separately.

## Graph Isolation (Option A)

Phase 43 keeps graph coverage on both sides.

- The baseline graph is copied from the production `dotmd` graph to an isolated name with `GRAPH.COPY`.
- The default isolated name is `dotmd_shadow_baseline`.
- The isolation guard refuses any baseline graph name equal to `dotmd`.
- The baseline `DotMDService` binds to the isolated graph through `falkordb_graph_name`.
- The isolated baseline copy is torn down with `GRAPH.DELETE` after capture.
- The candidate graph side is the isolated Surreal namespace/database target, not production.

Because both sides stay graph-capable, the full 16-query golden corpus runs on
both sides with complete category coverage. There is no non-graph subset and no
graph-disabled marker in the artifact bundle.

## Baseline Binding

The runner derives the baseline service settings with:

```python
Settings.model_copy(
    update={
        "index_dir": <baseline_rehearsal_path>,
        "falkordb_graph_name": <isolated_baseline_graph>,
    }
)
```

This means:

- `index_db_path` resolves to the copied rehearsal `index.db`
- FalkorDB binds to the isolated copied graph, not the production `dotmd` graph
- env vars, TOML config, and live runtime config are not edited

Before baseline capture, the runner fails closed if the rehearsal copy does not
match `source-capture-expected.json` for:

- `chunk_strategy`
- `embedding_model`
- `expected_chunk_count`
- `expected_embedding_count`

## Input And Output Manifests

`--source-capture-manifest-json` is the immutable operator input. It should
point to `source-capture-expected.json`.

The runner writes a separate produced artifact:

- `source-capture.json`

That output file records the expected identity plus rehearsal file metadata and
the isolated baseline graph name used for the run. The input manifest is never
rewritten.

## Candidate Config JSON

`--candidate-config-json` must be a JSON object.

Allowed keys:

- `embedding_dimension`: required positive integer
- `hnsw_ef`: optional positive integer, defaults to `DEFAULT_HNSW_EF`
- `top_k`: required positive integer
- `pool_size`: required positive integer

Unknown keys are rejected. Non-integer or non-positive values are rejected.

Routing:

- `embedding_dimension` and `hnsw_ef` feed `build_surreal_native_engine_overrides()`
- `top_k` and `pool_size` feed the capture loop only

## Replay Query Descriptor

`--metrics-replay-queries` is a JSONL file path. Each row must contain:

- `query_id`
- `query`

Both must be non-empty strings, and `query_id` values must be unique. Malformed
rows fail closed with line-numbered errors.

## CLI Surface

Run from `backend/`.

```bash
uv run python devtools/surreal_shadow_runner.py \
  --artifacts-dir .planning/phases/43-shadow-run-and-quality-gate/artifacts \
  --golden-queries devtools/surreal_golden_queries.jsonl \
  --source-capture-manifest-json /path/to/source-capture-expected.json \
  --candidate-config-json /path/to/candidate-config.json \
  --baseline-rehearsal-path /path/to/rehearsal-index \
  --baseline-graph-name dotmd_shadow_baseline \
  --production-graph-name dotmd \
  --metrics-replay-queries /path/to/replay-queries.jsonl \
  --target-url surrealkv:///path/to/phase43-shadow.db \
  --target-namespace dotmd \
  --target-database phase43_shadow \
  --capture-baseline \
  --capture-candidate
```

Additional artifact override flags:

- `--baseline-results`
- `--candidate-results`
- `--accepted-diffs`
- `--shadow-diffs`
- `--shadow-summary`
- `--scale-metrics`
- `--memory-metrics`

Operational flags:

- `--verify-only`
- `--preflight-candidate-target`
- `--representative-corpus`

## Artifact Bundle

Default artifact names under `--artifacts-dir`:

- `source-capture.json`
- `baseline-results.jsonl`
- `candidate-results.jsonl`
- `accepted-diffs.jsonl`
- `shadow-diffs.jsonl`
- `shadow-summary.md`
- `scale-metrics.json`
- `memory-metrics.json`

The runner validates the bundle as a single unit under `--verify-only`.

## Acceptance Ledger

`accepted-diffs.jsonl` serves two roles:

- reviewer-owned acceptance rows for Phase 40 diff output
- one Phase 43 sentinel metadata row with replay-window and guardrail context

The sentinel row is stripped before the Phase 40 acceptance loader is invoked.
Only real `query_id` / `accepted_by` / `accepted_reason` rows are passed into
the Phase 40 evaluator.

## Artifact Handling

Phase 43 artifacts are local-only operational evidence by default.

- Do not commit raw production-derived refs or snippets unless they are intentionally included.
- Artifacts may contain production-derived refs, snippets, non-ASCII text, and metric samples.
- Choose report paths intentionally before export or review.
- Redact or relocate artifacts before sharing them outside the local operator workflow.

## Verify-Only Behavior

`--verify-only` checks the expected artifact bundle on disk and revalidates the
shadow diff output via a canonical `query_id`-keyed comparison. This is meant to
catch missing artifacts or tampered classifications without relying on raw file
ordering.

## Related Inputs

- Phase 40 diff harness: [docs/surrealdb-evaluation-harness.md](./surrealdb-evaluation-harness.md)
- Phase 41 migration evidence: [docs/surrealdb-production-migration.md](./surrealdb-production-migration.md)
- Phase 42 explicit Surreal override seam: `backend/src/dotmd/search/surreal_native.py`

## Not In Phase 43

- Production cutover
- Default runtime switch to SurrealDB
- Runtime fallback backend logic
- Compatibility shims
- Legacy backend deletion
