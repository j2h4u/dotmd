---
phase: 38
reviewers: [opencode]
reviewed_at: 2026-06-12T13:44:01.201805+00:00
plans_reviewed: [38-01-PLAN.md, 38-02-PLAN.md, 38-03-PLAN.md, 38-04-PLAN.md, 38-05-PLAN.md]
---

# Cross-AI Plan Review — Phase 38

## OpenCode Review

# Cross-AI Plan Review: Phase 38 — Embedded SurrealDB Storage Spike

---

## 1. Summary

Phase 38 is a **well-structured decision spike** with a clear default posture of "defer unless parity is proven." The five-wave dependency chain (01→05→02→03→04) correctly gates Surreal schema/import/parity work behind an early embedded atomicity gate, and the plans encode the D-01 "migration over recomputation" invariant through test-enforced boundaries, recomputation-guard monkeypatching, and explicit gate-checking functions. The threat models are thorough, the TDD discipline is consistently applied, and the artifact/output contracts are unusually precise. The primary risk is that the plans assume fixture-scale testing will generalize to a 2.4GB production database with 149k chunks and 353k graph edges — and that core architectural mismatches (Surreal single-field FTS vs dotMD weighted FTS5, embedded-mode transaction limitations) may produce permanently-failing parity gates that the phase structure doesn't explicitly route to a "defer" codepath without executing all five waves.

---

## 2. Strengths

- **Gate-first sequencing is correct and principled.** Requiring 38-05's embedded atomicity/writer-safety proof before 38-02 can claim migrate-readiness prevents the common mistake of discovering fundamental incompatibilities after substantial implementation work.
- **D-01 enforcement is multi-layered and testable.** The recomputation boundary guards (monkeypatching embedding/extraction call sites to raise), the `assert_embedded_safety_gate_passed` gate check in the importer, and the dry-run/apply mode separation all create enforceable invariants rather than aspirational comments.
- **Parity testing design is rigorous.** Separate `compare_fts_results`, `compare_vector_results`, `compare_graph_direct_results`, and `compare_hybrid_results` functions with explicit pass/fail semantics, top-result exact-match requirements, and blocking-vs-informational classification avoids the "it has the feature, ship it" pitfall identified in research.
- **Threat models are comprehensive and actionable.** Every plan has a STRIDE register with specific mitigation plans. The secret-redaction discipline (key names only, no values) and snapshot-drift detection (record source mtime, row counts) are production-grade concerns well ahead of the spike's scope.
- **`build_storage_recommendation` as a decision function.** Requiring all high-severity gates (D-01 transform coverage, 38-05 embedded safety, STOR-02 parity, backup/restore, writer safety) before returning `migrate` makes the recommendation auditable and testable.
- **Package checkpoint is the right call.** Given the `surrealdb` package was flagged `SUS` in research, the human-verify checkpoint before any dependency install is appropriate and the plan stops cleanly (no `pyproject.toml` edit) if verification fails.

---

## 3. Concerns

### Cross-Plan Concerns

- **[HIGH] Fixture-scale testing cannot validate production-scale behavior.** Every plan tests against `tmp_path` SQLite fixtures and deterministic in-test rows. The production index is 2.4GB with 149,739 chunks, 353,700 graph edges, and 28.7k entities. SurrealDB HNSW index build time, embedded file-size growth, and query latency at that scale are untested by any plan. If the 38-03 parity harness only runs on small fixtures, a passing gate could mask production-scale performance failure.
- **[HIGH] FTS parity may be architecturally impossible given Surreal's single-field constraint.** 38-03 requires "exact top result and top-3 membership must match the current FTS baseline." Research explicitly documents that Surreal full-text indexes are single-field while dotMD's FTS5 indexes text/title/tags together with weighted columns. If this parity test permanently fails (as seems likely), the phase structure has no explicit "FTS parity failed → route to defer" short-circuit — the executor must run all five waves before producing a defer recommendation.
- **[MEDIUM] Embedded-mode transaction limitations vs import rollback.** 38-02 specifies rollback-on-error behavior for the importer, but research notes embedded Python connections lack client-side transaction handles. Raw `BEGIN`/`COMMIT` via `.query()` is listed as an assumption (A1). If this assumption proves false, the importer's error recovery model breaks, and 38-05's gate would catch it — but 38-02's Task 2 says to implement rollback behavior that may be impossible to implement correctly.
- **[MEDIUM] No end-to-end integration test across all five waves.** Each plan tests its own concerns in isolation, but there's no plan for a combined `test_surreal_full_pipeline.py` that runs inventory → import → parity → backup → recommendation end-to-end on the same corpus. Integration bugs at wave boundaries (e.g., 38-05 gate report format mismatched with 38-02's `assert_embedded_safety_gate_passed` expectations) would only surface during manual execution.

