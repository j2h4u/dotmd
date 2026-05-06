from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from watchdog.events import FileMovedEvent

from dotmd.core.config import Settings
from dotmd.core.models import ExtractDepth
from dotmd.ingestion.trickle import (
    TrickleIndexer,
    _format_duration,
    _format_rate,
    _MarkdownEventHandler,
)


@pytest.fixture
def minimal_settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    return Settings(
        data_dir=data_dir,
        index_dir=index_dir,
        embedding_url="http://localhost:18088",
        vector_backend="sqlite-vec",
        graph_backend="ladybugdb",
        extract_depth=ExtractDepth.STRUCTURAL,
    )


def test_trickle_rate_format_uses_per_second_units() -> None:
    assert _format_rate(23_040.0, "chunks") == "6.4 chunks/s"
    assert _format_rate(720.0, "files") == "0.20 files/s"


def test_trickle_duration_format_is_human_readable() -> None:
    assert _format_duration(9.4) == "9s"
    assert _format_duration(90.6) == "1m31s"
    assert _format_duration(3_723.0) == "1h02m03s"


def test_update_eta_uses_current_backlog_window(minimal_settings) -> None:
    indexer = TrickleIndexer(minimal_settings)
    indexer.state._start_time = time.monotonic() - 10
    indexer.state.total_chunks_done = 20

    indexer._update_eta(files_done=2, files_total=4)

    assert 7000 <= indexer.state.chunks_per_hour <= 7300
    assert 700 <= indexer.state.files_per_hour <= 730
    assert indexer.state.eta_minutes is None


def test_markdown_event_handler_indexes_atomic_move_destination() -> None:
    loop = asyncio.new_event_loop()
    queue: asyncio.Queue[str] = asyncio.Queue()

    try:
        handler = _MarkdownEventHandler(loop=loop, queue=queue, exclude=[])

        handler.on_moved(
            FileMovedEvent(
                src_path="/mnt/knowledgebase/chat.tmp",
                dest_path="/mnt/knowledgebase/chat.md",
            )
        )
        loop.run_until_complete(asyncio.sleep(0))

        assert queue.get_nowait() == "/mnt/knowledgebase/chat.md"
        assert queue.empty()
    finally:
        loop.close()


def test_markdown_event_handler_purges_old_path_and_indexes_new_path() -> None:
    loop = asyncio.new_event_loop()
    queue: asyncio.Queue[str] = asyncio.Queue()

    try:
        handler = _MarkdownEventHandler(loop=loop, queue=queue, exclude=[])

        handler.on_moved(
            FileMovedEvent(
                src_path="/mnt/knowledgebase/old.md",
                dest_path="/mnt/knowledgebase/new.md",
            )
        )
        loop.run_until_complete(asyncio.sleep(0))

        assert queue.get_nowait() == "/mnt/knowledgebase/old.md"
        assert queue.get_nowait() == "/mnt/knowledgebase/new.md"
        assert queue.empty()
    finally:
        loop.close()
