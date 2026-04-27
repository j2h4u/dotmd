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
        Path to the SQLite database file.  Ignored when *conn* is provided.
    table_name:
        Virtual table name for vector storage.
    conn:
        Pre-existing SQLite connection (shared database mode).  When given,
        the store reuses this connection instead of opening its own file.
        The caller is responsible for loading the ``sqlite-vec`` extension
        on the connection before constructing this store.
    """

    _VEC_TABLE = "vec_chunks"
    _META_TABLE = "vec_meta"
    _CONFIG_TABLE = "vec_config"

    def __init__(
        self,
        db_path: Path | None = None,
        table_name: str = "vec_chunks",
        *,
        conn: sqlite3.Connection | None = None,
    ) -> None:
        if conn is None and db_path is None:
            raise ValueError("Either db_path or conn must be provided")
        self._db_path = db_path
        self._VEC_TABLE = table_name
        # Derive meta/config table names from vec table name for multi-model support.
        # "vec_chunks" → "vec_meta", "vec_config" (backward compatible)
        # "vec_chunks_pplx_embed" → "vec_meta_pplx_embed", "vec_config_pplx_embed"
        suffix = table_name.removeprefix("vec_chunks")
        self._META_TABLE = f"vec_meta{suffix}"
        self._CONFIG_TABLE = f"vec_config{suffix}"
        # When a shared connection is provided, use it directly.
        # _owns_conn tracks whether we opened the connection ourselves.
        self._owns_conn = conn is None
        self._conn: sqlite3.Connection | None = conn

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            # Own-connection mode: open from db_path.
            assert self._db_path is not None
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")  # concurrent read/write safety
            self._conn.enable_load_extension(True)
            import sqlite_vec  # type: ignore[import-untyped]

            sqlite_vec.load(self._conn)
            self._conn.enable_load_extension(False)
            self._ensure_tables()
        elif not hasattr(self, "_tables_ensured"):
            # Shared-connection mode: tables may not exist yet on first access.
            self._ensure_tables()
            self._tables_ensured = True
        return self._conn

    def _ensure_tables(self) -> None:
        conn = self._conn
        assert conn is not None
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self._META_TABLE} (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                chunk_id TEXT NOT NULL UNIQUE,
                text_hash TEXT
            )
        """)
        # Migrate existing tables that lack the text_hash column.
        self._maybe_add_text_hash_column(conn)
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self._CONFIG_TABLE} (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.commit()

    def _maybe_add_text_hash_column(self, conn: sqlite3.Connection) -> None:
        """Add text_hash column to vec_meta if it doesn't exist (migration)."""
        try:
            cols = conn.execute(
                f"PRAGMA table_info({self._META_TABLE})"
            ).fetchall()
            col_names = {row[1] for row in cols}
            if cols and "text_hash" not in col_names:
                conn.execute(
                    f"ALTER TABLE {self._META_TABLE} ADD COLUMN text_hash TEXT"
                )
                logger.info("Migrated %s: added text_hash column", self._META_TABLE)
        except Exception:  # noqa: BLE001
            # Table might not exist yet (CREATE IF NOT EXISTS hasn't run),
            # or PRAGMA returned nothing — both are fine, column will be
            # present after the CREATE statement above.
            pass

    def _get_dim(self) -> int | None:
        """Read the stored embedding dimension, or None if not yet indexed."""
        conn = self._get_conn()
        row = conn.execute(
            f"SELECT value FROM {self._CONFIG_TABLE} WHERE key = 'dim'",
        ).fetchone()
        return int(row[0]) if row else None

    def get_model_name(self) -> str | None:
        """Read the stored embedding model name, or None if not recorded."""
        conn = self._get_conn()
        row = conn.execute(
            f"SELECT value FROM {self._CONFIG_TABLE} WHERE key = 'model'",
        ).fetchone()
        return row[0] if row else None

    def set_model_name(self, model: str) -> None:
        """Record which embedding model was used to build this index."""
        conn = self._get_conn()
        conn.execute(
            f"INSERT OR REPLACE INTO {self._CONFIG_TABLE} (key, value) VALUES ('model', ?)",
            (model,),
        )
        conn.commit()

    def get_distance_metric(self) -> str | None:
        """Read the stored distance metric, or None if not recorded."""
        conn = self._get_conn()
        row = conn.execute(
            f"SELECT value FROM {self._CONFIG_TABLE} WHERE key = 'metric'",
        ).fetchone()
        return row[0] if row else None

    def set_distance_metric(self, metric: str) -> None:
        """Record which distance metric the vector table uses."""
        conn = self._get_conn()
        conn.execute(
            f"INSERT OR REPLACE INTO {self._CONFIG_TABLE} (key, value) VALUES ('metric', ?)",
            (metric,),
        )
        conn.commit()

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
            USING vec0(embedding float[{dim}] distance_metric=cosine)
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
        *,
        overwrite: bool = True,
        text_hashes: dict[str, str] | None = None,
    ) -> None:
        """Upsert chunks with their corresponding embeddings.

        Parameters
        ----------
        text_hashes:
            Optional mapping of ``{chunk_id: text_hash}`` for embedding reuse
            across chunk strategies.  Stored in vec_meta alongside chunk_id.
        """
        if not chunks:
            return

        dim = len(embeddings[0])
        self._create_vec_table(dim)
        conn = self._get_conn()

        if overwrite:
            # Clear existing data (matches LanceDB's mode="overwrite")
            conn.execute(f"DELETE FROM {self._VEC_TABLE}")
            conn.execute(f"DELETE FROM {self._META_TABLE}")

        for chunk, embedding in zip(chunks, embeddings):
            th = text_hashes.get(chunk.chunk_id) if text_hashes else None
            # Phase 16: use INSERT OR IGNORE so that re-indexing a chunk_id
            # that already has a vector (e.g. identical content from another
            # file) is a no-op. The existing vector row is kept as-is.
            cur = conn.execute(
                f"INSERT OR IGNORE INTO {self._META_TABLE} (chunk_id, text_hash) VALUES (?, ?)",
                (chunk.chunk_id, th),
            )
            # Use cur.rowcount (not cur.lastrowid) to detect no-op.
            # In isolation_level=None (autocommit) mode, cur.lastrowid returns the
            # last successful INSERT rowid on the connection — NOT 0 on no-op — which
            # causes a false positive and an erroneous INSERT into vec0 (UNIQUE violation).
            # cur.rowcount == 0 means INSERT OR IGNORE was a no-op (row already exists).
            if cur.rowcount and cur.lastrowid:
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

    def delete_by_chunk_ids(
        self,
        strategy: str,
        chunk_ids: list[str],
        *,
        conn: sqlite3.Connection,
    ) -> int:
        """Delete vec_meta_* and vec0_* rows for chunk_ids using a caller-supplied conn.

        This variant accepts an explicit connection so the delete runs inside
        the pipeline's transaction (P4 single-transaction purge). Does NOT call
        commit() — the caller owns the transaction boundary.

        Parameters
        ----------
        strategy:
            Strategy name (used to discover all vec_meta_<strategy>_* tables).
        chunk_ids:
            Chunk identifiers to delete.
        conn:
            Open SQLite connection; must be the same one wrapping the caller's
            BEGIN/COMMIT transaction.

        Returns
        -------
        int
            Number of vec rows deleted (across all embedding models for this strategy).
        """
        if not chunk_ids:
            return 0

        placeholders = ",".join("?" for _ in chunk_ids)

        # Discover all vec_meta tables for this strategy (any embedding model).
        vec_meta_tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?",
                (f"vec_meta_{strategy}_%",),
            ).fetchall()
        ]

        total_deleted = 0
        for vm_table in vec_meta_tables:
            vec0_table = "vec_chunks_" + vm_table.removeprefix("vec_meta_")
            rowids = [
                r[0]
                for r in conn.execute(
                    f"SELECT rowid FROM {vm_table} WHERE chunk_id IN ({placeholders})",
                    chunk_ids,
                ).fetchall()
            ]
            if rowids:
                rph = ",".join("?" for _ in rowids)
                try:
                    conn.execute(
                        f"DELETE FROM {vec0_table} WHERE rowid IN ({rph})",
                        rowids,
                    )
                    total_deleted += len(rowids)
                except sqlite3.OperationalError:
                    logger.warning("vec0 delete failed for %s — orphaned rows possible", vec0_table, exc_info=True)
            conn.execute(
                f"DELETE FROM {vm_table} WHERE chunk_id IN ({placeholders})",
                chunk_ids,
            )

        return total_deleted

    def delete_all(self) -> None:
        try:
            conn = self._get_conn()
            conn.execute(f"DROP TABLE IF EXISTS {self._VEC_TABLE}")
            conn.execute(f"DELETE FROM {self._META_TABLE}")
            conn.execute(f"DELETE FROM {self._CONFIG_TABLE}")
            conn.commit()
        except Exception:  # noqa: BLE001
            logger.warning("Failed to delete all vectors", exc_info=True)

    # -- queries ------------------------------------------------------------

    def lookup_embeddings_by_text_hash(
        self,
        text_hashes: list[str],
    ) -> dict[str, list[float]]:
        """Find existing embeddings by text content hash.

        Returns ``{text_hash: embedding}`` for hashes found in vec_meta.
        Used for embedding reuse when switching chunk strategy — same text
        content encoded with the same model produces identical vectors, so
        we can skip re-encoding.

        .. note::

            This requires that ``SELECT embedding FROM <vec0_table> WHERE
            rowid = ?`` works on sqlite-vec virtual tables.  If a future
            sqlite-vec version breaks this, the method will return an empty
            dict (logged as warning) and the pipeline must fall back to
            re-encoding.  This is an acceptable degradation — correctness
            is preserved, only performance is lost.

        Assumes flat (non-context-aware) encoding only.
        """
        if not text_hashes:
            return {}

        conn = self._get_conn()
        if not self._has_index():
            return {}

        result: dict[str, list[float]] = {}
        # Process in batches to stay within SQLite variable limits.
        batch_size = 500
        for i in range(0, len(text_hashes), batch_size):
            batch = text_hashes[i : i + batch_size]
            placeholders = ",".join("?" for _ in batch)
            try:
                rows = conn.execute(
                    f"""
                    SELECT vm.text_hash, vc.embedding
                    FROM {self._META_TABLE} vm
                    JOIN {self._VEC_TABLE} vc ON vm.rowid = vc.rowid
                    WHERE vm.text_hash IN ({placeholders})
                    """,
                    batch,
                ).fetchall()
            except Exception:  # noqa: BLE001
                logger.warning(
                    "lookup_embeddings_by_text_hash failed — vec0 may not "
                    "support direct SELECT on embedding column. "
                    "Pipeline will fall back to re-encoding.",
                    exc_info=True,
                )
                return {}

            for text_hash, embedding_blob in rows:
                if text_hash not in result:
                    # Deserialize binary embedding back to float list.
                    dim = len(embedding_blob) // 4  # 4 bytes per float32
                    result[text_hash] = list(
                        struct.unpack(f"{dim}f", embedding_blob)
                    )

        logger.debug(
            "text_hash lookup: %d requested, %d found",
            len(text_hashes),
            len(result),
        )
        return result

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
    ) -> list[tuple[str, float]]:
        try:
            conn = self._get_conn()
        except Exception:  # noqa: BLE001
            logger.warning("Vector search failed: cannot open connection", exc_info=True)
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
            logger.warning("Vector search query failed", exc_info=True)
            return []

        # distance_metric=cosine → distance is cosine distance (1 - similarity)
        return [(row[0], 1.0 - row[1]) for row in rows]

    def count(self) -> int:
        try:
            conn = self._get_conn()
            return conn.execute(f"SELECT COUNT(*) FROM {self._META_TABLE}").fetchone()[0]
        except Exception:  # noqa: BLE001
            logger.warning("Failed to count vectors", exc_info=True)
            return 0
