---
phase: 41
reviewers: [opencode, codex]
reviewed_at: 2026-06-13T11:09:03.633847Z
plans_reviewed:
  - .planning/phases/41-production-grade-surreal-schema-and-import/41-01-PLAN.md
  - .planning/phases/41-production-grade-surreal-schema-and-import/41-02-PLAN.md
  - .planning/phases/41-production-grade-surreal-schema-and-import/41-03-PLAN.md
---

# Cross-AI Plan Review — Phase 41

## OpenCode Review

Now I have complete context. Here is the review.

---

# Cross-AI Plan Review: Phase 41 — Production-grade Surreal schema and import

## Summary

The three plans form a well-structured TDD pipeline: schema catalog (41-01) → migration runner (41-02) → evidence/report/operator tooling (41-03). Scope discipline is the standout quality — every plan explicitly refuses to drift into retrieval, shadow-run, cutover, or legacy deletion, which matches the roadmap split perfectly. The core design decisions (REFUSE-by-default overwrite, phase checkpoints, no-recompute defaults, relation-table graph edges) are sound. The primary gaps are: (1) the `chunk_file_bindings` M2M table is present in the current schema but absent from the schema catalog task and migration phase checklist; (2) partial-failure cleanup semantics are unspecified — does the runner wipe what it wrote or leave it for operator recovery?; (3) the handoff contract between Phase 41 schema DDL and Phase 42 retrieval is implicit rather than explicit.

---

## Strengths

- **TDD discipline throughout**: every plan starts with RED tests, has explicit verification gates, and names specific test files.
- **Overwrite policy is correctly conservative**: default `REFUSE` with auditable `EXPLICIT_REPLACE` as the only write path — no accidental data loss.
- **Scope boundaries are airtight**: each plan's objectives, actions, and success criteria explicitly say "no retrieval, no cutover, no legacy deletion." The `must_haves.truths` sections reinforce this.
- **Threat modeling is thorough**: 5-6 STRIDE threats per plan with concrete mitigation plans, and a supply-chain threat row (`T-41-SC` / `T-41-SC` / `T-41-SC`) for package legitimacy.
- **Source-preserving architecture**: feedback via provider, graph via exporter, SQLite via copied snapshot — never raw/direct live-store access.
- **Research-driven anti-pattern warnings**: the Research file explicitly flags `clear_phase38_tables()` as prototype-only, warns against assuming SDK transactions on embedded, and lists four concrete pitfalls with detection criteria.
- **Pattern reuse from existing codebase**: PATTERNS.md maps every new file to a concrete analog and specifies exact line ranges to copy from.
- **Machine-readable outputs**: JSON report artifacts with explicit fields that Phase 43/44 can consume programmatically.
- **Graph edge preservation**: relation tables carry `rel_type`, `weight`, and `properties` instead of denormalizing edges into arrays — correct per SurrealDB's `TYPE RELATION` model.

---

## Concerns

### HIGH severity

1. **`chunk_file_bindings` missing from schema catalog and phase checklist**. The current `_SCHEMA_TABLES` in `surreal.py:43` includes `"chunk_file_bindings": "Phase 16 chunk/file/path/index many-to-many bindings"`. Plan 41-01's table list covers 16 tables but omits `chunk_file_bindings`. Plan 41-02's phase checkpoint list (schema, documents, source_units, chunks, provenance, bindings, fingerprints, embeddings, vector_components, graph, feedback, state) also omits it. The current `replace_chunk_rows()` in `surreal.py:340-359` writes bindings as a side effect — if the production runner doesn't have a `chunk_file_bindings` import phase, those rows are silently lost.

2. **Partial-failure cleanup behavior is undefined**. Plan 41-02 says failure returns `committed=false, restore_required=true, errors populated`. But it does not specify what happens to the *target store* state. Does the runner: (a) clear all previously written phases, (b) leave them intact for operator inspection, or (c) attempt per-phase rollback? The current prototype (`migrate_surreal.py:482-487`) calls `clear_phase38_tables()` on error — a full target wipe. The production runner must be explicit. Without a transactional wrapper (embedded SDK limitation confirmed in Research), partial writes are unrecoverable without a fresh target or per-table delete logic. This is the highest-impact gap for production use.

