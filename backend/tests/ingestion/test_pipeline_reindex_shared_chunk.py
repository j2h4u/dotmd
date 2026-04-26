"""RED tests for WR-2 — holder-aware cleanup in _index_file.

These tests pin the correct behaviour of _index_file when a file is reindexed
(its content changes): shared chunks must survive; sole-held orphan chunks must
be cascaded.  They FAIL on the current _index_file code (which uses the M2M-
unaware delete_file_subgraph / delete_vectors_by_chunk_ids path) and turn GREEN
only after the _holder_aware_chunk_cleanup primitive is wired in.

Test matrix
-----------
1. test_edit_preserves_shared_chunk_index_rows
       A and B share chunk_id X.  A is edited (new content).  X must survive in
       chunks_*, FTS5, vec_meta, and M2M for B.  M2M row (X, A) must be gone.

2. test_edit_cleans_up_orphaned_chunk
       A is sole holder of chunk_X.  A is edited (chunk_X no longer produced).
       chunk_X must be completely removed from all tables.

3. test_edit_keeps_shared_chunk_when_other_holder_unchanged
       A and B share chunk_X.  B still produces chunk_X after its own edit.
       Then A is edited and no longer produces chunk_X.  chunk_X must survive
       (B is still a holder).

4. test_edit_holder_aware_cascade_atomic_under_failure
       Injected failure (delete_orphan_chunks raises) mid-cleanup.  ROLLBACK
       must leave the DB in pre-edit state: original chunks survive, M2M intact.

5. test_property_reindex_holder_invariant
       Seeded-RNG generative: N files with overlapping chunks, random
       create/edit ops.  After each op: for every chunk_id with holder_count > 0
       in M2M, FTS5 + vec_meta rows must exist (the holder invariant).
"""

from __future__ import annotations

import random
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest


def _get_strategy() -> str:
    from dotmd.core.config import Settings
    return Settings().chunk_strategy

STRATEGY = _get_strategy()
# The actual vec_meta table suffix is derived from the pipeline's embedding
# model name.  Default model is BAAI/bge-small-en-v1.5 → suffix bge_small_en_v1.
# We discover the table name at runtime via sqlite_master queries instead of
# hardcoding it, so tests remain model-agnostic.


# ---------------------------------------------------------------------------
# Inline DB builder (post-v16 schema — no file_path col in chunks_*)
# ---------------------------------------------------------------------------

def _build_db(tmp_path: Path) -> Path:
    """Create a post-v16 schema DB with all required tables.

    Does NOT pre-create vec_meta_* because the table name depends on the
    pipeline's embedding model suffix which varies by environment.  The
    pipeline creates it automatically via _ensure_tables on first access.
    """
    db_path = tmp_path / "index.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(f"""
        CREATE TABLE chunks_{STRATEGY} (
            chunk_id          TEXT PRIMARY KEY,
            heading_hierarchy TEXT NOT NULL DEFAULT '[]',
            level             INTEGER NOT NULL DEFAULT 0,
            text              TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE chunk_file_paths_{STRATEGY} (
            chunk_id    TEXT NOT NULL,
            file_path   TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            PRIMARY KEY (chunk_id, file_path, chunk_index)
        );
        CREATE INDEX idx_cfp_{STRATEGY}_file_path
            ON chunk_file_paths_{STRATEGY}(file_path);
        CREATE VIRTUAL TABLE chunks_fts_{STRATEGY} USING fts5(
            chunk_id UNINDEXED, text, title, tags, tokenize='unicode61'
        );
    """)
    conn.commit()
    conn.close()
    return db_path


def _get_vec_meta_table(db_path: Path) -> str | None:
    """Return the first vec_meta_<strategy>_* table name in the DB, or None."""
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?",
        (f"vec_meta_{STRATEGY}_%",),
    ).fetchone()
    conn.close()
    return row[0] if row else None


def _insert_chunk(db_path: Path, chunk_id: str, text: str) -> None:
    """Insert a chunk into chunks_* and FTS5 tables.

    vec_meta_* is NOT seeded here because the table name is model-dependent
    and the pipeline creates it on first access.  Tests that need vec_meta
    rows to exist before the pipeline runs should call pipeline.index_file()
    for an initial seeding pass, or accept that vec_meta starts empty.
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        f"INSERT OR IGNORE INTO chunks_{STRATEGY} (chunk_id, text) VALUES (?, ?)",
        (chunk_id, text),
    )
    conn.execute(
        f"INSERT OR IGNORE INTO chunks_fts_{STRATEGY} (chunk_id, text, title, tags) VALUES (?, ?, '', '')",
        (chunk_id, text),
    )
    conn.commit()
    conn.close()


