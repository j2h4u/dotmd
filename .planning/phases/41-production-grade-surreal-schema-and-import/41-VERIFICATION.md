---
phase: 41-production-grade-surreal-schema-and-import
verified: 2026-06-13T19:19:50Z
status: passed
score: 11/11 must-haves verified
overrides_applied: 0
---

# Phase 41: Production-grade Surreal schema and import Verification Report

**Phase Goal:** Convert the Phase 38 schema/import proof into production migration tooling that preserves existing data where practical.
**Verified:** 2026-06-13T19:19:50Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Harden the Phase 38 proof into a production schema catalog. | ✓ VERIFIED | `build_dotmd_surreal_schema_plan()` defines the Phase 41 catalog with required tables including `chunk_file_bindings`, relation metadata, flexible JSON fields, and stable unsupported categories in [backend/src/dotmd/storage/surreal_schema.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal_schema.py:259). |
| 2 | Schema application is inspectable, idempotent, and fail-closed on mismatched targets. | ✓ VERIFIED | `define_dotmd_surreal_schema()` returns machine-readable metadata and blocks `SCHEMALESS`/newer/incompatible targets via explicit apply statuses in [backend/src/dotmd/storage/surreal_schema.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal_schema.py:615) and [backend/src/dotmd/storage/surreal_schema.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal_schema.py:697). |
| 3 | Existing stored categories are preserved in the target schema where practical. | ✓ VERIFIED | The schema and migration code cover documents, source units, chunks, provenance, chunk-file bindings, bindings, fingerprints, embeddings, graph entities/relations, feedback, cursors, and checkpoints; tests assert those categories and fields in [backend/tests/storage/test_surreal_schema_definition.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/storage/test_surreal_schema_definition.py:46) and [backend/tests/storage/test_surreal_storage_contract.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/storage/test_surreal_storage_contract.py:441). |
| 4 | Default migration is transform-first and forbids recomputation. | ✓ VERIFIED | `build_surreal_migration_manifest()` marks `recompute_forbidden=True`, and `run_surreal_migration()` returns `recompute_blocked` if recompute steps are requested in [backend/src/dotmd/ingestion/migrate_surreal.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/ingestion/migrate_surreal.py:739) and [backend/src/dotmd/ingestion/migrate_surreal.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/ingestion/migrate_surreal.py:1137). |
| 5 | Source-capture evidence is mandatory and records timestamps, checksums, counts, skew policy, and source identity. | ✓ VERIFIED | `_build_source_capture_manifest()` records all capture fields before plan/dry-run/apply/verify work in [backend/src/dotmd/ingestion/migrate_surreal.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/ingestion/migrate_surreal.py:702). |
| 6 | Apply mode refuses unsafe target writes unless overwrite policy and target-mode gates are explicit. | ✓ VERIFIED | `run_surreal_migration()` rejects invalid targets, enforces embedded gate evidence, blocks `SCHEMALESS` targets without replacement, and refuses populated targets under default policy in [backend/src/dotmd/ingestion/migrate_surreal.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/ingestion/migrate_surreal.py:1092) and [backend/src/dotmd/ingestion/migrate_surreal.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/ingestion/migrate_surreal.py:1174). |
| 7 | Apply mode records named checkpoints and preserves embeddings/source data instead of recomputing them. | ✓ VERIFIED | Per-phase checkpoints for schema/documents/source_units/chunks/chunk-file-bindings/provenance/bindings/fingerprints/embeddings/vector-components/graph/feedback/cursors/checkpoints are built and written in [backend/src/dotmd/ingestion/migrate_surreal.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/ingestion/migrate_surreal.py:1216). Embedding reuse is verified by comparing `text_hash`, `vector_rowid`, and vector payloads in [backend/src/dotmd/ingestion/migrate_surreal.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/ingestion/migrate_surreal.py:1033). |
| 8 | Partial failures leave explicit restore-required evidence and avoid silent cleanup. | ✓ VERIFIED | Failure handling sets `partial_writes_present`, `restore_required`, `cleanup_attempted=false`, and `rollback_evidence="no_automatic_cleanup"` in [backend/src/dotmd/ingestion/migrate_surreal.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/ingestion/migrate_surreal.py:1329). |
| 9 | Maintainers can emit JSON and Markdown evidence reports that classify restore/recovery safety correctly. | ✓ VERIFIED | `build_surreal_restore_manifest()`, `classify_surreal_migration_report()`, and `write_surreal_migration_evidence_reports()` enforce verified restore semantics and emit JSON with `ensure_ascii=False` plus Markdown summaries in [backend/src/dotmd/storage/surreal_ops.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal_ops.py:497), [backend/src/dotmd/storage/surreal_ops.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal_ops.py:555), and [backend/src/dotmd/storage/surreal_ops.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal_ops.py:658). |
| 10 | A repo-local devtool runner exposes explicit plan/dry-run/apply/verify/report modes and safe apply gating. | ✓ VERIFIED | `run_migration_command()` requires explicit source-capture, target, and gate inputs for apply and writes manifest/report artifacts; `build_parser()` exposes the planned flags in [backend/devtools/surreal_migration_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/devtools/surreal_migration_runner.py:367) and [backend/devtools/surreal_migration_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/devtools/surreal_migration_runner.py:474). |
| 11 | Phase 41 stayed inside scope: schema/import/evidence/devtool/runbook only, with no retrieval, shadow-run, cutover, runtime fallback, or legacy deletion implementation. | ✓ VERIFIED | The only phase artifacts live in storage, ingestion, devtools, tests, and docs; the runbook explicitly marks retrieval/shadow-run/cutover/fallback/deletion as out of scope in [docs/surrealdb-production-migration.md](/home/j2h4u/repos/j2h4u/dotmd/docs/surrealdb-production-migration.md:3) and [docs/surrealdb-production-migration.md](/home/j2h4u/repos/j2h4u/dotmd/docs/surrealdb-production-migration.md:187). No Phase 41 files add search/retrieval code paths. |

