"""RED test skeletons for P3 — IndexingPipeline M2M write path.

After Phase 16 P3 ships:
  - _index_file uses INSERT OR IGNORE on chunks_* and chunk_file_paths_*
  - Re-indexing the same file is a no-op on chunks_* content
  - Two files with identical content share one chunks_* row + two M2M rows
  - Payload mismatch on conflict is WARN-logged without overwriting

These tests will FAIL until P3 (wave 3) implements the M2M ingest path.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

# P1 (wave 2) delivers these — will ImportError until then:
from dotmd.storage.metadata import SQLiteMetadataStore  # noqa: F401


def _build_post_v16_db(tmp_path: Path) -> tuple[Path, str, str]:
    """Build a post-v16 schema DB using the strategy/model from Settings.

    Returns ``(db_path, strategy, model_key)`` so tests use the same names
    as the running pipeline regardless of env-var overrides.
    """
    from dotmd.core.config import Settings
    from dotmd.ingestion.pipeline import _model_to_table_suffix

    settings = Settings(
        index_dir=tmp_path,
        embedding_url="http://localhost:18088",
    )
    strategy = settings.chunk_strategy
    model_key = _model_to_table_suffix(settings.embedding_model).lstrip("_")

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
        CREATE TABLE vec_meta_{strategy}_{model_key} (
            rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_id TEXT NOT NULL UNIQUE,
            text_hash TEXT
        );
    """)
    conn.commit()
    conn.close()
    return db_path, strategy, model_key


def _settings(tmp_path: Path):
    from dotmd.core.config import Settings

    return Settings(
        index_dir=tmp_path,
        embedding_url="http://localhost:18088",
        indexing_paths=[str(tmp_path)],
    )


class TestInsertOrIgnoreOnRepeat:
    """INSERT OR IGNORE means re-indexing same file does not duplicate or overwrite rows."""

    def test_insert_or_ignore_on_repeat(self, tmp_path: Path) -> None:
        """Indexing the same file twice: chunks_* row count unchanged, text unchanged."""
        from dotmd.ingestion.pipeline import IndexingPipeline

        _, strategy, _model_key = _build_post_v16_db(tmp_path)
        settings = _settings(tmp_path)

        # Build a stub file
        md_file = tmp_path / "doc.md"
        md_file.write_text("# Heading\n\nSome unique content for idempotency test.\n")

        pipeline = IndexingPipeline(settings)
        # Index once
        pipeline.index_file(md_file)

        count_after_1 = pipeline._conn.execute(
            f"SELECT COUNT(*) FROM chunks_{strategy}"
        ).fetchone()[0]
        text_after_1 = pipeline._conn.execute(
            f"SELECT text FROM chunks_{strategy} LIMIT 1"
        ).fetchone()

        # Index the same file again
        pipeline.index_file(md_file)

        count_after_2 = pipeline._conn.execute(
            f"SELECT COUNT(*) FROM chunks_{strategy}"
        ).fetchone()[0]
        text_after_2 = pipeline._conn.execute(
            f"SELECT text FROM chunks_{strategy} LIMIT 1"
        ).fetchone()

        assert count_after_1 == count_after_2, "Re-indexing should not add rows to chunks_*"
        assert text_after_1 == text_after_2, (
            "Re-indexing should not overwrite text (INSERT OR IGNORE)"
        )


class TestTwoFilesIdenticalContentShareChunk:
    """Two files with identical content produce one chunks_* row + two M2M rows."""

    def test_two_files_identical_content_share_chunk(self, tmp_path: Path) -> None:
        """Identical content → 1 chunks_* row, 2 chunk_file_paths_* rows."""
        from dotmd.ingestion.pipeline import IndexingPipeline

        _, strategy, _model_key = _build_post_v16_db(tmp_path)
        settings = _settings(tmp_path)
        pipeline = IndexingPipeline(settings)

        body = "# Shared Heading\n\nThis content is identical in both files.\n"
        file_a = tmp_path / "a.md"
        file_b = tmp_path / "b.md"
        file_a.write_text(body)
        file_b.write_text(body)

        pipeline.index_file(file_a)
        pipeline.index_file(file_b)

        chunk_count = pipeline._conn.execute(f"SELECT COUNT(*) FROM chunks_{strategy}").fetchone()[
            0
        ]
        m2m_count = pipeline._conn.execute(
            f"SELECT COUNT(*) FROM chunk_file_paths_{strategy}"
        ).fetchone()[0]

        assert chunk_count == 1, (
            f"Expected 1 shared chunks_* row for identical content, got {chunk_count}"
        )
        assert m2m_count == 2, f"Expected 2 M2M rows (one per file), got {m2m_count}"


