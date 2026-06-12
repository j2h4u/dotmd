"""Tests for force parameter threading through DotMDService."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

if TYPE_CHECKING:
    from dotmd.api.service import DotMDService


class TestServiceForceParameter:
    """Verify DotMDService.index passes force to pipeline."""

    def _make_service(self, tmp_path: Path) -> DotMDService:
        """Create a DotMDService with mocked-out heavy deps."""
        from dotmd.api.service import DotMDService
        from dotmd.core.config import Settings

        settings = Settings(index_dir=tmp_path / "idx", embedding_url="http://test:8088")
        service = DotMDService(settings=settings)
        # Replace the pipeline's index method with a mock
        service._pipeline.index = cast(Any, MagicMock(return_value=MagicMock()))
        return service

    def test_force_false_by_default(self, tmp_path: Path) -> None:
        """service.index(dir) should pass force=False to pipeline."""
        service = self._make_service(tmp_path)
        service.index(tmp_path)

        cast(MagicMock, service._pipeline.index).assert_called_once_with(tmp_path, force=False)

    def test_force_true_passed_through(self, tmp_path: Path) -> None:
        """service.index(dir, force=True) should pass force=True to pipeline."""
        service = self._make_service(tmp_path)
        service.index(tmp_path, force=True)

        cast(MagicMock, service._pipeline.index).assert_called_once_with(tmp_path, force=True)

    def test_force_false_explicit(self, tmp_path: Path) -> None:
        """service.index(dir, force=False) should pass force=False to pipeline."""
        service = self._make_service(tmp_path)
        service.index(tmp_path, force=False)

        cast(MagicMock, service._pipeline.index).assert_called_once_with(tmp_path, force=False)
