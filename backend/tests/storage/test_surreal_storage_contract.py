from __future__ import annotations

from pathlib import Path
from typing import Any

from dotmd.feedback import FeedbackStore
from dotmd.storage.surreal_inventory import (
    build_surreal_migration_map,
    collect_feedback_inventory,
)


class _FakeSurrealClient:
    calls: list[tuple[str, Any]]

    def __init__(self, url: str) -> None:
        self.url = url
        self.calls = []

    def connect(self) -> None:
        self.calls.append(("connect", None))

    def use(self, namespace: str, database: str) -> None:
        self.calls.append(("use", (namespace, database)))

    def signin(self, credentials: dict[str, str]) -> None:
        self.calls.append(("signin", credentials))

    def authenticate(self, token: str) -> None:
        self.calls.append(("authenticate", token))

    def close(self) -> None:
        self.calls.append(("close", None))


class _FakeFeedbackProvider:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.calls: list[tuple[int, bool]] = []

    def list_all(self, limit: int = 50, include_closed: bool = False) -> list[dict[str, object]]:
        self.calls.append((limit, include_closed))
        return self._rows[:limit]


def test_collect_feedback_inventory_uses_provider_abstraction_and_not_raw_sql(
    tmp_path: Path,
) -> None:
    feedback_db = tmp_path / "feedback.db"
    store = FeedbackStore(feedback_db)
    store.submit("One", severity="bug", model="gpt")
    store.submit("Two", severity="suggestion", model="gpt")
    provider = _FakeFeedbackProvider(store.list_all(limit=50, include_closed=True))

    inventory = collect_feedback_inventory(provider)

    assert inventory.total_feedback == 2
    assert inventory.status_counts["open"] == 2
    assert provider.calls == [(1001, True)]


def test_collect_feedback_inventory_fails_closed_when_export_may_be_truncated() -> None:
    provider = _FakeFeedbackProvider(
        [
            {
                "status": "open",
                "severity": "bug",
            }
            for _ in range(1001)
        ]
    )

    inventory = collect_feedback_inventory(provider)

    assert inventory.available is False
    assert inventory.total_feedback == 0
    assert "exhaustive feedback export" in str(inventory.unavailable_reason)


def test_build_surreal_migration_map_marks_known_categories_and_rejects_unknown() -> None:
    migration_map = build_surreal_migration_map(
        categories={
            "chunks": {"columns": ["chunk_id", "text"], "verified": True},
            "provenance": {"columns": ["chunk_id", "document_ref"], "verified": True},
            "bindings": {"columns": ["resource_ref", "active"], "verified": True},
            "fingerprints": {"columns": ["chunk_id", "fingerprint"], "verified": True},
            "source_state": {"columns": ["namespace", "checkpoint_cursor"], "verified": True},
            "embeddings": {"columns": ["chunk_id", "text_hash"], "verified": True},
            "vector_components": {"columns": ["entity_id", "component"], "verified": True},
            "graph": {"properties": ["relation_label", "weight"], "verified": True},
            "feedback": {"fields": ["status", "submitted_at"], "verified": True},
            "mystery_table": {"columns": ["oops"], "verified": False},
        }
    )

    assert migration_map.categories["chunks"].disposition == "transformable"
    assert migration_map.categories["embeddings"].disposition == "transformable"
    assert migration_map.categories["graph"].disposition in {"transformable", "unsafe"}
    assert migration_map.categories["mystery_table"].disposition == "unsupported"
    assert "unknown" in migration_map.categories["mystery_table"].reason.lower()


def test_surreal_record_id_codec_round_trips_special_characters_without_leaking_raw_values() -> (
    None
):
    from dotmd.storage.surreal import (  # type: ignore[import-not-found]
        SurrealRecordIdCodec,
        decode_surreal_record_id,
        encode_surreal_record_id,
    )

    codec = SurrealRecordIdCodec()
    raw_identifiers = [
        'chunk:alpha/one {"quoted"}',
        'filesystem:/tmp/Doc One "quoted".md',
        "entity/Привет мир",
        "feedback:{42}/ spaced",
    ]
    forbidden_fragments = ["DROP", "RETURN", "{", "}", '"', "'", "\n", ";"]

    for raw_identifier in raw_identifiers:
        record_id = codec.encode("chunks", raw_identifier)
        assert record_id.table_name == "chunks"
        assert codec.decode(record_id) == raw_identifier
        assert decode_surreal_record_id(record_id) == raw_identifier
        assert decode_surreal_record_id(encode_surreal_record_id("chunks", raw_identifier)) == (
            raw_identifier
        )

        encoded_identifier = str(record_id.id)
        assert raw_identifier not in encoded_identifier
        assert all(fragment not in encoded_identifier for fragment in forbidden_fragments)


