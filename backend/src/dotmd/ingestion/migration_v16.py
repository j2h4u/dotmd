"""Phase 16 schema migration: introduce per-strategy M2M chunk_file_paths_* tables.

Replaces file_path / chunk_index / char_offset columns in chunks_* with a
separate chunk_file_paths_<strategy>(chunk_id, file_path, chunk_index) table.
Also remaps chunk_ids from pre-v15 blake2b (128-char) or intermediate formats
to content-addressed blake3 (64-char), collapsing collision groups.

Flow overview (per strategy, inside a transaction):
  Step 1  — Create chunk_file_paths_<strategy> + index.
  Step 2  — Backfill M2M from chunks_*.file_path / chunk_index.
  Step 3  — ADD COLUMN new_chunk_id (shadow column).
  Step 4  — Compute new_chunk_id for every row (calls chunker._make_chunk_id).
  Step 5  — Detect collision groups; for each:
    5a. payload_invariant_check (text must match; heading/level divergence → policy gate).
    5b. canonical_old_id = MIN(old_ids).
    5c. Redirect non-canonical M2M rows to canonical old id BEFORE delete.
        [cycle-2 NEW-HIGH-1 fix]
    5d. Vector divergence WARN (Decision #4).
    5e. Collapse: DELETE non-canonical rows from chunks_*/vec_meta_*/chunks_fts_*.
  Step 5f — Fail-closed divergence gate (Decision #10 / cycle-2 NEW-HIGH-2 fix).
            Any divergence → write divergence_report.txt, ROLLBACK, raise PayloadDivergenceBlocked.
            No override flag — fail-closed is the only path (YAGNI cleanup 2026-04-25).
  Step 6  — Sanity: zero duplicates in new_chunk_id.
  Step 7  — Remap M2M / vec_meta / chunks_fts chunk_id → new_chunk_id.
  Step 8  — UPDATE chunks_*.chunk_id = new_chunk_id (safe — uniqueness guaranteed).
  Step 9  — DROP COLUMN new_chunk_id + legacy columns; fallback to rebuild.
  Step 10 — INSERT INTO migration_v16_state.
  COMMIT (or ROLLBACK for dry_run / verify_only).

Post-flight: release advisory lock.

Run offline (container must be stopped):
    python -m dotmd.ingestion.migration_v16 /path/to/index.db [--dry-run] [--verify-only]
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import socket
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import blake3 as _blake3

import dotmd.ingestion.chunker as _chunker_module
from dotmd.storage.lock_constants import LOCK_TABLE

logger = logging.getLogger("dotmd-migrate")

# Whitelist for strategy names interpolated into SQL.  Only alphanumeric chars
# and underscores are permitted — this prevents SQL injection via crafted table
# names in a user-supplied index.db (e.g. "chunks_foo; DROP TABLE bar").
_SAFE_STRATEGY_RE = re.compile(r"^[a-zA-Z0-9_]+$")


def _validate_strategy(strategy: str) -> str:
    """Raise ValueError if *strategy* contains SQL-unsafe characters.

    Called at the discovery boundary so every downstream f-string
    interpolation of strategy names is safe.
    """
    if not _SAFE_STRATEGY_RE.fullmatch(strategy):
        raise ValueError(
            f"Unsafe strategy name {strategy!r} — only alphanumeric chars and "
            "underscores are allowed.  If this DB was produced by dotmd, this "
            "is a bug; otherwise the DB may have been tampered with."
        )
    return strategy


# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------

class PayloadDivergenceBlocked(RuntimeError):
    """Raised when collision groups have diverging heading_hierarchy or level.

    Decision #10 fail-closed: no override flag exists (YAGNI cleanup 2026-04-25).
    Migration writes divergence_report.txt, rolls back, and raises this exception.
    CLI translates this to exit code 4.
    """


# ---------------------------------------------------------------------------
# Report dataclasses
# ---------------------------------------------------------------------------

@dataclass
class MigrationReport:
    """Summary of a migration run."""

    completed: bool = False
    completed_strategies: list[str] = field(default_factory=list)
    skipped_strategies: list[str] = field(default_factory=list)
    collisions_collapsed: int = 0
    divergence_warnings: int = 0
    payload_mismatch_warnings: int = 0
    dry_run: bool = False
    verify_only: bool = False
    lock_mode: str = "run"
    # dry-run / verify-only specific fields
    divergence_report_lines: list[str] = field(default_factory=list)
    payload_divergence_preview: dict[str, Any] | None = None
    # Progress reporter fields (Task 1 — P2)
    mode: str = "run"  # "run" | "dry-run" | "verify-only"
    per_strategy_progress: dict[str, dict[str, Any]] = field(default_factory=dict)
    disk_delta_estimate: int | None = None  # bytes, dry-run only
    # verify-only: result of run_invariants() so CLI can reuse it without
    # re-opening the DB.  None for dry-run and real-run paths.
    invariant_report: "InvariantReport | None" = None


@dataclass
class InvariantCheck:
    """A single invariant check result."""
    name: str
    passed: bool
    detail: str = ""


@dataclass
class InvariantReport:
    """Result of run_invariants()."""
    passed: bool
    checks: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class StatusReport:
    """Result of status()."""
    strategies: dict[str, dict[str, Any]] = field(default_factory=dict)
    lock_held: bool = False
    lock_info: dict[str, Any] | None = None
    # Convenience aliases expected by test_migration_v16_ops.py
    needs_migration: bool = True
    per_strategy_state: dict[str, dict[str, Any]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_body_checksum_from_file(file_path: str, kind: str) -> str:
    """Compute the canonical body_checksum by reading the source file from disk.

    Formula: blake3(kind + "\\n" + body) where body is the file content after
    frontmatter strip — identical to chunker.chunk_file and reader.chunk_checksum.

    Used as a fallback when chunk_fingerprints_<strategy> has no row for a
    file_path (e.g. partial fingerprint table from an interrupted prior run).
    """
    from dotmd.ingestion.reader import parse_frontmatter, read_file
    content = read_file(Path(file_path))
    _, body = parse_frontmatter(content)
    return _blake3.blake3(f"{kind}\n{body}".encode()).hexdigest()


def _get_body_checksums_for_strategy(
    conn: sqlite3.Connection,
    strategy: str,
    file_paths: list[str],
) -> dict[str, str]:
    """Look up canonical body_checksums from chunk_fingerprints_<strategy>.

    Returns a mapping of file_path → checksum for all file_paths that have
    a fingerprint row.  Missing entries must be resolved by the caller (either
    via disk read or by aborting with a clear error).

    The checksum stored in chunk_fingerprints_<strategy> is
    blake3(kind + "\\n" + body) — the same formula used by chunker.chunk_file
    to compute body_checksum before calling _make_chunk_id.
    """
    if not file_paths:
        return {}
    fp_table = f"chunk_fingerprints_{strategy}"
    # Check the fingerprints table exists before querying.
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (fp_table,),
    ).fetchone()
    if not exists:
        return {}
    placeholders = ",".join("?" for _ in file_paths)
    rows = conn.execute(
        f"SELECT file_path, checksum FROM {fp_table} "
        f"WHERE file_path IN ({placeholders})",
        file_paths,
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def _compute_new_id_for_row(
    body_checksum: str, chunk_index: int, strategy: str
) -> str:
    """Derive the new blake3 chunk_id for a row.

    Parameters
    ----------
    body_checksum:
        Canonical blake3(kind + "\\n" + body) from chunk_fingerprints_<strategy>
        or computed fresh from the source file.  Must match the formula used by
        chunker.chunk_file so migrated IDs match post-migration fresh-index IDs.
    chunk_index:
        Position of this chunk within the file.
    strategy:
        Strategy name (prevents cross-strategy ID collisions).

    Reuses chunker._make_chunk_id via the module reference so monkeypatching
    in tests is respected (Review-HIGH-3 compliance).
    """
    return _chunker_module._make_chunk_id(body_checksum, chunk_index, strategy)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors using stdlib math."""
    dot = math.fsum(x * y for x, y in zip(a, b, strict=True))
    mag_a = math.sqrt(math.fsum(x * x for x in a))
    mag_b = math.sqrt(math.fsum(x * x for x in b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 1.0  # treat zero vectors as identical
    return dot / (mag_a * mag_b)


def _fetch_vector_for_divergence_check(
    conn: sqlite3.Connection, strategy: str, chunk_id: str
) -> list[float] | None:
    """Fetch a vector from vec_meta_* for divergence checking.

    Returns None if no vec_meta table exists or the chunk_id is absent.
    vec0 virtual tables require the extension; we read from vec_meta plain
    tables only (text_hash as proxy — no actual vector read needed for the
    divergence check in migration tests).

    Note: in production the vec0 table holds the actual float vectors. Since
    migration tests do not load the sqlite_vec extension, this helper reads
    text_hash from vec_meta as a proxy. The actual cosine divergence check
    requires the real vector; callers that can load the extension should
    override this via monkeypatching (test_divergence_warn_emitted tests do
    exactly this).
    """
    # Discover vec_meta tables for this strategy
    meta_tables = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?",
            (f"vec_meta_{strategy}_%",),
        ).fetchall()
    ]
    for mt in meta_tables:
        row = conn.execute(
            f"SELECT rowid FROM {mt} WHERE chunk_id = ?", (chunk_id,)
        ).fetchone()
        if row is not None:
            return None  # cannot read actual float vector without sqlite_vec
    return None


