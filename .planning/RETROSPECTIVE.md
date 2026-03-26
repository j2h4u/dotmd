# Retrospective

## Milestone: v1.1 — Incremental Indexing

**Shipped:** 2026-03-26
**Phases:** 3 | **Plans:** 5 | **Tasks:** 9

### What Was Built
- FileTracker with two-stage mtime+size/MD5 change detection
- Per-file delete across all 3 stores (metadata, vectors, graph)
- Diff-based incremental indexing — unchanged files skipped entirely
- `--force` flag for full re-index bypass
- CLI diff summary + live change detection in status command
- Pipeline timing metrics with run_id correlation
- Mandatory TEI embedding server (no local model fallback)

### What Worked
- TDD approach (red → green → refactor) caught edge cases early (no-changes short-circuit, stale diff counts)
- Protocol-based architecture made adding new fields to IndexStats clean — changes threaded through naturally
- GSD phase structure kept scope focused — 3 clean phases with no scope creep
- Existing test infrastructure (conftest fixtures) made new tests fast to write

### What Was Inefficient
- Ran `uv run dotmd index` from host instead of Docker — wasted 10+ minutes on local model loading before killing it
- `seed-fingerprints` command written, fixed for lock, then deleted — could have skipped it entirely
- LadybugDB lock issue hit 3 times before being properly fixed (server.py creating new service per request)
- Phase 3 roadmap table showed "Pending" even after completion — state sync gap

### Patterns Established
- Always test via Docker (`docker compose exec` or API), never from host
- `DOTMD_EMBEDDING_URL` mandatory — prevents silent local model fallback
- Pipeline logs with `[run_id]` prefix for stage-level timing correlation
- Full re-index via API (`POST /index` with `force: true`), not CLI (avoids LadybugDB lock)

### Key Lessons
- Embedded graph DBs with file locks are fundamentally incompatible with server + CLI architecture — FalkorDB migration is necessary, not optional
- Schema migrations via idempotent `ALTER TABLE` + try/except work well for SQLite
- `read_only=True` on the global service was a latent bug — write endpoints need write access

### Cost Observations
- Model mix: 100% Opus 4.6 (1M context)
- Sessions: 2 (planning + execution in one, deployment/testing in another)
- Notable: Single-plan phases execute cleanly with one subagent, no wave overhead

## Cross-Milestone Trends

| Milestone | Phases | Plans | Duration | Key Metric |
|-----------|--------|-------|----------|------------|
| v1.1 | 3 | 5 | 2 days | Incremental index: <1s (was 50min) |
