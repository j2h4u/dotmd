"""FTS5 keyword search engine for dotMD.

Uses SQLite FTS5 for incremental full-text search over chunks.
Each chunk is INSERT-ed immediately, eliminating full-corpus rebuilds.
"""

from __future__ import annotations

import logging
import re
import sqlite3

from dotmd.core.models import Chunk

logger = logging.getLogger(__name__)

_CREATE_FTS5_TPL = """
CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING fts5(
    chunk_id UNINDEXED,
    text,
    title,
    tags,
    tokenize = 'unicode61'
)
"""

# ADR: FTS5 column weights are 1x text, 5x title, 3x tags.
# Title gets highest boost (5x) because a title match is the strongest
# relevance signal -- the entire document is about that term.
# Tags get 3x because they are curated metadata indicating topical relevance
# but a tag match is weaker than a title match (file may only be tangentially
# related to a tag). Body text gets baseline 1x.
_BM25_WEIGHTS = "1.0, 5.0, 3.0"


_COMPOUND_RE = re.compile(r"(\w+)['\u2019\u2018/\-\u2013\u2014](\w+)")


def _expand_compounds(text: str) -> str:
    """Expand compound words for FTS5 indexing.

    For each word containing an intra-word separator (hyphen, apostrophe,
    slash, dash), appends the joined form so both variants are searchable:
      "инфо-цыганам" → "инфо-цыганам инфоцыганам"
      "TCP/IP" → "TCP/IP TCPIP"
    """
    expanded = []
    for m in _COMPOUND_RE.finditer(text):
        joined = m.group(1) + m.group(2)
        if joined.lower() not in text.lower():
            expanded.append(joined)
    if expanded:
        return text + " " + " ".join(expanded)
    return text


def _sanitize_fts5_query(query: str) -> str:
    """Sanitize a user query for safe FTS5 MATCH usage.

    Removes FTS5 special characters. Each word uses prefix matching
    (``word*``) so partial/compound word variants are found.
    For example, "инфоцыган" matches "инфоцыганам" via prefix.
    """
    # Remove FTS5 special characters
    cleaned = re.sub(r'["\(\)\*:]', "", query)
    words = cleaned.split()
    if not words:
        return ""
    # Use prefix matching so compound word variants are found.
    # FTS5 prefix syntax: unquoted word followed by *
    return " ".join(f"{w}*" for w in words)


