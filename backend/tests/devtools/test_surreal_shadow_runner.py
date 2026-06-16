"""Runner tests for the Phase 43 shadow-run evidence workflow."""

from __future__ import annotations

import importlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from dotmd.core.config import DEFAULT_FALKORDB_GRAPH_NAME, RUNTIME_INDEX_DIR, Settings
from dotmd.ingestion.pipeline import _model_to_table_suffix
from dotmd.search.surreal_eval import GoldenQueryCategory
from dotmd.search.surreal_shadow_metrics import (
    DEFAULT_SHADOW_MEMORY_GUARDRAILS,
    ShadowMemoryMetrics,
    ShadowMetricBundle,
)
from dotmd.storage.surreal_schema import DEFAULT_HNSW_EF


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def _settings(index_dir: Path) -> Settings:
    return Settings(
        index_dir=index_dir,
        embedding_url="http://localhost:8088",
        embedding_model="intfloat/multilingual-e5-large",
        telegram_daemon_socket=None,
    )


def _golden_row(query_id: str, category: GoldenQueryCategory) -> dict[str, object]:
    return {
        "id": query_id,
        "query": f"{category.value} query",
        "category": category.value,
        "primary_surface": "graph_entity"
        if category is GoldenQueryCategory.GRAPH_ENTITY
        else "vector",
        "languages": ["ru", "en"] if category is GoldenQueryCategory.MIXED_RU_EN else ["en"],
        "relevant": [{"ref": f"filesystem:/mnt/{query_id}.md", "contains": query_id}],
        "maybe": [],
        "expected_engines": ["graph", "semantic"]
        if category is GoldenQueryCategory.GRAPH_ENTITY
        else ["semantic"],
        "broad_query": False,
        "notes": "phase 43 fixture",
    }


def _eval_result_row(query_id: str, category: GoldenQueryCategory) -> dict[str, object]:
    return {
        "query_id": query_id,
        "query": f"{category.value} query",
        "category": category.value,
        "primary_surface": "graph_entity"
        if category is GoldenQueryCategory.GRAPH_ENTITY
        else "vector",
        "top_refs": [f"filesystem:/mnt/{query_id}.md"],
        "matched_engines": {f"filesystem:/mnt/{query_id}.md": ["semantic"]},
        "snippets_by_ref": {f"filesystem:/mnt/{query_id}.md": query_id},
        "read_evidence_by_ref": {f"filesystem:/mnt/{query_id}.md": query_id},
        "unreadable_refs": [],
        "latency_ms": 1.0,
    }


def _write_complete_golden_corpus(path: Path) -> Path:
    return _write_jsonl(
        path,
        [
            _golden_row(f"sq-{index:03d}", category)
            for index, category in enumerate(GoldenQueryCategory, start=1)
        ],
    )


def _expected_manifest_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "chunk_strategy": "heading_512_50",
        "embedding_model": "intfloat/multilingual-e5-large",
        "import_id": "phase43-shadow",
        "expected_chunk_count": 3,
        "expected_embedding_count": 3,
    }
    payload.update(overrides)
    return payload