3. **Surreal `TYPE RELATION` constraint may be too narrow**. Plan 41-01 says `relations` is `TYPE RELATION IN sections OUT entities | tags ENFORCED`. The current Falkor graph exports relations where `source_id` is always a section (`chunk_id`) and `target_id` is an entity name or tag name — this matches the constraint today. But the `ENFORCED` keyword means Surreal will reject any relation that doesn't match these source/target table types at write time. If any edge exists in the export where the source isn't a `sections` record (e.g., a file node with edges imported separately), the import will fail. Consider `TYPE RELATION` without `ENFORCED` during migration, or verify the exporter output shape against this constraint.

### MEDIUM severity

4. **"state" checkpoint is ambiguous**. Plan 41-02 lists phase checkpoints ending with "state" — but the source has separate `cursors` and `checkpoints` categories. Are these one phase or two? The current runner imports them as separate steps (`replace_cursor_rows`, `replace_checkpoint_rows`). The checkpoint label should be explicit.

5. **No runtime `recompute_forbidden` enforcement**. Plan 41-02's tests monkeypatch TEI/GLiNER/chunker to fail. This proves the *test path* doesn't call them. But there is no production guard — nothing prevents a future code change from accidentally routing through recomputation. Add a boolean guard in the runner that raises if recomputation entry points are discovered during apply, not just in tests.

6. **Embedding vector length verification missing from success criteria**. Plan 41-02 says `verify_surreal_migration_target()` checks "text_hash/vector_rowid, and embedding vector lengths" — but the success criteria only mention "vector values survive import." The dimensional check (1024 floats for `multilingual-e5-large`) should be explicit in the acceptance criteria and tied to `vec_config_*` table dimensions from the source snapshot.

7. **Feedback row limit of 1001 is hardcoded and unused for production**. `load_feedback_rows_for_surreal()` (`migrate_surreal.py:359`) caps at 1001 rows and raises `RuntimeError` if exceeded. The production runner (41-02) will call this same loader. A production cutover could exceed this limit. The limit should be configurable or removed.

8. **`SCHEMAFULL` transition from existing `SCHEMALESS` tables**. If a target Surreal store already exists with `SCHEMALESS` tables (from Phase 38 prototype), the schema DDL will fail or behave unexpectedly when trying to redefine as `SCHEMAFULL`. The `EXPLICIT_REPLACE` policy covers record-level replacement but doesn't address whether the schema itself needs re-creation.

9. **Graph/feedback JSON export adapter underspecified in 41-03**. The devtool runner (`surreal_migration_runner.py`) accepts `--graph-export-json` and `--feedback-export-json` flags, but the current `run_surreal_import()` expects Python object interfaces (`graph_exporter.export_inventory()`, `feedback_provider.list_all()`). The adapter code that converts JSON files to compatible objects is not detailed in the plan.

### LOW severity

10. **`docs/` directory addition**. Plan 41-03 Task 3 creates `docs/surrealdb-production-migration.md`. AGENTS.md doesn't mention a `docs/` directory convention. Verify this is consistent with the repo's documentation structure. The AGENTS.md says "Never proactively create documentation files (*.md) or README files" — but this is part of a planned task, not a proactive creation, so it's fine.

11. **Dependency on Phase 39/40 artifacts**. Plan 41-01 depends on `["39-01", "40-01"]`. The requirements trace shows both as "Complete" — this is correct. But 41-02 depends on `["41-01"]` and its context includes `41-01-SUMMARY.md`, which is produced *after* 41-01 executes. If 41-01 hasn't run yet, 41-02's execute-phase step would fail to find the summary file. The executor should handle this, but worth noting.

12. **`stats` table disposition**. The migration map (38-01-MIGRATION-MAP.md:35) flags `stats` as "not safe to treat as canonical current state without separate producer validation." Plan 41-01's schema catalog should either omit `stats` or flag it as unsupported/non-critical, matching the Research's Pitfall 4 warning about smuggling non-D-01 caches into required success paths.

---

## Suggestions

1. **Add `chunk_file_bindings` to the schema catalog and migration phases.** Add it to the table list in 41-01 Task 1 behavior spec, the must_haves.truths field list, and add a `chunk_file_bindings` phase checkpoint in 41-02's phase list.

2. **Define partial-failure cleanup semantics explicitly.** In 41-02's `run_surreal_migration()` behavior spec, add: "On phase failure during APPLY, recorded phases remain in the target. The report includes `restore_required=true` and the failed phase name. The caller must decide: restore from backup, re-apply with `EXPLICIT_REPLACE`, or manually delete the partial data. The runner does not automatically clear the target." Or, if auto-cleanup is desired, specify which tables are cleaned.

