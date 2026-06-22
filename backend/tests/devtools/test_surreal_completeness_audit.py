from __future__ import annotations

import ast
import inspect
import json
import textwrap
from dataclasses import asdict

from devtools.surreal_completeness_audit import (
    CompletenessAuditReport,
    SurrealCompletenessAuditSettings,
    _audit_completeness,
    _build_provenance_fanout_by_chunk_id,
    _human_summary,
    read_settings_from_env,
)


class _FakeAuditConnection:
    def __init__(self) -> None:
        self.query_calls: list[str] = []
        self.query_raw_calls: list[str] = []

    def query(self, statement: str, variables: dict | None = None):
        self.query_calls.append(statement)
        responses = {
            "SELECT count() AS count FROM chunks GROUP ALL;": [{"count": 3}],
            "SELECT count() AS count FROM provenance GROUP ALL;": [{"count": 5}],
            "SELECT chunk_id, embedding_model, chunk_strategy, text_hash, count() AS count FROM embeddings_0 GROUP BY chunk_id, embedding_model, chunk_strategy, text_hash ORDER BY chunk_id ASC, embedding_model ASC, chunk_strategy ASC, text_hash ASC;": [
                {
                    "chunk_id": "chunk-b",
                    "embedding_model": "model-b",
                    "chunk_strategy": "heading_512_50",
                    "text_hash": "hash-b",
                    "count": 1,
                },
            ],
            "SELECT count() AS count FROM embeddings_0 GROUP ALL;": [{"count": 1}],
            "SELECT chunk_id, embedding_model, chunk_strategy, text_hash, count() AS count FROM embeddings_1 GROUP BY chunk_id, embedding_model, chunk_strategy, text_hash ORDER BY chunk_id ASC, embedding_model ASC, chunk_strategy ASC, text_hash ASC;": [
                {
                    "chunk_id": "chunk-c",
                    "embedding_model": "model-a",
                    "chunk_strategy": "heading_512_50",
                    "text_hash": "hash-c",
                    "count": 1,
                },
                {
                    "chunk_id": "chunk-orphan",
                    "embedding_model": "model-a",
                    "chunk_strategy": "heading_512_50",
                    "text_hash": "hash-z",
                    "count": 1,
                },
            ],
            "SELECT count() AS count FROM embeddings_1 GROUP ALL;": [{"count": 2}],
            "SELECT chunk_id, embedding_model, chunk_strategy, text_hash, array::len(vector) AS embedding_dimension FROM embeddings_0 LIMIT 50;": [
                {
                    "chunk_id": "chunk-b",
                    "embedding_model": "model-b",
                    "chunk_strategy": "heading_512_50",
                    "text_hash": "hash-b",
                    "embedding_dimension": 3,
                },
            ],
            "SELECT chunk_id, embedding_model, chunk_strategy, text_hash, array::len(vector) AS embedding_dimension FROM embeddings_1 LIMIT 50;": [
                {
                    "chunk_id": "chunk-c",
                    "embedding_model": "model-a",
                    "chunk_strategy": "heading_512_50",
                    "text_hash": "hash-c",
                    "embedding_dimension": 4,
                },
                {
                    "chunk_id": "chunk-orphan",
                    "embedding_model": "model-a",
                    "chunk_strategy": "heading_512_50",
                    "text_hash": "hash-z",
                    "embedding_dimension": 3,
                },
            ],
            "SELECT embedding_model, array::len(vector) AS embedding_dimension FROM embeddings_0 LIMIT 50;": [
                {
                    "embedding_model": "model-b",
                    "embedding_dimension": 3,
                },
            ],
            "SELECT embedding_model, array::len(vector) AS embedding_dimension FROM embeddings_0;": [
                {
                    "embedding_model": "model-b",
                    "embedding_dimension": 3,
                },
            ],
            "SELECT embedding_model, array::len(vector) AS embedding_dimension FROM embeddings_1 LIMIT 50;": [
                {
                    "embedding_model": "model-a",
                    "embedding_dimension": 4,
                },
                {
                    "embedding_model": "model-a",
                    "embedding_dimension": 3,
                },
            ],
            "SELECT embedding_model, array::len(vector) AS embedding_dimension FROM embeddings_1;": [
                {
                    "embedding_model": "model-a",
                    "embedding_dimension": 4,
                },
                {
                    "embedding_model": "model-a",
                    "embedding_dimension": 3,
                },
            ],
            "SELECT chunk_id FROM chunks LIMIT 20;": [
                {"chunk_id": "chunk-a"},
                {"chunk_id": "chunk-b"},
                {"chunk_id": "chunk-c"},
            ],
            "SELECT chunk_id FROM provenance LIMIT 20;": [
                {"chunk_id": "chunk-a"},
                {"chunk_id": "chunk-b"},
                {"chunk_id": "chunk-c"},
                {"chunk_id": "chunk-orphan"},
            ],
            "SELECT chunk_id, namespace, document_ref, 1 AS count FROM provenance LIMIT 20;": [
                {
                    "chunk_id": "chunk-a",
                    "namespace": "filesystem",
                    "document_ref": "/mnt/a.md",
                    "count": 1,
                },
                {
                    "chunk_id": "chunk-a",
                    "namespace": "notes",
                    "document_ref": "/mnt/a.md",
                    "count": 1,
                },
                {
                    "chunk_id": "chunk-c",
                    "namespace": "filesystem",
                    "document_ref": "/mnt/c.md",
                    "count": 1,
                },
            ],
            "SELECT chunk_id FROM embeddings_0 WHERE chunk_id IN [\"chunk-a\", \"chunk-b\", \"chunk-c\"] LIMIT 20;": [
                {"chunk_id": "chunk-b"}
            ],
            "SELECT chunk_id FROM embeddings_1 WHERE chunk_id IN [\"chunk-a\", \"chunk-b\", \"chunk-c\"] LIMIT 20;": [
                {"chunk_id": "chunk-c"}
            ],
            "SELECT chunk_id FROM provenance WHERE chunk_id IN [\"chunk-a\", \"chunk-b\", \"chunk-c\"] LIMIT 20;": [
                {"chunk_id": "chunk-a"},
                {"chunk_id": "chunk-c"},
            ],
            "SELECT chunk_id FROM chunks WHERE chunk_id IN [\"chunk-a\", \"chunk-b\", \"chunk-c\", \"chunk-orphan\"] LIMIT 20;": [
                {"chunk_id": "chunk-a"},
                {"chunk_id": "chunk-b"},
                {"chunk_id": "chunk-c"},
            ],
            "SELECT chunk_id FROM embeddings_0 LIMIT 20;": [
                {"chunk_id": "chunk-b"},
            ],
            "SELECT chunk_id FROM embeddings_1 LIMIT 20;": [
                {"chunk_id": "chunk-c"},
            ],
            "SELECT chunk_id FROM chunks WHERE chunk_id IN [\"chunk-b\"] LIMIT 20;": [
                {"chunk_id": "chunk-b"},
            ],
            "SELECT chunk_id FROM chunks WHERE chunk_id IN [\"chunk-c\"] LIMIT 20;": [
                {"chunk_id": "chunk-c"},
            ],
            "SELECT count() AS count FROM chunks WHERE chunk_id NOT IN (SELECT chunk_id FROM provenance GROUP ALL) GROUP ALL;": [
                {"count": 1}
            ],
            "SELECT chunk_id FROM chunks WHERE chunk_id NOT IN (SELECT chunk_id FROM provenance GROUP ALL) LIMIT 20;": [
                {"chunk_id": "chunk-b"}
            ],
            "SELECT count() AS count FROM chunks WHERE chunk_id NOT IN (SELECT chunk_id FROM embeddings_0 GROUP ALL) AND chunk_id NOT IN (SELECT chunk_id FROM embeddings_1 GROUP ALL) GROUP ALL;": [
                {"count": 1}
            ],
            "SELECT chunk_id FROM chunks WHERE chunk_id NOT IN (SELECT chunk_id FROM embeddings_0 GROUP ALL) AND chunk_id NOT IN (SELECT chunk_id FROM embeddings_1 GROUP ALL) LIMIT 20;": [
                {"chunk_id": "chunk-a"}
            ],
            "SELECT count() AS count FROM provenance WHERE chunk_id NOT IN (SELECT chunk_id FROM chunks GROUP ALL) GROUP ALL;": [
                {"count": 1}
            ],
            "SELECT chunk_id FROM provenance WHERE chunk_id NOT IN (SELECT chunk_id FROM chunks GROUP ALL) LIMIT 20;": [
                {"chunk_id": "chunk-orphan"}
            ],
            "SELECT count() AS count FROM embeddings_0 WHERE chunk_id NOT IN (SELECT chunk_id FROM chunks GROUP ALL) GROUP ALL;": [
                {"count": 0}
            ],
            "SELECT chunk_id FROM embeddings_0 WHERE chunk_id NOT IN (SELECT chunk_id FROM chunks GROUP ALL) LIMIT 20;": [],
            "SELECT count() AS count FROM embeddings_1 WHERE chunk_id NOT IN (SELECT chunk_id FROM chunks GROUP ALL) GROUP ALL;": [
                {"count": 1}
            ],
            "SELECT chunk_id FROM embeddings_1 WHERE chunk_id NOT IN (SELECT chunk_id FROM chunks GROUP ALL) LIMIT 20;": [
                {"chunk_id": "chunk-orphan"}
            ],
            "SELECT chunk_id, namespace, document_ref, count() AS count FROM provenance GROUP BY chunk_id, namespace, document_ref ORDER BY chunk_id ASC, namespace ASC, document_ref ASC;": [
                {
                    "chunk_id": "chunk-a",
                    "namespace": "filesystem",
                    "document_ref": "/mnt/a.md",
                    "count": 2,
                },
                {
                    "chunk_id": "chunk-a",
                    "namespace": "notes",
                    "document_ref": "/mnt/a.md",
                    "count": 1,
                },
                {
                    "chunk_id": "chunk-c",
                    "namespace": "filesystem",
                    "document_ref": "/mnt/c.md",
                    "count": 1,
                },
                {
                    "chunk_id": "chunk-orphan",
                    "namespace": "filesystem",
                    "document_ref": "/mnt/z.md",
                    "count": 1,
                },
            ],
            "SELECT count() AS count FROM files GROUP ALL;": [{"count": 11}],
            "SELECT count() AS count FROM sections GROUP ALL;": [{"count": 12}],
            "SELECT count() AS count FROM entities GROUP ALL;": [{"count": 13}],
            "SELECT count() AS count FROM tags GROUP ALL;": [{"count": 14}],
            "SELECT count() AS count FROM relations GROUP ALL;": [{"count": 15}],
        }
        return responses.get(statement, [])

    def query_raw(self, statement: str, variables: dict | None = None):
        self.query_raw_calls.append(statement)
        responses = {
            "INFO FOR TABLE chunks;": {
                "result": {
                    "indexes": {
                        "chunks_chunk_id_idx": "DEFINE INDEX chunks_chunk_id_idx ON chunks FIELDS chunk_id UNIQUE;",
                        "chunks_ref_idx": "DEFINE INDEX chunks_ref_idx ON chunks FIELDS ref;",
                    }
                }
            },
            "INFO FOR TABLE embeddings;": {
                "result": {
                    "indexes": {
                        "embeddings_strategy_chunk_model_idx": "DEFINE INDEX embeddings_strategy_chunk_model_idx ON embeddings FIELDS chunk_strategy, chunk_id, embedding_model UNIQUE;",
                        "embeddings_strategy_model_idx": "DEFINE INDEX embeddings_strategy_model_idx ON embeddings FIELDS chunk_strategy, embedding_model;",
                        "embeddings_text_hash_idx": "DEFINE INDEX embeddings_text_hash_idx ON embeddings FIELDS text_hash;",
                        "embeddings_vector_hnsw": "DEFINE INDEX embeddings_vector_hnsw ON embeddings FIELDS vector HNSW DIMENSION 3 DIST COSINE TYPE F16 EFC 40 M 12 M0 24 LM 6;",
                    }
                }
            },
            "INFO FOR TABLE embeddings_0;": {
                "result": {
                    "indexes": {
                        "embeddings_0_vector_hnsw": "DEFINE INDEX embeddings_0_vector_hnsw ON embeddings_0 FIELDS vector HNSW DIMENSION 3 DIST COSINE TYPE F16 EFC 40 M 12 M0 24 LM 6;",
                    }
                }
            },
            "INFO FOR TABLE embeddings_1;": {
                "result": {
                    "indexes": {
                        "embeddings_1_vector_hnsw": "DEFINE INDEX embeddings_1_vector_hnsw ON embeddings_1 FIELDS vector HNSW DIMENSION 3 DIST COSINE TYPE F16 EFC 40 M 12 M0 24 LM 6;",
                    }
                }
            },
        }
        return responses.get(statement, {})


