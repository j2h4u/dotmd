"""Evaluation harness contract tests for Phase 40."""

from __future__ import annotations

from pathlib import Path

import pytest

from dotmd.search.surreal_contract import AcceptedDifference, CutoverGate, RetrievalSurface
from dotmd.search.surreal_eval import (
    DiffAcceptance,
    EvalResult,
    GoldenQuery,
    GoldenQueryCategory,
    classify_difference,
    load_eval_results,
    load_golden_queries,
    summarize_diffs,
)


def _query(
    *,
    query_id: str = "sq-001",
    category: GoldenQueryCategory = GoldenQueryCategory.TITLE_HEAVY,
    primary_surface: RetrievalSurface = RetrievalSurface.WEIGHTED_FULL_TEXT,
    relevant: list[dict[str, object]] | None = None,
    maybe: list[dict[str, object]] | None = None,
    broad_query: bool = False,
) -> GoldenQuery:
    return GoldenQuery(
        id=query_id,
        query="surreal search",
        category=category,
        primary_surface=primary_surface,
        languages=("en",),
        relevant=tuple(relevant or ({"ref": "filesystem:/mnt/relevant.md"},)),
        maybe=tuple(maybe or ()),
        expected_engines=("fts",),
        broad_query=broad_query,
        notes="fixture",
    )


def _result(
    *,
    query_id: str = "sq-001",
    category: GoldenQueryCategory = GoldenQueryCategory.TITLE_HEAVY,
    primary_surface: RetrievalSurface = RetrievalSurface.WEIGHTED_FULL_TEXT,
    top_refs: tuple[str, ...],
    matched_engines: dict[str, tuple[str, ...]] | None = None,
    snippets_by_ref: dict[str, str] | None = None,
    read_evidence_by_ref: dict[str, str] | None = None,
    unreadable_refs: tuple[str, ...] = (),
) -> EvalResult:
    return EvalResult(
        query_id=query_id,
        query="surreal search",
        category=category,
        primary_surface=primary_surface,
        top_refs=top_refs,
        matched_engines=matched_engines or {},
        snippets_by_ref=snippets_by_ref or {},
        read_evidence_by_ref=read_evidence_by_ref or {},
        unreadable_refs=frozenset(unreadable_refs),
    )


