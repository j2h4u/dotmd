"""Typed evaluation helpers for the SurrealDB cutover quality harness."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from dotmd.search.surreal_contract import (
    AcceptedDifference,
    CutoverGate,
    RetrievalSurface,
    default_surreal_retrieval_contract,
)

JsonObject = dict[str, Any]


class GoldenQueryCategory(StrEnum):
    """Phase 40 golden query categories."""

    TITLE_HEAVY = "title-heavy"
    TAG_HEAVY = "tag-heavy"
    BODY_HEAVY = "body-heavy"
    SEMANTIC = "semantic"
    GRAPH_ENTITY = "graph-entity"
    HYBRID = "hybrid"
    SOURCE_REF = "source-ref"
    MIXED_RU_EN = "mixed-ru-en"


def required_golden_query_categories() -> frozenset[GoldenQueryCategory]:
    """Return the complete required category set for the checked-in corpus."""

    return frozenset(GoldenQueryCategory)


def validate_required_category_coverage(
    queries: list[GoldenQuery] | tuple[GoldenQuery, ...],
    *,
    path: Path | None = None,
) -> None:
    """Reject a golden corpus that cannot exercise every required category."""

    present = {query.category for query in queries}
    missing = required_golden_query_categories() - present
    if not missing:
        return
    prefix = f"{path}: " if path is not None else ""
    missing_names = ", ".join(sorted(category.value for category in missing))
    raise ValueError(f"{prefix}golden query corpus missing required categories: {missing_names}")


@dataclass(slots=True, frozen=True)
class GoldenQuery:
    """One approved golden query row."""

    id: str
    query: str
    category: GoldenQueryCategory
    primary_surface: RetrievalSurface
    languages: tuple[str, ...]
    relevant: tuple[JsonObject, ...]
    maybe: tuple[JsonObject, ...]
    expected_engines: tuple[str, ...]
    broad_query: bool
    notes: str = ""


@dataclass(slots=True, frozen=True)
class EvalResult:
    """Captured baseline or candidate search output for one golden query."""

    query_id: str
    query: str
    category: GoldenQueryCategory
    primary_surface: RetrievalSurface
    top_refs: tuple[str, ...]
    matched_engines: dict[str, tuple[str, ...]]
    snippets_by_ref: dict[str, str] = field(default_factory=dict)
    read_evidence_by_ref: dict[str, str] = field(default_factory=dict)
    unreadable_refs: frozenset[str] = field(default_factory=frozenset)


@dataclass(slots=True, frozen=True)
class DiffAcceptance:
    """Human acceptance metadata for a raw diff row."""

    query_id: str
    accepted_by: str
    accepted_reason: str


@dataclass(slots=True, frozen=True)
class SurrealEvalDiffRow:
    """Machine-readable difference row for one query."""

    query_id: str
    query: str
    category: GoldenQueryCategory
    baseline_refs: tuple[str, ...]
    candidate_refs: tuple[str, ...]
    lost_relevant_refs: tuple[str, ...]
    gained_relevant_refs: tuple[str, ...]
    rank_deltas: dict[str, int]
    matched_engines: dict[str, dict[str, list[str]]]
    classification: AcceptedDifference
    cutover_gate: CutoverGate
    rationale_codes: tuple[str, ...]
    accepted_by: str | None = None
    accepted_reason: str | None = None

    @property
    def accepted(self) -> bool:
        return self.accepted_by is not None and self.accepted_reason is not None

    def with_acceptance(self, acceptance: DiffAcceptance | None) -> SurrealEvalDiffRow:
        """Attach explicit acceptance metadata without mutating raw classification."""

        if acceptance is None:
            return self
        return SurrealEvalDiffRow(
            query_id=self.query_id,
            query=self.query,
            category=self.category,
            baseline_refs=self.baseline_refs,
            candidate_refs=self.candidate_refs,
            lost_relevant_refs=self.lost_relevant_refs,
            gained_relevant_refs=self.gained_relevant_refs,
            rank_deltas=dict(self.rank_deltas),
            matched_engines={
                ref: {"baseline": list(values["baseline"]), "candidate": list(values["candidate"])}
                for ref, values in self.matched_engines.items()
            },
            classification=self.classification,
            cutover_gate=self.cutover_gate,
            rationale_codes=self.rationale_codes,
            accepted_by=acceptance.accepted_by,
            accepted_reason=acceptance.accepted_reason,
        )

    def to_jsonable(self) -> JsonObject:
        """Return a stable JSONL-ready dictionary."""

        return {
            "query_id": self.query_id,
            "query": self.query,
            "category": self.category.value,
            "baseline_refs": list(self.baseline_refs),
            "candidate_refs": list(self.candidate_refs),
            "lost_relevant_refs": list(self.lost_relevant_refs),
            "gained_relevant_refs": list(self.gained_relevant_refs),
            "rank_deltas": dict(self.rank_deltas),
            "matched_engines": self.matched_engines,
            "classification": self.classification.value,
            "cutover_gate": self.cutover_gate.value,
            "rationale_codes": list(self.rationale_codes),
            "accepted_by": self.accepted_by,
            "accepted_reason": self.accepted_reason,
        }


@dataclass(slots=True, frozen=True)
class SurrealEvalSummary:
    """Aggregate cutover summary derived from diff rows."""

    rows: tuple[SurrealEvalDiffRow, ...]
    unresolved_blocking_query_ids: tuple[str, ...]
    unresolved_unclear_query_ids: tuple[str, ...]
    accepted_query_ids: tuple[str, ...]
    classification_counts: dict[AcceptedDifference, int]

    @property
    def passed(self) -> bool:
        return not self.unresolved_blocking_query_ids and not self.unresolved_unclear_query_ids


def _load_jsonl(path: Path) -> list[tuple[int, JsonObject]]:
    rows: list[tuple[int, JsonObject]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path} line {line_number}: invalid JSON") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"{path} line {line_number}: expected JSON object")
            rows.append((line_number, payload))
    return rows


def _parse_category(raw: object, *, path: Path, line_number: int) -> GoldenQueryCategory:
    try:
        return GoldenQueryCategory(str(raw))
    except ValueError as exc:
        raise ValueError(f"{path} line {line_number}: unknown category {raw!r}") from exc


def _parse_surface(raw: object, *, path: Path, line_number: int) -> RetrievalSurface:
    try:
        return RetrievalSurface(str(raw))
    except ValueError as exc:
        raise ValueError(f"{path} line {line_number}: unknown surface {raw!r}") from exc


def _parse_difference(raw: object, *, path: Path, line_number: int) -> AcceptedDifference:
    try:
        return AcceptedDifference(str(raw))
    except ValueError as exc:
        raise ValueError(f"{path} line {line_number}: unknown difference {raw!r}") from exc


def _parse_str_list(raw: object, *, path: Path, line_number: int, field: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"{path} line {line_number}: {field} must be a list")
    return tuple(str(item) for item in raw)


def _parse_str_map(raw: object, *, path: Path, line_number: int, field: str) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} line {line_number}: {field} must be an object")
    return {str(key): str(value) for key, value in raw.items()}


def _parse_engine_map(raw: object, *, path: Path, line_number: int) -> dict[str, tuple[str, ...]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} line {line_number}: matched_engines must be an object")
    engines_by_ref: dict[str, tuple[str, ...]] = {}
    for ref, engines in raw.items():
        if not isinstance(engines, list):
            raise ValueError(
                f"{path} line {line_number}: matched_engines[{str(ref)!r}] must be a list"
            )
        engines_by_ref[str(ref)] = tuple(str(engine) for engine in engines)
    return engines_by_ref


def _parse_label_list(raw: object, *, path: Path, line_number: int) -> tuple[JsonObject, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError(f"{path} line {line_number}: labels must be a list")
    labels: list[JsonObject] = []
    for label in raw:
        if not isinstance(label, dict) or "ref" not in label:
            raise ValueError(f"{path} line {line_number}: each label requires ref")
        normalized = {str(key): value for key, value in label.items()}
        labels.append(normalized)
    return tuple(labels)


def load_golden_queries(path: Path) -> list[GoldenQuery]:
    """Load checked-in or temporary golden query rows."""

    rows: list[GoldenQuery] = []
    seen_ids: set[str] = set()
    for line_number, payload in _load_jsonl(path):
        query_id = str(payload.get("id", "")).strip()
        query = str(payload.get("query", "")).strip()
        if not query_id or not query:
            raise ValueError(f"{path} line {line_number}: id and query are required")
        if query_id in seen_ids:
            raise ValueError(f"{path} line {line_number}: duplicate query id {query_id!r}")
        seen_ids.add(query_id)
        rows.append(
            GoldenQuery(
                id=query_id,
                query=query,
                category=_parse_category(
                    payload.get("category"), path=path, line_number=line_number
                ),
                primary_surface=_parse_surface(
                    payload.get("primary_surface"),
                    path=path,
                    line_number=line_number,
                ),
                languages=_parse_str_list(
                    payload.get("languages"),
                    path=path,
                    line_number=line_number,
                    field="languages",
                ),
                relevant=_parse_label_list(
                    payload.get("relevant"), path=path, line_number=line_number
                ),
                maybe=_parse_label_list(payload.get("maybe"), path=path, line_number=line_number),
                expected_engines=_parse_str_list(
                    payload.get("expected_engines"),
                    path=path,
                    line_number=line_number,
                    field="expected_engines",
                ),
                broad_query=bool(payload.get("broad_query", False)),
                notes=str(payload.get("notes", "")),
            )
        )
    return rows


def load_eval_results(path: Path) -> list[EvalResult]:
    """Load baseline or candidate search output rows."""

    rows: list[EvalResult] = []
    seen_ids: set[str] = set()
    for line_number, payload in _load_jsonl(path):
        query_id = str(payload.get("query_id", "")).strip()
        query = str(payload.get("query", "")).strip()
        if not query_id or not query:
            raise ValueError(f"{path} line {line_number}: query_id and query are required")
        if query_id in seen_ids:
            raise ValueError(f"{path} line {line_number}: duplicate query id {query_id!r}")
        seen_ids.add(query_id)
        if payload.get("classification") is not None:
            _parse_difference(payload.get("classification"), path=path, line_number=line_number)
        category = _parse_category(payload.get("category"), path=path, line_number=line_number)
        primary_surface = _parse_surface(
            payload.get("primary_surface"),
            path=path,
            line_number=line_number,
        )
        top_refs = payload.get("top_refs")
        if not isinstance(top_refs, list):
            raise ValueError(f"{path} line {line_number}: top_refs must be a list")
        matched_engines = _parse_engine_map(
            payload.get("matched_engines"),
            path=path,
            line_number=line_number,
        )
        rows.append(
            EvalResult(
                query_id=query_id,
                query=query,
                category=category,
                primary_surface=primary_surface,
                top_refs=tuple(str(ref) for ref in top_refs),
                matched_engines=matched_engines,
                snippets_by_ref=_parse_str_map(
                    payload.get("snippets_by_ref"),
                    path=path,
                    line_number=line_number,
                    field="snippets_by_ref",
                ),
                read_evidence_by_ref=_parse_str_map(
                    payload.get("read_evidence_by_ref"),
                    path=path,
                    line_number=line_number,
                    field="read_evidence_by_ref",
                ),
                unreadable_refs=frozenset(
                    _parse_str_list(
                        payload.get("unreadable_refs"),
                        path=path,
                        line_number=line_number,
                        field="unreadable_refs",
                    )
                ),
            )
        )
    return rows


def _label_refs(labels: tuple[JsonObject, ...]) -> set[str]:
    return {str(label["ref"]) for label in labels}


def _result_rank_map(result: EvalResult) -> dict[str, int]:
    return {ref: index for index, ref in enumerate(result.top_refs, start=1)}


def _matches_contains_anchor(result: EvalResult, label: JsonObject) -> tuple[bool, bool]:
    ref = str(label["ref"])
    contains = label.get("contains")
    if not contains:
        return True, False
    evidence: list[str] = []
    if ref in result.snippets_by_ref:
        evidence.append(result.snippets_by_ref[ref])
    if ref in result.read_evidence_by_ref:
        evidence.append(result.read_evidence_by_ref[ref])
    if not evidence:
        return True, False
    needle = str(contains)
    return any(needle in text for text in evidence), True


def _matched_approved_refs(
    result: EvalResult, labels: tuple[JsonObject, ...]
) -> tuple[set[str], bool]:
    matched: set[str] = set()
    evidence_failure = False
    top_refs = set(result.top_refs)
    for label in labels:
        ref = str(label["ref"])
        if ref not in top_refs:
            continue
        matches_contains, had_evidence = _matches_contains_anchor(result, label)
        if matches_contains:
            matched.add(ref)
            continue
        if had_evidence:
            evidence_failure = True
    return matched, evidence_failure


def _matched_engines(
    baseline: EvalResult,
    candidate: EvalResult,
) -> dict[str, dict[str, list[str]]]:
    refs = sorted(set(baseline.top_refs) | set(candidate.top_refs))
    return {
        ref: {
            "baseline": list(baseline.matched_engines.get(ref, ())),
            "candidate": list(candidate.matched_engines.get(ref, ())),
        }
        for ref in refs
    }


def classify_difference(
    *,
    query: GoldenQuery,
    baseline: EvalResult,
    candidate: EvalResult,
) -> SurrealEvalDiffRow:
    """Compare one baseline/candidate pair against the approved golden labels."""

    if baseline.query_id != candidate.query_id or baseline.query_id != query.id:
        raise ValueError("query ids must match across golden, baseline, and candidate rows")
    if baseline.category is not candidate.category or baseline.category is not query.category:
        raise ValueError("categories must match across golden, baseline, and candidate rows")
    if (
        baseline.primary_surface is not candidate.primary_surface
        or baseline.primary_surface is not query.primary_surface
    ):
        raise ValueError("surfaces must match across golden, baseline, and candidate rows")

    approved_labels = query.relevant + query.maybe
    approved_refs = _label_refs(approved_labels)
    baseline_matched, baseline_evidence_failure = _matched_approved_refs(baseline, approved_labels)
    candidate_matched, candidate_evidence_failure = _matched_approved_refs(
        candidate, approved_labels
    )

    baseline_relevant, _ = _matched_approved_refs(baseline, query.relevant)
    candidate_relevant, _ = _matched_approved_refs(candidate, query.relevant)

    baseline_rank_map = _result_rank_map(baseline)
    candidate_rank_map = _result_rank_map(candidate)
    shared_refs = sorted(set(baseline_rank_map) & set(candidate_rank_map))
    rank_deltas = {ref: candidate_rank_map[ref] - baseline_rank_map[ref] for ref in shared_refs}

    rationale_codes: list[str] = []
    classification: AcceptedDifference

    unreadable_approved = approved_refs & candidate.unreadable_refs
    lost_approved = tuple(sorted(baseline_matched - candidate_matched))
    lost_relevant = tuple(sorted(baseline_relevant - candidate_relevant))
    gained_relevant = tuple(sorted(candidate_relevant - baseline_relevant))

    if unreadable_approved:
        rationale_codes.append("candidate_unreadable_relevant_ref")
        classification = AcceptedDifference.REGRESSION
    elif lost_approved:
        rationale_codes.append("lost_approved_ref")
        classification = AcceptedDifference.REGRESSION
    elif candidate_evidence_failure or baseline_evidence_failure:
        rationale_codes.append("contains_evidence_missing")
        classification = AcceptedDifference.UNCLEAR
    elif gained_relevant:
        rationale_codes.append("gained_relevant_ref")
        classification = AcceptedDifference.IMPROVEMENT
    elif candidate_matched == baseline_matched and candidate_matched:
        rationale_codes.append("same_accepted_set")
        classification = AcceptedDifference.HARMLESS_REORDER
    elif not candidate_matched and not baseline_matched and query.broad_query:
        rationale_codes.append("broad_query_miss")
        classification = AcceptedDifference.UNCLEAR
    elif not candidate_matched and not baseline_matched:
        rationale_codes.append("no_approved_refs_found")
        classification = AcceptedDifference.UNCLEAR
    else:
        rationale_codes.append("ambiguous_difference")
        classification = AcceptedDifference.UNCLEAR

    contract = default_surreal_retrieval_contract()
    return SurrealEvalDiffRow(
        query_id=query.id,
        query=query.query,
        category=query.category,
        baseline_refs=baseline.top_refs,
        candidate_refs=candidate.top_refs,
        lost_relevant_refs=lost_relevant,
        gained_relevant_refs=gained_relevant,
        rank_deltas=rank_deltas,
        matched_engines=_matched_engines(baseline, candidate),
        classification=classification,
        cutover_gate=contract.cutover_gate_for(classification),
        rationale_codes=tuple(rationale_codes),
    )


def summarize_diffs(
    rows: list[SurrealEvalDiffRow],
    *,
    acceptances: list[DiffAcceptance] | None = None,
) -> SurrealEvalSummary:
    """Apply acceptance metadata and derive aggregate gate state."""

    acceptance_map: dict[str, DiffAcceptance] = {}
    for acceptance in acceptances or []:
        if not acceptance.accepted_by:
            raise ValueError("accepted_by is required for accepted rows")
        if not acceptance.accepted_reason:
            raise ValueError("accepted_reason is required for accepted rows")
        if acceptance.query_id in acceptance_map:
            raise ValueError(f"duplicate acceptance for query {acceptance.query_id!r}")
        acceptance_map[acceptance.query_id] = acceptance

    resolved_rows = tuple(row.with_acceptance(acceptance_map.get(row.query_id)) for row in rows)
    unresolved_blocking = tuple(
        row.query_id
        for row in resolved_rows
        if row.cutover_gate is CutoverGate.BLOCK and not row.accepted
    )
    unresolved_unclear = tuple(
        row.query_id
        for row in resolved_rows
        if row.cutover_gate is CutoverGate.REQUIRES_ACCEPTANCE and not row.accepted
    )
    accepted_query_ids = tuple(row.query_id for row in resolved_rows if row.accepted)
    classification_counts: dict[AcceptedDifference, int] = dict.fromkeys(AcceptedDifference, 0)
    for row in resolved_rows:
        classification_counts[row.classification] += 1

    return SurrealEvalSummary(
        rows=resolved_rows,
        unresolved_blocking_query_ids=unresolved_blocking,
        unresolved_unclear_query_ids=unresolved_unclear,
        accepted_query_ids=accepted_query_ids,
        classification_counts=classification_counts,
    )
