from __future__ import annotations

from pathlib import Path


def _settings(tmp_path: Path):  # type: ignore[no-untyped-def]
    from dotmd.core.config import Settings

    return Settings(
        index_dir=tmp_path,
        embedding_url="http://localhost:8088",
        telegram_daemon_socket=None,
    )


def test_create_graph_store_defaults_to_dotmd_graph_name(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from dotmd.core.config import DEFAULT_FALKORDB_GRAPH_NAME
    from dotmd.ingestion.pipeline import _create_graph_store

    calls: list[dict[str, str]] = []

    class _FakeFalkorDBGraphStore:
        def __init__(self, *, url: str, graph_name: str) -> None:
            calls.append({"url": url, "graph_name": graph_name})

    monkeypatch.setattr(
        "dotmd.storage.falkordb_graph.FalkorDBGraphStore",
        _FakeFalkorDBGraphStore,
    )

    settings = _settings(tmp_path)

    assert settings.falkordb_graph_name == DEFAULT_FALKORDB_GRAPH_NAME

    _create_graph_store(settings)

    assert calls == [
        {
            "url": settings.falkordb_url,
            "graph_name": DEFAULT_FALKORDB_GRAPH_NAME,
        }
    ]


def test_create_graph_store_honors_overridden_graph_name(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from dotmd.ingestion.pipeline import _create_graph_store

    calls: list[dict[str, str]] = []

    class _FakeFalkorDBGraphStore:
        def __init__(self, *, url: str, graph_name: str) -> None:
            calls.append({"url": url, "graph_name": graph_name})

    monkeypatch.setattr(
        "dotmd.storage.falkordb_graph.FalkorDBGraphStore",
        _FakeFalkorDBGraphStore,
    )

    overridden_settings = _settings(tmp_path).model_copy(
        update={"falkordb_graph_name": "dotmd_shadow_baseline"}
    )

    _create_graph_store(overridden_settings)

    assert calls == [
        {
            "url": overridden_settings.falkordb_url,
            "graph_name": "dotmd_shadow_baseline",
        }
    ]
