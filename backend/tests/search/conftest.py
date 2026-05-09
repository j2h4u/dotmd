"""Shared fixtures for federated search tests."""

from __future__ import annotations

from typing import Any, Protocol

import pytest

from dotmd.core.models import (
    SearchCandidate,
    SourceCapability,
    SourceDescriptor,
    SourceDisplayMetadata,
    SourceAuthSchema,
    SourceConfigSchema,
    SourceCursorSchema,
)
from dotmd.ingestion.source_lifecycle import (
    SourceRuntimeBundle,
    SourceCursorStoreProtocol,
    FilesystemSourceConfig,
    SourceAccess,
)


class StubFederatedProvider:
    """Minimal stub federated provider for testing fan-out."""

    def __init__(
        self,
        candidates: list[SearchCandidate] | None = None,
        sleep_seconds: float = 0.0,
        raises: Exception | None = None,
    ) -> None:
        self.candidates = candidates or []
        self.sleep_seconds = sleep_seconds
        self.raises = raises

    def search_native(self, query: str, limit: int) -> list[SearchCandidate]:
        """Sync method that optionally sleeps or raises."""
        import time

        if self.sleep_seconds > 0:
            time.sleep(self.sleep_seconds)
        if self.raises is not None:
            raise self.raises
        return self.candidates[:limit]


@pytest.fixture
def slow_federated_provider():  # type: ignore[no-untyped-def]
    """Factory for a provider that sleeps before returning."""
    def _make(seconds: float) -> StubFederatedProvider:
        return StubFederatedProvider(
            candidates=[
                SearchCandidate(
                    ref=f"stub:result:{i}",
                    namespace="stub",
                    descriptor_key="stub",
                    source_kind="test",
                    retrieval_kind="stub:search",
                    snippet=f"result {i}",
                    fused_score=1.0,
                    can_read=False,
                )
                for i in range(2)
            ],
            sleep_seconds=seconds,
        )
    return _make


@pytest.fixture
def failing_federated_provider():  # type: ignore[no-untyped-def]
    """Factory for a provider that raises."""
    def _make(exc: Exception) -> StubFederatedProvider:
        return StubFederatedProvider(raises=exc)
    return _make


def make_federated_bundle(
    name: str = "stub",
    capabilities: list[SourceCapability] | None = None,
    provider: StubFederatedProvider | None = None,
) -> SourceRuntimeBundle:
    """Create a fake SourceRuntimeBundle with federated search support.

    Args:
        name: namespace name (default "stub")
        capabilities: list of source capabilities (defaults to [FEDERATED_SEARCH])
        provider: provider instance (defaults to StubFederatedProvider with 2 candidates)
    """
    if capabilities is None:
        capabilities = [SourceCapability.FEDERATED_SEARCH]
    if provider is None:
        provider = StubFederatedProvider(
            candidates=[
                SearchCandidate(
                    ref=f"{name}:result:{i}",
                    namespace=name,
                    descriptor_key=name,
                    source_kind="test",
                    retrieval_kind=f"{name}:fts",
                    snippet=f"result {i}",
                    fused_score=1.0,
                    can_read=False,
                )
                for i in range(2)
            ]
        )

    # Create a minimal descriptor with the requested capabilities
    descriptor = SourceDescriptor(
        namespace=name,
        source_kind="test",
        display=SourceDisplayMetadata(
            display_name=f"{name.capitalize()} Test",
            description="Stub federated source for testing",
        ),
        config_schema=SourceConfigSchema(name=f"{name}_config"),
        auth_schema=SourceAuthSchema(auth_kind="none"),
        cursor_schema=SourceCursorSchema(cursor_kind="none"),
        capabilities=capabilities,
    )

    # Create a minimal cursor store
    class StubCursorStore(SourceCursorStoreProtocol):
        def get_checkpoint(self, namespace: str) -> dict[str, object] | None:  # type: ignore[no-untyped-def]
            return None

        def commit_checkpoint(self, namespace: str, checkpoint_cursor: str | None, *, conn: Any, metadata_json: dict[str, object] | None = None) -> None:  # type: ignore[no-untyped-def]
            pass

        def record_error(self, namespace: str, error: str, *, conn: Any | None = None) -> None:  # type: ignore[no-untyped-def]
            pass

    # Create a minimal bundle
    bundle = SourceRuntimeBundle(
        descriptor=descriptor,
        config=FilesystemSourceConfig(paths=["/stub"]),
        access=SourceAccess(kind="none"),
        cursor_store=StubCursorStore(),  # type: ignore[arg-type]
        provider=provider,  # type: ignore[arg-type]
    )
    return bundle


def make_misconfigured_federated_factory() -> type:
    """Factory that raises during lifecycle build for init-failure tests."""
    class MisconfiguredFactory:
        def build_if_configured(self, namespace: str) -> SourceRuntimeBundle | None:
            raise RuntimeError("missing config")
    return MisconfiguredFactory
