---
phase: 16
reviewers: [codex, opencode]
reviewed_at: 2026-04-24T18:02:01Z
plans_reviewed: [16-P1-schema-migration-core.md,16-P2-migration-ops-modes.md,16-P3-ingest-flow-rewrite.md,16-P4-purge-and-change-detection.md,16-P5-search-api-clean-break.md,16-P6-test-suite.md]
---

# Cross-AI Plan Review — Phase 16

## Codex Review

> invoked via: `ssh hetz sudo codex exec --full-auto --skip-git-repo-check`

**Cross-Plan**
The decomposition is mostly sound and maps well to the locked decisions, but two issues materially threaten the phase goal. First, `16-P1` appears to conflate the “canonical old row to keep physical data from” with the final post-migration `chunk_id`; if left as written, Phase 16 may not actually finish the blake3 remap that unblocks Phase 15. Second, Wave 3 has real file-ownership conflicts: `P3` and `P4` both own [pipeline.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/ingestion/pipeline.py) and [trickle.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/ingestion/trickle.py), and `P2` and `P5` both own [cli.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/cli.py). Those should be sequenced, merged, or have ownership split more cleanly.

**P1 Schema Migration Core**
Summary: Strong plan shape and good alignment with Decisions #4, #6, #8, #9, but it contains the highest-risk correctness ambiguities in the entire phase because it defines the migration semantics everything else depends on.

Strengths:
- Covers the real hard parts: M2M creation, resumable state, lock sentinel, collision collapse, drop-column fallback, and v15 supersession.
- Good explicit invariants and test list for the risky paths.
- Correctly treats `INSERT OR IGNORE` as the right steady-state write primitive.

Concerns:
- `HIGH`: The plan says collision groups collapse to `MIN(old chunk_id)` in `chunks_*`/`vec_meta_*`/`fts_*`. That conflicts with the phase invariant that final ids are 64-char blake3. The canonical old row should be the source of retained payload, not the final identifier.
- `HIGH`: Step 3 says `body_checksum` comes from a per-file fingerprint. If that is literal, the remap logic is wrong for chunk-level content addressing and may miss or miscompute dedup collisions.
- `HIGH`: `INSERT OR IGNORE` is only safe if all non-key payload on the content row is truly content-intrinsic. The plan does not require asserting equality of `text`, `heading_hierarchy`, and `level` within a collision group before freezing one copy.
- `MEDIUM`: `dry_run` lock behavior is ambiguous. For a schema-migration rehearsal, “no lock” gives misleading counts if writes are happening.

Suggestions:
- Split “canonical source row” from “final chunk_id” explicitly: keep payload from `MIN(old_chunk_id)`, but rename surviving rows to `new_blake3_id`.
- Define the hash input precisely and reuse the exact Phase 15 helper instead of restating it in plan prose.
- Add a hard invariant check before collapse: all rows mapping to the same new id must have equal stored content fields, or log/error clearly.
- Pick one dry-run policy now: either acquire the advisory lock like a real run, or require offline-only dry runs and document that.

Risk Assessment: `HIGH` — if the old-id/new-id confusion is not corrected, the phase can ship “green” tests and still fail its actual goal of superseding the blocked v15 migration.

**P2 Migration Ops Modes**
Summary: Good operator-facing layer with sensible CLI surfaces, but it is lighter-risk work riding on top of P1 and should avoid inventing partial invariant logic that later diverges from P6.

Strengths:
- Clear operator modes: run, dry-run, verify-only, status.
- Exit-code discipline is well thought through.
- Progress logging is appropriately journald-friendly.

Concerns:
- `MEDIUM`: `verify-only` inside `migrate run` is semantically awkward and invites branching logic duplication.
- `MEDIUM`: The plan proposes a temporary invariant runner in P2 before P6 finalizes the invariant suite; that risks two sources of truth.
- `LOW`: ETA/rows-per-sec logging can be noisy or misleading unless the denominator is defined consistently per strategy.

Suggestions:
- Put invariant execution behind one shared helper owned by the migration module, with P6 extending tests around it rather than P2 inventing a stub.
- Consider keeping `status` pure-state and `verify-only` explicitly described as invariant validation, not just another run mode.
- Keep progress assertions loose in tests; avoid brittle exact-string matching.

Risk Assessment: `MEDIUM` — operationally useful and likely fine, but avoid duplication with P6.

