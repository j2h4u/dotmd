"""Application source provider protocol."""

from __future__ import annotations

from typing import Protocol

from dotmd.core.models import (
    ApplicationSourceChangeBatch,
    ApplicationSourceDescription,
    SearchCandidate,
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
        updated_after: str | None = None,
        updated_after_cursor: str | None = None,
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


class FederatedSearchProviderProtocol(Protocol):
    """Protocol for federated search providers (Phase 34).

    Implemented by integrations (Telegram, Slack, etc.) to surface
    external search results into the local search response.

    The search_native method is synchronous and will be wrapped with
    asyncio.to_thread in the federated fan-out orchestrator to run in
    a thread pool without blocking the event loop.

    Errors are soft-skipped per D-12; they propagate to SourceStatus as
    error records but do not fail the overall search.
    """

    def search_native(
        self,
        query: str,
        limit: int,
    ) -> list[SearchCandidate]:
        """Search the external source and return ranked candidates.

        All candidates returned MUST have:
        - chunk_id=None (federated identifier)
        - namespace matching the source (e.g., "telegram", "slack")
        - descriptor_key identifying the source instance/account
        - can_read=True (federated sources are assumed readable) or False if read not supported

        Parameters
        ----------
        query:
            Natural-language search query.
        limit:
            Maximum number of results to return.

        Returns
        -------
        list[SearchCandidate]
            Ranked candidates from the source. Empty list if no results.
            Each candidate must have chunk_id=None and valid namespace.

        Raises
        ------
        Exception
            Any exception indicates provider failure. Per D-12, the error
            is caught and recorded in SourceStatus; the overall search
            continues. Errors are not re-raised.
        """
        ...