3. **Relax the `relations` table constraint during migration.** Consider `TYPE RELATION` without `ENFORCED` for the schema DDL, or add a comment in the schema catalog noting the constraint depends on source data shape. Add a test that verifies all Falkor-exported relations can be written to the `relations` table.

4. **Rename "state" checkpoint to "cursors_and_checkpoints"** in 41-02's phase list for clarity.

5. **Add a runtime recompute guard.** In the migration runner, pass a `recompute_forbidden: bool = True` flag. Before any call to `_write_*` phases, if `recompute_forbidden` is True, assert that TEI/GLiNER/chunker entry-point modules are not imported or their callables are mocked. At minimum, add a `RuntimeError` guard at the runner entry.

6. **Make the feedback row limit configurable.** Add a `feedback_limit` parameter to `load_feedback_rows_for_surreal()` with a default of `None` (unlimited) for the production path, or `1001` for Phase 38 compatibility.

7. **Add vector dimension verification to 41-02 success criteria.** Explicitly check that all imported embedding vectors have `len(embedding) == expected_dimension` where `expected_dimension` is read from the source snapshot's `vec_config_*` table or from a known constant.

8. **Add snapshot freshness metadata to the migration manifest.** Record the SQLite snapshot's `mtime` or a `snapshot_created_at` timestamp in `SurrealMigrationManifest` so later phases can detect stale source data.

9. **Specify the Phase 42 input contract.** In 41-01's schema catalog, add a `phase_42_consumables` key to `define_dotmd_surreal_schema()` output, listing which tables/fields are expected by Phase 42's FTS indexer, vector indexer, and graph traversal.

10. **Bridge the JSON-export gap.** In 41-03 Task 2's implementation, specify adapter functions (`load_graph_rows_from_json()`, `load_feedback_rows_from_json()`) that produce the same dict shapes as `load_graph_rows_for_surreal()` and `load_feedback_rows_for_surreal()` from JSON files.

---

## Risk Assessment

**MEDIUM**

The plans are architecturally sound and well-scoped. The three issues that elevate this from LOW to MEDIUM:

1. **HIGH: Missing `chunk_file_bindings` in schema/migration** — this is a concrete data-loss risk for the M2M chunk↔file_path mapping that Phase 16 introduced.
2. **HIGH: Undefined partial-failure target state** — without transactional safety (confirmed absent in embedded SurrealDB), partial writes during apply are unrecoverable without operator intervention. The plans need to define whether the runner cleans up or leaves state for manual recovery.
3. **MEDIUM: Schema/relation constraint may reject real data** — `ENFORCED` on the `TYPE RELATION` definition could block import of valid source edges if the constraint doesn't match the actual export shape.

None of these are design-level flaws — they are specification gaps that can be addressed by tightening the task behavior descriptions before execution. The roadmap split (migration → retrieval → shadow → cutover → deletion) is correct, and these plans stay in their lane.

---

## Codex Review

## Plan 41-01 Review

**Summary**  
Strong schema-first plan. It correctly separates schema catalog work from retrieval/cutover and gives Phase 41 a durable contract for later import/reporting. Main risk is that the schema may become over-specified before the migration runner and Phase 42 retrieval prove exact table shapes, especially around graph relation endpoints, vector component modeling, and `SCHEMAFULL` metadata flexibility.

**Strengths**
- Clear SURR-MIG-01 traceability and good phase boundary discipline.
- Good TDD sequencing: schema tests before implementation.
- Keeps record-ID encoding centralized in `SurrealRecordIdCodec`.
- Explicitly prevents Phase 42+ retrieval work from leaking into schema work.
- Makes schema inspectable without a live SurrealDB target, which is useful for reports and review.

**Concerns**
- **MEDIUM:** `relations` table shape may be under-specified. The plan says `sections OUT entities | tags`, but requirements mention graph entities/relations broadly; if relations can connect chunks, documents, tags, source units, or entity nodes, this may constrain Phase 42 prematurely.
- **MEDIUM:** `SCHEMAFULL` everywhere can reject preserved legacy metadata unless fields like `properties`, `metadata`, and source payloads are intentionally flexible.
- **MEDIUM:** `vector_components` may create a large row explosion if used for every 1024-dim embedding. If this is only for verification/import shape, state that clearly; otherwise it may become a performance trap.
- **LOW:** The plan does not explicitly require schema evolution behavior: version mismatch handling, re-applying same DDL idempotently, or refusing unknown newer schema versions.
- **LOW:** Tests may assert too much exact DDL text, making harmless Surreal syntax/layout changes painful.

