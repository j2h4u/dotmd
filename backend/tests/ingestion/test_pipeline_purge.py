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

from dotmd.ingestion.surreal_delta_sync import (
    FakeSurrealDeltaWriter,
    SurrealDeltaSyncState,
    run_surreal_delta_sync,
)

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
            chunk_id UNINDEXED, text, title, tags, tokenize='unicode61'
        );
        CREATE TABLE vec_meta_{strategy}_{MODEL} (
            rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_id TEXT NOT NULL UNIQUE,
            text_hash TEXT
        );
        CREATE TABLE source_documents (
            namespace TEXT NOT NULL,
            document_ref TEXT NOT NULL,
            ref TEXT NOT NULL,
            source_uri TEXT NOT NULL,
            file_path TEXT,
            media_type TEXT NOT NULL,
            parser_name TEXT NOT NULL,
            document_type TEXT NOT NULL,
            title TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            content_fingerprint TEXT NOT NULL,
            metadata_fingerprint TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{{}}',
            PRIMARY KEY (namespace, document_ref)
        );
        CREATE TABLE resource_bindings (
            namespace TEXT NOT NULL,
            resource_ref TEXT NOT NULL,
            document_ref TEXT NOT NULL,
            ref TEXT NOT NULL,
            active INTEGER NOT NULL,
            bound_at TEXT NOT NULL,
            unbound_at TEXT,
            content_fingerprint TEXT NOT NULL,
            metadata_fingerprint TEXT NOT NULL,
            source_unit_refs TEXT NOT NULL DEFAULT '[]',
            metadata_json TEXT NOT NULL DEFAULT '{{}}',
            PRIMARY KEY (namespace, resource_ref)
        );
        CREATE TABLE chunk_source_provenance_{strategy} (
            chunk_id TEXT NOT NULL,
            namespace TEXT NOT NULL,
            document_ref TEXT NOT NULL,
            source_unit_refs TEXT NOT NULL,
            chunk_strategy TEXT NOT NULL,
            parser_name TEXT,
            PRIMARY KEY (chunk_id, namespace, document_ref)
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


def _add_m2m(
    db_path: Path, strategy: str, chunk_id: str, file_path: str, chunk_index: int = 0
) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        f"INSERT OR IGNORE INTO chunk_file_paths_{strategy} (chunk_id, file_path, chunk_index) "
        "VALUES (?, ?, ?)",
        (chunk_id, file_path, chunk_index),
    )
    conn.commit()
    conn.close()


def _add_source_document(db_path: Path, file_path: str) -> None:
    document_ref = str(Path(file_path).resolve())
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT OR REPLACE INTO source_documents ("
        "namespace, document_ref, ref, source_uri, file_path, media_type, "
        "parser_name, document_type, title, updated_at, content_fingerprint, "
        "metadata_fingerprint, metadata_json"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "filesystem",
            document_ref,
            f"filesystem:{document_ref}",
            document_ref,
            file_path,
            "text/markdown",
            "markdown",
            "document",
            Path(file_path).stem,
            "2026-05-05T00:00:00+00:00",
            "content",
            "metadata",
            "{}",
        ),
    )
    conn.commit()
    conn.close()


def _add_resource_binding(db_path: Path, file_path: str) -> None:
    document_ref = str(Path(file_path).resolve())
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT OR REPLACE INTO resource_bindings ("
        "namespace, resource_ref, document_ref, ref, active, bound_at, "
        "unbound_at, content_fingerprint, metadata_fingerprint, source_unit_refs, "
        "metadata_json"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "filesystem",
            document_ref,
            document_ref,
            f"filesystem:{document_ref}",
            1,
            "2026-05-05T00:00:00+00:00",
            None,
            "content",
            "metadata",
            "[]",
            "{}",
        ),
    )
    conn.commit()
    conn.close()


