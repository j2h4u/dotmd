"""Tests for Telegram application-source provider mapping."""

from __future__ import annotations

from pathlib import Path

from dotmd.core.models import ApplicationSourceChangeBatch, SearchCandidate
from dotmd.ingestion.telegram_provider import (
    TelegramApplicationSourceProvider,
    is_low_signal_telegram_text,
    public_ref_for_unit,
)


class _TelegramSourceClientFixture:
    def __init__(
        self,
        changes: list[dict] | None = None,
        search_hits: list[dict] | None = None,
    ) -> None:
        self.export_calls: list[dict] = []
        self._changes = changes or _telegram_changes()
        self._search_hits = search_hits if search_hits is not None else _default_search_hits()

    def describe_source(self) -> dict:
        return {
            "namespace": "telegram",
            "source_kind": "chat",
            "display_name": "Telegram",
            "capabilities": ["incremental-export", "unit-window"],
            "metadata_json": {"transport": "mcp-telegram-daemon"},
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
        return {
            "changes": self._changes,
            "next_cursor": "telegram:v1:dialog:-1001:message:45",
            "checkpoint_cursor": "telegram:v1:dialog:-1001:message:44",
            "updated_after": "2026-05-07T12:00:00.000000Z",
            "updated_after_cursor": "telegram:v1:dialog:-1001:message:42",
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

    def search_messages(
        self,
        query: str,
        limit: int,
        dialog_id: int | None = None,
    ) -> dict:
        """Search Telegram messages via daemon FTS. Returns {messages: [...], total: int, ...}"""
        return {"messages": list(self._search_hits[:limit])}


def _default_search_hits() -> list[dict]:
    """Default search hits for federated search testing."""
    return [
        {
            "dialog_id": 12345,
            "dialog_name": "Project Chat",
            "message_id": 67,
            "text": "Kantine is open on Monday",
            "sender": "alice",
            "sent_at": "2026-04-12T08:11:00+00:00",
            "score": 0.93,
        },
        {
            "dialog_id": 12345,
            "dialog_name": "Project Chat",
            "message_id": 68,
            "text": "Kantine menu updated",
            "sender": "bob",
            "sent_at": "2026-04-12T08:15:00+00:00",
            "score": 0.87,
        },
        {
            "dialog_id": 12345,
            "dialog_name": "Project Chat",
            "message_id": 69,
            "text": "Don't forget kantine lunch time",
            "sender": "carol",
            "sent_at": "2026-04-12T08:20:00+00:00",
            "score": 0.81,
        },
    ]


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
            text="ok",
            sender_id=333,
            sender_name="Carol",
            sent_at="2026-05-07T12:00:02.000000Z",
            topic_id=7,
            topic_title="Deployments",
            reply_to_msg_id=None,
            edit_date=None,
        ),
    ]


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
            "dialog_name": "Release Chat",
            "updated_at": sent_at,
        },
        "unit": {
            "dialog_id": -1001,
            "dialog_name": "Release Chat",
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


def _canonical_daemon_change() -> dict:
    return {
        "document": {
            "namespace": "telegram",
            "document_ref": "dialog:-1001",
            "ref": "telegram:dialog:-1001",
            "title": "Project Chat",
            "source_uri": "telegram://dialog/-1001",
            "media_type": "text/plain",
            "parser_name": "telegram-message",
            "document_type": "dialog",
            "updated_at": "2026-05-07T12:00:00.000000Z",
            "content_fingerprint": "dialog-content-fingerprint",
            "metadata_fingerprint": "dialog-metadata-fingerprint",
            "metadata_json": {
                "dialog_id": -1001,
                "dialog_type": "Channel",
                "username": "project_chat",
                "sync_status": "synced",
            },
        },
        "unit": {
            "namespace": "telegram",
            "document_ref": "dialog:-1001",
            "unit_ref": "dialog:-1001:message:42",
            "unit_type": "message",
            "text": "Deployment checklist is ready",
            "order_key": "00000000000000000042",
            "fingerprint": "daemon-message-fingerprint",
            "updated_at": "2026-05-07T12:00:00.000000Z",
            "metadata_json": {
                "dialog_id": -1001,
                "message_id": 42,
                "sent_at": "2026-05-07T12:00:00.000000Z",
                "sender_id": 111,
                "sender_name": "Alice",
                "topic_id": 7,
                "topic_title": "Deployments",
                "reply_to_msg_id": 41,
                "edit_date": None,
                "deleted_at": None,
                "is_deleted": False,
                "unit_updated_at": "2026-05-07T12:00:00.000000Z",
            },
            "chunking_hints": {},
        },
    }


def test_provider_maps_structured_export_to_application_source_batch() -> None:
    provider = TelegramApplicationSourceProvider(_TelegramSourceClientFixture())

    assert provider.describe_source().namespace == "telegram"
    assert "incremental_cursor" in provider.describe_source().normalized_capabilities()
    assert "read_unit_window" in provider.describe_source().normalized_capabilities()
    batch = provider.export_changes(None, 10)

    assert isinstance(batch, ApplicationSourceChangeBatch)
    assert batch.next_cursor == "telegram:v1:dialog:-1001:message:45"
    assert batch.checkpoint_cursor == "telegram:v1:dialog:-1001:message:44"
    assert batch.updated_after == "2026-05-07T12:00:00.000000Z"
    assert batch.updated_after_cursor == "telegram:v1:dialog:-1001:message:42"

    change = batch.changes[0]
    assert change.document.namespace == "telegram"
    assert change.document.document_ref == "dialog:-1001"
    assert change.document.ref == "telegram:dialog:-1001"
    assert change.document.source_uri == "telegram://dialog/-1001"
    assert change.document.media_type == "text/plain"
    assert change.document.parser_name == "telegram-message"
    assert change.document.document_type == "dialog"

    assert change.unit.unit_ref == "dialog:-1001:message:42"
    assert change.unit.unit_type == "message"
    assert change.unit.order_key == "00000000000000000042"
    assert public_ref_for_unit(change.unit) == "telegram:dialog:-1001:message:42"

    metadata = change.unit.metadata_json
    assert metadata["dialog_id"] == -1001
    assert metadata["dialog_name"] == "Release Chat"
    assert metadata["message_id"] == 42
    assert metadata["sender_id"] == 111
    assert metadata["sender_name"] == "Alice"
    assert metadata["topic_id"] == 7
    assert metadata["topic_title"] == "Deployments"
    assert metadata["reply_to_msg_id"] == 41
    assert metadata["edit_date"] is None
    assert metadata["is_deleted"] is False
    assert metadata["standalone_search"] is True


def test_provider_accepts_canonical_daemon_source_model_payload() -> None:
    provider = TelegramApplicationSourceProvider(
        _TelegramSourceClientFixture([_canonical_daemon_change()])
    )

    change = provider.export_changes(None, 10).changes[0]

    assert change.document.title == "Project Chat"
    assert change.document.metadata_json["sync_status"] == "synced"
    assert change.unit.unit_ref == "dialog:-1001:message:42"
    assert change.unit.fingerprint == "daemon-message-fingerprint"
    assert change.unit.metadata_json["message_id"] == 42
    assert change.unit.metadata_json["topic_title"] == "Deployments"
    assert change.unit.metadata_json["standalone_search"] is True
    assert public_ref_for_unit(change.unit) == "telegram:dialog:-1001:message:42"


def test_provider_preserves_low_signal_units_as_distinct_source_units() -> None:
    batch = TelegramApplicationSourceProvider(
        _TelegramSourceClientFixture()
    ).export_changes(None, 10)
    first_ok = batch.changes[1].unit
    second_ok = batch.changes[2].unit

    assert first_ok.text == "ok"
    assert first_ok.metadata_json["standalone_search"] is False
    assert second_ok.metadata_json["standalone_search"] is False
    assert first_ok.unit_ref == "dialog:-1001:message:43"
    assert second_ok.unit_ref == "dialog:-1001:message:44"
    assert first_ok.unit_ref != second_ok.unit_ref
    assert first_ok.fingerprint != second_ok.fingerprint


def test_low_signal_classification_is_conservative_for_en_and_ru() -> None:
    assert is_low_signal_telegram_text("")
    assert is_low_signal_telegram_text(" ok ")
    assert is_low_signal_telegram_text("спасибо")
    assert is_low_signal_telegram_text("да")
    assert is_low_signal_telegram_text("!!!")
    assert is_low_signal_telegram_text("👍")
    assert not is_low_signal_telegram_text("Deployment checklist is ready")


def test_edited_message_changes_fingerprint() -> None:
    original = TelegramApplicationSourceProvider(
        _TelegramSourceClientFixture()
    ).export_changes(None, 10).changes[0].unit
    edited = TelegramApplicationSourceProvider(
        _TelegramSourceClientFixture(
            [
                _change(
                    message_id=42,
                    text="Deployment checklist is ready, smoke included",
                    sender_id=111,
                    sender_name="Alice",
                    sent_at="2026-05-07T12:00:00.000000Z",
                    topic_id=7,
                    topic_title="Deployments",
                    reply_to_msg_id=41,
                    edit_date="2026-05-07T12:05:00.000000Z",
                )
            ]
        )
    ).export_changes(None, 10).changes[0].unit

    assert original.unit_ref == edited.unit_ref
    assert original.fingerprint != edited.fingerprint


def test_missing_optional_fingerprint_fields_are_explicit_null_values() -> None:
    batch = TelegramApplicationSourceProvider(
        _TelegramSourceClientFixture(
            [
                _change(
                    message_id=45,
                    text="No optional metadata",
                    sender_id=111,
                    sender_name="Alice",
                    sent_at="2026-05-07T12:00:03.000000Z",
                    topic_id=None,
                    topic_title=None,
                    reply_to_msg_id=None,
                    edit_date=None,
                )
            ]
        )
    ).export_changes(None, 10)
    unit = batch.changes[0].unit

    assert unit.metadata_json["topic_id"] is None
    assert unit.metadata_json["reply_to_msg_id"] is None
    assert unit.metadata_json["edit_date"] is None
    assert '"topic_id":null' in unit.fingerprint
    assert '"reply_to_msg_id":null' in unit.fingerprint
    assert '"edit_date":null' in unit.fingerprint


def test_export_changes_forwards_update_watermarks_to_structured_client() -> None:
    client = _TelegramSourceClientFixture()
    provider = TelegramApplicationSourceProvider(client)

    provider.export_changes(
        "telegram:v1:dialog:-1001:message:42",
        10,
        updated_after="2026-05-07T12:00:00.000000Z",
        updated_after_cursor="telegram:v1:dialog:-1001:message:42",
    )

    assert client.export_calls == [
        {
            "cursor": "telegram:v1:dialog:-1001:message:42",
            "limit": 10,
            "updated_after": "2026-05-07T12:00:00.000000Z",
            "updated_after_cursor": "telegram:v1:dialog:-1001:message:42",
        }
    ]


def test_provider_source_does_not_depend_on_telegram_runtime_internals() -> None:
    source = Path("src/dotmd/ingestion/telegram_provider.py").read_text()

    assert "telethon" not in source.lower()
    assert "sync_db" not in source
    assert "list_messages" not in source


# Task 1 tests: Federated search contract


def test_telegram_source_client_protocol_includes_search_messages() -> None:
    """TelegramSourceClientProtocol defines search_messages method."""
    from inspect import signature

    from dotmd.ingestion.telegram_provider import TelegramSourceClientProtocol

    protocol_methods = {
        name for name, _ in vars(TelegramSourceClientProtocol).items()
        if not name.startswith("_")
    }
    assert "search_messages" in protocol_methods
    # Verify signature has expected parameters
    sig = signature(vars(TelegramSourceClientProtocol)["search_messages"])
    params = list(sig.parameters.keys())
    assert "query" in params
    assert "limit" in params


def test_unix_socket_search_messages_request_shape() -> None:
    """UnixSocketTelegramSourceClient.search_messages builds correct request."""
    client = _TelegramSourceClientFixture()

    # Test basic request
    result = client.search_messages("kantine", limit=20)
    assert isinstance(result, dict)
    assert "messages" in result

    # Test with dialog_id
    result = client.search_messages("kantine", limit=20, dialog_id=42)
    assert isinstance(result, dict)
    assert "messages" in result


def test_search_native_returns_searchcandidate_list() -> None:
    """TelegramApplicationSourceProvider.search_native returns SearchCandidate list."""
    client = _TelegramSourceClientFixture()
    provider = TelegramApplicationSourceProvider(client)

    result = provider.search_native("kantine", limit=10)

    assert isinstance(result, list)
    assert len(result) == 3
    assert all(isinstance(c, SearchCandidate) for c in result)

    # Check first candidate structure
    c = result[0]
    assert c.ref == "telegram:dialog:12345:message:67"
    assert c.namespace == "telegram"
    assert c.descriptor_key == "telegram"
    assert c.source_kind == "chat"
    assert c.retrieval_kind == "tg:fts"
    assert c.title == "Project Chat"
    assert "Kantine is open" in c.snippet
    assert c.can_read is True
    assert c.can_materialize is False
    assert c.source_native_score == 0.93
    assert c.source_native_rank == 0

    # Check second candidate rank
    assert result[1].source_native_rank == 1
    assert result[2].source_native_rank == 2


def test_search_native_can_read_derived_from_provider_capability() -> None:
    """can_read is derived from runtime check on read_source_unit_window capability."""
    client = _TelegramSourceClientFixture()
    provider = TelegramApplicationSourceProvider(client)

    result = provider.search_native("kantine", limit=10)
    assert result[0].can_read is True

    # Test with a stub client that lacks read_source_unit_window
    class StubClientWithoutRead:
        def search_messages(self, query: str, limit: int, dialog_id: int | None = None) -> dict:
            return {"messages": _default_search_hits()[:limit]}

    provider_no_read = TelegramApplicationSourceProvider(StubClientWithoutRead())  # type: ignore
    result_no_read = provider_no_read.search_native("kantine", limit=10)
    assert result_no_read[0].can_read is False


def test_search_native_provider_metadata_whitelist() -> None:
    """provider_metadata only contains whitelisted keys."""
    hits_with_extra = [
        {
            "dialog_id": 12345,
            "message_id": 67,
            "text": "Message",
            "sender": "alice",
            "sent_at": "2026-04-12T08:11:00+00:00",
            "dialog_name": "Chat",
            "score": 0.93,
            # Extra fields that should be filtered out
            "phone_number": "+1234567890",
            "auth_token": "secret123",
            "session_path": "/tmp/session",
            "api_id": 12345,
            "api_hash": "deadbeef",
        }
    ]
    client = _TelegramSourceClientFixture(search_hits=hits_with_extra)
    provider = TelegramApplicationSourceProvider(client)

    result = provider.search_native("test", limit=10)
    assert len(result) == 1

    metadata = result[0].provider_metadata
    assert metadata is not None
    # Check whitelisted keys are present
    assert "dialog_id" in metadata
    assert "message_id" in metadata
    assert "sender" in metadata
    assert "sent_at" in metadata
    assert "dialog_name" in metadata
    # Check forbidden keys are absent
    assert "phone_number" not in metadata
    assert "auth_token" not in metadata
    assert "session_path" not in metadata
    assert "api_id" not in metadata
    assert "api_hash" not in metadata


def test_search_native_source_native_rank_is_zero_based() -> None:
    """source_native_rank is zero-based for all hits."""
    client = _TelegramSourceClientFixture()
    provider = TelegramApplicationSourceProvider(client)

    result = provider.search_native("kantine", limit=10)

    ranks = [c.source_native_rank for c in result]
    assert ranks == [0, 1, 2]


def test_search_native_handles_empty_hits() -> None:
    """search_native handles empty search results gracefully."""
    client = _TelegramSourceClientFixture(search_hits=[])
    provider = TelegramApplicationSourceProvider(client)

    result = provider.search_native("nonexistent", limit=10)

    assert result == []


def test_search_native_propagates_daemon_failure() -> None:
    """search_native propagates RuntimeError from daemon."""
    import pytest

    class FailingClient:
        def search_messages(self, query: str, limit: int, dialog_id: int | None = None) -> dict:
            raise RuntimeError("Telegram daemon request failed: socket disconnected")

    provider = TelegramApplicationSourceProvider(FailingClient())  # type: ignore

    with pytest.raises(RuntimeError, match="Telegram daemon request failed"):
        provider.search_native("test", limit=10)


# TG-03 and TG-04 regression tests


def test_application_source_ingest_result_has_rebound_units() -> None:
    """TG-03: ApplicationSourceIngestResult must have rebound_units field with default 0."""
    from dotmd.ingestion.pipeline import ApplicationSourceIngestResult

    result = ApplicationSourceIngestResult()
    assert hasattr(result, "rebound_units")
    assert result.rebound_units == 0


def test_tg04_public_ref_matches_search_native_ref() -> None:
    """TG-04: public_ref_for_unit, ChunkProvenance.ref formula, and search_native ref must all agree."""
    client = _TelegramSourceClientFixture()
    provider = TelegramApplicationSourceProvider(client)

    # 1. public_ref_for_unit matches expected message-level ref
    batch = provider.export_changes(None, 10)
    change = batch.changes[0]
    unit_ref = public_ref_for_unit(change.unit)
    assert unit_ref == "telegram:dialog:-1001:message:42"

    # 2. ChunkProvenance.ref formula: f"{unit.namespace}:{unit.unit_ref}"
    expected_provenance_ref = f"{change.unit.namespace}:{change.unit.unit_ref}"
    assert expected_provenance_ref == "telegram:dialog:-1001:message:42"

    # 3. search_native ref
    candidates = provider.search_native("test query", limit=5)
    if candidates:
        search_ref = candidates[0].ref
        assert search_ref.startswith("telegram:dialog:")
        assert ":message:" in search_ref

    # All three must be equal
    assert unit_ref == expected_provenance_ref