**Score:** 11/11 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `backend/src/dotmd/storage/surreal_schema.py` | Production schema catalog and apply-status logic | ✓ VERIFIED | 740 lines; substantive table catalog, validation, versioning, and apply-status logic. |
| `backend/src/dotmd/storage/surreal.py` | Storage helpers wired to Phase 41 schema and centralized record-id encoding | ✓ VERIFIED | Re-exports `define_dotmd_surreal_schema`, enumerates schema-owned tables, and writes chunk-file bindings during chunk import. |
| `backend/src/dotmd/ingestion/migrate_surreal.py` | Production migration manifest/apply/verify runner | ✓ VERIFIED | 1359 lines; substantive manifest, import, verification, gating, and partial-failure handling. |
| `backend/src/dotmd/storage/surreal_ops.py` | Restore/evidence/report helpers | ✓ VERIFIED | 1236 lines; substantive restore classification, report generation, and evidence gating. |
| `backend/devtools/surreal_migration_runner.py` | Operator CLI for plan/dry-run/apply/verify/report | ✓ VERIFIED | 547 lines; substantive argparse surface, artifact writing, and safe-apply behavior. |
| `docs/surrealdb-production-migration.md` | Phase 41 runbook and scope boundary | ✓ VERIFIED | 193 lines; documents operator flow, flags, evidence fields, failure semantics, and explicit non-goals. |
| `backend/tests/storage/test_surreal_schema_definition.py` | Schema contract coverage | ✓ VERIFIED | Focused tests cover categories, relation modeling, flexible fields, idempotency, and mismatch behavior. |
| `backend/tests/ingestion/test_surreal_production_migration.py` | Migration contract coverage | ✓ VERIFIED | Focused tests cover source capture, checkpoints, overwrite policy, no-recompute defaults, and partial failures. |
| `backend/tests/storage/test_surreal_ops_safety.py` | Restore/report safety coverage | ✓ VERIFIED | Focused tests cover restore classification, false-success blocking, and report safety. |
| `backend/tests/devtools/test_surreal_migration_runner.py` | Runner CLI coverage | ✓ VERIFIED | Focused tests cover flags, malformed JSON handling, report writing, Unicode, and unsafe apply rejection. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `backend/src/dotmd/storage/surreal.py` | `backend/src/dotmd/storage/surreal_schema.py` | import and re-export of schema helpers | ✓ VERIFIED | Manual check at [backend/src/dotmd/storage/surreal.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal.py:14). `verify.key-links` missed this because the import is multiline. |
| `backend/tests/storage/test_surreal_schema_definition.py` | `backend/src/dotmd/storage/surreal_schema.py` | direct schema-plan/apply-status assertions | ✓ VERIFIED | Tests import and exercise `build_dotmd_surreal_schema_plan()`, `define_dotmd_surreal_schema()`, and `validate_dotmd_surreal_schema_plan()`. |
| `backend/src/dotmd/ingestion/migrate_surreal.py` | `backend/src/dotmd/storage/surreal_schema.py` | schema version and plan consumed by manifest/apply | ✓ VERIFIED | `SURREAL_SCHEMA_VERSION` drives payloads and manifest/report generation; apply uses `define_dotmd_surreal_schema()`. |
| `backend/src/dotmd/ingestion/migrate_surreal.py` | `backend/src/dotmd/storage/surreal.py` | uses metadata/vector/graph/feedback stores during apply | ✓ VERIFIED | Store classes are imported at [backend/src/dotmd/ingestion/migrate_surreal.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/ingestion/migrate_surreal.py:14) and invoked across the phase writers at [backend/src/dotmd/ingestion/migrate_surreal.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/ingestion/migrate_surreal.py:1250). |
| `backend/devtools/surreal_migration_runner.py` | `backend/src/dotmd/ingestion/migrate_surreal.py` | runner builds config, calls migration, emits evidence | ✓ VERIFIED | Manual check at [backend/devtools/surreal_migration_runner.py](/home/j2h4u/repos/j2h4u/dotmd/backend/devtools/surreal_migration_runner.py:421). `verify.key-links` missed the multiline import pattern. |
| `backend/src/dotmd/storage/surreal_ops.py` | `backend/src/dotmd/ingestion/migrate_surreal.py` | classifies `SurrealMigrationReport`-compatible output | ✓ VERIFIED | Evidence classification consumes runner output fields at [backend/src/dotmd/storage/surreal_ops.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal_ops.py:555). |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| `backend/src/dotmd/ingestion/migrate_surreal.py` | `expected_counts` / `source_capture_manifest` | Read-only SQLite snapshot + graph export JSON + feedback export JSON | Yes | ✓ FLOWING |
| `backend/src/dotmd/ingestion/migrate_surreal.py` | `actual_counts`, `stored_embeddings`, relation/feedback/cursor/checkpoint samples | Target Surreal tables via `SurrealConnection.scan_table()` | Yes | ✓ FLOWING |
| `backend/devtools/surreal_migration_runner.py` | `evidence`, `restore_manifest` | `run_surreal_migration()` + `_rehearse_restore()` | Yes | ✓ FLOWING |
| `backend/src/dotmd/storage/surreal.py` | `chunk_file_bindings` rows | `replace_chunk_rows()` writes bindings extracted from chunk payloads | Yes | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Full repo verification gate stays green | `cd backend && just verify` | `615 passed, 36 deselected, 1 warning` after format/lint/type/import/actionlint/compile/vulture gates | ✓ PASS |
| Phase 41 focused tests still pass | `cd backend && uv run pytest tests/storage/test_surreal_schema_definition.py tests/ingestion/test_surreal_production_migration.py tests/storage/test_surreal_ops_safety.py tests/devtools/test_surreal_migration_runner.py -q` | `31 passed in 1.69s` | ✓ PASS |
| Manifest generation preserves migration counts and no-recompute defaults | `cd backend && uv run python - <<'PY' ... build_surreal_migration_manifest(...) ... PY` | Output included `schema_version=41.1.0`, `chunk_file_bindings=2`, `graph_relations=2`, `feedback=2`, `recompute_forbidden=true` | ✓ PASS |
| Apply path writes real data into schema-owned target tables | `cd backend && uv run python - <<'PY' ... run_surreal_migration(...APPLY...) ... scan tables ... PY` | `STATUS applied VERIFIED True ERRORS []`; target counts included `chunks 2`, `chunk_file_bindings 2`, `embeddings 2`, `relations 2`, `feedback 2`, `cursors 2`, `checkpoints 1` | ✓ PASS |

