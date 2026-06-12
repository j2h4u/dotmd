"""Smoke tests for the vendored Airweave slice."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx


def test_entities_import() -> None:
    from dotmd.vendor.airweave.entities_base import BaseEntity, Breadcrumb
    from dotmd.vendor.airweave.entities_gmail import GmailMessageEntity, GmailThreadEntity

    assert BaseEntity is not None
    assert Breadcrumb is not None
    assert GmailMessageEntity is not None
    assert GmailThreadEntity is not None


def test_gmail_source_import() -> None:
    from dotmd.vendor.airweave.source_gmail import GmailSource

    assert GmailSource.short_name == "gmail"


def test_gmail_config_import() -> None:
    from dotmd.vendor.airweave.gmail_config import GmailConfig

    cfg = GmailConfig()
    assert cfg.included_labels == ["inbox", "sent"]


def test_shim_construction() -> None:
    from dotmd.vendor.airweave.shims import (
        GmailHttpClientShim,
        GmailLoggerShim,
        GmailOAuthTokenProvider,
    )
    from dotmd.vendor.airweave.source_gmail import GmailSource

    log_shim = GmailLoggerShim(logging.getLogger("test"))
    log_shim.debug("test message")
    creds = {"client_id": "cid", "client_secret": "csec", "refresh_token": "rtoken"}
    auth_shim = GmailOAuthTokenProvider(credentials=creds)
    assert auth_shim.supports_refresh is True
    assert auth_shim.provider_kind == "oauth"
    assert isinstance(auth_shim._refresh_lock, type(threading.Lock()))
    assert auth_shim._cached_token is None
    http_shim = GmailHttpClientShim(httpx.AsyncClient())
    source = GmailSource(auth=auth_shim, logger=log_shim, http_client=http_shim)
    assert source.auth is auth_shim


def test_token_provider_uses_expires_in_margin() -> None:
    """Token cache expiry must be margin-based, not hard-coded."""
    from dotmd.vendor.airweave.shims import GmailOAuthTokenProvider

    creds = {"client_id": "cid", "client_secret": "csec", "refresh_token": "rtoken"}
    provider = GmailOAuthTokenProvider(credentials=creds)

    mock_response = MagicMock()
    mock_response.json.return_value = {"access_token": "fake-token", "expires_in": 3600}
    mock_response.raise_for_status.return_value = None

    with patch("httpx.post", return_value=mock_response):
        token = provider.get_token()
        assert token == "fake-token"
        expected_min_expiry = time.time() + 3000
        assert provider._token_expires_at > expected_min_expiry


def test_token_provider_concurrent_refresh_serialized() -> None:
    """Concurrent get_token() calls must not issue multiple refresh requests."""
    from dotmd.vendor.airweave.shims import GmailOAuthTokenProvider

    creds = {"client_id": "cid", "client_secret": "csec", "refresh_token": "rtoken"}
    provider = GmailOAuthTokenProvider(credentials=creds)
    call_count = 0

    def mock_post(*args: object, **kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        time.sleep(0.05)
        response = MagicMock()
        response.json.return_value = {"access_token": f"token-{call_count}", "expires_in": 3600}
        response.raise_for_status.return_value = None
        return response

    tokens: list[str] = []
    errors: list[Exception] = []

    def get_token() -> None:
        try:
            tokens.append(provider.get_token())
        except (
            KeyError,
            httpx.HTTPError,
            ValueError,
        ) as exc:  # pragma: no cover - assertion reports errors below.
            errors.append(exc)

    with patch("httpx.post", side_effect=mock_post):
        threads = [threading.Thread(target=get_token) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert not errors
    assert len(tokens) == 5
    assert call_count == 1


def test_no_airweave_package_required() -> None:
    import sys

    for mod_name in list(sys.modules.keys()):
        assert not (mod_name.startswith(("airweave.domains", "airweave.core", "temporalio"))), (
            f"Unexpected heavy Airweave module loaded: {mod_name}"
        )


def test_vendor_version_file_exists() -> None:
    vendor_version = Path("src/dotmd/vendor/airweave/VENDOR_VERSION")
    assert vendor_version.exists()
    content = vendor_version.read_text(encoding="utf-8")
    assert "airweave" in content.lower()
