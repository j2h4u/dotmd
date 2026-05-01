"""CLI tests for runtime reranker selection and comparison diagnostics."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from dotmd.cli import main


def test_search_accepts_reranker_option(tmp_path: Path) -> None:
    with patch("dotmd.api.service.DotMDService.search", return_value=[]) as search:
        result = CliRunner().invoke(
            main,
            [
                "--index-dir",
                str(tmp_path),
                "search",
                "test query",
                "--reranker",
                "msmarco-minilm",
            ],
        )

    assert result.exit_code == 0, result.output
    assert search.call_args.kwargs["reranker_name"] == "msmarco-minilm"


def test_rerank_compare_command_outputs_diagnostics(tmp_path: Path) -> None:
    comparison = {
        "query": "test query",
        "search_query": "expanded query",
        "shared_pool_size": 2,
        "rerankers": [
            {
                "name": "qwen3-0.6b",
                "model_name": "Qwen",
                "elapsed_ms": 12.34,
                "returned_count": 2,
                "top_chunk_ids": ["c1", "c2"],
                "scores": [0.9, 0.8],
                "error": None,
            },
            {
                "name": "msmarco-minilm",
                "model_name": "MiniLM",
                "elapsed_ms": 4.56,
                "returned_count": 1,
                "top_chunk_ids": ["c2"],
                "scores": [0.7],
                "error": None,
            },
        ],
        "overlap_reference": "qwen3-0.6b",
        "overlap": {"qwen3-0.6b": 2, "msmarco-minilm": 1},
    }
    with patch(
        "dotmd.api.service.DotMDService.compare_rerankers",
        return_value=comparison,
    ) as compare:
        result = CliRunner().invoke(
            main,
            [
                "--index-dir",
                str(tmp_path),
                "rerank",
                "compare",
                "test query",
                "--rerankers",
                "qwen3-0.6b,msmarco-minilm",
            ],
        )

    assert result.exit_code == 0, result.output
    compare.assert_called_once_with(
        query="test query",
        reranker_names=["qwen3-0.6b", "msmarco-minilm"],
        top_k=10,
        mode="hybrid",
        expand=True,
    )
    assert "Shared pool: 2 candidates" in result.output
    assert "qwen3-0.6b" in result.output
    assert "msmarco-minilm" in result.output
    assert "elapsed_ms=12.3" in result.output
    assert "Overlap reference: qwen3-0.6b" in result.output


def test_rerank_compare_unknown_reranker_is_click_error(tmp_path: Path) -> None:
    with patch(
        "dotmd.api.service.DotMDService.compare_rerankers",
        side_effect=ValueError("Unknown reranker 'missing'; available: qwen3-0.6b"),
    ):
        result = CliRunner().invoke(
            main,
            [
                "--index-dir",
                str(tmp_path),
                "rerank",
                "compare",
                "test query",
                "--rerankers",
                "missing",
            ],
        )

    assert result.exit_code != 0
    assert "Unknown reranker" in result.output
