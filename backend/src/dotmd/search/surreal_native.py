"""Surreal-native engine overrides for the existing service fusion seam."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dotmd.search.base import SearchEngineProtocol
from dotmd.search.surreal_fts import SurrealFTSSearchEngine
from dotmd.search.surreal_graph import SurrealGraphDirectEngine
from dotmd.search.surreal_vector import SurrealVectorSearchEngine
from dotmd.storage.surreal_schema import DEFAULT_HNSW_EF

if TYPE_CHECKING:
    from dotmd.core.config import Settings
    from dotmd.storage.surreal import SurrealConnection


def build_surreal_native_engine_overrides(
    connection: SurrealConnection,
    settings: Settings,
    *,
    embedding_dimension: int,
    hnsw_ef: int = DEFAULT_HNSW_EF,
) -> dict[str, SearchEngineProtocol]:
    """Build explicit Surreal-native retrieval engines for one service call."""

    return {
        "semantic": SurrealVectorSearchEngine(
            connection,
            model_name=settings.embedding_model,
            embedding_dimension=embedding_dimension,
            score_floor=settings.semantic_score_floor,
            embedding_url=settings.embedding_url,
            tei_batch_size=settings.tei_batch_size,
            use_prefix=settings.needs_embedding_prefix,
            query_instruction=settings.query_instruction,
            hnsw_ef=hnsw_ef,
        ),
        "keyword": SurrealFTSSearchEngine(connection),
        "graph_direct": SurrealGraphDirectEngine(connection),
    }
