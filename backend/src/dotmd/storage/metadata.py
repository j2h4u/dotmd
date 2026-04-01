"""SQLite-backed metadata store for chunk and index-statistics persistence.

Implements :class:`~dotmd.storage.base.MetadataStoreProtocol` using the
Python standard-library ``sqlite3`` module.  Heading hierarchies are
serialised as JSON strings.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from dotmd.core.models import Chunk, IndexStats

# ---------------------------------------------------------------------------
# SQL templates (table name injected at instance level)
# ---------------------------------------------------------------------------

_CREATE_CHUNKS_TPL = """
CREATE TABLE IF NOT EXISTS {table} (
    chunk_id        TEXT PRIMARY KEY,
    file_path       TEXT    NOT NULL,
    heading_hierarchy TEXT  NOT NULL DEFAULT '[]',
    level           INTEGER NOT NULL DEFAULT 0,
    text            TEXT    NOT NULL DEFAULT '',
    chunk_index     INTEGER NOT NULL DEFAULT 0,
    char_offset     INTEGER NOT NULL DEFAULT 0
)
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

_UPSERT_CHUNK_TPL = """
INSERT INTO {table} (chunk_id, file_path, heading_hierarchy, level, text, chunk_index, char_offset)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(chunk_id) DO UPDATE SET
    file_path         = excluded.file_path,
    heading_hierarchy = excluded.heading_hierarchy,
    level             = excluded.level,
    text              = excluded.text,
    chunk_index       = excluded.chunk_index,
    char_offset       = excluded.char_offset
"""

_CREATE_INDEX_FILE_PATH_TPL = (
    "CREATE INDEX IF NOT EXISTS idx_{table}_file_path ON {table}(file_path)"
)

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
            self._conn = conn
        else:
            if db_path is None:
                raise ValueError("Either db_path or conn must be provided")
            self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_CHUNKS_TPL.format(table=self._table))
        self._conn.execute(_CREATE_INDEX_FILE_PATH_TPL.format(table=self._table))
        self._conn.execute(_CREATE_STATS)
        # Idempotent schema migration: add diff-reporting columns
        for col, typedef in [
            ("new_files", "INTEGER NOT NULL DEFAULT 0"),
            ("modified_files", "INTEGER NOT NULL DEFAULT 0"),
            ("deleted_files", "INTEGER NOT NULL DEFAULT 0"),
            ("unchanged_files", "INTEGER NOT NULL DEFAULT 0"),
            ("data_dir", "TEXT"),
        ]:
            try:
                self._conn.execute(
                    f"ALTER TABLE stats ADD COLUMN {col} {typedef}"
                )
            except sqlite3.OperationalError:
                pass  # Column already exists
        self._conn.commit()

    # -- chunks -------------------------------------------------------------

    def save_chunks(self, chunks: list[Chunk]) -> None:
        """Persist a batch of chunks (insert or update)."""
        rows = [
            (
                c.chunk_id,
                str(c.file_path),
                json.dumps(c.heading_hierarchy),
                c.level,
                c.text,
                c.chunk_index,
                c.char_offset,
            )
            for c in chunks
        ]
        self._conn.executemany(_UPSERT_CHUNK_TPL.format(table=self._table), rows)
        self._conn.commit()

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        """Retrieve a single chunk by its identifier."""
        cur = self._conn.execute(
            f"SELECT chunk_id, file_path, heading_hierarchy, level, text, chunk_index, char_offset "
            f"FROM {self._table} WHERE chunk_id = ?",
            (chunk_id,),
        )
        row = cur.fetchone()
        return self._row_to_chunk(row) if row else None

    def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]:
        """Retrieve multiple chunks by their identifiers.

        Missing ids are silently skipped.
        """
        if not chunk_ids:
            return []
        placeholders = ",".join("?" for _ in chunk_ids)
        cur = self._conn.execute(
            f"SELECT chunk_id, file_path, heading_hierarchy, level, text, chunk_index, char_offset "
            f"FROM {self._table} WHERE chunk_id IN ({placeholders})",
            chunk_ids,
        )
        return [self._row_to_chunk(row) for row in cur.fetchall()]

    def get_all_chunks(self) -> list[Chunk]:
        """Return every chunk currently stored."""
        cur = self._conn.execute(
            f"SELECT chunk_id, file_path, heading_hierarchy, level, text, chunk_index, char_offset "
            f"FROM {self._table}"
        )
        return [self._row_to_chunk(row) for row in cur.fetchall()]

    def get_chunk_ids_by_file(self, file_path: str) -> list[str]:
        """Return all chunk_ids for a given file path."""
        cur = self._conn.execute(
            f"SELECT chunk_id FROM {self._table} WHERE file_path = ?",
            (file_path,),
        )
        return [row[0] for row in cur.fetchall()]

    def delete_chunks_by_file(self, file_path: str) -> int:
        """Delete all chunks belonging to a file. Returns count deleted."""
        cur = self._conn.execute(
            f"DELETE FROM {self._table} WHERE file_path = ?",
            (file_path,),
        )
        self._conn.commit()
        return cur.rowcount

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
        try:
            self._conn.execute(f"DELETE FROM {self._fts_table}")
        except sqlite3.OperationalError:
            pass  # FTS5 table not yet created
        self._conn.commit()

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _row_to_chunk(row: tuple) -> Chunk:  # type: ignore[type-arg]
        """Convert a raw SQLite row tuple into a :class:`Chunk`."""
        return Chunk(
            chunk_id=row[0],
            file_path=Path(row[1]),
            heading_hierarchy=json.loads(row[2]),
            level=row[3],
            text=row[4],
            chunk_index=row[5],
            char_offset=row[6],
        )
