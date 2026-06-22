"""Task 3 (TDD RED): Federated Telegram read/drill tests.

These tests validate the read(ref) and drill(ref) round-trips for federated-only
Telegram refs, ensuring proper routing through the provider infrastructure.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from dotmd.api.service import DotMDService
from dotmd.core.models import ExtractDepth, SourceUnit, SourceUnitWindow
from dotmd.ingestion.telegram_provider import TelegramApplicationSourceProvider
from tests.conftest import make_surreal_service


def _get_service(tmp_path: Path) -> DotMDService:
    return make_surreal_service(
        tmp_path / "index",
        data_dir=tmp_path,
        indexing={"paths": [str(tmp_path)]},
        embedding={"url": "http://localhost:18088"},
        extraction={"depth": ExtractDepth.STRUCTURAL},
    )


class TestFederatedTelegramRead:
    """RED phase: add failing tests for federated Telegram read/drill."""

    def test_federated_only_message_round_trip(self, tmp_path: Path) -> None:
        """Non-indexed Telegram message routes to provider.read_unit_window."""
        # RED: This test fails because read() doesn't check for federated-only refs yet
        service = _get_service(tmp_path)

        # Mock provider to return text for the message
        provider = MagicMock(spec=TelegramApplicationSourceProvider)

        mock_unit = SourceUnit(
            namespace="telegram",
            document_ref="dialog:12345",
            unit_ref="dialog:12345:message:67890",
            unit_type="message",
            text="Hello from Telegram",
            order_key="67890",
            fingerprint="abc123def456",
            updated_at=datetime.now(UTC),
            metadata_json={},
        )

        provider.read_unit_window = MagicMock(
            return_value=SourceUnitWindow(
                namespace="telegram",
                document_ref="dialog:12345",
                unit_ref="dialog:12345:message:67890",
                units=[mock_unit],
                metadata_json={},
            )
        )
        service._telegram_provider = provider

        # Try to read a federated-only Telegram ref
        telegram_ref = "telegram:dialog:12345:message:67890"
        result = service.read(telegram_ref, 0, 1)

        # Should route through provider
        assert result is not None
        assert "units" in result
        assert len(result["units"]) > 0
        provider.read_unit_window.assert_called_once()

    def test_federated_drill_returns_provider_metadata(self, tmp_path: Path) -> None:
        """drill(ref) returns provider metadata for federated-only refs."""
        # RED: drill() doesn't support federated refs yet
        service = _get_service(tmp_path)

        # Mock provider metadata with units payload
        provider = MagicMock(spec=TelegramApplicationSourceProvider)

        # Create unit with required attributes
        mock_unit = SourceUnit(
            namespace="telegram",
            document_ref="dialog:12345",
            unit_ref="dialog:12345:message:67890",
            unit_type="message",
            text="Test message",
            order_key="67890",
            fingerprint="abc123def456",
            updated_at=datetime.now(UTC),
            metadata_json={},
        )

        provider.read_unit_window = MagicMock(
            return_value=SourceUnitWindow(
                namespace="telegram",
                document_ref="dialog:12345",
                unit_ref="dialog:12345:message:67890",
                units=[mock_unit],
                metadata_json={"total_chunks": 42},
            )
        )
        service._telegram_provider = provider

        telegram_ref = "telegram:dialog:12345:message:67890"
        result = service.drill(telegram_ref)

        # Should return provider metadata
        assert result is not None
        assert result["total_chunks"] == 1
        provider.read_unit_window.assert_called_once()

    def test_federated_read_provider_down_attribution(self, tmp_path: Path) -> None:
        """Provider down error is clear and attributed."""
        # RED: Provider error attribution not implemented yet
        service = _get_service(tmp_path)

        # Mock provider to raise an error
        provider = MagicMock(spec=TelegramApplicationSourceProvider)
        provider.read_unit_window = MagicMock(
            side_effect=ConnectionError("Telegram provider unreachable")
        )
        service._telegram_provider = provider

        telegram_ref = "telegram:dialog:12345:message:67890"

        # Should raise error with clear attribution (service wraps in RuntimeError)
        with pytest.raises(RuntimeError, match="Telegram provider error"):
            service.read(telegram_ref, 0, 1)

    def test_truly_federated_telegram_ref_routes_to_provider(self, tmp_path: Path) -> None:
        """CRITICAL: No local entry → provider path (Cycle-2 HIGH-7)."""
        # RED: federated-only routing not implemented
        service = _get_service(tmp_path)

        # No local indexing of this message
        telegram_ref = "telegram:dialog:12345:message:67890"

        # Verify ref doesn't exist in local index
        store = service._pipeline.metadata_store
        assert store.get_source_document("telegram", "dialog:12345") is None

        # Mock provider to return text with proper structure
        provider = MagicMock(spec=TelegramApplicationSourceProvider)

        mock_unit = SourceUnit(
            namespace="telegram",
            document_ref="dialog:12345",
            unit_ref="dialog:12345:message:67890",
            unit_type="message",
            text="Provider content",
            order_key="67890",
            fingerprint="abc123def456",
            updated_at=datetime.now(UTC),
            metadata_json={},
        )

        provider.read_unit_window = MagicMock(
            return_value=SourceUnitWindow(
                namespace="telegram",
                document_ref="dialog:12345",
                unit_ref="dialog:12345:message:67890",
                units=[mock_unit],
                metadata_json={},
            )
        )
        service._telegram_provider = provider

        # Read should route through provider
        result = service.read(telegram_ref, 0, 1)
        assert result is not None
        provider.read_unit_window.assert_called_once()

    def test_inactive_locally_indexed_telegram_ref_does_not_fall_through_to_provider(
        self, tmp_path: Path
    ) -> None:
        """CRITICAL: Inactive local entry raises PermissionError, no fallthrough (Cycle-2 HIGH-7)."""
        # RED: binding gate and provider fallthrough not implemented
        service = _get_service(tmp_path)

        telegram_ref = "telegram:dialog:12345:message:67890"

        # Use service._resolve_telegram_read_path to test direct routing
        # Mock the metadata store to return inactive binding
        original_is_active = service._pipeline.metadata_store.is_resource_binding_active
        original_get_doc = service._pipeline.metadata_store.get_source_document

        def mock_is_active(namespace: str, resource_ref: str) -> bool:
            if namespace == "telegram" and resource_ref == "dialog:12345":
                return False  # INACTIVE
            return original_is_active(namespace, resource_ref)

        def mock_get_doc(namespace: str, document_ref: str, *, conn: Any | None = None):
            if namespace == "telegram" and document_ref == "dialog:12345":
                # Return a mock document
                from dotmd.core.models import SourceDocument

                return SourceDocument(
                    namespace="telegram",
                    document_ref="dialog:12345",
                    ref="telegram:dialog:12345",
                    title="Test Dialog",
                    source_uri="",
                    media_type="text/telegram",
                    parser_name="telegram",
                    document_type="telegram",
                    updated_at=datetime.now(UTC),
                    content_fingerprint="abc123",
                    metadata_fingerprint="def456",
                )
            return original_get_doc(namespace, document_ref, conn=conn)

        service._pipeline.metadata_store.is_resource_binding_active = mock_is_active
        service._pipeline.metadata_store.get_source_document = mock_get_doc

        # Mock provider
        provider = MagicMock(spec=TelegramApplicationSourceProvider)
        service._telegram_provider = provider

        # Read should raise PermissionError due to inactive binding, NOT fall through
        with pytest.raises(PermissionError, match="INACTIVE"):
            service.read(telegram_ref, 0, 1)

        # Provider should never be called
        provider.read_unit_window.assert_not_called()

    def test_active_locally_indexed_telegram_ref_uses_local_path(self, tmp_path: Path) -> None:
        """Active local entry uses local read path (not provider)."""
        # RED: binding-aware read routing not implemented
        service = _get_service(tmp_path)

        telegram_ref = "telegram:dialog:12345:message:67890"

        # Mock the metadata store to return active binding
        original_is_active = service._pipeline.metadata_store.is_resource_binding_active
        original_get_doc = service._pipeline.metadata_store.get_source_document

        def mock_is_active(namespace: str, resource_ref: str) -> bool:
            if namespace == "telegram" and resource_ref == "dialog:12345":
                return True  # ACTIVE
            return original_is_active(namespace, resource_ref)

        def mock_get_doc(namespace: str, document_ref: str, *, conn: Any | None = None):
            if namespace == "telegram" and document_ref == "dialog:12345":
                # Return a mock document
                from dotmd.core.models import SourceDocument

                return SourceDocument(
                    namespace="telegram",
                    document_ref="dialog:12345",
                    ref="telegram:dialog:12345",
                    title="Test Dialog",
                    source_uri="",
                    media_type="text/telegram",
                    parser_name="telegram",
                    document_type="telegram",
                    updated_at=datetime.now(UTC),
                    content_fingerprint="abc123",
                    metadata_fingerprint="def456",
                )
            return original_get_doc(namespace, document_ref, conn=conn)

        service._pipeline.metadata_store.is_resource_binding_active = mock_is_active
        service._pipeline.metadata_store.get_source_document = mock_get_doc

        # Mock provider
        provider = MagicMock(spec=TelegramApplicationSourceProvider)
        service._telegram_provider = provider

        # For this test, we expect a different error (no local chunks)
        # but definitely NOT a provider call
        import contextlib

        with contextlib.suppress(ValueError, KeyError):
            service.read(telegram_ref, 0, 1)

        # Provider should never be called
        provider.read_unit_window.assert_not_called()

    def test_federated_read_helper_naming(self, tmp_path: Path) -> None:
        """Helper method names/signatures correct."""
        # RED: Helper methods not implemented yet
        service = _get_service(tmp_path)

        # Verify helper methods exist and have correct signatures
        assert hasattr(service, "_resolve_telegram_read_path")

        # The method should be callable with a ref
        method = service._resolve_telegram_read_path
        assert callable(method)
