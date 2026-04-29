"""Feedback storage for MCP SubmitFeedback tool."""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_VALID_SEVERITIES = frozenset({"bug", "suggestion", "question"})
_VALID_STATUSES = frozenset({"open", "in_progress", "done", "dismissed"})


class FeedbackStore:
    """SQLite-backed store for agent feedback submissions.

    Agent writes via submit(). Operator reads via list_all(), set_status(), delete().
    WAL mode allows concurrent reads while the MCP server writes.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    submitted_at INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    severity TEXT,
                    context TEXT,
                    model TEXT,
                    harness TEXT,
                    status TEXT NOT NULL DEFAULT 'open',
                    status_changed_at INTEGER,
                    status_comment TEXT
                )
            """)

    def submit(
        self,
        message: str,
        severity: str | None = None,
        context: str | None = None,
        model: str | None = None,
        harness: str | None = None,
    ) -> None:
        if severity and severity not in _VALID_SEVERITIES:
            severity = None
        now = int(time.time())
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO feedback (submitted_at, message, severity, context, model, harness)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (now, message, severity, context, model, harness),
            )
        logger.info("Feedback submitted: id=%d severity=%s", cur.lastrowid, severity)

    def list_all(self, limit: int = 50, include_closed: bool = False) -> list[dict]:
        with self._connect() as conn:
            if include_closed:
                rows = conn.execute(
                    "SELECT * FROM feedback ORDER BY submitted_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM feedback WHERE status IN ('open', 'in_progress') "
                    "ORDER BY submitted_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def set_status(self, feedback_id: int, status: str, reason: str | None = None) -> bool:
        if status not in _VALID_STATUSES:
            raise ValueError(f"Invalid status {status!r}. Must be one of: {', '.join(sorted(_VALID_STATUSES))}")
        now = int(time.time())
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE feedback SET status = ?, status_changed_at = ?, status_comment = ? WHERE id = ?",
                (status, now, reason, feedback_id),
            )
        return cur.rowcount > 0

    def delete(self, feedback_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM feedback WHERE id = ?", (feedback_id,))
        return cur.rowcount > 0