**P3 Ingest Flow Rewrite**
Summary: The intended steady-state write path is correct in direction, but this plan inherits a schema assumption that needs one more validation pass: whether the remaining chunk payload columns are really safe to deduplicate by `chunk_id`.

Strengths:
- Correctly replaces clobbering UPSERT behavior with additive M2M writes.
- Good idempotency tests for re-index and shared-content scenarios.
- Keeps graph writes unchanged, matching the locked scope.

Concerns:
- `HIGH`: If two holders of the same `chunk_id` can differ in `heading_hierarchy` or `level`, `INSERT OR IGNORE` silently preserves arbitrary metadata from first writer.
- `MEDIUM`: Trickle only checks the advisory lock at startup. That is not full mutual exclusion if trickle is already running when migration begins.
- `LOW`: Reusing `_LOCK_TABLE` from `migration_v16` is fine, but it creates a cross-module dependency on a migration module for runtime ingestion.

Suggestions:
- Add an ingest-time assertion/log on chunk conflict: same `chunk_id` must imply identical stored payload fields.
- Document explicitly that migration still requires trickle/service stop; the startup check is a guardrail, not full locking.
- If possible, move the lock-table constant to a tiny shared module to avoid importing migration code into trickle.

Risk Assessment: `MEDIUM` — the write primitive change is right, but the payload-intrinsic assumption needs to be made explicit.

**P4 Purge And Change Detection**
Summary: Necessary plan, but currently the most under-specified on transactional safety. As written, it risks claiming atomic decrement-and-cascade semantics without guaranteeing them across `chunks_*`, `vec_*`, and `fts_*`.

Strengths:
- Correct holder-count semantics.
- Good edge-case coverage for shared vs orphaned chunks.
- Preserves multi-strategy orphan sweeping.

Concerns:
- `HIGH`: The plan says `delete_m2m_for_file` may own its own transaction, then does vector/FTS cascade afterward. That is not atomic end-to-end.
- `HIGH`: The rollback test objective is stronger than the implementation sketch; the plan does not guarantee one shared transaction boundary across metadata, vec, and FTS tables.
- `MEDIUM`: Graph and fingerprint cleanup happen outside the main DB semantics and may leave partial external state if they fail after DB commit.

Suggestions:
- Require one connection and one explicit transaction for M2M delete, orphan discovery, chunk delete, vec delete, and FTS delete.
- Define post-commit ordering for graph/fingerprint cleanup and what happens on failure.
- Make the transaction boundary a hard must-have, not an implementation choice.

Risk Assessment: `HIGH` — the holder-count logic is right, but the atomicity story is not yet strong enough.

**P5 Search API Clean Break**
Summary: Good contract discipline and consistent with the locked “clean break” decision, but it overlaps with P1/P2 more than necessary and should reduce file ownership contention before execution.

Strengths:
- Cleanly honors `file_paths` with no compatibility shim.
- Correctly pushes lexical sort into hydration.
- Updates all visible consumers, including MCP.

Concerns:
- `MEDIUM`: `core/models.py` is already touched in P1, and `cli.py` is also owned by P2. That is manageable only if execution is strictly serialized.
- `MEDIUM`: Using one `Chunk` model for both transient ingest objects and hydrated stored objects may create avoidable blast radius.
- `LOW`: Per-hit hydration queries are probably fine for current top-K, but the plan should call that an accepted tradeoff, not an unnoticed cost.

Suggestions:
- Move all `SearchResult` API-shape changes into P5 only, and keep P1 limited to storage-side model changes if possible.
- Split CLI ownership: let P2 own migration/status commands and P5 own search output only, or merge the `cli.py` changes into one plan.
- Consider separate ingest vs hydrated chunk models if the single-model change starts touching too many call sites.

Risk Assessment: `MEDIUM` — likely implementable, but sequencing and model-surface discipline matter.

**P6 Test Suite**
Summary: This is a strong test-first plan and the best part of the set structurally. The main risk is breadth: it can become a giant red wall that obscures which downstream plan actually broke what.

Strengths:
- Excellent coverage of Decision #7.
- Good fixture design around real duplicate sources rather than synthetic toy cases only.
- Properly narrows parity expectations to non-collision queries.

