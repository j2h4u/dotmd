"""MCP server for dotMD — exposes markdown knowledgebase search as MCP tools."""

from __future__ import annotations

import logging
import re
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from dotmd.api.service import DotMDService
from dotmd.core.config import Settings

logger = logging.getLogger(__name__)

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
)

_service: DotMDService | None = None


def _get_service() -> DotMDService:
    global _service
    if _service is None:
        _service = DotMDService(Settings())
        _service.warmup()
    return _service


@mcp.tool(
    annotations={
        "title": "Search Knowledgebase",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
def search(
    query: Annotated[str, Field(description="Natural-language search query.")],
    top_k: Annotated[int, Field(description="Maximum results to return.", ge=1, le=100)] = 10,
    mode: Annotated[
        Literal["hybrid", "semantic", "keyword", "graph"],
        Field(description=(
            "Search strategy. "
            "hybrid: semantic + keyword + graph fused via RRF (default, best for most queries). "
            "semantic: vector similarity only. "
            "keyword: FTS5 full-text search only. "
            "graph: entity-based graph traversal only."
        )),
    ] = "hybrid",
    rerank: Annotated[bool, Field(description="Rerank results with a cross-encoder for higher precision.")] = True,
) -> list[dict]:
    """Search the indexed markdown knowledgebase and return ranked chunks.

    Each result includes the source file paths, heading context, a cleaned text
    snippet, a relevance score, and which search engines matched it.
    """
    service = _get_service()
    results = service.search(query, top_k=top_k, mode=mode, rerank=rerank)
    return [_format_result(r) for r in results]


@mcp.tool(
    annotations={
        "title": "Index Status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
)
def status() -> dict:
    """Return current index statistics and trickle indexer progress.

    Useful for checking how many files and chunks are indexed, whether
    background indexing is active, and when the last file was indexed.
    """
    service = _get_service()
    stats = service.status().model_dump(mode="json")

    # Enrich with graph counts from FalkorDB
    try:
        graph_store = service._pipeline.graph_store
        stats["total_entities"] = graph_store.node_count()
        stats["total_edges"] = graph_store.edge_count()
    except Exception:
        pass

    # last_indexed from fingerprints if stats table is empty
    if not stats.get("last_indexed"):
        try:
            conn = service._pipeline.conn
            fp_table = f"chunk_fingerprints_{service._settings.chunk_strategy}"
            row = conn.execute(
                f"SELECT max(indexed_at) FROM {fp_table}"
            ).fetchone()
            if row and row[0]:
                stats["last_indexed"] = row[0]
        except Exception:
            pass

    return stats


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
    first_ts = _TIMESTAMP_RE.search(clean)
    start_time = first_ts.group().strip(" []") if first_ts else None
    clean = _TIMESTAMP_RE.sub("", clean).strip()

    return {
        "file_paths": [str(p) for p in r.file_paths],
        "heading": r.heading_path or title,
        "snippet": clean,
        "score": round(r.fused_score, 3),
        "matched_engines": r.matched_engines,
        "start_time": start_time,
    }


if __name__ == "__main__":
    mcp.run()