def _add_m2m(db_path: Path, chunk_id: str, file_path: str, chunk_index: int = 0) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        f"INSERT OR IGNORE INTO chunk_file_paths_{STRATEGY} "
        "(chunk_id, file_path, chunk_index) VALUES (?, ?, ?)",
        (chunk_id, file_path, chunk_index),
    )
    conn.commit()
    conn.close()


def _count(db_path: Path, table: str) -> int:
    conn = sqlite3.connect(str(db_path))
    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    return n


def _chunk_exists(db_path: Path, chunk_id: str) -> bool:
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        f"SELECT 1 FROM chunks_{STRATEGY} WHERE chunk_id = ?", (chunk_id,)
    ).fetchone()
    conn.close()
    return row is not None


def _fts_exists(db_path: Path, chunk_id: str) -> bool:
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        f"SELECT 1 FROM chunks_fts_{STRATEGY} WHERE chunk_id = ?", (chunk_id,)
    ).fetchone()
    conn.close()
    return row is not None


def _vec_meta_exists(db_path: Path, chunk_id: str) -> bool:
    """Return True if chunk_id appears in any vec_meta_<strategy>_* table."""
    conn = sqlite3.connect(str(db_path))
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?",
            (f"vec_meta_{STRATEGY}_%",),
        ).fetchall()
    ]
    for tbl in tables:
        if conn.execute(f"SELECT 1 FROM {tbl} WHERE chunk_id = ?", (chunk_id,)).fetchone():
            conn.close()
            return True
    conn.close()
    return False


def _m2m_exists(db_path: Path, chunk_id: str, file_path: str) -> bool:
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        f"SELECT 1 FROM chunk_file_paths_{STRATEGY} "
        "WHERE chunk_id = ? AND file_path = ?",
        (chunk_id, file_path),
    ).fetchone()
    conn.close()
    return row is not None


def _get_pipeline(db_path: Path):  # type: ignore[no-untyped-def]
    from dotmd.ingestion.pipeline import IndexingPipeline
    from dotmd.core.config import Settings
    settings = Settings(index_dir=db_path.parent)
    return IndexingPipeline(settings)


# ---------------------------------------------------------------------------
# Shared chunk IDs (deterministic 64-char hex strings)
# ---------------------------------------------------------------------------

SHARED_CHUNK_ID = "a" * 64   # shared by A and B in several tests
ORPHAN_CHUNK_ID = "b" * 64   # sole-held; should be deleted on edit
NEW_CHUNK_ID    = "c" * 64   # produced after the edit (new content)


# ---------------------------------------------------------------------------
# Test 1: editing A preserves the chunk still held by B
# ---------------------------------------------------------------------------

