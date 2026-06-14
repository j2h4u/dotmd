from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from dotmd.storage.surreal import SurrealConnection, SurrealStoreConfig, define_dotmd_surreal_schema


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
) -> object:
    define_dotmd_surreal_schema(connection)

    from dotmd.storage import surreal_schema as schema_module

    retrieval_plan = schema_module.build_surreal_native_retrieval_index_plan(
        embedding_dimension=embedding_dimension,
        hnsw_ef=hnsw_ef,
    )
    for statement in retrieval_plan.statements:
        try:
            connection.query(statement)
        except Exception as exc:
            detail = str(exc).lower()
            if "already exists" not in detail and "already defined" not in detail:
                raise
    return retrieval_plan
