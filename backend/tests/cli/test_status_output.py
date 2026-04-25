"""RED test skeleton for CLI status command using M2M for path counts (P5 — Task 2).

After Phase 16 P5 ships, `dotmd status` queries chunk_file_paths_* for
distinct file path counts instead of the legacy chunks_* file_path column.

This test FAILS until P5 (wave 5) updates the status query.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


def _get_cli():  # type: ignore[no-untyped-def]
    from click.testing import CliRunner
    from dotmd.cli import main
    return CliRunner, main


class TestStatusCountsDistinctPathsFromM2M:
    """dotmd status reports distinct file_paths count from chunk_file_paths_*."""

    def test_counts_distinct_paths_from_m2m(self, tmp_path: Path) -> None:
        """Status command counts distinct file paths via M2M table after P5."""
        strategy = "heading_512_50"
        MODEL = "multilingual_e5_large"

        # Build a post-v16 schema DB with known content
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
            CREATE TABLE vec_meta_{strategy}_{MODEL} (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                chunk_id TEXT NOT NULL UNIQUE,
                text_hash TEXT
            );
            CREATE VIRTUAL TABLE chunks_fts_{strategy} USING fts5(
                chunk_id UNINDEXED, text, tokenize='unicode61'
            );
            CREATE TABLE stats (
                id INTEGER PRIMARY KEY DEFAULT 1,
                total_files INTEGER NOT NULL DEFAULT 0,
                total_chunks INTEGER NOT NULL DEFAULT 0,
                total_entities INTEGER NOT NULL DEFAULT 0,
                total_edges INTEGER NOT NULL DEFAULT 0,
                last_indexed TEXT,
                new_files INTEGER NOT NULL DEFAULT 0,
                modified_files INTEGER NOT NULL DEFAULT 0,
                deleted_files INTEGER NOT NULL DEFAULT 0,
                unchanged_files INTEGER NOT NULL DEFAULT 0,
                data_dir TEXT
            );
        """)

        # Insert: 1 chunk held by 3 distinct files (collision group)
        chunk_id = "a" * 64
        conn.execute(
            f"INSERT INTO chunks_{strategy} (chunk_id, text) VALUES (?, ?)",
            (chunk_id, "shared text"),
        )
        for i, fp in enumerate(["/file_a.md", "/file_b.md", "/file_c.md"]):
            conn.execute(
                f"INSERT INTO chunk_file_paths_{strategy} (chunk_id, file_path, chunk_index) "
                "VALUES (?, ?, ?)",
                (chunk_id, fp, i),
            )
        conn.execute(
            f"INSERT INTO vec_meta_{strategy}_{MODEL} (chunk_id) VALUES (?)", (chunk_id,)
        )
        conn.execute(
            "INSERT INTO stats (id, total_files, total_chunks) VALUES (1, 3, 1)"
        )
        conn.commit()
        conn.close()

        CliRunner, main = _get_cli()
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--index-dir", str(tmp_path), "status"],
        )

        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}.\nOutput:\n{result.output}"
        )
        # Status must report 3 distinct paths (from M2M), not 1 (from chunks_*)
        assert "3" in result.output, (
            f"Expected '3' distinct paths in status output (from M2M), "
            f"got: {result.output!r}"
        )
