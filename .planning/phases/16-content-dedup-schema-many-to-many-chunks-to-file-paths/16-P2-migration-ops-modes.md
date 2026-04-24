---
phase: 16-content-dedup-schema
plan: 2
type: execute
wave: 5
depends_on: [16-P1, 16-P3, 16-P4]
files_modified:
  - backend/src/dotmd/cli.py
  - backend/src/dotmd/ingestion/migration_v16.py
autonomous: true
requirements: [DEDUP-06]
must_haves:
  truths:
    - "`dotmd migrate run` executes the migration with structured progress logs tagged dotmd-migrate."
    - "`dotmd migrate run --dry-run` reports collision counts, divergence stats, payload_mismatch counts, disk delta estimate; persists nothing; acquires advisory lock."
    - "`dotmd migrate run --verify-only` calls `migration_v16.run_invariants` (shared helper — single source of truth) against live DB without mutation."
    - "`dotmd migrate status` reports current state marker, per-strategy progress, lock state."
    - "All migration log lines carry the `dotmd-migrate` logger name so journald can filter by SyslogIdentifier."
    - "Exit codes are stable: 0 success / 1 invariant violation / 2 lock contention or flag mutex / 3 unexpected exception."
    - "P2 touches only the `migrate` command group in cli.py; P5's search/status changes already landed in the earlier wave with no merge overlap."
  artifacts:
    - path: backend/src/dotmd/cli.py
      provides: "`dotmd migrate` Click subcommand group with run / status subcommands and --dry-run / --verify-only flags — appended AFTER P5's changes in the same file (wave 5 sequencing)."
    - path: backend/src/dotmd/ingestion/migration_v16.py
      provides: "Progress reporter with rows/sec, ETA, per-strategy collision counts; dry-run and verify-only code paths; invariant runner helper already added in P1 (this plan wires CLI-visible reporting)."
  key_links:
    - from: backend/src/dotmd/cli.py
      to: backend/src/dotmd/ingestion/migration_v16.py
      via: "Click subcommand calls run_migration_v16(dry_run=..., verify_only=...) and status()"
      pattern: "migrate.*run_migration_v16|migrate.*status"
---

<objective>
Expose the migration through the CLI with the three ops modes Decision #7 locked: `--dry-run`, `--verify-only`, and `migrate status`. Add structured progress logs (rows/sec, ETA, collision count) under the `dotmd-migrate` logger so journald can filter them. Reuse the invariant runner implemented in P1 — this plan adds NO new invariant logic (addresses Review-MED "avoid two sources of truth").

Purpose: Operators need a safe "look before you leap" path (`--dry-run`), a non-mutating health check (`--verify-only`), a way to inspect in-flight state (`migrate status`), and readable progress. This plan wires those without touching the core migration semantics delivered in P1. Sequenced AFTER P5 (wave 5) to resolve the cli.py file-ownership conflict flagged by both reviewers.

Output: Click subcommand group `dotmd migrate {run,status}` + progress reporter wired into migration_v16.py.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-CONTEXT.md
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-RESEARCH.md
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-REVIEWS.md
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-01-SUMMARY.md
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-03-SUMMARY.md
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-04-SUMMARY.md
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-05-SUMMARY.md
@backend/src/dotmd/cli.py
@backend/src/dotmd/ingestion/migration_v16.py

<interfaces>
From P1 SUMMARY (available at execution time):
- `migration_v16.run_migration_v16(index_db: Path, *, dry_run: bool=False, verify_only: bool=False) -> MigrationReport`
- `migration_v16.status(index_db: Path) -> StatusReport`
- `migration_v16.run_invariants(conn) -> InvariantReport`  ← single source of truth; do NOT duplicate here
- Module-level `logger = logging.getLogger("dotmd-migrate")`

`MigrationReport` and `StatusReport` fields (agreed with P1):
- per-strategy: rows_before, rows_after, collisions_collapsed, divergence_warnings, payload_mismatch_warnings, completed_at
- lock state: locked_at, pid, host, mode ('run'|'dry-run'|'verify-only'), None if clear
- mode: "run" | "dry-run" | "verify-only"
- disk_delta_estimate (dry-run only)

`InvariantReport` fields:
- passed: bool
- checks: list[{name, passed, detail}]  # structured, not log strings

