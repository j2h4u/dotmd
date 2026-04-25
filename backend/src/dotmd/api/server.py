"""FastAPI REST API for dotMD.

Thin HTTP layer over :class:`DotMDService`.  Start with::

    dotmd serve          # uses Click CLI
    uvicorn dotmd.api.server:app  # direct uvicorn
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import time

from fastapi import FastAPI, Query, Request
from pydantic import BaseModel

from dotmd.api.service import DotMDService
from dotmd.core.config import Settings
from dotmd.core.models import ExtractDepth, IndexStats, SearchMode, SearchResult

logger = logging.getLogger(__name__)

_service: DotMDService | None = None


def _get_service() -> DotMDService:
    assert _service is not None, "Service not initialised"
    return _service


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _service  # noqa: PLW0603
    _service = DotMDService(Settings())
    _service.warmup()

    # Start background trickle indexer
    shutdown_event = asyncio.Event()
    indexer_task = asyncio.create_task(
        _service.trickle_indexer.run(shutdown_event)
    )

    yield

    # Signal shutdown, wait for current file to finish
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


app = FastAPI(
    title="dotMD",
    description="Markdown knowledgebase search API",
    lifespan=_lifespan,
)


@app.middleware("http")
async def _log_requests(request: Request, call_next):  # noqa: ANN001
    """Log every HTTP request with method, path, status, and duration."""
    t0 = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    is_health = request.url.path == "/health"
    log = logger.error if response.status_code >= 500 else (logger.debug if is_health else logger.info)
    log(
        "%s %s %d (%.0fms)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


@app.get("/health")
async def health() -> dict:
    """Liveness probe -- confirms FastAPI is up and responding."""
    return {"status": "ok"}


# -- Request / response models ------------------------------------------------

class IndexRequest(BaseModel):
    directory: str
    extract_depth: ExtractDepth = ExtractDepth.NER
    entity_types: list[str] | None = None
    force: bool = False


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    count: int


class GraphNode(BaseModel):
    id: str
    label: str
    properties: dict


class GraphEdge(BaseModel):
    source: str
    target: str
    relation_type: str
    weight: float


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


# -- Endpoints -----------------------------------------------------------------

@app.post("/index", response_model=IndexStats)
async def index(req: IndexRequest) -> IndexStats:
    """Index all markdown files under the given directory."""
    return _get_service().index(Path(req.directory), force=req.force)


@app.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., description="Search query"),
    top_k: int = Query(10, ge=1, le=100),
    mode: SearchMode = Query(SearchMode.HYBRID),
    rerank: bool = Query(True),
    expand: bool = Query(True),
) -> SearchResponse:
    """Search the indexed knowledgebase."""
    results = _get_service().search(
        query=q,
        top_k=top_k,
        mode=mode,
        rerank=rerank,
        expand=expand,
    )
    return SearchResponse(query=q, results=results, count=len(results))


@app.get("/status", response_model=IndexStats)
async def status() -> IndexStats:
    """Return current index statistics and trickle indexer progress."""
    return _get_service().status()


@app.get("/graph", response_model=GraphResponse)
async def graph() -> GraphResponse:
    """Return all graph nodes and edges for visualization."""
    data = _get_service().graph_data()
    return GraphResponse(
        nodes=[GraphNode(**n) for n in data["nodes"]],
        edges=[GraphEdge(**e) for e in data["edges"]],
    )


def main(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the API server via uvicorn."""
    import uvicorn

    uvicorn.run(app, host=host, port=port, access_log=False)
