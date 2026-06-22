"""GAP-02 (T-34-12) and GAP-03 (T-34-13): Federated Telegram read/drill routing.

GAP-02: read(ref) for a federated-only Telegram ref routes through provider
        read_unit_window, never hits local store, never inserts chunks.

GAP-03: When daemon socket is unreachable, read(ref) raises RuntimeError with
        provider-attributed message containing "telegram".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from dotmd.core.models import SourceUnitWindow
from tests.conftest import make_surreal_service


def _telegram_unit_dict(message_id: int, text: str) -> dict[str, Any]:
    return {
        "dialog_id": 42,
        "dialog_name": "Project Chat",
        "message_id": message_id,
        "text": text,
        "sent_at": "2026-04-12T08:11:00+00:00",
        "sender_id": 111,
        "sender_name": "alice",
        "topic_id": None,
        "topic_title": None,
        "reply_to_msg_id": None,
        "edit_date": None,
        "is_deleted": False,
        "unit_updated_at": "2026-04-12T08:11:00+00:00",
        "unit_ref": f"dialog:42:message:{message_id}",
    }


def _source_unit(message_id: int, text: str):
    from datetime import UTC, datetime

    from dotmd.core.models import SourceUnit

    return SourceUnit(
        namespace="telegram",
        document_ref="dialog:42",
        unit_ref=f"dialog:42:message:{message_id}",
        unit_type="message",
        text=text,
        order_key=f"{message_id:020d}",
        fingerprint=f"fp-{message_id}",
        updated_at=datetime(2026, 4, 12, 8, 11, 0, tzinfo=UTC),
        metadata_json=_telegram_unit_dict(message_id, text),
    )


def _get_service(tmp_path: Path):  # type: ignore[no-untyped-def]
    return make_surreal_service(
        tmp_path,
        data_dir=tmp_path,
        indexing={"paths": [str(tmp_path)]},
        embedding={"url": "http://localhost:8088"},
        telegram_daemon_socket=None,
    )


def test_federated_only_message_round_trip(tmp_path: Path) -> None:
    """T-34-12: read(ref) for a federated-only Telegram ref routes through provider,
    never raises 'no chunks', and does NOT insert rows into the local chunk store.

    The local store has NO document for this ref — purely federated.
    """
    service = _get_service(tmp_path)

    # Local store: no document for this ref
    metadata = MagicMock()
    metadata.get_source_document.return_value = None
    metadata.is_resource_binding_active.return_value = False
    service._pipeline._metadata_store = metadata

    # Provider returns a window with one unit
    provider = MagicMock()
    window = SourceUnitWindow(
        namespace="telegram",
        document_ref="dialog:42",
        unit_ref="dialog:42:message:99",
        units=[_source_unit(99, "Kantine is open on Monday")],
        metadata_json={"dialog_id": 42},
    )
    provider.read_unit_window.return_value = window
    service._telegram_provider = provider

    # Count chunk rows before
    chunk_count_before = service._pipeline._conn.execute(
        f"SELECT COUNT(*) FROM chunks_{service._settings.indexing.chunk_strategy}"
    ).fetchone()[0]

    # Act: read a federated-only Telegram ref — must NOT raise
    payload = cast(
        dict[str, Any],
        service.read("telegram:dialog:42:message:99"),
    )

    # Provider was called
    provider.read_unit_window.assert_called_once()
    call_args = provider.read_unit_window.call_args
    assert (
        call_args[0][0] == "dialog:42:message:99"
        or call_args[1].get("unit_ref") == "dialog:42:message:99"
    )

    # Payload contains the provider-sourced text
    assert payload["ref"] == "telegram:dialog:42:message:99"
    assert payload["frontmatter"] == {}
    units = payload.get("units", [])
    assert any("Kantine" in u.get("text", "") for u in units), (
        f"Expected 'Kantine' in units text, got: {units}"
    )

    # No chunk rows were inserted
    chunk_count_after = service._pipeline._conn.execute(
        f"SELECT COUNT(*) FROM chunks_{service._settings.indexing.chunk_strategy}"
    ).fetchone()[0]
    assert chunk_count_after == chunk_count_before, (
        f"Federated read inserted {chunk_count_after - chunk_count_before} "
        "chunk rows — materialization must not happen."
    )


def test_federated_read_provider_down_attribution(tmp_path: Path) -> None:
    """T-34-13: When daemon socket is unreachable, read(ref) raises RuntimeError
    whose message contains 'telegram' (provider-attributed error shape, D-15).
    """
    service = _get_service(tmp_path)

    # Local store: no document for this ref (federated-only path)
    metadata = MagicMock()
    metadata.get_source_document.return_value = None
    metadata.is_resource_binding_active.return_value = False
    service._pipeline._metadata_store = metadata

    # Provider raises to simulate daemon down
    provider = MagicMock()
    provider.read_unit_window.side_effect = RuntimeError(
        "Telegram daemon request failed: socket disconnected"
    )
    service._telegram_provider = provider

    with pytest.raises(RuntimeError) as exc_info:
        service.read("telegram:dialog:42:message:99")

    error_msg = str(exc_info.value).lower()
    assert "telegram" in error_msg, (
        f"RuntimeError must contain 'telegram' for provider attribution (D-15). "
        f"Got: {str(exc_info.value)!r}"
    )