def test_read_settings_from_env_uses_live_surreal_env(monkeypatch) -> None:
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL_URL", "http://surrealdb:8000")
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL_NAMESPACE", "dotmd")
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL_DATABASE", "production")
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL_USERNAME", "alice")
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL_PASSWORD", "secret")
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL_EMBEDDING_DIMENSION", "3")
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL_EMBEDDING_SHARD_COUNT", "2")
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL_HNSW_EF", "40")
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL_VECTOR_INDEX_TYPE", "f16")

    settings = read_settings_from_env()

    assert settings == SurrealCompletenessAuditSettings(
        url="http://surrealdb:8000",
        namespace="dotmd",
        database="production",
        username="alice",
        password="secret",
        access_token=None,
        embedding_dimension=3,
        embedding_shard_count=2,
        hnsw_ef=40,
        vector_index_type="F16",
        hnsw_m=12,
    )


def test_audit_completeness_reports_coverage_indexes_distribution_and_graph_counts(capsys) -> None:
    settings = SurrealCompletenessAuditSettings(
        url="http://surrealdb:8000",
        namespace="dotmd",
        database="production",
        username=None,
        password=None,
        access_token=None,
        embedding_dimension=3,
        embedding_shard_count=2,
        hnsw_ef=40,
        vector_index_type="F16",
        hnsw_m=12,
    )
    connection = _FakeAuditConnection()

    report = _audit_completeness(connection, settings)
    payload = asdict(report)
    captured = capsys.readouterr()

    assert isinstance(report, CompletenessAuditReport)
    assert report.status == "needs_attention"
    assert report.counts["chunks"] is None
    assert report.counts["chunks_mode"] == "not_run"
    assert report.counts["provenance"] is None
    assert report.counts["provenance_mode"] == "not_run"
    assert report.counts["embeddings"] == 3
    assert report.counts["embedding_rows_by_table"] == {"embeddings_0": 1, "embeddings_1": 2}
    assert report.counts["embeddings_mode"] == "sample"
    assert report.counts["embeddings_sample_size"] == 100
    assert report.coverage["chunks_without_provenance_count"] is None
    assert report.coverage["chunks_without_provenance_sample"] == ["chunk-b"]
    assert report.coverage["chunks_without_provenance_count_mode"] == "sample"
    assert report.coverage["chunks_without_provenance_sample_size"] == 3
    assert report.coverage["chunks_without_embeddings_count"] is None
    assert report.coverage["chunks_without_embeddings_sample"] == []
    assert report.coverage["chunks_without_embeddings_count_mode"] == "not_run"
    assert report.coverage["chunks_without_embeddings_sample_size"] == 0
    assert report.coverage["orphan_provenance_count"] is None
    assert report.coverage["orphan_provenance_sample"] == ["chunk-orphan"]
    assert report.coverage["orphan_provenance_count_mode"] == "sample"
    assert report.coverage["orphan_provenance_sample_size"] == 4
    assert report.coverage["orphan_embeddings_count"] is None
    assert report.coverage["orphan_embeddings_sample"] == []
    assert report.coverage["orphan_embeddings_count_mode"] == "sample"
    assert report.coverage["orphan_embeddings_sample_size"] == 2
    assert report.coverage["duplicate_provenance_key_count"] == 0
    assert report.coverage["duplicate_provenance_key_sample"] == []
    assert report.coverage["provenance_fanout_count"] == 1
    assert report.coverage["provenance_fanout_sample"] == [{"chunk_id": "chunk-a", "count": 2}]
    assert report.coverage["embedding_fields"] == {
        "scan_mode": "sample",
        "sample_size": 100,
        "row_count": 3,
        "present_counts": {
            "chunk_id": 3,
            "embedding_model": 3,
            "chunk_strategy": 3,
            "text_hash": 3,
        },
        "missing_counts": {
            "chunk_id": 0,
            "embedding_model": 0,
            "chunk_strategy": 0,
            "text_hash": 0,
        },
        "distinct_value_counts": {
            "chunk_id": 3,
            "embedding_model": 2,
            "chunk_strategy": 1,
            "text_hash": 3,
        },
    }
    assert report.provenance_fanout_by_chunk_id == [{"chunk_id": "chunk-a", "count": 2}]
    assert report.duplicate_provenance_keys == []
    assert report.embedding_distribution["model_counts"] == {"model-a": 2, "model-b": 1}
    assert report.embedding_distribution["dimension_counts"] == {"3": 2, "4": 1}
    assert report.embedding_distribution["configured_dimension_mismatch_count"] == 1
    assert report.embedding_distribution["scan_mode"] == "sample"
    assert report.embedding_distribution["sample_size"] == 100
    assert report.embedding_distribution["sampled_row_count"] == 3
    assert report.graph_table_counts == {
        "files": None,
        "sections": None,
        "entities": None,
        "tags": None,
        "relations": None,
    }
    assert report.index_audits["chunks"].missing_index_names == ()
    assert report.index_audits["chunks"].definition_mismatches == ()
    assert report.index_audits["embeddings"].missing_index_names == ()
    assert report.index_audits["embeddings"].definition_mismatches == ()
    assert report.index_audits["embeddings_0"].expected_index_names == ("embeddings_0_vector_hnsw",)
    assert report.index_audits["embeddings_0"].definition_mismatches == ()
    assert report.index_audits["embeddings_1"].expected_index_names == ("embeddings_1_vector_hnsw",)
    assert report.index_audits["embeddings_1"].definition_mismatches == ()
    assert _human_summary(report) == (
        "status=needs_attention chunks=not_run provenance=not_run embeddings=sample(3/100) vector_dims=sample(3/100) "
        "missing_provenance=sample(1/3)/unknown missing_embeddings=not_run provenance_fanout_chunks=1 duplicate_provenance_keys=0 "
        "index_missing=0 index_mismatches=0 "
        "graph_relations=not_run"
    )
    assert payload["index_audits"]["embeddings_0"]["observed_index_names"] == (
        "embeddings_0_vector_hnsw",
    )
    assert connection.query_calls == [
        "SELECT chunk_id, embedding_model, chunk_strategy, text_hash, array::len(vector) AS embedding_dimension FROM embeddings_0 LIMIT 50;",
        "SELECT chunk_id, embedding_model, chunk_strategy, text_hash, array::len(vector) AS embedding_dimension FROM embeddings_1 LIMIT 50;",
        "SELECT chunk_id FROM chunks LIMIT 20;",
        "SELECT chunk_id FROM provenance WHERE chunk_id IN [\"chunk-a\", \"chunk-b\", \"chunk-c\"] LIMIT 20;",
        "SELECT chunk_id FROM provenance LIMIT 20;",
        "SELECT chunk_id FROM chunks WHERE chunk_id IN [\"chunk-a\", \"chunk-b\", \"chunk-c\", \"chunk-orphan\"] LIMIT 20;",
        "SELECT chunk_id FROM embeddings_0 LIMIT 20;",
        "SELECT chunk_id FROM chunks WHERE chunk_id IN [\"chunk-b\"] LIMIT 20;",
        "SELECT chunk_id FROM embeddings_1 LIMIT 20;",
        "SELECT chunk_id FROM chunks WHERE chunk_id IN [\"chunk-c\"] LIMIT 20;",
        "SELECT chunk_id, namespace, document_ref, 1 AS count FROM provenance LIMIT 20;",
    ]
    assert "SELECT chunk_id FROM chunks WHERE chunk_id NOT IN (SELECT chunk_id FROM provenance GROUP ALL) LIMIT 20;" not in connection.query_calls
    assert "SELECT count() AS count FROM chunks WHERE chunk_id NOT IN (SELECT chunk_id FROM provenance GROUP ALL) GROUP ALL;" not in connection.query_calls
    assert "SELECT chunk_id FROM provenance WHERE chunk_id NOT IN (SELECT chunk_id FROM chunks GROUP ALL) LIMIT 20;" not in connection.query_calls
    assert "SELECT count() AS count FROM provenance WHERE chunk_id NOT IN (SELECT chunk_id FROM chunks GROUP ALL) GROUP ALL;" not in connection.query_calls
    assert "SELECT chunk_id FROM embeddings_0 WHERE chunk_id NOT IN (SELECT chunk_id FROM chunks GROUP ALL) LIMIT 20;" not in connection.query_calls
    assert "SELECT chunk_id FROM embeddings_1 WHERE chunk_id NOT IN (SELECT chunk_id FROM chunks GROUP ALL) LIMIT 20;" not in connection.query_calls
    assert "[audit] SELECT chunk_id FROM chunks LIMIT 20;: start" in captured.err
    assert "[audit] SELECT chunk_id FROM chunks LIMIT 20;: done in" in captured.err


