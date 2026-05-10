"""Tests for Telegram auto-sync polling task — TG-01, TG-02 (Phase 36 Plan 02)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def test_settings_has_telegram_sync_interval() -> None:
    """Settings must expose telegram_sync_interval_seconds with default 300.0."""
    from dotmd.core.config import Settings

    s = Settings()
    assert hasattr(s, "telegram_sync_interval_seconds")
    assert s.telegram_sync_interval_seconds == 300.0


def test_run_telegram_poller_calls_ingest_once_then_exits() -> None:
    """_run_telegram_poller must be importable from dotmd.mcp_server (RED: function absent)."""
    from dotmd.mcp_server import _run_telegram_poller  # noqa: F401
