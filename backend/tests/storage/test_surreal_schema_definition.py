from __future__ import annotations

import pytest

from dotmd.storage import surreal_schema
from dotmd.storage.surreal_schema import (
    MONOLITHIC_TABLES,
    SurrealSchemaPlan,
    build_analyzer_statement,
    build_embeddings_diskann_index_statement,
    build_embeddings_hnsw_index_statement,
    build_fulltext_index_statement,
    build_minimal_monolithic_schema_plan,
)

pytestmark = pytest.mark.real_schema_check


def test_schema_plan_is_monolithic_and_covers_expected_tables() -> None:
    plan = build_minimal_monolithic_schema_plan(embedding_dimension=1536)

    assert isinstance(plan, SurrealSchemaPlan)
    assert plan.embedding_dimension == 1536
    assert MONOLITHIC_TABLES == (
        "documents",
        "source_units",
        "chunks",
        "chunk_file_bindings",
        "chunk_source_provenance",
        "resource_bindings",
        "source_unit_fingerprints",
        "source_checkpoints",
        "embeddings",
        "graph_nodes",
        "graph_edges",
        "entities",
        "relations",
        "feedback",
    )
    assert list(plan.table_statements()) == [
        "DEFINE TABLE IF NOT EXISTS documents SCHEMAFULL;",
        "DEFINE TABLE IF NOT EXISTS source_units SCHEMAFULL;",
        "DEFINE TABLE IF NOT EXISTS chunks SCHEMAFULL;",
        "DEFINE TABLE IF NOT EXISTS chunk_file_bindings SCHEMAFULL;",
        "DEFINE TABLE IF NOT EXISTS chunk_source_provenance SCHEMAFULL;",
        "DEFINE TABLE IF NOT EXISTS resource_bindings SCHEMAFULL;",
        "DEFINE TABLE IF NOT EXISTS source_unit_fingerprints SCHEMAFULL;",
        "DEFINE TABLE IF NOT EXISTS source_checkpoints SCHEMAFULL;",
        "DEFINE TABLE IF NOT EXISTS embeddings SCHEMAFULL;",
        "DEFINE TABLE IF NOT EXISTS graph_nodes SCHEMAFULL;",
        "DEFINE TABLE IF NOT EXISTS graph_edges SCHEMAFULL;",
        "DEFINE TABLE IF NOT EXISTS entities SCHEMAFULL;",
        "DEFINE TABLE IF NOT EXISTS relations SCHEMAFULL;",
        "DEFINE TABLE IF NOT EXISTS feedback SCHEMAFULL;",
    ]

    field_statements = plan.field_statements()
    assert (
        "DEFINE FIELD IF NOT EXISTS document_ref ON TABLE documents TYPE string;"
        in field_statements
    )
    assert (
        "DEFINE FIELD IF NOT EXISTS document ON TABLE chunks TYPE option<record<documents>>;"
        in field_statements
    )
    assert (
        "DEFINE FIELD IF NOT EXISTS text ON TABLE source_units TYPE option<string>;"
        in field_statements
    )
    assert (
        "DEFINE FIELD IF NOT EXISTS chunking_hints ON TABLE source_units TYPE object FLEXIBLE;"
        in field_statements
    )
    assert (
        "DEFINE FIELD IF NOT EXISTS metadata ON TABLE documents TYPE object FLEXIBLE;"
        in field_statements
    )
    assert (
        "DEFINE FIELD IF NOT EXISTS source_unit_refs ON TABLE chunk_source_provenance "
        "TYPE array<string>;"
    ) in field_statements
    assert (
        "DEFINE FIELD IF NOT EXISTS vector ON TABLE embeddings TYPE array<float>;"
        in field_statements
    )
    assert (
        "DEFINE FIELD IF NOT EXISTS labels ON TABLE graph_nodes TYPE array<string>;"
        in field_statements
    )
    assert (
        "DEFINE FIELD IF NOT EXISTS properties ON TABLE graph_edges TYPE object FLEXIBLE;"
        in field_statements
    )
    assert (
        "DEFINE FIELD IF NOT EXISTS source ON TABLE relations TYPE record<entities>;"
        in field_statements
    )
    assert plan.fulltext_statements() == (
        "DEFINE ANALYZER IF NOT EXISTS dotmd_fts TOKENIZERS class, punct "
        "FILTERS lowercase, ascii;",
        "DEFINE INDEX IF NOT EXISTS chunks_title_fts ON TABLE chunks FIELDS title "
        "FULLTEXT ANALYZER dotmd_fts BM25(1.2,0.75) CONCURRENTLY;",
        "DEFINE INDEX IF NOT EXISTS chunks_text_fts ON TABLE chunks FIELDS text "
        "FULLTEXT ANALYZER dotmd_fts BM25(1.2,0.75) CONCURRENTLY;",
    )
    assert not any("tags" in statement.lower() for statement in plan.fulltext_statements())
    assert len(plan.scalar_index_statements()) == 10
    assert len(plan.index_statements()) == 1
    assert len(plan.index_statements(vector_index="diskann")) == 1
    assert plan.index_statements(vector_index="none") == ()
    assert len(plan.vector_index_statements()) == 2
    assert len(plan.statements()) == len(MONOLITHIC_TABLES) + len(field_statements) + 10 + 3 + 1


def test_embedding_index_builders_emit_expected_sql() -> None:
    hnsw = build_embeddings_hnsw_index_statement(dimension=1536)
    diskann = build_embeddings_diskann_index_statement(dimension=1536)

    assert hnsw == (
        "DEFINE INDEX IF NOT EXISTS embeddings_vector_hnsw ON TABLE embeddings FIELDS vector "
        "HNSW DIMENSION 1536 TYPE F32 DIST COSINE EFC 150 M 12;"
    )
    assert diskann == (
        "DEFINE INDEX IF NOT EXISTS embeddings_vector_diskann ON TABLE embeddings FIELDS vector "
        "DISKANN DIMENSION 1536 TYPE F32 DIST COSINE DEGREE 64 L_BUILD 100 ALPHA 1.2;"
    )


def test_fulltext_builders_emit_expected_sql() -> None:
    assert build_analyzer_statement() == (
        "DEFINE ANALYZER IF NOT EXISTS dotmd_fts TOKENIZERS class, punct "
        "FILTERS lowercase, ascii;"
    )
    assert build_fulltext_index_statement(
        index_name="chunks_title_fts",
        table="chunks",
        field="title",
    ) == (
        "DEFINE INDEX IF NOT EXISTS chunks_title_fts ON TABLE chunks FIELDS title "
        "FULLTEXT ANALYZER dotmd_fts BM25(1.2,0.75) CONCURRENTLY;"
    )
    assert build_fulltext_index_statement(
        index_name="chunks_text_fts",
        table="chunks",
        field="text",
        highlights=True,
    ) == (
        "DEFINE INDEX IF NOT EXISTS chunks_text_fts ON TABLE chunks FIELDS text "
        "FULLTEXT ANALYZER dotmd_fts BM25(1.2,0.75) HIGHLIGHTS CONCURRENTLY;"
    )


def test_schema_module_does_not_define_shard_helpers() -> None:
    assert not any("shard" in name.lower() for name in dir(surreal_schema))
