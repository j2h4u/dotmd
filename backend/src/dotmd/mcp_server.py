"""MCP server for dotMD — exposes markdown knowledgebase search as MCP tools."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field, model_serializer
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from dotmd.api.service import DotMDService
from dotmd.auth import DotMDOAuthProvider
from dotmd.core.config import Settings
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


class SearchHit(BaseModel):
    file_paths: list[str]
    heading: str | None = None
    snippet: str
    score: float

    @model_serializer
    def _serialize(self) -> dict:
        d: dict = {"file_paths": self.file_paths, "snippet": self.snippet, "score": self.score}
        if self.heading:
            d["heading"] = self.heading
        return d


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
    file_path: str
    total_chunks: int
    frontmatter: dict[str, Any]
    chunks: list[ReadChunk] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

_INSTRUCTIONS = """\
Search a personal markdown knowledgebase — notes, meeting transcripts, voice notes, documentation, project files.

Key workflows:
SEARCH THEN READ: Use search to locate relevant chunks by topic. Once you know which file matters, use read to consume its content by chunk range — don't keep spinning search queries against a file you've already identified.
READ IN STEPS: Call read without an end parameter first to get frontmatter and total_chunks, then request ranges. Long transcripts won't fit in one call — plan your ranges.

Use feedback immediately when a tool response is wrong, surprising, or missing a useful capability — don't wait until end of session.\
"""

_base_url: str = os.environ.get("DOTMD_BASE_URL", "").rstrip("/")

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


def _get_service() -> DotMDService:
    if _service is None:
        raise RuntimeError("Service not initialized — server not started via create_app() or _init_for_stdio()")
    return _service


def _get_feedback() -> FeedbackStore:
    if _feedback is None:
        raise RuntimeError("Feedback store not initialized — server not started via create_app() or _init_for_stdio()")
    return _feedback


def _init_for_stdio() -> None:
    """Initialize service for the stdio transport path (no trickle, no warmup).

    The stdio entry point (``dotmd mcp``) calls ``mcp_app.run()`` directly,
    bypassing ``create_app()``.  Call this before ``mcp_app.run()`` to set up
    the service so tool handlers can reach it via ``_get_service()``.

    Warmup is intentionally skipped: it blocks for 10-15s while loading ML
    models, which causes MCP clients (Claude Desktop) to timeout before the
    ``initialize`` handshake completes.  Models load lazily on first use.
    """
    global _service, _feedback
    settings = Settings()
    _service = DotMDService(settings)
    _feedback = FeedbackStore(settings.index_dir / "feedback.db")


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

        settings = Settings()
        svc = DotMDService(settings)
        # warmup() is CPU/disk-bound; run in thread to keep event loop free
        await asyncio.to_thread(svc.warmup)
        _service = svc
        _feedback = FeedbackStore(settings.index_dir / "feedback.db")

        shutdown_event = asyncio.Event()
        indexer_task = asyncio.create_task(svc.trickle_indexer.run(shutdown_event))

        # session_manager.run() initialises the task group that handles all
        # MCP HTTP sessions — must stay alive for the full server lifetime.
        async with mcp.session_manager.run():
            yield

        shutdown_event.set()
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

    return Starlette(
        debug=mcp.settings.debug,
        routes=mcp_starlette.routes,
        middleware=mcp_starlette.user_middleware,
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
) -> list[SearchHit]:
    """Search the indexed markdown knowledgebase and return ranked chunks.

    Use proactively whenever the user asks about notes, meetings, decisions, people,
    projects, or anything that may have been written down. Prefer search over
    relying on your own knowledge for facts about this person's work or life.

    Each result contains: file_paths (source files sharing this chunk), a
    cleaned text snippet, a relevance score, and an optional heading (present
    only for structured docs with markdown headings).

    Once search identifies a relevant file, switch to read for deeper access.
    Do not call search for general knowledge questions that don't involve the
    user's personal notes or project files.
    """
    if not query.strip():
        return []
    try:
        service = _get_service()
        results = await asyncio.to_thread(service.search, query, top_k=top_k)
        return [_format_result(r) for r in results]
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
    file_path: Annotated[str, Field(description="Absolute file path from a search result.")],
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
    """Read chunks from a known file by index range.

    Use after search has identified a relevant file. Always returns frontmatter
    and total_chunks. When end is provided, also returns chunk text for indices
    [start, end) — capped at 50 chunks per call.

    Recommended workflow:
    1. Call read(file_path) without end to get frontmatter and total_chunks.
    2. Request ranges as needed: read(file_path, 0, 20), read(file_path, 20, 40), etc.

    Only pass file_paths values from search results.
    """
    try:
        service = _get_service()
        result = await asyncio.to_thread(service.read, file_path, start, end)
        chunks = [
            ReadChunk(
                index=c["index"],
                heading=" > ".join(c["heading_hierarchy"]) if c["heading_hierarchy"] else None,
                text=c["text"],
            )
            for c in result["chunks"]
        ]
        return ReadResult(
            file_path=result["file_path"],
            total_chunks=result["total_chunks"],
            frontmatter=result["frontmatter"],
            chunks=chunks,
        )
    except Exception as exc:
        logger.error("read failed: file_path=%r", file_path, exc_info=True)
        raise RuntimeError(
            f"Read failed for {file_path!r}: {exc}. "
            "Action: verify the file_path comes from a search result."
        ) from exc


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


def _format_result(r: Any) -> SearchHit:
    clean = _FRONTMATTER_RE.sub("", r.snippet).strip()
    clean = _TIMESTAMP_RE.sub("", clean).strip()

    return SearchHit(
        file_paths=[str(p) for p in r.file_paths],
        heading=r.heading_path or None,
        snippet=clean,
        score=round(r.fused_score, 3),
    )


if __name__ == "__main__":
    mcp.run()
