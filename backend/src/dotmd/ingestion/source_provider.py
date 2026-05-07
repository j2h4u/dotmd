"""Application source provider protocol."""

from __future__ import annotations

from typing import Protocol

from dotmd.core.models import (
    ApplicationSourceChangeBatch,
    ApplicationSourceDescription,
    SourceUnitWindow,
)


class ApplicationSourceProviderProtocol(Protocol):
    """Minimal provider contract for non-filesystem application sources."""

    def describe_source(self) -> ApplicationSourceDescription:
        """Describe the source namespace and capabilities."""
        ...

    def export_changes(
        self,
        cursor: str | None,
        limit: int,
    ) -> ApplicationSourceChangeBatch:
        """Export active document/unit changes after an opaque cursor."""
        ...

    def read_unit_window(
        self,
        unit_ref: str,
        before: int,
        after: int,
    ) -> SourceUnitWindow:
        """Read neighboring units around a provider-owned unit reference."""
        ...