### Probe Execution

| Probe | Command | Result | Status |
| --- | --- | --- | --- |
| Step 7c | `find scripts -path '*/tests/probe-*.sh' -type f` | No probe scripts found in this repo | SKIPPED |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| `SURR-MIG-01` | `41-01`, `41-02` | Production Surreal schema represents required migration categories. | ✓ SATISFIED | Schema catalog covers all required categories and validation fails on omissions; apply spot-check wrote the preserved category rows. |
| `SURR-MIG-02` | `41-02`, `41-03` | Migration imports existing stored data transform-first and avoids default recomputation. | ✓ SATISFIED | Manifest hard-codes `recompute_forbidden=True`; apply path blocks requested recompute steps; verification checks embedding reuse instead of recomputation. |
| `SURR-MIG-03` | `41-02`, `41-03` | Migration has explicit backup/restore/rollback and partial-failure semantics before cutover. | ✓ SATISFIED | Restore manifests, evidence classification, unsafe-apply gating, and partial-write reporting are implemented and tested; production cutover itself remains Phase 44 by roadmap. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| `-` | `-` | No blocking debt markers or placeholder implementations found in inspected Phase 41 files | ℹ️ Info | No `TODO`/`FIXME`/`XXX` markers or user-visible stub code were present in the verified artifact set. |

### Human Verification Required

None. This phase delivers repo-local schema/import/evidence tooling, and the phase contract was fully verified through code inspection plus automated checks without requiring visual or live-production UAT.

### Gaps Summary

No actionable gaps found. The only automated verification misses were two multiline-import regex false negatives in `verify.key-links`; manual inspection confirmed the wiring in `surreal.py` and `surreal_migration_runner.py`.

---

_Verified: 2026-06-13T19:19:50Z_  
_Verifier: the agent (gsd-verifier)_
