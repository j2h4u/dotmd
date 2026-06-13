"""CLI runner for the SurrealDB cutover evaluation harness."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotmd.search.surreal_eval import (  # noqa: E402
    DiffAcceptance,
    SurrealEvalDiffRow,
    SurrealEvalSummary,
    classify_difference,
    load_eval_results,
    load_golden_queries,
    summarize_diffs,
)


@dataclass(slots=True, frozen=True)
class EvalRunnerConfig:
    """Filesystem inputs and outputs for one evaluation run."""

    golden_queries: Path
    baseline_results: Path
    candidate_results: Path
    output_jsonl: Path
    summary_markdown: Path
    acceptance: Path | None = None


@dataclass(slots=True, frozen=True)
class EvalRunResult:
    """Structured runner outcome."""

    rows: tuple[SurrealEvalDiffRow, ...]
    summary: SurrealEvalSummary
    exit_code: int


def _load_acceptances(path: Path | None) -> list[DiffAcceptance]:
    if path is None:
        return []
    rows: list[DiffAcceptance] = []
    seen_ids: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"{path} line {line_number}: expected JSON object")
            query_id = str(payload.get("query_id", "")).strip()
            accepted_by = str(payload.get("accepted_by", "")).strip()
            accepted_reason = str(payload.get("accepted_reason", "")).strip()
            if not query_id:
                raise ValueError(f"{path} line {line_number}: query_id is required")
            if query_id in seen_ids:
                raise ValueError(f"{path} line {line_number}: duplicate acceptance for {query_id!r}")
            if not accepted_by:
                raise ValueError(f"{path} line {line_number}: accepted_by is required")
            if not accepted_reason:
                raise ValueError(f"{path} line {line_number}: accepted_reason is required")
            seen_ids.add(query_id)
            rows.append(
                DiffAcceptance(
                    query_id=query_id,
                    accepted_by=accepted_by,
                    accepted_reason=accepted_reason,
                )
            )
    return rows


def _write_jsonl(path: Path, rows: tuple[SurrealEvalDiffRow, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row.to_jsonable(), ensure_ascii=False, sort_keys=True) + "\n")


def _build_summary_markdown(summary: SurrealEvalSummary) -> str:
    lines = [
        "# Surreal Evaluation Summary",
        "",
        "## Classification Counts",
        "",
    ]
    for difference, count in summary.classification_counts.items():
        lines.append(f"- `{difference.value}`: {count}")
    lines.extend(
        [
            "",
            "## Accepted semantic changes",
            "",
        ]
    )
    if summary.accepted_query_ids:
        for query_id in summary.accepted_query_ids:
            lines.append(f"- `{query_id}`")
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Unresolved blockers",
            "",
        ]
    )
    if summary.unresolved_blocking_query_ids:
        for query_id in summary.unresolved_blocking_query_ids:
            lines.append(f"- `{query_id}`")
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Unresolved unclear",
            "",
        ]
    )
    if summary.unresolved_unclear_query_ids:
        for query_id in summary.unresolved_unclear_query_ids:
            lines.append(f"- `{query_id}`")
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Report gate",
            "",
            f"- `passed`: {str(summary.passed).lower()}",
        ]
    )
    return "\n".join(lines) + "\n"


def run_eval(config: EvalRunnerConfig) -> EvalRunResult:
    """Compare baseline and candidate result captures against the golden corpus."""

    golden_queries = load_golden_queries(config.golden_queries)
    baseline_results = {
        row.query_id: row for row in load_eval_results(config.baseline_results)
    }
    candidate_results = {
        row.query_id: row for row in load_eval_results(config.candidate_results)
    }
    acceptances = _load_acceptances(config.acceptance)

    raw_rows: list[SurrealEvalDiffRow] = []
    for query in golden_queries:
        if query.id not in baseline_results:
            raise ValueError(f"missing baseline result for query {query.id!r}")
        if query.id not in candidate_results:
            raise ValueError(f"missing candidate result for query {query.id!r}")
        raw_rows.append(
            classify_difference(
                query=query,
                baseline=baseline_results[query.id],
                candidate=candidate_results[query.id],
            )
        )

    summary = summarize_diffs(raw_rows, acceptances=acceptances)
    _write_jsonl(config.output_jsonl, summary.rows)
    config.summary_markdown.parent.mkdir(parents=True, exist_ok=True)
    config.summary_markdown.write_text(
        _build_summary_markdown(summary),
        encoding="utf-8",
    )
    return EvalRunResult(
        rows=summary.rows,
        summary=summary,
        exit_code=0 if summary.passed else 1,
    )


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser for standalone execution."""

    parser = argparse.ArgumentParser(description="Compare baseline and Surreal result JSONL files.")
    parser.add_argument("--golden-queries", required=True, type=Path)
    parser.add_argument("--baseline-results", required=True, type=Path)
    parser.add_argument("--candidate-results", required=True, type=Path)
    parser.add_argument("--acceptance", type=Path, default=None)
    parser.add_argument("--output-jsonl", required=True, type=Path)
    parser.add_argument("--summary-markdown", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run evaluation, and return the shell exit code."""

    args = build_parser().parse_args(argv)
    result = run_eval(
        EvalRunnerConfig(
            golden_queries=args.golden_queries,
            baseline_results=args.baseline_results,
            candidate_results=args.candidate_results,
            acceptance=args.acceptance,
            output_jsonl=args.output_jsonl,
            summary_markdown=args.summary_markdown,
        )
    )
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