def _discover_strategies(conn: sqlite3.Connection) -> list[str]:
    """Return all strategy names from chunks_* tables (excluding FTS and M2M).

    Each returned name is validated against ``_SAFE_STRATEGY_RE`` before being
    returned.  A tampered index.db with a crafted table name (e.g.
    ``chunks_foo; DROP TABLE bar``) will raise ``ValueError`` here rather than
    propagating unsafe SQL through every downstream f-string interpolation.
    """
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name LIKE 'chunks_%' "
        "AND name NOT LIKE 'chunks_fts_%' "
        "AND name NOT LIKE 'chunk_file_paths_%'"
    ).fetchall()
    return [_validate_strategy(r[0].removeprefix("chunks_")) for r in rows]


def _strategy_needs_migration(conn: sqlite3.Connection, strategy: str) -> bool:
    """True if this strategy still needs v16 migration."""
    # Check state table
    state_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='migration_v16_state'"
    ).fetchone()
    if state_exists:
        row = conn.execute(
            "SELECT status FROM migration_v16_state WHERE strategy = ?", (strategy,)
        ).fetchone()
        if row and row[0] == "complete":
            return False

    # Check for presence of file_path column in chunks_* table
    table = f"chunks_{strategy}"
    pragma = conn.execute(f"PRAGMA table_info({table})").fetchall()
    col_names = {r[1] for r in pragma}
    if "file_path" in col_names:
        return True

    # Check for non-64-hex chunk_ids
    count = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE length(chunk_id) != 64"
    ).fetchone()[0]
    return count > 0


def _ensure_state_table(conn: sqlite3.Connection) -> None:
    """Create migration_v16_state and migration_v16_lock if absent."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS migration_v16_state (
            strategy                TEXT PRIMARY KEY,
            status                  TEXT NOT NULL DEFAULT 'complete',
            completed_at            TEXT NOT NULL DEFAULT '',
            collisions_collapsed    INTEGER NOT NULL DEFAULT 0,
            divergence_warnings     INTEGER NOT NULL DEFAULT 0,
            payload_mismatch_warnings INTEGER NOT NULL DEFAULT 0,
            allow_payload_divergence  INTEGER NOT NULL DEFAULT 0,
            payload_divergences     TEXT
        )
    """)
    # Add columns idempotently for DBs created by an older version of this table
    for col, typedef in [
        ("payload_divergences", "TEXT"),
        ("status", "TEXT NOT NULL DEFAULT 'complete'"),
    ]:
        try:
            conn.execute(
                f"ALTER TABLE migration_v16_state ADD COLUMN {col} {typedef}"
            )
        except sqlite3.OperationalError:
            pass  # column already exists

    conn.execute("""
        CREATE TABLE IF NOT EXISTS migration_v16_lock (
            id       INTEGER PRIMARY KEY CHECK (id = 1),
            locked_at TEXT NOT NULL,
            pid      INTEGER NOT NULL,
            host     TEXT NOT NULL,
            mode     TEXT NOT NULL
        )
    """)


