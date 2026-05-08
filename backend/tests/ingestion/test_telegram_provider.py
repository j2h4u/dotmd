"""Tests for Telegram application-source provider mapping."""

from __future__ import annotations

from pathlib import Path

from dotmd.core.models import ApplicationSourceChangeBatch
from dotmd.ingestion.telegram_provider import (
    TelegramApplicationSourceProvider,
    is_low_signal_telegram_text,
    public_ref_for_unit,
)


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
