---
phase: 28
reviewers: [codex, opencode]
reviewed_at: 2026-05-07T23:34:00+05:00
cycle: 2
replan_commit: 587cae3
plans_reviewed:
  - .planning/phases/28-application-source-provider-contract/28-01-provider-models-and-protocol-PLAN.md
  - .planning/phases/28-application-source-provider-contract/28-02-source-state-and-fingerprint-storage-PLAN.md
  - .planning/phases/28-application-source-provider-contract/28-03-fixture-provider-contract-PLAN.md
  - .planning/phases/28-application-source-provider-contract/28-04-docs-and-telegram-contract-note-PLAN.md
---

# Cross-AI Plan Review - Phase 28

Cycle 2 review after replan commit `587cae3`.

## Codex Review

### Summary

Cycle 2 resolves both prior HIGH concerns. The replan now has concrete mitigation and verification for the `SourceUnit.updated_at` blast radius and for metadata-store transaction convention mismatch. I do not see a remaining HIGH concern in the current plans.

### Strengths

- Prior HIGH resolved: `28-01-provider-models-and-protocol-PLAN.md` now requires `rg -n "SourceUnit\\(" backend/src backend/tests` before editing, updates all stale constructors in the same task, and runs regression tests for filesystem and service search.
- Prior HIGH resolved: `28-02-source-state-and-fingerprint-storage-PLAN.md` now explicitly audits existing `metadata.py` write conventions and requires `commit_source_checkpoint(..., *, conn)` and fingerprint writes to avoid internal `commit()`.
- Cursor semantics are much stronger: `checkpoint_cursor` is separated from `next_cursor`, rollback behavior is tested, and `save_next_cursor` is explicitly forbidden.
- The phase boundary is preserved: no direct Telegram client, no private `mcp-telegram` SQLite coupling, no lifecycle/delete semantics promoted prematurely, and no full reindex path.
- Fixture validation in `28-03` usefully exercises window reads, implicit root units, cursor parsing, positive limits, and idempotent fingerprint replay.
- `28-04` closes the documentation gap with concrete payload examples and requires validation evidence in a phase summary.

### Concerns

- **MEDIUM:** Plan 01 may under-spec import/export location for new core models. `28-01` adds `ApplicationSourceDescription`, `ApplicationSourceChange`, `ApplicationSourceChangeBatch`, and `SourceUnitWindow` to `backend/src/dotmd/core/models.py`, while `28-02` and `28-03` depend on those types from storage and fixture code. The plan verifies file contents and tests, but does not explicitly require checking `__all__`, package exports, or existing import style if this project has public model re-export patterns.
- **MEDIUM:** Fingerprint helper return semantics need a transaction-sensitive read path. `28-02` says `get_source_unit_fingerprint` reads from `self._conn` by default and may accept optional `conn` "only if needed." Since `upsert_source_unit_fingerprint` is explicitly transaction-bound, tests that inspect uncommitted state or callers that batch decisions inside one transaction may need the optional `conn` consistently.
- **LOW:** Docs JSON validation is slightly soft. `28-04` requires strict JSON examples, but the summary acceptance allows "examples are prose-only and not fenced as JSON." That fallback weakens the contract note. Since Task 1 explicitly requires example JSON, the summary should require validation of fenced JSON examples rather than allowing prose-only examples.

### Suggestions

- In `28-01`, add a verification line for model import paths, for example running the provider test from a clean import of `dotmd.ingestion.source_provider`.
- In `28-02`, make optional `conn` explicit for read helpers that may be used inside a transaction.
- In `28-04`, require JSON fenced examples to be parsed successfully, rather than permitting prose-only examples.
- Consider a quick grep in docs/tests forbidding `export_documents` and `export_units` across all Phase 28 files, not only the provider module.

### Risk Assessment

Current residual risk is MEDIUM overall, mostly around execution precision rather than plan design. The two prior HIGH concerns are fully resolved in the current plan set, and I do not see unresolved or newly introduced HIGH concerns.

---

## OpenCode Review

### Summary

Phase 28's four plans are well-structured, correctly sequenced, and address all 23 locked decisions. Both prior-cycle HIGH concerns are fully resolved with concrete verification paths. No new HIGH concerns remain. A few minor observations are noted below.

### Prior HIGH Concerns: Resolution Status

#### Prior HIGH 1: SourceUnit.updated_at blast radius - RESOLVED

Live codebase verification (`rg -n "SourceUnit\\(" backend/src backend/tests`) confirms the only match is the class definition at `models.py:147`. Zero constructor call sites exist anywhere in `backend/src` or `backend/tests`. Plan 01 Task 1 explicitly instructs the executor to run this same audit first and update any constructors found in the same task. The verification section also runs regression tests (`test_source_filesystem.py`, `test_service_search.py`) to catch any downstream breakage. No blast radius exists, and the plan verifies it.

#### Prior HIGH 2: Storage helper conn handle convention mismatch - RESOLVED

Plan 02 now explicitly enumerates five existing method signatures to verify against (`upsert_source_document`, `upsert_resource_binding`, `set_resource_binding_active`, `delete_m2m_for_file`, `backfill_resource_bindings_from_source_documents`) and specifies three tiers matching existing convention exactly:

