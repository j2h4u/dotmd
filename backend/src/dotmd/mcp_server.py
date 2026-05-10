"""MCP server for dotMD — exposes markdown knowledgebase search as MCP tools."""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import parse_qs

from mcp.server.auth.handlers.authorize import AuthorizationRequest
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, model_serializer
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from dotmd.api.service import DotMDService
from dotmd.auth import DotMDOAuthProvider, PairingCodeError
from dotmd.core.config import load_runtime_settings
from dotmd.core.models import SearchCandidate, SearchResponse
from dotmd.feedback import FeedbackStore

logger = logging.getLogger(__name__)

_service: DotMDService | None = None
_feedback: FeedbackStore | None = None

# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------


def _collapse_null(schema: dict) -> None:
    """Strip null variant from anyOf and remove default: null.

    Pydantic v2 serialises `T | None` as `anyOf: [T, null]` which breaks
    Claude Desktop's tool parameter rendering.  Applied as json_schema_extra
    on Optional parameters to collapse the schema to just the non-null type.
    """
    if "anyOf" not in schema:
        schema.pop("default", None)
        return
    non_null = [s for s in schema["anyOf"] if s.get("type") != "null"]
    preserved = {k: v for k, v in schema.items() if k not in ("anyOf", "default")}
    if len(non_null) == 1:
        schema.clear()
        schema.update(non_null[0])
        schema.update(preserved)
    elif non_null:
        schema["anyOf"] = non_null
        schema.pop("default", None)
    else:
        schema.pop("default", None)


# ---------------------------------------------------------------------------
# Output models (enable outputSchema auto-generation)
# ---------------------------------------------------------------------------


class ReadChunk(BaseModel):
    index: int
    heading: str | None = None
    text: str

    @model_serializer
    def _serialize(self) -> dict:
        d: dict = {"index": self.index, "text": self.text}
        if self.heading:
            d["heading"] = self.heading
        return d


class ReadResult(BaseModel):
    ref: str
    total_chunks: int
    frontmatter: dict[str, Any]
    chunks: list[ReadChunk] = Field(default_factory=list)


class DrillResult(BaseModel):
    ref: str
    title: str | None = None
    source_uri: str | None = None
    document_type: str | None = None
    parser_name: str | None = None
    frontmatter: dict[str, Any]
    total_chunks: int


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

_INSTRUCTIONS = """\
Search a personal markdown knowledgebase — notes, meeting transcripts, voice notes, documentation, project files.

Key workflows:
SEARCH THEN DRILL/READ: Use search(query) -> ref to locate relevant chunks by topic. Use drill(ref) for metadata and read(ref, start, end) for chunk text — don't keep spinning search queries against a source you've already identified.
READ IN STEPS: Call read(ref) without an end parameter first to get frontmatter and total_chunks, then request ranges. Long transcripts won't fit in one call — plan your ranges.

Use feedback immediately when a tool response is wrong, surprising, or missing a useful capability — don't wait until end of session.\
"""

_base_url: str = os.environ.get("DOTMD_BASE_URL", "").rstrip("/")
_ACCESS_LOG_PATH = Path(os.environ.get("DOTMD_ACCESS_LOG_PATH", "/dotmd-index/logs/access.log"))

_provider: DotMDOAuthProvider | None = None
if _base_url:
    _provider = DotMDOAuthProvider(Path("/dotmd-index/oauth_state.json"))


def _auth_settings(base_url: str) -> AuthSettings:
    return AuthSettings.model_validate(
        {
            "issuer_url": base_url,
            "resource_server_url": f"{base_url}/mcp",
            "client_registration_options": ClientRegistrationOptions(
                enabled=True,
                valid_scopes=["dotmd"],
                default_scopes=["dotmd"],
            ),
        }
    )


