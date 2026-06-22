"""CLI search result rendering tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tests.conftest import make_surreal_runtime_settings


def _get_cli():  # type: ignore[no-untyped-def]
    from click.testing import CliRunner

    from dotmd.cli import main

    return CliRunner, main


def _make_search_candidate(ref: str):  # type: ignore[no-untyped-def]
    from dotmd.core.models import SearchCandidate

    return SearchCandidate(
        ref=ref,
        namespace="filesystem",
        descriptor_key="filesystem-mnt",
        source_kind="markdown",
        retrieval_kind="semantic",
        heading_path="# Test Heading",
        snippet="Test snippet content.",
        fused_score=0.85,
        can_read=True,
    )


class TestRefRendering:
    """Search results render the public source ref."""

    def test_renders_ref(self, tmp_path: Path) -> None:
        CliRunner, main = _get_cli()

        from dotmd.core.models import SearchResponse

        ref = "filesystem:/mnt/single/file.md#0"
        stub_result = _make_search_candidate(ref)
        stub_response = SearchResponse(candidates=[stub_result])

        runner = CliRunner()
        settings = make_surreal_runtime_settings(
            data_dir=tmp_path,
            index_dir=tmp_path,
            indexing={"paths": [str(tmp_path)]},
            embedding={"url": "http://localhost:8088"},
            telegram_daemon_socket=None,
        )
        with (
            patch("dotmd.cli.load_settings", return_value=settings),
            patch("dotmd.cli.DotMDService") as service_cls,
        ):
            service_cls.return_value.search.return_value = stub_response
            result = runner.invoke(
                main,
                ["--index-dir", str(tmp_path), "search", "test query"],
            )

        assert result.exit_code == 0, (
            f"Unexpected exit code {result.exit_code}.\nOutput:\n{result.output}"
        )
        assert ref in result.output
        assert "file_paths" not in result.output
        assert "file_path" not in result.output
