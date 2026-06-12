---
phase: 16-content-dedup-schema
plan: 02
type: execute
wave: 6
depends_on: [16-01, 16-03, 16-04, 16-05]
files_modified:
  - backend/src/dotmd/cli.py
  - backend/src/dotmd/ingestion/migration_v16.py
autonomous: true
requirements: [DEDUP-06]
must_haves:
  truths:
    - "`dotmd migrate run` executes the migration with structured progress logs tagged dotmd-migrate."
    - "`dotmd migrate run --dry-run` reports collision counts, divergence stats, payload_mismatch counts, divergence-group count + top-5 example paths, disk delta estimate; persists nothing; acquires advisory lock."
    - "`dotmd migrate run --verify-only` calls `migration_v16.run_invariants` (shared helper — single source of truth) against live DB without mutation; additionally reports payload divergence count + top-5 example paths up-front per Decision #10."
    - "`dotmd migrate run --allow-payload-divergence` passes through to `run_migration_v16(allow_payload_divergence=True)` — documented in `--help` with a clear warning that canonical-keep discards non-canonical heading_hierarchy/level."
    - "`dotmd migrate status` reports current state marker, per-strategy progress, lock state, and — when present — the `allow_payload_divergence` flag value and payload_divergences JSON summary for the last run."
    - "All migration log lines carry the `dotmd-migrate` logger name so journald can filter by SyslogIdentifier."
    - "Exit codes are stable: 0 success / 1 invariant violation / 2 lock contention or flag mutex / 3 unexpected exception / 4 payload divergence detected without --allow-payload-divergence / 5 hard integrity error (text mismatch across collision group)."
    - "P2 is wave 6 — sequenced AFTER P5 (wave 5). P2 touches only the `migrate` command group in cli.py; P5's search/status changes already landed."
  artifacts:
    - path: backend/src/dotmd/cli.py
      provides: "`dotmd migrate` Click subcommand group with run / status subcommands and --dry-run / --verify-only / --allow-payload-divergence flags — appended AFTER P5's changes in the same file (wave 6 sequencing)."
    - path: backend/src/dotmd/ingestion/migration_v16.py
      provides: "Progress reporter with rows/sec, ETA, per-strategy collision counts; dry-run and verify-only code paths surface divergence preview; invariant runner helper already added in P1 (this plan wires CLI-visible reporting)."
  key_links:
    - from: backend/src/dotmd/cli.py
      to: backend/src/dotmd/ingestion/migration_v16.py
      via: "Click subcommand calls run_migration_v16(dry_run=..., verify_only=..., allow_payload_divergence=...) and status()"
      pattern: "migrate.*run_migration_v16|migrate.*status"
---

<objective>
Expose the migration through the CLI with the three ops modes Decision #7 locked: `--dry-run`, `--verify-only`, and `migrate status`. Add the `--allow-payload-divergence` override flag per Decision #10 (fail-closed by default, explicit override). Add structured progress logs (rows/sec, ETA, collision count) under the `dotmd-migrate` logger so journald can filter them. Reuse the invariant runner implemented in P1 — this plan adds NO new invariant logic (addresses Review-MED "avoid two sources of truth").

Purpose: Operators need a safe "look before you leap" path (`--dry-run`), a non-mutating health check (`--verify-only`) that surfaces payload-divergence preview, a way to inspect in-flight state (`migrate status`), and readable progress. Decision #10 (locked CONTEXT.md cycle 3) requires operators to opt in explicitly when a migration would discard divergent heading_hierarchy/level metadata — this plan wires the flag through.

Output: Click subcommand group `dotmd migrate {run,status}` with `--allow-payload-divergence` + divergence-preview output in `--verify-only` / `--dry-run`, plus progress reporter wired into migration_v16.py.
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
- `migration_v16.run_migration_v16(index_db: Path, *, dry_run: bool=False, verify_only: bool=False, allow_payload_divergence: bool=False) -> MigrationReport`
- `migration_v16.status(index_db: Path) -> StatusReport`
- `migration_v16.run_invariants(conn) -> InvariantReport`  ← single source of truth; do NOT duplicate here
- `migration_v16.PayloadDivergenceBlocked` — exception raised when divergences exist and allow_payload_divergence is False. CLI catches and exits 4.
- Module-level `logger = logging.getLogger("dotmd-migrate")`

`MigrationReport` and `StatusReport` fields (agreed with P1):
- per-strategy: rows_before, rows_after, collisions_collapsed, divergence_warnings, payload_mismatch_warnings, allow_payload_divergence (bool), payload_divergences (list of records), completed_at
- lock state: locked_at, pid, host, mode ('run'|'dry-run'|'verify-only'), None if clear
- mode: "run" | "dry-run" | "verify-only"
- disk_delta_estimate (dry-run only)
- payload_divergence_preview: {count: int, example_paths: list[str]} — populated by dry-run and verify-only

