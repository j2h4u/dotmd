"""RED test skeletons for P4 — holder-aware purge (DEDUP-08).

Tests cover: single/shared holder cascades, mixed orphans, transactional
rollback, multi-strategy, and graph cleanup failure isolation.

Review-HIGH-P4: atomicity — all DB cascades (M2M + chunks + vec + FTS)
in ONE sqlite3 transaction owned by pipeline.

These tests FAIL at execution time until P4 (wave 4) ships the rewritten
_purge_file. Imports are deferred so --collect-only works before P4 ships.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

STRATEGIES = ["heading_512_50"]
MODEL = "multilingual_e5_large"


def _build_post_v16_db(tmp_path: Path, strategy: str = "heading_512_50") -> Path:
    """Build a post-v16 schema DB with M2M tables for purge tests."""
    db_path = tmp_path / "index.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(f"""
        CREATE TABLE chunks_{strategy} (
            chunk_id TEXT PRIMARY KEY,
            heading_hierarchy TEXT NOT NULL DEFAULT '[]',
            level INTEGER NOT NULL DEFAULT 0,
            text TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE chunk_file_paths_{strategy} (
            chunk_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            PRIMARY KEY (chunk_id, file_path, chunk_index)
        );
        CREATE INDEX idx_chunk_file_paths_{strategy}_file_path
            ON chunk_file_paths_{strategy}(file_path);
        CREATE VIRTUAL TABLE chunks_fts_{strategy} USING fts5(
            chunk_id UNINDEXED, text, tokenize='unicode61'
        );
        CREATE TABLE vec_meta_{strategy}_{MODEL} (
            rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_id TEXT NOT NULL UNIQUE,
            text_hash TEXT
        );
    """)
    conn.commit()
    conn.close()
    return db_path


def _insert_chunk(db_path: Path, strategy: str, chunk_id: str, text: str) -> None:
    """Insert a chunk row into chunks_* + vec_meta_* + chunks_fts_*."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        f"INSERT OR IGNORE INTO chunks_{strategy} (chunk_id, text) VALUES (?, ?)",
        (chunk_id, text),
    )
    conn.execute(
        f"INSERT OR IGNORE INTO vec_meta_{strategy}_{MODEL} (chunk_id) VALUES (?)",
        (chunk_id,),
    )
    conn.execute(
        f"INSERT OR IGNORE INTO chunks_fts_{strategy} (chunk_id, text) VALUES (?, ?)",
        (chunk_id, text),
    )
    conn.commit()
    conn.close()


def _add_m2m(db_path: Path, strategy: str, chunk_id: str, file_path: str, chunk_index: int = 0) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        f"INSERT OR IGNORE INTO chunk_file_paths_{strategy} (chunk_id, file_path, chunk_index) "
        "VALUES (?, ?, ?)",
        (chunk_id, file_path, chunk_index),
    )
    conn.commit()
    conn.close()


def _count(db_path: Path, table: str) -> int:
    conn = sqlite3.connect(str(db_path))
    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    return n


def _get_pipeline(db_path: Path):  # type: ignore[no-untyped-def]
    """Deferred import of IndexingPipeline — raises ImportError until P3/P4 ships."""
    from dotmd.core.config import Settings
    from dotmd.ingestion.pipeline import IndexingPipeline
    settings = Settings(index_dir=db_path.parent)
    return IndexingPipeline(settings)


class TestPurgeSingleHolder:
    """Purging the sole holder cascades the chunk row."""

    def test_purge_single_holder_cascades_chunk(self, tmp_path: Path) -> None:
        """File A is sole holder of chunk X; deleting A removes X from all tables."""
        db_path = _build_post_v16_db(tmp_path)
        strategy = STRATEGIES[0]
        chunk_id = "a" * 64

        _insert_chunk(db_path, strategy, chunk_id, "content")
        _add_m2m(db_path, strategy, chunk_id, "/file_A.md")

        pipeline = _get_pipeline(db_path)
        pipeline._purge_file("/file_A.md")

        assert _count(db_path, f"chunks_{strategy}") == 0
        assert _count(db_path, f"vec_meta_{strategy}_{MODEL}") == 0
        assert _count(db_path, f"chunk_file_paths_{strategy}") == 0


