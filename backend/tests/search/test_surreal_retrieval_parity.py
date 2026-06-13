"""Retrieval parity tests for the Phase 38 Surreal prototype."""

from __future__ import annotations

from collections.abc import Callable

from dotmd.search.surreal_parity import (
    RetrievalFailureCategory,
    RetrievalParityCase,
    RetrievalParityReport,
    SurrealRetrievalParityHarness,
    classify_fts_parity_failure,
    compare_fts_results,
    compare_graph_direct_results,
    compare_hybrid_results,
    compare_vector_results,
    evaluate_surreal_scale_gate,
)


def _make_case(
    *,
    name: str,
    retrieval_kind: str,
    query: str = "surreal search",
    top_k: int = 10,
    blocking: bool = True,
    metadata: dict[str, object] | None = None,
) -> RetrievalParityCase:
    return RetrievalParityCase(
        name=name,
        retrieval_kind=retrieval_kind,
        query=query,
        top_k=top_k,
        blocking=blocking,
        metadata=metadata or {},
    )


class TestParityComparators:
    """Behavior-level retrieval parity checks."""

    def test_fts_parity_matches_top_result_and_top3_membership(self) -> None:
        case = _make_case(
            name="fts-bilingual-title-tag-body",
            retrieval_kind="fts",
            top_k=3,
        )

        current_results = [
            ("chunk:title:ru", 15.0),
            ("chunk:tags:en", 13.0),
            ("chunk:body:mixed", 10.0),
            ("chunk:extra", 6.0),
        ]
        surreal_results = [
            ("chunk:title:ru", 1.50),
            ("chunk:tags:en", 1.30),
            ("chunk:body:mixed", 1.00),
            ("chunk:other", 0.60),
        ]

        result = compare_fts_results(case, current_results, surreal_results)

        assert result.passed is True
        assert result.top_result_match is True
        assert result.top_k_overlap == 1.0
        assert result.missing_ids == ()
        assert result.failure_category is None

    def test_fts_weighting_mismatch_is_classified_as_defer_and_blocks_report(self) -> None:
        category, stop_condition = classify_fts_parity_failure(
            current_top_ids=("chunk:title", "chunk:tags", "chunk:body"),
            surreal_top_ids=("chunk:body", "chunk:title", "chunk:tags"),
            current_field_hits={
                "chunk:title": ("title",),
                "chunk:tags": ("tags",),
            },
            surreal_field_hits={
                "chunk:body": ("body",),
                "chunk:title": ("body",),
                "chunk:tags": ("body",),
            },
        )

        assert category is RetrievalFailureCategory.DEFER_FTS_WEIGHTING
        assert "FTS weighting" in stop_condition

        case = _make_case(
            name="fts-weighting-gap",
            retrieval_kind="fts",
            top_k=3,
            metadata={
                "current_field_hits": {
                    "chunk:title": ("title",),
                    "chunk:tags": ("tags",),
                },
                "surreal_field_hits": {
                    "chunk:body": ("body",),
                    "chunk:title": ("body",),
                    "chunk:tags": ("body",),
                },
            },
        )
        result = compare_fts_results(
            case,
            [
                ("chunk:title", 15.0),
                ("chunk:tags", 13.0),
                ("chunk:body", 10.0),
            ],
            [
                ("chunk:body", 1.50),
                ("chunk:title", 1.30),
                ("chunk:tags", 1.00),
            ],
        )
        report = RetrievalParityReport(results=(result,))

        assert result.passed is False
        assert result.failure_category is RetrievalFailureCategory.DEFER_FTS_WEIGHTING
        assert report.passed is False
        assert report.recommendation_gate == "fail"

    def test_vector_parity_requires_same_top_hit_and_eighty_percent_overlap(self) -> None:
        case = _make_case(
            name="vector-imported-embeddings",
            retrieval_kind="vector",
            top_k=10,
        )

        current_results = [(f"chunk-{index:02d}", 1.0 - index * 0.01) for index in range(10)]
        surreal_results = [*current_results[:8], ("chunk-11", 0.81), ("chunk-12", 0.80)]

        result = compare_vector_results(case, current_results, surreal_results)

        assert result.passed is True
        assert result.top_result_match is True
        assert result.top_k_overlap == 0.8
        assert result.failure_category is None

    def test_graph_direct_parity_normalizes_relation_rows_and_matches_exact_sections(self) -> None:
        case = _make_case(
            name="graph-direct-section-entity-tag",
            retrieval_kind="graph-direct",
            top_k=5,
        )

        current_results = [
            ("chunk-alpha", "MENTIONS", 1.0),
            ("chunk-beta", "HAS_TAG", 0.6),
        ]
        surreal_results = [
            {
                "source_id": "chunk-seed",
                "target_id": "entity:surreal",
                "relation_type": "MENTIONS",
                "weight": 1.0,
            },
            {
                "source_id": "chunk-alpha",
                "target_id": "entity:surreal",
                "relation_type": "MENTIONS",
                "weight": 1.0,
            },
            {
                "source_id": "chunk-beta",
                "target_id": "tag:retrieval",
                "relation_type": "HAS_TAG",
                "weight": 0.6,
            },
        ]

        result = compare_graph_direct_results(
            case,
            current_results,
            surreal_results,
            seed_chunk_id="chunk-seed",
        )

        assert result.passed is True
        assert result.top_result_match is True
        assert result.missing_ids == ()
        assert result.failure_category is None

    def test_graph_direct_parity_respects_top_k_before_comparison(self) -> None:
        case = _make_case(
            name="graph-direct-top-k",
            retrieval_kind="graph-direct",
            top_k=1,
        )

        current_results = [
            ("chunk-alpha", "MENTIONS", 1.0),
        ]
        surreal_results = [
            {
                "source_id": "chunk-alpha",
                "target_id": "entity:surreal",
                "relation_type": "MENTIONS",
                "weight": 1.0,
            },
            {
                "source_id": "chunk-low-rank-extra",
                "target_id": "entity:surreal",
                "relation_type": "MENTIONS",
                "weight": 0.1,
            },
        ]

        result = compare_graph_direct_results(case, current_results, surreal_results)

        assert result.passed is True
        assert result.candidate_ids == ("chunk-alpha",)

    def test_hybrid_parity_preserves_top_hit_and_engine_attribution(self) -> None:
        case = _make_case(
            name="hybrid-rrf-stable",
            retrieval_kind="hybrid",
            top_k=3,
        )

        current_fused = [
            ("chunk-a", 0.0480),
            ("chunk-b", 0.0325),
            ("chunk-c", 0.0310),
        ]
        surreal_fused = [
            ("chunk-a", 0.0910),
            ("chunk-b", 0.0740),
            ("chunk-c", 0.0730),
        ]
        current_engine_hits = {
            "fts": [("chunk-a", 7.0), ("chunk-c", 6.0)],
            "vector": [("chunk-a", 0.99), ("chunk-b", 0.95)],
            "graph": [("chunk-b", 1.0)],
        }
        surreal_engine_hits = {
            "fts": [("chunk-a", 1.7), ("chunk-c", 1.6)],
            "vector": [("chunk-a", 0.99), ("chunk-b", 0.95)],
            "graph": [("chunk-b", 1.0)],
        }

        result = compare_hybrid_results(
            case,
            current_fused,
            surreal_fused,
            current_engine_hits=current_engine_hits,
            surreal_engine_hits=surreal_engine_hits,
        )

        assert result.passed is True
        assert result.top_result_match is True
        assert result.matched_engines_match is True
        assert result.failure_category is None

    def test_hybrid_ties_are_stabilized_by_chunk_id_and_repeatable(self) -> None:
        case = _make_case(
            name="hybrid-tie-break",
            retrieval_kind="hybrid",
            top_k=2,
        )

        current_fused = [("chunk-b", 0.10), ("chunk-a", 0.10)]
        surreal_fused = [("chunk-a", 2.00), ("chunk-b", 2.00)]
        engine_hits = {
            "fts": [("chunk-b", 7.0), ("chunk-a", 7.0)],
            "vector": [("chunk-a", 0.95), ("chunk-b", 0.95)],
        }

        first = compare_hybrid_results(
            case,
            current_fused,
            surreal_fused,
            current_engine_hits=engine_hits,
            surreal_engine_hits=engine_hits,
        )
        second = compare_hybrid_results(
            case,
            current_fused,
            surreal_fused,
            current_engine_hits=engine_hits,
            surreal_engine_hits=engine_hits,
        )

        assert first.passed is True
        assert second.passed is True
        assert first.baseline_ids == ("chunk-a", "chunk-b")
        assert first.candidate_ids == ("chunk-a", "chunk-b")
        assert first.baseline_ids == second.baseline_ids
        assert first.candidate_ids == second.candidate_ids

    def test_regression_result_causes_failing_report_not_warning(self) -> None:
        passing_case = _make_case(name="vector-pass", retrieval_kind="vector")
        failing_case = _make_case(name="vector-fail", retrieval_kind="vector")

        passing_result = compare_vector_results(
            passing_case,
            [("chunk-a", 1.0), ("chunk-b", 0.9)],
            [("chunk-a", 1.0), ("chunk-b", 0.8)],
        )
        failing_result = compare_vector_results(
            failing_case,
            [("chunk-a", 1.0), ("chunk-b", 0.9)],
            [("chunk-z", 1.0), ("chunk-y", 0.9)],
        )

        report = RetrievalParityReport(results=(passing_result, failing_result))

        assert passing_result.passed is True
        assert failing_result.passed is False
        assert failing_result.failure_category is RetrievalFailureCategory.REJECT_VECTOR_RECALL_GAP
        assert report.passed is False
        assert report.blocking_failure_categories == (
            RetrievalFailureCategory.REJECT_VECTOR_RECALL_GAP,
        )


