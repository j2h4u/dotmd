"""MCP server for dotMD — exposes markdown knowledgebase search as MCP tools."""

from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from typing import Annotated, AsyncIterator

from mcp.server.fastmcp import FastMCP
from pydantic import Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from dotmd.api.service import DotMDService
from dotmd.core.config import Settings

logger = logging.getLogger(__name__)

_service: DotMDService | None = None

mcp = FastMCP(
    "dotmd",
    instructions=(
        "Search a personal markdown knowledgebase containing notes, meeting transcripts, "
        "voice notes, documentation, and project files. "
        "Use `search` to find relevant chunks by meaning or keyword. "
        "Use `status` to check how many files are indexed and whether indexing is in progress."
    ),
    host="0.0.0.0",
    port=8080,
    # json_response=True: tool call responses returned as JSON in the POST body
    # instead of SSE. More reliable — avoids a mcp 1.27.0 SSE delivery bug where
    # message_router drops responses when the zero-buffer stream isn't consumed
    # in time. MCP spec allows both; clients send Accept: application/json, text/event-stream.
    json_response=True,
    stateless_http=True,
    # No lifespan= here — FastMCP's lifespan fires per MCP session, not per server.
    # Server-wide init lives in create_app() below.
)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:  # noqa: ARG001
    return JSONResponse({"status": "ok"})


def _get_service() -> DotMDService:
    assert _service is not None, "Service not initialized — server not started via create_app()"
    return _service


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
    async def _server_lifespan(app: Starlette) -> AsyncIterator[None]:  # noqa: ARG001
        global _service  # noqa: PLW0603

        svc = DotMDService(Settings())
        # warmup() is CPU/disk-bound; run in thread to keep event loop free
        await asyncio.to_thread(svc.warmup)
        _service = svc

        shutdown_event = asyncio.Event()
        indexer_task = asyncio.create_task(svc.trickle_indexer.run(shutdown_event))

        # session_manager.run() initialises the task group that handles all
        # MCP HTTP sessions — must stay alive for the full server lifetime.
        async with mcp.session_manager.run():
            yield

        shutdown_event.set()
        try:
            await asyncio.wait_for(indexer_task, timeout=120)
        except asyncio.TimeoutError:
            logger.warning("Trickle indexer did not stop within 120s -- cancelling")
            indexer_task.cancel()
            try:
                await indexer_task
            except asyncio.CancelledError:
                pass
        except Exception:
            logger.exception("Trickle indexer task failed during shutdown")
        _service = None

    return Starlette(
        debug=mcp.settings.debug,
        routes=mcp_starlette.routes,
        lifespan=_server_lifespan,
    )


@mcp.tool(
    annotations={
        "title": "Search Knowledgebase",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def search(
    query: Annotated[str, Field(description="Natural-language search query.")],
    top_k: Annotated[int, Field(description="Maximum results to return.", ge=1, le=100)] = 10,
) -> list[dict]:
    """Search the indexed markdown knowledgebase and return ranked chunks.

    Each result includes the source file paths, heading context, a cleaned text
    snippet, a relevance score, and which search engines matched it.
    """
    service = _get_service()
    results = await asyncio.to_thread(service.search, query, top_k=top_k)
    return [_format_result(r) for r in results]


@mcp.tool(
    annotations={
        "title": "Drill Into Document",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def drill(
    file_path: Annotated[str, Field(description="Absolute file path from a search result.")],
) -> dict:
    """Retrieve metadata for a file returned by search.

    Returns frontmatter fields (title, date, tags, speaker, etc.), the number
    of indexed chunks, and entity names extracted from the file's graph nodes.
    Use this after search to understand the document's context before drawing
    conclusions from a snippet.
    """
    service = _get_service()
    return await asyncio.to_thread(service.drill, file_path)


@mcp.tool(
    annotations={
        "title": "Index Status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
async def status() -> dict:
    """Return current index statistics and trickle indexer progress.

    Useful for checking how many files and chunks are indexed, whether
    background indexing is active, and when the last file was indexed.
    """
    def _collect_stats() -> dict:
        service = _get_service()
        stats = service.status(live_diff=False).model_dump(mode="json")
        try:
            graph_store = service._pipeline.graph_store
            stats["total_entities"] = graph_store.node_count()
            stats["total_edges"] = graph_store.edge_count()
        except Exception:
            pass
        if not stats.get("last_indexed"):
            try:
                conn = service._pipeline.conn
                fp_table = f"chunk_fingerprints_{service._settings.chunk_strategy}"
                row = conn.execute(f"SELECT max(indexed_at) FROM {fp_table}").fetchone()
                if row and row[0]:
                    stats["last_indexed"] = row[0]
            except Exception:
                pass
        return stats

    return await asyncio.to_thread(_collect_stats)


# ---------------------------------------------------------------------------
# Result formatting helpers
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n?", re.DOTALL)
_TIMESTAMP_RE = re.compile(r"\[\d{2}:\d{2}:\d{2}\]\s*")


def _format_result(r) -> dict:
    snippet = r.snippet

    # Extract title from frontmatter (for heading fallback)
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

    return {
        "file_paths": [str(p) for p in r.file_paths],
        "heading": r.heading_path or title,
        "snippet": clean,
        "score": round(r.fused_score, 3),
    }


if __name__ == "__main__":
    mcp.run()
