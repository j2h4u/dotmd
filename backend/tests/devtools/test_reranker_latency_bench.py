from pathlib import Path

from devtools.reranker_latency_bench import (
    DEFAULT_RERANKERS,
    QUERY_SET_V1,
    BenchmarkConfig,
    dnf_row,
    latency_band,
    parse_rerankers,
    percentile,
    summarize_rows,
    write_summary_markdown,
)


def test_query_set_and_defaults_are_canonical() -> None:
    assert len(QUERY_SET_V1) == 10
    assert DEFAULT_RERANKERS == [
        "mmarco-minilm",
    ]


def test_parse_rerankers_defaults_and_trims_names() -> None:
    assert parse_rerankers(None) == DEFAULT_RERANKERS
    assert parse_rerankers(" mmarco-minilm, experimental ,,") == [
        "mmarco-minilm",
        "experimental",
    ]


def test_percentile_interpolates_values() -> None:
    assert percentile([10, 20, 30, 40], 50) == 25
    assert percentile([10, 20, 30, 40], 95) == 38.5


def test_latency_band_uses_hot_p95_and_failures() -> None:
    assert latency_band(9_999) == "fast"
    assert latency_band(30_000) == "acceptable"
    assert latency_band(120_000) == "slow"
    assert latency_band(120_001) == "unusable"
    assert latency_band(1, errors=1) == "unusable"
    assert latency_band(1, timeouts=1) == "unusable"
    assert latency_band(None) == "unusable"


def test_summarize_rows_uses_hot_rows_only_and_sorts_fastest_first() -> None:
    rows = [
        {
            "model": "slow",
            "model_name": "slow-model",
            "pass_kind": "hot",
            "rerank_ms": 40_000.0,
            "load_ms": 1.0,
            "error": None,
            "timeout": False,
        },
        {
            "model": "fast",
            "model_name": "fast-model",
            "pass_kind": "cold",
            "rerank_ms": 999_999.0,
            "load_ms": 20_000.0,
            "error": None,
            "timeout": False,
        },
        {
            "model": "fast",
            "model_name": "fast-model",
            "pass_kind": "hot",
            "rerank_ms": 1_000.0,
            "load_ms": 0.0,
            "error": None,
            "timeout": False,
        },
        {
            "model": "error",
            "model_name": "error-model",
            "pass_kind": "hot",
            "rerank_ms": None,
            "load_ms": None,
            "error": "provider failed",
            "timeout": False,
        },
    ]

    summary = summarize_rows(rows)

    assert [row["model"] for row in summary] == ["fast", "slow", "error"]
    assert summary[0]["p95_rerank_ms"] == 1_000.0
    assert summary[0]["cold_load_max_ms"] == 20_000.0
    assert summary[0]["latency_band"] == "fast"
    assert summary[1]["latency_band"] == "slow"
    assert summary[2]["latency_band"] == "unusable"
    assert summary[2]["error_count"] == 1


def test_dnf_row_records_timeout_contract(tmp_path: Path) -> None:
    config = BenchmarkConfig(
        rerankers=["a"],
        output=tmp_path / "out.jsonl",
        summary=tmp_path / "summary.md",
    )

    row = dnf_row("a", config, "abc123")

    assert row["model"] == "a"
    assert row["timeout"] is True
    assert row["error"] == "model_wall_timeout_s exceeded"
    assert row["commit"] == "abc123"
    assert row["shared_pool_size"] == 20
    assert row["top_n"] == 3


def test_write_summary_markdown_mentions_hot_metric_and_protocol(tmp_path: Path) -> None:
    config = BenchmarkConfig(
        rerankers=["fast"],
        output=tmp_path / "out.jsonl",
        summary=tmp_path / "summary.md",
    )
    write_summary_markdown(
        [
            {
                "model": "fast",
                "latency_band": "fast",
                "hot_samples": 30,
                "p50_rerank_ms": 1_000.0,
                "p95_rerank_ms": 2_000.0,
                "max_rerank_ms": 3_000.0,
                "cold_load_max_ms": 4_000.0,
                "error_count": 0,
                "timeout_count": 0,
            }
        ],
        config.summary,
        config=config,
        commit="abc123",
    )

    text = config.summary.read_text()
    assert "shared_pool_size=20" in text
    assert "top_n=3" in text
    assert "hot_samples_per_model=30" in text
    assert "hot p95 `rerank_ms`" in text
    assert "| `fast` | fast | 30 | 1s | 2s | 3s | 4s | 0 | 0 |" in text
