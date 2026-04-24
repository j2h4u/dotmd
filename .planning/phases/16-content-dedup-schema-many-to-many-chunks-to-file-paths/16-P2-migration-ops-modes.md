---
phase: 16-content-dedup-schema
plan: 2
type: execute
wave: 3
depends_on: [16-P1]
files_modified:
  - backend/src/dotmd/cli.py
  - backend/src/dotmd/ingestion/migration_v16.py
autonomous: true
requirements: [DEDUP-06]
must_haves:
  truths:
    - "`dotmd migrate run` executes the migration with structured progress logs tagged dotmd-migrate."
    - "`dotmd migrate run --dry-run` reports collision counts, divergence stats, disk delta estimate; persists nothing."
    - "`dotmd migrate run --verify-only` runs invariant checks against live DB without mutation."
    - "`dotmd migrate status` reports current state marker, per-strategy progress, lock state."
    - "All migration log lines carry the `dotmd-migrate` logger name so journald can filter by SyslogIdentifier."
  artifacts:
    - path: backend/src/dotmd/cli.py
      provides: "`dotmd migrate` Click subcommand group with run / status subcommands and --dry-run / --verify-only flags."
    - path: backend/src/dotmd/ingestion/migration_v16.py
      provides: "Progress reporter with rows/sec, ETA, per-strategy collision counts, dry-run and verify-only code paths."
  key_links:
    - from: backend/src/dotmd/cli.py
      to: backend/src/dotmd/ingestion/migration_v16.py
      via: "Click subcommand calls run_migration_v16(dry_run=..., verify_only=...) and status()"
      pattern: "migrate.*run_migration_v16|migrate.*status"
---

<objective>
Expose the migration through the CLI with the three ops modes Decision #7 locked: `--dry-run`, `--verify-only`, and `migrate status`. Add structured progress logs (rows/sec, ETA, collision count) under the `dotmd-migrate` logger so journald can filter them.

Purpose: Operators need a safe "look before you leap" path (`--dry-run`), a non-mutating health check (`--verify-only`), a way to inspect in-flight state (`migrate status`), and readable progress. This plan wires those without touching the core migration semantics delivered in P1.

Output: Click subcommand group `dotmd migrate {run,status}` + progress reporter wired into migration_v16.py.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-CONTEXT.md
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-RESEARCH.md
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-01-SUMMARY.md
@backend/src/dotmd/cli.py
@backend/src/dotmd/ingestion/migration_v16.py

<interfaces>
From P1 SUMMARY (assumed available at execution time):
- `migration_v16.run_migration_v16(index_db: Path, *, dry_run: bool=False, verify_only: bool=False) -> MigrationReport`
- `migration_v16.status(index_db: Path) -> StatusReport`
- Module-level `logger = logging.getLogger("dotmd-migrate")`