class TestPurgeSharedHolder:
    """Purging one holder of a shared chunk preserves the chunk."""

    def test_purge_shared_holder_preserves_chunk(self, tmp_path: Path) -> None:
        """Files A and B both hold chunk X; deleting A preserves X (still held by B)."""
        db_path = _build_post_v16_db(tmp_path)
        strategy = STRATEGIES[0]
        chunk_id = "b" * 64

        _insert_chunk(db_path, strategy, chunk_id, "shared content")
        _add_m2m(db_path, strategy, chunk_id, "/file_A.md")
        _add_m2m(db_path, strategy, chunk_id, "/file_B.md")

        pipeline = _get_pipeline(db_path)
        pipeline._purge_file("/file_A.md")

        # Chunk survives in chunks_* and vec_meta_*
        assert _count(db_path, f"chunks_{strategy}") == 1
        assert _count(db_path, f"vec_meta_{strategy}_{MODEL}") == 1
        # Only file_A's M2M row removed; file_B's survives
        m2m_rows = sqlite3.connect(str(db_path)).execute(
            f"SELECT file_path FROM chunk_file_paths_{strategy}"
        ).fetchall()
        file_paths = {r[0] for r in m2m_rows}
        assert "/file_B.md" in file_paths
        assert "/file_A.md" not in file_paths


class TestPurgeMixedOrphansAndShared:
    """Purging a file with both sole-held and shared chunks removes only orphans."""

    def test_purge_mixed_orphans_and_shared(self, tmp_path: Path) -> None:
        """File A holds X (solo) and Y (shared with B); deleting A cascades X only."""
        db_path = _build_post_v16_db(tmp_path)
        strategy = STRATEGIES[0]
        cid_x = "c" * 64  # sole-held by A
        cid_y = "d" * 64  # shared by A + B

        _insert_chunk(db_path, strategy, cid_x, "sole content")
        _insert_chunk(db_path, strategy, cid_y, "shared content")
        _add_m2m(db_path, strategy, cid_x, "/file_A.md")
        _add_m2m(db_path, strategy, cid_y, "/file_A.md")
        _add_m2m(db_path, strategy, cid_y, "/file_B.md")

        pipeline = _get_pipeline(db_path)
        pipeline._purge_file("/file_A.md")

        # X is gone, Y survives
        conn = sqlite3.connect(str(db_path))
        surviving_ids = {r[0] for r in conn.execute(
            f"SELECT chunk_id FROM chunks_{strategy}"
        ).fetchall()}
        conn.close()
        assert cid_x not in surviving_ids, "Sole-held chunk should be cascaded"
        assert cid_y in surviving_ids, "Shared chunk should survive"


class TestPurgeIsTransactional:
    """DB purge is fully transactional — failure mid-cascade rolls back everything."""

    def test_purge_is_transactional_on_failure(self, tmp_path: Path) -> None:
        """Injected failure in vec cascade rolls back ALL tables to pre-purge state."""
        db_path = _build_post_v16_db(tmp_path)
        strategy = STRATEGIES[0]
        chunk_id = "e" * 64

        _insert_chunk(db_path, strategy, chunk_id, "content")
        _add_m2m(db_path, strategy, chunk_id, "/file_A.md")

        pre_chunks = _count(db_path, f"chunks_{strategy}")
        pre_m2m = _count(db_path, f"chunk_file_paths_{strategy}")
        pre_vec = _count(db_path, f"vec_meta_{strategy}_{MODEL}")

        pipeline = _get_pipeline(db_path)

        # Inject failure in vector delete (mid-cascade)
        with patch(
            "dotmd.storage.sqlite_vec.SQLiteVecVectorStore.delete_by_chunk_ids",
            side_effect=RuntimeError("Simulated failure in vector cascade"),
        ), pytest.raises(RuntimeError):
            pipeline._purge_file("/file_A.md")

        # All tables restored to pre-purge state
        assert _count(db_path, f"chunks_{strategy}") == pre_chunks
        assert _count(db_path, f"chunk_file_paths_{strategy}") == pre_m2m
        assert _count(db_path, f"vec_meta_{strategy}_{MODEL}") == pre_vec


