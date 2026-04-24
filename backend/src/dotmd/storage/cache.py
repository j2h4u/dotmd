"""Global embedding cache — content-addressed, model-aware.

Stores ``(text_hash, model_name) → embedding BLOB`` in the shared
``index.db`` so that TEI HTTP calls are skipped for chunks whose text
has already been embedded by the same model, even after a file move that
purges the chunk from ``vec_meta``.

Composite primary key ``(text_hash, model_name)`` guarantees that vectors
from different models are stored separately and never cross-used.  A
sentinel row in ``embedding_cache_meta`` tracks which model populated the
cache; on model change :meth:`should_invalidate` returns ``True`` and the
caller must call :meth:`clear` before the first lookup.
"""

from __future__ import annotations

import logging
import sqlite3
import struct

logger = logging.getLogger(__name__)


class EmbeddingCache:
    """SQLite-backed global embedding cache keyed on ``(text_hash, model_name)``.

    Parameters
    ----------
    conn:
        Shared SQLite connection to ``index.db``.  The cache tables are
        created on first instantiation.
    model_name:
        Name of the currently active embedding model (e.g.
        ``"intfloat/multilingual-e5-large"``).  Used both as a lookup
        filter and for model-change invalidation.
    """

    _BATCH = 500  # max placeholders per IN-clause

    def __init__(self, conn: sqlite3.Connection, model_name: str) -> None:
        self._conn = conn
        self._model_name = model_name
        self.ensure_table()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def ensure_table(self) -> None:
        """Create cache tables if they do not already exist."""
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS embedding_cache (
                text_hash  TEXT NOT NULL,
                model_name TEXT NOT NULL,
                embedding  BLOB NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (text_hash, model_name)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS embedding_cache_meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Model-change invalidation
    # ------------------------------------------------------------------

    def should_invalidate(self) -> bool:
        """Return ``True`` if the stored model sentinel differs from the current model.

        Returns ``False`` on a fresh table (no sentinel row yet).
        """
        row = self._conn.execute(
            "SELECT value FROM embedding_cache_meta WHERE key = 'model_name'"
        ).fetchone()
        if row is None:
            return False
        return row[0] != self._model_name

    def clear(self) -> None:
        """Wipe all cached embeddings and reset the model sentinel."""
        self._conn.execute("DELETE FROM embedding_cache")
        self._conn.execute("DELETE FROM embedding_cache_meta")
        self._conn.execute(
            "INSERT OR REPLACE INTO embedding_cache_meta VALUES ('model_name', ?)",
            (self._model_name,),
        )
        self._conn.commit()

    def update_model_sentinel(self) -> None:
        """Write (or confirm) the current model name into the meta table."""
        self._conn.execute(
            "INSERT OR REPLACE INTO embedding_cache_meta VALUES ('model_name', ?)",
            (self._model_name,),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def lookup(self, text_hashes: list[str]) -> dict[str, list[float]]:
        """Return cached embeddings for the given text hashes.

        Only rows whose ``model_name`` matches the current model are
        returned.  Missing hashes are silently omitted.

        Parameters
        ----------
        text_hashes:
            Content hashes to look up.

        Returns
        -------
        dict[str, list[float]]
            Mapping of ``{text_hash: embedding}`` for hashes found.
        """
        if not text_hashes:
            return {}

        result: dict[str, list[float]] = {}
        try:
            for i in range(0, len(text_hashes), self._BATCH):
                batch = text_hashes[i : i + self._BATCH]
                placeholders = ",".join("?" * len(batch))
                rows = self._conn.execute(
                    f"SELECT text_hash, embedding FROM embedding_cache"
                    f" WHERE model_name = ? AND text_hash IN ({placeholders})",
                    (self._model_name, *batch),
                ).fetchall()
                for text_hash, blob in rows:
                    dim = len(blob) // 4  # 4 bytes per float32
                    result[text_hash] = list(struct.unpack(f"{dim}f", blob))
        except Exception:
            logger.warning(
                "embedding_cache lookup failed — returning empty (graceful degradation)",
                exc_info=True,
            )
            return {}

        return result

    # ------------------------------------------------------------------
    # Store
    # ------------------------------------------------------------------

    def store(self, text_hash: str, embedding: list[float]) -> None:
        """Persist one embedding into the cache.

        Uses ``INSERT OR IGNORE`` so re-storing an existing hash is a
        no-op (the original value is preserved).  Does **not** commit —
        the caller's existing commit (after vector-store writes) persists
        this row in the same transaction.

        Parameters
        ----------
        text_hash:
            Content hash of the chunk text.
        embedding:
            Float vector produced by the embedding model.
        """
        blob = struct.pack(f"{len(embedding)}f", *embedding)
        self._conn.execute(
            "INSERT OR IGNORE INTO embedding_cache"
            " (text_hash, model_name, embedding) VALUES (?, ?, ?)",
            (text_hash, self._model_name, blob),
        )
