"""Tests for application source provider payloads and protocol."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from dotmd.core.models import (
    ApplicationSourceChange,
    ApplicationSourceChangeBatch,
    ApplicationSourceDescription,
    SourceDocument,
    SourceUnit,
    SourceUnitWindow,
)
from dotmd.ingestion.source_provider import ApplicationSourceProviderProtocol


NOW = datetime(2026, 5, 7, 12, 0, tzinfo=UTC)


def _telegram_document() -> SourceDocument:
    return SourceDocument(
        namespace="telegram",
        document_ref="dialog:123",
        ref="telegram:dialog:123",
        source_uri="telegram://dialog/123",
        media_type="text/plain",
        parser_name="telegram-message",
        document_type="dialog",
        title="Telegram dialog 123",
        updated_at=NOW,
        content_fingerprint="doc-content",
        metadata_fingerprint="doc-meta",
        metadata_json={},
    )


def _telegram_unit(
    unit_ref: str = "dialog:123:message:456",
    *,
    order_key: str = "0000000456",
    text: str = "hello",
    fingerprint: str = "unit-fingerprint",
) -> SourceUnit:
    return SourceUnit(
        namespace="telegram",
        document_ref="dialog:123",
        unit_ref=unit_ref,
        unit_type="message",
        text=text,
        order_key=order_key,
        fingerprint=fingerprint,
        updated_at=NOW,
        metadata_json={},
        chunking_hints={},
    )


def test_source_unit_requires_updated_at() -> None:
    with pytest.raises(ValidationError):
        SourceUnit(
            namespace="telegram",
            document_ref="dialog:123",
            unit_ref="dialog:123:message:456",
            unit_type="message",
            text="hello",
            order_key="0000000456",
            fingerprint="unit-fingerprint",
            metadata_json={},
            chunking_hints={},
        )


def test_application_source_change_batch_carries_document_unit_and_cursors() -> None:
    batch = ApplicationSourceChangeBatch(
        changes=[
            ApplicationSourceChange(
                document=_telegram_document(),
                unit=_telegram_unit(),
            )
        ],
        next_cursor=None,
        checkpoint_cursor="cursor:456",
    )

    assert batch.changes[0].document.document_ref == "dialog:123"
    assert batch.changes[0].unit.unit_ref == "dialog:123:message:456"
    assert batch.changes[0].unit.unit_type == "message"
    assert batch.changes[0].unit.chunking_hints == {}
    assert batch.checkpoint_cursor == "cursor:456"


class _ProviderFixture:
    def describe_source(self) -> ApplicationSourceDescription:
        return ApplicationSourceDescription(
            namespace="telegram",
            source_kind="chat",
            display_name="Telegram",
            capabilities=["window"],
        )

    def export_changes(
        self,
        cursor: str | None,
        limit: int,
    ) -> ApplicationSourceChangeBatch:
        return ApplicationSourceChangeBatch(
            changes=[
                ApplicationSourceChange(
                    document=_telegram_document(),
                    unit=_telegram_unit(),
                )
            ],
            checkpoint_cursor="cursor:456",
        )

    def read_unit_window(
        self,
        unit_ref: str,
        before: int,
        after: int,
    ) -> SourceUnitWindow:
        return SourceUnitWindow(
            namespace="telegram",
            document_ref="dialog:123",
            unit_ref=unit_ref,
            units=[
                _telegram_unit(
                    "dialog:123:message:455",
                    order_key="0000000455",
                    text="previous",
                    fingerprint="unit-455",
                ),
                _telegram_unit(),
            ],
        )


def test_application_source_provider_protocol_shape() -> None:
    provider: ApplicationSourceProviderProtocol = _ProviderFixture()

    assert provider.describe_source().namespace == "telegram"
    assert provider.export_changes(None, 10).checkpoint_cursor == "cursor:456"
    window = provider.read_unit_window("dialog:123:message:456", before=1, after=0)
    assert isinstance(window, SourceUnitWindow)
    assert [unit.unit_ref for unit in window.units] == [
        "dialog:123:message:455",
        "dialog:123:message:456",
    ]