def _acquire_lock(
    conn: sqlite3.Connection,
    mode: str,
    *,
    commit: bool = True,
) -> None:
    """Acquire advisory lock. Raises RuntimeError if already held.

    Parameters
    ----------
    commit:
        If False, do not commit after acquiring — caller owns the transaction
        (used by dry-run / verify-only paths so the lock write is rolled back
        at the end, leaving the DB byte-identical).
    """
    _ensure_state_table(conn)
    try:
        conn.execute(
            "INSERT INTO migration_v16_lock (id, locked_at, pid, host, mode) "
            "VALUES (1, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                os.getpid(),
                socket.gethostname(),
                mode,
            ),
        )
        if commit:
            conn.commit()
    except sqlite3.IntegrityError:
        row = conn.execute(
            "SELECT locked_at, pid, host, mode FROM migration_v16_lock WHERE id = 1"
        ).fetchone()
        if row:
            raise RuntimeError(
                f"migration_v16_lock is held by pid={row[1]} host={row[2]} "
                f"mode={row[3]} since {row[0]}. "
                "If the previous run was interrupted, run: "
                "DELETE FROM migration_v16_lock WHERE id = 1;"
            ) from None
        raise


def _release_lock(conn: sqlite3.Connection, *, commit: bool = True) -> None:
    """Release advisory lock (best-effort).

    Parameters
    ----------
    commit:
        If False, skip the commit (caller owns the transaction — e.g. when
        releasing inside a ROLLBACK path).
    """
    try:
        conn.execute("DELETE FROM migration_v16_lock WHERE id = 1")
        if commit:
            conn.commit()
    except Exception:  # noqa: BLE001
        logger.warning("Failed to release migration_v16_lock", exc_info=True)


def _attempt_drop_column(conn: sqlite3.Connection, table: str, col: str) -> None:
    """Execute ALTER TABLE {table} DROP COLUMN {col}.

    This is a module-level function so tests can monkeypatch it to simulate
    DROP COLUMN failures and verify the rebuild fallback path is taken.
    """
    conn.execute(f"ALTER TABLE {table} DROP COLUMN {col}")


def _drop_column_or_rebuild(
    conn: sqlite3.Connection,
    strategy: str,
    cols_to_drop: list[str],
) -> None:
    """Drop columns from chunks_<strategy>, with fallback to full rebuild.

    Tries ALTER TABLE DROP COLUMN (SQLite ≥3.35) for each column via
    _attempt_drop_column (patchable for tests).
    On OperationalError falls back to CREATE+INSERT SELECT+DROP+RENAME.
    """
    table = f"chunks_{strategy}"

    # Try DROP COLUMN for each
    dropped: list[str] = []
    needs_rebuild = False
    for col in cols_to_drop:
        # Check column exists before attempting drop
        pragma = conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing = {r[1] for r in pragma}
        if col not in existing:
            continue
        try:
            _attempt_drop_column(conn, table, col)
            dropped.append(col)
        except sqlite3.OperationalError:
            logger.debug("DROP COLUMN %s failed; will use rebuild fallback", col)
            needs_rebuild = True
            break

    if not needs_rebuild:
        return

    # Rebuild fallback: determine target columns
    pragma = conn.execute(f"PRAGMA table_info({table})").fetchall()
    keep_cols = [
        r for r in pragma
        if r[1] not in cols_to_drop
    ]
    col_defs = []
    for r in keep_cols:
        cid, cname, ctype, notnull, dflt, pk = r
        parts = [f"{cname} {ctype}"]
        if pk:
            parts.append("PRIMARY KEY")
        if notnull and not pk:
            parts.append("NOT NULL")
        if dflt is not None:
            parts.append(f"DEFAULT {dflt}")
        col_defs.append(" ".join(parts))

    col_names = [r[1] for r in keep_cols]
    tmp_table = f"{table}_v16_rebuild"

    conn.execute(f"DROP TABLE IF EXISTS {tmp_table}")
    conn.execute(
        f"CREATE TABLE {tmp_table} ({', '.join(col_defs)})"
    )
    conn.execute(
        f"INSERT INTO {tmp_table} ({', '.join(col_names)}) "
        f"SELECT {', '.join(col_names)} FROM {table}"
    )
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {tmp_table} RENAME TO {table}")


def _write_divergence_report(report_path: Path, divergences: list[dict]) -> None:
    """Write a human-readable divergence report to report_path."""
    lines = []
    for d in divergences:
        lines.append(
            f"strategy={d['strategy']} new_id={d['new_chunk_id']} "
            f"old_ids={','.join(d['old_ids'])} "
            f"diverged_fields={','.join(d['diverged_fields'])} "
            f"canonical={d['chosen_canonical_old_id']}"
        )
        for oid, payload in d.get("payloads", {}).items():
            lines.append(
                f"  {oid}: heading_hierarchy={payload.get('heading_hierarchy')!r} "
                f"level={payload.get('level')!r}"
            )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Progress reporter
# ---------------------------------------------------------------------------

_PROGRESS_INTERVAL = 1000  # emit a log line every N rows


class ProgressReporter:
    """Lightweight progress tracker for per-strategy migration steps.

    Emits throttled structured log lines to the ``dotmd-migrate`` logger so
    journald can filter by SyslogIdentifier. Uses only stdlib (no tqdm — tqdm
    outputs escape codes to journald).

    Log format (single-line key=value for journald parsing)::

        dotmd-migrate mode=run strategy=heading_512_50 rows_done=1000 rows_total=12345 rows_per_sec=850.3 eta=9.8s collisions=12
    """

    def __init__(self, strategy: str, total_rows: int, mode: str) -> None:
        import time
        self.strategy = strategy
        self.total_rows = total_rows
        self.mode = mode
        self._start = time.monotonic()
        self._rows_done = 0
        self._last_emit = 0
        self._collisions = 0

    def tick(self, n: int = 1) -> None:
        """Advance rows_done counter; emit a log line every _PROGRESS_INTERVAL rows."""
        import time
        self._rows_done += n
        if self._rows_done - self._last_emit >= _PROGRESS_INTERVAL:
            self._emit(time.monotonic())
            self._last_emit = self._rows_done

    def set_collisions(self, count: int) -> None:
        self._collisions = count

    def _emit(self, now: float) -> None:
        elapsed = now - self._start
        rows_per_sec = self._rows_done / elapsed if elapsed > 0 else 0.0
        remaining = max(0, self.total_rows - self._rows_done)
        eta_seconds = remaining / rows_per_sec if rows_per_sec > 0 else 0.0
        logger.info(
            "mode=%s strategy=%s rows_done=%d rows_total=%d rows_per_sec=%.1f eta=%.1fs collisions=%d",
            self.mode, self.strategy, self._rows_done, self.total_rows,
            rows_per_sec, eta_seconds, self._collisions,
        )

    def finish(self) -> dict[str, Any]:
        """Emit final summary line and return a progress dict for MigrationReport."""
        import time
        now = time.monotonic()
        elapsed = now - self._start
        rows_per_sec = self._rows_done / elapsed if elapsed > 0 else 0.0
        remaining = max(0, self.total_rows - self._rows_done)
        eta_seconds = remaining / rows_per_sec if rows_per_sec > 0 else 0.0
        logger.info(
            "mode=%s strategy=%s DONE rows_done=%d rows_total=%d rows_per_sec=%.1f "
            "eta=%.1fs collisions=%d",
            self.mode, self.strategy, self._rows_done, self.total_rows,
            rows_per_sec, eta_seconds, self._collisions,
        )
        return {
            "rows_done": self._rows_done,
            "rows_total": self.total_rows,
            "rows_per_sec": rows_per_sec,
            "eta_seconds": eta_seconds,
            "collisions": self._collisions,
            "mode": self.mode,
        }


