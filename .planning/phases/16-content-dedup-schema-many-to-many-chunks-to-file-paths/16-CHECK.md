---
phase: 16-content-dedup-schema
checked_at: 2026-04-24
checker: gsd-plan-checker (internal, post cycle-3 convergence)
plans_checked: [16-P1, 16-P2, 16-P3, 16-P4, 16-P5, 16-P6]
reviews_context: cycle-1 + cycle-2 cross-AI convergence; cycle-3 replan addressed all NEW-HIGH / NEW-MED findings
---

# Phase 16 — Pre-Execute Plan Check

Goal-backward verification after 3 cycles of cross-AI review-convergence. Starting hypothesis: plans are flawed. Findings are classified strictly; bias is toward surfacing BLOCKERs.

## Findings summary

- **BLOCKER:** 0
- **WARN:** 3
- **ACCEPTED:** 4
- **OK:** 11

## Directive-by-directive verification

### D1. P1 Task 2 shadow-column flow — step-by-step walk

Full per-strategy sequence (reading `16-P1-schema-migration-core.md` Task 2):

| Step | Action | UNIQUE-safe? | M2M-consistent? |
|------|--------|--------------|-----------------|
| 1 | ensure `chunk_file_paths_<strategy>` + index | n/a | creates table |
| 2 | M2M backfill (carries OLD chunk_ids) | — | M2M consistent with chunks_* at this point |
| 3 | `ALTER TABLE chunks_* ADD COLUMN new_chunk_id TEXT` | safe: plain column | M2M untouched |
| 4 | per-row compute `new_chunk_id = _make_chunk_id(body_checksum, chunk_index, strategy)` via Python helper, UPDATE by old_id | no PK clash — new_chunk_id is non-unique column | M2M still points at old_ids |
| 5a | payload_invariant_check per collision group; TEXT mismatch → HARD ABORT (exit 5); heading/level mismatch → collect into `all_divergences` | n/a | n/a |
| 5b | canonical_old_id = MIN(old_ids) (payload-source row, NOT final id) | n/a | n/a |
| 5c | **M2M REDIRECT** — UPDATE chunk_file_paths SET chunk_id = :canonical_old_id WHERE chunk_id IN (non_canonical) | plain UPDATE — M2M PK includes (chunk_id, file_path, chunk_index); check below | every M2M row now points at a chunk_id that SURVIVES step 5e |
| 5d | vector cosine divergence WARN (threshold 0.01) — does not abort | read-only | n/a |
| 5e | DELETE non_canonical from chunks_*, vec_meta_*, vec0_*, chunks_fts_* | safe: no PK on new_chunk_id yet | M2M unaffected because step 5c already redirected |
| 5f | fail-closed gate if `all_divergences` and not override → ROLLBACK + release lock + raise `PayloadDivergenceBlocked` (exit 4) | n/a | rollback restores pre-collapse state |
| 6 | sanity SELECT: 0 duplicate new_chunk_id | n/a | guarded |
| 7 | UPDATE chunk_file_paths SET chunk_id = (SELECT new_chunk_id FROM chunks_* c WHERE c.chunk_id = chunk_file_paths.chunk_id) WHERE chunk_id IN (SELECT chunk_id FROM chunks_*) | subquery resolves for every M2M row (all point to surviving canonical/non-collision old ids thanks to 5c) | M2M now on blake3 new ids |
| 8 | UPDATE chunks_*.chunk_id = new_chunk_id | safe — deduplication complete | consistent |
| 9 | DROP COLUMN new_chunk_id / file_path / chunk_index / char_offset (fallback rebuild) | n/a | M2M untouched (columns live on M2M) |
| 10 | state marker INSERT | n/a | n/a |

**Verdict:** Flow is sound. Step 5c is the load-bearing fix for cycle-2 NEW-HIGH-1. After 5c + 5e, every row in `chunk_file_paths_*` points to an id still present in `chunks_*`, so step 7's correlated UPDATE resolves for every M2M row.

**WARN-1 (non-blocker, stylistic, already mitigated):** Step 5c's UPDATE touches `chunk_file_paths_*` PK column (part of composite PK `(chunk_id, file_path, chunk_index)`). If two non-canonical M2M rows share `(file_path, chunk_index)` with a canonical row already present for the same group, the redirect-UPDATE would violate the PK. Concrete example: same file indexed under identical chunk_index twice (impossible under current chunker — guarded by chunker determinism) OR canonical_old_id and a non_canonical_old_id both already have an M2M row for the same (file_path, chunk_index). The second is impossible because M2M backfill in step 2 copies exactly one `(chunk_id, file_path, chunk_index)` per chunks_* row and no two chunks_* rows share `(chunk_id_old, file_path, chunk_index)`. After redirect, `(canonical_old_id, file_path, chunk_index)` must be distinct per row. Given the blake3 formula requires chunk_index equality within a collision group, AND typical production state has one row per file × strategy × (old_chunk_id), the redirect UPDATE is safe. Still, the plan does not call out `INSERT OR IGNORE`-style absorb semantics for the edge case of legitimately-duplicate M2M rows that collapse. Recommend adding a safety ON CONFLICT clause or a brief "known-safe because" comment. Severity: WARN — not a blocker because the assumptions hold for real data; fix defensively.

