from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from dotmd.core.config import Settings
from dotmd.core.models import ExtractDepth, FileInfo
from dotmd.ingestion.pipeline import IndexingPipeline
from dotmd.ingestion.trickle import TrickleIndexer


def _surreal_settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    index_dir = tmp_path / "index"
    data_dir.mkdir()
    index_dir.mkdir()
    return Settings(
        data_dir=data_dir,
        index_dir=index_dir,
        embedding_url="http://localhost:18088",
        indexing_paths=[str(data_dir)],
        extract_depth=ExtractDepth.STRUCTURAL,
        search_backend="surreal",
        surreal_retrieval_url="http://surrealdb:8000",
        surreal_retrieval_database="dotmd",
        surreal_retrieval_embedding_dimension=3,
    )


def _surreal_pipeline(tmp_path: Path) -> IndexingPipeline:
    from dotmd.ingestion import pipeline as pipeline_module

    settings = _surreal_settings(tmp_path)
    with patch.object(
        pipeline_module,
        "_create_surreal_direct_writer",
        return_value=object(),
    ):
        return IndexingPipeline(settings)


def _seed_local_legacy_state(pipeline: IndexingPipeline) -> list[str]:
    strategy = pipeline._strategy
    model_suffix = pipeline._model_suffix
    conn = pipeline.conn
    tables = [
        f"chunks_{strategy}",
        f"chunk_file_paths_{strategy}",
        f"chunks_fts_{strategy}",
        f"chunk_source_provenance_{strategy}",
        f"chunk_fingerprints_{strategy}",
        f"vec_chunks_{strategy}{model_suffix}",
        f"vec_meta_{strategy}{model_suffix}",
        f"vec_config_{strategy}{model_suffix}",
        f"meta_fingerprints_{strategy}{model_suffix}",
        f"vec_components_{strategy}{model_suffix}",
        "source_documents",
        "resource_bindings",
        "source_unit_fingerprints",
        "source_checkpoints",
    ]
    conn.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS chunks_{strategy} (
            chunk_id TEXT PRIMARY KEY,
            text TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS chunk_file_paths_{strategy} (
            chunk_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            PRIMARY KEY (chunk_id, file_path, chunk_index)
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts_{strategy}
            USING fts5(chunk_id UNINDEXED, text);
        CREATE TABLE IF NOT EXISTS chunk_source_provenance_{strategy} (
            chunk_id TEXT NOT NULL,
            namespace TEXT NOT NULL,
            document_ref TEXT NOT NULL,
            source_unit_refs TEXT NOT NULL,
            chunk_strategy TEXT NOT NULL,
            parser_name TEXT,
            PRIMARY KEY (chunk_id, namespace, document_ref)
        );
        CREATE TABLE IF NOT EXISTS chunk_fingerprints_{strategy} (
            file_path TEXT PRIMARY KEY,
            mtime REAL NOT NULL,
            size_bytes INTEGER NOT NULL,
            checksum TEXT NOT NULL,
            indexed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS vec_chunks_{strategy}{model_suffix} (
            chunk_id TEXT PRIMARY KEY,
            embedding BLOB NOT NULL
        );
        CREATE TABLE IF NOT EXISTS vec_meta_{strategy}{model_suffix} (
            chunk_id TEXT NOT NULL UNIQUE,
            text_hash TEXT
        );
        CREATE TABLE IF NOT EXISTS vec_config_{strategy}{model_suffix} (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS meta_fingerprints_{strategy}{model_suffix} (
            file_path TEXT PRIMARY KEY,
            mtime REAL NOT NULL,
            size_bytes INTEGER NOT NULL,
            checksum TEXT NOT NULL,
            indexed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS vec_components_{strategy}{model_suffix} (
            entity_id TEXT PRIMARY KEY,
            component TEXT NOT NULL,
            embedding BLOB NOT NULL
        );
        CREATE TABLE IF NOT EXISTS source_documents (
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
        CREATE TABLE IF NOT EXISTS resource_bindings (
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
        CREATE TABLE IF NOT EXISTS source_unit_fingerprints (
            namespace TEXT NOT NULL,
            document_ref TEXT NOT NULL,
            unit_ref TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            indexed_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{{}}',
            PRIMARY KEY (namespace, document_ref, unit_ref)
        );
        CREATE TABLE IF NOT EXISTS source_checkpoints (
            namespace TEXT PRIMARY KEY,
            checkpoint_cursor TEXT,
            last_success_at TEXT,
            last_error TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{{}}'
        );
        """
    )
    conn.executemany(
        f"INSERT OR REPLACE INTO chunks_{strategy} (chunk_id, text) VALUES (?, ?)",
        [("chunk-1", "chunk text")],
    )
    conn.executemany(
        f"INSERT OR REPLACE INTO chunk_file_paths_{strategy} (chunk_id, file_path, chunk_index) "
        "VALUES (?, ?, ?)",
        [("chunk-1", "/notes/orphan.md", 0)],
    )
    conn.executemany(
        f"INSERT INTO chunks_fts_{strategy} (chunk_id, text) VALUES (?, ?)",
        [("chunk-1", "chunk text")],
    )
    conn.executemany(
        f"INSERT OR REPLACE INTO chunk_source_provenance_{strategy} "
        "(chunk_id, namespace, document_ref, source_unit_refs, chunk_strategy, parser_name) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [("chunk-1", "fixture", "doc-1", '["unit-1"]', strategy, "markdown")],
    )
    conn.executemany(
        f"INSERT OR REPLACE INTO chunk_fingerprints_{strategy} "
        "(file_path, mtime, size_bytes, checksum, indexed_at) VALUES (?, ?, ?, ?, ?)",
        [("/notes/orphan.md", 1.0, 1, "chunk-fp", "2026-06-19T00:00:00+00:00")],
    )
    conn.executemany(
        f"INSERT OR REPLACE INTO vec_chunks_{strategy}{model_suffix} (chunk_id, embedding) "
        "VALUES (?, ?)",
        [("chunk-1", b"vec")],
    )
    conn.executemany(
        f"INSERT OR REPLACE INTO vec_meta_{strategy}{model_suffix} (chunk_id, text_hash) "
        "VALUES (?, ?)",
        [("chunk-1", "text-hash")],
    )
    conn.executemany(
        f"INSERT OR REPLACE INTO vec_config_{strategy}{model_suffix} (key, value) "
        "VALUES (?, ?)",
        [("seed", "value")],
    )
    conn.executemany(
        f"INSERT OR REPLACE INTO meta_fingerprints_{strategy}{model_suffix} "
        "(file_path, mtime, size_bytes, checksum, indexed_at) VALUES (?, ?, ?, ?, ?)",
        [("/notes/orphan.md", 1.0, 1, "meta-fp", "2026-06-19T00:00:00+00:00")],
    )
    conn.executemany(
        f"INSERT OR REPLACE INTO vec_components_{strategy}{model_suffix} "
        "(entity_id, component, embedding) VALUES (?, ?, ?)",
        [("chunk-1", "text", b"component")],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO source_documents ("
        "namespace, document_ref, ref, source_uri, file_path, media_type, parser_name, "
        "document_type, title, updated_at, content_fingerprint, metadata_fingerprint, "
        "metadata_json"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "fixture",
                "doc-1",
                "fixture:doc-1",
                "fixture://doc-1",
                "/notes/orphan.md",
                "text/markdown",
                "markdown",
                "document",
                "Orphan",
                "2026-06-19T00:00:00+00:00",
                "content",
                "metadata",
                "{}",
            )
        ],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO resource_bindings ("
        "namespace, resource_ref, document_ref, ref, active, bound_at, unbound_at, "
        "content_fingerprint, metadata_fingerprint, source_unit_refs, metadata_json"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "fixture",
                "doc-1",
                "doc-1",
                "fixture:doc-1",
                1,
                "2026-06-19T00:00:00+00:00",
                None,
                "content",
                "metadata",
                "[]",
                "{}",
            )
        ],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO source_unit_fingerprints "
        "(namespace, document_ref, unit_ref, fingerprint, updated_at, indexed_at, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "fixture",
                "doc-1",
                "unit-1",
                "unit-fp",
                "2026-06-19T00:00:00+00:00",
                "2026-06-19T00:00:00+00:00",
                "{}",
            )
        ],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO source_checkpoints "
        "(namespace, checkpoint_cursor, last_success_at, last_error, metadata_json) "
        "VALUES (?, ?, ?, ?, ?)",
        [("fixture", "cursor-1", "2026-06-19T00:00:00+00:00", None, "{}")],
    )
    conn.commit()
    return tables


def _snapshot_counts(conn: sqlite3.Connection, tables: list[str]) -> dict[str, int]:
    return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}


@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        ("purge_application_source", ("fixture",)),
        ("drop_vectors", ()),
        ("drop_chunks", ()),
        ("clear", ()),
    ],
)
def test_surreal_pipeline_destructive_methods_refuse_and_preserve_local_tables(
    tmp_path: Path,
    method_name: str,
    args: tuple[object, ...],
) -> None:
    pipeline = _surreal_pipeline(tmp_path)
    tables = _seed_local_legacy_state(pipeline)
    counts_before = _snapshot_counts(pipeline.conn, tables)

    if method_name == "clear":
        pipeline._settings.acronyms_path.write_text("{}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Surreal mode"):
        getattr(pipeline, method_name)(*args)

    assert _snapshot_counts(pipeline.conn, tables) == counts_before
    if method_name == "clear":
        assert pipeline._settings.acronyms_path.exists()


@pytest.mark.asyncio
async def test_surreal_trickle_runs_startup_orphan_cleanup(
    tmp_path: Path,
) -> None:
    pipeline = _surreal_pipeline(tmp_path)
    settings = pipeline._settings
    indexer = TrickleIndexer(settings, pipeline)

    present_file = settings.data_dir / "present.md"
    present_file.write_text("# Present\n", encoding="utf-8")
    discovered = [
        FileInfo(
            path=present_file,
            title="Present",
            last_modified=datetime.now(UTC),
            size_bytes=present_file.stat().st_size,
        )
    ]

    purge_mock = Mock(return_value=(0, 0, 0))
    pipeline.purge_orphaned_files = purge_mock  # type: ignore[method-assign]

    from dotmd.ingestion import reader as reader_module

    with patch.object(reader_module, "discover_files_multi", return_value=discovered):
        await indexer._startup_checks()

    assert purge_mock.call_count == 1
    assert purge_mock.call_args.args == ({str(present_file)},)


@pytest.mark.asyncio
async def test_surreal_trickle_calls_deleted_file_purge_in_backlog(
    tmp_path: Path,
) -> None:
    settings = _surreal_settings(tmp_path)
    indexer = TrickleIndexer(settings)
    purge_mock = Mock(return_value=None)
    indexer._pipeline = SimpleNamespace(
        file_tracker=SimpleNamespace(
            diff=lambda all_files: SimpleNamespace(
                new=[],
                modified=[],
                deleted=["/notes/orphan.md"],
                unchanged=[],
            )
        ),
        _purge_file=purge_mock,
    )

    from dotmd.ingestion import reader as reader_module

    with patch.object(reader_module, "discover_files_multi", return_value=[]):
        await indexer._process_backlog(asyncio.Event())

    assert purge_mock.call_count == 1
    assert purge_mock.call_args.args == ("/notes/orphan.md",)