Wave dependency: Wave 1 = P6. Wave 2 = P1. Wave 3 = P3. Wave 4 = P4. Wave 5 = P5. Wave 6 = P2.
(Strictly serialised to avoid cli.py / pipeline.py / trickle.py overlap flagged by both reviewers.)
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add progress reporter inside migration_v16.py</name>
  <files>backend/src/dotmd/ingestion/migration_v16.py</files>
  <behavior>
    - Per-strategy progress log every N rows (default 1000, configurable constant) emits: `strategy`, `rows_done`, `rows_total`, `rows_per_sec`, `eta_seconds`, `mode`.
    - Log format is single-line key=value structured for journald parsing. Example:
        `dotmd-migrate mode=run strategy=heading_512_50 rows_done=4000 rows_total=12345 rows_per_sec=850.3 eta=9.8s collisions=12`
    - End-of-strategy summary line with final counts including payload_mismatch_warnings.
    - End-of-run summary line aggregating all strategies.
    - Dry-run mode: identical log format with `mode=dry-run` on every line. Same rows_per_sec denominator (rows examined) so dry-run ETA meaningfully estimates a real run (addresses Review-LOW from codex about ETA denominator consistency).
    - Verify-only mode: emits invariant check lines from `run_invariants(conn)` output, one per check:
        `dotmd-migrate mode=verify-only invariant=64char_blake3 passed=true rows_examined=12345`
        `dotmd-migrate mode=verify-only invariant=no_orphan_vec_meta passed=false detail="2 orphan(s) in vec_meta_heading_512_50"`
      Does NOT reimplement invariant logic — consumes `InvariantReport` from P1.
    - Tests assert via pytest caplog: assert on structured extras (logger calls), not on exact string matching (addresses Review-LOW-10 "brittle log-string assertions").
      Prefer `assert report.rows_per_sec > 0`, `assert report.mode == "dry-run"` over `assert "dry-run" in caplog.text`.
  </behavior>
  <action>
    Introduce a small `ProgressReporter` helper (closure or tiny class) that tracks start time + rows seen and emits throttled logs. Keep dependencies stdlib-only (Research §Don't Hand-Roll: no tqdm — outputs escape codes to journald).

    Verify-only mode invokes `run_invariants(conn)` — the SHARED helper already landed in P1 Task 2. This plan adds NO new invariant logic. Addresses Review-MED from codex: "single source of truth — don't let P2 invent a stub that later diverges from P6."

    Disk delta estimate for --dry-run: `rows_collapsed * avg_row_size` where `avg_row_size = db_size_bytes / total_rows_across_chunks_tables`. Emitted in dry-run summary line only (addresses Review-LOW from opencode).

    Do not touch the transaction semantics shipped in P1. This plan strictly adds observability.
  </action>
  <verify>
    <automated>cd backend && pytest tests/ingestion/test_migration_v16_progress.py -x --tb=short</automated>
  </verify>
  <done>
    - Progress lines emitted at throttled intervals.
    - Dry-run / verify-only modes reflected in `mode=` key.
    - Invariant lines derived from `run_invariants(conn)` — no duplicated check logic.
    - Disk delta estimate emitted in dry-run summary.
    - Tests assert on helper return values, not log-text substring matches.
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
      - Non-zero exit on fatal error:
        - Lock contention → exit 2 with clear message (`locked_at=… pid=… host=… mode=…`; hint: `DELETE FROM migration_v16_lock WHERE id = 1` if stale).
        - Invariant violation (verify-only) → exit 1 with summary of failed checks.
        - Unexpected exception → exit 3.
      - Divergence/payload-mismatch WARN counts are NOT failures (Decision #4) — exit 0 with summary.
      - Prints end-of-run summary from MigrationReport to stdout in human-readable form (journald still sees structured logs).

    `status`:
      - Calls `migration_v16.status(index_db)` and prints:
        - Lock state (held / clear; if held show locked_at + pid + host + mode + operator hint).
        - Per-strategy state rows (completed_at, collisions_collapsed, divergence_warnings, payload_mismatch_warnings).
        - Whether `needs_migration_v16` is currently True or False.
      - Read-only — never mutates.

    Tests (CliRunner):
    - `migrate run --dry-run` on a fresh fixture DB: exit 0; DB bytes unchanged (hash before/after compared via `assert_db_bytes_unchanged`).
    - `migrate run --verify-only`: exit 0; DB unchanged.
    - `migrate run --dry-run --verify-only`: exit 2 with mutex error.
    - `migrate status` on never-migrated DB: prints "needs migration".
    - `migrate status` on post-migration DB: prints per-strategy rows.
    - `migrate run` against a DB with stale lock: exit 2 with operator hint containing the literal string `DELETE FROM migration_v16_lock`.
    - `migrate run --verify-only` on a DB with an intentional invariant violation fixture: exit 1; stdout summarises failed checks.
  </behavior>
  <action>
    Follow the project's Click conventions (backend/CLAUDE.md: `cli.py` is a thin wrapper over `api/service.py`, but migration is a pure ingestion concern — call `migration_v16` directly, no service layer).

    Use Click's `group()` + `command()` pattern. Keep helper stubs minimal; CLI is thin glue.

    Exit code convention (documented in Click help text for `migrate run`):
      0 — success (run clean, dry-run clean, verify-only clean)
      1 — invariant violation in --verify-only
      2 — lock contention or flag mutex error
      3 — unexpected exception (unhandled DDL failure, etc.)

    File-overlap-safety: verify at the top of the task that prior waves (P5) already landed their cli.py edits. Then append the `migrate` group at the bottom of the file without touching `search` or `status` commands. If a merge conflict appears, stop and surface — this plan deliberately depends on P5 being merged first.
  </action>
  <verify>
    <automated>cd backend && pytest tests/cli/test_migrate_cli.py -x --tb=short</automated>
  </verify>
  <done>
    - `dotmd migrate run --help` shows --dry-run, --verify-only flags and exit codes.
    - `dotmd migrate status` works against fresh and post-migration fixtures.
    - All seven CliRunner tests green.
    - No code duplication with migration_v16.py — CLI is a thin Click shell.
    - Verify-only exit code differentiates invariant failure (1) from success (0).
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
- `journalctl -t dotmd-migrate` filter works (manual post-deploy check — noted in SUMMARY).
- `dotmd migrate --help` shows three subcommand forms.
- Invariant logic is imported from `migration_v16.run_invariants`, not reimplemented in CLI (grep gate: no `def.*invariant` in cli.py).
</verification>

<success_criteria>
- All three ops modes exposed via CLI and confirmed by tests.
- Dry-run hash-equivalent DB proven unchanged via assert_db_bytes_unchanged.
- Verify-only exits 1 on fixture containing known invariant violations; 0 on clean fixture.
- Status output readable and complete, including lock mode field.
- Invariant helper reused from P1 — no duplicated logic.
</success_criteria>

<output>
Create `.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-02-SUMMARY.md` covering: final CLI shape, exit code table, journald filter example, note that `run_invariants` is shared between CLI verify-only mode and P6 invariant tests (single source of truth).
</output>
</content>
</invoke>