class TestRepeatedHeadingInSameFile:
    """Repeated identical heading+body in same file creates two M2M rows (Decision #3)."""

    def test_repeated_heading_in_same_file_creates_two_m2m_rows(self, tmp_path: Path) -> None:
        """File with repeated heading at chunk_index 0 and 1 → 2 M2M rows sharing chunk_id."""
        from dotmd.ingestion.pipeline import IndexingPipeline

        _, strategy, _model_key = _build_post_v16_db(tmp_path)
        settings = _settings(tmp_path)
        pipeline = IndexingPipeline(settings)

        # Two identical heading blocks in same file at different positions
        body = "# Introduction\n\nSame text here.\n\n---\n\n# Introduction\n\nSame text here.\n"
        md_file = tmp_path / "repeated.md"
        md_file.write_text(body)
        pipeline.index_file(md_file)

        m2m_rows = pipeline._conn.execute(
            f"SELECT chunk_id, file_path, chunk_index FROM chunk_file_paths_{strategy} "
            f"ORDER BY chunk_index"
        ).fetchall()

        # Two M2M rows for the same file (different chunk_index → different chunk_ids)
        assert len(m2m_rows) >= 2, (
            f"Expected >= 2 M2M rows for repeated heading, got {len(m2m_rows)}"
        )
        file_paths = {r[1] for r in m2m_rows}
        assert str(md_file) in file_paths


class TestVecMetaNotRewrittenOnReindex:
    """vec_meta_* row count does not grow on re-index (Phase 15 cache honoured)."""

    def test_vec_meta_not_rewritten_on_reindex(self, tmp_path: Path) -> None:
        """Second index_file call for the same chunks does not add vec_meta_* rows."""
        from dotmd.ingestion.pipeline import IndexingPipeline

        _, strategy, model_key = _build_post_v16_db(tmp_path)
        settings = _settings(tmp_path)
        pipeline = IndexingPipeline(settings)

        md_file = tmp_path / "cached.md"
        md_file.write_text("# Cache Test\n\nContent for vec_meta idempotency.\n")
        pipeline.index_file(md_file)

        count1 = pipeline._conn.execute(
            f"SELECT COUNT(*) FROM vec_meta_{strategy}_{model_key}"
        ).fetchone()[0]

        # Index again
        pipeline.index_file(md_file)

        count2 = pipeline._conn.execute(
            f"SELECT COUNT(*) FROM vec_meta_{strategy}_{model_key}"
        ).fetchone()[0]

        assert count1 == count2, (
            f"vec_meta_* grew from {count1} to {count2} on reindex — cache not honoured"
        )


class TestPayloadMismatchLogsWarn:
    """Review-HIGH-P3: payload mismatch on chunk_id conflict is WARN-logged, row not overwritten."""

    def test_payload_mismatch_logs_warn_without_overwriting(self, tmp_path: Path) -> None:
        """Monkeypatched chunker emitting same chunk_id with different text logs WARN; first-writer survives."""
        from dotmd.core.models import Chunk
        from dotmd.ingestion.pipeline import IndexingPipeline

        _, strategy, _model_key = _build_post_v16_db(tmp_path)
        settings = _settings(tmp_path)
        pipeline = IndexingPipeline(settings)

        # Insert the "first writer" row directly into chunks_*
        first_text = "First writer text — must survive"
        conflict_text = "Second writer text — must NOT overwrite first"
        fixed_chunk_id = "a" * 64  # Valid 64-char id

        pipeline._conn.execute(
            f"INSERT INTO chunks_{strategy} (chunk_id, heading_hierarchy, level, text) "
            "VALUES (?, '[]', 0, ?)",
            (fixed_chunk_id, first_text),
        )
        pipeline._conn.commit()

        # Monkeypatch the chunker to emit a Chunk with the same chunk_id but different text
        md_file = tmp_path / "mismatch.md"
        md_file.write_text("# Conflict\n\nContent.\n")

        import dotmd.ingestion.chunker as _chunker

        def patched_chunk_file(*args, **kwargs):  # type: ignore[no-untyped-def]
            return [
                Chunk(
                    chunk_id=fixed_chunk_id,
                    file_paths=[md_file],
                    heading_hierarchy=["Conflict"],
                    level=1,
                    text=conflict_text,
                    chunk_index=0,
                )
            ]

        import logging

        warn_messages: list[str] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                warn_messages.append(record.getMessage())

        handler = _Capture(level=logging.WARNING)
        pip_logger = logging.getLogger("dotmd.ingestion.pipeline")
        pip_logger.addHandler(handler)
        pip_logger.setLevel(logging.WARNING)
        try:
            with patch.object(_chunker, "chunk_file", patched_chunk_file):
                pipeline.index_file(md_file)
        finally:
            pip_logger.removeHandler(handler)

        # Row must retain first-writer's text
        stored_text = pipeline._conn.execute(
            f"SELECT text FROM chunks_{strategy} WHERE chunk_id=?",
            (fixed_chunk_id,),
        ).fetchone()[0]
        assert stored_text == first_text, f"First-writer text overwritten: stored={stored_text!r}"

        # WARN must have been logged
        assert any("mismatch" in m.lower() for m in warn_messages), (
            "Expected at least one WARNING log about payload mismatch"
        )