`InvariantReport` fields:
- passed: bool
- checks: list[{name, passed, detail}]  # structured, not log strings
- divergence_count: int                  # Decision #10 — surfaced by verify-only
- example_divergence_paths: list[str]    # up to 5

Wave dependency: Wave 1 = P6. Wave 2 = P1. Wave 3 = P3. Wave 4 = P4. Wave 5 = P5. **Wave 6 = P2**.
(Strictly serialised to avoid cli.py / pipeline.py / trickle.py overlap flagged by reviewers.)
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add progress reporter inside migration_v16.py + divergence preview in dry-run/verify-only</name>
  <files>backend/src/dotmd/ingestion/migration_v16.py</files>
  <behavior>
    - Per-strategy progress log every N rows (default 1000, configurable constant) emits: `strategy`, `rows_done`, `rows_total`, `rows_per_sec`, `eta_seconds`, `mode`.
    - Log format is single-line key=value structured for journald parsing. Example:
        `dotmd-migrate mode=run strategy=heading_512_50 rows_done=4000 rows_total=12345 rows_per_sec=850.3 eta=9.8s collisions=12`
    - End-of-strategy summary line with final counts including payload_mismatch_warnings AND allow_payload_divergence flag state.
    - End-of-run summary line aggregating all strategies.
    - Dry-run mode: identical log format with `mode=dry-run` on every line. Same rows_per_sec denominator (rows examined) so dry-run ETA meaningfully estimates a real run (addresses Review-LOW from codex about ETA denominator consistency).
    - Dry-run summary line additionally emits:
        `dotmd-migrate mode=dry-run payload_divergence_groups=<count> example_paths=<top5_csv> would_abort_without_flag=<true|false>`
      [Addresses cycle-2 NEW-HIGH-2 divergence-preview requirement]
    - Verify-only mode: emits invariant check lines from `run_invariants(conn)` output, one per check:
        `dotmd-migrate mode=verify-only invariant=64char_blake3 passed=true rows_examined=12345`
        `dotmd-migrate mode=verify-only invariant=no_orphan_vec_meta passed=false detail="2 orphan(s) in vec_meta_heading_512_50"`
      Additionally emits (Decision #10):
        `dotmd-migrate mode=verify-only payload_divergence_groups=<count> example_paths=<top5_csv>`
      Does NOT reimplement invariant or divergence-detection logic — consumes `InvariantReport` from P1.
    - Tests assert via pytest caplog: assert on structured extras (logger calls), not on exact string matching (addresses Review-LOW-10 "brittle log-string assertions").
      Prefer `assert report.rows_per_sec > 0`, `assert report.mode == "dry-run"`, `assert report.payload_divergence_preview.count == 2` over `assert "dry-run" in caplog.text`.
  </behavior>
  <action>
    Introduce a small `ProgressReporter` helper (closure or tiny class) that tracks start time + rows seen and emits throttled logs. Keep dependencies stdlib-only (Research §Don't Hand-Roll: no tqdm — outputs escape codes to journald).

    Verify-only mode invokes `run_invariants(conn)` — the SHARED helper already landed in P1 Task 2. This plan adds NO new invariant logic. Addresses Review-MED from codex: "single source of truth — don't let P2 invent a stub that later diverges from P6."

    Divergence-preview in `--verify-only` and `--dry-run`: P1 already computes divergences during per-strategy step 5/5f; this plan just surfaces them into `MigrationReport.payload_divergence_preview` (count + up to 5 example file_paths extracted from the first divergent collision groups). P1 populates this field; P2 prints it.

    Disk delta estimate for --dry-run: `rows_collapsed * avg_row_size` where `avg_row_size = db_size_bytes / total_rows_across_chunks_tables`. Emitted in dry-run summary line only (addresses Review-LOW from opencode).

    Do not touch the transaction semantics shipped in P1. This plan strictly adds observability.
  </action>
  <verify>
    <automated>cd backend && pytest tests/ingestion/test_migration_v16_progress.py -x --tb=short</automated>
  </verify>
  <done>
    - Progress lines emitted at throttled intervals.
    - Dry-run / verify-only modes reflected in `mode=` key.
    - Divergence preview emitted in both dry-run and verify-only summaries (count + up to 5 example paths).
    - Invariant lines derived from `run_invariants(conn)` — no duplicated check logic.
    - Disk delta estimate emitted in dry-run summary.
    - Tests assert on helper return values, not log-text substring matches.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Wire `dotmd migrate` Click subcommand group with --allow-payload-divergence</name>
  <files>backend/src/dotmd/cli.py</files>
  <behavior>
    CLI surface (Click):
      dotmd migrate run [--dry-run] [--verify-only] [--allow-payload-divergence]
      dotmd migrate status

    Mutual exclusion: `--dry-run` and `--verify-only` cannot be combined; error message points to `migrate status` for read-only state. `--allow-payload-divergence` is compatible with all three modes (run / dry-run / verify-only); in verify-only and dry-run it changes the reported `would_abort_without_flag` boolean.

    `--allow-payload-divergence` help text (exact prose):
      "Proceed with canonical-keep when a collision group has diverging heading_hierarchy
       or level across holders. WITHOUT this flag, the migration aborts with exit 4 and writes
       `divergence_report.txt` to the run directory. WITH this flag, canonical (MIN old chunk_id)
       metadata is kept and the divergence is recorded in migration_v16_state for audit.
       See Decision #10 in CONTEXT.md."

    `run`:
      - Loads settings, resolves `index_dir / "index.db"`.
      - Calls `run_migration_v16(index_db, dry_run=flag, verify_only=flag, allow_payload_divergence=flag)`.
      - Non-zero exit on fatal error:
        - Lock contention → exit 2 with clear message (`locked_at=… pid=… host=… mode=…`; hint: `DELETE FROM migration_v16_lock WHERE id = 1` if stale).
        - Invariant violation (verify-only) → exit 1 with summary of failed checks.
        - **PayloadDivergenceBlocked (no flag, divergences present) → exit 4** with:
            - Stdout pointer to `divergence_report.txt`.
            - Hint: "Re-run with --allow-payload-divergence to proceed with canonical-keep (see Decision #10)."
            - Count of divergent groups and top-5 example paths.
        - Hard integrity error (text mismatch across collision group) → exit 5.
        - Unexpected exception → exit 3.
      - Divergence/payload-mismatch WARN counts are NOT failures once `--allow-payload-divergence` is set (Decision #4 for vector divergence; Decision #10 for payload divergence with override) — exit 0 with summary.
      - Prints end-of-run summary from MigrationReport to stdout in human-readable form (journald still sees structured logs).

    `run --verify-only`:
      - Prints InvariantReport summary.
      - **Additionally prints divergence preview** (Decision #10): `payload_divergence_groups=<N>` and, if N > 0, up to 5 example file_paths and a hint:
          "N divergence group(s) detected. Migration will ABORT without --allow-payload-divergence. Re-run `dotmd migrate run --verify-only --allow-payload-divergence` to suppress this warning, or re-run `dotmd migrate run --allow-payload-divergence` to commit."
      - Exit 4 when divergence_count > 0 AND --allow-payload-divergence was NOT passed (tells operator up-front that real run would abort).
      - Exit 0 otherwise.

    `run --dry-run`:
      - Prints MigrationReport (inc. payload_divergence_preview) without persistence.
      - Exit 0 even when divergences are detected (dry-run is preview; operator decides next step).
      - Summary line states `would_abort_without_flag=true|false` so operator knows.

    `status`:
      - Calls `migration_v16.status(index_db)` and prints:
        - Lock state (held / clear; if held show locked_at + pid + host + mode + operator hint).
        - Per-strategy state rows (completed_at, collisions_collapsed, divergence_warnings, payload_mismatch_warnings, **allow_payload_divergence flag value**, **payload_divergences summary** (count only, full JSON available via direct SQL query)).
        - Whether `needs_migration_v16` is currently True or False.
      - Read-only — never mutates.

    Tests (CliRunner):
    - `migrate run --dry-run` on a fresh fixture DB: exit 0; DB bytes unchanged (hash before/after compared via `assert_db_bytes_unchanged`).
    - `migrate run --verify-only`: exit 0 on clean DB; DB unchanged.
    - `migrate run --dry-run --verify-only`: exit 2 with mutex error.
    - `migrate status` on never-migrated DB: prints "needs migration".
    - `migrate status` on post-migration DB: prints per-strategy rows including `allow_payload_divergence` flag state.
    - `migrate run` against a DB with stale lock: exit 2 with operator hint containing the literal string `DELETE FROM migration_v16_lock`.
    - `migrate run --verify-only` on a DB with an intentional invariant violation fixture: exit 1; stdout summarises failed checks.
    - **test_run_aborts_exit_4_on_divergence_without_flag** (NEW — Decision #10): fixture with heading_hierarchy divergence; `migrate run` exits 4; stderr mentions `divergence_report.txt`.
    - **test_run_proceeds_exit_0_with_flag** (NEW — Decision #10): same fixture + `--allow-payload-divergence`; exits 0; post-run status shows `allow_payload_divergence=1`.
    - **test_verify_only_reports_divergence_count_exit_4** (NEW — Decision #10): same fixture + `--verify-only`; exit 4; stdout has `payload_divergence_groups=1` and at least one example path.
    - **test_dry_run_reports_divergence_count_exit_0** (NEW — Decision #10): same fixture + `--dry-run`; exit 0; stdout has `payload_divergence_groups=1` and `would_abort_without_flag=true`.
    - **test_allow_payload_divergence_help_text_present** (NEW): assert `dotmd migrate run --help` output contains "Decision #10" reference.
  </behavior>
  <action>
    Follow the project's Click conventions (backend/CLAUDE.md: `cli.py` is a thin wrapper over `api/service.py`, but migration is a pure ingestion concern — call `migration_v16` directly, no service layer).

    Use Click's `group()` + `command()` pattern. Keep helper stubs minimal; CLI is thin glue.

    Exit code convention (documented in Click help text for `migrate run`):
      0 — success (run clean, dry-run clean, verify-only clean)
      1 — invariant violation in --verify-only
      2 — lock contention or flag mutex error
      3 — unexpected exception (unhandled DDL failure, etc.)
      4 — payload divergence detected without --allow-payload-divergence (Decision #10)
      5 — hard integrity error (text mismatch across collision group — real blake3 collision or chunker bug)

    File-overlap-safety: verify at the top of the task that prior waves (P5) already landed their cli.py edits. Then append the `migrate` group at the bottom of the file without touching `search` or `status` commands. If a merge conflict appears, stop and surface — this plan deliberately depends on P5 being merged first.

    Exception handling:
      try:
          report = run_migration_v16(index_db, dry_run=..., verify_only=..., allow_payload_divergence=...)
      except migration_v16.PayloadDivergenceBlocked as e:
          click.echo(f"ABORT: {e}", err=True)
          click.echo(f"See {run_dir}/divergence_report.txt", err=True)
          click.echo("Hint: re-run with --allow-payload-divergence to proceed with canonical-keep (Decision #10).", err=True)
          sys.exit(4)
      except RuntimeError as e:
          if "text mismatch" in str(e):
              sys.exit(5)
          raise
  </action>
  <verify>
    <automated>cd backend && pytest tests/cli/test_migrate_cli.py -x --tb=short</automated>
  </verify>
  <done>
    - `dotmd migrate run --help` shows --dry-run, --verify-only, --allow-payload-divergence flags and exit codes 0/1/2/3/4/5.
    - `dotmd migrate status` works against fresh and post-migration fixtures and surfaces `allow_payload_divergence` state.
    - All twelve CliRunner tests green (seven original + five new Decision-#10 guards).
    - No code duplication with migration_v16.py — CLI is a thin Click shell.
    - Verify-only exit code differentiates invariant failure (1) from divergence preview (4) from success (0).
    - Dry-run remains exit 0 even when divergences detected; summary includes `would_abort_without_flag` boolean.
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
| T-16-28 | Data loss | operator sets `--allow-payload-divergence` without reading divergence_report.txt | accept | help text warns explicitly; verify-only surfaces count up-front; persisted audit in `migration_v16_state.payload_divergences` allows post-hoc review |
</threat_model>

<verification>
- `pytest tests/cli/test_migrate_cli.py tests/ingestion/test_migration_v16_progress.py -x` green.
- `journalctl -t dotmd-migrate` filter works (manual post-deploy check — noted in SUMMARY).
- `dotmd migrate --help` shows three subcommand forms.
- `dotmd migrate run --help` shows `--allow-payload-divergence` with its warning prose.
- Invariant logic is imported from `migration_v16.run_invariants`, not reimplemented in CLI (grep gate: no `def.*invariant` in cli.py).
</verification>

<success_criteria>
- All three ops modes exposed via CLI with `--allow-payload-divergence` override wired through.
- Dry-run hash-equivalent DB proven unchanged via assert_db_bytes_unchanged.
- Verify-only exits 1 on fixture with invariant violations; exits 4 on fixture with payload divergence and no flag; 0 on clean fixture.
- Status output readable and complete, including lock mode and `allow_payload_divergence` state.
- Invariant helper reused from P1 — no duplicated logic.
- Exit-code matrix covers 0/1/2/3/4/5 with distinct semantics.
</success_criteria>

<output>
Create `.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-02-SUMMARY.md` covering: final CLI shape, exit code table (inc. 4 + 5), `--allow-payload-divergence` semantics and warnings, journald filter example, note that `run_invariants` is shared between CLI verify-only mode and P6 invariant tests (single source of truth).
</output>
</content>
</invoke>