def test_define_dotmd_surreal_schema_declares_required_record_shapes_and_schema_contract() -> None:
    from dotmd.storage.surreal import define_dotmd_surreal_schema  # type: ignore[import-not-found]
    from dotmd.storage.surreal_schema import SURREAL_SCHEMA_VERSION

    schema = define_dotmd_surreal_schema()

    assert {
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
    }.issubset(set(schema["tables"]))
    assert schema["schema_version"] == SURREAL_SCHEMA_VERSION
    assert schema["apply_status"].status == "not-applied"
    assert "stats" in schema["unsupported_categories"]
    assert "chunk_file_bindings" in schema["required_categories"]
    assert any(
        "DEFINE TABLE documents SCHEMAFULL" in statement for statement in schema["statements"]
    )
    assert any(
        "DEFINE TABLE relations TYPE RELATION" in statement for statement in schema["statements"]
    )
    assert not any(
        "DEFINE TABLE documents SCHEMALESS" in statement for statement in schema["statements"]
    )


def test_surreal_connection_signs_in_after_namespace_selection(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from dotmd.storage import surreal as surreal_module
    from dotmd.storage.surreal import SurrealConnection, SurrealStoreConfig

    clients: list[_FakeSurrealClient] = []

    def fake_surreal(url: str) -> _FakeSurrealClient:
        client = _FakeSurrealClient(url)
        clients.append(client)
        return client

    monkeypatch.setattr(surreal_module, "Surreal", fake_surreal)

    connection = SurrealConnection(
        SurrealStoreConfig(
            url="http://surrealdb:8000",
            namespace="dotmd",
            database="phase43",
            username="root",
            password="secret",
        )
    )

    assert clients[0].calls == [
        ("connect", None),
        ("use", ("dotmd", "phase43")),
        ("signin", {"username": "root", "password": "secret"}),
    ]
    connection.close()


def test_surreal_connection_authenticates_token_after_namespace_selection(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from dotmd.storage import surreal as surreal_module
    from dotmd.storage.surreal import SurrealConnection, SurrealStoreConfig

    clients: list[_FakeSurrealClient] = []

    def fake_surreal(url: str) -> _FakeSurrealClient:
        client = _FakeSurrealClient(url)
        clients.append(client)
        return client

    monkeypatch.setattr(surreal_module, "Surreal", fake_surreal)

    connection = SurrealConnection(
        SurrealStoreConfig(
            url="http://surrealdb:8000",
            namespace="dotmd",
            database="phase43",
            access_token="token",
        )
    )

    assert clients[0].calls == [
        ("connect", None),
        ("use", ("dotmd", "phase43")),
        ("authenticate", "token"),
    ]
    connection.close()


def test_surreal_connection_can_use_http_sql_timeout_for_long_queries(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from dotmd.storage import surreal as surreal_module
    from dotmd.storage.surreal import SurrealConnection, SurrealStoreConfig

    clients: list[_FakeSurrealClient] = []
    captured: dict[str, Any] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> list[dict[str, Any]]:
            return [{"status": "OK", "result": [{"ok": True}]}]

    def fake_surreal(url: str) -> _FakeSurrealClient:
        client = _FakeSurrealClient(url)
        clients.append(client)
        return client

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return FakeResponse()

    monkeypatch.setattr(surreal_module, "Surreal", fake_surreal)
    monkeypatch.setattr(surreal_module.requests, "post", fake_post)

    connection = SurrealConnection(
        SurrealStoreConfig(
            url="http://surrealdb:8000",
            namespace="dotmd",
            database="production",
            username="root",
            password="secret",
            http_query_timeout_seconds=2400,
        )
    )

    result = connection.query("DEFINE INDEX embeddings_vector_hnsw ON TABLE embeddings;")

    assert result == [{"ok": True}]
    assert captured["url"] == "http://surrealdb:8000/sql"
    assert captured["kwargs"]["timeout"] == 2400
    assert captured["kwargs"]["auth"] == ("root", "secret")
    assert captured["kwargs"]["headers"]["Surreal-NS"] == "dotmd"
    assert captured["kwargs"]["headers"]["Surreal-DB"] == "production"
    assert captured["kwargs"]["data"] == b"DEFINE INDEX embeddings_vector_hnsw ON TABLE embeddings;"
    connection.close()


def test_surreal_stores_expose_existing_protocol_method_names(tmp_path: Path) -> None:
    from dotmd.storage.base import GraphStoreProtocol, MetadataStoreProtocol, VectorStoreProtocol
    from dotmd.storage.surreal import (  # type: ignore[import-not-found]
        SurrealConnection,
        SurrealGraphStore,
        SurrealMetadataStore,
        SurrealStoreConfig,
        SurrealVectorStore,
    )

    db_path = tmp_path / "storage-contract.db"
    config = SurrealStoreConfig(
        url=f"surrealkv://{db_path}",
        namespace="dotmd",
        database="phase38_contract",
    )

    with SurrealConnection(config) as connection:
        metadata_store = SurrealMetadataStore(connection)
        vector_store = SurrealVectorStore(connection)
        graph_store = SurrealGraphStore(connection)

        assert isinstance(metadata_store, MetadataStoreProtocol)
        assert isinstance(vector_store, VectorStoreProtocol)
        assert isinstance(graph_store, GraphStoreProtocol)


def test_surreal_vector_store_uses_vector_field_only(tmp_path: Path) -> None:
    from dotmd.storage.surreal import (  # type: ignore[import-not-found]
        SurrealConnection,
        SurrealStoreConfig,
        SurrealVectorStore,
        define_dotmd_surreal_schema,
    )
    from dotmd.storage.surreal_schema import SURREAL_SCHEMA_VERSION

    db_path = tmp_path / "vector-contract.db"
    config = SurrealStoreConfig(url=f"surrealkv://{db_path}")

    with SurrealConnection(config) as connection:
        define_dotmd_surreal_schema(connection)
        vector_store = SurrealVectorStore(connection)
        vector_store.replace_embedding_rows(
            [
                {
                    "schema_version": SURREAL_SCHEMA_VERSION,
                    "chunk_id": "chunk-1",
                    "original_chunk_id": "chunk-1",
                    "chunk_strategy": "contextual_512_50",
                    "embedding_model": "multilingual-e5-large",
                    "text_hash": "hash-1",
                    "vector_rowid": 1,
                    "vector": [0.1, 0.2, 0.3],
                    "metadata": {},
                }
            ]
        )
        stored = connection.select(
            vector_store._codec.encode(
                "embeddings",
                "contextual_512_50\x1fmultilingual-e5-large\x1fchunk-1",
            )
        )

    assert stored["vector"] == [0.1, 0.2, 0.3]
    assert "embedding" not in stored


def test_surreal_metadata_store_hydrates_active_provenance_from_chunks(tmp_path: Path) -> None:
    from dotmd.storage.surreal import (
        SurrealConnection,
        SurrealMetadataStore,
        SurrealStoreConfig,
        define_dotmd_surreal_schema,
    )

    db_path = tmp_path / "provenance-contract.db"
    config = SurrealStoreConfig(url=f"surrealkv://{db_path}")

    with SurrealConnection(config) as connection:
        define_dotmd_surreal_schema(connection)
        store = SurrealMetadataStore(connection)
        store.replace_chunk_rows(
            [
                {
                    "schema_version": "test",
                    "original_chunk_id": "telegram-chunk",
                    "chunk_id": "telegram-chunk",
                    "chunk_strategy": "contextual_512_50",
                    "document_ref": "dialog:289227226",
                    "ref": "telegram:dialog:289227226",
                    "text": "hello",
                    "heading_hierarchy": [],
                    "level": 0,
                    "file_paths": [],
                    "file_bindings": [],
                    "source_unit_refs": ["dialog:289227226"],
                    "metadata": {},
                }
            ]
        )

        provenance = store.get_active_chunk_provenance_for_chunk_ids(
            "contextual_512_50",
            ["telegram-chunk"],
        )

    assert provenance["telegram-chunk"].ref == "telegram:dialog:289227226"
    assert provenance["telegram-chunk"].source_unit_refs == ["dialog:289227226"]
