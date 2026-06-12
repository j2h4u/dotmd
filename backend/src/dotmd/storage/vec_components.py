"""Raw component embedding storage for dual-encoder unified embeddings.

Stores ``(entity_id, component) -> embedding BLOB`` in the shared ``index.db``
SQLite database.  Used by Phase 999.12 dual-encoder architecture to persist
raw per-component vectors before fusion weighting.

Entity ID conventions
---------------------
Two component types are stored:

* **``"text"`` component** — keyed by ``chunk_id`` (str), stores
  ``embed(chunk.text)`` as a float32 BLOB.
* **``"meta"`` component** — keyed by the canonical absolute, symlink-resolved
  POSIX path string (see invariant below), stores ``embed(title + tags)`` as a
  float32 BLOB.

Canonical path invariant
------------------------
For the ``"meta"`` component, ``entity_id`` **MUST** be
``str(pathlib.Path(file_path).resolve())``.  This produces the absolute,
symlink-resolved POSIX path string.  The same canonical form must be used
consistently across:

1. ``VecComponentStore.store(entity_id, "meta", ...)`` calls — callers must
   pass ``str(Path(fp).resolve())``.
2. ``VecComponentStore.get(entity_id, "meta")`` calls — same canonical form.
3. ``VecComponentStore.get_batch(entity_ids, "meta")`` calls — all paths must
   be normalized.
4. ``meta_tracker`` ``FileTracker`` — the ``meta_fp_table`` uses the same path
   as a key (``pipeline.py`` ensures this).
5. ``vec_meta`` table path column — same canonical form.

**VecComponentStore itself does NOT normalize entity_ids** — normalization is
the caller's responsibility.  Never pass relative paths or unresolved symlinks
as entity_ids for the ``"meta"`` component.

Connection lifecycle
--------------------
The ``conn`` argument is a shared SQLite connection owned by the caller
(typically ``IndexingPipeline``).  VecComponentStore does not open, close, or
manage the connection.  ``store()`` and ``delete_by_entity_ids()`` do not call
``commit()`` — the caller is the transaction owner.
"""

from __future__ import annotations

import logging
import sqlite3
import struct

logger = logging.getLogger(__name__)

_BATCH_SIZE = 500  # max placeholders per IN-clause (SQLite default limit = 999)


class VecComponentStore:
    """SQLite-backed store for raw per-component embedding BLOBs.

    Parameters
    ----------
    conn:
        Shared SQLite connection to ``index.db``.  The caller owns the
        connection lifecycle.  The caller is responsible for loading any
        required extensions before constructing this store.
    table_name:
        Name of the SQLite table, e.g.
        ``"vec_components_heading_512_50_multilingual_e5_large"``.
        Must follow the same two-dimensional suffix pattern as
        ``vec_chunks{suffix}``, ``vec_meta{suffix}``, ``vec_config{suffix}``.
        The caller (``pipeline.py``) constructs this as:
        ``f"vec_components{strategy_suffix}{model_suffix}"``.
    """

    def __init__(self, conn: sqlite3.Connection, table_name: str) -> None:
        self._conn = conn
        self._TABLE = table_name
        self._ensure_table()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _ensure_table(self) -> None:
        """Create the component table if it does not already exist."""
        self._conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self._TABLE} (
                entity_id  TEXT NOT NULL,
                component  TEXT NOT NULL,
                embedding  BLOB NOT NULL,
                PRIMARY KEY (entity_id, component)
            )
        """)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def store(self, entity_id: str, component: str, embedding: list[float]) -> None:
        """Persist one component embedding.

        Uses ``INSERT OR REPLACE`` so re-storing an existing ``(entity_id,
        component)`` pair overwrites the previous value.  Does **not** call
        ``commit()`` — the caller owns the transaction boundary.

        Parameters
        ----------
        entity_id:
            For ``"text"`` component: the chunk's ``chunk_id``.
            For ``"meta"`` component: ``str(Path(file_path).resolve())``.
        component:
            Component name, e.g. ``"text"`` or ``"meta"``.
        embedding:
            Float vector to persist.  Serialized as float32 BLOB.
        """
        blob = struct.pack(f"{len(embedding)}f", *embedding)
        self._conn.execute(
            f"INSERT OR REPLACE INTO {self._TABLE} (entity_id, component, embedding)"
            " VALUES (?, ?, ?)",
            (entity_id, component, blob),
        )

    def delete_by_entity_ids(self, entity_ids: list[str]) -> int:
        """Delete all component rows for the given entity IDs.

        Does **not** call ``commit()`` — the caller owns the transaction
        boundary.  Processes in batches of 500 to stay within SQLite's
        variable limit.

        Parameters
        ----------
        entity_ids:
            Entity identifiers whose rows should be removed.

        Returns
        -------
        int
            Total number of rows deleted across all batches.
        """
        if not entity_ids:
            return 0

        total_deleted = 0
        for i in range(0, len(entity_ids), _BATCH_SIZE):
            batch = entity_ids[i : i + _BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch)
            cur = self._conn.execute(
                f"DELETE FROM {self._TABLE} WHERE entity_id IN ({placeholders})",
                batch,
            )
            total_deleted += cur.rowcount

        return total_deleted

    def delete_all(self) -> None:
        """Remove all rows from the component table and commit."""
        self._conn.execute(f"DELETE FROM {self._TABLE}")
        self._conn.commit()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, entity_id: str, component: str) -> list[float] | None:
        """Retrieve a single component embedding.

        Parameters
        ----------
        entity_id:
            For ``"text"`` component: chunk_id.
            For ``"meta"`` component: ``str(Path(file_path).resolve())``.
        component:
            Component name, e.g. ``"text"`` or ``"meta"``.

        Returns
        -------
        list[float] | None
            The embedding vector, or ``None`` if not found.
        """
        row = self._conn.execute(
            f"SELECT embedding FROM {self._TABLE} WHERE entity_id = ? AND component = ?",
            (entity_id, component),
        ).fetchone()
        if row is None:
            return None
        blob = row[0]
        dim = len(blob) // 4  # 4 bytes per float32
        return list(struct.unpack(f"{dim}f", blob))

    def get_batch(self, entity_ids: list[str], component: str) -> dict[str, list[float]]:
        """Retrieve embeddings for multiple entity IDs with one component name.

        Processes in batches of 500 to stay within SQLite's variable limit.
        Missing entity IDs are silently omitted from the result.

        Parameters
        ----------
        entity_ids:
            Entity identifiers to look up.
        component:
            Component name, e.g. ``"text"`` or ``"meta"``.

        Returns
        -------
        dict[str, list[float]]
            Mapping of ``{entity_id: embedding}`` for found rows only.
        """
        if not entity_ids:
            return {}

        result: dict[str, list[float]] = {}
        for i in range(0, len(entity_ids), _BATCH_SIZE):
            batch = entity_ids[i : i + _BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch)
            rows = self._conn.execute(
                f"SELECT entity_id, embedding FROM {self._TABLE}"
                f" WHERE component = ? AND entity_id IN ({placeholders})",
                (component, *batch),
            ).fetchall()
            for entity_id, blob in rows:
                dim = len(blob) // 4
                result[entity_id] = list(struct.unpack(f"{dim}f", blob))

        return result

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Return the total number of rows in the component table."""
        try:
            return self._conn.execute(f"SELECT COUNT(*) FROM {self._TABLE}").fetchone()[0]
        except sqlite3.OperationalError:
            logger.warning("Failed to count vec_components rows", exc_info=True)
            return 0