def test_audit_completeness_sanitizes_password_from_report() -> None:
    settings = SurrealCompletenessAuditSettings(
        url="http://surrealdb:8000",
        namespace="dotmd",
        database="production",
        username="alice",
        password="secret",
        access_token=None,
        embedding_dimension=3,
        embedding_shard_count=2,
        hnsw_ef=40,
        vector_index_type="F16",
        hnsw_m=12,
    )
    connection = _FakeAuditConnection()

    report = _audit_completeness(connection, settings)
    payload = asdict(report)
    settings_payload = payload["settings"]

    assert "secret" not in json.dumps(payload)
    assert "password" not in settings_payload
    assert "access_token" not in settings_payload
    assert settings_payload == {
        "url": "http://surrealdb:8000",
        "namespace": "dotmd",
        "database": "production",
        "auth_mode": "username_password",
        "has_username": True,
        "embedding_dimension": 3,
        "embedding_shard_count": 2,
        "hnsw_ef": 40,
        "vector_index_type": "F16",
        "hnsw_m": 12,
    }


def test_audit_completeness_sanitizes_access_token_from_report() -> None:
    settings = SurrealCompletenessAuditSettings(
        url="http://surrealdb:8000",
        namespace="dotmd",
        database="production",
        username=None,
        password=None,
        access_token="secret-token",
        embedding_dimension=3,
        embedding_shard_count=1,
        hnsw_ef=40,
        vector_index_type="F16",
        hnsw_m=12,
    )
    connection = _FakeAuditConnection()

    report = _audit_completeness(connection, settings)
    payload = asdict(report)
    settings_payload = payload["settings"]

    assert "secret" not in json.dumps(payload)
    assert "password" not in settings_payload
    assert "access_token" not in settings_payload
    assert settings_payload == {
        "url": "http://surrealdb:8000",
        "namespace": "dotmd",
        "database": "production",
        "auth_mode": "access_token",
        "has_username": False,
        "embedding_dimension": 3,
        "embedding_shard_count": 1,
        "hnsw_ef": 40,
        "vector_index_type": "F16",
        "hnsw_m": 12,
    }