class _AccessLogMiddleware(BaseHTTPMiddleware):
    """Log MCP HTTP requests after upstream proxies have rewritten paths."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        t0 = time.perf_counter()
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        body = await self._body_for_logging(request)
        summary = self._request_summary(request, body)
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        client = request.client.host if request.client else "-"
        path = request.url.path
        if request.url.query:
            path = f"{path}?{request.url.query}"
        log = logger.error if response.status_code >= 500 else logger.info
        log(
            "HTTP %s %s %d %.0fms client=%s",
            request.method,
            path,
            response.status_code,
            elapsed_ms,
            client,
        )
        self._write_jsonl(
            {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "request_id": request_id,
                "method": request.method,
                "path": str(request.url.path),
                "query": str(request.url.query),
                "status": response.status_code,
                "duration_ms": round(elapsed_ms, 3),
                "client": client,
                "user_agent": request.headers.get("user-agent"),
                "origin": request.headers.get("origin"),
                "referer": request.headers.get("referer"),
                "accept": request.headers.get("accept"),
                "content_type": request.headers.get("content-type"),
                "request": summary,
                "response": self._response_summary(response),
            }
        )
        return response

    async def _body_for_logging(self, request: Request) -> bytes | None:
        if request.url.path not in {"/register", "/token", "/mcp"}:
            return None
        try:
            body = await request.body()
        except Exception:
            return None

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": body, "more_body": False}

        # BaseHTTPMiddleware does not guarantee downstream handlers can reread
        # form bodies after middleware consumes them. Replay the exact bytes so
        # OAuth token parsing still sees client_id/code/code_verifier.
        request._receive = receive  # type: ignore[method-assign]
        return body

    def _request_summary(self, request: Request, body: bytes | None) -> dict[str, Any] | None:
        if request.url.path == "/register":
            try:
                payload = json.loads((body or b"").decode("utf-8"))
            except Exception:
                return {"parse_error": "invalid_json"}
            if not isinstance(payload, dict):
                return {"type": type(payload).__name__}
            return {
                "client_name": payload.get("client_name"),
                "redirect_uris": payload.get("redirect_uris"),
                "grant_types": payload.get("grant_types"),
                "response_types": payload.get("response_types"),
                "scope": payload.get("scope"),
                "token_endpoint_auth_method": payload.get("token_endpoint_auth_method"),
            }
        if request.url.path == "/token":
            try:
                form = {key: values[-1] for key, values in parse_qs((body or b"").decode("utf-8")).items()}
            except Exception:
                return {"parse_error": "invalid_form"}
            return {
                "grant_type": form.get("grant_type"),
                "client_id": form.get("client_id"),
                "redirect_uri": form.get("redirect_uri"),
                "resource": form.get("resource"),
                "scope": form.get("scope"),
                "has_code": bool(form.get("code")),
                "has_code_verifier": bool(form.get("code_verifier")),
                "has_client_secret": bool(form.get("client_secret")),
                "has_refresh_token": bool(form.get("refresh_token")),
            }
        if request.url.path == "/mcp" and request.method == "POST":
            try:
                payload = json.loads((body or b"").decode("utf-8"))
            except Exception:
                return None
            if isinstance(payload, dict):
                params = payload.get("params")
                return {
                    "jsonrpc_method": payload.get("method"),
                    "jsonrpc_id": payload.get("id"),
                    "tool_name": params.get("name") if isinstance(params, dict) else None,
                }
        return None

    def _response_summary(self, response: Response) -> dict[str, Any]:
        return {
            "location": response.headers.get("location"),
            "www_authenticate": response.headers.get("www-authenticate"),
            "mcp_session_id": response.headers.get("mcp-session-id"),
        }

    def _write_jsonl(self, record: dict[str, Any]) -> None:
        try:
            _ACCESS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with _ACCESS_LOG_PATH.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        except Exception:
            logger.exception("Failed to write access log: %s", _ACCESS_LOG_PATH)


mcp = FastMCP(
    "dotmd",
    instructions=_INSTRUCTIONS,
    host="0.0.0.0",
    port=8080,
    # json_response=True: tool call responses returned as JSON in the POST body
    # instead of SSE. More reliable — avoids a mcp 1.27.0 SSE delivery bug where
    # message_router drops responses when the zero-buffer stream isn't consumed
    # in time. MCP spec allows both; clients send Accept: application/json, text/event-stream.
    json_response=True,
    stateless_http=True,
    # No lifespan= here — FastMCP's lifespan fires per MCP session (once per client
    # connection for stateless HTTP), not once per server process.
    # - HTTP: server-wide init (service + trickle) lives in create_app() below.
    # - stdio: caller must invoke _init_for_stdio() before mcp_app.run().
    auth_server_provider=_provider,
    auth=_auth_settings(_base_url) if _base_url else None,
)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


@mcp.custom_route("/", methods=["GET"])
async def root(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "dotmd"})


def _pairing_form(request: Request, *, error: str | None = None) -> Response:
    action = html.escape(str(request.url), quote=True)
    error_html = ""
    if error:
        error_html = f'<p class="error">{html.escape(error)}</p>'
    return Response(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>dotMD OAuth pairing</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 34rem; margin: 12vh auto; padding: 0 1rem; }}
    label {{ display: block; font-weight: 600; margin-bottom: .5rem; }}
    input {{ box-sizing: border-box; width: 100%; font: inherit; padding: .7rem .8rem; text-transform: uppercase; }}
    button {{ font: inherit; margin-top: 1rem; padding: .65rem 1rem; }}
    .error {{ color: #b00020; }}
  </style>
</head>
<body>
  <h1>dotMD pairing code</h1>
  <p>Enter the one-time code generated on the dotMD server.</p>
  {error_html}
  <form method="post" action="{action}">
    <label for="pairing_code">Pairing code</label>
    <input id="pairing_code" name="pairing_code" autocomplete="one-time-code" autofocus required>
    <button type="submit">Continue</button>
  </form>
</body>
</html>""",
        media_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