Concerns:
- `MEDIUM`: The fixture builder must mirror the real pre-v16 schema very closely or the migration tests will validate a fake world.
- `MEDIUM`: If too many tests depend on not-yet-final interface names, Wave 1 RED may be noisy rather than informative.
- `LOW`: Progress/logging tests can become brittle if they assert exact message strings.

Suggestions:
- Keep per-plan test modules sharply isolated so each execute plan has a small, meaningful red/green loop.
- Prefer helper-level assertions over full CLI/log snapshot matching.
- Add one fixture-level assertion document mapping “what this fixture represents in production” so future edits do not drift.

Risk Assessment: `MEDIUM` — strong and necessary, but it needs discipline to stay useful rather than sprawling.

**Overall Risk**
`MEDIUM-HIGH`. The six plans do cover the phase goal in substance, and if corrected they should unblock the Phase 15 collision-blocked migration. The blocking issues are concentrated, not widespread: fix the P1 identifier semantics, make P4 transactionality explicit, and resolve Wave 3 file ownership conflicts before execution. After that, the plan set looks solid.

---

## OpenCode Review

> invoked via: `opencode run`

# Cross-AI Plan Review: Phase 16 — Content-dedup Schema

---

## Cross-Cutting Findings

Before per-plan reviews, these issues span multiple plans:

### File Overlap in Wave 3 (HIGH)