class FTS5SearchEngine:
    """Full-text search engine backed by SQLite FTS5.

    Replaces the former pickle-based keyword search engine.  The FTS5
    virtual table lives in the same SQLite database as chunk metadata,
    sharing the WAL-mode connection.

    Parameters
    ----------
    conn:
        An open ``sqlite3.Connection`` (typically the metadata store's
        connection, already in WAL mode).
    table_name:
        Name of the FTS5 virtual table.  Defaults to ``"chunks_fts"``
        for backward compatibility.  Use a strategy-specific name
        (e.g. ``"chunks_fts_heading_512_50"``) for multi-strategy
        isolation.
    """

    def __init__(self, conn: sqlite3.Connection, table_name: str = "chunks_fts") -> None:
        self._conn = conn
        self._table = table_name
        self._ensure_fts5_schema()

    def _ensure_fts5_schema(self) -> None:
        """Create or migrate the FTS5 table to include title + tags columns.

        FTS5 does not support ALTER TABLE, so if the schema is outdated
        (missing title/tags columns) we drop and recreate.
        """
        # Check if table exists at all
        table_exists = self._conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
            (self._table,),
        ).fetchone()[0]

        if table_exists:
            col_names = {r[1] for r in self._conn.execute(f"PRAGMA table_info({self._table})").fetchall()}
            if "title" not in col_names or "tags" not in col_names:
                row_count = self._conn.execute(f"SELECT COUNT(*) FROM {self._table}").fetchone()[0]
                logger.info(
                    "FTS5: dropping and recreating %s to add title+tags columns (%d rows will be lost, run reindex_fts5 to repopulate)",
                    self._table, row_count,
                )
                self._conn.execute(f"DROP TABLE {self._table}")
                self._conn.commit()

        self._conn.execute(_CREATE_FTS5_TPL.format(table=self._table))
        self._conn.commit()

    # ------------------------------------------------------------------
    # Incremental add / remove
    # ------------------------------------------------------------------

    def add_chunks(
        self,
        chunks: list[Chunk],
        file_meta: dict[str, tuple[str, str]] | None = None,
    ) -> None:
        """Insert or replace chunks in the FTS5 index.

        Parameters
        ----------
        chunks:
            Chunks to add.  Existing entries with the same ``chunk_id``
            are replaced.
        file_meta:
            Optional mapping of ``file_path_str -> (title, tags_csv)``
            for populating the title and tags FTS5 columns.
        """
        if not chunks:
            return
        file_meta = file_meta or {}
        rows = []
        for c in chunks:
            # Phase 16: Chunk.file_path → Chunk.file_paths (list). Use first
            # path for file_meta lookup; falls back to empty string for orphaned chunks.
            _fp_key = str(c.file_paths[0]) if c.file_paths else ""
            title, tags_csv = file_meta.get(_fp_key, ("", ""))
            rows.append((c.chunk_id, _expand_compounds(c.text), title, tags_csv))
        self._conn.executemany(
            f"INSERT OR REPLACE INTO {self._table}(chunk_id, text, title, tags) "
            f"VALUES (?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()
        logger.debug("FTS5: added %d chunks", len(chunks))

    def remove_chunks(
        self,
        chunk_ids: list[str],
        *,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        """Remove chunks from the FTS5 index by their identifiers.

        Parameters
        ----------
        chunk_ids:
            List of chunk identifiers to delete.
        conn:
            Optional caller-supplied connection.  When provided the delete
            runs inside the caller's transaction and commit() is NOT called
            (P4 single-transaction purge pattern).  When None the engine's
            own connection is used and commit() is called as before.
        """
        if not chunk_ids:
            return
        _conn = conn if conn is not None else self._conn
        _conn.executemany(
            f"DELETE FROM {self._table} WHERE chunk_id = ?",
            [(cid,) for cid in chunk_ids],
        )
        if conn is None:
            self._conn.commit()
        logger.debug("FTS5: removed %d chunks", len(chunk_ids))

    # ------------------------------------------------------------------
    # Compatibility wrappers
    # ------------------------------------------------------------------

    def load_index(self) -> None:
        """One-time migration: populate FTS5 from the ``chunks`` table.

        If the FTS5 table is empty but the ``chunks`` table has data,
        all chunk texts are copied over.  This provides a seamless
        upgrade path from the old pickle-based keyword index.
        """
        fts_count = self._conn.execute(
            f"SELECT COUNT(*) FROM {self._table}"
        ).fetchone()[0]

        # Derive the chunks table name from the FTS table name.
        # "chunks_fts" -> "chunks", "chunks_fts_heading_512_50" -> "chunks_heading_512_50"
        chunks_table = self._table.replace("_fts", "", 1)

        try:
            chunks_count = self._conn.execute(
                f"SELECT COUNT(*) FROM {chunks_table}"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            # chunks table doesn't exist yet
            logger.info("FTS5: no %s table found; skipping migration", chunks_table)
            return

        if fts_count == 0 and chunks_count > 0:
            self._conn.execute(
                f"INSERT INTO {self._table}(chunk_id, text, title, tags) "
                f"SELECT chunk_id, text, '', '' FROM {chunks_table}"
            )
            self._conn.commit()
            logger.info("FTS5: migrated %d chunks from %s", chunks_count, chunks_table)
        elif fts_count > 0:
            logger.info("FTS5: index already populated (%d chunks)", fts_count)
        else:
            logger.info("FTS5: no chunks to index yet")

    def build_index(
        self,
        chunks: list[Chunk],
        file_meta: dict[str, tuple[str, str]] | None = None,
    ) -> None:
        """Compatibility wrapper -- delegates to :meth:`add_chunks`."""
        self.add_chunks(chunks, file_meta=file_meta)

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
                f"SELECT chunk_id, -bm25({self._table}, {_BM25_WEIGHTS}) AS score "
                f"FROM {self._table} WHERE {self._table} MATCH ? "
                f"ORDER BY bm25({self._table}, {_BM25_WEIGHTS}) LIMIT ?",
                (sanitized, top_k),
            )
            return [(row[0], row[1]) for row in cur.fetchall()]
        except sqlite3.OperationalError as exc:
            logger.warning("FTS5 search error for query %r: %s", query, exc)
            return []
