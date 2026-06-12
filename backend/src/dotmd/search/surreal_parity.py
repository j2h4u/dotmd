"""Parity helpers for the Phase 38 Surreal retrieval spike."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from statistics import median
from typing import Any


class RetrievalFailureCategory(StrEnum):
    """Blocking and informational retrieval parity outcomes."""

    DEFER_FTS_WEIGHTING = "defer: FTS weighting"
    REJECT_RETRIEVAL_PARITY = "reject: retrieval parity"
    REJECT_VECTOR_RECALL_GAP = "reject: vector recall gap"
    REJECT_GRAPH_SEMANTIC_GAP = "reject: graph semantic gap"
    REJECT_HYBRID_RRF_GAP = "reject: hybrid/RRF gap"
    FAIL_UNAVAILABLE_SCALE_EVIDENCE = "fail: unavailable scale evidence"
    INFO_ACCEPTED_DIFFERENCE = "info: accepted difference"


@dataclass(slots=True, frozen=True)
class RetrievalParityCase:
    """One parity comparison case."""

    name: str
    retrieval_kind: str
    query: str
    top_k: int = 10
    blocking: bool = True
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class RetrievalParityResult:
    """Structured parity result for a single retrieval case."""

    case: RetrievalParityCase
    passed: bool
    top_result_match: bool
    top_k_overlap: float
    baseline_ids: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    missing_ids: tuple[str, ...]
    unexpected_ids: tuple[str, ...]
    rank_deltas: dict[str, int]
    score_deltas: dict[str, float]
    failure_category: RetrievalFailureCategory | None = None
    stop_condition: str | None = None
    matched_engines_match: bool | None = None
    notes: tuple[str, ...] = ()

    @property
    def blocking(self) -> bool:
        return self.case.blocking


@dataclass(slots=True, frozen=True)
class RetrievalParityReport:
    """Aggregate retrieval parity report for recommendation gating."""

    results: tuple[RetrievalParityResult, ...]
    scale_gate: dict[str, Any] | None = None

    @property
    def passed(self) -> bool:
        if any(result.blocking and not result.passed for result in self.results):
            return False
        if self.scale_gate is not None and not bool(self.scale_gate.get("passed", False)):
            return False
        return True

    @property
    def blocking_failure_categories(self) -> tuple[RetrievalFailureCategory, ...]:
        categories: list[RetrievalFailureCategory] = []
        for result in self.results:
            if result.blocking and not result.passed and result.failure_category is not None:
                categories.append(result.failure_category)
        if self.scale_gate is not None:
            category = self.scale_gate.get("failure_category")
            if isinstance(category, RetrievalFailureCategory):
                categories.append(category)
        unique: list[RetrievalFailureCategory] = []
        for category in categories:
            if category not in unique:
                unique.append(category)
        return tuple(unique)

    @property
    def recommendation_gate(self) -> str:
        return "pass" if self.passed else "fail"


def _stable_sort_pairs(results: Sequence[tuple[str, float]]) -> list[tuple[str, float]]:
    return sorted(results, key=lambda item: (-item[1], item[0]))


def _trim_pairs(results: Sequence[tuple[str, float]], top_k: int) -> list[tuple[str, float]]:
    return _stable_sort_pairs(results)[:top_k]


def _ids(results: Sequence[tuple[str, float]]) -> tuple[str, ...]:
    return tuple(chunk_id for chunk_id, _score in results)


def _score_map(results: Sequence[tuple[str, float]]) -> dict[str, float]:
    return {chunk_id: score for chunk_id, score in results}


def _rank_map(results: Sequence[tuple[str, float]]) -> dict[str, int]:
    return {chunk_id: rank for rank, (chunk_id, _score) in enumerate(results, start=1)}


def _top_k_overlap(
    baseline_ids: Sequence[str],
    candidate_ids: Sequence[str],
) -> tuple[float, tuple[str, ...], tuple[str, ...]]:
    baseline_set = set(baseline_ids)
    candidate_set = set(candidate_ids)
    overlap = tuple(sorted(baseline_set & candidate_set))
    missing = tuple(sorted(baseline_set - candidate_set))
    unexpected = tuple(sorted(candidate_set - baseline_set))
    denominator = max(len(baseline_ids), 1)
    return len(overlap) / denominator, missing, unexpected


def _shared_rank_and_score_deltas(
    baseline_results: Sequence[tuple[str, float]],
    candidate_results: Sequence[tuple[str, float]],
) -> tuple[dict[str, int], dict[str, float]]:
    baseline_ranks = _rank_map(baseline_results)
    candidate_ranks = _rank_map(candidate_results)
    baseline_scores = _score_map(baseline_results)
    candidate_scores = _score_map(candidate_results)
    shared_ids = set(baseline_ranks) & set(candidate_ranks)
    rank_deltas = {
        chunk_id: candidate_ranks[chunk_id] - baseline_ranks[chunk_id]
        for chunk_id in sorted(shared_ids)
    }
    score_deltas = {
        chunk_id: candidate_scores[chunk_id] - baseline_scores[chunk_id]
        for chunk_id in sorted(shared_ids)
    }
    return rank_deltas, score_deltas


def _current_weighted_fields(
    mapping: Mapping[str, Sequence[str]] | None,
    chunk_id: str | None,
) -> set[str]:
    if mapping is None or chunk_id is None:
        return set()
    raw = mapping.get(chunk_id, ())
    return {field for field in raw}


def classify_fts_parity_failure(
    *,
    current_top_ids: Sequence[str],
    surreal_top_ids: Sequence[str],
    current_field_hits: Mapping[str, Sequence[str]] | None = None,
    surreal_field_hits: Mapping[str, Sequence[str]] | None = None,
) -> tuple[RetrievalFailureCategory, str]:
    """Classify the likely reason for an FTS parity failure."""

    current_top_id = current_top_ids[0] if current_top_ids else None
    surreal_top_id = surreal_top_ids[0] if surreal_top_ids else None
    current_fields = _current_weighted_fields(current_field_hits, current_top_id)
    surreal_fields = _current_weighted_fields(surreal_field_hits, surreal_top_id)
    weighted_current = bool(current_fields & {"title", "tags"})
    body_only_surreal = bool(surreal_fields) and surreal_fields <= {"body", "text"}

    if weighted_current and body_only_surreal:
        return (
            RetrievalFailureCategory.DEFER_FTS_WEIGHTING,
            "FTS weighting mismatch blocks migrate-ready output until weighted-field parity is proven.",
        )

    return (
        RetrievalFailureCategory.REJECT_RETRIEVAL_PARITY,
        "FTS top-result or visibility regression blocks retrieval parity.",
    )


def compare_fts_results(
    case: RetrievalParityCase,
    current_results: Sequence[tuple[str, float]],
    surreal_results: Sequence[tuple[str, float]],
) -> RetrievalParityResult:
    """Compare current FTS ordering with Surreal FTS ordering."""

    baseline = _trim_pairs(current_results, case.top_k)
    candidate = _trim_pairs(surreal_results, case.top_k)
    baseline_ids = _ids(baseline)
    candidate_ids = _ids(candidate)
    top_result_match = bool(baseline_ids) and baseline_ids[:1] == candidate_ids[:1]
    overlap, missing, unexpected = _top_k_overlap(baseline_ids, candidate_ids)
    passed = top_result_match and overlap == 1.0
    rank_deltas, score_deltas = _shared_rank_and_score_deltas(baseline, candidate)

    failure_category = None
    stop_condition = None
    if not passed:
        failure_category, stop_condition = classify_fts_parity_failure(
            current_top_ids=baseline_ids,
            surreal_top_ids=candidate_ids,
            current_field_hits=case.metadata.get("current_field_hits"),  # type: ignore[arg-type]
            surreal_field_hits=case.metadata.get("surreal_field_hits"),  # type: ignore[arg-type]
        )

    return RetrievalParityResult(
        case=case,
        passed=passed,
        top_result_match=top_result_match,
        top_k_overlap=overlap,
        baseline_ids=baseline_ids,
        candidate_ids=candidate_ids,
        missing_ids=missing,
        unexpected_ids=unexpected,
        rank_deltas=rank_deltas,
        score_deltas=score_deltas,
        failure_category=failure_category,
        stop_condition=stop_condition,
    )


def compare_vector_results(
    case: RetrievalParityCase,
    current_results: Sequence[tuple[str, float]],
    surreal_results: Sequence[tuple[str, float]],
) -> RetrievalParityResult:
    """Compare vector search top hits and overlap."""

    baseline = _trim_pairs(current_results, case.top_k)
    candidate = _trim_pairs(surreal_results, case.top_k)
    baseline_ids = _ids(baseline)
    candidate_ids = _ids(candidate)
    top_result_match = bool(baseline_ids) and baseline_ids[:1] == candidate_ids[:1]
    overlap, missing, unexpected = _top_k_overlap(baseline_ids, candidate_ids)
    passed = top_result_match and overlap >= 0.8
    rank_deltas, score_deltas = _shared_rank_and_score_deltas(baseline, candidate)

    return RetrievalParityResult(
        case=case,
        passed=passed,
        top_result_match=top_result_match,
        top_k_overlap=overlap,
        baseline_ids=baseline_ids,
        candidate_ids=candidate_ids,
        missing_ids=missing,
        unexpected_ids=unexpected,
        rank_deltas=rank_deltas,
        score_deltas=score_deltas,
        failure_category=None if passed else RetrievalFailureCategory.REJECT_VECTOR_RECALL_GAP,
        stop_condition=(
            None
            if passed
            else "Vector recall gap blocks migrate-ready output until top hit and overlap thresholds recover."
        ),
    )


def _normalize_graph_related_sections(
    related_rows: Sequence[tuple[str, str, float]],
) -> list[tuple[str, str, float]]:
    normalized = [
        (str(chunk_id), str(relation_type), float(weight))
        for chunk_id, relation_type, weight in related_rows
    ]
    return sorted(normalized, key=lambda item: (item[0], item[1], item[2]))


def _normalize_surreal_relation_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    seed_chunk_id: str | None,
) -> list[tuple[str, str, float]]:
    normalized: list[tuple[str, str, float]] = []
    for row in rows:
        source_id = row.get("source_id")
        relation_type = row.get("relation_type")
        weight = row.get("weight", 1.0)
        if not isinstance(source_id, str) or not isinstance(relation_type, str):
            continue
        if seed_chunk_id is not None and source_id == seed_chunk_id:
            continue
        if relation_type not in {"MENTIONS", "HAS_TAG", "TAGGED"}:
            continue
        normalized.append(
            (
                source_id,
                "HAS_TAG" if relation_type == "TAGGED" else relation_type,
                float(weight),
            )
        )
    return sorted(normalized, key=lambda item: (item[0], item[1], item[2]))


def compare_graph_direct_results(
    case: RetrievalParityCase,
    current_results: Sequence[tuple[str, str, float]],
    surreal_results: Sequence[Mapping[str, object]] | Sequence[tuple[str, str, float]],
    *,
    seed_chunk_id: str | None = None,
) -> RetrievalParityResult:
    """Compare bounded graph-direct related-section results."""

    baseline_rows = _normalize_graph_related_sections(current_results)[: case.top_k]
    if surreal_results and isinstance(surreal_results[0], Mapping):  # type: ignore[index]
        candidate_rows = _normalize_surreal_relation_rows(
            surreal_results,  # type: ignore[arg-type]
            seed_chunk_id=seed_chunk_id,
        )[: case.top_k]
    else:
        candidate_rows = _normalize_graph_related_sections(  # type: ignore[arg-type]
            surreal_results,  # type: ignore[arg-type]
        )[: case.top_k]

    baseline = [(chunk_id, weight) for chunk_id, _relation_type, weight in baseline_rows]
    candidate = [(chunk_id, weight) for chunk_id, _relation_type, weight in candidate_rows]
    baseline_ids = tuple(chunk_id for chunk_id, _relation_type, _weight in baseline_rows)
    candidate_ids = tuple(chunk_id for chunk_id, _relation_type, _weight in candidate_rows)
    overlap, missing, unexpected = _top_k_overlap(baseline_ids, candidate_ids)
    top_result_match = bool(baseline_ids) and baseline_ids[:1] == candidate_ids[:1]
    passed = baseline_rows == candidate_rows
    rank_deltas, score_deltas = _shared_rank_and_score_deltas(baseline, candidate)

    notes: tuple[str, ...] = ()
    if baseline_rows != candidate_rows:
        notes = (
            f"baseline={baseline_rows}",
            f"candidate={candidate_rows}",
        )

    return RetrievalParityResult(
        case=case,
        passed=passed,
        top_result_match=top_result_match,
        top_k_overlap=overlap,
        baseline_ids=baseline_ids,
        candidate_ids=candidate_ids,
        missing_ids=missing,
        unexpected_ids=unexpected,
        rank_deltas=rank_deltas,
        score_deltas=score_deltas,
        failure_category=None if passed else RetrievalFailureCategory.REJECT_GRAPH_SEMANTIC_GAP,
        stop_condition=(
            None
            if passed
            else "Graph semantic gap blocks migrate-ready output until bounded related-section semantics match."
        ),
        notes=notes,
    )


def _matched_engine_map(
    engine_results: Mapping[str, Sequence[tuple[str, float]]],
    ids: Sequence[str],
) -> dict[str, tuple[str, ...]]:
    matched: dict[str, tuple[str, ...]] = {}
    for chunk_id in ids:
        engines = sorted(
            engine
            for engine, results in engine_results.items()
            if any(result_id == chunk_id for result_id, _score in results)
        )
        matched[chunk_id] = tuple(engines)
    return matched


def compare_hybrid_results(
    case: RetrievalParityCase,
    current_fused: Sequence[tuple[str, float]],
    surreal_fused: Sequence[tuple[str, float]],
    *,
    current_engine_hits: Mapping[str, Sequence[tuple[str, float]]],
    surreal_engine_hits: Mapping[str, Sequence[tuple[str, float]]],
) -> RetrievalParityResult:
    """Compare app-side hybrid fusion outputs with deterministic tie handling."""

    baseline = _trim_pairs(current_fused, case.top_k)
    candidate = _trim_pairs(surreal_fused, case.top_k)
    baseline_ids = _ids(baseline)
    candidate_ids = _ids(candidate)
    overlap, missing, unexpected = _top_k_overlap(baseline_ids, candidate_ids)
    top_result_match = bool(baseline_ids) and baseline_ids[:1] == candidate_ids[:1]
    baseline_engines = _matched_engine_map(current_engine_hits, baseline_ids)
    candidate_engines = _matched_engine_map(surreal_engine_hits, candidate_ids)
    shared_ids = set(baseline_ids) & set(candidate_ids)
    matched_engines_match = all(
        baseline_engines.get(chunk_id) == candidate_engines.get(chunk_id)
        for chunk_id in shared_ids
    )
    passed = top_result_match and overlap == 1.0 and matched_engines_match
    rank_deltas, score_deltas = _shared_rank_and_score_deltas(baseline, candidate)

    return RetrievalParityResult(
        case=case,
        passed=passed,
        top_result_match=top_result_match,
        top_k_overlap=overlap,
        baseline_ids=baseline_ids,
        candidate_ids=candidate_ids,
        missing_ids=missing,
        unexpected_ids=unexpected,
        rank_deltas=rank_deltas,
        score_deltas=score_deltas,
        failure_category=None if passed else RetrievalFailureCategory.REJECT_HYBRID_RRF_GAP,
        stop_condition=(
            None
            if passed
            else "Hybrid/RRF gap blocks migrate-ready output until fused ordering and engine attribution match."
        ),
        matched_engines_match=matched_engines_match,
    )


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("values must not be empty")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile
    lower_index = int(rank)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = rank - lower_index
    lower = ordered[lower_index]
    upper = ordered[upper_index]
    return lower + (upper - lower) * fraction


def evaluate_surreal_scale_gate(
    *,
    record_counts: Mapping[str, int] | None,
    hnsw_build_seconds: float | None,
    surrealkv_file_size_bytes: int | None,
    query_latencies_ms: Sequence[float] | None,
    representative: bool,
) -> dict[str, Any]:
    """Evaluate whether scale evidence is complete enough for migration gating."""

    latency_p50 = None
    latency_p95 = None
    if query_latencies_ms:
        latencies = [float(value) for value in query_latencies_ms]
        latency_p50 = median(latencies)
        latency_p95 = _percentile(latencies, 0.95)

    missing: list[str] = []
    if not record_counts:
        missing.append("record count")
    if hnsw_build_seconds is None:
        missing.append("HNSW build time")
    if surrealkv_file_size_bytes is None:
        missing.append("SurrealKV file size")
    if not query_latencies_ms:
        missing.append("query latency")
    if not representative:
        missing.append("representative corpus flag")

    if missing:
        return {
            "passed": False,
            "failure_category": RetrievalFailureCategory.FAIL_UNAVAILABLE_SCALE_EVIDENCE,
            "recommendation_gate": "fail",
            "missing": tuple(missing),
            "record_counts": dict(record_counts or {}),
            "hnsw_build_seconds": hnsw_build_seconds,
            "surrealkv_file_size_bytes": surrealkv_file_size_bytes,
            "query_latency_p50_ms": latency_p50,
            "query_latency_p95_ms": latency_p95,
        }

    return {
        "passed": True,
        "failure_category": None,
        "recommendation_gate": "pass",
        "missing": (),
        "record_counts": dict(record_counts),
        "hnsw_build_seconds": float(hnsw_build_seconds),
        "surrealkv_file_size_bytes": int(surrealkv_file_size_bytes),
        "query_latency_p50_ms": latency_p50,
        "query_latency_p95_ms": latency_p95,
    }


class SurrealRetrievalParityHarness:
    """Run parity cases against current-stack and Surreal-stack callables."""

    def __init__(
        self,
        *,
        current_stack: Mapping[str, Callable[[RetrievalParityCase], object]],
        surreal_stack: Mapping[str, Callable[[RetrievalParityCase], object]],
    ) -> None:
        self._current_stack = dict(current_stack)
        self._surreal_stack = dict(surreal_stack)

    def run_case(self, case: RetrievalParityCase) -> RetrievalParityResult:
        current = self._call(self._current_stack, case)
        surreal = self._call(self._surreal_stack, case)

        if case.retrieval_kind == "fts":
            return compare_fts_results(case, current, surreal)  # type: ignore[arg-type]
        if case.retrieval_kind == "vector":
            return compare_vector_results(case, current, surreal)  # type: ignore[arg-type]
        if case.retrieval_kind == "graph-direct":
            return compare_graph_direct_results(  # type: ignore[arg-type]
                case,
                current,
                surreal,
                seed_chunk_id=case.metadata.get("seed_chunk_id"),  # type: ignore[arg-type]
            )
        if case.retrieval_kind == "hybrid":
            baseline_fused, baseline_engine_hits = self._unpack_hybrid_payload(current)
            candidate_fused, candidate_engine_hits = self._unpack_hybrid_payload(surreal)
            return compare_hybrid_results(
                case,
                baseline_fused,
                candidate_fused,
                current_engine_hits=baseline_engine_hits,
                surreal_engine_hits=candidate_engine_hits,
            )
        raise ValueError(f"unsupported retrieval_kind={case.retrieval_kind!r}")

    def run(
        self,
        cases: Sequence[RetrievalParityCase],
        *,
        scale_gate: dict[str, Any] | None = None,
    ) -> RetrievalParityReport:
        return RetrievalParityReport(
            results=tuple(self.run_case(case) for case in cases),
            scale_gate=scale_gate,
        )

    @staticmethod
    def _call(
        call_map: Mapping[str, Callable[[RetrievalParityCase], object]],
        case: RetrievalParityCase,
    ) -> object:
        try:
            callback = call_map[case.retrieval_kind]
        except KeyError as exc:
            raise ValueError(
                f"missing callable for retrieval_kind={case.retrieval_kind!r}"
            ) from exc
        return callback(case)

    @staticmethod
    def _unpack_hybrid_payload(
        payload: object,
    ) -> tuple[list[tuple[str, float]], dict[str, list[tuple[str, float]]]]:
        if isinstance(payload, Mapping):
            fused = payload.get("fused")
            engine_results = payload.get("engine_results", payload.get("engine_hits"))
            if isinstance(fused, Sequence) and isinstance(engine_results, Mapping):
                return list(fused), {
                    str(engine): list(results)  # type: ignore[arg-type]
                    for engine, results in engine_results.items()
                }

        if (
            isinstance(payload, tuple)
            and len(payload) == 2
            and isinstance(payload[0], Sequence)
            and isinstance(payload[1], Mapping)
        ):
            return list(payload[0]), {
                str(engine): list(results)  # type: ignore[arg-type]
                for engine, results in payload[1].items()
            }

        raise TypeError(
            "hybrid payload must be {'fused': [...], 'engine_results': {...}} or a matching tuple"
        )


__all__ = [
    "RetrievalFailureCategory",
    "RetrievalParityCase",
    "RetrievalParityResult",
    "RetrievalParityReport",
    "SurrealRetrievalParityHarness",
    "classify_fts_parity_failure",
    "compare_fts_results",
    "compare_vector_results",
    "compare_graph_direct_results",
    "compare_hybrid_results",
    "evaluate_surreal_scale_gate",
]
