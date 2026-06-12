---
phase: 16-content-dedup-schema
plan: 02
subsystem: ingestion/cli
tags: [migration, cli, dry-run, verify-only, progress-reporter, journald, decision-10, fail-closed]
dependency_graph:
  requires: [16-01, 16-03, 16-04, 16-05]
  provides: [dotmd-migrate-cli, progress-reporter, migration-ops-modes]
  affects: []
tech_stack:
  added: []
  patterns:
    - ProgressReporter with throttled key=value structured log lines (stdlib-only, no tqdm)
    - Click group/command pattern for migrate subcommand
    - sys.exit() for stable exit codes (0/1/2/3/4/5)
    - re-use run_invariants from P1 (single source of truth — no duplicated invariant logic)
key_files:
  created: []
  modified:
    - backend/src/dotmd/ingestion/migration_v16.py
    - backend/src/dotmd/cli.py
    - backend/tests/cli/test_migrate_cli.py
decisions:
  - "ProgressReporter is a lightweight class using stdlib time.monotonic — no tqdm (tqdm emits ANSI escapes to journald)"
  - "MigrationReport gains mode/per_strategy_progress/disk_delta_estimate fields; StatusReport gains needs_migration/per_strategy_state"
  - "migrate run --verify-only re-runs run_invariants on live DB after run_migration_v16 returns; single source of truth"
  - "sys.exit() used instead of raise SystemExit for clarity in all non-zero exit paths"
  - "[Rule 1 - Bug] Fixed test_cli_verify_only_invariant_violation_exit_1: INSERT had 2 bind params but only 1 value supplied"
metrics:
  duration: "~35m"
  completed: "2026-04-25"
  tasks: 2
  files_created: 0
  files_modified: 3
---

# Phase 16 Plan 02: Migration Ops Modes Summary

