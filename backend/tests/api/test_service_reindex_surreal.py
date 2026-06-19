"""Tests for Surreal-mode reindex routing in DotMDService."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


def test_service_reindex_all_skips_local_rebuilds_in_surreal_mode(
    tmp_path: Path, monkeypatch
) -> None:
    from dotmd.api.service import DotMDService
    from dotmd.core.config import Settings

    class FakeConnection:
        def close(self) -> None:
            pass

    class FakeWriter:
        def __init__(self) -> None:
            self.connection = FakeConnection()

    monkeypatch.setattr(
        "dotmd.ingestion.pipeline._create_surreal_direct_writer",
        lambda _settings: FakeWriter(),
    )
    monkeypatch.setattr(
        "dotmd.api.service.DotMDService._configure_surreal_search_backend",
        lambda self: None,
    )

    settings = Settings(
        index_dir=tmp_path / "index",
        embedding_url="http://test-tei:8088",
        search_backend="surreal",
        surreal_retrieval_url="http://surrealdb:8000",
        surreal_retrieval_database="dotmd",
        surreal_retrieval_embedding_dimension=3,
    )
    service = DotMDService(settings)

    service._pipeline.reindex_vectors = MagicMock(return_value=11)  # type: ignore[method-assign]
    service._pipeline.reindex_fts5 = MagicMock(return_value=22)  # type: ignore[method-assign]
    service._pipeline.reindex_graph = MagicMock(return_value=33)  # type: ignore[method-assign]

    try:
        assert service.reindex("all") == 0
        service._pipeline.reindex_vectors.assert_not_called()
        service._pipeline.reindex_fts5.assert_not_called()
        service._pipeline.reindex_graph.assert_not_called()
    finally:
        service.close()
