"""FastAPI REST API for dotMD.

Thin HTTP layer over :class:`DotMDService`.  Start with::

    dotmd serve          # uses Click CLI
    uvicorn dotmd.api.server:app  # direct uvicorn
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel

from dotmd.api.service import DotMDService
from dotmd.core.config import load_runtime_settings
from dotmd.core.models import ExtractDepth, IndexStats, SearchCandidate, SearchMode

logger = logging.getLogger(__name__)

_service: DotMDService | None = None


def _get_service() -> DotMDService:
    assert _service is not None, "Service not initialised"
    return _service


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _service
    _service = DotMDService(load_runtime_settings())
    _service.warmup()
    yield
    _service = None


app = FastAPI(
    title="dotMD",
    description="Markdown knowledgebase search API",
    lifespan=_lifespan,
)


@app.middleware("http")
async def _log_requests(request: Request, call_next):
    """Log every HTTP request with method, path, status, and duration."""
    t0 = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    is_health = request.url.path == "/health"
    log = (
        logger.error
        if response.status_code >= 500
        else (logger.debug if is_health else logger.info)
    )
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
    results: list[SearchCandidate]
    count: int


class RerankerRunComparisonResponse(BaseModel):
    name: str
    model_name: str
    elapsed_ms: float
    elapsed: str
    load_ms: float
    load: str
    rerank_ms: float
    rerank: str
    returned_count: int
    top_chunk_ids: list[str]
    scores: list[float]
    error: str | None = None


class RerankerComparisonResponse(BaseModel):
    query: str
    search_query: str
    shared_pool_size: int
    rerankers: list[RerankerRunComparisonResponse]
    overlap_reference: str | None = None
    overlap: dict[str, int]


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
    federated: bool = Query(False, description="Include federated providers in the search."),
    reranker: str | None = Query(None, description="Reranker name to use"),
) -> SearchResponse:
    """Search the indexed knowledgebase."""
    try:
        results = await _get_service().search_async(
            query=q,
            top_k=top_k,
            mode=mode,
            rerank=rerank,
            expand=expand,
            reranker_name=reranker,
            include_federated=federated,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    candidates = results.candidates
    return SearchResponse(query=q, results=candidates, count=len(candidates))


@app.get("/rerank/compare", response_model=RerankerComparisonResponse)
async def compare_rerankers(
    q: str = Query(..., description="Search query"),
    rerankers: str | None = Query(None, description="Comma-separated reranker names"),
    top_k: int = Query(10, ge=1, le=100),
    mode: SearchMode = Query(SearchMode.HYBRID),
    expand: bool = Query(True),
) -> RerankerComparisonResponse:
    """Compare developer-selected rerankers over one shared candidate pool."""
    names = [name.strip() for name in rerankers.split(",") if name.strip()] if rerankers else None
    try:
        comparison = _get_service().compare_rerankers(
            query=q,
            reranker_names=names,
            top_k=top_k,
            mode=mode.value,
            expand=expand,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RerankerComparisonResponse.model_validate(comparison)


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
