---
phase: 38
slug: evaluate-embedded-surrealdb-as-unified-storage-backend
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-12
---

# Phase 38 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 |
| **Config file** | `backend/pyproject.toml`; e2e override in `backend/tests/e2e/pytest.ini` |
| **Quick run command** | `cd backend && uv run pytest tests/storage/test_falkordb_graph.py tests/storage/test_metadata_m2m.py tests/test_hybrid_bm25.py tests/test_vector_delete.py -x` |
| **Full suite command** | `cd backend && uv run pytest` |
| **Estimated runtime** | existing suite: repo-dependent; Surreal prototype checks should stay scoped per task |

---

## Sampling Rate

- **After every task commit:** Run the most local new Surreal-focused test file plus the nearest existing invariant test.
- **After every plan wave:** Run `cd backend && uv run pytest` plus the phase's copied-snapshot smoke command when available.
- **Before `/gsd-verify-work`:** Full suite must be green and the phase recommendation must cite parity, migration, and rollback evidence.
- **Max feedback latency:** keep per-task checks bounded; do not run full production reindex or TEI/GLiNER recomputation as validation.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 38-01-01 | 01 | 1 | STOR-01 | T-38-01 | Snapshot readers must not mutate production stores | integration | `cd backend && uv run pytest tests/storage/test_surreal_storage_contract.py -x` | ❌ W0 | ⬜ pending |
| 38-02-01 | 02 | 1 | STOR-03 | T-38-02 | Migration proof must import existing IDs/vectors/entities without TEI/GLiNER calls | integration | `cd backend && uv run pytest tests/ingestion/test_surreal_transform_only_migration.py -x` | ❌ W0 | ⬜ pending |
| 38-03-01 | 03 | 2 | STOR-02 | T-38-03 | Retrieval parity checks must compare Surreal outputs against current dotMD behavior on the same corpus | integration/parity | `cd backend && uv run pytest tests/search/test_surreal_retrieval_parity.py -x` | ❌ W0 | ⬜ pending |
| 38-04-01 | 04 | 2 | STOR-04 | T-38-04 | Backup, restore, rollback, and writer coordination must be rehearsed before a migrate recommendation | integration/manual-smoke | `cd backend && uv run pytest tests/storage/test_surreal_ops_safety.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/storage/test_surreal_storage_contract.py` — storage model and protocol contract coverage for STOR-01.
- [ ] `backend/tests/ingestion/test_surreal_transform_only_migration.py` — transform-only import coverage for STOR-03.
- [ ] `backend/tests/search/test_surreal_retrieval_parity.py` — FTS/vector/graph/hybrid parity coverage for STOR-02.
- [ ] `backend/tests/storage/test_surreal_ops_safety.py` — backup/restore/rollback and single-writer safety coverage for STOR-04.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Production-volume snapshot discipline | STOR-03, STOR-04 | The phase must not mutate live `index.db`, `feedback.db`, or FalkorDB while measuring migration feasibility | Use copied snapshots only; record source paths, counts, and checksum/row-count evidence in the final recommendation |
| Surreal CLI backup/import rehearsal, if used | STOR-04 | The `surreal` CLI is not currently installed on the host | Install/provision explicitly for the spike or document why CLI-backed backup evidence is unavailable |
| Final migrate/defer/reject recommendation | STOR-04 | The decision combines automated parity, operational risk, and user constraints | Recommendation document must cite which current data moved without CPU recomputation and which parity gates passed or failed |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency avoids full reindex/reembedding as routine validation
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