def test_audit_completeness_keeps_fanout_informational_when_keys_are_unique() -> None:
    settings = SurrealCompletenessAuditSettings(
        url="http://surrealdb:8000",
        namespace="dotmd",
        database="production",
        username=None,
        password=None,
        access_token=None,
        embedding_dimension=3,
        embedding_shard_count=2,
        hnsw_ef=40,
        vector_index_type="F16",
        hnsw_m=12,
    )

    class _FanoutOnlyConnection(_FakeAuditConnection):
        def query(self, statement: str, variables: dict | None = None):
            self.query_calls.append(statement)
            responses = {
                "SELECT count() AS count FROM chunks GROUP ALL;": [{"count": 3}],
                "SELECT count() AS count FROM provenance GROUP ALL;": [{"count": 4}],
                "SELECT chunk_id, embedding_model, chunk_strategy, text_hash, array::len(vector) AS embedding_dimension FROM embeddings_0 LIMIT 50;": [
                    {
                        "chunk_id": "chunk-a",
                        "embedding_model": "model-a",
                        "chunk_strategy": "heading_512_50",
                        "text_hash": "hash-a",
                        "embedding_dimension": 3,
                    },
                    {
                        "chunk_id": "chunk-b",
                        "embedding_model": "model-b",
                        "chunk_strategy": "heading_512_50",
                        "text_hash": "hash-b",
                        "embedding_dimension": 3,
                    },
                ],
                "SELECT chunk_id, embedding_model, chunk_strategy, text_hash, array::len(vector) AS embedding_dimension FROM embeddings_1 LIMIT 50;": [
                    {
                        "chunk_id": "chunk-c",
                        "embedding_model": "model-a",
                        "chunk_strategy": "heading_512_50",
                        "text_hash": "hash-c",
                        "embedding_dimension": 4,
                    },
                ],
                "SELECT chunk_id FROM chunks LIMIT 20;": [
                    {"chunk_id": "chunk-a"},
                    {"chunk_id": "chunk-b"},
                    {"chunk_id": "chunk-c"},
                ],
                "SELECT chunk_id FROM embeddings_0 WHERE chunk_id IN [\"chunk-a\", \"chunk-b\", \"chunk-c\"] LIMIT 20;": [
                    {"chunk_id": "chunk-a"},
                    {"chunk_id": "chunk-b"},
                ],
                "SELECT chunk_id FROM embeddings_1 WHERE chunk_id IN [\"chunk-a\", \"chunk-b\", \"chunk-c\"] LIMIT 20;": [
                    {"chunk_id": "chunk-c"},
                ],
                "SELECT chunk_id FROM provenance WHERE chunk_id IN [\"chunk-a\", \"chunk-b\", \"chunk-c\"] LIMIT 20;": [
                    {"chunk_id": "chunk-a"},
                    {"chunk_id": "chunk-b"},
                    {"chunk_id": "chunk-c"},
                ],
                "SELECT chunk_id FROM provenance LIMIT 20;": [
                    {"chunk_id": "chunk-a"},
                    {"chunk_id": "chunk-b"},
                    {"chunk_id": "chunk-c"},
                ],
                "SELECT chunk_id FROM chunks WHERE chunk_id IN [\"chunk-a\", \"chunk-b\", \"chunk-c\"] LIMIT 20;": [
                    {"chunk_id": "chunk-a"},
                    {"chunk_id": "chunk-b"},
                    {"chunk_id": "chunk-c"},
                ],
                "SELECT chunk_id FROM embeddings_0 LIMIT 20;": [
                    {"chunk_id": "chunk-a"},
                    {"chunk_id": "chunk-b"},
                ],
                "SELECT chunk_id FROM chunks WHERE chunk_id IN [\"chunk-a\", \"chunk-b\"] LIMIT 20;": [
                    {"chunk_id": "chunk-a"},
                    {"chunk_id": "chunk-b"},
                ],
                "SELECT chunk_id FROM embeddings_1 LIMIT 20;": [
                    {"chunk_id": "chunk-c"},
                ],
                "SELECT chunk_id FROM chunks WHERE chunk_id IN [\"chunk-c\"] LIMIT 20;": [
                    {"chunk_id": "chunk-c"},
                ],
                "SELECT embedding_model, array::len(vector) AS embedding_dimension FROM embeddings_0 LIMIT 50;": [
                    {
                        "embedding_model": "model-a",
                        "embedding_dimension": 3,
                    },
                    {
                        "embedding_model": "model-b",
                        "embedding_dimension": 3,
                    },
                ],
                "SELECT embedding_model, array::len(vector) AS embedding_dimension FROM embeddings_1 LIMIT 50;": [
                    {
                        "embedding_model": "model-a",
                        "embedding_dimension": 4,
                    },
                ],
                "SELECT chunk_id, namespace, document_ref, 1 AS count FROM provenance LIMIT 20;": [
                    {
                        "chunk_id": "chunk-a",
                        "namespace": "filesystem",
                        "document_ref": "/mnt/a.md",
                        "count": 1,
                    },
                    {
                        "chunk_id": "chunk-a",
                        "namespace": "notes",
                        "document_ref": "/mnt/a.md",
                        "count": 1,
                    },
                    {
                        "chunk_id": "chunk-b",
                        "namespace": "filesystem",
                        "document_ref": "/mnt/b.md",
                        "count": 1,
                    },
                    {
                        "chunk_id": "chunk-c",
                        "namespace": "filesystem",
                        "document_ref": "/mnt/c.md",
                        "count": 1,
                    },
                ],
                "SELECT count() AS count FROM files GROUP ALL;": [{"count": 11}],
                "SELECT count() AS count FROM sections GROUP ALL;": [{"count": 12}],
                "SELECT count() AS count FROM entities GROUP ALL;": [{"count": 13}],
                "SELECT count() AS count FROM tags GROUP ALL;": [{"count": 14}],
                "SELECT count() AS count FROM relations GROUP ALL;": [{"count": 15}],
            }
            return responses.get(statement, [])

    report = _audit_completeness(_FanoutOnlyConnection(), settings)

    assert report.status == "ok"
    assert report.coverage["chunks_without_provenance_count"] is None
    assert report.coverage["chunks_without_embeddings_count"] is None
    assert report.coverage["orphan_provenance_count"] is None
    assert report.coverage["orphan_embeddings_count"] is None
    assert report.provenance_fanout_by_chunk_id == [{"chunk_id": "chunk-a", "count": 2}]
    assert report.duplicate_provenance_keys == []
    assert _human_summary(report) == (
        "status=ok chunks=not_run provenance=not_run embeddings=sample(3/100) vector_dims=sample(3/100) "
        "missing_provenance=sample(0/3)/unknown missing_embeddings=not_run provenance_fanout_chunks=1 duplicate_provenance_keys=0 "
        "index_missing=0 index_mismatches=0 graph_relations=not_run"
    )