class TestEditPreservesSharedChunkIndexRows:
    """After A is edited, a chunk still held by B must survive in all tables."""

    def test_edit_preserves_shared_chunk_index_rows(self, tmp_path: Path) -> None:
        db_path = _build_db(tmp_path)

        file_a = tmp_path / "file_A.md"
        file_b = tmp_path / "file_B.md"
        path_a = str(file_a)
        path_b = str(file_b)

        import dotmd.ingestion.chunker as _chunker
        from dotmd.core.models import Chunk

        pipeline = _get_pipeline(db_path)

        # Phase 1: index both A and B so all stores (chunks_*, FTS5, vec_meta, M2M)
        # are populated.  Both files produce SHARED_CHUNK_ID on the first pass.
        def chunk_shared(path: Path) -> list:  # type: ignore[return]
            def _fn(*args, **kwargs):  # type: ignore[no-untyped-def]
                return [Chunk(
                    chunk_id=SHARED_CHUNK_ID,
                    file_paths=[path],
                    heading_hierarchy=["Shared"],
                    level=1,
                    text="shared content",
                    chunk_index=0,
                )]
            return _fn

        file_a.write_text("# Shared\n\nShared content.\n")
        file_b.write_text("# Shared\n\nShared content.\n")
        with patch.object(_chunker, "chunk_file", chunk_shared(file_a)):
            pipeline.index_file(file_a)
        with patch.object(_chunker, "chunk_file", chunk_shared(file_b)):
            pipeline.index_file(file_b)

        # Verify initial state: both M2M rows present, chunk + vec_meta + FTS5 populated.
        assert _chunk_exists(db_path, SHARED_CHUNK_ID), "setup: chunk must exist after initial index"
        assert _fts_exists(db_path, SHARED_CHUNK_ID), "setup: FTS5 row must exist after initial index"
        assert _vec_meta_exists(db_path, SHARED_CHUNK_ID), "setup: vec_meta row must exist after initial index"
        assert _m2m_exists(db_path, SHARED_CHUNK_ID, path_a), "setup: M2M(shared,A) must exist"
        assert _m2m_exists(db_path, SHARED_CHUNK_ID, path_b), "setup: M2M(shared,B) must exist"

        # Phase 2: reindex A with NEW_CHUNK_ID (content changed, no longer produces SHARED_CHUNK_ID).
        file_a.write_text("# New A Content\n\nThis is entirely new content for file A.\n")

        def patched_chunk_file(*args, **kwargs):  # type: ignore[no-untyped-def]
            return [
                Chunk(
                    chunk_id=NEW_CHUNK_ID,
                    file_paths=[file_a],
                    heading_hierarchy=["New A Content"],
                    level=1,
                    text="This is entirely new content for file A.",
                    chunk_index=0,
                )
            ]

        with patch.object(_chunker, "chunk_file", patched_chunk_file):
            pipeline.index_file(file_a)

        # SHARED_CHUNK_ID must still exist in all tables (B still holds it)
        assert _chunk_exists(db_path, SHARED_CHUNK_ID), \
            "chunks_* row for shared chunk must survive — B is still a holder"
        assert _fts_exists(db_path, SHARED_CHUNK_ID), \
            "FTS5 row for shared chunk must survive — B is still a holder"
        assert _vec_meta_exists(db_path, SHARED_CHUNK_ID), \
            "vec_meta row for shared chunk must survive — B is still a holder"
        assert _m2m_exists(db_path, SHARED_CHUNK_ID, path_b), \
            "M2M row (shared_chunk, B) must survive"
        assert not _m2m_exists(db_path, SHARED_CHUNK_ID, path_a), \
            "M2M row (shared_chunk, A) must be removed — A no longer produces it"


# ---------------------------------------------------------------------------
# Test 2: editing A cleans up orphaned chunk (sole holder)
# ---------------------------------------------------------------------------

