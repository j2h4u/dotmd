"""Runner tests for the Phase 40 evaluation harness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from devtools.surreal_eval_runner import EvalRunnerConfig, main, run_eval

from dotmd.search.surreal_contract import AcceptedDifference, CutoverGate
from dotmd.search.surreal_eval import GoldenQueryCategory


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )


def _golden_row(query_id: str, category: GoldenQueryCategory) -> dict[str, object]:
    return {
        "id": query_id,
        "query": f"{category.value} query",
        "category": category.value,
        "primary_surface": "vector",
        "languages": ["en"],
        "relevant": [{"ref": f"filesystem:/mnt/{query_id}.md"}],
        "maybe": [],
        "expected_engines": ["semantic"],
        "broad_query": False,
        "notes": "complete corpus fixture",
    }


def _result_row(query_id: str, category: GoldenQueryCategory) -> dict[str, object]:
    return {
        "query_id": query_id,
        "query": f"{category.value} query",
        "category": category.value,
        "primary_surface": "vector",
        "top_refs": [f"filesystem:/mnt/{query_id}.md"],
        "matched_engines": {f"filesystem:/mnt/{query_id}.md": ["semantic"]},
    }


def _write_complete_passing_fixture(corpus: Path, baseline: Path, candidate: Path) -> None:
    query_ids_by_category = {category: f"sq-{category.value}" for category in GoldenQueryCategory}
    _write_jsonl(
        corpus,
        [_golden_row(query_id, category) for category, query_id in query_ids_by_category.items()],
    )
    result_rows = [
        _result_row(query_id, category) for category, query_id in query_ids_by_category.items()
    ]
    _write_jsonl(baseline, result_rows)
    _write_jsonl(candidate, result_rows)


def test_run_eval_writes_machine_readable_rows_and_markdown_summary(tmp_path: Path) -> None:
    corpus = tmp_path / "golden.jsonl"
    baseline = tmp_path / "baseline.jsonl"
    candidate = tmp_path / "candidate.jsonl"
    acceptance = tmp_path / "acceptance.jsonl"
    output = tmp_path / "diffs.jsonl"
    summary = tmp_path / "summary.md"

    _write_jsonl(
        corpus,
        [
            {
                "id": "sq-001",
                "query": "surreal search",
                "category": GoldenQueryCategory.GRAPH_ENTITY.value,
                "primary_surface": "graph_entity",
                "languages": ["ru", "en"],
                "relevant": [
                    {
                        "ref": "filesystem:/mnt/alpha.md",
                        "contains": "alpha anchor",
                    }
                ],
                "maybe": [{"ref": "filesystem:/mnt/beta.md"}],
                "expected_engines": ["graph", "semantic"],
                "broad_query": False,
                "notes": "graph fixture",
            }
        ],
    )
    _write_jsonl(
        baseline,
        [
            {
                "query_id": "sq-001",
                "query": "surreal search",
                "category": GoldenQueryCategory.GRAPH_ENTITY.value,
                "primary_surface": "graph_entity",
                "top_refs": ["filesystem:/mnt/alpha.md", "filesystem:/mnt/beta.md"],
                "matched_engines": {
                    "filesystem:/mnt/alpha.md": ["graph"],
                    "filesystem:/mnt/beta.md": ["semantic"],
                },
                "snippets_by_ref": {
                    "filesystem:/mnt/alpha.md": "alpha anchor",
                },
            }
        ],
    )
    _write_jsonl(
        candidate,
        [
            {
                "query_id": "sq-001",
                "query": "surreal search",
                "category": GoldenQueryCategory.GRAPH_ENTITY.value,
                "primary_surface": "graph_entity",
                "top_refs": ["filesystem:/mnt/beta.md", "filesystem:/mnt/alpha.md"],
                "matched_engines": {
                    "filesystem:/mnt/alpha.md": ["graph", "semantic"],
                    "filesystem:/mnt/beta.md": ["semantic"],
                },
                "snippets_by_ref": {
                    "filesystem:/mnt/alpha.md": "alpha anchor",
                },
            }
        ],
    )
    _write_jsonl(
        acceptance,
        [
            {
                "query_id": "sq-001",
                "accepted_by": "maintainer",
                "accepted_reason": "Candidate preserves the same accepted set.",
            }
        ],
    )

    result = run_eval(
        EvalRunnerConfig(
            golden_queries=corpus,
            baseline_results=baseline,
            candidate_results=candidate,
            acceptance=acceptance,
            output_jsonl=output,
            summary_markdown=summary,
            require_complete_category_coverage=False,
        )
    )

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert result.exit_code == 0
    assert len(rows) == 1
    assert rows[0]["query_id"] == "sq-001"
    assert rows[0]["category"] == GoldenQueryCategory.GRAPH_ENTITY.value
    assert rows[0]["baseline_refs"] == [
        "filesystem:/mnt/alpha.md",
        "filesystem:/mnt/beta.md",
    ]
    assert rows[0]["candidate_refs"] == [
        "filesystem:/mnt/beta.md",
        "filesystem:/mnt/alpha.md",
    ]
    assert rows[0]["matched_engines"]["filesystem:/mnt/alpha.md"]["baseline"] == ["graph"]
    assert rows[0]["matched_engines"]["filesystem:/mnt/alpha.md"]["candidate"] == [
        "graph",
        "semantic",
    ]
    assert rows[0]["classification"] == AcceptedDifference.HARMLESS_REORDER.value
    assert rows[0]["cutover_gate"] == CutoverGate.ALLOW.value
    assert rows[0]["accepted_by"] == "maintainer"
    assert rows[0]["accepted_reason"] == "Candidate preserves the same accepted set."
    markdown = summary.read_text(encoding="utf-8")
    assert "Accepted semantic changes" in markdown
    assert "sq-001" in markdown


def test_run_eval_keeps_raw_regression_gate_and_fails_on_unresolved_blocker(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "golden.jsonl"
    baseline = tmp_path / "baseline.jsonl"
    candidate = tmp_path / "candidate.jsonl"
    output = tmp_path / "diffs.jsonl"
    summary = tmp_path / "summary.md"

    _write_jsonl(
        corpus,
        [
            {
                "id": "sq-002",
                "query": "bad'; rm -rf /",
                "category": "source-ref",
                "primary_surface": "weighted_full_text",
                "languages": ["en"],
                "relevant": [{"ref": "filesystem:/mnt/relevant.md"}],
                "maybe": [],
                "expected_engines": ["fts"],
                "broad_query": False,
                "notes": "runner consumes JSONL only",
            }
        ],
    )
    _write_jsonl(
        baseline,
        [
            {
                "query_id": "sq-002",
                "query": "bad'; rm -rf /",
                "category": "source-ref",
                "primary_surface": "weighted_full_text",
                "top_refs": ["filesystem:/mnt/relevant.md"],
                "matched_engines": {"filesystem:/mnt/relevant.md": ["fts"]},
            }
        ],
    )
    _write_jsonl(
        candidate,
        [
            {
                "query_id": "sq-002",
                "query": "bad'; rm -rf /",
                "category": "source-ref",
                "primary_surface": "weighted_full_text",
                "top_refs": ["filesystem:/mnt/noise.md"],
                "matched_engines": {"filesystem:/mnt/noise.md": ["semantic"]},
            }
        ],
    )

    result = run_eval(
        EvalRunnerConfig(
            golden_queries=corpus,
            baseline_results=baseline,
            candidate_results=candidate,
            acceptance=None,
            output_jsonl=output,
            summary_markdown=summary,
            require_complete_category_coverage=False,
        )
    )

    row = json.loads(output.read_text(encoding="utf-8").splitlines()[0])
    assert result.exit_code == 1
    assert row["classification"] == AcceptedDifference.REGRESSION.value
    assert row["cutover_gate"] == CutoverGate.BLOCK.value
    assert row["accepted_by"] is None
    assert row["accepted_reason"] is None
    assert "Unresolved blockers" in summary.read_text(encoding="utf-8")


def test_run_eval_rejects_incomplete_corpus_by_default(tmp_path: Path) -> None:
    corpus = tmp_path / "golden.jsonl"
    baseline = tmp_path / "baseline.jsonl"
    candidate = tmp_path / "candidate.jsonl"
    output = tmp_path / "diffs.jsonl"
    summary = tmp_path / "summary.md"

    _write_jsonl(
        corpus,
        [_golden_row("sq-semantic", GoldenQueryCategory.SEMANTIC)],
    )
    _write_jsonl(
        baseline,
        [_result_row("sq-semantic", GoldenQueryCategory.SEMANTIC)],
    )
    _write_jsonl(
        candidate,
        [_result_row("sq-semantic", GoldenQueryCategory.SEMANTIC)],
    )

    with pytest.raises(ValueError, match="golden query corpus missing required categories"):
        run_eval(
            EvalRunnerConfig(
                golden_queries=corpus,
                baseline_results=baseline,
                candidate_results=candidate,
                acceptance=None,
                output_jsonl=output,
                summary_markdown=summary,
            )
        )

    assert not output.exists()
    assert not summary.exists()


def test_main_requires_acceptance_metadata_for_accepted_rows(tmp_path: Path) -> None:
    corpus = tmp_path / "golden.jsonl"
    baseline = tmp_path / "baseline.jsonl"
    candidate = tmp_path / "candidate.jsonl"
    acceptance = tmp_path / "acceptance.jsonl"
    output = tmp_path / "diffs.jsonl"
    summary = tmp_path / "summary.md"

    _write_complete_passing_fixture(corpus, baseline, candidate)
    _write_jsonl(
        acceptance,
        [{"query_id": "sq-semantic", "accepted_by": "maintainer"}],
    )

    with pytest.raises(ValueError, match="accepted_reason"):
        main(
            [
                "--golden-queries",
                str(corpus),
                "--baseline-results",
                str(baseline),
                "--candidate-results",
                str(candidate),
                "--acceptance",
                str(acceptance),
                "--output-jsonl",
                str(output),
                "--summary-markdown",
                str(summary),
            ]
        )


def test_main_wraps_malformed_acceptance_json_with_line_number(tmp_path: Path) -> None:
    corpus = tmp_path / "golden.jsonl"
    baseline = tmp_path / "baseline.jsonl"
    candidate = tmp_path / "candidate.jsonl"
    acceptance = tmp_path / "acceptance.jsonl"
    output = tmp_path / "diffs.jsonl"
    summary = tmp_path / "summary.md"

    _write_complete_passing_fixture(corpus, baseline, candidate)
    acceptance.write_text('{"query_id": "sq-004",\n', encoding="utf-8")

    with pytest.raises(ValueError, match=r"acceptance\.jsonl line 1: invalid JSON"):
        main(
            [
                "--golden-queries",
                str(corpus),
                "--baseline-results",
                str(baseline),
                "--candidate-results",
                str(candidate),
                "--acceptance",
                str(acceptance),
                "--output-jsonl",
                str(output),
                "--summary-markdown",
                str(summary),
            ]
        )