| Tier | Convention | Plan 02 Usage |
|---|---|---|
| Transactional writes | `conn: _SQLiteConn`, never commits | `commit_source_checkpoint` |
| Reads | `self._conn`, optional `conn` | `get_source_checkpoint` |
| Post-failure diagnostics | `conn: _SQLiteConn \| None`, commits when `conn is None` | `record_source_checkpoint_error` |

This matches the existing codebase pattern precisely.

### Strengths

1. Threat models are specific and actionable. Every HIGH threat has a concrete mitigation, not just "be careful." The threat about accidentally creating Telegram-only naming is explicitly tested via grep-based acceptance criteria.
2. Wave ordering is correct. Plan 01 models/protocol comes before Plan 02 storage, Plan 03 fixture proof, and Plan 04 docs.
3. Acceptance criteria are grep-verified. Each task has concrete grep/pytest acceptance checks. Negative checks such as no `export_documents`, no `save_next_cursor`, and no `telethon` are particularly valuable.
4. Plan 03 correctly separates test fixtures from production code. `FixtureApplicationSourceProvider` lives under `backend/tests/` while `source_provider.py` stays protocol-only.
5. Plan 04 `SUMMARY.md` self-check gate requires citing pre-existing ratchet failures with command output, preventing silent test debt accumulation.
6. Full-reindex safety is stated in every plan's must-haves with consistent "no `dotmd index --force`, no TEI re-embedding, no FTS/vector/graph rebuild" language.

### Concerns

- **MEDIUM:** Pre-existing `_SQLiteConn` vs `sqlite3.Connection` inconsistency in `backend/src/dotmd/storage/metadata.py:851,870`. `delete_chunk_provenance` and `delete_chunk_provenance_for_document` use `conn: sqlite3.Connection` while all other transactional write helpers use `conn: _SQLiteConn`. Plan 02's new helpers correctly use `_SQLiteConn`. The executor should be aware of this pre-existing inconsistency when testing.
- **LOW:** `read_unit_window` uses count-based `before`/`after` semantics while existing `DotMDService.read(ref, start, end)` uses line-number window semantics. This is by design, but Phase 29 will need to bridge between them.
- **LOW:** Empty batch `checkpoint_cursor` behavior is implicit. Plan 03 says `checkpoint_cursor="offset:<end>"` after each non-empty batch but does not explicitly state what empty batches return.
- **LOW:** `ApplicationSourceChangeBatch.checkpoint_cursor` can be `None` alongside non-empty `changes`. The fixture provider always sets it for non-empty batches, but there is no Pydantic validator enforcing this. This is acceptable for Phase 28.

### Suggestions

1. Consider adding `_SQLiteConn` to `delete_chunk_provenance` signatures if the executor touches those lines during Plan 02 work, but do not scope-creep; it is pre-existing and not blocking.
2. Plan 03 Task 2 could add one explicit test assertion that an empty `export_changes` batch returns `checkpoint_cursor=None`.

### Risk Assessment

| Area | Risk Level | Rationale |
|---|---:|---|
| Model changes breaking existing code | LOW | Zero `SourceUnit` constructors exist; plan verifies first |
| Storage convention mismatch | LOW | Plan 02 enumerates and matches existing three-tier pattern |
| Hidden full reindex | NONE | All four plans are additive models/protocol/fixtures/docs |
| Telegram-specific leakage | LOW | Grep-based negative acceptance criteria on every task |
| Cross-plan integration | LOW | Plan 03 depends on both 01 and 02 and exercises them together |
| Phase 29 handoff clarity | LOW | Plan 04 contract note has concrete JSON examples and scope exclusions |

**Verdict:** Plans are ready for execution. No HIGH concerns remain.

---

## Consensus Summary

Both reviewers agree that Cycle 2 resolves the two prior HIGH concerns from Cycle 1. The `SourceUnit.updated_at` blast radius is now mitigated by an explicit constructor audit plus earlier filesystem/service regression tests. The storage transaction-convention concern is now mitigated by a live-code convention audit and by helper signatures that distinguish transactional writes, reads, and post-failure diagnostics.

### Agreed Strengths

- The phase remains correctly scoped to provider contract, storage state, fixtures, and docs; it does not claim Telegram ingestion.
- The plans preserve the Telegram boundary: no direct Telegram API client, no Telethon ownership, and no private `mcp-telegram` SQLite reads.
- Cursor semantics are now explicit: `next_cursor` is not durable progress, and `checkpoint_cursor` is committed only after local persistence succeeds.
- Fixture validation is test-only and deterministic, which gives Phase 29 an executable contract without live Telegram dependency.
- Every plan states that no full reindex, TEI re-embedding, FTS rebuild, vector rebuild, or graph rebuild is required.

### Agreed Concerns

- **MEDIUM:** Execution should keep storage transaction/read helper signatures aligned with existing `metadata.py` conventions, including optional transaction-aware reads where needed.
- **LOW:** A small explicit empty-batch cursor assertion in Plan 03 would remove ambiguity around terminal fixture batches.

### Divergent Views

- Codex sees residual MEDIUM risk around model import/export location and JSON validation strictness; OpenCode did not flag those as current plan blockers.
- OpenCode flagged the existing `_SQLiteConn` versus `sqlite3.Connection` type inconsistency in two older metadata helpers as executor context; Codex did not treat that as a plan concern.

## Current HIGH Concerns

None.