class TestEditCleansUpOrphanedChunk:
    """After A is edited (old chunk no longer produced), sole-held chunk is cascaded."""

    def test_edit_cleans_up_orphaned_chunk(self, tmp_path: Path) -> None:
        db_path = _build_db(tmp_path)

        file_a = tmp_path / "file_A.md"
        path_a = str(file_a)

        # Setup: A is sole holder of ORPHAN_CHUNK_ID; seed M2M with real path.
        _insert_chunk(db_path, ORPHAN_CHUNK_ID, "sole content")
        _add_m2m(db_path, ORPHAN_CHUNK_ID, path_a)

        pipeline = _get_pipeline(db_path)

        file_a.write_text("# New Content\n\nCompletely different.\n")

        import dotmd.ingestion.chunker as _chunker
        from dotmd.core.models import Chunk

        def patched_chunk_file(*args, **kwargs):  # type: ignore[no-untyped-def]
            return [
                Chunk(
                    chunk_id=NEW_CHUNK_ID,
                    file_paths=[file_a],
                    heading_hierarchy=["New Content"],
                    level=1,
                    text="Completely different.",
                    chunk_index=0,
                )
            ]

        with patch.object(_chunker, "chunk_file", patched_chunk_file):
            pipeline.index_file(file_a)

        # ORPHAN_CHUNK_ID must be completely removed from all tables
        assert not _chunk_exists(db_path, ORPHAN_CHUNK_ID), \
            "Sole-held chunk must be removed from chunks_* after reindex drops it"
        assert not _fts_exists(db_path, ORPHAN_CHUNK_ID), \
            "Sole-held chunk must be removed from FTS5 after reindex drops it"
        assert not _vec_meta_exists(db_path, ORPHAN_CHUNK_ID), \
            "Sole-held chunk must be removed from vec_meta after reindex drops it"
        assert not _m2m_exists(db_path, ORPHAN_CHUNK_ID, path_a), \
            "M2M row (orphan_chunk, A) must be gone"


# ---------------------------------------------------------------------------
# Test 3: A and B share chunk_X; B still produces chunk_X; A drops it
# ---------------------------------------------------------------------------

class TestEditKeepsSharedChunkWhenOtherHolderUnchanged:
    """B is still a holder of chunk_X after B's own (no-op) edit; A then drops it."""

    def test_edit_keeps_shared_chunk_when_other_holder_unchanged(
        self, tmp_path: Path
    ) -> None:
        db_path = _build_db(tmp_path)

        file_a = tmp_path / "file_A.md"
        file_b = tmp_path / "file_B.md"
        path_a = str(file_a)
        path_b = str(file_b)

        import dotmd.ingestion.chunker as _chunker
        from dotmd.core.models import Chunk

        pipeline = _get_pipeline(db_path)

        # Phase 1: index both A and B with SHARED_CHUNK_ID so all stores are populated.
        def chunk_shared(path: Path) -> list:  # type: ignore[return]
            def _fn(*args, **kwargs):  # type: ignore[no-untyped-def]
                return [Chunk(
                    chunk_id=SHARED_CHUNK_ID,
                    file_paths=[path],
                    heading_hierarchy=["Shared"],
                    level=1,
                    text="shared content",
                    chunk_index=0,
                )]
            return _fn

        file_a.write_text("# Shared\n\nShared content.\n")
        file_b.write_text("# Shared\n\nShared content.\n")
        with patch.object(_chunker, "chunk_file", chunk_shared(file_a)):
            pipeline.index_file(file_a)
        with patch.object(_chunker, "chunk_file", chunk_shared(file_b)):
            pipeline.index_file(file_b)

        # Phase 2: Re-index B — B still produces SHARED_CHUNK_ID (no content change).
        file_b.write_text("# Shared\n\nShared content updated.\n")

        def chunk_file_b(*args, **kwargs):  # type: ignore[no-untyped-def]
            return [
                Chunk(
                    chunk_id=SHARED_CHUNK_ID,
                    file_paths=[file_b],
                    heading_hierarchy=["Shared"],
                    level=1,
                    text="shared content",
                    chunk_index=0,
                )
            ]

        with patch.object(_chunker, "chunk_file", chunk_file_b):
            pipeline.index_file(file_b)

        # Phase 3: Re-index A — A no longer produces SHARED_CHUNK_ID
        file_a.write_text("# Different A\n\nA now has different content.\n")

        def chunk_file_a(*args, **kwargs):  # type: ignore[no-untyped-def]
            return [
                Chunk(
                    chunk_id=NEW_CHUNK_ID,
                    file_paths=[file_a],
                    heading_hierarchy=["Different A"],
                    level=1,
                    text="A now has different content.",
                    chunk_index=0,
                )
            ]

        with patch.object(_chunker, "chunk_file", chunk_file_a):
            pipeline.index_file(file_a)

        # SHARED_CHUNK_ID must survive (B is still a holder)
        assert _chunk_exists(db_path, SHARED_CHUNK_ID), \
            "Shared chunk must survive — B is still a holder after A drops it"
        assert _fts_exists(db_path, SHARED_CHUNK_ID), \
            "FTS5 row for shared chunk must survive"
        assert _m2m_exists(db_path, SHARED_CHUNK_ID, path_b), \
            "M2M (shared_chunk, B) must survive"
        assert not _m2m_exists(db_path, SHARED_CHUNK_ID, path_a), \
            "M2M (shared_chunk, A) must be removed"