**Status: OK** with one stylistic WARN above.

### D2. Decision #10 enforcement (fail-closed divergence policy)

Paths traced through plan set:

- `16-P1` Task 2 step 5a collects `all_divergences` (records: new_chunk_id, old_ids, diverged_fields, canonical, per-old payloads).
- `16-P1` Task 2 step 5f: `if all_divergences: if not allow_payload_divergence: write divergence_report, update state, ROLLBACK, release_lock, raise PayloadDivergenceBlocked`.
- `16-P1` must_haves truth 6 locks the abort semantics explicitly.
- `16-P1` truth 14 adds `allow_payload_divergence` + `payload_divergences` columns to `migration_v16_state`.
- `16-P1` Task 2 test battery: `test_aborts_on_divergence_without_flag`, `test_proceeds_with_flag_records_to_state`, `test_verify_only_reports_divergence_count`.
- `16-P2` Task 2 adds `--allow-payload-divergence` Click flag with explicit help text referencing Decision #10.
- `16-P2` Task 2 catches `PayloadDivergenceBlocked` → exit 4 with pointer to `divergence_report.txt`.
- `16-P2` must_haves truth 4 requires the flag pass-through.
- `16-P2` CLI exit-code matrix: 4 is reserved for divergence-without-flag, 5 for hard text-mismatch — distinct codes.
- `16-P2` verify-only mode reports divergence count up-front and exits 4 without flag.

No code path that could silently skip the check. If `allow_payload_divergence` is false and divergences exist, abort is unconditional.

**Status: OK.**

### D3. Wave / frontmatter consistency

| Plan | wave | depends_on | body prose consistent? | files_modified overlap with same-wave plan? |
|------|------|-------------|------------------------|--------------------------------------------|
| P6 | 1 | [] | yes | wave 1 solo — none |
| P1 | 2 | [P6] | yes | wave 2 solo — none |
| P3 | 3 | [P1] | yes | wave 3 solo — none |
| P4 | 4 | [P1, P3] | yes (body says "wave 4") | wave 4 solo — none |
| P5 | 5 | [P1, P4] | yes | wave 5 solo — none |
| P2 | 6 | [P1, P3, P4, P5] | yes — explicitly "wave 6" throughout, cycle-2 NEW-MED-1 fixed | wave 6 solo — none |

Cross-wave shared files (serial, acceptable):
- `cli.py`: P5 (wave 5) writes `search`/`status` lines, P2 (wave 6) appends `migrate` group — sequence enforced by `depends_on`.
- `migration_v16.py`: P1 writes, P2 augments with progress reporter, P3 swaps in LOCK_TABLE import — all in later waves.
- `pipeline.py`: P3 (wave 3) writes ingest, P4 (wave 4) writes purge — serial.
- `trickle.py`: P3 (wave 3) writes startup lock check, P4 (wave 4) may tweak purge_orphaned_files call site — serial.
- `metadata.py`: P1 (wave 2) writes, P3 (wave 3) defensively declares `get_stored_payload` — serial.

All cross-wave dependencies declared via `depends_on`. No same-wave file overlap anywhere.

**Status: OK.**

### D4. Phase goal coverage — goal-backward chain

Phase goal: unblock Phase 15's collision-blocked `migration_v15.py`; ship content-dedup schema with M2M file_paths.

| Stage | Requirement | Plan(s) | Status |
|-------|-------------|---------|--------|
| v15 blocker: PK collisions on same-content chunks | M2M schema + blake3 remap + collision collapse in one pass | P1 (DEDUP-01..04) | covered |
| Ingest must stop clobbering | INSERT OR IGNORE on chunks_* + chunk_file_paths_* | P3 (DEDUP-07) | covered |
| Purge must be holder-aware | decrement-cascade across M2M | P4 (DEDUP-08) | covered |
| Search must surface all holders | file_paths: list[Path], sorted lex | P5 (DEDUP-09) | covered |
| Operator needs safe "look before leap" + override | migrate CLI with --dry-run, --verify-only, --allow-payload-divergence | P2 (DEDUP-06) | covered |
| v15 supersession | migration_v15.py stub | P1 Task 3 (DEDUP-11) | covered |
| Test fidelity | collision fixtures + invariants + round-trip parity | P6 (DEDUP-10, DEDUP-10b) | covered |

