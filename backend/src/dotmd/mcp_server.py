"""MCP server for dotMD — exposes markdown knowledgebase search as MCP tools."""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from dotmd.api.service import DotMDService
from dotmd.core.config import Settings

logger = logging.getLogger(__name__)

mcp = FastMCP("dotmd", instructions="Search a markdown knowledgebase.")

_service: DotMDService | None = None


def _get_service() -> DotMDService:
    global _service
    if _service is None:
        _service = DotMDService(Settings())
        _service.warmup()
    return _service


@mcp.tool()
def search(
    query: str,
    top_k: int = 10,
    mode: str = "hybrid",
    rerank: bool = True,
) -> list[dict]:
    """Search the indexed markdown knowledgebase.

    Args:
        query: Natural-language search query.
        top_k: Maximum number of results to return.
        mode: Search strategy — "semantic", "keyword", "graph", or "hybrid".
        rerank: Whether to rerank results with a cross-encoder.

    Returns:
        List of search results with file_path, heading, snippet, and score.
    """
    service = _get_service()
    results = service.search(query, top_k=top_k, mode=mode, rerank=rerank)
    return [
        {
            "chunk_id": r.chunk_id,
            "file_path": str(r.file_path),
            "heading": r.heading_path,
            "snippet": _strip_frontmatter(r.snippet),
            "score": r.fused_score,
            "matched_engines": r.matched_engines,
        }
        for r in results
    ]


def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter from snippet for cleaner display."""
    if not text.startswith("---"):
        return text
    end = text.find("---", 3)
    if end == -1:
        return text
    return text[end + 3:].strip()


@mcp.tool()
def status() -> dict:
    """Get current index statistics.

    Returns:
        Index statistics including trickle indexer progress.
    """
    service = _get_service()
    return service.status().model_dump(mode="json")


if __name__ == "__main__":
    mcp.run()