def _add_chunk_provenance(
    db_path: Path,
    strategy: str,
    chunk_id: str,
    file_path: str,
) -> None:
    document_ref = str(Path(file_path).resolve())
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        f"INSERT OR REPLACE INTO chunk_source_provenance_{strategy} ("
        "chunk_id, namespace, document_ref, source_unit_refs, chunk_strategy, parser_name"
        ") VALUES (?, ?, ?, ?, ?, ?)",
        (
            chunk_id,
            "filesystem",
            document_ref,
            "[]",
            strategy,
            "markdown",
        ),
    )
    conn.commit()
    conn.close()


def _count(db_path: Path, table: str) -> int:
    conn = sqlite3.connect(str(db_path))
    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    return n


def _table_exists(db_path: Path, table: str) -> bool:
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    conn.close()
    return row is not None


def _get_pipeline(db_path: Path):  # type: ignore[no-untyped-def]
    """Deferred import of IndexingPipeline — raises ImportError until P3/P4 ships."""
    return _get_pipeline_with_backend(db_path)


def _get_pipeline_with_backend(
    db_path: Path,
    *,
    search_backend: str = "sqlite",
):  # type: ignore[no-untyped-def]
    from dotmd.core.config import Settings
    from dotmd.ingestion import pipeline as pipeline_module
    from dotmd.ingestion.pipeline import IndexingPipeline

    settings = Settings(
        index_dir=db_path.parent,
        embedding_url="http://localhost:18088",
        embedding_model=MODEL,
        search_backend=search_backend,
        surreal_retrieval_url="http://localhost:8000",
        surreal_retrieval_database="dotmd",
    )
    if search_backend == "surreal":
        with patch.object(
            pipeline_module,
            "_create_surreal_direct_writer",
            return_value=object(),
        ):
            return IndexingPipeline(settings)
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
        _add_source_document(db_path, "/file_A.md")
        _add_resource_binding(db_path, "/file_A.md")
        _add_chunk_provenance(db_path, strategy, chunk_id, "/file_A.md")

        pipeline = _get_pipeline(db_path)
        pipeline._purge_file("/file_A.md")

        assert _count(db_path, f"chunks_{strategy}") == 0
        assert _count(db_path, f"vec_meta_{strategy}_{MODEL}") == 0
        assert _count(db_path, f"chunk_file_paths_{strategy}") == 0
        assert _count(db_path, "source_documents") == 0
        assert _count(db_path, f"chunk_source_provenance_{strategy}") == 0