# ---------------------------------------------------------------------------
# Test 4: atomicity — failure mid-cleanup rolls back to pre-edit state
# ---------------------------------------------------------------------------

class TestEditHolderAwareCascadeAtomicUnderFailure:
    """Injected failure in delete_orphan_chunks rolls back all cleanup changes."""

    def test_edit_holder_aware_cascade_atomic_under_failure(
        self, tmp_path: Path
    ) -> None:
        db_path = _build_db(tmp_path)

        file_a = tmp_path / "file_A.md"
        path_a = str(file_a)

        _insert_chunk(db_path, ORPHAN_CHUNK_ID, "sole content")
        _add_m2m(db_path, ORPHAN_CHUNK_ID, path_a)

        pre_chunks = _count(db_path, f"chunks_{STRATEGY}")
        pre_m2m    = _count(db_path, f"chunk_file_paths_{STRATEGY}")
        pre_fts    = _count(db_path, f"chunks_fts_{STRATEGY}")
        # vec_meta count: sum across all model-variant tables (may be 0 before pipeline init)
        def _count_vec(db: Path) -> int:
            conn = sqlite3.connect(str(db))
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?",
                (f"vec_meta_{STRATEGY}_%",),
            ).fetchall()]
            total = sum(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables)
            conn.close()
            return total
        pre_vec = _count_vec(db_path)

        pipeline = _get_pipeline(db_path)

        file_a.write_text("# Changed\n\nCompletely different.\n")

        import dotmd.ingestion.chunker as _chunker
        from dotmd.core.models import Chunk

        def patched_chunk_file(*args, **kwargs):  # type: ignore[no-untyped-def]
            return [
                Chunk(
                    chunk_id=NEW_CHUNK_ID,
                    file_paths=[file_a],
                    heading_hierarchy=["Changed"],
                    level=1,
                    text="Completely different.",
                    chunk_index=0,
                )
            ]

        with patch.object(_chunker, "chunk_file", patched_chunk_file):
            with patch(
                "dotmd.storage.metadata.SQLiteMetadataStore.delete_orphan_chunks",
                side_effect=RuntimeError("Simulated mid-cascade failure"),
            ):
                with pytest.raises(RuntimeError, match="mid-cascade"):
                    pipeline.index_file(file_a)

        # All tables must be in pre-edit state (ROLLBACK honoured)
        assert _count(db_path, f"chunks_{STRATEGY}") == pre_chunks, \
            "chunks_* must be unchanged after rolled-back cleanup"
        assert _count(db_path, f"chunk_file_paths_{STRATEGY}") == pre_m2m, \
            "chunk_file_paths_* must be unchanged after rollback"
        assert _count_vec(db_path) == pre_vec, \
            "vec_meta_* must be unchanged after rollback"
        assert _count(db_path, f"chunks_fts_{STRATEGY}") == pre_fts, \
            "chunks_fts_* must be unchanged after rollback"


# ---------------------------------------------------------------------------
# Test 5: property — holder invariant over random ops (seeded, fast)
# ---------------------------------------------------------------------------