def test_load_golden_queries_rejects_duplicate_ids_and_unknown_categories(
    tmp_path: Path,
) -> None:
    corpus = tmp_path / "golden.jsonl"
    corpus.write_text(
        "\n".join(
            [
                (
                    '{"id":"sq-001","query":"one","category":"title-heavy",'
                    '"primary_surface":"weighted_full_text","languages":["en"],'
                    '"relevant":[{"ref":"filesystem:/mnt/a.md"}],'
                    '"maybe":[],"expected_engines":["fts"],"broad_query":false,"notes":"ok"}'
                ),
                (
                    '{"id":"sq-001","query":"two","category":"not-a-category",'
                    '"primary_surface":"weighted_full_text","languages":["en"],'
                    '"relevant":[{"ref":"filesystem:/mnt/b.md"}],'
                    '"maybe":[],"expected_engines":["fts"],"broad_query":false,"notes":"bad"}'
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="line 2|duplicate|unknown"):
        load_golden_queries(corpus)


def test_load_golden_queries_rejects_malformed_collection_fields(tmp_path: Path) -> None:
    corpus = tmp_path / "golden.jsonl"
    corpus.write_text(
        (
            '{"id":"sq-001","query":"one","category":"title-heavy",'
            '"primary_surface":"weighted_full_text","languages":"en",'
            '"relevant":[{"ref":"filesystem:/mnt/a.md"}],'
            '"maybe":[],"expected_engines":["fts"],"broad_query":false,"notes":"bad"}\n'
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="line 1: languages must be a list"):
        load_golden_queries(corpus)


def test_load_eval_results_rejects_malformed_engine_maps(tmp_path: Path) -> None:
    results = tmp_path / "results.jsonl"
    results.write_text(
        (
            '{"query_id":"sq-001","query":"one","category":"title-heavy",'
            '"primary_surface":"weighted_full_text",'
            '"top_refs":["filesystem:/mnt/a.md"],'
            '"matched_engines":{"filesystem:/mnt/a.md":"fts"}}\n'
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match=r"line 1: matched_engines\['filesystem:/mnt/a.md'\] must be a list",
    ):
        load_eval_results(results)


def test_approved_corpus_file_covers_required_categories() -> None:
    corpus = Path(__file__).resolve().parents[2] / "devtools" / "surreal_golden_queries.jsonl"

    rows = load_golden_queries(corpus)

    required = {category.value for category in GoldenQueryCategory}
    categories = {row.category.value for row in rows}

    assert categories == required
    for category in GoldenQueryCategory:
        assert sum(1 for row in rows if row.category is category) >= 2


def test_classify_difference_marks_gained_relevant_refs_as_improvement() -> None:
    query = _query(
        relevant=[
            {"ref": "filesystem:/mnt/relevant-a.md"},
            {"ref": "filesystem:/mnt/relevant-b.md"},
        ]
    )
    baseline = _result(top_refs=("filesystem:/mnt/relevant-a.md", "filesystem:/mnt/noise.md"))
    candidate = _result(
        top_refs=(
            "filesystem:/mnt/relevant-a.md",
            "filesystem:/mnt/relevant-b.md",
            "filesystem:/mnt/noise.md",
        ),
        matched_engines={
            "filesystem:/mnt/relevant-a.md": ("fts",),
            "filesystem:/mnt/relevant-b.md": ("semantic", "fts"),
        },
    )

    diff = classify_difference(query=query, baseline=baseline, candidate=candidate)

    assert diff.classification is AcceptedDifference.IMPROVEMENT
    assert diff.cutover_gate is CutoverGate.ALLOW
    assert diff.gained_relevant_refs == ("filesystem:/mnt/relevant-b.md",)
    assert diff.lost_relevant_refs == ()
    assert diff.matched_engines["filesystem:/mnt/relevant-b.md"]["candidate"] == [
        "semantic",
        "fts",
    ]


def test_classify_difference_marks_same_accepted_set_as_harmless_reorder() -> None:
    query = _query(
        relevant=[{"ref": "filesystem:/mnt/relevant.md"}],
        maybe=[{"ref": "filesystem:/mnt/maybe.md"}],
    )
    baseline = _result(top_refs=("filesystem:/mnt/relevant.md", "filesystem:/mnt/maybe.md"))
    candidate = _result(top_refs=("filesystem:/mnt/maybe.md", "filesystem:/mnt/relevant.md"))

    diff = classify_difference(query=query, baseline=baseline, candidate=candidate)

    assert diff.classification is AcceptedDifference.HARMLESS_REORDER
    assert diff.cutover_gate is CutoverGate.ALLOW
    assert diff.rank_deltas["filesystem:/mnt/relevant.md"] == 1
    assert diff.rank_deltas["filesystem:/mnt/maybe.md"] == -1


def test_lost_maybe_ref_does_not_appear_as_lost_relevant_ref() -> None:
    query = _query(
        relevant=[{"ref": "filesystem:/mnt/relevant.md"}],
        maybe=[{"ref": "filesystem:/mnt/maybe.md"}],
    )
    baseline = _result(top_refs=("filesystem:/mnt/relevant.md", "filesystem:/mnt/maybe.md"))
    candidate = _result(top_refs=("filesystem:/mnt/relevant.md",))

    diff = classify_difference(query=query, baseline=baseline, candidate=candidate)

    assert diff.classification is AcceptedDifference.REGRESSION
    assert diff.lost_relevant_refs == ()
    assert "lost_approved_ref" in diff.rationale_codes


def test_classify_difference_marks_lost_or_unreadable_relevant_refs_as_regression() -> None:
    query = _query(relevant=[{"ref": "filesystem:/mnt/relevant.md"}])
    baseline = _result(top_refs=("filesystem:/mnt/relevant.md",))
    candidate = _result(
        top_refs=("filesystem:/mnt/relevant.md",),
        unreadable_refs=("filesystem:/mnt/relevant.md",),
    )

    diff = classify_difference(query=query, baseline=baseline, candidate=candidate)

    assert diff.classification is AcceptedDifference.REGRESSION
    assert diff.cutover_gate is CutoverGate.BLOCK
    assert "candidate_unreadable_relevant_ref" in diff.rationale_codes


def test_classify_difference_marks_ambiguous_broad_miss_as_unclear() -> None:
    query = _query(
        category=GoldenQueryCategory.GRAPH_ENTITY,
        primary_surface=RetrievalSurface.GRAPH_ENTITY,
        relevant=[{"ref": "filesystem:/mnt/entity.md"}],
        broad_query=True,
    )
    baseline = _result(
        category=GoldenQueryCategory.GRAPH_ENTITY,
        primary_surface=RetrievalSurface.GRAPH_ENTITY,
        top_refs=("filesystem:/mnt/other-a.md",),
    )
    candidate = _result(
        category=GoldenQueryCategory.GRAPH_ENTITY,
        primary_surface=RetrievalSurface.GRAPH_ENTITY,
        top_refs=("filesystem:/mnt/other-b.md",),
    )

    diff = classify_difference(query=query, baseline=baseline, candidate=candidate)

    assert diff.classification is AcceptedDifference.UNCLEAR
    assert diff.cutover_gate is CutoverGate.REQUIRES_ACCEPTANCE
    assert GoldenQueryCategory.GRAPH_ENTITY.value == "graph-entity"


def test_contains_anchor_only_checks_supplied_result_evidence() -> None:
    query = _query(
        relevant=[
            {
                "ref": "filesystem:/mnt/relevant.md",
                "contains": "needle phrase",
            }
        ]
    )
    baseline = _result(top_refs=("filesystem:/mnt/noise.md",))
    candidate_without_evidence = _result(top_refs=("filesystem:/mnt/relevant.md",))

    diff_without_evidence = classify_difference(
        query=query,
        baseline=baseline,
        candidate=candidate_without_evidence,
    )

    candidate_with_bad_evidence = _result(
        top_refs=("filesystem:/mnt/relevant.md",),
        snippets_by_ref={"filesystem:/mnt/relevant.md": "missing anchor"},
    )
    diff_with_bad_evidence = classify_difference(
        query=query,
        baseline=baseline,
        candidate=candidate_with_bad_evidence,
    )

    assert diff_without_evidence.classification is AcceptedDifference.IMPROVEMENT
    assert diff_with_bad_evidence.classification is AcceptedDifference.UNCLEAR
    assert "contains_evidence_missing" in diff_with_bad_evidence.rationale_codes


def test_summarize_diffs_blocks_unresolved_regressions_and_unclear_rows() -> None:
    unresolved_regression = classify_difference(
        query=_query(query_id="sq-001", relevant=[{"ref": "filesystem:/mnt/relevant.md"}]),
        baseline=_result(
            query_id="sq-001",
            top_refs=("filesystem:/mnt/relevant.md",),
        ),
        candidate=_result(query_id="sq-001", top_refs=("filesystem:/mnt/noise.md",)),
    )
    unresolved_unclear = classify_difference(
        query=_query(
            query_id="sq-002",
            relevant=[{"ref": "filesystem:/mnt/relevant.md"}],
            broad_query=True,
        ),
        baseline=_result(query_id="sq-002", top_refs=("filesystem:/mnt/noise-a.md",)),
        candidate=_result(query_id="sq-002", top_refs=("filesystem:/mnt/noise-b.md",)),
    )

    summary = summarize_diffs([unresolved_regression, unresolved_unclear])

    assert summary.passed is False
    assert summary.unresolved_blocking_query_ids == ("sq-001",)
    assert summary.unresolved_unclear_query_ids == ("sq-002",)


def test_summarize_diffs_treats_explicit_acceptance_as_resolved_without_mutating_raw_gate() -> None:
    regression = classify_difference(
        query=_query(query_id="sq-101", relevant=[{"ref": "filesystem:/mnt/relevant.md"}]),
        baseline=_result(
            query_id="sq-101",
            top_refs=("filesystem:/mnt/relevant.md",),
        ),
        candidate=_result(query_id="sq-101", top_refs=("filesystem:/mnt/noise.md",)),
    )
    unclear = classify_difference(
        query=_query(
            query_id="sq-102",
            relevant=[{"ref": "filesystem:/mnt/relevant.md"}],
            broad_query=True,
        ),
        baseline=_result(query_id="sq-102", top_refs=("filesystem:/mnt/noise-a.md",)),
        candidate=_result(query_id="sq-102", top_refs=("filesystem:/mnt/noise-b.md",)),
    )

    summary = summarize_diffs(
        [regression, unclear],
        acceptances=[
            DiffAcceptance(
                query_id="sq-101",
                accepted_by="maintainer",
                accepted_reason="Intentional Surreal semantic shift",
            ),
            DiffAcceptance(
                query_id="sq-102",
                accepted_by="maintainer",
                accepted_reason="Broad bilingual query remains intentionally ambiguous",
            ),
        ],
    )

    assert regression.classification is AcceptedDifference.REGRESSION
    assert regression.cutover_gate is CutoverGate.BLOCK
    assert unclear.classification is AcceptedDifference.UNCLEAR
    assert unclear.cutover_gate is CutoverGate.REQUIRES_ACCEPTANCE
    assert summary.passed is True
    assert summary.unresolved_blocking_query_ids == ()
    assert summary.unresolved_unclear_query_ids == ()
    assert summary.accepted_query_ids == ("sq-101", "sq-102")
