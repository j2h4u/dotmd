"""DI shims for the vendored Airweave Gmail source."""
# pyright: reportArgumentType=false, reportReturnType=false

from __future__ import annotations

import logging
import threading
import time

import httpx


class GmailLoggerShim:
    """ContextualLogger-compatible shim around stdlib logging."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def debug(self, msg: str, *args: object, **kwargs: object) -> None:
        self._logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args: object, **kwargs: object) -> None:
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args: object, **kwargs: object) -> None:
        self._logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args: object, **kwargs: object) -> None:
        self._logger.error(msg, *args, **kwargs)


class GmailHttpClientShim:
    """AirweaveHttpClient-compatible shim around httpx.AsyncClient."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        params: dict[str, object] | None = None,
    ) -> httpx.Response:
        """Issue a GET request."""
        return await self._client.get(url, headers=headers, params=params)

    async def post(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
    ) -> httpx.Response:
        """Issue a POST request."""
        return await self._client.post(url, headers=headers, json=json)


class GmailOAuthTokenProvider:
    """OAuth token provider with thread-safe margin-based cache expiry."""

    provider_kind: str = "oauth"
    supports_refresh: bool = True

    def __init__(self, credentials: dict[str, str]) -> None:
        self._credentials = credentials
        self._cached_token: str | None = None
        self._token_expires_at: float = 0.0
        self._refresh_lock = threading.Lock()

    def get_token(self) -> str:
        """Return a valid access token, refreshing with a 300 second safety margin."""
        now = time.time()
        if self._cached_token and now < self._token_expires_at:
            return self._cached_token

        with self._refresh_lock:
            if self._cached_token and time.time() < self._token_expires_at:
                return self._cached_token

            response = httpx.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": self._credentials["client_id"],
                    "client_secret": self._credentials["client_secret"],
                    "refresh_token": self._credentials["refresh_token"],
                    "grant_type": "refresh_token",
                },
                timeout=10.0,
            )
            response.raise_for_status()
            token_data = response.json()
            self._cached_token = token_data["access_token"]
            if "refresh_token" in token_data:
                self._credentials["refresh_token"] = token_data["refresh_token"]
            expires_in = token_data.get("expires_in", 3600)
            self._token_expires_at = time.time() + max(expires_in - 300, 0)
            return self._cached_token

    def force_refresh(self) -> str:
        """Force a refresh by expiring the cache before calling get_token."""
        with self._refresh_lock:
            self._cached_token = None
            self._token_expires_at = 0.0
        return self.get_token()