Exposes the Phase 16 migration through the CLI with three ops modes (Decision #7): `--dry-run`, `--verify-only`, and `migrate status`. Adds structured progress logging under the `dotmd-migrate` logger name for journald filtering. Adds `--allow-payload-divergence` override flag (Decision #10). Reuses `run_invariants` from P1 — no new invariant logic.

## CLI Surface

```
dotmd migrate run                                   # execute migration
dotmd migrate run --dry-run                         # preview, no writes
dotmd migrate run --verify-only                     # invariant check, no mutation
dotmd migrate run --allow-payload-divergence        # override fail-closed divergence gate
dotmd migrate status                                # inspect state + lock
```

## Exit Code Table

| Code | Meaning |
|------|---------|
| 0 | Success (run, dry-run, verify-only — all clean) |
| 1 | Invariant violation (--verify-only, at least one check failed) |
| 2 | Lock contention OR --dry-run + --verify-only mutex error |
| 3 | Unexpected exception (unhandled RuntimeError, etc.) |
| 4 | Payload divergence detected without --allow-payload-divergence (Decision #10) |
| 5 | Hard integrity error (text mismatch across collision group — blake3 collision or chunker bug) |

## --allow-payload-divergence Semantics

Wired through `run_migration_v16(allow_payload_divergence=True)`. When set:
- Migration proceeds with canonical-keep (MIN old chunk_id's heading_hierarchy/level wins)
- Each mismatch logged as WARN: `payload_mismatch_override strategy=... new_id=... diverged_fields=...`
- `payload_divergences` JSON and `allow_payload_divergence=1` persisted to `migration_v16_state`

When NOT set (default fail-closed):
- Any divergence group → `PayloadDivergenceBlocked` exception → ROLLBACK → write `divergence_report.txt`
- CLI exits 4, prints pointer to report and hint to re-run with `--allow-payload-divergence`

In `--verify-only` mode with divergences:
- Prints `payload_divergence_groups=N` and up to 5 example paths
- Exits 4 if N > 0 and flag not passed; exits 0 otherwise

In `--dry-run` mode with divergences:
- Always exits 0 (preview only)
- Summary includes `would_abort_without_flag=true|false`

## journald Filter

All migration log lines use `logger = logging.getLogger("dotmd-migrate")`. To filter in journald:

```bash
journalctl -t dotmd-migrate
```

Note: `SyslogIdentifier` is set by the process name. When running via `dotmd migrate run`, the identifier will be `dotmd`. The `dotmd-migrate` logger name appears in the message field. For structured log filtering, use:

```bash
journalctl | grep 'dotmd-migrate'
```

## ProgressReporter

`ProgressReporter` is a stdlib-only class that tracks rows processed and emits throttled structured log lines every `_PROGRESS_INTERVAL` (default 1000) rows:

```
dotmd-migrate mode=run strategy=heading_512_50 rows_done=1000 rows_total=5 rows_per_sec=850.3 eta=0.0s collisions=2
```

Fields: `mode`, `strategy`, `rows_done`, `rows_total`, `rows_per_sec`, `eta`, `collisions`. Single-line key=value format is journald-parseable without escapes (no tqdm).

`reporter.finish()` emits a final summary line and returns a dict stored in `MigrationReport.per_strategy_progress[strategy]`.

## Disk Delta Estimate (dry-run only)

Computed as `rows_collapsed * avg_row_size` where `avg_row_size = db_size_bytes / total_rows_across_strategies`. Emitted in the dry-run summary line and stored in `MigrationReport.disk_delta_estimate`.

## run_invariants Reuse (Single Source of Truth)

`--verify-only` CLI path calls `run_migration_v16(verify_only=True)` which internally calls `run_invariants(conn)` (P1 shared helper). After the call returns, the CLI also runs `run_invariants` directly on the live DB to get the `InvariantReport` for exit-code logic. This is the only place invariant logic lives — no duplication.

Grep gate (documented in plan): `grep -n "def.*invariant" backend/src/dotmd/cli.py` → no matches (zero invariant logic reimplemented in CLI).

## migrate status Output

```
needs migration: YES/NO

Per-strategy state:
  heading_512_50: status=complete completed_at=... collisions_collapsed=2 payload_mismatch_warnings=0 allow_payload_divergence=False

Advisory lock: clear
```

When lock is held, output includes `locked_at`, `pid`, `host`, `mode`, and hint:
```
To clear a stale lock: DELETE FROM migration_v16_lock WHERE id = 1
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test fixture INSERT binding mismatch in test_cli_verify_only_invariant_violation_exit_1**
- **Found during:** Task 2 test run — `sqlite3.ProgrammingError: Incorrect number of bindings`
- **Issue:** `test_migrate_cli.py` line 184 had `("short_invalid_id",)` (1 value) for an INSERT with 2 `?` placeholders (`chunk_id` and `file_path`).
- **Fix:** Changed to `("short_invalid_id", "/tmp/test.md")`.
- **Files modified:** `backend/tests/cli/test_migrate_cli.py`
- **Commit:** b787b4b

## Known Stubs

None.

## Threat Flags

No new security-relevant surface beyond the plan's threat model. All STRIDE mitigations implemented: advisory lock prevents concurrent runs (T-16-07), lock status output limited to pid/host (T-16-08 accepted), help text warns about `--allow-payload-divergence` data loss risk (T-16-28).

## Self-Check: PASSED

**Files modified:**
- `backend/src/dotmd/ingestion/migration_v16.py` — EXISTS
- `backend/src/dotmd/cli.py` — EXISTS
- `backend/tests/cli/test_migrate_cli.py` — EXISTS

**Commits:**
- `924ec71` — feat(16-02): Task 1: EXISTS
- `b787b4b` — feat(16-02): Task 2: EXISTS

**Test results:**
- P2 target tests (14): 14/14 GREEN
- P1 regression tests (37): 37/37 GREEN
- Phase 16 full suite (ingestion/ cli/ storage/ api/ mcp/ test_fixture_fidelity.py): 86 passed, 1 xfailed, 0 failures