class TestParityHarness:
    """Harness wiring and scale-gate behavior."""

    def test_harness_accepts_current_and_surreal_callables(self) -> None:
        current_calls: dict[str, Callable[[RetrievalParityCase], object]] = {
            "fts": lambda _case: [("chunk:title", 15.0), ("chunk:tags", 13.0)],
            "vector": lambda _case: [("chunk:title", 0.99), ("chunk:tags", 0.95)],
        }
        surreal_calls: dict[str, Callable[[RetrievalParityCase], object]] = {
            "fts": lambda _case: [("chunk:title", 1.50), ("chunk:tags", 1.30)],
            "vector": lambda _case: [("chunk:title", 0.99), ("chunk:tags", 0.95)],
        }

        harness = SurrealRetrievalParityHarness(
            current_stack=current_calls,
            surreal_stack=surreal_calls,
        )

        report = harness.run(
            [
                _make_case(name="fts-callable", retrieval_kind="fts", top_k=2),
                _make_case(name="vector-callable", retrieval_kind="vector", top_k=2),
            ]
        )

        assert len(report.results) == 2
        assert report.passed is True
        assert report.results[0].case.name == "fts-callable"
        assert report.results[1].case.name == "vector-callable"

    def test_scale_gate_fails_when_required_metrics_are_missing(self) -> None:
        scale_gate = evaluate_surreal_scale_gate(
            record_counts={"chunks": 149_739, "embeddings": 149_739},
            hnsw_build_seconds=None,
            surrealkv_file_size_bytes=None,
            query_latencies_ms=[],
            representative=False,
        )

        assert scale_gate["passed"] is False
        assert (
            scale_gate["failure_category"]
            is RetrievalFailureCategory.FAIL_UNAVAILABLE_SCALE_EVIDENCE
        )
        assert scale_gate["recommendation_gate"] == "fail"
