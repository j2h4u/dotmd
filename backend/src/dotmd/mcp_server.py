"""MCP server for dotMD — exposes markdown knowledgebase search as MCP tools."""

from __future__ import annotations

import logging
import re

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
        List of search results. Each result has `file_paths: list[str]` —
        all files whose content hashes to this chunk (Phase 16 Decision #1).
        Also includes heading, snippet, score, and matched_engines.
    """
    service = _get_service()
    results = service.search(query, top_k=top_k, mode=mode, rerank=rerank)
    return [_format_result(r) for r in results]


@mcp.tool()
def status() -> dict:
    """Get current index statistics.

    Returns:
        Index statistics including trickle indexer progress.
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
    """Format a SearchResult for MCP response."""
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

    # Clean snippet: strip frontmatter, extract first timestamp
    clean = _FRONTMATTER_RE.sub("", snippet).strip()
    first_ts = _TIMESTAMP_RE.search(clean)
    start_time = first_ts.group().strip(" []") if first_ts else None
    clean = _TIMESTAMP_RE.sub("", clean).strip()

    # heading: use heading_path if available, fallback to frontmatter title
    heading = r.heading_path or title

    return {
        "file_paths": [str(p) for p in r.file_paths],
        "heading": heading,
        "snippet": clean,
        "score": round(r.fused_score, 3),
        "matched_engines": r.matched_engines,
        "start_time": start_time,
    }


if __name__ == "__main__":
    mcp.run()
