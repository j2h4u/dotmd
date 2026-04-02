"""File change detection via fingerprints stored in SQLite.

Provides :class:`FileTracker` which persists ``(path, mtime, size, checksum)``
tuples in a ``file_fingerprints`` table and classifies files as
new / modified / deleted / unchanged on each :meth:`diff` call.

The two-stage detection strategy avoids unnecessary I/O:

1. If ``mtime`` **and** ``size`` match the stored fingerprint the file is
   classified as **unchanged** without reading any bytes.
2. Only when ``mtime`` or ``size`` differ is the MD5 checksum computed.
   If the checksum still matches (e.g. a ``touch`` without content change)
   the file is classified as **unchanged** and the stored mtime/size are
   silently updated.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

from dotmd.core.models import FileInfo
from dotmd.ingestion.reader import content_checksum

# ---------------------------------------------------------------------------
# SQL constants
# ---------------------------------------------------------------------------

_CREATE_FINGERPRINTS = """
CREATE TABLE IF NOT EXISTS {table} (
    file_path   TEXT PRIMARY KEY,
    mtime       REAL    NOT NULL,
    size_bytes  INTEGER NOT NULL,
    checksum    TEXT    NOT NULL,
    indexed_at  TEXT    NOT NULL
)
"""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class FileDiff:
    """Result of comparing discovered files against stored fingerprints."""

    new: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# FileTracker
# ---------------------------------------------------------------------------


class FileTracker:
    """Track file changes via fingerprints persisted in SQLite.

    Parameters
    ----------
    conn:
        An open :class:`sqlite3.Connection`.  The tracker creates its
        own table but shares the connection (and therefore the database
        file) with other components such as
        :class:`~dotmd.storage.metadata.SQLiteMetadataStore`.
    table_name:
        Name of the fingerprints table.  Use a model-specific suffix
        (e.g. ``"file_fingerprints_e5_large"``) so each embedding model
        maintains independent change-detection state.
    """

    def __init__(self, conn: sqlite3.Connection, table_name: str = "file_fingerprints") -> None:
        self._conn = conn
        self._table = table_name
        self._conn.execute(_CREATE_FINGERPRINTS.format(table=self._table))
        self._conn.commit()

    # -- diff ---------------------------------------------------------------

    def diff(self, discovered: list[FileInfo]) -> FileDiff:
        """Classify *discovered* files relative to stored fingerprints.

        Returns a :class:`FileDiff` with four lists of file-path strings.

        **Important:** This method never accesses :pyattr:`FileInfo.checksum`
        (a computed field that reads the full file on every access).  MD5
        is computed explicitly via :func:`hashlib.md5` only when the fast
        mtime+size check is inconclusive.
        """
        # Load all stored fingerprints: {path: (mtime, size, checksum)}
        cur = self._conn.execute(
            f"SELECT file_path, mtime, size_bytes, checksum FROM {self._table}"
        )
        stored: dict[str, tuple[float, int, str]] = {
            row[0]: (row[1], row[2], row[3]) for row in cur.fetchall()
        }

        result = FileDiff()
        seen_paths: set[str] = set()

        for fi in discovered:
            path_str = str(fi.path)
            seen_paths.add(path_str)

            if path_str not in stored:
                result.new.append(path_str)
                continue

            s_mtime, s_size, s_checksum = stored[path_str]

            # Fast path: mtime + size unchanged -> skip checksum
            stat = fi.path.stat()
            if stat.st_mtime == s_mtime and stat.st_size == s_size:
                result.unchanged.append(path_str)
                continue

            # Slow path: mtime or size differ -> compute checksum
            # Hash body+kind only (frontmatter changes don't trigger reindex)
            current_checksum = content_checksum(fi.path)

            if current_checksum == s_checksum:
                # Content unchanged, just metadata drift (e.g. touch)
                # Update stored mtime/size silently
                self._conn.execute(
                    f"UPDATE {self._table} SET mtime = ?, size_bytes = ? "
                    "WHERE file_path = ?",
                    (stat.st_mtime, stat.st_size, path_str),
                )
                self._conn.commit()
                result.unchanged.append(path_str)
            else:
                result.modified.append(path_str)

        # Deleted = stored paths not in discovered set
        for stored_path in stored:
            if stored_path not in seen_paths:
                result.deleted.append(stored_path)

        return result

    # -- CRUD ---------------------------------------------------------------

    def save_fingerprint(
        self,
        file_path: str,
        mtime: float,
        size: int,
        checksum: str,
    ) -> None:
        """Insert or replace a file fingerprint."""
        self._conn.execute(
            f"INSERT OR REPLACE INTO {self._table} "
            "(file_path, mtime, size_bytes, checksum, indexed_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                file_path,
                mtime,
                size,
                checksum,
                datetime.now(tz=timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()

    def remove_fingerprint(self, file_path: str) -> None:
        """Delete the fingerprint for a single file."""
        self._conn.execute(
            f"DELETE FROM {self._table} WHERE file_path = ?",
            (file_path,),
        )
        self._conn.commit()

    def clear(self) -> None:
        """Remove all stored fingerprints."""
        self._conn.execute(f"DELETE FROM {self._table}")
        self._conn.commit()
