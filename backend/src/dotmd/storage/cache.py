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

import json
import logging

import blake3
import sqlite3
import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dotmd.core.models import Chunk

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


class ExtractionCache:
    """Per-chunk extraction cache keyed on (chunk_text, model_name, entity_types, threshold).

    Stores only chunk-id-independent data:
    - entities_json: [{name, type, source}] — no chunk_ids field
    - co_occurs_json: [{source_id: entity_name, target_id: entity_name,
                        relation_type: "CO_OCCURS", weight: 1.0}]

    MENTIONS relations (source_id = chunk_id) are NEVER stored.
    They are rebuilt at read time using the current chunk.chunk_id.

    Invalidation: full table clear when model_sig changes.
    model_sig = blake3(model_name + entity_types_hash + str(threshold)).hexdigest()
    """

    _BATCH = 500  # max placeholders per IN-clause

    def __init__(
        self,
        conn: sqlite3.Connection,
        model_name: str,
        entity_types: list[str],
        threshold: float,
    ) -> None:
        self._conn = conn
        self._model_name = model_name
        self._threshold = threshold
        self._entity_types_hash = blake3.blake3(
            ",".join(sorted(entity_types)).encode()
        ).hexdigest()
        self._model_sig = blake3.blake3(
            (model_name + self._entity_types_hash + str(threshold)).encode()
        ).hexdigest()
        self.ensure_table()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def ensure_table(self) -> None:
        """Create cache tables if they do not already exist.

        Does NOT write or read extraction_cache_meta. Table creation is
        separate from sentinel management.
        """
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS extraction_cache (
                cache_key    TEXT PRIMARY KEY,
                entities_json  TEXT NOT NULL,
                co_occurs_json TEXT NOT NULL,
                created_at   TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS extraction_cache_meta (
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
        """Return True if the stored model_sig sentinel differs from the current sig.

        Returns False on a fresh table (no sentinel row yet) — first run,
        no previous state to invalidate.
        """
        row = self._conn.execute(
            "SELECT value FROM extraction_cache_meta WHERE key = 'model_sig'"
        ).fetchone()
        if row is None:
            return False
        return row[0] != self._model_sig

    def clear(self) -> None:
        """Wipe all cached extraction results and write the new model_sig sentinel."""
        self._conn.execute("DELETE FROM extraction_cache")
        self._conn.execute("DELETE FROM extraction_cache_meta")
        self._conn.execute(
            "INSERT OR REPLACE INTO extraction_cache_meta VALUES ('model_sig', ?)",
            (self._model_sig,),
        )
        self._conn.commit()

    def update_model_sig(self) -> None:
        """Write (or confirm) the current model_sig into the meta table.

        Called after should_invalidate() returns False to confirm the sentinel.
        """
        self._conn.execute(
            "INSERT OR REPLACE INTO extraction_cache_meta VALUES ('model_sig', ?)",
            (self._model_sig,),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Key derivation
    # ------------------------------------------------------------------

    def _make_key(self, chunk_text: str) -> str:
        """Derive a cache key from raw chunk text + model signature.

        Uses raw chunk.text — NOT the pipeline's text_hash (which is for
        enriched text). This is correct because GLiNER runs on raw text.
        """
        chunk_text_hash = blake3.blake3(chunk_text.encode()).hexdigest()
        return blake3.blake3(
            (chunk_text_hash + self._model_sig).encode()
        ).hexdigest()

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def lookup_batch(
        self, chunks: list[Chunk]
    ) -> tuple[dict[str, tuple[list, list]], list[Chunk]]:
        """Look up a batch of chunks in the extraction cache.

        Parameters
        ----------
        chunks:
            Chunks to look up.

        Returns
        -------
        tuple[dict, list]
            ``(hits_dict, miss_chunks)`` where:
            - hits_dict maps chunk_id → (entities_raw, co_occurs_raw)
            - miss_chunks is the list of Chunk objects not found in cache
        """
        if not chunks:
            return {}, []

        # Build key → chunk_id mapping
        key_to_chunk: dict[str, Chunk] = {}
        for chunk in chunks:
            key = self._make_key(chunk.text)
            key_to_chunk[key] = chunk

        all_keys = list(key_to_chunk.keys())
        found_keys: dict[str, tuple[list, list]] = {}  # cache_key → (ents, co_occurs)

        try:
            for i in range(0, len(all_keys), self._BATCH):
                batch = all_keys[i : i + self._BATCH]
                placeholders = ",".join("?" * len(batch))
                rows = self._conn.execute(
                    f"SELECT cache_key, entities_json, co_occurs_json"
                    f" FROM extraction_cache WHERE cache_key IN ({placeholders})",
                    batch,
                ).fetchall()
                for cache_key, entities_json, co_occurs_json in rows:
                    found_keys[cache_key] = (
                        json.loads(entities_json),
                        json.loads(co_occurs_json),
                    )
        except Exception:
            logger.warning(
                "extraction_cache lookup failed — returning empty (graceful degradation)",
                exc_info=True,
            )
            return {}, list(chunks)

        # Build results: map chunk_id for hits, collect misses
        hits_dict: dict[str, tuple[list, list]] = {}
        miss_chunks: list[Chunk] = []

        for key, chunk in key_to_chunk.items():
            if key in found_keys:
                hits_dict[chunk.chunk_id] = found_keys[key]
            else:
                miss_chunks.append(chunk)

        return hits_dict, miss_chunks

    # ------------------------------------------------------------------
    # Store
    # ------------------------------------------------------------------

    def store_batch(
        self,
        chunks: list[Chunk],
        results_per_chunk: dict[str, tuple[list, list]],
    ) -> None:
        """Persist extraction results for a batch of chunks.

        Parameters
        ----------
        chunks:
            Chunks whose results are being stored.
        results_per_chunk:
            Mapping of chunk_id → (entities_raw, co_occurs_raw).
            entities_raw: list[dict] with keys {name, type, source} (NO chunk_ids).
            co_occurs_raw: list[dict] CO_OCCURS relations only (no MENTIONS).

        Uses INSERT OR IGNORE so re-storing an existing key is a no-op.
        Does NOT commit — caller commits.
        """
        for chunk in chunks:
            chunk_id = chunk.chunk_id
            if chunk_id not in results_per_chunk:
                continue
            entities_raw, co_occurs_raw = results_per_chunk[chunk_id]
            cache_key = self._make_key(chunk.text)
            self._conn.execute(
                "INSERT OR IGNORE INTO extraction_cache"
                " (cache_key, entities_json, co_occurs_json) VALUES (?, ?, ?)",
                (
                    cache_key,
                    json.dumps(entities_raw),
                    json.dumps(co_occurs_raw),
                ),
            )