**Suggestions**
- Add acceptance criteria for schema idempotency and schema-version mismatch behavior.
- Clarify relation endpoints as either deliberately broad or deliberately minimal for Phase 41 import only.
- Keep flexible object fields for preserved source metadata/properties.
- Make `vector_components` optional/derived unless later phases truly need physical per-dimension records.

**Risk Assessment: MEDIUM**  
The plan is well-scoped, but schema contracts are expensive to unwind. The main risk is prematurely locking shapes before import and retrieval prove them.

## Plan 41-02 Review

**Summary**  
This is the core plan and it targets the right problems: replacing prototype wipe/replay semantics, preserving stored data, refusing unsafe overwrite, and producing phase checkpoints. It is comprehensive, but also high-complexity. The largest gaps are consistent snapshot semantics, migration locking/coordination with the running trickle indexer, and precise partial-failure language.

**Strengths**
- Correctly removes default whole-target clearing.
- Strong no-recompute posture with planned monkeypatch tests for TEI, GLiNER, chunking, and indexing pipeline calls.
- Good overwrite policy design: default refuse, explicit replace only with recorded pre-counts.
- Per-phase checkpoints are exactly the right primitive for partial failure and evidence.
- Verifies embeddings, graph metadata, feedback, cursors, checkpoints, and source identifiers.

**Concerns**
- **HIGH:** Snapshot consistency is not specified enough. SQLite snapshot, Falkor export, and feedback export can represent different moments in time unless the plan defines a capture boundary or accepts/report skews explicitly.
- **HIGH:** No explicit coordination with the running production trickle/indexer lock. Phase 41 must not mutate old stores, but even read/export consistency can be affected by live writes unless copied snapshots/exporters are bounded.
- **HIGH:** “committed false” after partial apply can be misleading if some Surreal writes actually landed. The report should distinguish `committed_success=false` from `partial_writes_present=true`.
- **MEDIUM:** APPLY requiring an “embedded safety gate” is good, but the plan does not define what happens for remote `ws/http` targets if endpoint-agnostic support is desired.
- **MEDIUM:** PLAN/DRY_RUN “do not create or mutate target store” conflicts slightly with target pre-count validation unless the runner can inspect existing targets read-only. The expected behavior should be explicit.
- **MEDIUM:** The implementation scope is large for one plan: manifest building, apply orchestration, overwrite safety, verification, embedding preservation, graph import, feedback import, failure handling, and old-test migration.
- **LOW:** `unsupported_categories such as search_log` should be explicit and stable, not open-ended.

**Suggestions**
- Add a `source_capture_manifest` with timestamps/checksums/counts for SQLite snapshot, graph export, and feedback export.
- Add a migration/run lock or explicit “snapshot only” precondition so the runner cannot read live mutable stores by accident.
- Change failure report fields to include `partial_writes_present`, `last_successful_phase`, and `failed_phase`.
- Define target modes separately: embedded local target vs remote Surreal service.
- Split verification into cheap required invariants and heavier sample/deep checks to keep the runner usable on production-derived data.

**Risk Assessment: HIGH**  
The design is directionally right, but this is the phase where data-loss and false-success risks live. Snapshot consistency and partial-write semantics need to be tightened before implementation.

## Plan 41-03 Review

**Summary**  
Good evidence/reporting plan with useful operator tooling and documentation. It complements 41-02 well by making migration results durable and reviewable. The main concern is whether restore/rollback semantics are actually proven or merely documented, since SURR-MIG-03 requires explicit backup, restore, rollback, and partial-failure semantics before cutover.

**Strengths**
- Good separation between migration execution and operator/reporting surfaces.
- Explicit CLI flags and fail-closed apply behavior.
- Correctly treats missing `surreal` CLI as evidence, not as an implicit install step.
- JSON plus Markdown reports are useful for later Phase 43/44 review.
- Documentation scope boundary is strong: no retrieval, no cutover, no fallback, no legacy deletion.

