"""MCP server for dotMD — exposes markdown knowledgebase search as MCP tools."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from dotmd.api.service import DotMDService
from dotmd.core.config import Settings
from dotmd.core.models import IndexStats
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
    heading: str
    snippet: str
    score: float


class DrillResult(BaseModel):
    file_path: str
    frontmatter: dict[str, Any]
    chunk_count: int
    entities: list[str]


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

_INSTRUCTIONS = """\
Search a personal markdown knowledgebase — notes, meeting transcripts, voice notes, documentation, project files.

Key workflows:
SEARCH THEN DRILL: Use Search to locate relevant chunks. Use Drill(file_path=...) on any result to read full frontmatter and extracted entities before drawing conclusions from a snippet alone.
CHECK BEFORE CONCLUDING: Before telling the user a topic is not in the knowledgebase, call GetStatus to verify indexing is complete — the trickle indexer may still be running.

Use SubmitFeedback immediately when a tool response is wrong, surprising, or missing a useful capability — don't wait until end of session.\
"""

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
        lifespan=_server_lifespan,
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool(
    name="Search",
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
    projects, or anything that may have been written down. Prefer Search over
    relying on your own knowledge for facts about this person's work or life.

    Each result contains: file_paths (source files sharing this chunk), heading
    context, a cleaned text snippet, and a relevance score. Use Drill on any
    result to get full frontmatter and entity context before drawing conclusions.

    Do not call Search for general knowledge questions that don't involve the
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
        raise RuntimeError(
            f"Search failed: {exc}. "
            "Action: call GetStatus to check if the index is healthy and trickle indexer is running."
        ) from exc


@mcp.tool(
    name="Drill",
    annotations=ToolAnnotations(
        title="Drill Into Document",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def drill(
    file_path: Annotated[
        str,
        Field(description="Absolute file path from a search() result. Pass file_paths[0] from any search hit."),
    ],
) -> DrillResult:
    """Read metadata for a file returned by search().

    Use after Search to get full context before drawing conclusions from a snippet.
    Returns frontmatter fields (title, date, tags, speaker, etc.), number of indexed
    chunks, and entity names extracted from the file's knowledge graph nodes.

    Only pass file_paths values from Search results — passing arbitrary paths
    will return empty results if the file is not indexed.
    """
    try:
        service = _get_service()
        result = await asyncio.to_thread(service.drill, file_path)
        return DrillResult(**result)
    except Exception as exc:
        logger.error("drill failed: file_path=%r", file_path, exc_info=True)
        raise RuntimeError(
            f"Drill failed for {file_path!r}: {exc}. "
            "Action: verify the file_path comes from a Search result. "
            "Call GetStatus to check index health."
        ) from exc


@mcp.tool(
    name="GetStatus",
    annotations=ToolAnnotations(
        title="Index Status",
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def status() -> IndexStats:
    """Return current index statistics and trickle indexer progress.

    Use proactively before concluding that a topic or file is not in the
    knowledgebase — the trickle indexer may still be processing files.
    Also useful for checking total file and chunk counts, indexing speed,
    and estimated time to completion.
    """
    try:
        service = _get_service()
        return await asyncio.to_thread(service.status, live_diff=False)
    except Exception as exc:
        logger.error("status failed", exc_info=True)
        raise RuntimeError(
            f"Status check failed: {exc}. "
            "Action: retry in a few seconds; if the error persists, the index may be corrupted."
        ) from exc


@mcp.tool(
    name="SubmitFeedback",
    annotations=ToolAnnotations(
        title="Submit Feedback",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
async def submit_feedback(
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
        feedback = _get_feedback()
        await asyncio.to_thread(
            feedback.submit,
            message=message.strip(),
            severity=severity,
            context=context,
            model=model,
            harness=harness,
        )
        return "Feedback recorded."
    except Exception as exc:
        logger.error("submit_feedback failed", exc_info=True)
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
    snippet = r.snippet

    title = ""
    if snippet.startswith("---"):
        end = snippet.find("---", 3)
        if end != -1:
            for line in snippet[3:end].split("\n"):
                stripped = line.strip()
                if stripped.startswith("title:"):
                    title = stripped[6:].strip().strip("'\"")
                    break

    clean = _FRONTMATTER_RE.sub("", snippet).strip()
    clean = _TIMESTAMP_RE.sub("", clean).strip()

    return SearchHit(
        file_paths=[str(p) for p in r.file_paths],
        heading=r.heading_path or title,
        snippet=clean,
        score=round(r.fused_score, 3),
    )


if __name__ == "__main__":
    mcp.run()
