"""Tests for Telegram auto-sync polling task — TG-01, TG-02 (Phase 36 Plan 02)."""

from __future__ import annotations

import asyncio


def test_settings_has_telegram_sync_interval() -> None:
    """Settings must expose telegram_sync_interval_seconds with default 300.0."""
    from dotmd.core.config import Settings

    s = Settings(embedding_url="http://localhost:18088")
    assert hasattr(s, "telegram_sync_interval_seconds")
    assert s.telegram_sync_interval_seconds == 300.0


async def test_run_telegram_poller_calls_ingest_and_exits_on_shutdown() -> None:
    """_run_telegram_poller calls ingest_application_source_runtime via run_in_executor
    and exits cleanly when shutdown_event is set."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from dotmd.mcp_server import _run_telegram_poller

    shutdown_event = asyncio.Event()
    svc = MagicMock()
    bundle = MagicMock()
    result_mock = MagicMock(
        discovered=1,
        new_units=1,
        changed_units=0,
        skipped_units=0,
        rebound_units=0,
        failed_units=0,
        reused_units=0,
    )
    svc._local_executor = MagicMock()
    svc._pipeline.ingest_application_source_runtime.return_value = result_mock

    with patch("asyncio.get_running_loop") as mock_loop:
        mock_loop.return_value = MagicMock()
        mock_loop.return_value.run_in_executor = AsyncMock(return_value=result_mock)

        # Set shutdown after first iteration completes
        async def set_shutdown() -> None:
            await asyncio.sleep(0.01)
            shutdown_event.set()

        shutdown_task = asyncio.create_task(set_shutdown())
        await _run_telegram_poller(svc, bundle, interval_seconds=0.1, shutdown_event=shutdown_event)
        await shutdown_task

    # Verify run_in_executor was called at least once
    assert mock_loop.return_value.run_in_executor.call_count >= 1
