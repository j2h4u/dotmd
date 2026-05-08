"""Deterministic application source fixtures for provider-contract tests."""

from __future__ import annotations

from datetime import datetime

from dotmd.core.models import (
    ApplicationSourceChange,
    ApplicationSourceChangeBatch,
    ApplicationSourceDescription,
    SourceDocument,
    SourceUnit,
    SourceUnitWindow,
)
from dotmd.ingestion.source_provider import ApplicationSourceProviderProtocol


def make_implicit_root_unit(
    document: SourceDocument,
    text: str,
    fingerprint: str,
    updated_at: datetime,
    *,
    metadata_json: dict | None = None,
    chunking_hints: dict | None = None,
) -> SourceUnit:
    """Create the single implicit unit used by document-shaped sources."""
    return SourceUnit(
        namespace=document.namespace,
        document_ref=document.document_ref,
        unit_ref=f"{document.document_ref}:root",
        unit_type="root",
        text=text,
        order_key="0000000000",
        fingerprint=fingerprint,
        updated_at=updated_at,
        metadata_json=metadata_json or {},
        chunking_hints=chunking_hints or {},
    )


class FixtureApplicationSourceProvider(ApplicationSourceProviderProtocol):
    """In-memory provider with opaque offset cursors."""

    def __init__(
        self,
        description: ApplicationSourceDescription,
        changes: list[ApplicationSourceChange],
    ) -> None:
        self._description = description
        self._changes = changes
        self._units = {change.unit.unit_ref: change.unit for change in changes}

    def describe_source(self) -> ApplicationSourceDescription:
        return self._description

    def export_changes(
        self,
        cursor: str | None,
        limit: int,
        updated_after: str | None = None,
        updated_after_cursor: str | None = None,
    ) -> ApplicationSourceChangeBatch:
        _ = (updated_after, updated_after_cursor)
        if limit <= 0:
            raise ValueError("limit must be positive")

        offset = self._parse_cursor(cursor)
        end = min(offset + limit, len(self._changes))
        changes = self._changes[offset:end]
        if not changes:
            return ApplicationSourceChangeBatch(changes=[], next_cursor=None)

        next_cursor = f"offset:{end}" if end < len(self._changes) else None
        return ApplicationSourceChangeBatch(
            changes=changes,
            next_cursor=next_cursor,
            checkpoint_cursor=f"offset:{end}",
        )

    def read_unit_window(
        self,
        unit_ref: str,
        before: int,
        after: int,
    ) -> SourceUnitWindow:
        target = self._units.get(unit_ref)
        if target is None:
            raise ValueError(f"Unknown source unit: {unit_ref}")

        document_units = sorted(
            (
                unit
                for unit in self._units.values()
                if unit.document_ref == target.document_ref
            ),
            key=lambda unit: unit.order_key,
        )
        target_index = document_units.index(target)
        if target.unit_type == "root":
            units = [target]
        else:
            start = max(0, target_index - before)
            stop = min(len(document_units), target_index + after + 1)
            units = document_units[start:stop]

        return SourceUnitWindow(
            namespace=target.namespace,
            document_ref=target.document_ref,
            unit_ref=unit_ref,
            units=units,
        )

    def _parse_cursor(self, cursor: str | None) -> int:
        if cursor is None:
            return 0
        prefix, separator, value = cursor.partition(":")
        if prefix != "offset" or separator != ":":
            raise ValueError(f"Invalid fixture cursor: {cursor}")
        try:
            offset = int(value)
        except ValueError as exc:
            raise ValueError(f"Invalid fixture cursor: {cursor}") from exc
        if offset < 0:
            raise ValueError(f"Invalid fixture cursor: {cursor}")
        return offset
