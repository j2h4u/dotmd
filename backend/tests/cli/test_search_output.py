"""RED test skeletons for CLI search result rendering (P5 — Task 2).

After Phase 16 P5 ships, the CLI printer renders file_paths as:
  Single holder: "[{i}] {path}"
  Multi holder:  "[{i}] {path_0}  (+{N-1} more: {path_1}, ...)"
  — sorted-lex order (Decision #1, locked in CONTEXT.md via Review-LOW-11).

These tests FAIL until P5 (wave 5) updates the CLI renderer.
Imports are deferred so --collect-only works before P5 ships.
"""

from __future__ import annotations

from pathlib import Path


def _get_cli():  # type: ignore[no-untyped-def]
    from click.testing import CliRunner

    from dotmd.cli import main
    return CliRunner, main


def _make_search_result(file_paths: list[Path]):  # type: ignore[no-untyped-def]
    """Build a minimal SearchResult with the given file_paths."""
    from dotmd.core.models import SearchResult
    return SearchResult(
        chunk_id="a" * 64,
        file_paths=file_paths,
        heading_path="# Test Heading",
        snippet="Test snippet content.",
        fused_score=0.85,
    )


class TestSingleHolderRendering:
    """Single-holder result renders without '+N more' suffix."""

    def test_renders_single_holder_no_more_suffix(
        self, tmp_path: Path
    ) -> None:
        """CLI search result with one file_path renders '[i] /path/to/file.md'."""
        CliRunner, main = _get_cli()
        from unittest.mock import patch


        single_path = Path("/some/single/file.md")
        stub_result = _make_search_result([single_path])

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
        assert str(single_path) in result.output, (
            f"Expected path in output: {result.output!r}"
        )
        assert "more" not in result.output.lower(), (
            f"Single-holder result should not have '+N more' suffix: {result.output!r}"
        )


class TestMultiHolderRendering:
    """Multi-holder result renders primary path + '+N more' in sorted-lex order."""

    def test_renders_multi_holder_with_plus_n_suffix(
        self, tmp_path: Path
    ) -> None:
        """CLI search result with 3 file_paths renders '[i] /a/first  (+2 more: /b/..., /z/...)'."""
        CliRunner, main = _get_cli()
        from unittest.mock import patch

        # Paths in unsorted order — renderer must sort lex
        paths = [
            Path("/z/third.md"),
            Path("/a/first.md"),
            Path("/m/second.md"),
        ]
        sorted_paths = sorted(paths)
        stub_result = _make_search_result(paths)

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
        # First path must be the lex-first one
        assert str(sorted_paths[0]) in result.output, (
            f"Expected lex-first path {sorted_paths[0]!r} in output: {result.output!r}"
        )
        # '+2 more' suffix present
        assert "+2 more" in result.output, (
            f"Expected '+2 more' suffix in output: {result.output!r}"
        )
        # Remaining paths in sorted-lex order
        assert str(sorted_paths[1]) in result.output, (
            f"Expected path {sorted_paths[1]!r} in '+N more' list: {result.output!r}"
        )
        assert str(sorted_paths[2]) in result.output, (
            f"Expected path {sorted_paths[2]!r} in '+N more' list: {result.output!r}"
        )
