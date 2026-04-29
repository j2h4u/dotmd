"""SQLite-backed metadata store for chunk and index-statistics persistence.

Implements :class:`~dotmd.storage.base.MetadataStoreProtocol` using the
Python standard-library ``sqlite3`` module.  Heading hierarchies are
serialised as JSON strings.

Phase 16 changes (Decision #1, #3, #7, #8):
  - chunks_* tables no longer carry file_path, chunk_index, or char_offset.
  - New M2M table chunk_file_paths_<strategy>(chunk_id, file_path, chunk_index)
    with PK (chunk_id, file_path, chunk_index) and index on file_path.
  - insert_chunk uses INSERT OR IGNORE (never UPDATE on conflict — D-07).
  - New helpers: ensure_m2m_table, add_file_path, get_file_paths_by_chunk_id,
    get_file_paths_for_chunk_ids, get_stored_payload, delete_m2m_for_file,
    delete_orphan_chunks.
  - delete_m2m_for_file / delete_orphan_chunks accept a caller-supplied
    sqlite3.Connection and do NOT call commit() — caller owns the transaction.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from dotmd.core.models import Chunk, IndexStats

# ---------------------------------------------------------------------------
# _ConnProxy — thin wrapper around sqlite3.Connection
# ---------------------------------------------------------------------------

class _ConnProxy:
    """Thin Python-level wrapper around ``sqlite3.Connection``.

    Delegates all attribute access to the underlying connection, but because
    it is a Python object (not a C extension type), attributes like ``execute``
    can be re-assigned at runtime.  This is required by test_metadata_m2m.py's
    spy pattern (``store._conn.execute = counting_execute``).
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        # Store the real connection under a mangled name to avoid infinite
        # recursion when __getattr__ is called.
        object.__setattr__(self, "_real_conn", conn)

    # Expose execute/executemany/executescript as real attributes so they
    # can be replaced (test spy) without going through __getattr__.
    @property
    def execute(self):  # type: ignore[no-untyped-def]
        return object.__getattribute__(self, "_execute_override") if "_execute_override" in object.__getattribute__(self, "__dict__") else object.__getattribute__(self, "_real_conn").execute

    @execute.setter
    def execute(self, value):  # type: ignore[no-untyped-def]
        object.__getattribute__(self, "__dict__")["_execute_override"] = value

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        return getattr(object.__getattribute__(self, "_real_conn"), name)

    def __setattr__(self, name: str, value) -> None:  # type: ignore[no-untyped-def]
        if name == "_real_conn":
            object.__setattr__(self, name, value)
        else:
            object.__getattribute__(self, "__dict__")[name] = value

# ---------------------------------------------------------------------------
# SQL templates (table name injected at instance level)
# ---------------------------------------------------------------------------

# Phase 16: chunks_* has NO file_path, chunk_index, or char_offset columns.
_CREATE_CHUNKS_TPL = """
CREATE TABLE IF NOT EXISTS {table} (
    chunk_id          TEXT PRIMARY KEY,
    heading_hierarchy TEXT NOT NULL DEFAULT '[]',
    level             INTEGER NOT NULL DEFAULT 0,
    text              TEXT NOT NULL DEFAULT ''
)
"""

_CREATE_M2M_TPL = """
CREATE TABLE IF NOT EXISTS {m2m_table} (
    chunk_id    TEXT NOT NULL,
    file_path   TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    PRIMARY KEY (chunk_id, file_path, chunk_index)
)
"""

_CREATE_M2M_IDX_TPL = """
CREATE INDEX IF NOT EXISTS {idx_name}
    ON {m2m_table}(file_path)
"""

_CREATE_STATS = """
CREATE TABLE IF NOT EXISTS stats (
    id              INTEGER PRIMARY KEY DEFAULT 1,
    total_files     INTEGER NOT NULL DEFAULT 0,
    total_chunks    INTEGER NOT NULL DEFAULT 0,
    total_entities  INTEGER NOT NULL DEFAULT 0,
    total_edges     INTEGER NOT NULL DEFAULT 0,
    last_indexed    TEXT
)
"""

# INSERT OR IGNORE — content is immutable once written (D-07 / Pitfall 1).
_INSERT_CHUNK_TPL = """
INSERT OR IGNORE INTO {table} (chunk_id, heading_hierarchy, level, text)
VALUES (?, ?, ?, ?)
"""