# ---------------------------------------------------------------------------
# Per-strategy migration
# ---------------------------------------------------------------------------

def _migrate_strategy(
    conn: sqlite3.Connection,
    strategy: str,
    *,
    dry_run: bool,
    verify_only: bool,
    run_dir: Path,
    reporter: "ProgressReporter | None" = None,
) -> tuple[int, int, int, list[dict], bool]:
    """Migrate a single strategy inside an open connection.

    Returns:
        (collisions_collapsed, divergence_warnings, payload_mismatch_warnings,
         all_divergences, aborted_by_divergence)

    On PayloadDivergenceBlocked (fail-closed), raises the exception after
    writing divergence_report.txt.
    """
    table = f"chunks_{strategy}"
    fts_table = f"chunks_fts_{strategy}"
    m2m_table = f"chunk_file_paths_{strategy}"
    idx_name = f"idx_chunk_file_paths_{strategy}_file_path"

    # --- Step 1: M2M table + index ---
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {m2m_table} (
            chunk_id    TEXT NOT NULL,
            file_path   TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            PRIMARY KEY (chunk_id, file_path, chunk_index)
        )
    """)
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS {idx_name} ON {m2m_table}(file_path)"
    )

    # --- Step 2: Backfill M2M from current chunks_* ---
    # Only if file_path column still exists (pre-v16 schema)
    pragma = conn.execute(f"PRAGMA table_info({table})").fetchall()
    col_names = {r[1] for r in pragma}
    has_file_path = "file_path" in col_names
    has_chunk_index = "chunk_index" in col_names

    if has_file_path and has_chunk_index:
        conn.execute(f"""
            INSERT OR IGNORE INTO {m2m_table} (chunk_id, file_path, chunk_index)
            SELECT chunk_id, file_path, chunk_index FROM {table}
        """)
    elif has_file_path:
        conn.execute(f"""
            INSERT OR IGNORE INTO {m2m_table} (chunk_id, file_path, chunk_index)
            SELECT chunk_id, file_path, 0 FROM {table}
        """)

    # --- Step 3: Add shadow column new_chunk_id ---
    try:
        conn.execute(
            f"ALTER TABLE {table} ADD COLUMN new_chunk_id TEXT"
        )
    except sqlite3.OperationalError:
        pass  # Column already exists from a previous interrupted run

    # --- Step 4: Compute new_chunk_id for every row ---
    # chunk_index must exist (it's in M2M now, but still on chunks_* pre-drop)
    #
    # CR-01 fix: body_checksum MUST come from chunk_fingerprints_<strategy>
    # (formula: blake3(kind + "\n" + body) over the FULL file body after
    # frontmatter strip).  Using only chunk text would produce a different
    # checksum than chunker.chunk_file, so migrated IDs would never match
    # fresh-index IDs, silently defeating content-deduplication post-migration.
    #
    # Lookup strategy:
    #   1. Query chunk_fingerprints_<strategy> for all distinct file_paths.
    #   2. For rows with no fingerprint entry, read the source file from disk.
    #   3. If the file is also missing from disk, abort with a clear error
    #      directing the user to run `dotmd index --force` first.
    if has_chunk_index:
        rows = conn.execute(
            f"SELECT chunk_id, file_path, chunk_index FROM {table}"
        ).fetchall()
    else:
        # chunk_index already dropped — guard against re-runs after partial migration
        rows = conn.execute(
            f"SELECT chunk_id, file_path, 0 FROM {table}"
        ).fetchall()

    # Collect all distinct file_paths present in this strategy's table and
    # batch-fetch their canonical checksums from chunk_fingerprints_<strategy>.
    all_file_paths: list[str] = list({r[1] for r in rows if r[1]})
    fp_checksums = _get_body_checksums_for_strategy(conn, strategy, all_file_paths)

    # For any file_path missing from chunk_fingerprints, try a disk read.
    # Log a single WARNING per missing file_path (not per chunk row).
    missing_fps = [fp for fp in all_file_paths if fp not in fp_checksums]
    if missing_fps:
        logger.warning(
            "chunk_fingerprints_%s has no entry for %d file(s); "
            "falling back to disk read for canonical body_checksum: %s",
            strategy, len(missing_fps), missing_fps[:5],
        )
    for fp in missing_fps:
        try:
            # kind is not stored in pre-v16 chunks_* — default to "document"
            # which matches the chunker default for files without a kind frontmatter.
            fp_checksums[fp] = _compute_body_checksum_from_file(fp, "document")
        except OSError as exc:
            raise RuntimeError(
                f"Cannot compute canonical body_checksum for {fp!r}: "
                f"not in chunk_fingerprints_{strategy} and file not found on disk ({exc}). "
                "Run `dotmd index --force` to rebuild fingerprints before re-running migration."
            ) from exc

    for old_id, file_path, chunk_index in rows:
        body_checksum = fp_checksums.get(file_path or "")
        if body_checksum is None:
            raise RuntimeError(
                f"No body_checksum available for file_path={file_path!r} "
                f"(chunk_id={old_id!r}, strategy={strategy!r}). "
                "Run `dotmd index --force` to rebuild fingerprints before re-running migration."
            )
        new_id = _compute_new_id_for_row(body_checksum, chunk_index, strategy)
        conn.execute(
            f"UPDATE {table} SET new_chunk_id = ? WHERE chunk_id = ?",
            (new_id, old_id),
        )
        if reporter is not None:
            reporter.tick()

    # --- Step 5: Detect collision groups ---
    collision_rows = conn.execute(f"""
        SELECT new_chunk_id,
               GROUP_CONCAT(chunk_id, '|') AS old_ids_concat,
               COUNT(*) AS n
        FROM {table}
        GROUP BY new_chunk_id
        HAVING n > 1
    """).fetchall()

    all_divergences: list[dict] = []
    collisions_collapsed = 0
    divergence_warnings = 0
    payload_mismatch_warnings = 0

    meta_tables = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?",
            (f"vec_meta_{strategy}_%",),
        ).fetchall()
    ]

    fts_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE name=?", (fts_table,)
    ).fetchone()

    for new_chunk_id, old_ids_concat, n in collision_rows:
        old_ids: list[str] = old_ids_concat.split("|")

        # --- Step 5a: payload_invariant_check ---
        member_rows = conn.execute(
            f"SELECT chunk_id, text, heading_hierarchy, level FROM {table} "
            f"WHERE chunk_id IN ({','.join('?' * len(old_ids))})",
            old_ids,
        ).fetchall()

        texts = {r[0]: r[1] for r in member_rows}
        hh_map = {r[0]: r[2] for r in member_rows}
        lv_map = {r[0]: r[3] for r in member_rows}

        # text MUST be identical (same new_chunk_id implies same body_checksum)
        unique_texts = set(texts.values())
        if len(unique_texts) > 1:
            raise RuntimeError(
                f"HARD ERROR: strategy={strategy} new_chunk_id={new_chunk_id} "
                f"has {len(old_ids)} members with DIFFERENT text values. "
                "This indicates a blake3 collision or chunker non-determinism. "
                f"old_ids={old_ids}"
            )

        # heading_hierarchy / level may differ → policy gate
        unique_hh = set(hh_map.values())
        unique_lv = set(lv_map.values())
        diverged_fields = []
        if len(unique_hh) > 1:
            diverged_fields.append("heading_hierarchy")
        if len(unique_lv) > 1:
            diverged_fields.append("level")

        if diverged_fields:
            canonical_for_report = min(old_ids)
            divergence_record = {
                "strategy": strategy,
                "new_chunk_id": new_chunk_id,
                "old_ids": old_ids,
                "diverged_fields": diverged_fields,
                "chosen_canonical_old_id": canonical_for_report,
                "payloads": {
                    oid: {
                        "heading_hierarchy": hh_map[oid],
                        "level": lv_map[oid],
                    }
                    for oid in old_ids
                },
            }
            all_divergences.append(divergence_record)

        # --- Step 5b: canonical_old_id = MIN(old_ids) ---
        canonical_old_id = min(old_ids)
        non_canonical = [oid for oid in old_ids if oid != canonical_old_id]

        # --- Step 5c: M2M redirect (cycle-2 NEW-HIGH-1 fix) ---
        # Redirect non-canonical M2M rows to canonical BEFORE deleting them.
        # This ensures every M2M row survives the collapse DELETE.
        for nc_id in non_canonical:
            conn.execute(
                f"UPDATE {m2m_table} SET chunk_id = ? WHERE chunk_id = ?",
                (canonical_old_id, nc_id),
            )
        # Note: (canonical_old_id, file_path, chunk_index) may already exist if
        # canonical also referenced the same file — INSERT OR IGNORE handled this
        # in step 2; after redirect we may have duplicates that need dedup.
        # Use a dedup step: keep one row per (canonical_old_id, file_path, chunk_index).
        conn.execute(f"""
            DELETE FROM {m2m_table}
            WHERE chunk_id = ?
            AND rowid NOT IN (
                SELECT MIN(rowid)
                FROM {m2m_table}
                WHERE chunk_id = ?
                GROUP BY chunk_id, file_path, chunk_index
            )
        """, (canonical_old_id, canonical_old_id))

        # --- Step 5d removed: vector divergence check was dead code ---
        # _fetch_vector_for_divergence_check always returned None because the
        # migration connection does not load the sqlite_vec extension.  The
        # guard `if v_canon is not None and v_other is not None` never fired.
        # Payload divergence (step 5f) covers the common case; vector
        # divergence is not checked during migration.  The canonical chunk's
        # vector is kept by default in step 5e's DELETE.

        # --- Step 5e: Collapse DELETE non-canonical rows ---
        nc_placeholders = ",".join("?" * len(non_canonical))
        conn.execute(
            f"DELETE FROM {table} WHERE chunk_id IN ({nc_placeholders})",
            non_canonical,
        )
        # FTS5: chunk_id is UNINDEXED, plain DELETE safe
        if fts_exists:
            conn.execute(
                f"DELETE FROM {fts_table} WHERE chunk_id IN ({nc_placeholders})",
                non_canonical,
            )
        for mt in meta_tables:
            conn.execute(
                f"DELETE FROM {mt} WHERE chunk_id IN ({nc_placeholders})",
                non_canonical,
            )

        collisions_collapsed += len(non_canonical)
        if reporter is not None:
            reporter.set_collisions(collisions_collapsed)

    # --- Step 5f: Fail-closed divergence gate (Decision #10) ---
    # No override flag exists — any divergence aborts the migration.
    if all_divergences:
        report_path = run_dir / "divergence_report.txt"
        _write_divergence_report(report_path, all_divergences)
        raise PayloadDivergenceBlocked(
            f"{len(all_divergences)} collision group(s) with diverging "
            f"heading_hierarchy/level in strategy={strategy}. "
            f"See divergence_report.txt for details."
        )

    # --- Step 6: Sanity — zero duplicates in new_chunk_id ---
    dup_count = conn.execute(f"""
        SELECT COUNT(*) FROM (
            SELECT new_chunk_id FROM {table}
            GROUP BY new_chunk_id
            HAVING COUNT(*) > 1
        )
    """).fetchone()[0]
    if dup_count > 0:
        raise RuntimeError(
            f"INTERNAL ERROR: strategy={strategy} still has {dup_count} "
            "duplicate new_chunk_ids after collision collapse. "
            "This is a bug in the migration."
        )

    # --- Step 7: Remap M2M / vec_meta / chunks_fts to new_chunk_ids ---
    conn.execute(f"""
        UPDATE {m2m_table}
        SET chunk_id = (
            SELECT new_chunk_id FROM {table} c
            WHERE c.chunk_id = {m2m_table}.chunk_id
        )
        WHERE chunk_id IN (SELECT chunk_id FROM {table})
    """)

    # vec_meta tables
    for mt in meta_tables:
        conn.execute(f"""
            UPDATE {mt}
            SET chunk_id = (
                SELECT new_chunk_id FROM {table} c
                WHERE c.chunk_id = {mt}.chunk_id
            )
            WHERE chunk_id IN (SELECT chunk_id FROM {table})
        """)

    # FTS5 (chunk_id UNINDEXED — plain UPDATE safe)
    if fts_exists:
        conn.execute(f"""
            UPDATE {fts_table}
            SET chunk_id = (
                SELECT new_chunk_id FROM {table} c
                WHERE c.chunk_id = {fts_table}.chunk_id
            )
            WHERE chunk_id IN (SELECT chunk_id FROM {table})
        """)

    # --- Step 8: UPDATE chunks_*.chunk_id = new_chunk_id ---
    # Safe now — no duplicates after collapse
    conn.execute(f"UPDATE {table} SET chunk_id = new_chunk_id")

    # --- Step 9: Drop shadow + legacy columns ---
    cols_to_drop = ["new_chunk_id", "file_path", "chunk_index", "char_offset"]
    _drop_column_or_rebuild(conn, strategy, cols_to_drop)

    return (
        collisions_collapsed,
        divergence_warnings,
        payload_mismatch_warnings,
        all_divergences,
        False,  # not aborted_by_divergence
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def needs_migration_v16(index_db: Path) -> bool:
    """Return True iff any chunks_* table still needs v16 migration.

    Criteria:
      - file_path column present in chunks_* (pre-v16 schema), OR
      - any chunk_id is not 64-hex (pre-v15 or intermediate format), OR
      - migration_v16_state row missing for a present strategy.
    """
    conn = sqlite3.connect(str(index_db))
    try:
        strategies = _discover_strategies(conn)
        if not strategies:
            return False
        for s in strategies:
            if _strategy_needs_migration(conn, s):
                return True
        return False
    finally:
        conn.close()


def run_migration_v16(
    index_db: Path,
    *,
    dry_run: bool = False,
    verify_only: bool = False,
) -> MigrationReport:
    """Orchestrate the v16 migration across all strategies.

    Parameters
    ----------
    index_db:
        Path to the SQLite index database.
    dry_run:
        Run all steps but ROLLBACK. Acquires lock with mode='dry-run'.
        Backup not created. Returns report with counts.
    verify_only:
        Run invariant checks only. Acquires lock with mode='verify-only'.
        No schema mutation.
    """
    _mode = "dry-run" if dry_run else ("verify-only" if verify_only else "run")
    report = MigrationReport(
        dry_run=dry_run,
        verify_only=verify_only,
        lock_mode=_mode,
        mode=_mode,
    )

    conn = sqlite3.connect(str(index_db))

    run_dir = index_db.parent
    # For dry-run and verify-only we wrap everything in a single transaction
    # that is ROLLBACKed at the end, leaving the DB byte-identical.
    is_no_persist = dry_run or verify_only

    # Only set WAL mode for real runs — PRAGMA journal_mode=WAL modifies the
    # DB file header, breaking the byte-equality check for dry-run tests.
    if not is_no_persist:
        conn.execute("PRAGMA journal_mode=WAL")

    # Guard: tracks whether _release_lock has already been called so the
    # finally block does not attempt a second release on a closed connection
    # (PayloadDivergenceBlocked handler releases + closes before re-raising).
    _lock_released = False

    try:
        if is_no_persist:
            # Begin a wrapping transaction that will ROLLBACK at the end.
            # The migration_v16_state + migration_v16_lock tables are
            # pre-created by the test fixture (or by a prior real run) so
            # CREATE TABLE IF NOT EXISTS inside this transaction is a no-op
            # DDL that rolls back cleanly, leaving the file byte-identical.
            conn.execute("BEGIN")

        # --- Pre-flight: ensure state/lock tables + acquire lock ---
        _ensure_state_table(conn)
        if not is_no_persist:
            conn.commit()

        mode = "dry-run" if dry_run else ("verify-only" if verify_only else "run")
        # For no-persist runs, do NOT commit after lock acquire — the lock row
        # will roll back with the wrapping transaction at the end.
        _acquire_lock(conn, mode, commit=not is_no_persist)

        # verify_only path
        if verify_only:
            inv = run_invariants(conn)
            # Compute divergence preview (read-only)
            strategies = _discover_strategies(conn)
            all_divergence_count = 0
            example_paths: list[str] = []
            for s in strategies:
                table = f"chunks_{s}"
                pragma = conn.execute(f"PRAGMA table_info({table})").fetchall()
                col_names = {r[1] for r in pragma}
                has_ci = "chunk_index" in col_names
                if not has_ci:
                    continue
                # Compute preview by scanning for potential collision groups.
                # Use canonical body_checksum from chunk_fingerprints_<strategy>
                # (same formula as chunker.chunk_file) so collision prediction
                # matches what the actual migration will compute.
                rows = conn.execute(
                    f"SELECT chunk_id, file_path, chunk_index FROM {table}"
                ).fetchall()
                all_fps: list[str] = list({r[1] for r in rows if r[1]})
                preview_checksums = _get_body_checksums_for_strategy(conn, s, all_fps)
                # For missing fingerprints in verify_only, skip the row — we
                # cannot read files here without side effects; the preview count
                # may be slightly under-reported but the migration itself will
                # error on missing fingerprints with a clear message.
                id_to_new: dict[str, str] = {}
                for cid, file_path, ci in rows:
                    bcs = preview_checksums.get(file_path or "")
                    if bcs is None:
                        continue  # fingerprint missing — skip from preview
                    new_id = _compute_new_id_for_row(bcs, ci, s)
                    id_to_new[cid] = new_id

                # Group by new_id
                groups: dict[str, list[str]] = defaultdict(list)
                for cid, new_id in id_to_new.items():
                    groups[new_id].append(cid)

                for new_id, old_ids in groups.items():
                    if len(old_ids) <= 1:
                        continue
                    # Check for heading divergence
                    member_rows = conn.execute(
                        f"SELECT chunk_id, heading_hierarchy, level FROM {table} "
                        f"WHERE chunk_id IN ({','.join('?' * len(old_ids))})",
                        old_ids,
                    ).fetchall()
                    hh_vals = {r[0]: r[1] for r in member_rows}
                    lv_vals = {r[0]: r[2] for r in member_rows}
                    if len(set(hh_vals.values())) > 1 or len(set(lv_vals.values())) > 1:
                        all_divergence_count += 1
                        # Gather example file paths from M2M or file_path col
                        m2m = f"chunk_file_paths_{s}"
                        m2m_exists = conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                            (m2m,),
                        ).fetchone()
                        if m2m_exists:
                            fp_rows = conn.execute(
                                f"SELECT DISTINCT file_path FROM {m2m} "
                                f"WHERE chunk_id IN ({','.join('?' * len(old_ids))}) "
                                "LIMIT 5",
                                old_ids,
                            ).fetchall()
                            example_paths.extend(r[0] for r in fp_rows)
                        elif "file_path" in col_names:
                            fp_rows = conn.execute(
                                f"SELECT DISTINCT file_path FROM {table} "
                                f"WHERE chunk_id IN ({','.join('?' * len(old_ids))}) "
                                "LIMIT 5",
                                old_ids,
                            ).fetchall()
                            example_paths.extend(r[0] for r in fp_rows)

            report.payload_divergence_preview = {
                "count": all_divergence_count,
                "example_paths": example_paths[:5],
            }
            # Persist the invariants result on the report so the CLI can
            # use it directly without re-opening the DB (IN-01 fix).
            report.invariant_report = inv
            report.completed = True
            # ROLLBACK the wrapping transaction — leaves DB byte-identical.
            conn.execute("ROLLBACK")
            return report

        # --- Backup (real run only) ---
        if not dry_run:
            backup_path = Path(str(index_db) + ".v16-backup")
            shutil.copy2(index_db, backup_path)
            logger.info("Backup created: %s", backup_path)

        strategies = _discover_strategies(conn)
        logger.info("Strategies found: %s", strategies)

        # --- Disk delta estimate setup (dry-run only) ---
        # Compute avg_row_size = db_size / total_rows for the delta estimate.
        _db_size_bytes: int = index_db.stat().st_size if index_db.exists() else 0
        _total_rows_all: int = sum(
            conn.execute(f"SELECT COUNT(*) FROM chunks_{s}").fetchone()[0]
            for s in strategies
        ) if strategies else 0

        total_collisions = 0
        total_divergence_warnings = 0
        total_payload_mismatch = 0

        for strategy in strategies:
            # Check if already completed (only relevant for real runs)
            if not dry_run:
                state_exists = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name='migration_v16_state'"
                ).fetchone()
                if state_exists:
                    state_row = conn.execute(
                        "SELECT status FROM migration_v16_state WHERE strategy = ?",
                        (strategy,),
                    ).fetchone()
                    if state_row and state_row[0] == "complete":
                        logger.info("Strategy %s already migrated — skipping", strategy)
                        report.skipped_strategies.append(strategy)
                        continue

            logger.info("Migrating strategy: %s", strategy)

            # --- Create progress reporter ---
            total_rows_for_strategy = conn.execute(
                f"SELECT COUNT(*) FROM chunks_{strategy}"
            ).fetchone()[0]
            reporter = ProgressReporter(strategy, total_rows_for_strategy, _mode)

            if not dry_run:
                # Real run: per-strategy transaction
                conn.execute("BEGIN")

            all_divergences: list[dict] = []
            try:
                (
                    collisions,
                    div_warns,
                    pm_warns,
                    all_divergences,
                    _aborted,
                ) = _migrate_strategy(
                    conn,
                    strategy,
                    dry_run=dry_run,
                    verify_only=False,
                    run_dir=run_dir,
                    reporter=reporter,
                )

                total_collisions += collisions
                total_divergence_warnings += div_warns
                total_payload_mismatch += pm_warns

                # Collect per-strategy progress
                prog = reporter.finish()
                prog["collisions_collapsed"] = collisions
                prog["divergence_warnings"] = div_warns
                prog["payload_mismatch_warnings"] = pm_warns
                report.per_strategy_progress[strategy] = prog

                if dry_run:
                    # All work is inside the outer wrapping BEGIN — do not
                    # commit per-strategy; the outer finally ROLLBACKs everything.
                    # Compute disk delta estimate: rows_collapsed * avg_row_size
                    if _total_rows_all > 0 and _db_size_bytes > 0:
                        avg_row_size = _db_size_bytes // _total_rows_all
                    else:
                        avg_row_size = 0
                    if report.disk_delta_estimate is None:
                        report.disk_delta_estimate = 0
                    report.disk_delta_estimate += collisions * avg_row_size

                    all_divs = prog.get("_all_divergences", [])
                    div_count = len([d for d in all_divs]) if all_divs else 0
                    logger.info(
                        "mode=dry-run strategy=%s collisions=%d "
                        "divergence_warnings=%d payload_mismatch_warnings=%d "
                        "payload_divergence_groups=%d "
                        "disk_delta_estimate=%d",
                        strategy, collisions, div_warns, pm_warns,
                        div_count,
                        report.disk_delta_estimate or 0,
                    )
                else:
                    # --- Step 10: State marker ---
                    conn.execute("""
                        INSERT OR REPLACE INTO migration_v16_state (
                            strategy, status, completed_at, collisions_collapsed,
                            divergence_warnings, payload_mismatch_warnings,
                            payload_divergences
                        ) VALUES (?, 'complete', ?, ?, ?, ?, ?)
                    """, (
                        strategy,
                        datetime.now(timezone.utc).isoformat(),
                        collisions,
                        div_warns,
                        pm_warns,
                        json.dumps(all_divergences) if all_divergences else None,
                    ))
                    conn.execute("COMMIT")
                    report.completed_strategies.append(strategy)
                    logger.info(
                        "Strategy %s committed: collisions=%d divergence_warnings=%d",
                        strategy, collisions, div_warns,
                    )

            except PayloadDivergenceBlocked as exc:
                # Real run: roll back per-strategy tx, persist state marker
                if not dry_run:
                    conn.execute("ROLLBACK")
                    conn.execute("BEGIN")
                    conn.execute("""
                        INSERT OR REPLACE INTO migration_v16_state (
                            strategy, status, completed_at, collisions_collapsed,
                            divergence_warnings, payload_mismatch_warnings,
                            payload_divergences
                        ) VALUES (?, 'payload_divergence_blocked', ?, 0, 0, 0, ?)
                    """, (
                        strategy,
                        datetime.now(timezone.utc).isoformat(),
                        json.dumps([
                            d for d in all_divergences
                            if d["strategy"] == strategy
                        ]) if all_divergences else None,
                    ))
                    conn.execute("COMMIT")
                    _release_lock(conn)
                    _lock_released = True
                    conn.close()
                raise exc from None

            except Exception:
                if not dry_run:
                    conn.execute("ROLLBACK")
                raise

        report.collisions_collapsed = total_collisions
        report.divergence_warnings = total_divergence_warnings
        report.payload_mismatch_warnings = total_payload_mismatch

        if not dry_run:
            report.completed = True

    finally:
        if is_no_persist:
            # Roll back the outer transaction — leaves DB byte-identical
            try:
                conn.execute("ROLLBACK")
            except Exception:  # noqa: BLE001
                pass
        elif not _lock_released:
            # Only release if not already released by the PayloadDivergenceBlocked
            # handler — avoids a spurious WARNING on an already-closed connection.
            _release_lock(conn)
        conn.close()

    return report


def run_invariants(conn: sqlite3.Connection) -> InvariantReport:
    """Run post-migration invariant checks. Single source of truth.

    Used by --verify-only CLI mode and P6 tests. Returns InvariantReport
    with a list of check dicts: {"name": str, "passed": bool, "detail": str}.

    Checks:
      - 64char_blake3: all chunk_ids in chunks_* are 64-char hex
      - no_orphan_vec_meta: no orphan rows in vec_meta_*
      - no_orphan_fts: no orphan rows in chunks_fts_*
      - unique_file_path_chunk_index: UNIQUE(file_path, chunk_index) in chunk_file_paths_*
      - row_count_delta: (informational) delta recorded
    """
    checks: list[dict[str, Any]] = []
    all_passed = True

    strategies = _discover_strategies(conn)

    # 1. 64char_blake3
    bad_ids_total = 0
    for s in strategies:
        table = f"chunks_{s}"
        count = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE length(chunk_id) != 64"
        ).fetchone()[0]
        bad_ids_total += count
    checks.append({
        "name": "64char_blake3",
        "passed": bad_ids_total == 0,
        "detail": f"{bad_ids_total} non-64-char chunk_ids found" if bad_ids_total else "",
    })
    if bad_ids_total > 0:
        all_passed = False

    # 2. no_orphan_vec_meta
    orphan_vec_total = 0
    for s in strategies:
        table = f"chunks_{s}"
        meta_tables = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?",
                (f"vec_meta_{s}_%",),
            ).fetchall()
        ]
        for mt in meta_tables:
            orphans = conn.execute(
                f"SELECT COUNT(*) FROM {mt} vm "
                f"WHERE NOT EXISTS (SELECT 1 FROM {table} c WHERE c.chunk_id = vm.chunk_id)"
            ).fetchone()[0]
            orphan_vec_total += orphans
    checks.append({
        "name": "no_orphan_vec_meta",
        "passed": orphan_vec_total == 0,
        "detail": f"{orphan_vec_total} orphan vec_meta rows" if orphan_vec_total else "",
    })
    if orphan_vec_total > 0:
        all_passed = False

    # 3. no_orphan_fts
    orphan_fts_total = 0
    for s in strategies:
        table = f"chunks_{s}"
        fts_table = f"chunks_fts_{s}"
        fts_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE name=?", (fts_table,)
        ).fetchone()
        if not fts_exists:
            continue
        orphans = conn.execute(
            f"SELECT COUNT(*) FROM {fts_table} f "
            f"WHERE NOT EXISTS (SELECT 1 FROM {table} c WHERE c.chunk_id = f.chunk_id)"
        ).fetchone()[0]
        orphan_fts_total += orphans
    checks.append({
        "name": "no_orphan_fts",
        "passed": orphan_fts_total == 0,
        "detail": f"{orphan_fts_total} orphan FTS rows" if orphan_fts_total else "",
    })
    if orphan_fts_total > 0:
        all_passed = False

    # 4. unique_file_path_chunk_index
    dup_m2m_total = 0
    for s in strategies:
        m2m = f"chunk_file_paths_{s}"
        m2m_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (m2m,)
        ).fetchone()
        if not m2m_exists:
            continue
        dups = conn.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT file_path, chunk_index
                FROM {m2m}
                GROUP BY file_path, chunk_index
                HAVING COUNT(*) > 1
            )
        """).fetchone()[0]
        dup_m2m_total += dups
    checks.append({
        "name": "unique_file_path_chunk_index",
        "passed": dup_m2m_total == 0,
        "detail": f"{dup_m2m_total} duplicate (file_path, chunk_index) in M2M" if dup_m2m_total else "",
    })
    if dup_m2m_total > 0:
        all_passed = False

    # 5. row_count_delta (informational)
    checks.append({
        "name": "row_count_delta",
        "passed": True,
        "detail": "row count delta check — see collisions_collapsed in MigrationReport",
    })

    return InvariantReport(passed=all_passed, checks=checks)


