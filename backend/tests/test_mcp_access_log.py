from __future__ import annotations

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from dotmd import mcp_server
from dotmd.mcp_server import _AccessLogMiddleware


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
