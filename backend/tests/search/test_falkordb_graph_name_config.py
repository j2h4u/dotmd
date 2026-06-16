from __future__ import annotations

from pathlib import Path

import pytest


def _settings(tmp_path: Path):  # type: ignore[no-untyped-def]
    from dotmd.core.config import Settings

    return Settings(
        index_dir=tmp_path,
        embedding_url="http://localhost:8088",
        telegram_daemon_socket=None,
    )


@pytest.fixture
def _mock_graph_store_factory():  # type: ignore[no-untyped-def]
    yield


def test_create_graph_store_defaults_to_dotmd_graph_name(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from dotmd.core.config import DEFAULT_FALKORDB_GRAPH_NAME
    from dotmd.ingestion.pipeline import _create_graph_store

    selected_graph_names: list[str] = []

    class _FakeGraph:
        def query(self, _query: str) -> None:
            return None

    class _FakeFalkorDB:
        def __init__(self, *, host: str, port: int) -> None:
            self.host = host
            self.port = port

        def select_graph(self, graph_name: str) -> _FakeGraph:
            selected_graph_names.append(graph_name)
            return _FakeGraph()

    monkeypatch.setattr("dotmd.storage.falkordb_graph.FalkorDB", _FakeFalkorDB)

    settings = _settings(tmp_path)

    assert settings.falkordb_graph_name == DEFAULT_FALKORDB_GRAPH_NAME

    graph_store = _create_graph_store(settings)

    assert graph_store._graph_name == DEFAULT_FALKORDB_GRAPH_NAME
    assert selected_graph_names == [DEFAULT_FALKORDB_GRAPH_NAME]


def test_create_graph_store_honors_overridden_graph_name(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from dotmd.ingestion.pipeline import _create_graph_store

    selected_graph_names: list[str] = []

    class _FakeGraph:
        def query(self, _query: str) -> None:
            return None

    class _FakeFalkorDB:
        def __init__(self, *, host: str, port: int) -> None:
            self.host = host
            self.port = port

        def select_graph(self, graph_name: str) -> _FakeGraph:
            selected_graph_names.append(graph_name)
            return _FakeGraph()

    monkeypatch.setattr("dotmd.storage.falkordb_graph.FalkorDB", _FakeFalkorDB)

    overridden_settings = _settings(tmp_path).model_copy(
        update={"falkordb_graph_name": "dotmd_shadow_baseline"}
    )

    graph_store = _create_graph_store(overridden_settings)

    assert graph_store._graph_name == "dotmd_shadow_baseline"
    assert selected_graph_names == ["dotmd_shadow_baseline"]