`MigrationReport` and `StatusReport` fields (agreed with P1):
- per-strategy: rows_before, rows_after, collisions_collapsed, divergence_warnings, completed_at
- lock state: locked_at, pid, host (None if clear)
- mode: "run" | "dry-run" | "verify-only"
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add progress reporter inside migration_v16.py</name>
  <files>backend/src/dotmd/ingestion/migration_v16.py</files>
  <behavior>
    - Per-strategy progress log every N rows (default 1000, configurable constant) emits: `strategy`, `rows_done`, `rows_total`, `rows_per_sec`, `eta_seconds`.
    - Log format is single-line key=value structured for journald parsing. Example: `dotmd-migrate strategy=heading_512_50 rows_done=4000 rows_total=12345 rows_per_sec=850.3 eta=9.8s collisions=12`.
    - End-of-strategy summary line with final counts.
    - End-of-run summary line aggregating all strategies.
    - Dry-run mode: identical log format plus prefix token `mode=dry-run` on every line.
    - Verify-only mode: emits invariant check lines (`invariant=64char_blake3 pass=N fail=M`, etc.) — actual invariant list comes from P6 but this task wires the reporting shape.
    - Tests assert log output via pytest caplog fixture: rows_per_sec emitted, eta emitted, mode prefix correct.
  </behavior>
  <action>
    Introduce a small `ProgressReporter` helper (closure or tiny class) that tracks start time + rows seen and emits throttled logs. Keep dependencies stdlib-only (Research §Don't Hand-Roll: no tqdm — outputs escape codes to journald).

    Verify-only mode invokes a `run_invariants(conn)` stub that P6 will fill in; for this plan provide a pass-through that runs the bare invariant set already checked in P1 tests (64-char chunk_id, no orphan vec_meta rows). P6 extends it.

    Do not touch the transaction semantics shipped in P1. This plan strictly adds observability.
  </action>
  <verify>
    <automated>cd backend && pytest tests/ingestion/test_migration_v16_progress.py -x --tb=short</automated>
  </verify>
  <done>
    - Progress lines emitted at throttled intervals.
    - Dry-run / verify-only modes reflected in log prefix.
    - caplog-based tests green.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Wire `dotmd migrate` Click subcommand group</name>
  <files>backend/src/dotmd/cli.py</files>
  <behavior>
    CLI surface (Click):
      dotmd migrate run [--dry-run] [--verify-only]
      dotmd migrate status

    Mutual exclusion: `--dry-run` and `--verify-only` cannot be combined; error message points to `migrate status` for read-only state.

    `run`:
      - Loads settings, resolves `index_dir / "index.db"`.
      - Calls `run_migration_v16(index_db, dry_run=flag, verify_only=flag)`.
      - Non-zero exit on fatal error (lock contention → exit 2 with clear message per Research Pattern 2); zero exit on clean run even with divergence WARNs (Decision #4).
      - Prints end-of-run summary from MigrationReport to stdout in a human-readable form (journald still sees structured logs).

    `status`:
      - Calls `migration_v16.status(index_db)` and prints:
        - Lock state (held / clear; if held, show locked_at + pid + host + operator hint to manually DELETE if stale).
        - Per-strategy state rows (completed_at, collisions_collapsed, divergence_warnings).
        - Whether `needs_migration_v16` is currently True or False.
      - Read-only — never mutates.

    Tests (CliRunner):
    - `migrate run --dry-run` on a fresh fixture DB: exit 0; DB unchanged (hash-of-bytes compared).
    - `migrate run --verify-only`: exit 0; DB unchanged.
    - `migrate run --dry-run --verify-only`: exit 2 with mutex error.
    - `migrate status` on never-migrated DB: prints "needs migration".
    - `migrate status` on post-migration DB: prints per-strategy rows.
    - `migrate run` against a DB with stale lock: exit 2 with operator hint containing "DELETE FROM migration_v16_lock".
  </behavior>
  <action>
    Follow the project's Click conventions (backend/CLAUDE.md: `cli.py` is a thin wrapper over `api/service.py`, but migration is a pure ingestion concern — call `migration_v16` directly, no service layer).

    Use Click's `group()` + `command()` pattern. Keep helper stubs minimal; CLI is thin glue.

    Exit code convention:
      0 — success (run clean, dry-run clean, verify-only clean)
      1 — invariant violation in --verify-only
      2 — lock contention or flag mutex error
      3 — unexpected exception (unhandled DDL failure, etc.)

    Document these codes in the Click help text for `migrate run`.
  </action>
  <verify>
    <automated>cd backend && pytest tests/cli/test_migrate_cli.py -x --tb=short</automated>
  </verify>
  <done>
    - `dotmd migrate run --help` shows --dry-run, --verify-only flags and exit codes.
    - `dotmd migrate status` works against fresh and post-migration fixtures.
    - All six CliRunner tests green.
    - No code duplication with migration_v16.py — CLI is a thin Click shell.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| operator → `dotmd migrate` CLI | single-user localhost; no auth required |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-16-06 | Tampering | operator misuse `--dry-run` when meant `run` | accept | dry-run is strictly safer than run; no data risk in either direction of slip |
| T-16-07 | Denial of service | concurrent operator invocations of `migrate run` | mitigate | `migration_v16_lock` (P1) — second run exits 2 |
| T-16-08 | Information disclosure | lock status output includes pid/host | accept | localhost single-user; pid/host is operational diagnostic |
</threat_model>

<verification>
- `pytest tests/cli/test_migrate_cli.py tests/ingestion/test_migration_v16_progress.py -x` green.
- `journalctl -t dotmd-migrate` filter works (manual post-deploy check — noted in P1 SUMMARY).
- `dotmd migrate --help` shows three subcommand forms.
</verification>

<success_criteria>
- All three ops modes exposed via CLI and confirmed by tests.
- Dry-run hash-equivalent DB proven unchanged.
- Verify-only exits 1 on fixture containing known invariant violations; 0 on clean fixture.
- Status output readable and complete.
</success_criteria>

<output>
Create `.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-02-SUMMARY.md` covering: final CLI shape, exit code table, journald filter example.
</output>
