"""Tests for dotMD OAuth provider storage behavior."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlparse

import pytest
from mcp.server.auth.handlers.authorize import AuthorizationParams
from mcp.server.auth.provider import AccessToken, RefreshToken, RegistrationError
from mcp.shared.auth import OAuthClientInformationFull

from dotmd.auth import DotMDOAuthProvider, PairingCodeError


def _client() -> OAuthClientInformationFull:
    return OAuthClientInformationFull.model_validate(
        {
            "client_id": "client-1",
            "client_secret": "secret-1",
            "redirect_uris": ["https://client.example/callback"],
            "scope": "dotmd",
        }
    )


def _client_with_redirect(redirect_uri: str) -> OAuthClientInformationFull:
    return OAuthClientInformationFull.model_validate(
        {
            "client_id": "client-1",
            "client_secret": "secret-1",
            "redirect_uris": [redirect_uri],
            "scope": "dotmd",
        }
    )


def _params(
    state: str | None = "state-1",
    redirect_uri: str = "https://client.example/callback",
) -> AuthorizationParams:
    return AuthorizationParams.model_validate(
        {
            "state": state,
            "scopes": ["dotmd"],
            "code_challenge": "challenge-1",
            "redirect_uri": redirect_uri,
            "redirect_uri_provided_explicitly": True,
            "resource": "https://senbonzakura.tailf87223.ts.net/dotmd/mcp",
        }
    )


def _provider(tmp_path: Path, monkeypatch) -> DotMDOAuthProvider:
    return DotMDOAuthProvider(tmp_path / "oauth_state.json")


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def test_register_creates_pending_client(tmp_path: Path, monkeypatch) -> None:
    async def run() -> None:
        provider = _provider(tmp_path, monkeypatch)
        client = _client()

        await provider.register_client(client)

        assert client.client_id is not None
        assert await provider.get_client(client.client_id) is None
        assert await provider.get_pending_client(client.client_id) == client
        assert await provider.get_client("unknown") is None
        state = json.loads((tmp_path / "oauth_state.json").read_text(encoding="utf-8"))
        assert client.client_id in state["pending_clients"]

    asyncio.run(run())


def test_register_allows_any_redirect_when_allowlist_empty(tmp_path: Path, monkeypatch) -> None:
    async def run() -> None:
        monkeypatch.delenv("DOTMD_OAUTH_ALLOWED_REDIRECT_URI_PREFIXES", raising=False)
        provider = DotMDOAuthProvider(tmp_path / "oauth_state.json")
        client = _client_with_redirect("https://agent.example/callback")

        await provider.register_client(client)

        assert client.client_id is not None
        assert await provider.get_pending_client(client.client_id) == client

    asyncio.run(run())


def test_register_rejects_unlisted_redirect_when_allowlist_configured(
    tmp_path: Path, monkeypatch
) -> None:
    async def run() -> None:
        monkeypatch.setenv("DOTMD_OAUTH_ALLOWED_REDIRECT_URI_PREFIXES", "https://trusted.example/callback")
        provider = DotMDOAuthProvider(tmp_path / "oauth_state.json")
        with pytest.raises(RegistrationError) as exc_info:
            await provider.register_client(_client_with_redirect("https://agent.example/callback"))
        assert exc_info.value.error == "invalid_redirect_uri"
        assert exc_info.value.error_description == "OAuth client redirect_uri is not allowed"

    asyncio.run(run())


def test_register_allows_chatgpt_connector_redirect_prefix(tmp_path: Path, monkeypatch) -> None:
    async def run() -> None:
        monkeypatch.setenv(
            "DOTMD_OAUTH_ALLOWED_REDIRECT_URI_PREFIXES",
            "https://chatgpt.com/connector/oauth/",
        )
        provider = DotMDOAuthProvider(tmp_path / "oauth_state.json")
        client = _client_with_redirect("https://chatgpt.com/connector/oauth/elZoTEQOgIRd")

        await provider.register_client(client)

        assert client.client_id is not None
        assert await provider.get_client(client.client_id) is None
        stored = await provider.get_pending_client(client.client_id)
        assert stored is not None
        assert stored.token_endpoint_auth_method == "none"
        assert stored.client_secret is None

    asyncio.run(run())


def test_authorize_allows_registered_chatgpt_connector_redirect_prefix(
    tmp_path: Path, monkeypatch
) -> None:
    async def run() -> None:
        monkeypatch.setenv(
            "DOTMD_OAUTH_ALLOWED_REDIRECT_URI_PREFIXES",
            "https://chatgpt.com/connector/oauth/",
        )
        provider = DotMDOAuthProvider(tmp_path / "oauth_state.json")
        redirect_uri = "https://chatgpt.com/connector/oauth/elZoTEQOgIRd"
        client = _client_with_redirect(redirect_uri)
        params = _params(redirect_uri=redirect_uri)

        redirect = await provider.authorize(client, params)

        assert redirect.startswith(f"{redirect_uri}?")
        assert "code" in _query(redirect)

    asyncio.run(run())


def test_register_allows_arbitrary_redirect_when_allowlist_empty(
    tmp_path: Path, monkeypatch
) -> None:
    async def run() -> None:
        monkeypatch.setenv("DOTMD_OAUTH_ALLOWED_REDIRECT_URI_PREFIXES", "")
        provider = DotMDOAuthProvider(tmp_path / "oauth_state.json")
        client = _client_with_redirect(
            "https://chatgpt.com.evil.example/connector/oauth/elZoTEQOgIRd"
        )

        await provider.register_client(client)

        assert client.client_id is not None
        assert await provider.get_pending_client(client.client_id) == client

    asyncio.run(run())


def test_register_creates_pending_client_by_default(tmp_path: Path, monkeypatch) -> None:
    async def run() -> None:
        provider = DotMDOAuthProvider(tmp_path / "oauth_state.json")
        client = _client()

        await provider.register_client(client)

        assert client.client_id is not None
        assert await provider.get_client(client.client_id) is None
        assert await provider.get_pending_client(client.client_id) == client

    asyncio.run(run())


def test_pairing_code_activates_pending_client_once(tmp_path: Path, monkeypatch) -> None:
    async def run() -> None:
        provider = DotMDOAuthProvider(tmp_path / "oauth_state.json")
        client = _client()
        await provider.register_client(client)

        code, expires_at = await provider.create_pairing_code(ttl_seconds=60)
        assert "-" in code
        assert expires_at > time.time()
        await provider.activate_pending_client(client, code.lower().replace("-", " "))

        assert client.client_id is not None
        assert await provider.get_pending_client(client.client_id) is None
        assert await provider.get_client(client.client_id) == client
        second_client = _client_with_redirect("https://client.example/callback")
        second_client.client_id = "client-2"
        await provider.register_client(second_client)
        with pytest.raises(PairingCodeError):
            await provider.activate_pending_client(second_client, code)

    asyncio.run(run())


def test_pairing_code_created_by_second_provider_activates_running_provider(
    tmp_path: Path, monkeypatch
) -> None:
    async def run() -> None:
        state_path = tmp_path / "oauth_state.json"
        server_provider = DotMDOAuthProvider(state_path)
        cli_provider = DotMDOAuthProvider(state_path)
        client = _client()
        await server_provider.register_client(client)

        code, _ = await cli_provider.create_pairing_code(ttl_seconds=60)
        await server_provider.activate_pending_client(client, code)

        assert client.client_id is not None
        assert await server_provider.get_client(client.client_id) == client

    asyncio.run(run())


def test_pairing_code_expires(tmp_path: Path, monkeypatch) -> None:
    async def run() -> None:
        provider = DotMDOAuthProvider(tmp_path / "oauth_state.json")
        client = _client()
        await provider.register_client(client)
        code, _ = await provider.create_pairing_code(ttl_seconds=1)
        pairing_record = cast(
            dict[str, object], provider._state["pairing_codes"][code.replace("-", "")]
        )
        pairing_record["expires_at"] = time.time() - 1
        await provider._flush()

        with pytest.raises(PairingCodeError):
            await provider.activate_pending_client(client, code)

    asyncio.run(run())


def test_pairing_code_rejects_too_fast_retry(tmp_path: Path, monkeypatch) -> None:
    async def run() -> None:
        provider = DotMDOAuthProvider(tmp_path / "oauth_state.json")
        client = _client()
        await provider.register_client(client)

        with pytest.raises(PairingCodeError, match="invalid or expired"):
            await provider.activate_pending_client(client, "WRONG-CODE")
        with pytest.raises(PairingCodeError, match="Too many pairing attempts"):
            await provider.activate_pending_client(client, "WRONG-CODE")

    asyncio.run(run())


def test_pairing_code_removes_pending_client_after_too_many_failures(
    tmp_path: Path, monkeypatch
) -> None:
    async def run() -> None:
        monkeypatch.setattr("dotmd.auth._PAIRING_MIN_ATTEMPT_INTERVAL_SECONDS", 0)
        provider = DotMDOAuthProvider(tmp_path / "oauth_state.json")
        client = _client()
        await provider.register_client(client)

        for _ in range(4):
            with pytest.raises(PairingCodeError, match="invalid or expired"):
                await provider.activate_pending_client(client, "WRONG-CODE")
        with pytest.raises(PairingCodeError, match="Too many invalid pairing attempts"):
            await provider.activate_pending_client(client, "WRONG-CODE")

        assert client.client_id is not None
        assert await provider.get_pending_client(client.client_id) is None

    asyncio.run(run())


def test_pending_client_expires_without_completed_pairing(tmp_path: Path, monkeypatch) -> None:
    async def run() -> None:
        provider = DotMDOAuthProvider(tmp_path / "oauth_state.json")
        client = _client()
        await provider.register_client(client)
        assert client.client_id is not None
        pending_record = cast(
            dict[str, object], provider._state["pending_clients"][client.client_id]
        )
        pending_record["expires_at"] = time.time() - 1
        await provider._flush()

        assert await provider.get_pending_client(client.client_id) is None

    asyncio.run(run())


def test_authorize_stores_code_and_returns_redirect(tmp_path: Path, monkeypatch) -> None:
    async def run() -> None:
        monkeypatch.delenv("DOTMD_BASE_URL", raising=False)
        provider = _provider(tmp_path, monkeypatch)
        redirect = await provider.authorize(_client(), _params())
        query = _query(redirect)

        assert "code" in query
        assert query["state"] == ["state-1"]
        assert "iss" not in query
        assert query["code"][0] in provider._state["auth_codes"]

    asyncio.run(run())


def test_authorize_includes_issuer_when_configured(tmp_path: Path, monkeypatch) -> None:
    async def run() -> None:
        monkeypatch.setenv("DOTMD_BASE_URL", "https://dotmd.example")
        provider = _provider(tmp_path, monkeypatch)
        redirect = await provider.authorize(_client(), _params())
        query = _query(redirect)

        assert query["iss"] == ["https://dotmd.example"]

    asyncio.run(run())


def test_load_authorization_code(tmp_path: Path, monkeypatch) -> None:
    async def run() -> None:
        provider = _provider(tmp_path, monkeypatch)
        client = _client()
        redirect = await provider.authorize(client, _params())
        code = _query(redirect)["code"][0]

        auth_code = await provider.load_authorization_code(client, code)

        assert auth_code is not None
        assert auth_code.code_challenge == "challenge-1"
        assert await provider.load_authorization_code(client, "missing") is None

    asyncio.run(run())


def test_exchange_authorization_code(tmp_path: Path, monkeypatch) -> None:
    async def run() -> None:
        provider = _provider(tmp_path, monkeypatch)
        client = _client()
        redirect = await provider.authorize(client, _params())
        code = _query(redirect)["code"][0]
        auth_code = await provider.load_authorization_code(client, code)
        assert auth_code is not None

        token = await provider.exchange_authorization_code(client, auth_code)

        assert code not in provider._state["auth_codes"]
        assert token.token_type == "Bearer"
        assert token.expires_in == 86400 * 30
        assert token.access_token in provider._state["access_tokens"]
        assert token.refresh_token in provider._state["refresh_tokens"]

    asyncio.run(run())


def test_load_access_token_valid(tmp_path: Path, monkeypatch) -> None:
    async def run() -> None:
        provider = _provider(tmp_path, monkeypatch)
        access = AccessToken(
            token="access-1",
            client_id="client-1",
            scopes=["dotmd"],
            expires_at=int(time.time()) + 60,
            resource=None,
        )
        provider._state["access_tokens"][access.token] = access.model_dump(mode="json")

        assert await provider.load_access_token(access.token) == access

    asyncio.run(run())


def test_load_access_token_expired(tmp_path: Path, monkeypatch) -> None:
    async def run() -> None:
        provider = _provider(tmp_path, monkeypatch)
        access = AccessToken(
            token="access-1",
            client_id="client-1",
            scopes=["dotmd"],
            expires_at=int(time.time()) - 60,
            resource=None,
        )
        provider._state["access_tokens"][access.token] = access.model_dump(mode="json")

        assert await provider.load_access_token(access.token) is None

    asyncio.run(run())


def test_load_refresh_token(tmp_path: Path, monkeypatch) -> None:
    async def run() -> None:
        provider = _provider(tmp_path, monkeypatch)
        client = _client()
        assert client.client_id is not None
        refresh = RefreshToken(token="refresh-1", client_id=client.client_id, scopes=["dotmd"])
        provider._state["refresh_tokens"][refresh.token] = refresh.model_dump(mode="json")

        assert await provider.load_refresh_token(client, refresh.token) == refresh
        assert await provider.load_refresh_token(client, "missing") is None

    asyncio.run(run())


def test_exchange_refresh_token_rotates_tokens(tmp_path: Path, monkeypatch) -> None:
    async def run() -> None:
        provider = _provider(tmp_path, monkeypatch)
        client = _client()
        assert client.client_id is not None
        refresh = RefreshToken(token="refresh-1", client_id=client.client_id, scopes=["dotmd"])
        provider._state["refresh_tokens"][refresh.token] = refresh.model_dump(mode="json")

        token = await provider.exchange_refresh_token(client, refresh, ["dotmd"])

        assert refresh.token not in provider._state["refresh_tokens"]
        assert token.access_token in provider._state["access_tokens"]
        assert token.refresh_token in provider._state["refresh_tokens"]
        assert token.refresh_token != refresh.token

    asyncio.run(run())


def test_revoke_token_removes_token_without_error(tmp_path: Path, monkeypatch) -> None:
    async def run() -> None:
        provider = _provider(tmp_path, monkeypatch)
        access = AccessToken(token="shared", client_id="client-1", scopes=["dotmd"])
        refresh = RefreshToken(token="shared", client_id="client-1", scopes=["dotmd"])
        provider._state["access_tokens"][access.token] = access.model_dump(mode="json")
        provider._state["refresh_tokens"][refresh.token] = refresh.model_dump(mode="json")

        await provider.revoke_token(access)
        await provider.revoke_token(access)

        assert access.token not in provider._state["access_tokens"]
        assert refresh.token not in provider._state["refresh_tokens"]

    asyncio.run(run())


def test_json_persistence(tmp_path: Path, monkeypatch) -> None:
    async def run() -> None:
        state_path = tmp_path / "oauth_state.json"
        provider = DotMDOAuthProvider(state_path)
        client = _client()
        await provider.register_client(client)
        code, _ = await provider.create_pairing_code(ttl_seconds=60)
        await provider.activate_pending_client(client, code)
        redirect = await provider.authorize(client, _params())
        code = _query(redirect)["code"][0]
        auth_code = await provider.load_authorization_code(client, code)
        assert auth_code is not None
        token = await provider.exchange_authorization_code(client, auth_code)

        reloaded = DotMDOAuthProvider(state_path)

        access_token = await reloaded.load_access_token(token.access_token)
        assert access_token is not None
        assert access_token.client_id == client.client_id

    asyncio.run(run())