class TestDropChunksClearsSourceAwareTables:
    """drop_chunks removes Phase 25 source-aware derived state."""

    def test_drop_chunks_clears_m2m_provenance_and_source_documents(
        self,
        tmp_path: Path,
    ) -> None:
        db_path = _build_post_v16_db(tmp_path)
        strategy = STRATEGIES[0]
        chunk_id = "h" * 64

        _insert_chunk(db_path, strategy, chunk_id, "content")
        _add_m2m(db_path, strategy, chunk_id, "/file_A.md")
        _add_source_document(db_path, "/file_A.md")
        _add_chunk_provenance(db_path, strategy, chunk_id, "/file_A.md")

        pipeline = _get_pipeline(db_path)
        pipeline.drop_chunks()

        assert not _table_exists(db_path, f"chunks_{strategy}")
        assert not _table_exists(db_path, f"chunk_file_paths_{strategy}")
        assert not _table_exists(db_path, f"chunk_source_provenance_{strategy}")
        assert _count(db_path, "source_documents") == 0
        assert _count(db_path, "resource_bindings") == 0

    def test_drop_chunks_preserves_source_documents_referenced_by_other_strategy(
        self,
        tmp_path: Path,
    ) -> None:
        db_path = tmp_path / "index.db"
        current_strategy = STRATEGIES[0]
        other_strategy = "contextual_512_50"
        conn = sqlite3.connect(str(db_path))
        for strategy in (current_strategy, other_strategy):
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
                CREATE VIRTUAL TABLE chunks_fts_{strategy} USING fts5(
                    chunk_id UNINDEXED, text, title, tags, tokenize='unicode61'
                );
                CREATE TABLE vec_meta_{strategy}_{MODEL} (
                    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                    chunk_id TEXT NOT NULL UNIQUE,
                    text_hash TEXT
                );
                CREATE TABLE chunk_source_provenance_{strategy} (
                    chunk_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    document_ref TEXT NOT NULL,
                    source_unit_refs TEXT NOT NULL,
                    chunk_strategy TEXT NOT NULL,
                    parser_name TEXT,
                    PRIMARY KEY (chunk_id, namespace, document_ref)
                );
            """)
        conn.executescript("""
            CREATE TABLE source_documents (
                namespace TEXT NOT NULL,
                document_ref TEXT NOT NULL,
                ref TEXT NOT NULL,
                source_uri TEXT NOT NULL,
                file_path TEXT,
                media_type TEXT NOT NULL,
                parser_name TEXT NOT NULL,
                document_type TEXT NOT NULL,
                title TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                content_fingerprint TEXT NOT NULL,
                metadata_fingerprint TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (namespace, document_ref)
            );
        """)
        conn.commit()
        conn.close()

        shared_path = "/shared.md"
        current_chunk_id = "i" * 64
        other_chunk_id = "j" * 64
        for strategy, chunk_id in (
            (current_strategy, current_chunk_id),
            (other_strategy, other_chunk_id),
        ):
            _insert_chunk(db_path, strategy, chunk_id, "content")
            _add_m2m(db_path, strategy, chunk_id, shared_path)
            _add_chunk_provenance(db_path, strategy, chunk_id, shared_path)
        _add_source_document(db_path, shared_path)

        pipeline = _get_pipeline(db_path)
        pipeline.drop_chunks()

        assert not _table_exists(db_path, f"chunk_file_paths_{current_strategy}")
        assert _table_exists(db_path, f"chunk_file_paths_{other_strategy}")
        assert _count(db_path, "source_documents") == 1


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
        _add_source_document(db_path, "/file_A.md")
        _add_source_document(db_path, "/file_B.md")
        _add_chunk_provenance(db_path, strategy, chunk_id, "/file_A.md")
        _add_chunk_provenance(db_path, strategy, chunk_id, "/file_B.md")

        pipeline = _get_pipeline(db_path)
        pipeline._purge_file("/file_A.md")

        # Chunk survives in chunks_* and vec_meta_*
        assert _count(db_path, f"chunks_{strategy}") == 1
        assert _count(db_path, f"vec_meta_{strategy}_{MODEL}") == 1
        # Only file_A's M2M row removed; file_B's survives
        m2m_rows = (
            sqlite3.connect(str(db_path))
            .execute(f"SELECT file_path FROM chunk_file_paths_{strategy}")
            .fetchall()
        )
        file_paths = {r[0] for r in m2m_rows}
        assert "/file_B.md" in file_paths
        assert "/file_A.md" not in file_paths
        conn = sqlite3.connect(str(db_path))
        source_refs = {
            r[0] for r in conn.execute("SELECT document_ref FROM source_documents").fetchall()
        }
        provenance_refs = {
            r[0]
            for r in conn.execute(
                f"SELECT document_ref FROM chunk_source_provenance_{strategy}"
            ).fetchall()
        }
        conn.close()
        assert str(Path("/file_A.md").resolve()) not in source_refs
        assert str(Path("/file_B.md").resolve()) in source_refs
        assert str(Path("/file_A.md").resolve()) not in provenance_refs
        assert str(Path("/file_B.md").resolve()) in provenance_refs


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
        surviving_ids = {
            r[0] for r in conn.execute(f"SELECT chunk_id FROM chunks_{strategy}").fetchall()
        }
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
        with (
            patch(
                "dotmd.storage.sqlite_vec.SQLiteVecVectorStore.delete_by_chunk_ids",
                side_effect=RuntimeError("Simulated failure in vector cascade"),
            ),
            pytest.raises(RuntimeError),
        ):
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
                    chunk_id UNINDEXED, text, title, tags, tokenize='unicode61'
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
            assert _count(db_path, f"chunks_{s}") == 0, f"chunks_{s} not cleaned after purge"
            assert _count(db_path, f"chunk_file_paths_{s}") == 0, (
                f"chunk_file_paths_{s} not cleaned after purge"
            )


class TestGraphCleanupFailureDoesNotRollbackDB:
    """Graph cleanup failure after DB commit does not undo DB changes (best-effort)."""

    def test_graph_cleanup_failure_does_not_rollback_db(self, tmp_path: Path) -> None:
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
            "delete_chunks_from_graph",
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

    def test_graph_holder_aware_path_when_audit_flags_unsafe(self, tmp_path: Path) -> None:
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
        file_node_delete_calls = []

        # Spy on graph narrow helpers to assert they are NOT called for shared chunks
        original = pipeline._graph_store.delete_chunks_from_graph

        def spy_delete(chunk_ids, *args, **kwargs):  # type: ignore[no-untyped-def]
            delete_calls.extend(chunk_ids)
            return original(chunk_ids, *args, **kwargs)

        pipeline._graph_store.delete_chunks_from_graph = spy_delete

        original_file_node_delete = pipeline._graph_store.delete_file_node

        def spy_file_node_delete(file_path, *args, **kwargs):  # type: ignore[no-untyped-def]
            file_node_delete_calls.append(file_path)
            return original_file_node_delete(file_path, *args, **kwargs)

        pipeline._graph_store.delete_file_node = spy_file_node_delete

        pipeline._purge_file("/file_A.md")

        # shared_cid must NOT appear in graph delete calls (still held by B)
        assert shared_cid not in delete_calls, (
            f"Shared chunk {shared_cid!r} should not be removed from graph (still held by /file_B.md)"
        )
        assert file_node_delete_calls == ["/file_A.md"]


class TestNormalFilesystemUnbind:
    """Normal missing-resource handling deactivates bindings and retains artifacts."""

    def test_normal_unbind_preserves_source_document_and_provenance(
        self,
        tmp_path: Path,
    ) -> None:
        db_path = _build_post_v16_db(tmp_path)
        strategy = STRATEGIES[0]
        chunk_id = "k" * 64
        file_path = "/file_A.md"
        document_ref = str(Path(file_path).resolve())

        _insert_chunk(db_path, strategy, chunk_id, "retained content")
        _add_m2m(db_path, strategy, chunk_id, file_path)
        _add_source_document(db_path, file_path)
        _add_chunk_provenance(db_path, strategy, chunk_id, file_path)

        pipeline = _get_pipeline(db_path)
        pipeline._deactivate_filesystem_binding(file_path)

        conn = sqlite3.connect(str(db_path))
        source_rows = conn.execute(
            "SELECT document_ref FROM source_documents WHERE document_ref = ?",
            (document_ref,),
        ).fetchall()
        provenance_rows = conn.execute(
            f"SELECT chunk_id, document_ref FROM chunk_source_provenance_{strategy} "
            "WHERE document_ref = ?",
            (document_ref,),
        ).fetchall()
        binding_row = conn.execute(
            "SELECT active, unbound_at, metadata_json FROM resource_bindings "
            "WHERE namespace = 'filesystem' AND resource_ref = ?",
            (document_ref,),
        ).fetchone()
        conn.close()

        assert source_rows == [(document_ref,)]
        assert provenance_rows == [(chunk_id, document_ref)]
        assert binding_row is not None
        assert binding_row[0] == 0
        assert binding_row[1] is not None
        assert "file_missing" in binding_row[2]

    def test_normal_unbind_preserves_chunks_fts_vectors_and_graph(
        self,
        tmp_path: Path,
    ) -> None:
        db_path = _build_post_v16_db(tmp_path)
        strategy = STRATEGIES[0]
        chunk_id = "l" * 64
        file_path = "/file_A.md"

        _insert_chunk(db_path, strategy, chunk_id, "retained content")
        _add_m2m(db_path, strategy, chunk_id, file_path)
        _add_source_document(db_path, file_path)
        _add_chunk_provenance(db_path, strategy, chunk_id, file_path)

        pipeline = _get_pipeline(db_path)
        graph_calls: list[tuple[str, object]] = []

        def record_chunks(chunk_ids, *args, **kwargs):  # type: ignore[no-untyped-def]
            graph_calls.append(("chunks", list(chunk_ids)))

        def record_file(file_path, *args, **kwargs):  # type: ignore[no-untyped-def]
            graph_calls.append(("file", file_path))

        def record_subgraph(file_path, *args, **kwargs):  # type: ignore[no-untyped-def]
            graph_calls.append(("subgraph", file_path))

        pipeline._graph_store.delete_chunks_from_graph = record_chunks
        pipeline._graph_store.delete_file_node = record_file
        pipeline._graph_store.delete_file_subgraph = record_subgraph

        pipeline._deactivate_filesystem_binding(file_path)

        assert _count(db_path, f"chunks_{strategy}") == 1
        assert _count(db_path, f"chunks_fts_{strategy}") == 1
        assert _count(db_path, f"vec_meta_{strategy}_{MODEL}") == 1
        assert _count(db_path, f"chunk_file_paths_{strategy}") == 1
        assert graph_calls == []

    def test_incremental_modified_files_keep_hard_replacement_path(
        self,
        tmp_path: Path,
    ) -> None:
        from dotmd.core.models import IndexStats
        from dotmd.ingestion.file_tracker import FileDiff

        db_path = _build_post_v16_db(tmp_path)
        pipeline = _get_pipeline(db_path)
        calls: list[str] = []

        def record_purge(path: str) -> None:
            calls.append(path)

        def fail_deactivate(path: str, *, reason: str = "file_missing") -> None:
            raise AssertionError("modified files must not deactivate bindings")

        pipeline._purge_file = record_purge  # type: ignore[method-assign]
        pipeline._deactivate_filesystem_binding = fail_deactivate  # type: ignore[method-assign]
        pipeline._ingest_and_finalize = lambda *args, **kwargs: IndexStats()  # type: ignore[method-assign]

        pipeline._incremental_index(
            [],
            FileDiff(modified=["/file_A.md"]),
            documents_by_path={},
        )

        assert calls == ["/file_A.md"]


class TestSurrealFilesystemLifecycle:
    def test_purge_file_emits_surreal_tombstones_for_orphans_and_bindings(
        self,
        tmp_path: Path,
    ) -> None:
        db_path = _build_post_v16_db(tmp_path)
        strategy = STRATEGIES[0]
        file_path = "/file_A.md"
        shared_file_path = "/file_B.md"
        orphan_chunk_id = "m" * 64
        shared_chunk_id = "n" * 64

        _insert_chunk(db_path, strategy, orphan_chunk_id, "orphan content")
        _insert_chunk(db_path, strategy, shared_chunk_id, "shared content")
        _add_m2m(db_path, strategy, orphan_chunk_id, file_path, chunk_index=0)
        _add_m2m(db_path, strategy, shared_chunk_id, file_path, chunk_index=1)
        _add_m2m(db_path, strategy, shared_chunk_id, shared_file_path, chunk_index=0)
        _add_source_document(db_path, file_path)
        _add_resource_binding(db_path, file_path)
        _add_chunk_provenance(db_path, strategy, orphan_chunk_id, file_path)
        _add_chunk_provenance(db_path, strategy, shared_chunk_id, file_path)

        pipeline = _get_pipeline_with_backend(db_path, search_backend="surreal")
        captured_manifests: list[object] = []

        def record_manifest(manifest) -> None:  # type: ignore[no-untyped-def]
            captured_manifests.append(manifest)

        pipeline._write_surreal_direct_manifest = record_manifest  # type: ignore[method-assign]
        pipeline._purge_file(file_path)

        assert len(captured_manifests) == 1
        manifest = captured_manifests[0]

        assert [row.change_type.value for row in manifest.documents.rows] == ["tombstone"]
        assert manifest.documents.rows[0].tombstone.previous_row["document_ref"] == str(
            Path(file_path).resolve()
        )
        assert [row.change_type.value for row in manifest.resource_bindings.rows] == [
            "tombstone"
        ]
        assert manifest.resource_bindings.rows[0].tombstone.previous_row["resource_ref"] == str(
            Path(file_path).resolve()
        )
        assert [row.tombstone.previous_row["binding_id"] for row in manifest.chunk_file_bindings.rows] == [
            f"{orphan_chunk_id}\x1f{file_path}\x1f0",
            f"{shared_chunk_id}\x1f{file_path}\x1f1",
        ]
        assert [row.tombstone.previous_row["chunk_id"] for row in manifest.chunks.rows] == [
            orphan_chunk_id,
        ]
        assert [row.tombstone.previous_row["chunk_id"] for row in manifest.provenance.rows] == [
            orphan_chunk_id,
        ]
        assert [
            row.tombstone.previous_row["chunk_strategy"] for row in manifest.embeddings.rows
        ] == [strategy]
        assert [
            row.tombstone.previous_row["embedding_model"] for row in manifest.embeddings.rows
        ] == [MODEL]

        result = run_surreal_delta_sync(
            manifest,
            FakeSurrealDeltaWriter(),
            state=SurrealDeltaSyncState(),
            batch_size=50,
        )
        assert result.applied_counts["tombstones"] == 7

    def test_deactivate_filesystem_binding_emits_surreal_tombstones(
        self,
        tmp_path: Path,
    ) -> None:
        db_path = _build_post_v16_db(tmp_path)
        file_path = "/file_A.md"
        document_ref = str(Path(file_path).resolve())

        _add_source_document(db_path, file_path)
        _add_resource_binding(db_path, file_path)

        pipeline = _get_pipeline_with_backend(db_path, search_backend="surreal")
        captured_manifests: list[object] = []

        def record_manifest(manifest) -> None:  # type: ignore[no-untyped-def]
            captured_manifests.append(manifest)

        pipeline._write_surreal_direct_manifest = record_manifest  # type: ignore[method-assign]
        pipeline._deactivate_filesystem_binding(file_path)

        assert len(captured_manifests) == 1
        manifest = captured_manifests[0]
        assert [row.change_type.value for row in manifest.documents.rows] == ["tombstone"]
        assert [row.change_type.value for row in manifest.resource_bindings.rows] == [
            "tombstone"
        ]
        assert manifest.chunks.rows == []
        assert manifest.chunk_file_bindings.rows == []
        assert manifest.provenance.rows == []
        assert manifest.embeddings.rows == []

        result = run_surreal_delta_sync(
            manifest,
            FakeSurrealDeltaWriter(),
            state=SurrealDeltaSyncState(),
            batch_size=50,
        )
        assert result.applied_counts["tombstones"] == 2

        conn = sqlite3.connect(str(db_path))
        binding_row = conn.execute(
            "SELECT active, unbound_at FROM resource_bindings "
            "WHERE namespace = 'filesystem' AND resource_ref = ?",
            (document_ref,),
        ).fetchone()
        conn.close()
        assert binding_row == (0, binding_row[1])

    def test_sqlite_backend_does_not_emit_surreal_tombstones(
        self,
        tmp_path: Path,
    ) -> None:
        db_path = _build_post_v16_db(tmp_path)
        file_path = "/file_A.md"
        _add_source_document(db_path, file_path)
        _add_resource_binding(db_path, file_path)

        pipeline = _get_pipeline_with_backend(db_path, search_backend="sqlite")
        captured_manifests: list[object] = []

        def record_manifest(manifest) -> None:  # type: ignore[no-untyped-def]
            captured_manifests.append(manifest)

        pipeline._write_surreal_direct_manifest = record_manifest  # type: ignore[method-assign]
        pipeline._deactivate_filesystem_binding(file_path)

        assert captured_manifests == []
