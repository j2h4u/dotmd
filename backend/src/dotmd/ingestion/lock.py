"""Exclusive file lock for indexing operations."""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path

from dotmd.core.exceptions import IndexingLockError


@contextmanager
def indexing_lock(index_dir: Path):
    """Acquire exclusive lock on <index_dir>/indexing.lock.

    Uses fcntl.flock (LOCK_EX | LOCK_NB). Non-blocking: if lock is held
    by another process, raises IndexingLockError immediately.
    Lock is released automatically on process exit (kernel cleanup).
    """
    lock_path = index_dir / "indexing.lock"
    with lock_path.open("w") as fd:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise IndexingLockError("Indexing already in progress. Stop the server first.") from exc
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
