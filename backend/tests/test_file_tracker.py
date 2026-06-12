"""Tests for FileTracker — file change detection via fingerprints."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from dotmd.core.models import FileInfo
from dotmd.ingestion.file_tracker import FileTracker


def _make_file(tmp_path: Path, name: str, content: str) -> FileInfo:
    """Create a real file on disk and return its FileInfo."""
    p = tmp_path / name
    p.write_text(content)
    stat = p.stat()
    return FileInfo(
        path=p,
        title=name,
        last_modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        size_bytes=stat.st_size,
    )


class TestFileTrackerDiff:
    """Tests for FileTracker.diff() classification logic."""

    def test_new_file_detected(self, tmp_path: Path, sqlite_conn: sqlite3.Connection) -> None:
        """A file not in fingerprints should appear in FileDiff.new."""
        tracker = FileTracker(sqlite_conn)
        fi = _make_file(tmp_path, "new.md", "hello world")

        diff = tracker.diff([fi])

        assert str(fi.path) in diff.new
        assert diff.modified == []
        assert diff.deleted == []
        assert diff.unchanged == []

    def test_unchanged_file_same_mtime_size(
        self, tmp_path: Path, sqlite_conn: sqlite3.Connection
    ) -> None:
        """A file with matching mtime+size should be unchanged; no bytes read."""
        tracker = FileTracker(sqlite_conn)
        fi = _make_file(tmp_path, "stable.md", "stable content")
        stat = fi.path.stat()
        # Pre-save a fingerprint that matches current file state
        from dotmd.ingestion.reader import chunk_checksum

        checksum = chunk_checksum(fi.path)
        tracker.save_fingerprint(str(fi.path), stat.st_mtime, stat.st_size, checksum)

        diff = tracker.diff([fi])

        assert str(fi.path) in diff.unchanged
        assert diff.new == []
        assert diff.modified == []

    def test_modified_file_different_checksum(
        self, tmp_path: Path, sqlite_conn: sqlite3.Connection
    ) -> None:
        """A file whose content changed should appear in FileDiff.modified."""
        tracker = FileTracker(sqlite_conn)
        fi = _make_file(tmp_path, "changing.md", "original content")
        stat = fi.path.stat()
        tracker.save_fingerprint(str(fi.path), stat.st_mtime, stat.st_size, "old_fake_checksum")

        # Modify the file content (change size to force checksum check)
        fi.path.write_text("totally different content here")
        # Rebuild FileInfo with new stat
        new_stat = fi.path.stat()
        fi_new = FileInfo(
            path=fi.path,
            title="changing.md",
            last_modified=datetime.fromtimestamp(new_stat.st_mtime, tz=UTC),
            size_bytes=new_stat.st_size,
        )

        diff = tracker.diff([fi_new])

        assert str(fi.path) in diff.modified

    def test_deleted_file(self, tmp_path: Path, sqlite_conn: sqlite3.Connection) -> None:
        """A file in fingerprints but not discovered should appear in FileDiff.deleted."""
        tracker = FileTracker(sqlite_conn)
        # Save a fingerprint for a file that no longer exists
        tracker.save_fingerprint("/gone/file.md", 1000.0, 42, "abc123")

        diff = tracker.diff([])  # no discovered files

        assert "/gone/file.md" in diff.deleted

    def test_mtime_changed_content_same(
        self, tmp_path: Path, sqlite_conn: sqlite3.Connection
    ) -> None:
        """File with different mtime but same content -> unchanged, mtime updated."""
        tracker = FileTracker(sqlite_conn)
        fi = _make_file(tmp_path, "touched.md", "same content")
        from dotmd.ingestion.reader import chunk_checksum

        checksum = chunk_checksum(fi.path)
        # Save fingerprint with an old mtime but same checksum
        old_mtime = fi.path.stat().st_mtime - 100.0
        tracker.save_fingerprint(str(fi.path), old_mtime, fi.size_bytes, checksum)

        diff = tracker.diff([fi])

        assert str(fi.path) in diff.unchanged
        assert diff.modified == []

        # Verify mtime was updated in DB
        cur = sqlite_conn.execute(
            "SELECT mtime FROM file_fingerprints WHERE file_path = ?",
            (str(fi.path),),
        )
        stored_mtime = cur.fetchone()[0]
        assert stored_mtime != old_mtime  # mtime should be updated


class TestFileTrackerPersistence:
    """Tests for fingerprint CRUD operations."""

    def test_save_fingerprint_persists_and_survives_reconnect(self, tmp_dir: Path) -> None:
        """Fingerprint should survive closing and reopening the connection."""
        db_path = str(tmp_dir / "persist.db")
        conn1 = sqlite3.connect(db_path)
        tracker1 = FileTracker(conn1)
        tracker1.save_fingerprint("/test/file.md", 1234.5, 100, "deadbeef")
        conn1.close()

        # Reopen connection and check
        conn2 = sqlite3.connect(db_path)
        FileTracker(conn2)
        cur = conn2.execute(
            "SELECT mtime, size_bytes, checksum FROM file_fingerprints WHERE file_path = ?",
            ("/test/file.md",),
        )
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 1234.5
        assert row[1] == 100
        assert row[2] == "deadbeef"
        conn2.close()

    def test_remove_fingerprint(self, sqlite_conn: sqlite3.Connection) -> None:
        """remove_fingerprint should delete the entry."""
        tracker = FileTracker(sqlite_conn)
        tracker.save_fingerprint("/test/a.md", 1.0, 10, "aaa")
        tracker.remove_fingerprint("/test/a.md")

        cur = sqlite_conn.execute(
            "SELECT * FROM file_fingerprints WHERE file_path = ?",
            ("/test/a.md",),
        )
        assert cur.fetchone() is None

    def test_clear_removes_all(self, sqlite_conn: sqlite3.Connection) -> None:
        """clear() should remove all fingerprints."""
        tracker = FileTracker(sqlite_conn)
        tracker.save_fingerprint("/a.md", 1.0, 10, "aaa")
        tracker.save_fingerprint("/b.md", 2.0, 20, "bbb")
        tracker.clear()

        cur = sqlite_conn.execute("SELECT COUNT(*) FROM file_fingerprints")
        assert cur.fetchone()[0] == 0
