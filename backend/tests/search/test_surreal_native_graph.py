from __future__ import annotations

import logging

import pytest
from tests.fixtures.surreal_native import (
    apply_surreal_native_retrieval_schema,
    isolated_surreal_connection,
)


@pytest.fixture(autouse=True)
def _propagate_dotmd_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(logging.getLogger("dotmd"), "propagate", True)


def _engine_class():
    from dotmd.search.surreal_graph import SurrealGraphDirectEngine

    return SurrealGraphDirectEngine


class _FakeGraphConnection:
    def __init__(
        self,
        *,
        entity_rows: list[dict[str, object]] | None = None,
        relation_rows: list[dict[str, object]] | None = None,
        entity_error: Exception | None = None,
        relation_error: Exception | None = None,
    ) -> None:
        self.entity_rows = entity_rows or []
        self.relation_rows = relation_rows or []
        self.entity_error = entity_error
        self.relation_error = relation_error
        self.calls: list[tuple[str, dict[str, object] | None]] = []

    def query(
        self,
        statement: str,
        variables: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        self.calls.append((statement, variables))
        if "FROM entities" in statement:
            if self.entity_error is not None:
                raise self.entity_error
            return list(self.entity_rows)
        if "FROM relations" in statement:
            if self.relation_error is not None:
                raise self.relation_error
            return list(self.relation_rows)
        raise AssertionError(f"unexpected query: {statement}")

    def scan_table(self, table_name: str) -> list[dict[str, object]]:
        raise AssertionError(f"scan_table() must not be used in graph retrieval: {table_name}")


def test_load_catalog_lowercases_entity_names_logs_count_and_reuses_loaded_state(
    caplog: pytest.LogCaptureFixture,
) -> None:
    connection = _FakeGraphConnection(
        entity_rows=[
            {"name": "Николай Сенин"},
            {"name": "Surreal"},
            {"name": ""},
        ]
    )
    engine = _engine_class()(connection)

    with caplog.at_level(logging.INFO):
        engine.load_catalog()

    assert engine._entity_catalog == {  # pyright: ignore[reportPrivateUsage]
        "николай сенин": "Николай Сенин",
        "surreal": "Surreal",
    }
    assert engine._loaded is True  # pyright: ignore[reportPrivateUsage]
    assert "Graph entity catalog loaded: 2 entities" in caplog.text

    assert engine.search("no matching entity here", top_k=3) == []
    assert engine.search("still no match", top_k=3) == []
    assert sum(1 for statement, _variables in connection.calls if "FROM entities" in statement) == 1
    assert (
        sum(1 for statement, _variables in connection.calls if "FROM relations" in statement) == 0
    )


def test_load_catalog_fail_softs_to_empty_catalog_on_runtime_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    connection = _FakeGraphConnection(entity_error=RuntimeError("catalog failed"))
    engine = _engine_class()(connection)

    with caplog.at_level(logging.WARNING):
        engine.load_catalog()

    assert engine._entity_catalog == {}  # pyright: ignore[reportPrivateUsage]
    assert engine._loaded is True  # pyright: ignore[reportPrivateUsage]
    assert "error_type=RuntimeError" in caplog.text
    assert "catalog failed" not in caplog.text


def test_search_matches_entities_like_graph_direct_and_returns_empty_without_match() -> None:
    connection = _FakeGraphConnection(
        entity_rows=[
            {"name": "Николай Сенин"},
            {"name": "Surreal"},
        ]
    )
    engine = _engine_class()(connection)

    assert engine.search("notes about unrelated work", top_k=3) == []

    results = engine.search("meeting with Николай Сенин about surreal", top_k=3)

    assert results == []
    assert len(connection.calls) == 2
    relation_statement, relation_variables = connection.calls[-1]
    assert "FROM relations" in relation_statement
    assert relation_variables == {
        "entity_names": ["Николай Сенин", "Surreal"],
        "allowed_rel_types": ["MENTIONS", "HAS_TAG"],
        "chunk_strategy": "contextual_512_50",
        "limit": 3,
    }


def test_search_uses_indexed_target_id_relation_query_with_bound_variables() -> None:
    connection = _FakeGraphConnection(
        entity_rows=[
            {"name": "Surreal"},
            {"name": "retrieval"},
        ],
        relation_rows=[
            {
                "source_id": "chunk-alpha",
                "target_id": "Surreal",
                "rel_type": "MENTIONS",
                "weight": 1.0,
                "properties": {"evidence": "alpha"},
                "metadata": {"source": "test"},
            }
        ],
    )
    engine = _engine_class()(connection)

    results = engine.search("surreal retrieval!!!", top_k=7)

    assert results == [("chunk-alpha", 1.0)]
    assert len(connection.calls) == 2

    statement, variables = connection.calls[-1]
    assert "SELECT source_id, math::sum(weight) AS total_weight" in statement
    assert "FROM relations" in statement
    assert "target_id IN $entity_names" in statement
    assert "rel_type IN $allowed_rel_types" in statement
    assert "source_table = 'sections'" in statement
    assert "source_id IN (" in statement
    assert "SELECT VALUE chunk_id" in statement
    assert "GROUP BY source_id" in statement
    assert "ORDER BY total_weight DESC, source_id ASC" in statement
    assert "LIMIT $limit" in statement
    assert variables == {
        "entity_names": ["Surreal", "retrieval"],
        "allowed_rel_types": ["MENTIONS", "HAS_TAG"],
        "chunk_strategy": "contextual_512_50",
        "limit": 7,
    }
    assert "surreal retrieval!!!" not in statement


def test_search_uses_relation_weights_normalizes_scores_and_breaks_ties_by_chunk_id() -> None:
    connection = _FakeGraphConnection(
        entity_rows=[
            {"name": "Surreal"},
            {"name": "retrieval"},
        ],
        relation_rows=[
            {
                "in": "sections:ignored-alpha",
                "out": "entities:surreal",
                "source_id": "chunk-alpha",
                "target_id": "Surreal",
                "rel_type": "MENTIONS",
                "weight": 2.0,
                "properties": {"evidence": "entity hit"},
                "metadata": {"rank": 1},
            },
            {
                "in": "sections:ignored-alpha",
                "out": "tags:retrieval",
                "source_id": "chunk-alpha",
                "target_id": "retrieval",
                "rel_type": "HAS_TAG",
                "weight": 1.0,
                "properties": {"source": "frontmatter"},
                "metadata": {"rank": 2},
            },
            {
                "in": "sections:ignored-beta",
                "out": "entities:surreal",
                "source_id": "chunk-beta",
                "target_id": "Surreal",
                "rel_type": "MENTIONS",
                "weight": 1.0,
                "properties": {},
                "metadata": {},
            },
            {
                "in": "sections:ignored-gamma",
                "out": "tags:retrieval",
                "source_id": "chunk-gamma",
                "target_id": "retrieval",
                "rel_type": "HAS_TAG",
                "weight": 1.0,
                "properties": {},
                "metadata": {},
            },
        ],
    )
    engine = _engine_class()(connection)

    results = engine.search("surreal retrieval", top_k=5)

    assert results == [
        ("chunk-alpha", 1.0),
        ("chunk-beta", 1.0 / 3.0),
        ("chunk-gamma", 1.0 / 3.0),
    ]


def test_search_limits_after_chunk_aggregation_not_raw_relation_rows() -> None:
    connection = _FakeGraphConnection(
        entity_rows=[
            {"name": "Surreal"},
            {"name": "retrieval"},
        ],
        relation_rows=[
            {
                "source_id": "chunk-alpha",
                "target_id": "Surreal",
                "rel_type": "MENTIONS",
                "weight": 2.0,
            },
            {
                "source_id": "chunk-alpha",
                "target_id": "retrieval",
                "rel_type": "HAS_TAG",
                "weight": 1.0,
            },
            {
                "source_id": "chunk-beta",
                "target_id": "Surreal",
                "rel_type": "MENTIONS",
                "weight": 4.0,
            },
        ],
    )
    engine = _engine_class()(connection)

    assert engine.search("surreal retrieval", top_k=1) == [("chunk-beta", 1.0)]

    statement, variables = connection.calls[-1]
    assert "GROUP BY source_id" in statement
    assert "LIMIT $limit" in statement
    assert variables is not None
    assert variables["chunk_strategy"] == "contextual_512_50"
    assert variables["limit"] == 1


def test_search_uses_flat_relation_fields_even_when_surreal_endpoints_are_present() -> None:
    connection = _FakeGraphConnection(
        entity_rows=[{"name": "Surreal"}],
        relation_rows=[
            {
                "in": "sections:not-the-answer",
                "out": "entities:not-the-answer",
                "source_id": "chunk-flat-fields-win",
                "target_id": "Surreal",
                "rel_type": "MENTIONS",
                "weight": 4.0,
                "properties": {"evidence": "flat fields"},
                "metadata": {"shape": "type relation"},
            }
        ],
    )
    engine = _engine_class()(connection)

    assert engine.search("surreal", top_k=3) == [("chunk-flat-fields-win", 1.0)]


def test_search_logs_and_returns_empty_on_relation_query_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    connection = _FakeGraphConnection(
        entity_rows=[{"name": "Surreal"}],
        relation_error=RuntimeError("relation query failed"),
    )
    engine = _engine_class()(connection)

    with caplog.at_level(logging.WARNING):
        results = engine.search("surreal", top_k=3)

    assert results == []
    assert len(connection.calls) == 2
    assert "matched_entities=1" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "relation query failed" not in caplog.text


def test_embedded_surreal_graph_returns_only_allowed_relation_matches(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    with isolated_surreal_connection(tmp_path) as connection:
        apply_surreal_native_retrieval_schema(connection, embedding_dimension=3, hnsw_ef=40)

        for chunk_id in ("chunk-alpha", "chunk-beta", "chunk-blocked"):
            connection.create(
                f"chunks:{chunk_id.replace('-', '_')}",
                {
                    "schema_version": "42.1.0",
                    "chunk_id": chunk_id,
                    "original_chunk_id": chunk_id,
                    "chunk_strategy": "contextual_512_50",
                    "document_ref": f"doc:{chunk_id}",
                    "ref": f"filesystem:/tmp/{chunk_id}.md",
                    "title": chunk_id,
                    "tags_text": "",
                    "text": chunk_id,
                    "metadata": {},
                },
            )

        connection.create(
            "entities:surreal",
            {
                "schema_version": "42.1.0",
                "original_id": "entity:surreal",
                "name": "Surreal",
                "metadata": {},
            },
        )
        connection.create(
            "sections:chunk_alpha",
            {
                "schema_version": "42.1.0",
                "original_id": "chunk-alpha",
                "document_ref": "doc:alpha",
                "metadata": {},
            },
        )
        connection.create(
            "sections:chunk_beta",
            {
                "schema_version": "42.1.0",
                "original_id": "chunk-beta",
                "document_ref": "doc:beta",
                "metadata": {},
            },
        )
        connection.create(
            "sections:chunk_blocked",
            {
                "schema_version": "42.1.0",
                "original_id": "chunk-blocked",
                "document_ref": "doc:blocked",
                "metadata": {},
            },
        )
        connection.create(
            "tags:surreal",
            {
                "schema_version": "42.1.0",
                "original_id": "tag:surreal",
                "name": "Surreal",
                "metadata": {},
            },
        )

        connection.query(
            """
RELATE sections:chunk_alpha->relations:alpha_mentions_surreal->entities:surreal
SET schema_version = '42.1.0',
    rel_type = 'MENTIONS',
    weight = 2.0,
    source_id = 'chunk-alpha',
    target_id = 'Surreal',
    source_table = 'sections',
    target_table = 'entities',
    properties = { evidence: 'entity' },
    metadata = { rank: 1 };
""".strip()
        )
        connection.query(
            """
RELATE sections:chunk_beta->relations:beta_has_tag_surreal->tags:surreal
SET schema_version = '42.1.0',
    rel_type = 'HAS_TAG',
    weight = 1.0,
    source_id = 'chunk-beta',
    target_id = 'Surreal',
    source_table = 'sections',
    target_table = 'tags',
    properties = { source: 'frontmatter' },
    metadata = { rank: 2 };
""".strip()
        )
        connection.query(
            """
RELATE sections:chunk_blocked->relations:blocked_unrelated->entities:surreal
SET schema_version = '42.1.0',
    rel_type = 'UNRELATED',
    weight = 9.0,
    source_id = 'chunk-blocked',
    target_id = 'Surreal',
    source_table = 'sections',
    target_table = 'entities',
    properties = {},
    metadata = {};
""".strip()
        )

        engine = _engine_class()(connection)
        results = engine.search("surreal", top_k=5)

    assert results == [
        ("chunk-alpha", 1.0),
        ("chunk-beta", 0.5),
    ]
