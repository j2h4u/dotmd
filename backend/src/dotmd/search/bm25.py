"""BM25 (sparse keyword) search engine for dotMD.

Uses SQLite FTS5 for incremental full-text search over chunks.
Each chunk is INSERT-ed immediately, eliminating full-corpus rebuilds.
"""

from __future__ import annotations

import logging
import re
import sqlite3

from dotmd.core.models import Chunk

logger = logging.getLogger(__name__)

_CREATE_FTS5 = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id UNINDEXED,
    text,
    tokenize = 'unicode61'
)
"""


def _sanitize_fts5_query(query: str) -> str:
    """Sanitize a user query for safe FTS5 MATCH usage.

    Removes FTS5 special characters and wraps each word in double
    quotes so that they are treated as literal terms.
    """
    # Remove FTS5 special characters
    cleaned = re.sub(r'["\(\)\*:]', "", query)
    words = cleaned.split()
    if not words:
        return ""
    return " ".join(f'"{w}"' for w in words)


class FTS5SearchEngine:
    """Full-text search engine backed by SQLite FTS5.

    Replaces the former pickle-based ``BM25SearchEngine``.  The FTS5
    virtual table lives in the same SQLite database as chunk metadata,
    sharing the WAL-mode connection.

    Parameters
    ----------
    conn:
        An open ``sqlite3.Connection`` (typically the metadata store's
        connection, already in WAL mode).
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.execute(_CREATE_FTS5)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Incremental add / remove
    # ------------------------------------------------------------------

    def add_chunks(self, chunks: list[Chunk]) -> None:
        """Insert or replace chunks in the FTS5 index.

        Parameters
        ----------
        chunks:
            Chunks to add.  Existing entries with the same ``chunk_id``
            are replaced.
        """
        if not chunks:
            return
        rows = [(c.chunk_id, c.text) for c in chunks]
        self._conn.executemany(
            "INSERT OR REPLACE INTO chunks_fts(chunk_id, text) VALUES (?, ?)",
            rows,
        )
        self._conn.commit()
        logger.debug("FTS5: added %d chunks", len(chunks))

    def remove_chunks(self, chunk_ids: list[str]) -> None:
        """Remove chunks from the FTS5 index by their identifiers.

        Parameters
        ----------
        chunk_ids:
            List of chunk identifiers to delete.
        """
        if not chunk_ids:
            return
        self._conn.executemany(
            "DELETE FROM chunks_fts WHERE chunk_id = ?",
            [(cid,) for cid in chunk_ids],
        )
        self._conn.commit()
        logger.debug("FTS5: removed %d chunks", len(chunk_ids))

    # ------------------------------------------------------------------
    # Compatibility wrappers
    # ------------------------------------------------------------------

    def load_index(self) -> None:
        """One-time migration: populate FTS5 from the ``chunks`` table.

        If the FTS5 table is empty but the ``chunks`` table has data,
        all chunk texts are copied over.  This provides a seamless
        upgrade path from the old pickle-based BM25 index.
        """
        fts_count = self._conn.execute(
            "SELECT COUNT(*) FROM chunks_fts"
        ).fetchone()[0]

        try:
            chunks_count = self._conn.execute(
                "SELECT COUNT(*) FROM chunks"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            # chunks table doesn't exist yet
            logger.info("FTS5: no chunks table found; skipping migration")
            return

        if fts_count == 0 and chunks_count > 0:
            self._conn.execute(
                "INSERT INTO chunks_fts(chunk_id, text) "
                "SELECT chunk_id, text FROM chunks"
            )
            self._conn.commit()
            logger.info("FTS5: migrated %d chunks from metadata", chunks_count)
        elif fts_count > 0:
            logger.info("FTS5: index already populated (%d chunks)", fts_count)
        else:
            logger.info("FTS5: no chunks to index yet")

    def build_index(self, chunks: list[Chunk]) -> None:
        """Compatibility wrapper -- delegates to :meth:`add_chunks`."""
        self.add_chunks(chunks)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Search the FTS5 index and return ``(chunk_id, score)`` pairs.

        Parameters
        ----------
        query:
            The natural-language search query.
        top_k:
            Maximum number of results to return.

        Returns
        -------
        list[tuple[str, float]]
            A list of ``(chunk_id, score)`` pairs ordered by
            descending relevance.  Returns an empty list if the query
            is empty or an FTS5 syntax error occurs.
        """
        sanitized = _sanitize_fts5_query(query)
        if not sanitized:
            return []

        try:
            cur = self._conn.execute(
                "SELECT chunk_id, -rank AS score "
                "FROM chunks_fts WHERE chunks_fts MATCH ? "
                "ORDER BY rank LIMIT ?",
                (sanitized, top_k),
            )
            return [(row[0], row[1]) for row in cur.fetchall()]
        except sqlite3.OperationalError as exc:
            logger.warning("FTS5 search error for query %r: %s", query, exc)
            return []
