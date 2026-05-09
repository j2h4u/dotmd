"""CLI search result rendering tests."""

from __future__ import annotations

from pathlib import Path


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
        from unittest.mock import patch

        ref = "filesystem:/mnt/single/file.md#0"
        stub_result = _make_search_candidate(ref)

        runner = CliRunner()
        with patch(
            "dotmd.api.service.DotMDService.search",
            return_value=[stub_result],
        ):
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
