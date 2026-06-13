# SurrealDB Production Migration Runbook

Phase 41 adds repo-local migration tooling and evidence artifacts for the
v1.8 SurrealDB cutover. It does not add retrieval behavior, shadow-run
execution, production cutover, runtime fallback, or legacy deletion.

## Scope

This runbook is for operators and developers preparing and reviewing a
production-grade migration rehearsal.

- Old SQLite/sqlite-vec/FTS5, FalkorDB, and feedback-provider outputs are read-only migration sources and evidence only.
- Stored embeddings are reused from sqlite-vec payloads; default TEI reembedding, rechunking, GLiNER re-extraction, and indexing-pipeline recomputation are forbidden.
- Feedback rows must come from the supported provider/exporter path, not direct `feedback.db` queries.
- Fresh installation of the standalone `surreal` CLI or any new package is out of scope here and requires human legitimacy verification first.

## Operator Flow

Run the steps in order.

1. Collect explicit source artifacts.
   - Create a copied SQLite snapshot.
   - Export graph rows to JSON.
   - Export feedback rows to JSON through the supported provider/exporter path.
   - Record or regenerate the source-capture manifest with timestamps, checksums, counts, and skew policy.

2. Run `plan`.
   - Builds the Phase 41 manifest.
   - Records expected counts and unsupported categories.
   - Does not mutate the target.

3. Run `dry-run`.
   - Reuses the same inputs and manifest surface.
   - Optionally inspects target pre-counts.
   - Does not write target rows.

4. Run `apply` only when target mode, target URL, overwrite policy, and gate inputs are explicit.
   - `embedded-local` apply requires a passed gate report.
   - Default overwrite policy is `refuse`.
   - Destructive replacement requires `explicit-replace`.

5. Run `verify`.
   - `cheap` verification checks counts, schema version, embedding reuse, and no-recompute evidence.
   - `deep` verification adds sample checks for graph relations, feedback, cursors, and checkpoints.

6. Emit evidence artifacts.
   - JSON evidence report
   - Markdown evidence summary
   - Restore manifest JSON
   - Optional migration manifest JSON
   - Optional source-capture manifest JSON

7. Retain restore and rollback evidence.
   - Verified restore evidence must include method, counts, smoke result, rehearsal target, and notes.
   - CLI absence is recorded as evidence. It is never silently treated as success.

## CLI Surface

Run from `backend/`.

```bash
uv run python devtools/surreal_migration_runner.py \
  --mode apply \
  --target-mode embedded-local \
  --sqlite-snapshot /path/to/index.snapshot.db \
  --source-capture-manifest-json /path/to/source-capture.json \
  --graph-export-json /path/to/graph-export.json \
  --feedback-export-json /path/to/feedback-export.json \
  --target-url surrealkv:///path/to/phase41-target.db \
  --target-namespace dotmd \
  --target-database phase41_migration \
  --gate-report /path/to/38-05-EMBEDDED-SAFETY-GATE.md \
  --overwrite-policy refuse \
  --verification-depth deep \
  --manifest-json /path/to/migration-manifest.json \
  --report-json /path/to/migration-report.json \
  --report-markdown /path/to/migration-report.md \
  --restore-manifest-json /path/to/restore-manifest.json \
  --owner-id ops-user \
  --max-report-samples 2 \
  --redact-report-samples
```

Supported flags:

- `--mode plan|dry-run|apply|verify|report`
- `--target-mode embedded-local|remote-service`
- `--sqlite-snapshot`
- `--source-capture-manifest-json`
- `--target-url`
- `--target-namespace`
- `--target-database`
- `--graph-export-json`
- `--feedback-export-json`
- `--gate-report`
- `--overwrite-policy refuse|explicit-replace`
- `--verification-depth cheap|deep`
- `--manifest-json`
- `--report-json`
- `--report-markdown`
- `--restore-manifest-json`
- `--owner-id`
- `--max-report-samples`
- `--redact-report-samples`

## Safety Rules

- `apply` fails closed without explicit source inputs, target inputs, and required gate inputs.
- `embedded-local` apply requires gate evidence before any write is attempted.
- Populated targets are blocked by default.
- `explicit-replace` is the only destructive overwrite path.
- Malformed graph or feedback JSON fails before migration execution.
- JSON syntax errors are reported with path, line, and column.
- Semantic row-shape errors are reported with path, category, row index, and field name.

## Source-Capture Inputs

The source-capture manifest should preserve:

- SQLite snapshot path, timestamp, checksum, and counts
- Graph export path, exported timestamp, checksum, and counts
- Feedback export path, exported timestamp, checksum, and counts
- skew policy
- source identity

These artifacts define the migration evidence boundary. Do not point the runner
at live mutable production stores as if they were snapshots.

## Evidence Report Fields

Phase 41 evidence reports record:

- `report_status`
- `schema_version`
- `mode`
- `target_mode`
- `overwrite_policy`
- `target`
- `source_capture_manifest`
- `phase_checkpoints`
- `expected_counts`
- `actual_counts`
- `cheap_invariants`
- `deep_sample_checks`
- `embedding_reuse_verified`
- `no_recompute_verified`
- `unsupported_categories`
- `redaction_policy`
- `sample_limit`
- `restore_manifest`
- `rollback_evidence`
- `partial_writes_present`
- `last_successful_phase`
- `failed_phase`
- `unresolved_blockers`
- `recommendation`

Restore status values are:

- `blocked`
- `restore_required`
- `verified_with_cli`
- `verified_with_fallback`
- `not_verified`

## Partial Failure Semantics

- `partial_writes_present` means at least one migration phase wrote data before a failure or verification block.
- `last_successful_phase` identifies the last completed phase checkpoint.
- `failed_phase` identifies the first failed phase checkpoint when known.
- Reports must not claim success when restore evidence is absent after apply, when phase checkpoints failed or stayed unverified, when embedding reuse is unverified, or when no-recompute evidence is false.

## Report Redaction And Unicode

Evidence JSON is written with `ensure_ascii=False`. Reports may contain
non-ASCII production-derived refs, feedback text, and graph metadata. Choose
report paths intentionally and use `--max-report-samples` plus
`--redact-report-samples` when reports should not include readable samples.

## Restore And Rollback Evidence

- Prefer official `surreal export` / `surreal import` evidence when that CLI is already available and verified.
- If the CLI is absent, record that fact explicitly.
- Fallback evidence only counts as verified restore when a rehearsal target is restored and counts plus smoke verification pass.
- Never mark restore success from CLI absence alone.

## Not Implemented In Phase 41

- Real Surreal retrieval semantics
- Shadow-run quality gates
- Production runtime cutover
- Runtime fallback backend behavior
- Legacy SQLite/Falkor/Ladybug removal
