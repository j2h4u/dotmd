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
from dotmd.storage.metadata import SQLiteMetadataStore

from .application_source_fixtures import (
    FixtureApplicationSourceProvider,
    make_implicit_root_unit,
)

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
    payload = {
        "namespace": "telegram",
        "document_ref": "dialog:123",
        "unit_ref": "dialog:123:message:456",
        "unit_type": "message",
        "text": "hello",
        "order_key": "0000000456",
        "fingerprint": "unit-fingerprint",
        "metadata_json": {},
        "chunking_hints": {},
    }

    with pytest.raises(ValidationError):
        SourceUnit(**payload)


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


def _telegram_change(message_id: int, text: str) -> ApplicationSourceChange:
    return ApplicationSourceChange(
        document=_telegram_document(),
        unit=_telegram_unit(
            f"dialog:123:message:{message_id}",
            order_key=f"{message_id:010d}",
            text=text,
            fingerprint=f"unit-{message_id}",
        ),
    )


def _fixture_provider() -> FixtureApplicationSourceProvider:
    return FixtureApplicationSourceProvider(
        ApplicationSourceDescription(
            namespace="telegram_fixture",
            source_kind="chat",
            display_name="Telegram fixture",
            capabilities=["read-window"],
        ),
        [
            _telegram_change(454, "before"),
            _telegram_change(455, "target"),
            _telegram_change(456, "after"),
        ],
    )


def test_fixture_provider_exports_offset_batches() -> None:
    provider = _fixture_provider()

    first = provider.export_changes(None, limit=2)
    second = provider.export_changes(first.checkpoint_cursor, limit=2)
    third = provider.export_changes(second.checkpoint_cursor, limit=2)

    assert provider.describe_source().namespace == "telegram_fixture"
    assert len(first.changes) == 2
    assert first.next_cursor == "offset:2"
    assert first.checkpoint_cursor == "offset:2"
    assert [change.unit.text for change in second.changes] == ["after"]
    assert second.checkpoint_cursor == "offset:3"
    assert third.changes == []


@pytest.mark.parametrize("cursor", ["bad", "offset:-1", "offset:not-an-int"])
def test_fixture_provider_rejects_invalid_cursors(cursor: str) -> None:
    with pytest.raises(ValueError, match="Invalid fixture cursor"):
        _fixture_provider().export_changes(cursor, limit=2)


def test_fixture_provider_rejects_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="limit must be positive"):
        _fixture_provider().export_changes(None, limit=0)


def test_fixture_provider_reads_neighboring_message_window() -> None:
    window = _fixture_provider().read_unit_window(
        "dialog:123:message:455",
        before=1,
        after=1,
    )

    assert [unit.unit_ref for unit in window.units] == [
        "dialog:123:message:454",
        "dialog:123:message:455",
        "dialog:123:message:456",
    ]


def test_fixture_provider_reads_implicit_root_fallback_window() -> None:
    document = SourceDocument(
        namespace="notion_fixture",
        document_ref="page:abc",
        ref="notion_fixture:page:abc",
        source_uri="notion://page/abc",
        media_type="text/markdown",
        parser_name="notion-page",
        document_type="page",
        title="Page ABC",
        updated_at=NOW,
        content_fingerprint="doc-content",
        metadata_fingerprint="doc-meta",
        metadata_json={},
    )
    provider = FixtureApplicationSourceProvider(
        ApplicationSourceDescription(
            namespace="notion_fixture",
            source_kind="document",
            display_name="Notion fixture",
        ),
        [
            ApplicationSourceChange(
                document=document,
                unit=make_implicit_root_unit(
                    document,
                    "page body",
                    "root-fingerprint",
                    NOW,
                ),
            )
        ],
    )

    window = provider.read_unit_window("page:abc:root", before=5, after=5)

    assert len(window.units) == 1
    assert window.units[0].unit_type == "root"


def test_fixture_provider_rejects_unknown_unit() -> None:
    with pytest.raises(ValueError, match="Unknown source unit"):
        _fixture_provider().read_unit_window("dialog:123:message:999", 1, 1)


def test_fixture_replay_classifies_unchanged_fingerprints(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteMetadataStore(db_path=tmp_path / "metadata.db")
    first_batch = _fixture_provider().export_changes(None, limit=10)
    conn = store._conn

    for change in first_batch.changes:
        assert store.upsert_source_unit_fingerprint(change.unit, conn=conn) is True
    conn.commit()

    replay_results = [
        store.upsert_source_unit_fingerprint(change.unit, conn=conn)
        for change in first_batch.changes
    ]

    assert replay_results == [False, False, False]