Requirements registered in plan frontmatter:
- P1: DEDUP-01, 02, 03, 04, 11 (5)
- P2: DEDUP-06 (1)
- P3: DEDUP-05, 07 (2)
- P4: DEDUP-08 (1)
- P5: DEDUP-09 (1)
- P6: DEDUP-10, 10b (2)

All 11 DEDUP requirements have at least one implementing plan. Chain from Phase 15's blocker to Phase 16's unblock is complete.

**Status: OK.**

### D5. `_make_chunk_id` helper reuse

- Helper exists at `backend/src/dotmd/ingestion/chunker.py:23` with signature `_make_chunk_id(body_checksum, chunk_index, chunk_strategy) -> str`.
- P1 Task 2 `<interfaces>` block imports it literally: `from dotmd.ingestion.chunker import _make_chunk_id`.
- P1 plan prose does NOT restate the hash recipe; `_compute_body_checksum` shown in the interface only reuses `blake3.blake3(f"{kind}\n{text}".encode()).hexdigest()` which matches chunker.py:178 verbatim.
- P1 includes regression test `test_uses_chunker_make_chunk_id_helper` that monkeypatches the import and asserts the helper was called.
- P6 Task 2 schedules the same test name in its skeleton list.

**Status: OK.**

### D6. Known-acceptable risks (ACCEPTED)

- **ACCEPTED-1:** Decision #10 override path discards non-canonical `heading_hierarchy`/`level` values. CONTEXT.md truth #10 locks this with operator explicitly opting in (`--allow-payload-divergence`) and persisted audit in `migration_v16_state.payload_divergences`. Real data loss only occurs on operator intent; no longer silent. Expected production count = 0 per CONTEXT.md observation ("duplicates are symlinks/mirrors with identical headings"). Schema expansion (per-holder heading storage) deferred to backlog 999.8.

- **ACCEPTED-2:** P4 Task 1 Step 1 audit outcome (branch (a) vs (b)) is deferred to execution-time inspection. Reviewers converged that call-site change (not schema change) is permissible under Decision #5. If branch (b), `falkordb_graph.py` and `fts5.py` edits materialise; `files_modified` explicitly declares them as conditional (cycle-2 NEW-MED-2 hygiene fix).

- **ACCEPTED-3:** Trickle startup lock check is a GUARDRAIL, not a full mutex. Runbook (P3 Task 2 docstring + P2 SUMMARY) instructs operators to stop trickle service before `migrate run`. Stated explicitly; operational risk accepted.

- **ACCEPTED-4:** Post-commit graph/fingerprint cleanup in P4 is best-effort (failure WARN-logged, not rolled back). DB is authoritative; next `purge_orphaned_files` sweep reconciles. Explicitly documented in P4 Task 1 behavior.

## Remaining WARN-level findings

- **WARN-1** (D1): P1 step 5c M2M redirect assumes no PK-violation on `chunk_file_paths_*` composite PK. Holds for real data under current chunker determinism, but a defensive `ON CONFLICT (chunk_id, file_path, chunk_index) DO NOTHING` clause (or equivalent `INSERT OR IGNORE` pattern applied to UPDATE via INSERT-SELECT) would make the invariant self-evident in code. Not blocking; executor can add defensively or plan-checker can revisit post-implementation.

- **WARN-2** (D4 — minor hygiene): REQUIREMENTS.md file does not contain literal `DEDUP-*` IDs (they live in `16-RESEARCH.md` §Requirements Decomposition); ROADMAP.md references them as `DEDUP-01..DEDUP-11 (see 16-RESEARCH.md)`. Planning & plan-checker conventions resolve via research file. Cross-referencing works but a future refactor should move IDs to REQUIREMENTS.md. Not a blocker.

- **WARN-3** (D1 — chunk_index semantics): CONTEXT.md Decision #3 says "chunk_index may differ across files for same chunk". In practice, `_make_chunk_id` includes chunk_index in the hash input, so identical content at different `chunk_index` values produces DIFFERENT chunk_ids — they will never collide. Decision #3's phrasing is therefore technically imprecise given the `_make_chunk_id` formula. Doesn't affect plan correctness (collapse groups are guaranteed to share chunk_index), but may confuse future readers. Not blocking; possible CONTEXT.md clarification post-ship.

## Goal-backward completeness: PASS

All DEDUP requirements mapped to covering plans. All cycle-1 + cycle-2 HIGH concerns resolved and regression-guarded with named tests. Locked Decision #10 enforced through P1, P2, and P6 with consistent exit-code discipline. Shadow-column flow is UNIQUE-safe. M2M remap gap is closed by step 5c. Fail-closed divergence policy is unconditional with explicit operator override. Frontmatter is internally consistent; zero same-wave file overlap; cross-wave shared files are serialised by `depends_on`.

No blocker. Three low-severity warnings do not require revision.

VERDICT: READY
