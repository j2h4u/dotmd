"""RED test skeletons for P4 — purge_orphaned_files (orphan sweep).

After Phase 16 P4 ships, purge_orphaned_files scans chunk_file_paths_*
instead of chunks_* for stale file paths.

These tests FAIL at execution time until P4 (wave 4) ships the rewritten
orphan sweep. Imports are deferred so --collect-only works before P4 ships.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

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

    settings = Settings(index_dir=db_path.parent)
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