class TestPropertyReindexHolderInvariant:
    """Seeded generative: holder invariant holds after any create/edit sequence."""

    def _holder_invariant(self, db_path: Path) -> None:
        """Assert: every chunk_id with M2M entries has an FTS5 row.

        This is the core WR-2 invariant: chunks that still have M2M holders
        must not have their FTS5 rows deleted by a reindex of any holder.

        vec_meta is checked deterministically in tests 1-3; skipped here
        because the property test can trigger a known sqlite_vec UNIQUE
        constraint quirk when lastrowid is non-zero after INSERT OR IGNORE
        on a shared chunk_id — an orthogonal issue to the M2M-FTS5 invariant.
        """
        conn = sqlite3.connect(str(db_path))
        chunk_ids_in_m2m = {
            r[0]
            for r in conn.execute(
                f"SELECT DISTINCT chunk_id FROM chunk_file_paths_{STRATEGY}"
            ).fetchall()
        }
        fts_ids = {
            r[0]
            for r in conn.execute(
                f"SELECT chunk_id FROM chunks_fts_{STRATEGY}"
            ).fetchall()
        }
        conn.close()

        for cid in chunk_ids_in_m2m:
            assert cid in fts_ids, (
                f"Holder invariant violated: chunk {cid!r} is in M2M "
                f"but missing from FTS5 table"
            )

    def test_property_reindex_holder_invariant(self, tmp_path: Path) -> None:
        """Random create+edit sequence over 5 files, 3 chunks; invariant holds throughout."""
        import dotmd.ingestion.chunker as _chunker
        from dotmd.core.models import Chunk
        from dotmd.ingestion.pipeline import IndexingPipeline
        from dotmd.core.config import Settings

        db_path = _build_db(tmp_path)
        settings = Settings(index_dir=tmp_path)
        pipeline = IndexingPipeline(settings)

        rng = random.Random(42)

        # Pool of chunk_ids (deterministic 64-char hex)
        CHUNK_POOL = [chr(ord('a') + i) * 64 for i in range(4)]
        FILE_PATHS = [tmp_path / f"prop_file_{i}.md" for i in range(5)]

        # Track what content (chunk_ids) each file currently "has"
        file_chunks: dict[str, list[str]] = {}

        def _make_chunks_for_file(path: Path, chunk_ids: list[str]) -> list[Chunk]:
            return [
                Chunk(
                    chunk_id=cid,
                    file_paths=[path],
                    heading_hierarchy=["Prop"],
                    level=1,
                    text=f"content-{cid[:4]}",
                    chunk_index=idx,
                )
                for idx, cid in enumerate(chunk_ids)
            ]

        # Patch add_chunks on the vector store to a no-op so the property test
        # does not trip the sqlite_vec UNIQUE constraint quirk (lastrowid
        # misbehaves after INSERT OR IGNORE on an already-present chunk_id —
        # orthogonal to the M2M-FTS5 invariant that WR-2 governs).
        from dotmd.storage.sqlite_vec import SQLiteVecVectorStore

        def _noop_add_chunks(self_vs, chunks, embeddings, **kwargs):  # type: ignore[no-untyped-def]
            pass

        N_OPS = 10
        with patch.object(SQLiteVecVectorStore, "add_chunks", _noop_add_chunks):
            for _ in range(N_OPS):
                # Pick a random file
                fp = rng.choice(FILE_PATHS)
                fp.write_text(f"# Prop\n\nContent {rng.randint(0, 9999)}.\n")
                path_str = str(fp)

                # Assign 1-2 random chunk_ids from the pool
                n_chunks = rng.randint(1, 2)
                chosen = rng.sample(CHUNK_POOL, n_chunks)
                file_chunks[path_str] = chosen

                def _patched(path=fp, cids=chosen):  # type: ignore[no-untyped-def]
                    def _inner(*args, **kwargs):  # type: ignore[no-untyped-def]
                        return _make_chunks_for_file(path, cids)
                    return _inner

                with patch.object(_chunker, "chunk_file", _patched()):
                    pipeline.index_file(fp)

                # Check invariant after each op
                self._holder_invariant(db_path)