class TestPurgeRunsAcrossAllStrategies:
    """Purge covers all strategies in a single transaction."""

    def test_purge_runs_across_all_strategies(self, tmp_path: Path) -> None:
        """File with chunks in two strategies — both strategies cleaned in one purge call."""
        db_path = tmp_path / "index.db"
        strategies = ["heading_512_50", "contextual_512_50"]
        conn = sqlite3.connect(str(db_path))
        for s in strategies:
            conn.executescript(f"""
                CREATE TABLE IF NOT EXISTS chunks_{s} (
                    chunk_id TEXT PRIMARY KEY, text TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS chunk_file_paths_{s} (
                    chunk_id TEXT NOT NULL, file_path TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    PRIMARY KEY (chunk_id, file_path, chunk_index)
                );
                CREATE TABLE IF NOT EXISTS vec_meta_{s}_{MODEL} (
                    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                    chunk_id TEXT NOT NULL UNIQUE, text_hash TEXT
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts_{s} USING fts5(
                    chunk_id UNINDEXED, text, tokenize='unicode61'
                );
            """)
        conn.commit()
        conn.close()

        for s in strategies:
            cid = ("a" if s == "heading_512_50" else "b") * 64
            _insert_chunk(db_path, s, cid, "content")
            _add_m2m(db_path, s, cid, "/file_A.md")

        pipeline = _get_pipeline(db_path)
        pipeline._purge_file("/file_A.md")

        for s in strategies:
            assert _count(db_path, f"chunks_{s}") == 0, (
                f"chunks_{s} not cleaned after purge"
            )
            assert _count(db_path, f"chunk_file_paths_{s}") == 0, (
                f"chunk_file_paths_{s} not cleaned after purge"
            )


class TestGraphCleanupFailureDoesNotRollbackDB:
    """Graph cleanup failure after DB commit does not undo DB changes (best-effort)."""

    def test_graph_cleanup_failure_does_not_rollback_db(
        self, tmp_path: Path
    ) -> None:
        """graph_store failure after DB commit: DB purge persisted, failure logged."""
        db_path = _build_post_v16_db(tmp_path)
        strategy = STRATEGIES[0]
        chunk_id = "f" * 64

        _insert_chunk(db_path, strategy, chunk_id, "content")
        _add_m2m(db_path, strategy, chunk_id, "/file_A.md")

        pipeline = _get_pipeline(db_path)

        # Inject graph failure AFTER DB commit
        with patch.object(
            pipeline._graph_store,
            "delete_file_subgraph",
            side_effect=RuntimeError("Simulated graph failure"),
        ):
            # Should NOT raise (graph failure is best-effort)
            pipeline._purge_file("/file_A.md")

        # DB purge must have persisted despite graph failure
        assert _count(db_path, f"chunks_{strategy}") == 0, (
            "DB purge must persist even when graph cleanup fails"
        )


class TestGraphHolderAwarePath:
    """When graph audit flags unsafe, holder-aware path preserves shared MENTIONS edges."""

    def test_graph_holder_aware_path_when_audit_flags_unsafe(
        self, tmp_path: Path
    ) -> None:
        """Shared chunk's graph artefacts survive when only one holder is purged."""
        # This test validates the holder-aware path described in P4 Task 1 branch (b).
        # It intentionally invokes purge with a shared chunk and asserts that the
        # graph store's narrow helper (delete_chunks_from_graph) is NOT called for
        # the shared chunk (it's still held by another file).
        db_path = _build_post_v16_db(tmp_path)
        strategy = STRATEGIES[0]
        shared_cid = "g" * 64

        _insert_chunk(db_path, strategy, shared_cid, "shared")
        _add_m2m(db_path, strategy, shared_cid, "/file_A.md")
        _add_m2m(db_path, strategy, shared_cid, "/file_B.md")

        pipeline = _get_pipeline(db_path)
        delete_calls = []

        # Spy on graph narrow helpers to assert they are NOT called for shared chunks
        if hasattr(pipeline._graph_store, "delete_chunks_from_graph"):
            original = pipeline._graph_store.delete_chunks_from_graph

            def spy_delete(chunk_ids, *args, **kwargs):  # type: ignore[no-untyped-def]
                delete_calls.extend(chunk_ids)
                return original(chunk_ids, *args, **kwargs)

            pipeline._graph_store.delete_chunks_from_graph = spy_delete

        pipeline._purge_file("/file_A.md")

        # shared_cid must NOT appear in graph delete calls (still held by B)
        assert shared_cid not in delete_calls, (
            f"Shared chunk {shared_cid!r} should not be removed from graph (still held by /file_B.md)"
        )
