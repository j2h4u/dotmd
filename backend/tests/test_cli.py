"""CLI tests for runtime reranker selection and comparison diagnostics."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from dotmd.cli import main
from dotmd.core.models import SearchResponse


def test_search_accepts_reranker_option(tmp_path: Path) -> None:
    with patch(
        "dotmd.api.service.DotMDService.search",
        return_value=SearchResponse(),
    ) as search:
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


def test_search_accepts_federated_option(tmp_path: Path) -> None:
    with patch(
        "dotmd.api.service.DotMDService.search",
        return_value=SearchResponse(),
    ) as search:
        result = CliRunner().invoke(
            main,
            [
                "--index-dir",
                str(tmp_path),
                "search",
                "test query",
                "--federated",
            ],
        )

    assert result.exit_code == 0, result.output
    assert search.call_args.kwargs["include_federated"] is True


def test_search_unknown_reranker_is_click_error(tmp_path: Path) -> None:
    with patch(
        "dotmd.api.service.DotMDService.search",
        side_effect=ValueError("Unknown reranker 'missing'; available: mmarco-minilm"),
    ):
        result = CliRunner().invoke(
            main,
            [
                "--index-dir",
                str(tmp_path),
                "search",
                "test query",
                "--reranker",
                "missing",
            ],
        )

    assert result.exit_code != 0
    assert "Unknown reranker" in result.output


def test_rerank_compare_command_outputs_diagnostics(tmp_path: Path) -> None:
    comparison = {
        "query": "test query",
        "search_query": "expanded query",
        "shared_pool_size": 2,
        "rerankers": [
            {
                "name": "mmarco-minilm",
                "model_name": "MMARCO",
                "elapsed_ms": 12.34,
                "elapsed": "12s",
                "load_ms": 2.34,
                "load": "2s",
                "rerank_ms": 10.0,
                "rerank": "10s",
                "returned_count": 2,
                "top_chunk_ids": ["c1", "c2"],
                "scores": [0.9, 0.8],
                "error": None,
            },
            {
                "name": "msmarco-minilm",
                "model_name": "MiniLM",
                "elapsed_ms": 4.56,
                "elapsed": "5s",
                "load_ms": 1.0,
                "load": "1s",
                "rerank_ms": 3.56,
                "rerank": "4s",
                "returned_count": 1,
                "top_chunk_ids": ["c2"],
                "scores": [0.7],
                "error": None,
            },
        ],
        "overlap_reference": "mmarco-minilm",
        "overlap": {"mmarco-minilm": 2, "msmarco-minilm": 1},
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
                "mmarco-minilm,msmarco-minilm",
            ],
        )

    assert result.exit_code == 0, result.output
    compare.assert_called_once_with(
        query="test query",
        reranker_names=["mmarco-minilm", "msmarco-minilm"],
        top_k=10,
        mode="hybrid",
        expand=True,
    )
    assert "Shared pool: 2 candidates" in result.output
    assert "mmarco-minilm" in result.output
    assert "msmarco-minilm" in result.output
    assert "elapsed_ms=12.3" in result.output
    assert "elapsed=12s" in result.output
    assert "load_ms=2.3" in result.output
    assert "rerank_ms=10.0" in result.output
    assert "Overlap reference: mmarco-minilm" in result.output


def test_rerank_compare_unknown_reranker_is_click_error(tmp_path: Path) -> None:
    with patch(
        "dotmd.api.service.DotMDService.compare_rerankers",
        side_effect=ValueError("Unknown reranker 'missing'; available: mmarco-minilm"),
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


def test_oauth_code_create_outputs_pairing_code(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        main,
        [
            "--index-dir",
            str(tmp_path),
            "oauth",
            "code",
            "create",
            "--ttl",
            "60s",
        ],
    )

    assert result.exit_code == 0, result.output
    code_line = next(
        line
        for line in result.output.splitlines()
        if re.fullmatch(r"[A-Z2-9]{4}-[A-Z2-9]{4}", line)
    )
    assert len(code_line) == 9
    assert "Expires:" in result.output
    assert (tmp_path / "oauth_state.json").exists()


def test_status_verbose_reports_surrealdb_graph_and_skips_sqlite_tables(tmp_path: Path) -> None:
    service = SimpleNamespace(
        _settings=SimpleNamespace(
            search_backend="surreal",
            surreal_retrieval_url="http://surrealdb:8000",
            surreal_retrieval_namespace="dotmd",
            surreal_retrieval_database="production",
        ),
        _pipeline=SimpleNamespace(
            conn=SimpleNamespace(execute=lambda *_args, **_kwargs: pytest.fail("sqlite scan ran"))
        ),
        status=lambda: SimpleNamespace(
            total_files=1,
            total_chunks=2,
            total_entities=3,
            total_edges=4,
            last_indexed=None,
            data_dir=None,
            new_files=0,
            modified_files=0,
            deleted_files=0,
            trickle_status=None,
        ),
    )

    with patch("dotmd.cli._get_runtime_service_from_ctx", return_value=service):
        result = CliRunner().invoke(main, ["--index-dir", str(tmp_path), "status", "-V"])

    assert result.exit_code == 0, result.output
    assert "Graph:    SurrealDB @ http://surrealdb:8000/dotmd/production" in result.output
    assert "falkordb" not in result.output.lower()
    assert "Strategies:" not in result.output


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["reindex", "vectors"], "reindex vectors is retired after the SurrealDB cutover"),
        (["reset", "model", "legacy"], "reset model is retired after the SurrealDB cutover"),
    ],
)
def test_retired_old_stack_admin_commands_fail_fast(
    tmp_path: Path, args: list[str], expected: str
) -> None:
    result = CliRunner().invoke(main, ["--index-dir", str(tmp_path), *args])

    assert result.exit_code != 0
    assert expected in result.output