def _create_rehearsal_index_db(
    root: Path,
    *,
    chunk_strategy: str = "heading_512_50",
    embedding_model: str = "intfloat/multilingual-e5-large",
    chunk_count: int = 3,
    embedding_count: int = 3,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / "index.db"
    conn = sqlite3.connect(db_path)
    strategy = chunk_strategy.lower()
    chunks_table = f"chunks_{strategy}"
    vec_table = f"vec_chunks_{strategy}{_model_to_table_suffix(embedding_model)}"
    meta_table = f"vec_meta{vec_table.removeprefix('vec_chunks')}"
    conn.execute(f"CREATE TABLE {chunks_table} (chunk_id TEXT PRIMARY KEY)")
    conn.execute(f"CREATE TABLE {meta_table} (rowid INTEGER PRIMARY KEY, chunk_id TEXT UNIQUE)")
    for index in range(chunk_count):
        conn.execute(f"INSERT INTO {chunks_table} (chunk_id) VALUES (?)", (f"chunk-{index}",))
    for index in range(embedding_count):
        conn.execute(f"INSERT INTO {meta_table} (rowid, chunk_id) VALUES (?, ?)", (index + 1, f"chunk-{index}"))
    conn.commit()
    conn.close()
    return db_path


def _shadow_metric_bundle() -> ShadowMetricBundle:
    baseline = ShadowMemoryMetrics(
        label="baseline",
        wall_clock_seconds=0.1,
        process_cpu_seconds=0.05,
        max_rss_bytes=100,
        current_python_heap_bytes=50,
        peak_python_heap_bytes=75,
    )
    candidate = ShadowMemoryMetrics(
        label="candidate",
        wall_clock_seconds=0.2,
        process_cpu_seconds=0.1,
        max_rss_bytes=120,
        current_python_heap_bytes=60,
        peak_python_heap_bytes=90,
    )
    return ShadowMetricBundle(
        passed=True,
        failure_category=None,
        recommendation_gate="pass",
        missing=(),
        record_counts={"chunks": 3, "embeddings": 3},
        hnsw_build_seconds=1.0,
        surrealkv_file_size_bytes=1024,
        query_latency_p50_ms=12.0,
        query_latency_p95_ms=18.0,
        memory={
            "baseline": baseline,
            "candidate": candidate,
        },
        guardrails=DEFAULT_SHADOW_MEMORY_GUARDRAILS,
        samples={"replay_window": {"count": 2}},
    )


def _artifact_payloads(tmp_path: Path) -> dict[str, Path]:
    return {
        "source_capture": tmp_path / "source-capture.json",
        "baseline_results": tmp_path / "baseline-results.jsonl",
        "candidate_results": tmp_path / "candidate-results.jsonl",
        "accepted_diffs": tmp_path / "accepted-diffs.jsonl",
        "shadow_diffs": tmp_path / "shadow-diffs.jsonl",
        "shadow_summary": tmp_path / "shadow-summary.md",
        "scale_metrics": tmp_path / "scale-metrics.json",
        "memory_metrics": tmp_path / "memory-metrics.json",
    }


def test_build_parser_exposes_phase_43_flags_and_folded_candidate_config() -> None:
    from devtools.surreal_shadow_runner import build_parser

    parser = build_parser()

    args = parser.parse_args(
        [
            "--artifacts-dir",
            "artifacts",
            "--golden-queries",
            "golden.jsonl",
            "--source-capture-manifest-json",
            "source-capture-expected.json",
            "--candidate-config-json",
            "candidate-config.json",
            "--baseline-rehearsal-path",
            "rehearsal",
            "--baseline-graph-name",
            "dotmd_shadow_baseline",
            "--production-graph-name",
            DEFAULT_FALKORDB_GRAPH_NAME,
            "--metrics-replay-queries",
            "replay.jsonl",
            "--target-url",
            "surrealkv:///tmp/shadow.db",
            "--target-namespace",
            "dotmd",
            "--target-database",
            "phase43_shadow",
        ]
    )

    assert args.baseline_graph_name == "dotmd_shadow_baseline"
    assert args.production_graph_name == DEFAULT_FALKORDB_GRAPH_NAME
    assert args.metrics_replay_queries == Path("replay.jsonl")
    assert args.candidate_config_json == Path("candidate-config.json")
    parser_help = parser.format_help()
    assert "--embedding-dimension" not in parser_help
    assert "--hnsw-ef" not in parser_help
    assert "--top-k" not in parser_help
    assert "--pool-size" not in parser_help


def test_ledger_sentinel_only_strips_and_yields_no_acceptance_rows(tmp_path: Path) -> None:
    from devtools.surreal_shadow_runner import load_shadow_acceptance_ledger

    ledger = _write_jsonl(
        tmp_path / "accepted-diffs.jsonl",
        [
            {
                "record_type": "phase43_ledger_metadata",
                "quality_corpus": "golden",
                "replay_window": {"count": 2},
                "guardrails": {"rss_ratio": 1.25},
            }
        ],
    )

    result = load_shadow_acceptance_ledger(ledger)

    assert result.acceptance_rows == ()
    assert result.metadata["record_type"] == "phase43_ledger_metadata"


def test_ledger_sentinel_plus_acceptance_passes_only_real_rows_to_loader(tmp_path: Path) -> None:
    from devtools.surreal_shadow_runner import load_shadow_acceptance_ledger

    ledger = _write_jsonl(
        tmp_path / "accepted-diffs.jsonl",
        [
            {
                "record_type": "phase43_ledger_metadata",
                "quality_corpus": "golden",
                "replay_window": {"count": 2},
                "guardrails": {"rss_ratio": 1.25},
            },
            {
                "query_id": "sq-001",
                "accepted_by": "operator",
                "accepted_reason": "same answer",
            },
        ],
    )

    result = load_shadow_acceptance_ledger(ledger)

    assert len(result.acceptance_rows) == 1
    assert result.acceptance_rows[0]["query_id"] == "sq-001"
    assert "record_type" not in result.acceptance_rows[0]


def test_ledger_acceptance_only_unchanged(tmp_path: Path) -> None:
    from devtools.surreal_shadow_runner import load_shadow_acceptance_ledger

    ledger = _write_jsonl(
        tmp_path / "accepted-diffs.jsonl",
        [
            {
                "query_id": "sq-001",
                "accepted_by": "operator",
                "accepted_reason": "same answer",
            }
        ],
    )

    result = load_shadow_acceptance_ledger(ledger)

    assert result.acceptance_rows == (
        {
            "query_id": "sq-001",
            "accepted_by": "operator",
            "accepted_reason": "same answer",
        },
    )
    assert result.metadata is None


def test_ledger_malformed_sentinel_fails_closed(tmp_path: Path) -> None:
    from devtools.surreal_shadow_runner import load_shadow_acceptance_ledger

    ledger = _write_jsonl(
        tmp_path / "accepted-diffs.jsonl",
        [
            {
                "quality_corpus": "golden",
                "replay_window": {"count": 2},
                "guardrails": {"rss_ratio": 1.25},
            }
        ],
    )

    with pytest.raises(ValueError, match="record_type"):
        load_shadow_acceptance_ledger(ledger)


def test_run_eval_receives_stripped_acceptance_path_not_raw_sentinel_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from devtools.surreal_shadow_runner import ShadowArtifactPaths, run_shadow_run

    golden = _write_complete_golden_corpus(tmp_path / "golden.jsonl")
    expected_manifest = _write_json(
        tmp_path / "source-capture-expected.json",
        _expected_manifest_payload(),
    )
    rehearsal_root = tmp_path / "rehearsal"
    _create_rehearsal_index_db(rehearsal_root)
    artifacts = _artifact_payloads(tmp_path)
    _write_jsonl(
        artifacts["accepted_diffs"],
        [
            {
                "record_type": "phase43_ledger_metadata",
                "quality_corpus": "golden",
                "replay_window": {"count": 2},
                "guardrails": {"rss_ratio": 1.25},
            },
            {
                "query_id": "sq-001",
                "accepted_by": "operator",
                "accepted_reason": "same answer",
            },
        ],
    )
    _write_json(artifacts["scale_metrics"], json.loads(json.dumps(_shadow_metric_bundle(), default=str)))
    _write_json(artifacts["memory_metrics"], json.loads(json.dumps(_shadow_metric_bundle(), default=str)))

    run_eval_calls: list[Path | None] = []

    def _fake_run_eval(config):  # type: ignore[no-untyped-def]
        run_eval_calls.append(config.acceptance)
        return SimpleNamespace(exit_code=0, rows=(), summary=SimpleNamespace(passed=True))

    monkeypatch.setattr("devtools.surreal_shadow_runner.run_eval", _fake_run_eval)
    monkeypatch.setattr(
        "devtools.surreal_shadow_runner.capture_baseline_eval_results",
        lambda *_args, **_kwargs: _write_jsonl(
            artifacts["baseline_results"],
            [_eval_result_row(f"sq-{index:03d}", category) for index, category in enumerate(GoldenQueryCategory, start=1)],
        ),
    )
    monkeypatch.setattr(
        "devtools.surreal_shadow_runner.capture_eval_results_from_candidates",
        lambda *_args, **_kwargs: _write_jsonl(
            artifacts["candidate_results"],
            [_eval_result_row(f"sq-{index:03d}", category) for index, category in enumerate(GoldenQueryCategory, start=1)],
        ),
    )
    monkeypatch.setattr("devtools.surreal_shadow_runner.copy_baseline_graph", lambda *args, **kwargs: SimpleNamespace(falkordb_url="redis://localhost:6379", source_graph="dotmd", baseline_graph="dotmd_shadow_baseline"))
    monkeypatch.setattr("devtools.surreal_shadow_runner.teardown_baseline_graph", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("devtools.surreal_shadow_runner.build_baseline_service", lambda *_args, **_kwargs: object())
    monkeypatch.setattr("devtools.surreal_shadow_runner.preflight_candidate_target", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("devtools.surreal_shadow_runner.load_settings", lambda: _settings(tmp_path / "prod-index"))
    monkeypatch.setattr(
        "devtools.surreal_shadow_runner.write_shadow_metric_json",
        lambda path, bundle: _write_json(path, {"passed": bundle.passed}),
    )

    config = SimpleNamespace(
        golden_queries=golden,
        source_capture_manifest_json=expected_manifest,
        candidate_config_json=_write_json(
            tmp_path / "candidate-config.json",
            {
                "embedding_dimension": 1024,
                "top_k": 5,
                "pool_size": 8,
            },
        ),
        baseline_rehearsal_path=rehearsal_root,
        baseline_graph_name="dotmd_shadow_baseline",
        production_graph_name=DEFAULT_FALKORDB_GRAPH_NAME,
        metrics_replay_queries=None,
        target_url="surrealkv:///tmp/shadow.db",
        target_namespace="dotmd",
        target_database="phase43_shadow",
        verify_only=False,
        capture_baseline=True,
        capture_candidate=True,
        preflight_candidate_target=False,
        artifacts=ShadowArtifactPaths(**artifacts),
    )

    run_shadow_run(config)

    assert run_eval_calls
    assert run_eval_calls[0] is not None
    assert run_eval_calls[0] != artifacts["accepted_diffs"]
    stripped_rows = [json.loads(line) for line in run_eval_calls[0].read_text(encoding="utf-8").splitlines()]
    assert stripped_rows == [
        {
            "accepted_by": "operator",
            "accepted_reason": "same answer",
            "query_id": "sq-001",
        }
    ]


def test_candidate_config_routes_only_embedding_dimension_and_hnsw_ef_to_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from devtools.surreal_shadow_runner import (
        capture_eval_results_from_candidates,
        load_candidate_config,
    )

    config = load_candidate_config(
        _write_json(
            tmp_path / "candidate-config.json",
            {
                "embedding_dimension": 1024,
                "hnsw_ef": 55,
                "top_k": 7,
                "pool_size": 11,
            },
        )
    )

    recorded_kwargs: list[dict[str, object]] = []

    def _fake_build_surreal_native_engine_overrides(*_args, **kwargs):  # type: ignore[no-untyped-def]
        recorded_kwargs.append(kwargs)
        return {}

    monkeypatch.setattr(
        "devtools.surreal_shadow_runner.build_surreal_native_engine_overrides",
        _fake_build_surreal_native_engine_overrides,
    )

    capture_eval_results_from_candidates(
        service=SimpleNamespace(search=lambda *_args, **_kwargs: []),
        golden_queries=[],
        output_path=tmp_path / "candidate-results.jsonl",
        connection=object(),
        settings=_settings(tmp_path / "settings"),
        candidate_config=config,
    )

    assert recorded_kwargs == [{"embedding_dimension": 1024, "hnsw_ef": 55}]


def test_candidate_config_defaults_hnsw_ef(tmp_path: Path) -> None:
    from devtools.surreal_shadow_runner import load_candidate_config

    config = load_candidate_config(
        _write_json(
            tmp_path / "candidate-config.json",
            {
                "embedding_dimension": 1024,
                "top_k": 5,
                "pool_size": 8,
            },
        )
    )

    assert config.hnsw_ef == DEFAULT_HNSW_EF


@pytest.mark.parametrize("extra_key", ["unknown", "graph_name"])
def test_candidate_config_rejects_unknown_keys(tmp_path: Path, extra_key: str) -> None:
    from devtools.surreal_shadow_runner import load_candidate_config

    with pytest.raises(ValueError, match=extra_key):
        load_candidate_config(
            _write_json(
                tmp_path / "candidate-config.json",
                {
                    "embedding_dimension": 1024,
                    "top_k": 5,
                    "pool_size": 8,
                    extra_key: 1,
                },
            )
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("embedding_dimension", 0),
        ("embedding_dimension", -1),
        ("embedding_dimension", "1024"),
        ("top_k", 0),
        ("pool_size", -1),
        ("hnsw_ef", 0),
    ],
)
def test_candidate_config_rejects_non_positive_integer(
    tmp_path: Path,
    field_name: str,
    value: object,
) -> None:
    from devtools.surreal_shadow_runner import load_candidate_config

    payload = {
        "embedding_dimension": 1024,
        "top_k": 5,
        "pool_size": 8,
        "hnsw_ef": 40,
    }
    payload[field_name] = value

    with pytest.raises(ValueError, match=field_name):
        load_candidate_config(_write_json(tmp_path / "candidate-config.json", payload))


@pytest.mark.parametrize("missing_field", ["embedding_dimension", "top_k", "pool_size"])
def test_candidate_config_rejects_missing_required_field(
    tmp_path: Path,
    missing_field: str,
) -> None:
    from devtools.surreal_shadow_runner import load_candidate_config

    payload = {
        "embedding_dimension": 1024,
        "top_k": 5,
        "pool_size": 8,
    }
    payload.pop(missing_field)

    with pytest.raises(ValueError, match=missing_field):
        load_candidate_config(_write_json(tmp_path / "candidate-config.json", payload))


def test_enforce_baseline_graph_isolation_refuses_production_name() -> None:
    from devtools.surreal_shadow_runner import enforce_baseline_graph_isolation

    enforce_baseline_graph_isolation("dotmd_shadow_baseline")

    with pytest.raises(ValueError, match="dotmd"):
        enforce_baseline_graph_isolation(DEFAULT_FALKORDB_GRAPH_NAME)


def test_copy_baseline_graph_uses_graph_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    from devtools.surreal_shadow_runner import copy_baseline_graph

    calls: list[tuple[str, str]] = []

    class _FakeGraph:
        def __init__(self, name: str) -> None:
            self.name = name

        def copy(self, destination: str) -> None:
            calls.append((self.name, destination))

        def delete(self) -> None:
            raise AssertionError("delete should not be called")

    class _FakeClient:
        def list_graphs(self) -> list[str]:
            return []

        def select_graph(self, graph_name: str) -> _FakeGraph:
            return _FakeGraph(graph_name)

    monkeypatch.setattr("devtools.surreal_shadow_runner._build_falkordb_client", lambda _url: _FakeClient())

    handle = copy_baseline_graph("redis://localhost:6379", "dotmd", "dotmd_shadow_baseline")

    assert handle.baseline_graph == "dotmd_shadow_baseline"
    assert calls == [("dotmd", "dotmd_shadow_baseline")]


def test_copy_baseline_graph_deletes_stale_destination_before_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from devtools.surreal_shadow_runner import copy_baseline_graph

    events: list[tuple[str, str]] = []

    class _FakeGraph:
        def __init__(self, name: str) -> None:
            self.name = name

        def copy(self, destination: str) -> None:
            events.append(("copy", f"{self.name}->{destination}"))

        def delete(self) -> None:
            events.append(("delete", self.name))

    class _FakeClient:
        def list_graphs(self) -> list[str]:
            return ["dotmd_shadow_baseline"]

        def select_graph(self, graph_name: str) -> _FakeGraph:
            return _FakeGraph(graph_name)

    monkeypatch.setattr("devtools.surreal_shadow_runner._build_falkordb_client", lambda _url: _FakeClient())

    copy_baseline_graph("redis://localhost:6379", "dotmd", "dotmd_shadow_baseline")

    assert events == [
        ("delete", "dotmd_shadow_baseline"),
        ("copy", "dotmd->dotmd_shadow_baseline"),
    ]


def test_copy_baseline_graph_refuses_production_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from devtools.surreal_shadow_runner import copy_baseline_graph

    called = False

    class _FakeClient:
        def list_graphs(self) -> list[str]:
            nonlocal called
            called = True
            return []

    monkeypatch.setattr("devtools.surreal_shadow_runner._build_falkordb_client", lambda _url: _FakeClient())

    with pytest.raises(ValueError, match="dotmd"):
        copy_baseline_graph("redis://localhost:6379", "dotmd", DEFAULT_FALKORDB_GRAPH_NAME)

    assert called is False


def test_teardown_baseline_graph_deletes_isolated_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    from devtools.surreal_shadow_runner import IsolatedBaselineGraph, teardown_baseline_graph

    deleted: list[str] = []

    class _FakeGraph:
        def __init__(self, graph_name: str) -> None:
            self.graph_name = graph_name

        def delete(self) -> None:
            deleted.append(self.graph_name)

    class _FakeClient:
        def select_graph(self, graph_name: str) -> _FakeGraph:
            return _FakeGraph(graph_name)

    monkeypatch.setattr("devtools.surreal_shadow_runner._build_falkordb_client", lambda _url: _FakeClient())

    teardown_baseline_graph(
        IsolatedBaselineGraph(
            falkordb_url="redis://localhost:6379",
            source_graph="dotmd",
            baseline_graph="dotmd_shadow_baseline",
        )
    )

    assert deleted == ["dotmd_shadow_baseline"]


def test_build_baseline_service_binds_isolated_graph_name(tmp_path: Path) -> None:
    from devtools.surreal_shadow_runner import build_baseline_service

    rehearsal_settings = _settings(tmp_path / "rehearsal").model_copy(
        update={
            "falkordb_graph_name": "dotmd_shadow_baseline",
        }
    )

    service = build_baseline_service(rehearsal_settings)

    assert service is not None


def test_capture_baseline_eval_results_runs_full_corpus_with_coverage(tmp_path: Path) -> None:
    from devtools.surreal_shadow_runner import capture_baseline_eval_results

    from dotmd.search.surreal_eval import load_eval_results

    golden_path = _write_complete_golden_corpus(tmp_path / "golden.jsonl")
    output_path = tmp_path / "baseline-results.jsonl"
    seen_queries: list[str] = []

    class _FakeService:
        def search(self, query: str, top_k: int = 10) -> list[SimpleNamespace]:
            seen_queries.append(query)
            return [
                SimpleNamespace(
                    ref=f"filesystem:/mnt/{query}.md",
                    score=1.0,
                    matched_terms=("semantic",),
                    snippet=query,
                    read_evidence=query,
                    unreadable=False,
                )
            ]

    capture_baseline_eval_results(_FakeService(), golden_path, output_path)

    rows = load_eval_results(output_path)
    assert len(rows) == len(tuple(GoldenQueryCategory))
    assert len(seen_queries) == len(tuple(GoldenQueryCategory))


def test_production_index_and_graph_untouched_by_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from devtools.surreal_shadow_runner import ShadowArtifactPaths, run_shadow_run

    production_root = tmp_path / "production-index"
    production_db = _create_rehearsal_index_db(production_root)
    production_stat_before = production_db.stat()
    rehearsal_root = tmp_path / "rehearsal"
    _create_rehearsal_index_db(rehearsal_root)
    golden = _write_complete_golden_corpus(tmp_path / "golden.jsonl")
    expected_manifest = _write_json(
        tmp_path / "source-capture-expected.json",
        _expected_manifest_payload(),
    )
    artifacts = _artifact_payloads(tmp_path)
    _write_jsonl(
        artifacts["accepted_diffs"],
        [
            {
                "record_type": "phase43_ledger_metadata",
                "quality_corpus": "golden",
                "replay_window": {"count": 2},
                "guardrails": {"rss_ratio": 1.25},
            }
        ],
    )
    _write_json(artifacts["scale_metrics"], {"passed": True})
    _write_json(artifacts["memory_metrics"], {"passed": True})

    graphs_after_run = ["dotmd"]
    monkeypatch.setattr(
        "devtools.surreal_shadow_runner.load_settings",
        lambda: _settings(production_root),
    )
    monkeypatch.setenv("DOTMD_INDEX_DIR", str(production_root))
    monkeypatch.setattr(
        "devtools.surreal_shadow_runner.copy_baseline_graph",
        lambda *_args, **_kwargs: SimpleNamespace(
            falkordb_url="redis://localhost:6379",
            source_graph="dotmd",
            baseline_graph="dotmd_shadow_baseline",
        ),
    )
    monkeypatch.setattr("devtools.surreal_shadow_runner.teardown_baseline_graph", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("devtools.surreal_shadow_runner._list_graph_names", lambda _url: graphs_after_run)
    monkeypatch.setattr("devtools.surreal_shadow_runner.build_baseline_service", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        "devtools.surreal_shadow_runner.capture_baseline_eval_results",
        lambda *_args, **_kwargs: _write_jsonl(
            artifacts["baseline_results"],
            [_eval_result_row(f"sq-{index:03d}", category) for index, category in enumerate(GoldenQueryCategory, start=1)],
        ),
    )
    monkeypatch.setattr(
        "devtools.surreal_shadow_runner.capture_eval_results_from_candidates",
        lambda *_args, **_kwargs: _write_jsonl(
            artifacts["candidate_results"],
            [_eval_result_row(f"sq-{index:03d}", category) for index, category in enumerate(GoldenQueryCategory, start=1)],
        ),
    )
    monkeypatch.setattr("devtools.surreal_shadow_runner.run_eval", lambda config: SimpleNamespace(exit_code=0, rows=(), summary=SimpleNamespace(passed=True)))
    monkeypatch.setattr("devtools.surreal_shadow_runner.preflight_candidate_target", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "devtools.surreal_shadow_runner.write_shadow_metric_json",
        lambda path, _bundle: _write_json(path, {"passed": True}),
    )

    config = SimpleNamespace(
        golden_queries=golden,
        source_capture_manifest_json=expected_manifest,
        candidate_config_json=_write_json(
            tmp_path / "candidate-config.json",
            {
                "embedding_dimension": 1024,
                "top_k": 5,
                "pool_size": 8,
            },
        ),
        baseline_rehearsal_path=rehearsal_root,
        baseline_graph_name="dotmd_shadow_baseline",
        production_graph_name=DEFAULT_FALKORDB_GRAPH_NAME,
        metrics_replay_queries=None,
        target_url="surrealkv:///tmp/shadow.db",
        target_namespace="dotmd",
        target_database="phase43_shadow",
        verify_only=False,
        capture_baseline=True,
        capture_candidate=True,
        preflight_candidate_target=False,
        artifacts=ShadowArtifactPaths(**artifacts),
    )

    run_shadow_run(config)

    production_stat_after = production_db.stat()
    assert (production_stat_after.st_mtime_ns, production_stat_after.st_size) == (
        production_stat_before.st_mtime_ns,
        production_stat_before.st_size,
    )
    assert DEFAULT_FALKORDB_GRAPH_NAME in graphs_after_run


def test_preflight_passes_when_target_queryable_with_records(tmp_path: Path) -> None:
    from devtools.surreal_shadow_runner import (
        load_candidate_config,
        load_expected_source_manifest,
        preflight_candidate_target,
    )

    manifest = load_expected_source_manifest(
        _write_json(tmp_path / "expected.json", _expected_manifest_payload())
    )
    config = load_candidate_config(
        _write_json(
            tmp_path / "candidate-config.json",
            {"embedding_dimension": 1024, "top_k": 5, "pool_size": 8},
        )
    )

    class _FakeConnection:
        def __init__(self) -> None:
            self.queries: list[str] = []

        def query(self, sql: str, **_kwargs):  # type: ignore[no-untyped-def]
            self.queries.append(sql)
            if "count() AS count FROM chunks" in sql:
                return [{"count": manifest.expected_chunk_count}]
            if "count() AS count FROM embeddings" in sql:
                return [{"count": manifest.expected_embedding_count}]
            if "chunk_strategy FROM chunks" in sql:
                return [{"chunk_strategy": manifest.chunk_strategy}]
            if "embedding_model FROM embeddings GROUP" in sql:
                return [{"embedding_model": manifest.embedding_model}]
            if "embedding_model, embedding FROM embeddings" in sql:
                return [
                    {
                        "embedding_model": manifest.embedding_model,
                        "embedding": [0.0] * config.embedding_dimension,
                    }
                ]
            raise AssertionError(f"unexpected query: {sql}")

    connection = _FakeConnection()
    progress_path = tmp_path / "preflight-progress.json"
    preflight_candidate_target(
        connection,
        _settings(tmp_path / "index"),
        config,
        manifest,
        progress_path=progress_path,
    )

    assert all(query != "phase43 preflight" for query in connection.queries)
    progress_payload = json.loads(progress_path.read_text(encoding="utf-8"))
    assert progress_payload["step"] == "complete"
    assert progress_payload["status"] == "applied"


def test_preflight_fails_when_target_unreachable(tmp_path: Path) -> None:
    from devtools.surreal_shadow_runner import (
        load_candidate_config,
        load_expected_source_manifest,
        preflight_candidate_target,
    )

    manifest = load_expected_source_manifest(
        _write_json(tmp_path / "expected.json", _expected_manifest_payload())
    )
    config = load_candidate_config(
        _write_json(
            tmp_path / "candidate-config.json",
            {"embedding_dimension": 1024, "top_k": 5, "pool_size": 8},
        )
    )

    class _FakeConnection:
        def query(self, _sql: str, **_kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("unreachable")

    with pytest.raises(RuntimeError, match="unreachable"):
        preflight_candidate_target(_FakeConnection(), _settings(tmp_path / "index"), config, manifest)


def test_preflight_fails_when_target_empty(tmp_path: Path) -> None:
    from devtools.surreal_shadow_runner import (
        load_candidate_config,
        load_expected_source_manifest,
        preflight_candidate_target,
    )

    manifest = load_expected_source_manifest(
        _write_json(tmp_path / "expected.json", _expected_manifest_payload())
    )
    config = load_candidate_config(
        _write_json(
            tmp_path / "candidate-config.json",
            {"embedding_dimension": 1024, "top_k": 5, "pool_size": 8},
        )
    )

    class _FakeConnection:
        def query(self, sql: str, **_kwargs):  # type: ignore[no-untyped-def]
            if "count() AS count FROM chunks" in sql:
                return [{"count": 0}]
            if "count() AS count FROM embeddings" in sql:
                return [{"count": 0}]
            raise AssertionError(f"unexpected query: {sql}")

    with pytest.raises(ValueError, match="empty"):
        preflight_candidate_target(_FakeConnection(), _settings(tmp_path / "index"), config, manifest)


def test_preflight_fails_when_target_identity_mismatches_manifest(tmp_path: Path) -> None:
    from devtools.surreal_shadow_runner import (
        load_candidate_config,
        load_expected_source_manifest,
        preflight_candidate_target,
    )

    manifest = load_expected_source_manifest(
        _write_json(tmp_path / "expected.json", _expected_manifest_payload())
    )
    config = load_candidate_config(
        _write_json(
            tmp_path / "candidate-config.json",
            {"embedding_dimension": 1024, "top_k": 5, "pool_size": 8},
        )
    )

    class _FakeConnection:
        def query(self, sql: str, **_kwargs):  # type: ignore[no-untyped-def]
            if "count() AS count FROM chunks" in sql:
                return [{"count": manifest.expected_chunk_count + 1}]
            if "count() AS count FROM embeddings" in sql:
                return [{"count": manifest.expected_embedding_count}]
            if "chunk_strategy FROM chunks" in sql:
                return [{"chunk_strategy": manifest.chunk_strategy}]
            if "embedding_model FROM embeddings GROUP" in sql:
                return [{"embedding_model": manifest.embedding_model}]
            raise AssertionError(f"unexpected query: {sql}")

    with pytest.raises(ValueError, match="expected_chunk_count"):
        preflight_candidate_target(_FakeConnection(), _settings(tmp_path / "index"), config, manifest)


def test_build_baseline_service_uses_model_copy_clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from devtools.surreal_shadow_runner import build_baseline_service

    calls: list[Settings] = []

    class _FakeDotMDService:
        def __init__(self, settings: Settings) -> None:
            calls.append(settings)

    monkeypatch.setattr("devtools.surreal_shadow_runner.DotMDService", _FakeDotMDService)

    base_settings = _settings(tmp_path / "prod")
    rehearsal_settings = base_settings.model_copy(
        update={
            "index_dir": tmp_path / "rehearsal",
            "falkordb_graph_name": "dotmd_shadow_baseline",
        }
    )

    build_baseline_service(rehearsal_settings)

    assert calls
    assert calls[0].index_db_path == rehearsal_settings.index_db_path
    assert calls[0].falkordb_graph_name == "dotmd_shadow_baseline"
    assert base_settings.falkordb_graph_name == DEFAULT_FALKORDB_GRAPH_NAME


def test_build_baseline_service_targets_isolated_copies_not_production(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from devtools.surreal_shadow_runner import build_baseline_service

    seen_settings: list[Settings] = []

    class _FakeDotMDService:
        def __init__(self, settings: Settings) -> None:
            seen_settings.append(settings)

    monkeypatch.setattr("devtools.surreal_shadow_runner.DotMDService", _FakeDotMDService)

    rehearsal_settings = _settings(tmp_path / "prod").model_copy(
        update={
            "index_dir": tmp_path / "rehearsal",
            "falkordb_graph_name": "dotmd_shadow_baseline",
        }
    )

    build_baseline_service(rehearsal_settings)

    assert seen_settings[0].index_dir == tmp_path / "rehearsal"
    assert seen_settings[0].falkordb_graph_name == "dotmd_shadow_baseline"
    assert seen_settings[0].falkordb_graph_name != DEFAULT_FALKORDB_GRAPH_NAME


def test_rehearsal_identity_match_passes(tmp_path: Path) -> None:
    from devtools.surreal_shadow_runner import (
        assert_rehearsal_identity_matches_manifest,
        load_expected_source_manifest,
    )

    rehearsal_root = tmp_path / "rehearsal"
    _create_rehearsal_index_db(rehearsal_root)
    settings = _settings(rehearsal_root)
    manifest = load_expected_source_manifest(
        _write_json(tmp_path / "expected.json", _expected_manifest_payload())
    )

    assert_rehearsal_identity_matches_manifest(settings, manifest)


def test_rehearsal_identity_mismatch_fails_closed(tmp_path: Path) -> None:
    from devtools.surreal_shadow_runner import (
        assert_rehearsal_identity_matches_manifest,
        load_expected_source_manifest,
    )

    rehearsal_root = tmp_path / "rehearsal"
    _create_rehearsal_index_db(rehearsal_root, chunk_count=4)
    settings = _settings(rehearsal_root)
    manifest = load_expected_source_manifest(
        _write_json(tmp_path / "expected.json", _expected_manifest_payload())
    )

    with pytest.raises(ValueError, match="expected_chunk_count"):
        assert_rehearsal_identity_matches_manifest(settings, manifest)


def test_rehearsal_identity_vec_table_name_matches_pipeline_convention(tmp_path: Path) -> None:
    from devtools.surreal_shadow_runner import (
        assert_rehearsal_identity_matches_manifest,
        load_expected_source_manifest,
    )

    rehearsal_root = tmp_path / "rehearsal"
    embedding_model = "Qwen/Qwen3-Embedding-0.6B"
    _create_rehearsal_index_db(
        rehearsal_root,
        chunk_strategy="heading_512_50",
        embedding_model=embedding_model,
    )
    settings = _settings(rehearsal_root).model_copy(update={"embedding_model": embedding_model})
    manifest = load_expected_source_manifest(
        _write_json(
            tmp_path / "expected.json",
            _expected_manifest_payload(embedding_model=embedding_model),
        )
    )

    assert_rehearsal_identity_matches_manifest(settings, manifest)


def test_expected_manifest_input_is_never_rewritten(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from devtools.surreal_shadow_runner import ShadowArtifactPaths, run_shadow_run

    expected_manifest = _write_json(
        tmp_path / "source-capture-expected.json",
        _expected_manifest_payload(),
    )
    expected_bytes = expected_manifest.read_bytes()
    rehearsal_root = tmp_path / "rehearsal"
    _create_rehearsal_index_db(rehearsal_root)
    golden = _write_complete_golden_corpus(tmp_path / "golden.jsonl")
    artifacts = _artifact_payloads(tmp_path)
    _write_jsonl(
        artifacts["accepted_diffs"],
        [
            {
                "record_type": "phase43_ledger_metadata",
                "quality_corpus": "golden",
                "replay_window": {"count": 2},
                "guardrails": {"rss_ratio": 1.25},
            }
        ],
    )
    _write_json(artifacts["scale_metrics"], {"passed": True})
    _write_json(artifacts["memory_metrics"], {"passed": True})

    monkeypatch.setattr("devtools.surreal_shadow_runner.load_settings", lambda: _settings(tmp_path / "prod"))
    monkeypatch.setattr("devtools.surreal_shadow_runner.copy_baseline_graph", lambda *_args, **_kwargs: SimpleNamespace(falkordb_url="redis://localhost:6379", source_graph="dotmd", baseline_graph="dotmd_shadow_baseline"))
    monkeypatch.setattr("devtools.surreal_shadow_runner.teardown_baseline_graph", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("devtools.surreal_shadow_runner._list_graph_names", lambda _url: ["dotmd"])
    monkeypatch.setattr("devtools.surreal_shadow_runner.build_baseline_service", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        "devtools.surreal_shadow_runner.capture_baseline_eval_results",
        lambda *_args, **_kwargs: _write_jsonl(
            artifacts["baseline_results"],
            [_eval_result_row(f"sq-{index:03d}", category) for index, category in enumerate(GoldenQueryCategory, start=1)],
        ),
    )
    monkeypatch.setattr(
        "devtools.surreal_shadow_runner.capture_eval_results_from_candidates",
        lambda *_args, **_kwargs: _write_jsonl(
            artifacts["candidate_results"],
            [_eval_result_row(f"sq-{index:03d}", category) for index, category in enumerate(GoldenQueryCategory, start=1)],
        ),
    )
    monkeypatch.setattr("devtools.surreal_shadow_runner.run_eval", lambda config: SimpleNamespace(exit_code=0, rows=(), summary=SimpleNamespace(passed=True)))
    monkeypatch.setattr("devtools.surreal_shadow_runner.preflight_candidate_target", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "devtools.surreal_shadow_runner.write_shadow_metric_json",
        lambda path, _bundle: _write_json(path, {"passed": True}),
    )

    config = SimpleNamespace(
        golden_queries=golden,
        source_capture_manifest_json=expected_manifest,
        candidate_config_json=_write_json(
            tmp_path / "candidate-config.json",
            {"embedding_dimension": 1024, "top_k": 5, "pool_size": 8},
        ),
        baseline_rehearsal_path=rehearsal_root,
        baseline_graph_name="dotmd_shadow_baseline",
        production_graph_name=DEFAULT_FALKORDB_GRAPH_NAME,
        metrics_replay_queries=None,
        target_url="surrealkv:///tmp/shadow.db",
        target_namespace="dotmd",
        target_database="phase43_shadow",
        verify_only=False,
        capture_baseline=True,
        capture_candidate=True,
        preflight_candidate_target=False,
        artifacts=ShadowArtifactPaths(**artifacts),
    )

    run_shadow_run(config)

    assert expected_manifest.read_bytes() == expected_bytes
    assert artifacts["source_capture"].exists()


def test_rehearsal_isolation_refuses_production_index_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from devtools.surreal_shadow_runner import enforce_rehearsal_path_isolation

    production_root = tmp_path / "production"
    _create_rehearsal_index_db(production_root)
    monkeypatch.setenv("DOTMD_INDEX_DIR", str(production_root))

    with pytest.raises(ValueError, match="production"):
        enforce_rehearsal_path_isolation(production_root, production_root)

    with pytest.raises(ValueError, match=str(RUNTIME_INDEX_DIR)):
        enforce_rehearsal_path_isolation(RUNTIME_INDEX_DIR, tmp_path / "production")


def test_rehearsal_isolation_runs_integrity_check(tmp_path: Path) -> None:
    from devtools.surreal_shadow_runner import enforce_rehearsal_path_isolation

    rehearsal_root = tmp_path / "rehearsal"
    _create_rehearsal_index_db(rehearsal_root)

    enforce_rehearsal_path_isolation(rehearsal_root, tmp_path / "production")

    corrupt_root = tmp_path / "corrupt"
    corrupt_root.mkdir(parents=True, exist_ok=True)
    (corrupt_root / "index.db").write_bytes(b"not a sqlite database")

    with pytest.raises(ValueError, match="integrity_check"):
        enforce_rehearsal_path_isolation(corrupt_root, tmp_path / "production")


def test_rehearsal_isolation_rejects_symlinked_index_db(tmp_path: Path) -> None:
    from devtools.surreal_shadow_runner import enforce_rehearsal_path_isolation

    target_root = tmp_path / "target"
    target_db = _create_rehearsal_index_db(target_root)
    rehearsal_root = tmp_path / "rehearsal"
    rehearsal_root.mkdir(parents=True, exist_ok=True)
    (rehearsal_root / "index.db").symlink_to(target_db)

    with pytest.raises(ValueError, match="symlink"):
        enforce_rehearsal_path_isolation(rehearsal_root, tmp_path / "production")


def test_metrics_replay_queries_parser_requires_path_and_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from devtools.surreal_shadow_runner import load_metrics_replay_queries

    replay = _write_jsonl(
        tmp_path / "replay.jsonl",
        [
            {"query_id": "rq-001", "query": "surreal shadow"},
            {"query_id": "rq-002", "query": "graph entity"},
        ],
    )

    rows = load_metrics_replay_queries(replay)

    assert rows == (
        {"query_id": "rq-001", "query": "surreal shadow"},
        {"query_id": "rq-002", "query": "graph entity"},
    )

    malformed = _write_jsonl(tmp_path / "malformed.jsonl", [{"query_id": "rq-001"}])
    with pytest.raises(ValueError, match="query"):
        load_metrics_replay_queries(malformed)


def test_verify_only_fails_when_required_artifact_is_missing(tmp_path: Path) -> None:
    from devtools.surreal_shadow_runner import ShadowArtifactPaths, verify_shadow_artifacts

    artifacts = ShadowArtifactPaths(**_artifact_payloads(tmp_path))
    _write_json(artifacts.source_capture, {"ok": True})

    with pytest.raises(ValueError, match="baseline-results"):
        verify_shadow_artifacts(artifacts)


def test_verify_only_regenerates_shadow_diffs_by_query_id_keyed_comparison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from devtools.surreal_shadow_runner import ShadowArtifactPaths, verify_shadow_artifacts

    artifacts = ShadowArtifactPaths(**_artifact_payloads(tmp_path))
    _write_jsonl(
        artifacts.shadow_diffs,
        [
            {"query_id": "sq-001", "classification": "harmless_reorder", "cutover_gate": "allow"},
            {"query_id": "sq-002", "classification": "improvement", "cutover_gate": "allow"},
        ],
    )
    for path in (
        artifacts.source_capture,
        artifacts.baseline_results,
        artifacts.candidate_results,
        artifacts.accepted_diffs,
        artifacts.shadow_summary,
        artifacts.scale_metrics,
        artifacts.memory_metrics,
    ):
        if path.suffix == ".jsonl":
            _write_jsonl(path, [{"query_id": "placeholder", "accepted_by": "ops", "accepted_reason": "ok"}])
        elif path.suffix == ".json":
            _write_json(path, {"passed": True})
        else:
            path.write_text("summary", encoding="utf-8")

    monkeypatch.setattr(
        "devtools.surreal_shadow_runner._regenerate_shadow_diffs",
        lambda *_args, **_kwargs: (
            {
                "sq-002": {"classification": "improvement", "cutover_gate": "allow"},
                "sq-001": {"classification": "harmless_reorder", "cutover_gate": "allow"},
            },
            {
                "sq-001": {"classification": "harmless_reorder", "cutover_gate": "allow"},
                "sq-002": {"classification": "improvement", "cutover_gate": "allow"},
            },
        ),
    )

    verify_shadow_artifacts(artifacts)

    monkeypatch.setattr(
        "devtools.surreal_shadow_runner._regenerate_shadow_diffs",
        lambda *_args, **_kwargs: (
            {"sq-001": {"classification": "regression", "cutover_gate": "block"}},
            {"sq-001": {"classification": "harmless_reorder", "cutover_gate": "allow"}},
        ),
    )

    with pytest.raises(ValueError, match="query_id"):
        verify_shadow_artifacts(artifacts)


def test_import_has_no_startup_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    writes: list[Path] = []

    real_write_text = Path.write_text

    def _record_write(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
        writes.append(self)
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _record_write)

    importlib.import_module("devtools.surreal_shadow_runner")

    assert writes == []