### 38-01 Specific

- **[MEDIUM] FalkorDB inventory via "fake exporter" may miss edge property types.** The plan tests `collect_falkor_inventory` with a fake graph exporter, but production FalkorDB edges carry relation weights, metadata, and typed properties. A fake exporter returning only node/edge counts won't verify that the real exporter preserves these properties — which 38-02's graph import depends on.
- **[LOW] Snapshot copy assumption for Docker volumes is untested.** The plan calls `copy_sqlite_snapshot` but doesn't address WAL/SHM sidecar files, which Research notes exist in the live volume. Copying `index.db` without `index.db-wal` and `index.db-shm` could produce an inconsistent snapshot.

### 38-05 Specific

- **[MEDIUM] Stale writer guard orphan cleanup is unspecified.** `SurrealWriterGuard` uses "owner metadata" to prevent concurrent writers, but there's no mechanism for detecting or cleaning up abandoned lock files (process crash, kill -9). In production, this could permanently block indexing after a crash.
- **[LOW] `autonomous: false` + checkpoint interaction.** The checkpoint task is manual but subsequent tasks are auto. If the human verifier doesn't respond promptly, the executor's context could drift. There's no timeout or escalation path specified.

### 38-02 Specific

- **[MEDIUM] Surreal record-ID sanitization is mentioned but SurrealQL injection through record IDs is under-specified.** dotMD chunk IDs, entity names, and file paths may contain characters (`:`, `/`, `{`, `}`, spaces) that interact with Surreal's record-ID syntax (`table:id`). A "central record-ID sanitizer" is mentioned but no test case validates injection through malicious IDs.
- **[LOW] Four protocol implementations in one plan is scope-heavy for a spike.** `SurrealMetadataStore`, `SurrealVectorStore`, `SurrealGraphStore`, `SurrealFeedbackStore` plus the importer is substantial implementation work. The research recommends "a thin Surreal-backed prototype" — this plan is building nearly the full storage surface.

### 38-03 Specific

- **[MEDIUM] Graph-direct parity with Surreal relation tables vs FalkorDB Cypher semantics.** FalkorDB uses Cypher with property graphs; SurrealDB uses RELATE tables with SurrealQL. The current `graph_direct.py` implementation likely uses Cypher-specific query patterns. 38-03 requires "exact" section ID matching but doesn't address how to normalize the two graph query languages' results.
- **[LOW] RRF fusion test determinism.** RRF scoring depends on rank positions from multiple engines. If either engine produces ties or score collisions, the fused ranking could be non-deterministic, making parity tests flaky.

### 38-04 Specific

- **[HIGH] `surreal` CLI missing on host — backup rehearsal gated on tool that doesn't exist.** The plan's operations rehearsal depends on `surreal export`/`surreal import` but research confirms the CLI is not installed. The plan allows SDK-file-copy as fallback but doesn't validate that file-copy-based restore produces consistent data (no WAL/journal semantics to worry about with embedded SurrealKV?).
- **[MEDIUM] Recommendation doesn't handle partial gate failure explicitly.** The logic says "migrate requires all gates pass" and "defer/reject otherwise," but doesn't distinguish between "FTS parity failed but vector/graph passed" vs "embedded atomicity failed entirely." These have different operational implications and the recommendation should reflect the severity of the specific failure.
- **[MEDIUM] Rollback rehearsal is Surreal-to-Surreal only.** The plan rehearses backup/restore within SurrealDB but doesn't rehearse reverting from a Surreal prototype back to the current SQLite/FalkorDB stack. For a "migrate" recommendation to be responsible, the fallback path should be tested: what happens if we migrate, discover problems, and need to go back?