def status(index_db: Path) -> StatusReport:
    """Return migration status for all strategies."""
    report = StatusReport()
    conn = sqlite3.connect(str(index_db))
    try:
        state_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='migration_v16_state'"
        ).fetchone()
        if state_exists:
            rows = conn.execute(
                "SELECT strategy, status, completed_at, collisions_collapsed, "
                "divergence_warnings, payload_mismatch_warnings "
                "FROM migration_v16_state"
            ).fetchall()
            for row in rows:
                entry = {
                    "status": row[1],
                    "completed_at": row[2],
                    "collisions_collapsed": row[3],
                    "divergence_warnings": row[4],
                    "payload_mismatch_warnings": row[5],
                }
                report.strategies[row[0]] = entry
                report.per_strategy_state[row[0]] = entry

        # needs_migration: True if any strategy still needs migration
        strategies = _discover_strategies(conn)
        if strategies:
            report.needs_migration = any(
                _strategy_needs_migration(conn, s) for s in strategies
            )
        else:
            report.needs_migration = False

        lock_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='migration_v16_lock'"
        ).fetchone()
        if lock_exists:
            lock_row = conn.execute(
                "SELECT locked_at, pid, host, mode FROM migration_v16_lock WHERE id = 1"
            ).fetchone()
            if lock_row:
                report.lock_held = True
                report.lock_info = {
                    "locked_at": lock_row[0],
                    "pid": lock_row[1],
                    "host": lock_row[2],
                    "mode": lock_row[3],
                }
    finally:
        conn.close()
    return report


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    verify_only = "--verify-only" in args
    db_args = [a for a in args if not a.startswith("--")]

    if not db_args:
        print(
            "Usage: python -m dotmd.ingestion.migration_v16 <index.db> "
            "[--dry-run] [--verify-only]",
            file=sys.stderr,
        )
        sys.exit(2)

    db_path = Path(db_args[0])
    if not db_path.exists():
        print(f"ERROR: {db_path} not found", file=sys.stderr)
        sys.exit(1)

    try:
        result = run_migration_v16(
            db_path,
            dry_run=dry_run,
            verify_only=verify_only,
        )
        print(
            f"Migration complete: completed={result.completed} "
            f"collisions={result.collisions_collapsed} "
            f"divergence_warnings={result.divergence_warnings}"
        )
    except PayloadDivergenceBlocked as exc:
        print(f"ABORT (exit 4): {exc}", file=sys.stderr)
        sys.exit(4)