**Concerns**
- **HIGH:** Restore evidence may be too weak if CLI export/import is absent and fallback copy evidence is accepted without an actual restore rehearsal. SURR-MIG-03 likely needs at least one verified restore path, not just a manifest.
- **MEDIUM:** Reports can include production-derived refs, feedback text, and graph metadata. The plan says explicit output paths, but it should also define redaction/sample limits.
- **MEDIUM:** Devtool malformed JSON errors with “line/context” are useful but can be overbuilt unless fixtures are line-delimited. Standard JSON parse errors may not map cleanly to semantic graph/feedback row errors.
- **MEDIUM:** Apply-mode safety is split between runner flags and 41-02 runner internals. Tests should prove both layers fail closed.
- **LOW:** `ensure_ascii=False` is good for RU/EN, but docs should warn that reports may contain non-ASCII production-derived text.

**Suggestions**
- Require one restore rehearsal mode, even if only against a temp local target, with count and smoke verification.
- Add report redaction/sample-size controls or a documented default.
- Make classification statuses explicit: `blocked`, `restore_required`, `verified_with_cli`, `verified_with_fallback`, `not_verified`.
- Test that CLI absence cannot classify as restore success unless fallback restore verification actually ran.

**Risk Assessment: MEDIUM**  
The reporting surface is solid, but restore semantics need to be concrete enough to satisfy SURR-MIG-03 rather than becoming documentation-only.

## Overall Assessment

The three plans are coherent and mostly achieve Phase 41’s goals: schema catalog, production migration runner, and evidence/runbook tooling. The phase boundaries are good and the plans consistently avoid retrieval, cutover, fallback, and legacy deletion scope creep.

The biggest risks to address before execution are:

- Consistent source snapshot/export semantics across SQLite, Falkor, and feedback.
- Partial-write reporting that does not imply rollback happened when it did not.
- A real, verified restore path, even if local/temp and not production.
- Avoiding premature schema over-constraint before Phase 42 retrieval proves the final access patterns.

Overall phase risk: **MEDIUM-HIGH**. The plan quality is high, but migration tooling has inherently high blast radius, and the current plan needs sharper recovery and consistency semantics before it can be called production-grade.

---

## Consensus Summary

Both reviewers agree that Phase 41 is well-scoped and correctly split into schema catalog, production migration runner, and evidence/operator tooling. The plans have strong TDD structure, conservative overwrite posture, and clear boundaries against retrieval, cutover, runtime fallback, and legacy deletion.

### Agreed Strengths

- The phase sequence is coherent: 41-01 defines schema, 41-02 imports/verifies data, and 41-03 emits operator evidence.
- The default overwrite behavior is appropriately fail-closed and records explicit replacement policy when destructive replacement is chosen.
- The plans preserve Phase 41 boundaries and avoid pulling in Phase 42 retrieval, Phase 43 shadow evaluation, Phase 44 cutover, or Phase 45 deletion.
- The no-recompute migration posture is directionally correct: stored SQLite/sqlite-vec, graph exporter, and feedback provider data are treated as sources rather than re-derived content.
- Machine-readable manifests, checkpoints, and reports are the right primitives for later cutover decisions.

### Agreed Concerns

- Partial apply semantics need sharper wording. Current plans say failed reports must not claim success, but they do not explicitly state whether partial Surreal writes remain, are cleaned up, or require restore/operator intervention.
- Restore/rollback evidence needs to be stronger than documentation-only manifesting. The plans should require a verified restore path or rehearsal evidence before classifying restore as successful.
- Schema constraints, especially graph relation endpoints and `SCHEMAFULL` strictness, could reject valid preserved data unless flexible payload fields and source/export shape validation are explicit.
- Source capture consistency across copied SQLite, graph export, and feedback export needs an explicit manifest or skew policy.
- Migration safety must account for live writer coordination so copied snapshots/exports are bounded and not accidentally read from mutable production stores.

### Divergent Views

- OpenCode raised a concrete missing-data concern around `chunk_file_bindings`; Codex focused more on snapshot/restore consistency and target-state semantics. Both are relevant to production migration safety.
- OpenCode treated the relation table endpoint constraint as a HIGH import-failure risk; Codex rated relation shape as MEDIUM but agreed that premature graph schema constraints could be costly.
- Codex accepted the overall schema plan but cautioned against over-specifying DDL and vector component storage before Phase 42 proves access patterns; OpenCode was more concerned with missing source categories and import phase coverage.

### Current Convergence Counts

- Unresolved HIGH concerns: 6
- Unresolved actionable MEDIUM/LOW concerns: 17
