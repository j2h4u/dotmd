from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from surrealdb import SurrealError

from dotmd.storage.surreal import SurrealConnection, SurrealStoreConfig, define_dotmd_surreal_schema
from dotmd.storage.surreal_schema import SurrealRetrievalIndexPlan


@contextmanager
def isolated_surreal_connection(
    tmp_path: Path,
    *,
    database: str = "phase42_retrieval",
) -> Iterator[SurrealConnection]:
    config = SurrealStoreConfig(
        url=f"surrealkv://{tmp_path / 'phase42-retrieval.db'}",
        database=database,
    )
    with SurrealConnection(config) as connection:
        yield connection


def apply_surreal_native_retrieval_schema(
    connection: SurrealConnection,
    *,
    embedding_dimension: int = 3,
    hnsw_ef: int = 40,
) -> SurrealRetrievalIndexPlan:
    define_dotmd_surreal_schema(connection)

    from dotmd.storage import surreal_schema as schema_module

    retrieval_plan = schema_module.build_surreal_native_retrieval_index_plan(
        embedding_dimension=embedding_dimension,
        hnsw_ef=hnsw_ef,
    )
    for statement in retrieval_plan.statements:
        try:
            connection.query(statement)
        except (RuntimeError, SurrealError) as exc:
            detail = str(exc).lower()
            fallback_statement = _legacy_fulltext_statement(statement)
            if fallback_statement is not None:
                try:
                    connection.query(fallback_statement)
                    continue
                except (RuntimeError, SurrealError):
                    pass
            if "already exists" not in detail and "already defined" not in detail:
                raise
    return retrieval_plan


def _legacy_fulltext_statement(statement: str) -> str | None:
    if statement == (
        "DEFINE INDEX chunks_title_fts ON chunks FIELDS title FULLTEXT ANALYZER dotmd_fts BM25(1.2,0.75)"
    ):
        return "DEFINE INDEX chunks_title_fts ON TABLE chunks COLUMNS title SEARCH ANALYZER dotmd_fts BM25;"
    if statement == (
        "DEFINE INDEX chunks_text_fts ON chunks FIELDS text FULLTEXT ANALYZER dotmd_fts BM25(1.2,0.75)"
    ):
        return "DEFINE INDEX chunks_text_fts ON TABLE chunks COLUMNS text SEARCH ANALYZER dotmd_fts BM25;"
    return None