async def _redirect_for_authorization(request: Request, *, pairing_code: str | None = None) -> Response:
    if _provider is None:
        return JSONResponse({"error": "OAuth is not configured"}, status_code=404)

    auth_request = AuthorizationRequest.model_validate(request.query_params)
    client = await _provider.get_client(auth_request.client_id)
    if client is None:
        client = await _provider.get_pending_client(auth_request.client_id)
        if client is None:
            return JSONResponse({"error": "invalid_request", "error_description": "Unknown client_id"}, status_code=400)
        if pairing_code is None:
            return _pairing_form(request)
        await _provider.activate_pending_client(client, pairing_code)
    redirect_uri = client.validate_redirect_uri(auth_request.redirect_uri)
    scopes = client.validate_scope(auth_request.scope)
    from mcp.server.auth.provider import AuthorizationParams

    auth_params = AuthorizationParams(
        state=auth_request.state,
        scopes=scopes,
        code_challenge=auth_request.code_challenge,
        redirect_uri=redirect_uri,
        redirect_uri_provided_explicitly=auth_request.redirect_uri is not None,
        resource=auth_request.resource,
    )
    return RedirectResponse(
        url=await _provider.authorize(client, auth_params),
        status_code=302,
        headers={"Cache-Control": "no-store"},
    )


@mcp.custom_route("/authorize", methods=["GET"])
async def authorize(request: Request) -> Response:
    """Authorize an OAuth client, prompting for a one-time code if needed."""
    try:
        return await _redirect_for_authorization(request)
    except Exception as exc:
        logger.exception("OAuth authorize failed")
        return JSONResponse(
            {"error": "invalid_request", "error_description": str(exc)},
            status_code=400,
            headers={"Cache-Control": "no-store"},
        )


@mcp.custom_route("/authorize", methods=["POST"])
async def authorize_pairing_code(request: Request) -> Response:
    """Activate a pending OAuth client with a one-time pairing code."""
    try:
        form = await request.form()
        pairing_code = str(form.get("pairing_code", ""))
        return await _redirect_for_authorization(request, pairing_code=pairing_code)
    except PairingCodeError as exc:
        logger.warning("OAuth pairing failed: %s", exc)
        return _pairing_form(request, error=str(exc))
    except Exception as exc:
        logger.exception("OAuth authorize failed")
        return JSONResponse(
            {"error": "invalid_request", "error_description": str(exc)},
            status_code=400,
            headers={"Cache-Control": "no-store"},
        )