P3 and P4 both modify `pipeline.py` and `trickle.py`. P2 and P5 both modify `cli.py`. Wave-based parallelization would produce merge conflicts. **Recommendation:** serialize P3→P4 (P4 depends on P3's ingest rewrite being in place for purge to test against) and P2→P5 (P2's migrate CLI is independent from P5's search output, but cli.py overlap requires sequencing).

### Migration Flow Correctness: Collision Collapse Must Precede PK Remap (HIGH)

P1 Task 2's per-strategy flow lists collision detection (step 8) and collapse (step 9) *after* chunk_id UPDATE (step 4). This is impossible — `chunk_id` is `PRIMARY KEY` on `chunks_*`. Two rows mapping to the same blake3 id would cause a UNIQUE constraint violation on step 4, before collapse ever runs.

**Required fix:** Detect collisions *before* remapping, collapse non-canonical rows, then remap the survivors. The parenthetical "(temp table if needed to avoid PK clash)" acknowledges this but treats it as optional — it is mandatory. Suggested corrected flow:

1. Create M2M, backfill
2. Compute new blake3 ids into a temporary mapping (temp column or shadow table)
3. Detect collision groups from the mapping
4. Collapse: delete non-canonical from chunks_*, vec_meta_*, vec0_*, chunks_fts_*
5. Now safe: UPDATE canonical rows' chunk_id to blake3 (no duplicates remain)
6. UPDATE M2M, vec_meta, FTS references
7. DROP old columns

### Starting State Ambiguity: v15 Never Completed (MEDIUM)

CONTEXT.md states `migration_v15.py` is "blocked" by collisions. The production DB has pre-v15 chunk_ids (old format, not blake3). P1's migration must handle remapping from scratch. The `post_v15_pre_v16_db` fixture in P6 assumes a post-v15 state that doesn't exist in production — fine for testing, but the primary migration path must be the pre-v15 → v16 path, and this should be the default test fixture, not the post-v15 one.

### `delete_file_subgraph` May Be Too Aggressive Under M2M (MEDIUM)

P4 Task 1 calls `graph_store.delete_file_subgraph(file_path)` unchanged. Under M2M, if file A is deleted but chunk X is still held by file B, the graph must not delete MENTIONS edges for chunk X. Decision #5 says zero graph changes, but doesn't verify that the existing `delete_file_subgraph` implementation respects content-level vs file-level boundaries. **Recommendation:** verify during P4 execution that `delete_file_subgraph` only removes File-node artifacts, not MENTIONS edges keyed on chunk_id.

---

## Plan-by-Plan Review

---

### 16-P6-test-suite.md (Wave 1)

**Summary:** Wave 0 TDD scaffold — creates all test skeletons, fixtures, and pytest config so downstream plans have RED targets. Well-structured with a comprehensive conftest fixture strategy covering collision-rich, empty, and pre-v16 database shapes.

**Strengths:**
- Correct TDD sequencing: tests first (Wave 1), implementations in Waves 2-3
- Fixture inventory matches CONTEXT.md real-world duplicate sources (pytest cache, mirrored skills, symlinks, repeated headings)
- `query_set` fixture enables the round-trip parity test (DEDUP-10b) without depending on TEI
- `assert_db_bytes_unchanged` helper is a pragmatic dry-run verifier
- Explicit acknowledgment that suite should be RED at end of Wave 0

**Concerns:**
- **MEDIUM:** `post_v15_pre_v16_db` fixture represents a state that doesn't exist in production (v15 is blocked). The primary test path should use pre-v15 chunk_ids as the starting state. The fixture is useful as a secondary case but shouldn't be the default.
- **MEDIUM:** Round-trip parity test (Task 3, `test_top_k_parity_for_non_collision_chunks`) requires a working `DotMDService.search` pipeline in the test environment. The fixture must stub the embedder, FTS5, and graph stores deterministically. This is complex scaffolding that could become flaky if stubs don't match real behavior.
- **LOW:** Task 2 and Task 3 create test skeletons for P1-P5 but the exact test names must stay synchronized with the plans. Any rename during P1-P5 execution would break the RED→GREEN contract.

**Suggestions:**
- Make `collision_rich_db` the default fixture (not `post_v15_pre_v16_db`) since it represents the actual production starting state.
- Add a `pre_v15_db` fixture alias for clarity, documenting that this is the realistic starting point.
- Consider a single `ALL_TEST_NAMES` manifest constant in conftest.py that downstream plans can reference for synchronization.

**Risk:** LOW — Test scaffolding risk only; fixture realism is the main concern.

---

### 16-P1-schema-migration-core.md (Wave 2)

**Summary:** Core migration module plus metadata layer rewrite and model updates. The most complex and highest-risk plan. Well-decomposed into three tasks (metadata layer, migration script, v15 stub), but the migration flow ordering is incorrect (see cross-cutting finding above).

**Strengths:**
- Excellent alignment with all 9 locked decisions
- Task decomposition is logical: models/metadata first (Task 1), then migration (Task 2), then v15 stub (Task 3)
- Divergence check with stdlib math (no numpy) is correct per Research §Don't Hand-Roll
- Grep gates at end of each task are pragmatic correctness checks
- `INSERT OR IGNORE` vs UPSERT replacement addresses Research Pitfall 1 directly
- The advisory lock pattern with pid/host in the sentinel row is good for operator diagnostics

**Concerns:**
- **HIGH:** Migration flow step ordering is incorrect — collision detection (step 8) must happen before chunk_id PK remap (step 4). See cross-cutting finding. This is a correctness bug that would cause `IntegrityError` on any collision group.
- **HIGH:** Step 4 says "UPDATE chunks_*.chunk_id = new_id (temp table if needed to avoid PK clash)." This is not a detail — it's the hard part of the migration. The plan must specify: (a) add temp column `new_chunk_id TEXT`, (b) compute blake3 into it, (c) detect collision groups from `new_chunk_id`, (d) collapse non-canonical rows, (e) then swap PK. Without this, the executor will hit the PK violation and have no guidance.
- **MEDIUM:** Step 3 says "body_checksum is the per-file content hash already on the fingerprints table (Phase 15)." But chunk_ids need the *chunk body* hash, not the file hash. The blake3 formula is `blake3(body_checksum:chunk_index:strategy)` where `body_checksum` is the hash of the chunk's text content. The migration must compute this from `chunks_*.text`, not from fingerprints. If fingerprints only has file-level hashes, the migration needs to compute chunk-level hashes.
- **MEDIUM:** The migration must handle the case where v15 never ran (pre-blake3 chunk_ids) as the primary path, not just the post-v15 case. `needs_migration_v16` checks for "any chunk_id is not 64-hex" which catches this, but the migration flow should explicitly note that step 3 is computing blake3 from scratch (not just verifying existing blake3 ids).
- **LOW:** The rebuild fallback for DROP COLUMN is mentioned but not tested end-to-end in the plan. The test `test_rebuild_fallback_when_drop_column_fails` uses `monkeypatch` to inject `OperationalError` — this tests the error path but not the actual rebuild SQL correctness.

**Suggestions:**
- Fix the migration flow ordering: detect → collapse → remap. Add explicit steps for temp-column approach.
- Clarify that `body_checksum` in step 3 means `blake3(chunks_*.text)` computed at migration time, not looked up from fingerprints.
- Add a `test_remapping_from_pre_v15_chunk_ids` test case that starts with old-format chunk_ids and verifies the full blake3 remap + collapse + schema change.
- Consider adding `test_migration_idempotent_on_rerun` to the must-have truths (it's implied by the state marker but worth an explicit test).

**Risk:** HIGH — The migration flow correctness issue is a blocking concern. The rest of the plan is well-structured.

---

### 16-P2-migration-ops-modes.md (Wave 3)

**Summary:** CLI integration for migration operations (`run`, `status`, `--dry-run`, `--verify-only`) plus structured progress logging. Clean and well-scoped — this is primarily glue code between Click and the migration module.

**Strengths:**
- Exit code convention is well-documented (0/1/2/3 with semantic meanings)
- Mutual exclusion of `--dry-run` and `--verify-only` with helpful error message
- Progress reporter uses throttled `logger.info` (no tqdm) — correct for journald
- `migrate status` is read-only — no mutation risk
- Structured log format (`key=value`) is journald-friendly

**Concerns:**
- **MEDIUM:** cli.py is also modified by P5 (Task 2 updates CLI result printer and status query). If P2 and P5 execute in parallel in Wave 3, they'll conflict on cli.py. P2 adds the `migrate` subcommand group; P5 modifies the `search` and `status` output. These are different code regions, but merge conflicts are still likely.
- **LOW:** `verify-only` mode's invariant checks are described as "a `run_invariants(conn)` stub that P6 will fill in." But P6 is Wave 1 (test creation), not invariant implementation. The invariant logic should be in P1's migration module. This seems like a handoff that could be unclear during execution.
- **LOW:** Disk delta estimate for `--dry-run` is mentioned in Decision #7 but not specified in the task behavior. Computing this requires knowing the approximate row reduction from collision collapse, which the dry-run already calculates.

**Suggestions:**
- Sequence P2 before P5 in Wave 3 to avoid cli.py conflicts.
- Clarify that `run_invariants()` lives in `migration_v16.py` (implemented in P1) and P2's verify-only just calls it.
- Add disk delta estimate logic to the dry-run path (trivial: `rows_collapsed * avg_row_size`).

**Risk:** LOW — Straightforward glue code with well-defined interfaces.

---

### 16-P3-ingest-flow-rewrite.md (Wave 3)

**Summary:** Rewrites `_index_file` to use INSERT OR IGNORE on both chunks and M2M tables, and adds trickle startup advisory lock check. Focused and correct in scope.

**Strengths:**
- Directly addresses Research Pitfall 1 (UPSERT clobber) and Pitfall 3 (trickle/migration race)
- Test coverage for the key correctness properties: idempotent re-index, shared chunk detection, repeated headings
- Trickle lock check is defensive: handles absent lock table (pre-migration DB) gracefully
- Uses short-lived read-only SQLite connection for lock check — no resource leak

**Concerns:**
- **HIGH:** pipeline.py is also modified by P4. If P3 and P4 run in parallel, merge conflicts are guaranteed (both rewrite functions in the same file). P4's `_purge_file` rewrite depends on P3's ingest flow being in place for integration testing.
- **MEDIUM:** Task 1 says "vec_meta_* row count does not grow on re-index of already-embedded chunks (Phase 15 cache still honoured)." This test requires the embedding cache to be wired through. If P1's metadata layer doesn't expose the cache check, this test will need to mock at the wrong level.
- **LOW:** `_LOCK_TABLE` constant is imported from `migration_v16` — creates a circular dependency risk if trickle imports migration_v16 at module level and migration_v16 imports something from trickle. Recommend extracting the constant to a shared location (e.g., `storage/constants.py` or a module-level string in trickle that matches by convention).

**Suggestions:**
- Sequence P3 before P4 (P4's purge needs P3's ingest to be in place).
- Extract `_LOCK_TABLE` constant to a shared location or duplicate as a private constant in trickle with a comment referencing migration_v16.
- Add a test for the case where the migration lock table exists but is empty (partially cleaned up state).

**Risk:** MEDIUM — File overlap with P4 is the main concern; logic is otherwise straightforward.

---

### 16-P4-purge-and-change-detection.md (Wave 3)

**Summary:** Rewrites `_purge_file` as holder-aware decrement-cascade and updates `purge_orphaned_files` to scan M2M tables. Critical for data integrity under M2M semantics.

**Strengths:**
- Transactional purge with explicit BEGIN/COMMIT/ROLLBACK addresses Research Pitfall 2
- Test coverage for all key scenarios: sole holder cascade, shared holder preservation, mixed case, transactional rollback, multi-strategy
- Orphan sweep preserves commit bb79455's multi-strategy behavior
- Summary log for operational visibility

**Concerns:**
- **HIGH:** Must execute after P3 (both modify pipeline.py). Plan header says `depends_on: [16-P1]` but should also depend on P3.
- **MEDIUM:** `graph_store.delete_file_subgraph(file_path)` is called unchanged, but under M2M this might delete MENTIONS edges for chunks still held by other files. The plan says "UNCHANGED per Decision #5" but doesn't verify this. If `delete_file_subgraph` removes content-level graph data, it would cause data loss for shared chunks. **Recommendation:** audit the actual `delete_file_subgraph` implementation during execution.
- **MEDIUM:** Task 1 says "the M2M delete + orphan cascade for a given strategy share one BEGIN/COMMIT." But `metadata.delete_m2m_for_file` "already owns a transaction internally." The plan then says "if that's sufficient, keep it. Otherwise wrap the three-step cascade inside pipeline in an explicit transaction." This uncertainty should be resolved: the purge must be atomic across M2M delete + orphan cascade + vec/FTS delete. The transaction boundary must encompass all three, which means the pipeline orchestrates the transaction, not metadata.
- **LOW:** "Strategy discovery: re-use whatever 'list all present strategies' helper the codebase already has." This is fine but should be explicit — if no such helper exists, one needs to be created (query `sqlite_master` for table names matching `chunks_%`).

**Suggestions:**
- Add `depends_on: [16-P1, 16-P3]` to the plan header.
- Before execution, audit `delete_file_subgraph` to confirm it only removes file-level graph nodes, not content-keyed MENTIONS edges.
- Make the transaction boundary explicit: pipeline owns the transaction, metadata/vec/FTS operations run within it (not auto-commit).
- Consider `purge_orphaned_files` as a startup-only operation (after lock check, before first index pass) to avoid running it concurrently with indexing.

**Risk:** MEDIUM — Graph store interaction is uncertain; transaction boundary needs clarification.

---

### 16-P5-search-api-clean-break.md (Wave 3)

**Summary:** Replaces `SearchResult.file_path: Path` with `file_paths: list[Path]` across all consumers. Clean, well-audited consumer list. The plan is mostly mechanical changes with good test coverage.

**Strengths:**
- Complete consumer audit from Research §Component Responsibilities (cli.py:112, cli.py:161, mcp_server.py:118, etc.)
- `test_no_file_path_attr` is an excellent regression guard for the clean break
- Graph-origin hits explicitly included in hydration test
- CLI rendering decision is documented and made within Claude's discretion
- Grep gate catches any residual `.file_path` references

**Concerns:**
- **MEDIUM:** cli.py overlap with P2 (both Wave 3). P5 modifies search/status output; P2 adds migrate subcommand. Different code regions but same file.
- **MEDIUM:** Fusion hydration does "one SELECT per chunk_id" which is O(K) queries for top-K results. For K=20 this is fine, but the plan should note this as a conscious choice. The current code likely does a single bulk fetch. Switching to per-chunk_id queries is a performance regression for large K, even if acceptable now.
- **LOW:** The CLI rendering format `[i] path1 (+N more: path2, path3)` is reasonable but undocumented in the decision log. It's Claude's discretion, but worth a one-liner in CONTEXT.md for traceability.

**Suggestions:**
- Sequence P5 after P2 to avoid cli.py conflicts.
- Consider a batch hydration query: `SELECT chunk_id, file_path FROM chunk_file_paths_<strategy> WHERE chunk_id IN (...)` to avoid O(K) round-trips. This is a minor optimization but matches the current code's likely bulk-fetch pattern.
- Add the CLI rendering format choice to CONTEXT.md (even as a brief note) for traceability.

**Risk:** LOW — Mechanical change with good test coverage. Performance note is minor.

---

## Overall Risk Assessment: **HIGH**

**Justification:**

The phase goal is achievable and the plans are well-structured, but two issues must be resolved before execution:

1. **Migration flow ordering (P1):** The collision collapse must happen *before* chunk_id PK remap, not after. This is a correctness bug in the plan that would cause runtime `IntegrityError`. Fixing it requires restructuring the migration flow steps and adding explicit temp-column handling.

2. **Wave 3 file conflicts (P3/P4, P2/P5):** The wave-based execution model would run these pairs in parallel, causing merge conflicts on `pipeline.py` and `cli.py`. The plans must either be sequenced within Wave 3 (P3→P4, P2→P5) or refactored to avoid file overlap.

Additionally, the `delete_file_subgraph` interaction with M2M semantics (P4) needs codebase verification — if the current implementation removes content-level MENTIONS edges, shared chunks would lose graph associations when one holder is deleted.

With these three issues addressed, the phase risk drops to **MEDIUM** — the remaining concerns are implementation details within well-defined boundaries.

**Recommended execution order:**

```
Wave 1: P6 (tests)
Wave 2: P1 (core migration — with fixed flow ordering)
Wave 3: P3 (ingest) → P4 (purge) → P2 (ops CLI) → P5 (search API)
```

---

## Consensus Summary

### Agreed Strengths
- Plan structure maps cleanly to locked decisions D-01 … D-09.
- Risk hotspot is concentrated in P1 (migration core); P2/P3/P4/P5/P6 are riding on top.
- Test suite (P6) coverage is appropriately broad given Decision #7.
- `INSERT OR IGNORE` is the correct steady-state write primitive for content-addressed ids.

### Agreed Concerns (HIGH — must fix before execution)

1. **P1 migration flow ordering is broken.** Both reviewers flagged that the plan's `UPDATE chunk_id = new_blake3` happens BEFORE collision collapse. Two rows mapping to the same blake3 would trigger a `UNIQUE` violation on the PK update itself. The temp-column/shadow-table approach parenthetically mentioned must be made mandatory. Correct order: (1) create M2M + backfill, (2) compute new ids into a shadow column, (3) detect collision groups on the shadow column, (4) collapse non-canonical rows (drop from chunks_*/vec_meta_*/fts_*), (5) then remap survivors. — **codex + opencode**

2. **Wave 3 file ownership conflicts.** P3 ↔ P4 both own `pipeline.py` and `trickle.py`. P2 ↔ P5 both own `cli.py`. Must serialize or merge, not parallelize. Suggested wave shape: Wave 1=P6, Wave 2=P1, Wave 3=P3→P4→P2→P5 (sequential). — **codex + opencode**

3. **P1 MIN(old chunk_id) semantics.** Codex raised that "MIN(old chunk_id)" must mean "row to keep payload from," not "final chunk_id." Final id is blake3. Plan prose is ambiguous. — **codex**

4. **P1 `body_checksum` derivation unclear.** Must explicitly reuse Phase 15's chunker helper (don't restate hash input in plan prose). — **codex**

5. **Collision-group invariant missing.** Before collapsing N old rows into one blake3 id, assert `text`, `heading_hierarchy`, `level` are equal across the group. If they're not, log+error — real hash collision or non-deterministic chunker. — **codex**

### Medium concerns
- P1 dry-run lock semantics: acquire lock like a real run, or require an offline-only mode — don't leave it ambiguous. (codex)
- P4 `delete_file_subgraph` behaviour under M2M: if current impl drops content-level MENTIONS edges when one file is removed, shared chunks lose graph associations. Needs source audit. (opencode)
- P4 transactionality of decrement-and-cascade must be explicit — one transaction per file, or rollback semantics spelled out. (codex)
- P6 fixture fidelity — must mirror pre-v16 schema exactly or migration tests validate a fake world. (codex)

### Low concerns
- CLI rendering format (file_paths output) not specified in CONTEXT.md — add short note. (opencode)
- Batch hydration query for M2M join to avoid O(K) round-trips. (opencode)
- Don't assert exact log strings in progress/logging tests — brittle. (codex)

### Divergent Views
None material. Both reviewers converged on the same HIGH concerns (flow ordering + file overlap). Codex went deeper on P1 semantics; OpenCode went deeper on graph-side interactions in P4. Complementary, not conflicting.

## Overall Risk
Both reviewers rate **HIGH before fixes**, **MEDIUM after**. Fix the 5 HIGH concerns via `/gsd-plan-phase 16 --reviews` and re-verify before executing.
