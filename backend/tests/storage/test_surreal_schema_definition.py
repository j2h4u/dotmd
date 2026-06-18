from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from dotmd.storage.surreal_schema import (
    SURREAL_SCHEMA_VERSION,
    SurrealFieldDefinition,
    SurrealSchemaApplyStatus,
    SurrealSchemaPlan,
    SurrealTableDefinition,
    build_dotmd_surreal_schema_plan,
    define_dotmd_surreal_schema,
    required_migration_categories,
    validate_dotmd_surreal_schema_plan,
)
from tests.fixtures.surreal_native import (
    apply_surreal_native_retrieval_schema,
    isolated_surreal_connection,
)


class _FakeSchemaConnection:
    def __init__(self, existing_schema: dict[str, Any] | None = None) -> None:
        self._existing_schema = existing_schema
        self.applied_statements: list[str] = []

    def inspect_schema(self) -> dict[str, Any]:
        return self._existing_schema or {}

    def query(self, statement: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        self.applied_statements.append(statement)
        return {"statement": statement, "variables": variables}

    def query_raw(
        self,
        statement: str,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.applied_statements.append(statement)
        return {"result": [{"statement": statement, "variables": variables}]}


def _table_by_name(plan: SurrealSchemaPlan, table_name: str) -> SurrealTableDefinition:
    return next(table for table in plan.tables if table.name == table_name)


def _field_names(table: SurrealTableDefinition) -> set[str]:
    return {field.name for field in table.fields}


def _field_by_name(table: SurrealTableDefinition, field_name: str) -> SurrealFieldDefinition:
    return next(field for field in table.fields if field.name == field_name)


def test_build_dotmd_surreal_schema_plan_covers_required_categories_and_tokens() -> None:
    plan = build_dotmd_surreal_schema_plan()

    assert plan.schema_version == SURREAL_SCHEMA_VERSION
    assert tuple(required_migration_categories()) == plan.required_categories
    assert set(plan.required_categories) == {
        "documents",
        "source_units",
        "chunks",
        "provenance",
        "chunk_file_bindings",
        "bindings",
        "fingerprints",
        "embeddings",
        "vector_components",
        "files",
        "sections",
        "entities",
        "tags",
        "relations",
        "feedback",
        "cursors",
        "checkpoints",
    }
    assert {
        "stats",
        "search_log",
        "embedding_cache",
        "embedding_cache_meta",
        "extraction_cache",
        "extraction_cache_meta",
    }.issubset(set(plan.unsupported_categories))

    assert [table.name for table in plan.tables][:5] == [
        "documents",
        "source_units",
        "chunks",
        "provenance",
        "chunk_file_bindings",
    ]
    assert len(plan.statements) >= len(plan.tables)
    assert any(
        statement.startswith("DEFINE TABLE documents SCHEMAFULL") for statement in plan.statements
    )
    assert any(
        statement.startswith("DEFINE TABLE relations TYPE RELATION")
        for statement in plan.statements
    )
    assert any(
        "DEFINE FIELD metadata ON TABLE documents TYPE option<object>" in s for s in plan.statements
    )
    assert any(
        "DEFINE FIELD properties ON TABLE relations TYPE option<object>" in statement
        for statement in plan.statements
    )


def test_schema_tables_preserve_required_fields_and_relation_metadata() -> None:
    plan = build_dotmd_surreal_schema_plan()

    chunks = _table_by_name(plan, "chunks")
    embeddings = _table_by_name(plan, "embeddings")
    bindings = _table_by_name(plan, "bindings")
    chunk_file_bindings = _table_by_name(plan, "chunk_file_bindings")
    relations = _table_by_name(plan, "relations")
    cursors = _table_by_name(plan, "cursors")
    checkpoints = _table_by_name(plan, "checkpoints")
    vector_components = _table_by_name(plan, "vector_components")

    assert chunks.schema_mode == "SCHEMAFULL"
    assert embeddings.schema_mode == "SCHEMAFULL"
    assert bindings.schema_mode == "SCHEMAFULL"
    assert chunk_file_bindings.schema_mode == "SCHEMAFULL"
    assert relations.schema_mode == "RELATION"
    assert relations.relation_endpoints_enforced is False
    assert relations.incoming_tables
    assert relations.outgoing_tables
    assert "ENFORCED" not in relations.statement

    assert {
        "schema_version",
        "original_chunk_id",
        "chunk_strategy",
        "document_ref",
        "ref",
        "text",
        "metadata",
    }.issubset(_field_names(chunks))
    assert {"embedding_model", "text_hash", "vector_rowid", "vector", "metadata"}.issubset(
        _field_names(embeddings)
    )
    assert {
        "namespace",
        "document_ref",
        "ref",
        "active",
        "bound_at",
        "unbound_at",
        "content_fingerprint",
        "metadata_fingerprint",
        "source_unit_refs",
        "metadata",
    }.issubset(_field_names(bindings))
    assert {"chunk_id", "file_path", "chunk_index", "metadata"}.issubset(
        _field_names(chunk_file_bindings)
    )
    assert {
        "rel_type",
        "weight",
        "source_id",
        "target_id",
        "source_table",
        "target_table",
        "properties",
        "metadata",
    }.issubset(_field_names(relations))
    assert {"namespace", "checkpoint_cursor", "metadata"}.issubset(_field_names(checkpoints))
    assert {"ref", "document_ref", "metadata"}.issubset(_field_names(cursors))
    assert vector_components.optional is True
    assert vector_components.derived_from == ("embeddings",)

    metadata_field = _field_by_name(chunks, "metadata")
    properties_field = _field_by_name(relations, "properties")
    assert metadata_field.flexible_json is True
    assert properties_field.flexible_json is True


def test_define_dotmd_surreal_schema_reports_apply_status_without_mutating_incompatible_targets() -> (
    None
):
    planned = define_dotmd_surreal_schema()
    assert planned["schema_version"] == SURREAL_SCHEMA_VERSION
    assert isinstance(planned["apply_status"], SurrealSchemaApplyStatus)
    assert planned["apply_status"].status == "not-applied"

    same_version = _FakeSchemaConnection(
        {
            "schema_version": SURREAL_SCHEMA_VERSION,
            "table_modes": {
                "documents": "SCHEMAFULL",
                "chunks": "SCHEMAFULL",
                "relations": "RELATION",
            },
        }
    )
    same_version_schema = define_dotmd_surreal_schema(connection=same_version)
    assert same_version_schema["apply_status"].status == "already-current"
    assert same_version.applied_statements == []

    newer_version = _FakeSchemaConnection(
        {
            "schema_version": "99-future-schema",
            "table_modes": {"documents": "SCHEMAFULL", "relations": "RELATION"},
        }
    )
    newer_schema = define_dotmd_surreal_schema(connection=newer_version)
    assert newer_schema["apply_status"].status == "replace-required"
    assert "newer" in newer_schema["apply_status"].reason.lower()
    assert newer_version.applied_statements == []

    phase38_target = _FakeSchemaConnection(
        {
            "schema_version": "phase38-prototype",
            "table_modes": {"documents": "SCHEMALESS", "relations": "SCHEMALESS"},
        }
    )
    phase38_schema = define_dotmd_surreal_schema(connection=phase38_target)
    assert phase38_schema["apply_status"].status == "replace-required"
    assert "SCHEMALESS" in phase38_schema["apply_status"].reason
    assert phase38_target.applied_statements == []


def test_validate_dotmd_surreal_schema_plan_fails_for_missing_categories_or_fields() -> None:
    plan = build_dotmd_surreal_schema_plan()

    without_bindings = replace(
        plan,
        tables=tuple(table for table in plan.tables if table.name != "chunk_file_bindings"),
    )
    with pytest.raises(ValueError, match="chunk_file_bindings"):
        validate_dotmd_surreal_schema_plan(without_bindings)

    relations = _table_by_name(plan, "relations")
    invalid_relations = replace(
        relations,
        fields=tuple(field for field in relations.fields if field.name != "rel_type"),
    )
    invalid_plan = replace(
        plan,
        tables=tuple(
            invalid_relations if table.name == "relations" else table for table in plan.tables
        ),
    )
    with pytest.raises(ValueError, match="rel_type"):
        validate_dotmd_surreal_schema_plan(invalid_plan)


def test_chunks_schema_adds_weighted_lexical_fields_without_removing_existing_identity_fields() -> (
    None
):
    plan = build_dotmd_surreal_schema_plan()
    chunks = _table_by_name(plan, "chunks")

    title_field = _field_by_name(chunks, "title")
    tags_text_field = _field_by_name(chunks, "tags_text")

    assert title_field.field_type == "string"
    assert title_field.required is False
    assert tags_text_field.field_type == "string"
    assert tags_text_field.required is False
    assert {"text", "ref", "document_ref"}.issubset(_field_names(chunks))


def test_retrieval_index_plan_exposes_runtime_compatible_bm25_hnsw_and_relation_indexes() -> None:
    from dotmd.storage.surreal_schema import (  # type: ignore[import-not-found]
        build_surreal_native_retrieval_index_plan,
    )

    retrieval_plan = build_surreal_native_retrieval_index_plan(
        embedding_dimension=3,
        hnsw_m=4,
        hnsw_ef=40,
    )

    assert retrieval_plan.embedding_dimension == 3
    assert retrieval_plan.hnsw_m == 4
    assert retrieval_plan.hnsw_ef == 40
    assert retrieval_plan.analyzer_statement == (
        "DEFINE ANALYZER dotmd_fts TOKENIZERS CLASS,PUNCT FILTERS LOWERCASE, ASCII"
    )
    assert retrieval_plan.bm25_index_statements == (
        "DEFINE INDEX chunks_title_fts ON chunks FIELDS title FULLTEXT ANALYZER dotmd_fts BM25(1.2,0.75)",
        "DEFINE INDEX chunks_text_fts ON chunks FIELDS text FULLTEXT ANALYZER dotmd_fts BM25(1.2,0.75)",
    )
    assert retrieval_plan.hnsw_index_statement == (
        "DEFINE INDEX embeddings_vector_hnsw ON TABLE embeddings FIELDS vector HNSW DIMENSION 3 DIST COSINE TYPE F32 EFC 40 M 4;"
    )
    assert retrieval_plan.relation_index_statements == (
        "DEFINE INDEX relations_rel_type_idx ON TABLE relations COLUMNS rel_type;",
        "DEFINE INDEX relations_target_id_idx ON TABLE relations COLUMNS target_id;",
        "DEFINE INDEX relations_source_target_idx ON TABLE relations COLUMNS source_id, target_id;",
    )
    assert retrieval_plan.statements == (
        retrieval_plan.analyzer_statement,
        *retrieval_plan.bm25_index_statements,
        retrieval_plan.hnsw_index_statement,
        *retrieval_plan.relation_index_statements,
    )


def test_retrieval_index_plan_matches_live_standalone_fulltext_surface() -> None:
    from dotmd.storage.surreal_schema import (  # type: ignore[import-not-found]
        build_surreal_native_retrieval_index_plan,
    )

    retrieval_plan = build_surreal_native_retrieval_index_plan(
        embedding_dimension=3,
        hnsw_ef=40,
    )
    serialized = "\n".join(retrieval_plan.statements)

    assert "FULLTEXT" in serialized
    assert "SEARCH ANALYZER" not in serialized
    assert "DISKANN" not in serialized
    assert "search::rrf" not in serialized
    assert "search::linear" not in serialized


def test_retrieval_contract_validation_rejects_bad_dimensions_models_vectors_and_query_bounds() -> (
    None
):
    from dotmd.storage.surreal_schema import (  # type: ignore[import-not-found]
        validate_surreal_native_retrieval_contract,
    )

    valid_rows = [
        {
            "embedding_model": "multilingual-e5-large",
            "vector": [0.11, 0.22, 0.33],
        }
    ]

    validate_surreal_native_retrieval_contract(
        embedding_dimension=3,
        embedding_rows=valid_rows,
        top_k=10,
        hnsw_ef=40,
    )

    with pytest.raises(ValueError, match="embedding_dimension"):
        validate_surreal_native_retrieval_contract(
            embedding_dimension=0,
            embedding_rows=valid_rows,
            top_k=10,
            hnsw_ef=40,
        )
    with pytest.raises(ValueError, match="single active embedding_model"):
        validate_surreal_native_retrieval_contract(
            embedding_dimension=3,
            embedding_rows=[
                {"embedding_model": "model-a", "vector": [0.11, 0.22, 0.33]},
                {"embedding_model": "model-b", "vector": [0.44, 0.55, 0.66]},
            ],
            top_k=10,
            hnsw_ef=40,
        )
    with pytest.raises(ValueError, match="embedding_dimension"):
        validate_surreal_native_retrieval_contract(
            embedding_dimension=3,
            embedding_rows=[
                {
                    "embedding_model": "multilingual-e5-large",
                    "vector": [0.11, 0.22],
                }
            ],
            top_k=10,
            hnsw_ef=40,
        )
    with pytest.raises(ValueError, match="top_k"):
        validate_surreal_native_retrieval_contract(
            embedding_dimension=3,
            embedding_rows=valid_rows,
            top_k=0,
            hnsw_ef=40,
        )
    with pytest.raises(ValueError, match="top_k"):
        validate_surreal_native_retrieval_contract(
            embedding_dimension=3,
            embedding_rows=valid_rows,
            top_k=101,
            hnsw_ef=40,
        )
    with pytest.raises(ValueError, match="hnsw_ef"):
        validate_surreal_native_retrieval_contract(
            embedding_dimension=3,
            embedding_rows=valid_rows,
            top_k=10,
            hnsw_ef=9,
        )
    with pytest.raises(ValueError, match="hnsw_ef"):
        validate_surreal_native_retrieval_contract(
            embedding_dimension=3,
            embedding_rows=valid_rows,
            top_k=10,
            hnsw_ef=401,
        )
    with pytest.raises(ValueError, match="hnsw_ef"):
        validate_surreal_native_retrieval_contract(
            embedding_dimension=3,
            embedding_rows=valid_rows,
            top_k=41,
            hnsw_ef=40,
        )


def test_probe_surreal_native_retrieval_capabilities_reports_required_and_observed_features(
    tmp_path: Path,
) -> None:
    from dotmd.storage.surreal_schema import (  # type: ignore[import-not-found]
        SurrealRetrievalCapabilityReport,
        probe_surreal_native_retrieval_capabilities,
    )

    with isolated_surreal_connection(tmp_path) as connection:
        report = probe_surreal_native_retrieval_capabilities(
            connection,
            embedding_dimension=3,
            hnsw_ef=40,
            allow_target_mutation=True,
        )

    assert isinstance(report, SurrealRetrievalCapabilityReport)
    assert report.overall_passed is False
    required = {check.name: check for check in report.required_checks}
    observations = {check.name: check for check in report.optional_observations}

    assert required["fts_analyzer"].passed is True
    assert required["fts_title_index"].passed is False
    assert required["fts_text_index"].passed is False
    assert "FULLTEXT" in required["fts_title_index"].statement
    assert "FULLTEXT" in required["fts_text_index"].statement
    assert required["hnsw_vector_index"].passed is True
    assert required["relation_table"].passed is True
    assert required["relations_target_id_idx"].passed is True
    assert observations["fulltext_analyzer_v3"].required is False
    assert observations["diskann_v3"].required is False
    assert observations["built_in_hybrid_helpers"].required is False


def test_probe_surreal_native_retrieval_capabilities_requires_explicit_mutation_opt_in(
    tmp_path: Path,
) -> None:
    from dotmd.storage.surreal_schema import (  # type: ignore[import-not-found]
        probe_surreal_native_retrieval_capabilities,
    )

    with (
        isolated_surreal_connection(tmp_path) as connection,
        pytest.raises(ValueError, match="explicit scratch target"),
    ):
        probe_surreal_native_retrieval_capabilities(
            connection,
            embedding_dimension=3,
            hnsw_ef=40,
        )


def test_shared_phase42_fixture_applies_base_schema_and_retrieval_plan(tmp_path: Path) -> None:
    with isolated_surreal_connection(tmp_path) as connection:
        retrieval_plan = apply_surreal_native_retrieval_schema(
            connection,
            embedding_dimension=3,
            hnsw_ef=40,
        )

        chunk_info = connection.query_raw("INFO FOR TABLE chunks;")

    assert retrieval_plan.embedding_dimension == 3
    assert "title" in str(chunk_info)
    assert "tags_text" in str(chunk_info)
