"""SQLite-vec backed vector store for chunk-embedding similarity search.

Implements :class:`~dotmd.storage.base.VectorStoreProtocol` using
`sqlite-vec <https://github.com/asg017/sqlite-vec>`_, a SQLite extension
for vector similarity search. No external services or AVX2 required.
"""

from __future__ import annotations

import logging
import sqlite3
import struct
from pathlib import Path

from dotmd.core.models import Chunk

logger = logging.getLogger(__name__)


def _serialize_f32(vec: list[float]) -> bytes:
    """Serialize a float vector to a compact binary format for sqlite-vec."""
    return struct.pack(f"{len(vec)}f", *vec)


class SQLiteVecVectorStore:
    """sqlite-vec implementation of :class:`VectorStoreProtocol`.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.
    table_name:
        Virtual table name for vector storage.
    """

    _VEC_TABLE = "vec_chunks"
    _META_TABLE = "vec_meta"
    _CONFIG_TABLE = "vec_config"

    def __init__(self, db_path: Path, table_name: str = "vec_chunks") -> None:
        self._db_path = db_path
        self._VEC_TABLE = table_name
        self._conn: sqlite3.Connection | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._db_path))
            self._conn.enable_load_extension(True)
            import sqlite_vec  # type: ignore[import-untyped]

            sqlite_vec.load(self._conn)
            self._conn.enable_load_extension(False)
            self._ensure_tables()
        return self._conn

    def _ensure_tables(self) -> None:
        conn = self._conn
        assert conn is not None
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self._META_TABLE} (
                rowid INTEGER PRIMARY KEY,
                chunk_id TEXT NOT NULL UNIQUE
            )
        """)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self._CONFIG_TABLE} (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.commit()

    def _get_dim(self) -> int | None:
        """Read the stored embedding dimension, or None if not yet indexed."""
        conn = self._get_conn()
        row = conn.execute(
            f"SELECT value FROM {self._CONFIG_TABLE} WHERE key = 'dim'",
        ).fetchone()
        return int(row[0]) if row else None

    def _create_vec_table(self, dim: int) -> None:
        """Create (or recreate) the vec0 virtual table for the given dimension."""
        conn = self._get_conn()
        old_dim = self._get_dim()

        if old_dim == dim:
            return

        if old_dim is not None:
            logger.warning(
                "Embedding dimension changed %d → %d — recreating vector table",
                old_dim, dim,
            )

        conn.execute(f"DROP TABLE IF EXISTS {self._VEC_TABLE}")
        conn.execute(f"""
            CREATE VIRTUAL TABLE {self._VEC_TABLE}
            USING vec0(embedding float[{dim}])
        """)
        conn.execute(
            f"INSERT OR REPLACE INTO {self._CONFIG_TABLE} (key, value) VALUES ('dim', ?)",
            (str(dim),),
        )
        conn.commit()

    def _has_index(self) -> bool:
        """Check whether the vector table exists and has been populated."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (self._VEC_TABLE,),
        ).fetchone()
        return row is not None

    # -- mutations ----------------------------------------------------------

    def add_chunks(
        self,
        chunks: list[Chunk],
        embeddings: list[list[float]],
    ) -> None:
        if not chunks:
            return

        dim = len(embeddings[0])
        self._create_vec_table(dim)
        conn = self._get_conn()

        # Clear existing data (matches LanceDB's mode="overwrite")
        conn.execute(f"DELETE FROM {self._VEC_TABLE}")
        conn.execute(f"DELETE FROM {self._META_TABLE}")

        for chunk, embedding in zip(chunks, embeddings):
            cur = conn.execute(
                f"INSERT INTO {self._META_TABLE} (chunk_id) VALUES (?)",
                (chunk.chunk_id,),
            )
            conn.execute(
                f"INSERT INTO {self._VEC_TABLE} (rowid, embedding) VALUES (?, ?)",
                (cur.lastrowid, _serialize_f32(embedding)),
            )

        conn.commit()
        logger.info("Indexed %d chunks (%d-dim vectors)", len(chunks), dim)

    def delete_vectors_by_chunk_ids(self, chunk_ids: list[str]) -> int:
        """Delete vectors for the given chunk IDs. Returns count deleted."""
        if not chunk_ids:
            return 0
        conn = self._get_conn()
        placeholders = ",".join("?" for _ in chunk_ids)

        # Get rowids from meta table
        rows = conn.execute(
            f"SELECT rowid FROM {self._META_TABLE} WHERE chunk_id IN ({placeholders})",
            chunk_ids,
        ).fetchall()
        rowids = [r[0] for r in rows]

        if not rowids:
            return 0

        rowid_placeholders = ",".join("?" for _ in rowids)
        # Delete from vec0 virtual table by rowid
        conn.execute(
            f"DELETE FROM {self._VEC_TABLE} WHERE rowid IN ({rowid_placeholders})",
            rowids,
        )
        # Delete from meta table
        conn.execute(
            f"DELETE FROM {self._META_TABLE} WHERE chunk_id IN ({placeholders})",
            chunk_ids,
        )
        conn.commit()

        return len(rowids)


    def delete_all(self) -> None:
        try:
            conn = self._get_conn()
            conn.execute(f"DROP TABLE IF EXISTS {self._VEC_TABLE}")
            conn.execute(f"DELETE FROM {self._META_TABLE}")
            conn.execute(f"DELETE FROM {self._CONFIG_TABLE}")
            conn.commit()
        except Exception:  # noqa: BLE001
            pass

    # -- queries ------------------------------------------------------------

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
    ) -> list[tuple[str, float]]:
        try:
            conn = self._get_conn()
        except Exception:  # noqa: BLE001
            return []

        if not self._has_index():
            return []

        try:
            rows = conn.execute(
                f"""
                SELECT m.chunk_id, v.distance
                FROM (
                    SELECT rowid, distance
                    FROM {self._VEC_TABLE}
                    WHERE embedding MATCH ? AND k = ?
                ) v
                JOIN {self._META_TABLE} m ON m.rowid = v.rowid
                """,
                (_serialize_f32(query_embedding), top_k),
            ).fetchall()
        except Exception:  # noqa: BLE001
            return []

        return [(row[0], 1.0 / (1.0 + row[1])) for row in rows]

    def count(self) -> int:
        try:
            conn = self._get_conn()
            return conn.execute(f"SELECT COUNT(*) FROM {self._META_TABLE}").fetchone()[0]
        except Exception:  # noqa: BLE001
            return 0
