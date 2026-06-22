"""RED test skeletons for P4 — purge_orphaned_files (orphan sweep).

After Phase 16 P4 ships, purge_orphaned_files scans chunk_file_paths_*
instead of chunks_* for stale file paths.

These tests FAIL at execution time until P4 (wave 4) ships the rewritten
orphan sweep. Imports are deferred so --collect-only works before P4 ships.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import Mock, patch

from dotmd.ingestion.surreal_delta_sync import (
    FakeSurrealDeltaWriter,
    SurrealDeltaSyncState,
    run_surreal_delta_sync,
)

MODEL = "multilingual_e5_large"


def _build_m2m_db(tmp_path: Path, strategy: str = "heading_512_50") -> Path:
    """Build a post-v16 schema DB with chunk_file_paths_* for orphan sweep tests."""
    db_path = tmp_path / "index.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(f"""
        CREATE TABLE chunks_{strategy} (
            chunk_id TEXT PRIMARY KEY, text TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE chunk_file_paths_{strategy} (
            chunk_id TEXT NOT NULL, file_path TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            PRIMARY KEY (chunk_id, file_path, chunk_index)
        );
        CREATE INDEX idx_chunk_file_paths_{strategy}_file_path
            ON chunk_file_paths_{strategy}(file_path);
        CREATE TABLE vec_meta_{strategy}_{MODEL} (
            rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_id TEXT NOT NULL UNIQUE, text_hash TEXT
        );
        CREATE VIRTUAL TABLE chunks_fts_{strategy} USING fts5(
            chunk_id UNINDEXED, text, tokenize='unicode61'
        );
    """)
    conn.commit()
    conn.close()
    return db_path


def _populate(db_path: Path, strategy: str, chunk_id: str, file_path: str) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        f"INSERT OR IGNORE INTO chunks_{strategy} (chunk_id, text) VALUES (?, ?)",
        (chunk_id, "text"),
    )
    conn.execute(
        f"INSERT OR IGNORE INTO vec_meta_{strategy}_{MODEL} (chunk_id) VALUES (?)",
        (chunk_id,),
    )
    conn.execute(
        f"INSERT OR IGNORE INTO chunks_fts_{strategy} (chunk_id, text) VALUES (?, 'text')",
        (chunk_id,),
    )
    conn.execute(
        f"INSERT OR IGNORE INTO chunk_file_paths_{strategy} (chunk_id, file_path, chunk_index) "
        "VALUES (?, ?, 0)",
        (chunk_id, file_path),
    )
    conn.commit()
    conn.close()


def _get_pipeline(db_path: Path):  # type: ignore[no-untyped-def]
    from dotmd.core.config import Settings
    from dotmd.ingestion.pipeline import IndexingPipeline

    settings = Settings(
        index_dir=db_path.parent,
        embedding={"url": "http://localhost:18088"},
    )
    return IndexingPipeline(settings)


def _get_pipeline_with_direct_writer(
    db_path: Path,
    *,
    use_surreal_direct_writer: bool = False,
):  # type: ignore[no-untyped-def]
    from dotmd.core.config import Settings
    from dotmd.ingestion import pipeline as pipeline_module
    from dotmd.ingestion.pipeline import IndexingPipeline

    settings = Settings(
        index_dir=db_path.parent,
        embedding={"url": "http://localhost:18088", "model": MODEL},
    )
    if use_surreal_direct_writer:
        settings = settings.model_copy(
            update={
                "surreal_retrieval": settings.surreal_retrieval.model_copy(
                    update={"url": "http://localhost:8000", "database": "dotmd"}
                ),
            }
        )
        with patch.object(
            pipeline_module,
            "_create_surreal_direct_writer",
            return_value=object(),
        ):
            return IndexingPipeline(settings)
    return IndexingPipeline(settings)


class TestOrphanSweepFindsMissingFiles:
    """purge_orphaned_files deactivates file_paths not on disk."""

    def test_orphan_sweep_finds_missing_files(self, tmp_path: Path) -> None:
        """M2M contains /gone/file.md which doesn't exist on disk; sweep purges it."""
        db_path = _build_m2m_db(tmp_path)
        strategy = "heading_512_50"
        chunk_id = "a" * 64
        missing_file = "/gone/does_not_exist.md"  # not on disk

        _populate(db_path, strategy, chunk_id, missing_file)

        pipeline = _get_pipeline(db_path)
        deactivate_calls = []

        original_deactivate = pipeline._deactivate_filesystem_binding

        def spy_deactivate(fp: str, *, reason: str = "file_missing") -> None:
            deactivate_calls.append(fp)
            original_deactivate(fp, reason=reason)

        pipeline._deactivate_filesystem_binding = spy_deactivate  # type: ignore[method-assign]
        pipeline.purge_orphaned_files()

        assert missing_file in deactivate_calls, (
            f"Expected {missing_file!r} to be deactivated, got calls: {deactivate_calls!r}"
        )


class TestOrphanSweepIgnoresPresentFiles:
    """purge_orphaned_files does not purge file_paths that exist on disk."""

    def test_orphan_sweep_ignores_present_files(self, tmp_path: Path) -> None:
        """M2M contains a file that actually exists on disk; sweep skips it."""
        db_path = _build_m2m_db(tmp_path)
        strategy = "heading_512_50"
        chunk_id = "b" * 64

        # Create the actual file
        existing_file = tmp_path / "present.md"
        existing_file.write_text("# Present\n\nThis file exists.\n")

        _populate(db_path, strategy, chunk_id, str(existing_file))

        pipeline = _get_pipeline(db_path)
        deactivate_calls = []
        original_deactivate = pipeline._deactivate_filesystem_binding

        def spy_deactivate(fp: str, *, reason: str = "file_missing") -> None:
            deactivate_calls.append(fp)
            original_deactivate(fp, reason=reason)

        pipeline._deactivate_filesystem_binding = spy_deactivate  # type: ignore[method-assign]
        pipeline.purge_orphaned_files()

        assert str(existing_file) not in deactivate_calls, (
            f"Present file should not be deactivated, but was: {deactivate_calls!r}"
        )


class TestOrphanSweepMultiStrategy:
    """Orphan sweep covers all strategies in the DB."""

    def test_orphan_sweep_multi_strategy(self, tmp_path: Path) -> None:
        """Stale file_paths in both heading_512_50 and contextual_512_50 are both purged."""
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

        missing_paths = [f"/gone/{s}_file.md" for s in strategies]
        for s, fp in zip(strategies, missing_paths, strict=False):
            cid = ("a" if s == "heading_512_50" else "b") * 64
            _populate(db_path, s, cid, fp)

        pipeline = _get_pipeline(db_path)
        deactivate_calls = []
        original_deactivate = pipeline._deactivate_filesystem_binding

        def spy_deactivate(fp: str, *, reason: str = "file_missing") -> None:
            deactivate_calls.append(fp)
            original_deactivate(fp, reason=reason)

        pipeline._deactivate_filesystem_binding = spy_deactivate  # type: ignore[method-assign]
        pipeline.purge_orphaned_files()

        for missing_fp in missing_paths:
            assert missing_fp in deactivate_calls, (
                f"Expected {missing_fp!r} to be deactivated; got: {deactivate_calls!r}"
            )


class TestOrphanSweepSurreal:
    """Missing-file sweep emits Surreal tombstones when the standalone backend is active."""

    def test_orphan_sweep_emits_surreal_tombstones_for_missing_files(
        self,
        tmp_path: Path,
    ) -> None:
        db_path = _build_m2m_db(tmp_path)
        strategy = "heading_512_50"
        chunk_id = "c" * 64
        missing_file = "/gone/does_not_exist.md"
        document_ref = str(Path(missing_file).resolve())

        _populate(db_path, strategy, chunk_id, missing_file)
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
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
                metadata_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (namespace, resource_ref)
            );
            """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO source_documents (
                namespace, document_ref, ref, source_uri, file_path, media_type,
                parser_name, document_type, title, updated_at, content_fingerprint,
                metadata_fingerprint, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "filesystem",
                document_ref,
                f"filesystem:{document_ref}",
                missing_file,
                missing_file,
                "text/markdown",
                "markdown",
                "document",
                "Missing file",
                "2026-06-19T12:00:00+00:00",
                "content",
                "metadata",
                "{}",
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO resource_bindings (
                namespace, resource_ref, document_ref, ref, active, bound_at,
                unbound_at, content_fingerprint, metadata_fingerprint, source_unit_refs,
                metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "filesystem",
                document_ref,
                document_ref,
                f"filesystem:{document_ref}",
                1,
                "2026-06-19T12:00:00+00:00",
                None,
                "content",
                "metadata",
                "[]",
                "{}",
            ),
        )
        conn.commit()
        counts_before = {
            "chunks": conn.execute(f"SELECT COUNT(*) FROM chunks_{strategy}").fetchone()[0],
            "chunk_file_paths": conn.execute(
                f"SELECT COUNT(*) FROM chunk_file_paths_{strategy}"
            ).fetchone()[0],
            "vec_meta": conn.execute(
                f"SELECT COUNT(*) FROM vec_meta_{strategy}_{MODEL}"
            ).fetchone()[0],
            "source_documents": conn.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0],
            "resource_bindings": conn.execute("SELECT COUNT(*) FROM resource_bindings").fetchone()[
                0
            ],
        }
        conn.close()

        pipeline = _get_pipeline_with_direct_writer(db_path, use_surreal_direct_writer=True)
        captured_manifests: list[object] = []

        def record_manifest(manifest) -> None:  # type: ignore[no-untyped-def]
            captured_manifests.append(manifest)

        pipeline._deactivate_filesystem_binding = Mock(  # type: ignore[method-assign]
            side_effect=AssertionError("should not be called")
        )
        pipeline._write_surreal_direct_manifest = record_manifest  # type: ignore[method-assign]
        pipeline.purge_orphaned_files()

        assert len(captured_manifests) == 1
        manifest = captured_manifests[0]
        assert [row.change_type.value for row in manifest.documents.rows] == ["tombstone"]
        assert [row.change_type.value for row in manifest.resource_bindings.rows] == ["tombstone"]
        assert manifest.chunks.rows == []
        assert manifest.chunk_file_bindings.rows == []
        assert manifest.provenance.rows == []
        assert manifest.embeddings.rows == []

        conn = sqlite3.connect(str(db_path))
        counts_after = {
            "chunks": conn.execute(f"SELECT COUNT(*) FROM chunks_{strategy}").fetchone()[0],
            "chunk_file_paths": conn.execute(
                f"SELECT COUNT(*) FROM chunk_file_paths_{strategy}"
            ).fetchone()[0],
            "vec_meta": conn.execute(
                f"SELECT COUNT(*) FROM vec_meta_{strategy}_{MODEL}"
            ).fetchone()[0],
            "source_documents": conn.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0],
            "resource_bindings": conn.execute("SELECT COUNT(*) FROM resource_bindings").fetchone()[
                0
            ],
        }
        conn.close()
        assert counts_after == counts_before

        result = run_surreal_delta_sync(
            manifest,
            FakeSurrealDeltaWriter(),
            state=SurrealDeltaSyncState(),
            batch_size=50,
        )
        assert result.applied_counts["tombstones"] == 2