def _oauth_metadata_response() -> JSONResponse:
    if not _base_url:
        return JSONResponse({"error": "OAuth is not configured"}, status_code=404)
    return JSONResponse(
        {
            "issuer": _base_url,
            "authorization_endpoint": f"{_base_url}/authorize",
            "token_endpoint": f"{_base_url}/token",
            "registration_endpoint": f"{_base_url}/register",
            "scopes_supported": ["dotmd"],
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
            "code_challenge_methods_supported": ["S256"],
            "authorization_response_iss_parameter_supported": True,
        },
        headers={"Cache-Control": "public, max-age=3600"},
    )


@mcp.custom_route("/.well-known/oauth-authorization-server", methods=["GET"])
async def oauth_authorization_server(request: Request) -> JSONResponse:
    """OAuth authorization server metadata with ChatGPT-compatible public-client auth."""
    return _oauth_metadata_response()


def _oauth_protected_resource_response() -> JSONResponse:
    if not _base_url:
        return JSONResponse({"error": "OAuth is not configured"}, status_code=404)
    return JSONResponse(
        {
            "resource": f"{_base_url}/mcp",
            "authorization_servers": [_base_url],
            "scopes_supported": ["dotmd"],
            "bearer_methods_supported": ["header"],
        },
        headers={"Cache-Control": "public, max-age=3600"},
    )


@mcp.custom_route("/.well-known/oauth-protected-resource/mcp", methods=["GET"])
async def oauth_protected_resource_mcp(request: Request) -> JSONResponse:
    """Protected-resource metadata for the canonical /mcp resource URL."""
    return _oauth_protected_resource_response()


def _get_service() -> DotMDService:
    if _service is None:
        raise RuntimeError("Service not initialized — server not started via create_app() or _init_for_stdio()")
    return _service


def _get_feedback() -> FeedbackStore:
    if _feedback is None:
        raise RuntimeError("Feedback store not initialized — server not started via create_app() or _init_for_stdio()")
    return _feedback


def _ref_tool_error(tool_name: str, ref: str, exc: ValueError) -> RuntimeError:
    return RuntimeError(
        f"{tool_name} failed for ref {ref!r}: {exc}. "
        "Action: pass a ref returned by search."
    )


def init_service() -> None:
    """Initialize service for the stdio transport path (no trickle, no warmup).

    The stdio entry point (``dotmd mcp``) calls ``mcp_app.run()`` directly,
    bypassing ``create_app()``.  Call this before ``mcp_app.run()`` to set up
    the service so tool handlers can reach it via ``_get_service()``.

    Warmup is intentionally skipped: it blocks for 10-15s while loading ML
    models, which causes MCP clients (Claude Desktop) to timeout before the
    ``initialize`` handshake completes.  Models load lazily on first use.
    """
    global _service, _feedback
    settings = load_runtime_settings()
    _service = DotMDService(settings)
    _feedback = FeedbackStore(settings.index_dir / "feedback.db")


_init_for_stdio = init_service


async def _run_telegram_poller(
    svc: DotMDService,
    bundle: Any,
    interval_seconds: float,
    shutdown_event: asyncio.Event,
) -> None:
    """Background Telegram sync task — cursor-based polling at fixed interval."""
    loop = asyncio.get_running_loop()
    while not shutdown_event.is_set():
        try:
            result = await loop.run_in_executor(
                svc._local_executor,
                lambda: svc._pipeline.ingest_application_source_runtime(bundle),
            )
            logger.info(
                "telegram_sync discovered=%d new=%d changed=%d skipped=%d "
                "rebound=%d failed=%d reused=%d",
                result.discovered,
                result.new_units,
                result.changed_units,
                result.skipped_units,
                result.rebound_units,
                result.failed_units,
                result.reused_units,
            )
        except Exception:
            logger.exception("telegram_sync error during ingest")
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass


def create_app() -> Starlette:
    """Build the Starlette ASGI app with a server-wide lifespan.

    FastMCP's ``lifespan=`` parameter fires per MCP session (once per client
    connection), not once for the server process.  This function composes a
    proper server-wide lifespan that:
      1. Initialises DotMDService and warms up ML models once at startup.
      2. Starts the trickle background indexer as a long-running asyncio task.
      3. Wraps the FastMCP session manager so its task group is live for the
         full server lifetime.
    """
    # streamable_http_app() lazy-creates mcp._session_manager and returns a
    # Starlette app whose lifespan is session_manager.run().  We copy its
    # routes but replace the lifespan with our own composed version.
    mcp_starlette = mcp.streamable_http_app()

    @asynccontextmanager
    async def _server_lifespan(app: Starlette) -> AsyncIterator[None]:
        global _service, _feedback

        settings = load_runtime_settings()
        svc = DotMDService(settings)
        # warmup() is CPU/disk-bound; run in thread to keep event loop free
        await asyncio.to_thread(svc.warmup)
        _service = svc
        _feedback = FeedbackStore(settings.index_dir / "feedback.db")

        shutdown_event = asyncio.Event()
        indexer_task = asyncio.create_task(svc.trickle_indexer.run(shutdown_event))

        telegram_task: asyncio.Task | None = None
        telegram_bundle = svc._source_runtime_factory.build_if_configured("telegram")
        if telegram_bundle is not None:
            telegram_task = asyncio.create_task(
                _run_telegram_poller(
                    svc,
                    telegram_bundle,
                    settings.telegram_sync_interval_seconds,
                    shutdown_event,
                )
            )

        # session_manager.run() initialises the task group that handles all
        # MCP HTTP sessions — must stay alive for the full server lifetime.
        async with mcp.session_manager.run():
            yield

        shutdown_event.set()
        if telegram_task is not None:
            try:
                await asyncio.wait_for(telegram_task, timeout=30)
            except TimeoutError:
                logger.warning("Telegram poller did not stop within 30s — cancelling")
                telegram_task.cancel()
                with suppress(asyncio.CancelledError):
                    await telegram_task
            except Exception:
                logger.exception("Telegram poller task failed during shutdown")
        try:
            await asyncio.wait_for(indexer_task, timeout=120)
        except TimeoutError:
            logger.warning("Trickle indexer did not stop within 120s -- cancelling")
            indexer_task.cancel()
            with suppress(asyncio.CancelledError):
                await indexer_task
        except Exception:
            logger.exception("Trickle indexer task failed during shutdown")
        _service = None
        _feedback = None

    routes = [
        Route(
            "/.well-known/oauth-authorization-server",
            oauth_authorization_server,
            methods=["GET"],
        ),
        Route(
            "/.well-known/oauth-protected-resource/mcp",
            oauth_protected_resource_mcp,
            methods=["GET"],
        ),
        Route(
            "/authorize",
            authorize,
            methods=["GET"],
        ),
        Route(
            "/authorize",
            authorize_pairing_code,
            methods=["POST"],
        ),
        *[
            route
            for route in mcp_starlette.routes
            if getattr(route, "path", None)
            not in {
                "/.well-known/oauth-authorization-server",
                "/.well-known/oauth-protected-resource/mcp",
                "/authorize",
            }
        ],
    ]

    return Starlette(
        debug=mcp.settings.debug,
        routes=routes,
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origin_regex=r"https://([a-zA-Z0-9-]+\.)?claude\.ai",
                allow_methods=["GET", "POST", "OPTIONS"],
                allow_headers=["*"],
                expose_headers=["WWW-Authenticate", "Mcp-Session-Id"],
            ),
            *mcp_starlette.user_middleware,
            Middleware(_AccessLogMiddleware),
        ],
        lifespan=_server_lifespan,
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool(
    name="search",
    annotations=ToolAnnotations(
        title="Search Knowledgebase",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def search(
    query: Annotated[str, Field(description="Natural-language search query.")],
    top_k: Annotated[int, Field(description="Maximum results to return.", ge=1, le=100)] = 10,
) -> SearchResponse:
    """Search the indexed markdown knowledgebase and return ranked chunks.

    Use proactively whenever the user asks about notes, meetings, decisions, people,
    projects, or anything that may have been written down. Prefer search over
    relying on your own knowledge for facts about this person's work or life.

    Each result contains: ref (the stable source key for read/drill), a cleaned
    text snippet, a relevance score, namespace, source kind, and optional metadata
    from the underlying source.

    Once search identifies a relevant file, switch to read for deeper access.
    Do not call search for general knowledge questions that don't involve the
    user's personal notes or project files.
    """
    if not query.strip():
        return SearchResponse()
    try:
        service = _get_service()
        # Per D-ASYNC-CANONICAL (cycle-2 HIGH-5): call search_async directly.
        # MCP tools already run inside the event loop; search_async is the
        # canonical async entry point.
        response = await service.search_async(query, top_k=top_k)
        # response is already a SearchResponse; format candidates for MCP output
        formatted_candidates = [_format_result(r) for r in response.candidates]
        return SearchResponse(candidates=formatted_candidates, source_status=response.source_status)
    except Exception as exc:
        logger.error("search failed: query=%r", query[:100], exc_info=True)
        raise RuntimeError(f"Search failed: {exc}.") from exc


@mcp.tool(
    name="read",
    annotations=ToolAnnotations(
        title="Read Document",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def read_document(
    ref: Annotated[str, Field(description="Source ref from a search result.")],
    start: Annotated[int, Field(description="First chunk index to return (0-based).", ge=0)] = 0,
    end: Annotated[
        int | None,
        Field(
            description="Exclusive end chunk index. Omit to return only frontmatter and total_chunks without chunk text. Capped at start+50.",
            ge=1,
            json_schema_extra=_collapse_null,
        ),
    ] = None,
) -> ReadResult:
    """Read chunks from a known source ref by index range.

    Use after search has identified a relevant ref. Always returns frontmatter
    and total_chunks. When end is provided, also returns chunk text for indices
    [start, end) — capped at 50 chunks per call.

    Recommended workflow:
    1. Call read(ref) without end to get frontmatter and total_chunks.
    2. Request ranges as needed: read(ref, 0, 20), read(ref, 20, 40), etc.

    Agent workflow: search(query) -> ref, drill(ref), read(ref, start, end).
    Only pass ref values from search results.
    """
    try:
        service = _get_service()
        result = await asyncio.to_thread(service.read, ref, start, end)
        chunks = [
            ReadChunk(
                index=c["index"],
                heading=" > ".join(c["heading_hierarchy"]) if c["heading_hierarchy"] else None,
                text=c["text"],
            )
            for c in result["chunks"]
        ]
        return ReadResult(
            ref=result["ref"],
            total_chunks=result["total_chunks"],
            frontmatter=result["frontmatter"],
            chunks=chunks,
        )
    except ValueError as exc:
        logger.warning("read ref rejected: ref=%r error=%s", ref, exc)
        raise _ref_tool_error("read", ref, exc) from exc
    except Exception as exc:
        logger.error("read failed: ref=%r", ref, exc_info=True)
        raise RuntimeError("Read failed. Action: retry later or submit feedback with the ref.") from exc


@mcp.tool(
    name="drill",
    annotations=ToolAnnotations(
        title="Drill Source Metadata",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def drill(
    ref: Annotated[str, Field(description="Source ref from a search result.")],
) -> DrillResult:
    """Return source metadata for a search result ref.

    Agent workflow: search(query) -> ref, drill(ref), read(ref, start, end).
    Use drill(ref) after search when you need frontmatter, source metadata, or
    total chunk count before deciding which chunk ranges to read.
    """
    try:
        service = _get_service()
        result = await asyncio.to_thread(service.drill, ref)
        return DrillResult(
            ref=result["ref"],
            title=result.get("title"),
            source_uri=result.get("source_uri"),
            document_type=result.get("document_type"),
            parser_name=result.get("parser_name"),
            frontmatter=result["frontmatter"],
            total_chunks=result["total_chunks"],
        )
    except ValueError as exc:
        logger.warning("drill ref rejected: ref=%r error=%s", ref, exc)
        raise _ref_tool_error("drill", ref, exc) from exc
    except Exception as exc:
        logger.error("drill failed: ref=%r", ref, exc_info=True)
        raise RuntimeError("Drill failed. Action: retry later or submit feedback with the ref.") from exc


@mcp.tool(
    name="feedback",
    annotations=ToolAnnotations(
        title="Submit Feedback",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
async def feedback(
    message: Annotated[
        str,
        Field(description="What was observed; ideally include what you expected instead.", min_length=1, max_length=10000),
    ],
    severity: Annotated[
        Literal["bug", "suggestion", "question"] | None,
        Field(description="bug — wrong output or violated contract; suggestion — new capability or UX improvement; question — unclear how something works.", json_schema_extra=_collapse_null),
    ] = None,
    context: Annotated[
        str | None,
        Field(description="Which tool, what arguments, or what task you were trying to accomplish.", max_length=2000, json_schema_extra=_collapse_null),
    ] = None,
    model: Annotated[
        str | None,
        Field(description="Your model name, e.g. claude-opus-4-7.", max_length=200, json_schema_extra=_collapse_null),
    ] = None,
    harness: Annotated[
        str | None,
        Field(description="Client or environment, e.g. Claude Desktop, Cursor.", max_length=200, json_schema_extra=_collapse_null),
    ] = None,
) -> str:
    """Send feedback to the knowledgebase maintainer.

    Use this proactively whenever you notice:
    - A tool returned unexpected, wrong, or unhelpful output
    - An error message was unclear and didn't help you fix the situation
    - A capability you needed didn't exist
    - A tool's behaviour contradicted its description

    Fire and forget — there is no follow-up, no tracking ID, and no read access
    for agents. The maintainer reviews the queue asynchronously.
    """
    if not message.strip():
        return "Feedback not recorded — message was empty."
    try:
        fb = _get_feedback()
        await asyncio.to_thread(
            fb.submit,
            message=message.strip(),
            severity=severity,
            context=context,
            model=model,
            harness=harness,
        )
        return "Feedback recorded."
    except Exception as exc:
        logger.error("feedback failed", exc_info=True)
        raise RuntimeError(
            f"Failed to record feedback: {exc}. "
            "Action: the feedback was not saved; you may retry or note the issue in your response to the user."
        ) from exc


# ---------------------------------------------------------------------------
# Result formatting helpers
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n?", re.DOTALL)
_TIMESTAMP_RE = re.compile(r"\[\d{2}:\d{2}:\d{2}\]\s*")


def _format_result(r: SearchCandidate) -> SearchCandidate:
    """Clean up snippet for MCP serialization.

    The SearchCandidate model preserves full precision on fused_score.
    For wire format, we round to 3 decimals to reduce payload size,
    but the canonical model retains full precision.
    """
    clean = _FRONTMATTER_RE.sub("", r.snippet).strip()
    clean = _TIMESTAMP_RE.sub("", clean).strip()

    # Return a new SearchCandidate with cleaned snippet
    # Note: frozen=True prevents modification, so we must reconstruct
    # Keep fused_score at full precision; JSON serialization handles rounding if needed
    return SearchCandidate(
        ref=r.ref,
        namespace=r.namespace,
        descriptor_key=r.descriptor_key,
        source_kind=r.source_kind,
        retrieval_kind=r.retrieval_kind,
        snippet=clean,
        fused_score=r.fused_score,
        can_read=r.can_read,
        can_materialize=r.can_materialize,
        title=r.title,
        chunk_id=r.chunk_id,
        heading_path=r.heading_path,
        provenance=r.provenance,
        matched_engines=r.matched_engines,
        source_native_score=r.source_native_score,
        source_native_rank=r.source_native_rank,
        engine_scores=r.engine_scores,
        provider_metadata=r.provider_metadata,
    )


if __name__ == "__main__":
    mcp.run()
