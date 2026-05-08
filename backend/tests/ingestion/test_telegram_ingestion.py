"""Tests for Telegram application-source ingestion."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from click.testing import CliRunner

from dotmd.cli import main
from dotmd.core.config import Settings
from dotmd.core.models import Chunk, ExtractDepth
from dotmd.ingestion.pipeline import IndexingPipeline
from dotmd.ingestion.telegram_provider import TelegramApplicationSourceProvider
from dotmd.storage.metadata import SQLiteMetadataStore

STRATEGY = "heading_512_50"
VALID_CHUNK_ID = "a" * 64


class _TelegramSourceClientFixture:
    def __init__(self, changes: list[dict] | None = None) -> None:
        self.export_calls: list[dict] = []
        self._changes = changes or _telegram_changes()

    def describe_source(self) -> dict:
        return {
            "namespace": "telegram",
            "source_kind": "chat",
            "display_name": "Telegram",
            "capabilities": ["incremental-export", "unit-window"],
            "metadata_json": {"transport": "fixture"},
        }

    def export_source_changes(
        self,
        cursor: str | None,
        limit: int,
        updated_after: str | None = None,
        updated_after_cursor: str | None = None,
    ) -> dict:
        self.export_calls.append(
            {
                "cursor": cursor,
                "limit": limit,
                "updated_after": updated_after,
                "updated_after_cursor": updated_after_cursor,
            }
        )
        start = 0
        if updated_after is not None and limit >= len(self._changes):
            start = 0
        elif cursor:
            for index, change in enumerate(self._changes):
                if _cursor_for_message(change["unit"]["message_id"]) == cursor:
                    start = index + 1
                    break
        rows = self._changes[start : start + limit]
        last_message_id = rows[-1]["unit"]["message_id"] if rows else None
        next_index = start + len(rows)
        next_cursor = (
            _cursor_for_message(self._changes[next_index - 1]["unit"]["message_id"])
            if rows and next_index < len(self._changes)
            else None
        )
        return {
            "changes": rows,
            "next_cursor": next_cursor,
            "checkpoint_cursor": _cursor_for_message(last_message_id)
            if last_message_id is not None
            else cursor,
            "updated_after": "2026-05-07T12:00:02.000000Z",
            "updated_after_cursor": _cursor_for_message(last_message_id)
            if last_message_id is not None
            else updated_after_cursor,
        }

    def read_source_unit_window(
        self,
        unit_ref: str,
        before: int,
        after: int,
    ) -> dict:
        return {
            "namespace": "telegram",
            "document_ref": "dialog:-1001",
            "unit_ref": unit_ref,
            "units": [change["unit"] for change in self._changes],
            "metadata_json": {"dialog_id": -1001},
        }


class _KeywordRecorder:
    def __init__(self, conn, table_name: str) -> None:  # type: ignore[no-untyped-def]
        self._conn = conn
        self._table = table_name
        self.source_meta_calls: list[dict] = []

    def add_chunks_with_source_meta(
        self,
        chunks,
        *,
        title: str,
        tags_csv: str,
        conn,
    ) -> None:  # type: ignore[no-untyped-def]
        self.source_meta_calls.append(
            {"chunk_ids": [chunk.chunk_id for chunk in chunks], "title": title, "tags": tags_csv}
        )
        conn.executemany(
            f"INSERT INTO {self._table}(chunk_id, text, title, tags) VALUES (?, ?, ?, ?)",
            [(chunk.chunk_id, chunk.text, title, tags_csv) for chunk in chunks],
        )

    def add_chunks(self, chunks, file_meta=None):  # type: ignore[no-untyped-def]
        raise AssertionError("Telegram ingestion must use add_chunks_with_source_meta")


def _cursor_for_message(message_id: int | None) -> str | None:
    if message_id is None:
        return None
    return f"telegram:v1:dialog:-1001:message:{message_id}"


def _change(
    *,
    message_id: int,
    text: str,
    sender_id: int,
    sender_name: str,
    sent_at: str,
    topic_id: int | None,
    topic_title: str | None,
    reply_to_msg_id: int | None,
    edit_date: str | None,
) -> dict:
    return {
        "document": {
            "dialog_id": -1001,
            "dialog_name": "Project Chat",
            "updated_at": sent_at,
            "unit_count": 3,
        },
        "unit": {
            "dialog_id": -1001,
            "dialog_name": "Project Chat",
            "message_id": message_id,
            "text": text,
            "sent_at": sent_at,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "topic_id": topic_id,
            "topic_title": topic_title,
            "reply_to_msg_id": reply_to_msg_id,
            "edit_date": edit_date,
            "is_deleted": False,
            "unit_updated_at": edit_date or sent_at,
        },
    }


def _telegram_changes() -> list[dict]:
    return [
        _change(
            message_id=42,
            text="Deployment checklist is ready",
            sender_id=111,
            sender_name="Alice",
            sent_at="2026-05-07T12:00:00.000000Z",
            topic_id=7,
            topic_title="Deployments",
            reply_to_msg_id=41,
            edit_date=None,
        ),
        _change(
            message_id=43,
            text="ok",
            sender_id=222,
            sender_name="Bob",
            sent_at="2026-05-07T12:00:01.000000Z",
            topic_id=7,
            topic_title="Deployments",
            reply_to_msg_id=None,
            edit_date=None,
        ),
        _change(
            message_id=44,
            text="Smoke confirms the deployment path",
            sender_id=333,
            sender_name="Carol",
            sent_at="2026-05-07T12:00:02.000000Z",
            topic_id=7,
            topic_title="Deployments",
            reply_to_msg_id=42,
            edit_date=None,
        ),
    ]


def _edited_changes() -> list[dict]:
    return [
        _change(
            message_id=42,
            text="Deployment checklist is ready with rollback",
            sender_id=111,
            sender_name="Alice",
            sent_at="2026-05-07T12:00:00.000000Z",
            topic_id=7,
            topic_title="Deployments",
            reply_to_msg_id=41,
            edit_date="2026-05-07T12:05:00.000000Z",
        ),
        *_telegram_changes()[1:],
    ]


def _pipeline(tmp_path: Path) -> IndexingPipeline:
    data_dir = tmp_path / "data"
    index_dir = tmp_path / "index"
    data_dir.mkdir()
    index_dir.mkdir()
    pipeline = IndexingPipeline(
        Settings(
            data_dir=data_dir,
            index_dir=index_dir,
            embedding_url="http://localhost:18088",
            vector_backend="sqlite-vec",
            graph_backend="ladybugdb",
            extract_depth=ExtractDepth.STRUCTURAL,
        )
    )
    pipeline._semantic_engine.encode_batch = lambda texts: [  # type: ignore[method-assign]
        [float(index + 1)] * 8 for index, _text in enumerate(texts)
    ]
    pipeline._keyword_engine = _KeywordRecorder(  # type: ignore[assignment]
        pipeline._conn,
        pipeline._fts_table,
    )
    return pipeline


def _provider(changes: list[dict] | None = None) -> TelegramApplicationSourceProvider:
    return TelegramApplicationSourceProvider(_TelegramSourceClientFixture(changes))


def _telegram_chunks(pipeline: IndexingPipeline) -> list[Chunk]:
    rows = pipeline._conn.execute(
        f"SELECT chunk_id FROM chunks_{STRATEGY} ORDER BY chunk_id"
    ).fetchall()
    return pipeline._metadata_store.get_chunks([row[0] for row in rows])


def test_save_chunks_accepts_empty_file_paths_before_telegram_refactor(
    tmp_path: Path,
) -> None:
    store = SQLiteMetadataStore(
        db_path=tmp_path / "metadata.db",
        table_name=f"chunks_{STRATEGY}",
    )
    store.ensure_m2m_table(STRATEGY)
    chunk = Chunk(
        chunk_id=VALID_CHUNK_ID,
        file_paths=[],
        heading_hierarchy=["Telegram"],
        level=1,
        text="Telegram message text",
        chunk_index=0,
    )

    store.save_chunks([chunk])

    assert store._conn.execute(
        f"SELECT COUNT(*) FROM chunks_{STRATEGY} WHERE chunk_id = ?",
        (VALID_CHUNK_ID,),
    ).fetchone()[0] == 1
    assert store._conn.execute(
        f"SELECT COUNT(*) FROM chunk_file_paths_{STRATEGY} WHERE chunk_id = ?",
        (VALID_CHUNK_ID,),
    ).fetchone()[0] == 0


def test_ingest_telegram_batch_persists_documents_bindings_units_and_checkpoint(
    tmp_path: Path,
) -> None:
    pipeline = _pipeline(tmp_path)

    result = pipeline.ingest_application_source(_provider(), limit=10)

    assert result.discovered == 3
    assert pipeline._metadata_store.get_source_document("telegram", "dialog:-1001") is not None
    assert pipeline._metadata_store.is_resource_binding_active("telegram", "dialog:-1001")
    assert pipeline._metadata_store.get_source_unit_fingerprint(
        "telegram",
        "dialog:-1001",
        "dialog:-1001:message:42",
    ) is not None
    assert pipeline._metadata_store.get_source_unit_fingerprint(
        "telegram",
        "dialog:-1001",
        "dialog:-1001:message:43",
    ) is not None
    checkpoint = pipeline._metadata_store.get_source_checkpoint("telegram")
    assert checkpoint is not None
    checkpoint_meta = cast(dict[str, Any], checkpoint["metadata_json"])
    assert checkpoint["checkpoint_cursor"] == "telegram:v1:dialog:-1001:message:44"
    assert checkpoint_meta["updated_after"] == "2026-05-07T12:00:02.000000Z"
    assert checkpoint_meta["updated_after_cursor"] == "telegram:v1:dialog:-1001:message:44"
    assert checkpoint_meta["single_batch"] is True


def test_ingest_telegram_replay_skips_unchanged_units(tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path)

    first = pipeline.ingest_application_source(_provider(), limit=10)
    second = pipeline.ingest_application_source(_provider(), limit=10)

    assert first.new_units == 3
    assert second.skipped_units == 3
    assert pipeline._conn.execute(
        f"SELECT COUNT(*) FROM chunks_{STRATEGY}"
    ).fetchone()[0] == 2


def test_ingest_telegram_edit_reindexes_changed_unit_only(tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path)
    pipeline.ingest_application_source(_provider(), limit=10)

    result = pipeline.ingest_application_source(_provider(_edited_changes()), limit=10)

    assert result.changed_units == 1
    assert result.skipped_units == 2
    chunks = pipeline._metadata_store.get_chunks_by_source_unit_ref(
        "telegram",
        "dialog:-1001",
        "dialog:-1001:message:42",
        STRATEGY,
    )
    assert len(chunks) == 1
    assert "with rollback" in chunks[0].text


def test_low_signal_message_is_not_standalone_search_chunk(tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path)

    result = pipeline.ingest_application_source(_provider(), limit=10)

    assert result.hidden_units == 1
    assert pipeline._metadata_store.get_source_unit_fingerprint(
        "telegram",
        "dialog:-1001",
        "dialog:-1001:message:43",
    ) is not None
    assert all(chunk.text.strip() != "ok" for chunk in _telegram_chunks(pipeline))
    assert not any(chunk.text.endswith("\nok") for chunk in _telegram_chunks(pipeline))


def test_telegram_chunks_with_empty_file_paths_are_saved_and_hydrated_by_provenance(
    tmp_path: Path,
) -> None:
    pipeline = _pipeline(tmp_path)

    pipeline.ingest_application_source(_provider(), limit=10)

    chunks = pipeline._metadata_store.get_chunks_by_source_unit_ref(
        "telegram",
        "dialog:-1001",
        "dialog:-1001:message:42",
        STRATEGY,
    )
    assert len(chunks) == 1
    assert chunks[0].file_paths == []
    assert pipeline._conn.execute(
        f"SELECT COUNT(*) FROM chunk_file_paths_{STRATEGY} WHERE chunk_id = ?",
        (chunks[0].chunk_id,),
    ).fetchone()[0] == 0


def test_telegram_fts_and_vector_index_without_fileinfo_frontmatter(
    tmp_path: Path,
) -> None:
    pipeline = _pipeline(tmp_path)
    encoded_texts: list[str] = []
    pipeline._semantic_engine.encode_batch = lambda texts: (  # type: ignore[method-assign]
        encoded_texts.extend(texts) or [[float(index + 1)] * 8 for index, _text in enumerate(texts)]
    )

    pipeline.ingest_application_source(_provider(), limit=10)

    fts_rows = pipeline._conn.execute(
        f"SELECT title, tags FROM chunks_fts_{STRATEGY} ORDER BY chunk_id"
    ).fetchall()
    assert fts_rows
    assert all(title == "Project Chat" for title, _tags in fts_rows)
    assert all("telegram" in tags for _title, tags in fts_rows)
    vec_meta_table = cast(Any, pipeline._vector_store)._META_TABLE
    assert pipeline._conn.execute(
        f"SELECT COUNT(*) FROM {vec_meta_table} WHERE chunk_id IN "
        f"(SELECT chunk_id FROM chunks_{STRATEGY})"
    ).fetchone()[0] == 2
    metadata_inputs = [
        text for text in encoded_texts
        if "telegram" in text and "Project Chat" in text
    ]
    assert metadata_inputs
    assert any("Alice" in text and "Deployments" in text for text in metadata_inputs)
    assert "Deployment checklist is ready" not in metadata_inputs[0]


def test_application_source_ingest_batches_body_and_metadata_embeddings(
    tmp_path: Path,
) -> None:
    pipeline = _pipeline(tmp_path)
    encode_calls: list[list[str]] = []

    def record_encode(texts: list[str]) -> list[list[float]]:
        encode_calls.append(list(texts))
        return [[float(len(encode_calls))] * 8 for _text in texts]

    pipeline._semantic_engine.encode_batch = record_encode  # type: ignore[method-assign]

    result = pipeline.ingest_application_source(_provider(), limit=10)

    assert result.chunks_indexed == 2
    assert [len(call) for call in encode_calls] == [2, 2]
    assert any("Deployment checklist is ready" in text for text in encode_calls[0])
    assert any("Smoke confirms the deployment path" in text for text in encode_calls[0])
    assert all("Project Chat" in text for text in encode_calls[1])
    assert all("Deployment checklist is ready" not in text for text in encode_calls[1])


def test_telegram_transaction_rolls_back_metadata_fts_vectors_and_checkpoint_on_vector_failure(
    tmp_path: Path,
) -> None:
    pipeline = _pipeline(tmp_path)

    def fail_vector_store(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("vector failure")

    pipeline._add_vectors_in_transaction = fail_vector_store  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="vector failure"):
        pipeline.ingest_application_source(_provider(), limit=10)

    assert pipeline._metadata_store.get_source_document("telegram", "dialog:-1001") is None
    assert pipeline._metadata_store.get_source_unit_fingerprint(
        "telegram",
        "dialog:-1001",
        "dialog:-1001:message:42",
    ) is None
    checkpoint = pipeline._metadata_store.get_source_checkpoint("telegram")
    assert checkpoint is not None
    assert checkpoint["checkpoint_cursor"] is None
    assert pipeline._conn.execute(
        f"SELECT COUNT(*) FROM chunks_{STRATEGY}"
    ).fetchone()[0] == 0
    assert pipeline._conn.execute(
        f"SELECT COUNT(*) FROM chunk_source_provenance_{STRATEGY}"
    ).fetchone()[0] == 0
    assert pipeline._conn.execute(
        f"SELECT COUNT(*) FROM chunks_fts_{STRATEGY}"
    ).fetchone()[0] == 0
    assert pipeline._conn.execute(
        f"SELECT COUNT(*) FROM {cast(Any, pipeline._vector_store)._META_TABLE}"
    ).fetchone()[0] == 0


def test_initial_bootstrap_single_batch_semantics_are_explicit(tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path)
    client = _TelegramSourceClientFixture()
    provider = TelegramApplicationSourceProvider(client)

    first = pipeline.ingest_application_source(provider, limit=2)
    second = pipeline.ingest_application_source(provider, limit=2)

    assert first.discovered == 2
    assert second.discovered == 1
    assert client.export_calls[0]["limit"] == 2
    assert client.export_calls[1]["cursor"] == "telegram:v1:dialog:-1001:message:43"
    checkpoint = pipeline._metadata_store.get_source_checkpoint("telegram")
    assert checkpoint is not None
    checkpoint_meta = cast(dict[str, Any], checkpoint["metadata_json"])
    assert checkpoint_meta["single_batch"] is True


def test_filesystem_and_telegram_chunks_coexist(tmp_path: Path) -> None:
    pipeline = _pipeline(tmp_path)
    md_path = tmp_path / "data" / "note.md"
    md_path.write_text("# Filesystem\n\nBody text.", encoding="utf-8")
    filesystem_chunk = Chunk(
        chunk_id="f" * 64,
        file_paths=[md_path],
        heading_hierarchy=["Filesystem"],
        level=1,
        text="Filesystem body",
        chunk_index=0,
    )
    pipeline._metadata_store.save_chunks([filesystem_chunk])

    pipeline.ingest_application_source(_provider(), limit=10)

    assert pipeline._metadata_store.get_chunks_for_file_range(
        STRATEGY,
        str(md_path),
        0,
        10,
    ) == [
        {
            "index": 0,
            "heading_hierarchy": ["Filesystem"],
            "text": "Filesystem body",
        }
    ]
    assert pipeline._conn.execute(
        f"SELECT COUNT(*) FROM chunks_{STRATEGY}"
    ).fetchone()[0] == 3


def test_settings_accepts_telegram_daemon_socket_only(tmp_path: Path) -> None:
    settings = Settings(
        index_dir=tmp_path / "index",
        embedding_url="http://localhost:18088",
        telegram_daemon_socket=tmp_path / "mcp-telegram.sock",
    )

    assert settings.telegram_daemon_socket == tmp_path / "mcp-telegram.sock"
    assert not hasattr(settings, "telegram_daemon" + "_url")


def test_telegram_ingest_cli_requires_configured_socket(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(
        main,
        [
            "--index-dir",
            str(tmp_path / "index"),
            "telegram",
            "ingest",
            "--limit",
            "10",
            "--single-batch",
            "--dry-run",
        ],
        env={"DOTMD_EMBEDDING_URL": "http://localhost:18088"},
    )

    assert result.exit_code != 0
    assert "Telegram daemon socket is not configured" in result.output
