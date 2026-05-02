from __future__ import annotations

import asyncio
from urllib.parse import urlencode

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from dotmd import mcp_server
from dotmd.auth import DotMDOAuthProvider
from dotmd.mcp_server import (
    _AccessLogMiddleware,
    _oauth_metadata_response,
    _oauth_protected_resource_response,
    authorize,
    authorize_pairing_code,
)


async def _token_echo(request: Request) -> JSONResponse:
    form = await request.form()
    return JSONResponse(
        {
            "client_id": form.get("client_id"),
            "has_code": bool(form.get("code")),
            "has_code_verifier": bool(form.get("code_verifier")),
        }
    )


def test_access_log_middleware_does_not_consume_token_form(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_ACCESS_LOG_PATH", tmp_path / "access.log")
    app = Starlette(
        routes=[Route("/token", _token_echo, methods=["POST"])],
        middleware=[Middleware(_AccessLogMiddleware)],
    )

    response = TestClient(app).post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "client-1",
            "code": "code-1",
            "code_verifier": "verifier-1",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "client_id": "client-1",
        "has_code": True,
        "has_code_verifier": True,
    }
    assert '"client_id": "client-1"' in (tmp_path / "access.log").read_text(encoding="utf-8")


def test_oauth_metadata_advertises_authorization_iss(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_base_url", "https://dotmd.example")

    response = _oauth_metadata_response()

    assert response.status_code == 200
    assert b'"issuer":"https://dotmd.example"' in response.body
    assert b'"authorization_response_iss_parameter_supported":true' in response.body


def test_oauth_protected_resource_metadata_includes_scopes(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_base_url", "https://dotmd.example")

    response = _oauth_protected_resource_response()

    assert response.status_code == 200
    assert b'"resource":"https://dotmd.example/mcp"' in response.body
    assert b'"authorization_servers":["https://dotmd.example"]' in response.body
    assert b'"scopes_supported":["dotmd"]' in response.body


def test_authorize_pending_client_requires_pairing_code(tmp_path, monkeypatch) -> None:
    async def setup() -> DotMDOAuthProvider:
        provider = DotMDOAuthProvider(tmp_path / "oauth_state.json")
        from mcp.shared.auth import OAuthClientInformationFull

        client = OAuthClientInformationFull.model_validate(
            {
                "client_id": "client-1",
                "client_secret": "secret-1",
                "redirect_uris": ["https://client.example/callback"],
                "scope": "dotmd",
            }
        )
        await provider.register_client(client)
        return provider

    provider = asyncio.run(setup())
    monkeypatch.setattr(mcp_server, "_provider", provider)
    app = Starlette(
        routes=[
            Route("/authorize", authorize, methods=["GET"]),
            Route("/authorize", authorize_pairing_code, methods=["POST"]),
        ]
    )
    query = urlencode(
        {
            "response_type": "code",
            "client_id": "client-1",
            "redirect_uri": "https://client.example/callback",
            "scope": "dotmd",
            "state": "state-1",
            "code_challenge": "challenge-1",
            "code_challenge_method": "S256",
        }
    )

    get_response = TestClient(app).get(f"/authorize?{query}")

    assert get_response.status_code == 200
    assert "text/html" in get_response.headers["content-type"]
    assert "Pairing code" in get_response.text


def test_authorize_pairing_code_activates_client_and_redirects(tmp_path, monkeypatch) -> None:
    async def setup() -> tuple[DotMDOAuthProvider, str]:
        provider = DotMDOAuthProvider(tmp_path / "oauth_state.json")
        from mcp.shared.auth import OAuthClientInformationFull

        client = OAuthClientInformationFull.model_validate(
            {
                "client_id": "client-1",
                "client_secret": "secret-1",
                "redirect_uris": ["https://client.example/callback"],
                "scope": "dotmd",
            }
        )
        await provider.register_client(client)
        code, _ = await provider.create_pairing_code(ttl_seconds=60)
        return provider, code

    provider, code = asyncio.run(setup())
    monkeypatch.setattr(mcp_server, "_provider", provider)
    app = Starlette(routes=[Route("/authorize", authorize_pairing_code, methods=["POST"])])
    query = urlencode(
        {
            "response_type": "code",
            "client_id": "client-1",
            "redirect_uri": "https://client.example/callback",
            "scope": "dotmd",
            "state": "state-1",
            "code_challenge": "challenge-1",
            "code_challenge_method": "S256",
        }
    )

    response = TestClient(app).post(
        f"/authorize?{query}", data={"pairing_code": code}, follow_redirects=False
    )

    assert response.status_code == 302
    assert response.headers["location"].startswith("https://client.example/callback?")
    assert asyncio.run(provider.get_client("client-1")) is not None