def test_build_provenance_fanout_by_chunk_id_is_single_pass() -> None:
    provenance_keys = [
        ("chunk-a", "filesystem", "/mnt/a.md"),
        ("chunk-a", "notes", "/mnt/a.md"),
        ("chunk-b", "filesystem", "/mnt/b.md"),
        ("chunk-b", "filesystem", "/mnt/b.md"),
        ("chunk-c", "filesystem", "/mnt/c.md"),
    ]

    assert _build_provenance_fanout_by_chunk_id(provenance_keys) == [
        {"chunk_id": "chunk-a", "count": 2},
    ]

    source = textwrap.dedent(inspect.getsource(_build_provenance_fanout_by_chunk_id))
    tree = ast.parse(source)
    assert "defaultdict(set)" in source
    assert "for provenance_chunk_id, namespace, document_ref in provenance_keys" not in source
    assert not any(isinstance(node, ast.DictComp) for node in ast.walk(tree))


def test_audit_completeness_can_full_scan_vector_dimensions_when_requested() -> None:
    settings = SurrealCompletenessAuditSettings(
        url="http://surrealdb:8000",
        namespace="dotmd",
        database="production",
        username=None,
        password=None,
        access_token=None,
        embedding_dimension=3,
        embedding_shard_count=2,
        hnsw_ef=40,
        vector_index_type="F16",
        hnsw_m=12,
    )
    connection = _FakeAuditConnection()

    report = _audit_completeness(
        connection,
        settings,
        dimension_sample_size=100,
        exact_counts=True,
        exact_coverage=True,
        exact_embedding_coverage=True,
    )

    assert report.counts["embeddings_mode"] == "exact"
    assert report.embedding_distribution["scan_mode"] == "exact"
    assert report.embedding_distribution["sampled_row_count"] == 3
    assert _human_summary(report) == (
        "status=needs_attention chunks=3 provenance=5 embeddings=exact(3) vector_dims=exact(3) "
        "missing_provenance=exact(1) missing_embeddings=exact(1) provenance_fanout_chunks=1 duplicate_provenance_keys=1 "
        "index_missing=0 index_mismatches=0 graph_relations=15"
    )
    assert "SELECT embedding_model, array::len(vector) AS embedding_dimension FROM embeddings_0;" in connection.query_calls
    assert "SELECT embedding_model, array::len(vector) AS embedding_dimension FROM embeddings_1;" in connection.query_calls


def test_audit_completeness_marks_missing_embedding_index_definitions() -> None:
    settings = SurrealCompletenessAuditSettings(
        url="http://surrealdb:8000",
        namespace="dotmd",
        database="production",
        username=None,
        password=None,
        access_token=None,
        embedding_dimension=3,
        embedding_shard_count=1,
        hnsw_ef=40,
        vector_index_type="F16",
        hnsw_m=12,
    )

    class _MissingIndexConnection(_FakeAuditConnection):
        def query_raw(self, statement: str, variables: dict | None = None):
            if statement == "INFO FOR TABLE embeddings;":
                return {
                    "result": {
                        "indexes": {
                            "embeddings_strategy_chunk_model_idx": "DEFINE INDEX embeddings_strategy_chunk_model_idx ON TABLE embeddings COLUMNS chunk_strategy, chunk_id, embedding_model UNIQUE;",
                        }
                    }
                }
            return super().query_raw(statement, variables)

    report = _audit_completeness(_MissingIndexConnection(), settings)

    assert report.index_audits["embeddings"].missing_index_names == (
        "embeddings_strategy_model_idx",
        "embeddings_text_hash_idx",
        "embeddings_vector_hnsw",
    )
    assert report.status == "needs_attention"
