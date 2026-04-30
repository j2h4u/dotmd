from __future__ import annotations

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from dotmd import mcp_server
from dotmd.mcp_server import (
    _AccessLogMiddleware,
    _oauth_metadata_response,
    _oauth_protected_resource_response,
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


def test_oauth_metadata_explicitly_disables_authorization_iss(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_base_url", "https://dotmd.example")

    response = _oauth_metadata_response()

    assert response.status_code == 200
    assert b'"issuer":"https://dotmd.example"' in response.body
    assert b'"authorization_response_iss_parameter_supported":false' in response.body


def test_oauth_protected_resource_metadata_includes_scopes(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server, "_base_url", "https://dotmd.example")

    response = _oauth_protected_resource_response()

    assert response.status_code == 200
    assert b'"resource":"https://dotmd.example/mcp"' in response.body
    assert b'"authorization_servers":["https://dotmd.example"]' in response.body
    assert b'"scopes_supported":["dotmd"]' in response.body