# M2M association: INSERT OR IGNORE so duplicate (chunk_id, file_path, chunk_index) is a no-op.
_INSERT_M2M_TPL = """
INSERT OR IGNORE INTO {m2m_table} (chunk_id, file_path, chunk_index)
VALUES (?, ?, ?)
"""

_UPSERT_STATS = """
INSERT INTO stats (id, total_files, total_chunks, total_entities, total_edges, last_indexed,
                   new_files, modified_files, deleted_files, unchanged_files, data_dir)
VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(id) DO UPDATE SET
    total_files     = excluded.total_files,
    total_chunks    = excluded.total_chunks,
    total_entities  = excluded.total_entities,
    total_edges     = excluded.total_edges,
    last_indexed    = excluded.last_indexed,
    new_files       = excluded.new_files,
    modified_files  = excluded.modified_files,
    deleted_files   = excluded.deleted_files,
    unchanged_files = excluded.unchanged_files,
    data_dir        = excluded.data_dir
"""


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------


class SQLiteMetadataStore:
    """SQLite implementation of :class:`MetadataStoreProtocol`.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.  Ignored when *conn* is provided.
        Use ``:memory:`` for an in-memory store.
    table_name:
        Name of the chunks table.  Defaults to ``"chunks"`` for backward
        compatibility.  Use a strategy-specific name (e.g.
        ``"chunks_heading_512_50"``) for multi-strategy isolation.
    fts_table_name:
        Name of the FTS5 virtual table managed by
        :class:`~dotmd.search.fts5.FTS5SearchEngine`.  Only used by
        :meth:`delete_all` to clear the FTS5 index alongside chunks.
        Defaults to ``"chunks_fts"``.
    conn:
        Pre-existing SQLite connection (shared database mode).  When given,
        the store reuses this connection instead of opening its own file.
        The caller is responsible for WAL mode and any extensions.
    """

    def __init__(
        self,
        db_path: Path | None = None,
        table_name: str = "chunks",
        fts_table_name: str = "chunks_fts",
        *,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        self._db_path = db_path
        self._table = table_name
        self._fts_table = fts_table_name
        if conn is not None:
            self._conn = _ConnProxy(conn) if not isinstance(conn, _ConnProxy) else conn
        else:
            if db_path is None:
                raise ValueError("Either db_path or conn must be provided")
            raw_conn = sqlite3.connect(str(db_path), check_same_thread=False)
            self._conn = _ConnProxy(raw_conn)
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_CHUNKS_TPL.format(table=self._table))
        self._conn.execute(_CREATE_STATS)
        # Idempotent schema migration: add diff-reporting columns
        for col, typedef in [
            ("new_files", "INTEGER NOT NULL DEFAULT 0"),
            ("modified_files", "INTEGER NOT NULL DEFAULT 0"),
            ("deleted_files", "INTEGER NOT NULL DEFAULT 0"),
            ("unchanged_files", "INTEGER NOT NULL DEFAULT 0"),
            ("data_dir", "TEXT"),
        ]:
            with contextlib.suppress(sqlite3.OperationalError):  # column already exists
                self._conn.execute(
                    f"ALTER TABLE stats ADD COLUMN {col} {typedef}"
                )
        self._conn.commit()

    # -- M2M table management -----------------------------------------------

    def ensure_m2m_table(self, strategy: str) -> None:
        """Create chunk_file_paths_<strategy> and its file_path index if absent.

        Safe to call repeatedly — all DDL uses IF NOT EXISTS.
        """
        m2m_table = f"chunk_file_paths_{strategy}"
        idx_name = f"idx_chunk_file_paths_{strategy}_file_path"
        self._conn.execute(_CREATE_M2M_TPL.format(m2m_table=m2m_table))
        self._conn.execute(
            _CREATE_M2M_IDX_TPL.format(idx_name=idx_name, m2m_table=m2m_table)
        )
        self._conn.commit()

    # -- chunks (Phase 16 M2M surface) --------------------------------------

    def insert_chunk(
        self,
        strategy: str,
        chunk_id: str,
        heading_hierarchy: list[str],
        level: int,
        text: str,
        *,
        _commit: bool = True,
    ) -> None:
        """Insert a chunk row using INSERT OR IGNORE (D-07).

        On conflict the existing row is left untouched — same chunk_id always
        implies identical content in a content-addressed schema.

        Parameters
        ----------
        strategy:
            Strategy name (used to derive the table name).
        chunk_id, heading_hierarchy, level, text:
            Chunk payload fields.
        _commit:
            If False, skip the auto-commit so the caller can batch multiple
            inserts inside its own BEGIN/COMMIT transaction (e.g. the
            index_file write loop in pipeline.py).  Defaults to True for
            backward compatibility with single-call sites.
        """
        table = f"chunks_{strategy}"
        self._conn.execute(
            _INSERT_CHUNK_TPL.format(table=table),
            (chunk_id, json.dumps(heading_hierarchy), level, text),
        )
        if _commit:
            self._conn.commit()

    def add_file_path(
        self,
        strategy: str,
        chunk_id: str,
        file_path: str,
        chunk_index: int,
        *,
        _commit: bool = True,
    ) -> None:
        """Record (chunk_id, file_path, chunk_index) in the M2M table.

        Uses INSERT OR IGNORE — duplicate (chunk_id, file_path, chunk_index)
        tuples are silently skipped (idempotent).

        Callers must have previously called :meth:`ensure_m2m_table`.

        Parameters
        ----------
        _commit:
            If False, skip the auto-commit so the caller can batch multiple
            inserts inside its own BEGIN/COMMIT transaction.
        """
        m2m_table = f"chunk_file_paths_{strategy}"
        self._conn.execute(
            _INSERT_M2M_TPL.format(m2m_table=m2m_table),
            (chunk_id, file_path, chunk_index),
        )
        if _commit:
            self._conn.commit()

    def get_file_paths_by_chunk_id(
        self, strategy: str, chunk_id: str
    ) -> list[str]:
        """Return all file_paths for a chunk_id, sorted lexicographically (D-01).

        Parameters
        ----------
        strategy:
            Strategy name.
        chunk_id:
            Chunk identifier to look up.

        Returns
        -------
        list[str]
            Distinct file paths in lexicographic order.
        """
        m2m_table = f"chunk_file_paths_{strategy}"
        rows = self._conn.execute(
            f"SELECT DISTINCT file_path FROM {m2m_table} "
            f"WHERE chunk_id = ? ORDER BY file_path",
            (chunk_id,),
        ).fetchall()
        return [r[0] for r in rows]

    def get_file_paths_for_chunk_ids(
        self, strategy: str, chunk_ids: Sequence[str]
    ) -> dict[str, list[str]]:
        """Batch-hydrate file_paths for multiple chunk_ids (Review-LOW-12).

        Uses a single SELECT with IN clause to avoid O(K) round-trips.

        Parameters
        ----------
        strategy:
            Strategy name.
        chunk_ids:
            Sequence of chunk identifiers to look up.

        Returns
        -------
        dict[str, list[str]]
            Mapping of chunk_id → sorted list of file_paths.
            chunk_ids with no M2M entries are absent from the result.
        """
        if not chunk_ids:
            return {}
        m2m_table = f"chunk_file_paths_{strategy}"
        placeholders = ",".join("?" for _ in chunk_ids)
        rows = self._conn.execute(
            f"SELECT chunk_id, file_path FROM {m2m_table} "
            f"WHERE chunk_id IN ({placeholders}) "
            f"ORDER BY chunk_id, file_path",
            list(chunk_ids),
        ).fetchall()
        result: dict[str, list[str]] = defaultdict(list)
        for cid, fp in rows:
            result[cid].append(fp)
        return dict(result)

    def get_stored_payload(
        self, strategy: str, chunk_id: str
    ) -> dict | None:
        """Return the stored payload for a chunk_id or None if absent.

        Used by P3 ingest to check payload consistency on conflict.

        Returns
        -------
        dict | None
            ``{"text": ..., "heading_hierarchy": ..., "level": ...}`` or
            ``None`` if the chunk_id is not found.
        """
        table = f"chunks_{strategy}"
        row = self._conn.execute(
            f"SELECT text, heading_hierarchy, level FROM {table} WHERE chunk_id = ?",
            (chunk_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "text": row[0],
            "heading_hierarchy": json.loads(row[1]),
            "level": row[2],
        }

    def get_chunk_ids_by_file(self, strategy: str, file_path: str) -> list[str]:  # type: ignore[override]
        """Return all chunk_ids associated with a file path via the M2M table.

        Phase 16: queries chunk_file_paths_* (not chunks_* directly).

        Parameters
        ----------
        strategy:
            Strategy name (required after Phase 16 M2M refactor).
        file_path:
            File path to look up.
        """
        m2m_table = f"chunk_file_paths_{strategy}"
        rows = self._conn.execute(
            f"SELECT DISTINCT chunk_id FROM {m2m_table} WHERE file_path = ?",
            (file_path,),
        ).fetchall()
        return [r[0] for r in rows]

    def delete_m2m_for_file(
        self,
        strategy: str,
        file_path: str,
        *,
        conn: sqlite3.Connection,
    ) -> list[str]:
        """Remove all M2M rows for file_path and return orphaned chunk_ids.

        A chunk_id is considered orphaned when it has zero remaining M2M rows
        after the deletion (i.e., it has no other file holders).

        **Callers must wrap this in BEGIN/COMMIT.** This method does NOT call
        commit() — the pipeline (P4) owns the transaction boundary to ensure
        the full per-file cascade is atomic (addresses Review-MED-P4-8
        atomicity requirement).

        Parameters
        ----------
        strategy:
            Strategy name.
        file_path:
            File path whose associations should be removed.
        conn:
            Open SQLite connection to use.  Must be supplied by the caller.

        Returns
        -------
        list[str]
            chunk_ids whose holder count dropped to 0 (orphans ready for
            cascade delete from chunks_*, vec_meta_*, vec0_*, chunks_fts_*).
        """
        m2m_table = f"chunk_file_paths_{strategy}"

        # Collect candidate chunk_ids before deletion.
        affected = [
            r[0]
            for r in conn.execute(
                f"SELECT DISTINCT chunk_id FROM {m2m_table} WHERE file_path = ?",
                (file_path,),
            ).fetchall()
        ]

        if not affected:
            return []

        # Delete the M2M rows for this file.
        conn.execute(
            f"DELETE FROM {m2m_table} WHERE file_path = ?",
            (file_path,),
        )

        # Find which chunk_ids now have zero holders.
        placeholders = ",".join("?" for _ in affected)
        still_held = {
            r[0]
            for r in conn.execute(
                f"SELECT DISTINCT chunk_id FROM {m2m_table} "
                f"WHERE chunk_id IN ({placeholders})",
                affected,
            ).fetchall()
        }

        return [cid for cid in affected if cid not in still_held]

    def delete_orphan_chunks(
        self,
        strategy: str,
        chunk_ids: Sequence[str],
        *,
        conn: sqlite3.Connection,
    ) -> None:
        """Delete rows from chunks_<strategy> for orphaned chunk_ids.

        Only deletes from the chunks_* content table. Callers are responsible
        for also deleting from vec_meta_*, vec0_*, and chunks_fts_*.

        **Callers must wrap this in BEGIN/COMMIT.** This method does NOT call
        commit() — the pipeline (P4) owns the transaction boundary.

        Parameters
        ----------
        strategy:
            Strategy name.
        chunk_ids:
            Chunk identifiers to delete.
        conn:
            Open SQLite connection to use.  Must be supplied by the caller.
        """
        if not chunk_ids:
            return
        table = f"chunks_{strategy}"
        placeholders = ",".join("?" for _ in chunk_ids)
        conn.execute(
            f"DELETE FROM {table} WHERE chunk_id IN ({placeholders})",
            list(chunk_ids),
        )

    # -- legacy save_chunks (kept for non-Phase-16 code paths) ---------------

    def save_chunks(self, chunks: list[Chunk]) -> None:
        """Persist a batch of chunks using INSERT OR IGNORE on chunks_*.

        Phase 16: uses INSERT OR IGNORE semantics (D-07). File path
        associations must be added separately via add_file_path().
        """
        # Derive strategy from table name (strips "chunks_" prefix).
        strategy = self._table.removeprefix("chunks_")
        for c in chunks:
            self.insert_chunk(
                strategy,
                chunk_id=c.chunk_id,
                heading_hierarchy=c.heading_hierarchy,
                level=c.level,
                text=c.text,
            )
            # Persist file_path associations to M2M.
            self.ensure_m2m_table(strategy)
            for fp in c.file_paths:
                self.add_file_path(strategy, c.chunk_id, str(fp), c.chunk_index)

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        """Retrieve a single chunk by its identifier."""
        strategy = self._table.removeprefix("chunks_")
        cur = self._conn.execute(
            f"SELECT chunk_id, heading_hierarchy, level, text "
            f"FROM {self._table} WHERE chunk_id = ?",
            (chunk_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_chunk(row, strategy)

    def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]:
        """Retrieve multiple chunks by their identifiers.

        Missing ids are silently skipped.
        """
        strategy = self._table.removeprefix("chunks_")
        if not chunk_ids:
            return []
        placeholders = ",".join("?" for _ in chunk_ids)
        cur = self._conn.execute(
            f"SELECT chunk_id, heading_hierarchy, level, text "
            f"FROM {self._table} WHERE chunk_id IN ({placeholders})",
            chunk_ids,
        )
        return [self._row_to_chunk(row, strategy) for row in cur.fetchall()]

    def get_all_chunks(self) -> list[Chunk]:
        """Return every chunk currently stored."""
        strategy = self._table.removeprefix("chunks_")
        cur = self._conn.execute(
            f"SELECT chunk_id, heading_hierarchy, level, text FROM {self._table}"
        )
        return [self._row_to_chunk(row, strategy) for row in cur.fetchall()]

    def delete_chunks_by_file(self, file_path: str) -> int:
        """Delete all chunks belonging to a file. Returns count deleted.

        Phase 16: delegates to M2M-aware helpers inside a single BEGIN/COMMIT
        so the M2M delete and orphan cascade are atomic.  A crash between the
        two operations in the old code could leave M2M rows gone but chunk
        content rows present (inverse orphan).
        """
        strategy = self._table.removeprefix("chunks_")
        raw = object.__getattribute__(self._conn, "_real_conn")
        raw.execute("BEGIN")
        try:
            orphans = self.delete_m2m_for_file(strategy, file_path, conn=self._conn)
            self.delete_orphan_chunks(strategy, orphans, conn=self._conn)
            raw.execute("COMMIT")
        except Exception:
            raw.execute("ROLLBACK")
            raise
        return len(orphans)

    # -- stats --------------------------------------------------------------

    def save_stats(self, stats: IndexStats) -> None:
        """Persist index statistics (overwrites previous stats)."""
        last_indexed = (
            stats.last_indexed.isoformat() if stats.last_indexed else None
        )
        self._conn.execute(
            _UPSERT_STATS,
            (
                stats.total_files,
                stats.total_chunks,
                stats.total_entities,
                stats.total_edges,
                last_indexed,
                stats.new_files,
                stats.modified_files,
                stats.deleted_files,
                stats.unchanged_files,
                stats.data_dir,
            ),
        )
        self._conn.commit()

    def get_stats(self) -> IndexStats | None:
        """Retrieve the most recent index statistics."""
        try:
            cur = self._conn.execute(
                "SELECT total_files, total_chunks, total_entities, total_edges, last_indexed, "
                "new_files, modified_files, deleted_files, unchanged_files, data_dir "
                "FROM stats WHERE id = 1"
            )
        except sqlite3.OperationalError:
            # Old schema without diff columns -- fall back to base query
            cur = self._conn.execute(
                "SELECT total_files, total_chunks, total_entities, total_edges, last_indexed "
                "FROM stats WHERE id = 1"
            )
            row = cur.fetchone()
            if row is None:
                return None
            last_indexed = (
                datetime.fromisoformat(row[4]) if row[4] else None
            )
            return IndexStats(
                total_files=row[0],
                total_chunks=row[1],
                total_entities=row[2],
                total_edges=row[3],
                last_indexed=last_indexed,
            )
        row = cur.fetchone()
        if row is None:
            return None
        last_indexed = (
            datetime.fromisoformat(row[4]) if row[4] else None
        )
        return IndexStats(
            total_files=row[0],
            total_chunks=row[1],
            total_entities=row[2],
            total_edges=row[3],
            last_indexed=last_indexed,
            new_files=row[5],
            modified_files=row[6],
            deleted_files=row[7],
            unchanged_files=row[8],
            data_dir=row[9],
        )

    # -- housekeeping -------------------------------------------------------

    def delete_all(self) -> None:
        """Remove all chunks and statistics from the store."""
        self._conn.execute(f"DELETE FROM {self._table}")
        self._conn.execute("DELETE FROM stats")
        # Clear FTS5 index if it exists
        with contextlib.suppress(sqlite3.OperationalError):  # FTS5 table not yet created
            self._conn.execute(f"DELETE FROM {self._fts_table}")
        self._conn.commit()

    # -- helpers ------------------------------------------------------------

    def _row_to_chunk(self, row: tuple, strategy: str) -> Chunk:  # type: ignore[type-arg]
        """Convert a raw SQLite row tuple (chunk_id, heading_hierarchy, level, text) into a Chunk.

        file_paths are not hydrated here — callers that need them should call
        get_file_paths_by_chunk_id separately.
        """
        return Chunk(
            chunk_id=row[0],
            heading_hierarchy=json.loads(row[1]),
            level=row[2],
            text=row[3],
            chunk_index=0,  # M2M-stored; not available in this row
            file_paths=[],  # hydrated separately via get_file_paths_by_chunk_id
        )