---

## 4. Suggestions

- **Add a scale-test gating task before 38-04's recommendation.** After 38-02 imports real production data (even a sample), time HNSW index build, measure embedded SurrealKV file size, and run representative queries before allowing a migrate recommendation. Without this, fixture-scale passing tests could produce a dangerously optimistic decision.
- **Add an explicit FTS-parity-failed → defer codepath.** Given the single-field FTS limitation documented in research, define a "graceful mismatch" classification: if the FTS result ordering differs but top-10 overlap is >80% and the reason is the single-field constraint, mark it as a documented limitation rather than a blocking failure — or explicitly document it as rationale for deferral without requiring all five waves to execute.
- **Add WAL/SHM handling to `copy_sqlite_snapshot` in 38-01.** The snapshot copier should either run `PRAGMA wal_checkpoint(TRUNCATE)` before copying or include WAL/SHM files in the snapshot manifest to avoid silent data loss.
- **Add writer guard orphan cleanup to 38-05.** Include a `force_release` or TTL-based cleanup mechanism in `SurrealWriterGuard`, with a test case showing that a simulated crash (process exit without release) doesn't permanently block the guard.
- **Add Surreal record-ID injection tests to 38-02.** Test cases with chunk IDs containing `:`, `/`, spaces, and `{`/`}` characters to validate the sanitizer before import begins.
- **Add an end-to-end integration smoke test.** A single test that takes a deterministic fixture through 38-01 inventory → 38-05 gate assertion → 38-02 import → 38-03 parity → 38-04 recommendation, asserting the full pipeline works and the recommendation function produces the expected output given the fixture's characteristics.
- **Distinguish recommendation outcomes by failure severity.** `build_storage_recommendation` should return a structured result: `migrate`, `defer (gap: FTS weighting)`, `defer (gap: CLI missing)`, or `reject (gap: embedded atomicity)`. This gives the operations recommendation more precision than three coarse buckets.
- **Consider a production-rollback rehearsal task in 38-04.** Before recommending migration, prove that reverting to the current SQLite/FalkorDB stack works by: (1) running the current dotMD service against a Surreal-imported corpus, (2) stopping it, (3) restoring the SQLite/FalkorDB originals, (4) verifying current dotMD service works correctly against the restored originals.

---

## 5. Risk Assessment

**Overall: MEDIUM**

The plans are systematically structured, the gating dependencies are correct, and the D-01/D-02 invariants are well-enforced at the test and code level. The primary risk vectors are:

1. **Architectural mismatch risk (FTS single-field)** — This is a known limitation that may cause permanent parity failure. The plans correctly identify the issue but the phase structure requires executing all waves regardless of whether this gate is fundamentally unpassable, wasting implementation effort.
2. **Scale-blind testing risk** — All tests use small fixtures. A 2.4GB production database with 149k chunks may expose performance or correctness issues invisible at fixture scale. A migrate recommendation produced from fixture-only evidence would be unsound.
3. **Missing tooling risk** — The `surreal` CLI is absent from the host, which constrains backup/rehearsal options. The plan provides file-copy fallback but doesn't validate its correctness for embedded SurrealKV stores.

These are mitigated by the plans' own gate structure: if any of these risks materialize, `build_storage_recommendation` should correctly return `defer` or `reject`. The concern is whether the executor will recognize these as gate failures or proceed optimistically past them. The plans would benefit from explicit "stop conditions" per wave that, if hit, allow skipping remaining waves and proceeding directly to a defer/reject recommendation.


---

## Consensus Summary

Only OpenCode was requested for this run, so consensus is single-reviewer.

### Agreed Strengths

- Phase structure is strong: inventory -> early embedded safety gate -> import -> parity -> recommendation.
- Migration-first invariant is visible and enforceable across plans.
- Threat models, TDD discipline, and explicit recommendation gates are materially useful.

### Agreed Concerns

- Production-scale behavior may not be proven by fixture-only tests.
- FTS parity may fail because SurrealDB full-text indexing does not map cleanly to current weighted FTS5 behavior.
- Backup/restore and rollback evidence depends on tooling and should not be hand-waved.

### Divergent Views

- None; one reviewer was invoked.
