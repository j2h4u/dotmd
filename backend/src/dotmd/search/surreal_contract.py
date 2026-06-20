"""SurrealDB-native retrieval contract vocabulary.

This module deliberately contains policy terms, not backend implementation.
Phase 40+ evaluators can import it without constructing storage or embedding
clients.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class RetrievalSurface(StrEnum):
    """Surfaces the SurrealDB-native backend must provide."""

    WEIGHTED_FULL_TEXT = "weighted_full_text"
    VECTOR = "vector"
    GRAPH_ENTITY = "graph_entity"
    HYBRID_FUSION = "hybrid_fusion"
    RERANKER_INPUT = "reranker_input"


class AcceptedDifference(StrEnum):
    """How comparison results are classified."""

    IMPROVEMENT = "improvement"
    HARMLESS_REORDER = "harmless_reorder"
    REGRESSION = "regression"
    UNCLEAR = "unclear"


class CutoverGate(StrEnum):
    """Cutover behavior for a classified retrieval difference."""

    ALLOW = "allow"
    BLOCK = "block"
    REQUIRES_ACCEPTANCE = "requires_acceptance"


class MigrationReusePolicy(StrEnum):
    """Default posture for existing stored data during the SurrealDB cutover."""

    PRESERVE_WHERE_PRACTICAL = "preserve_where_practical"


@dataclass(slots=True, frozen=True)
class SurrealRetrievalContract:
    """Policy contract shared by SurrealDB evaluation and cutover phases."""

    surfaces: frozenset[RetrievalSurface]
    accepted_differences: frozenset[AcceptedDifference]
    cutover_gates: dict[AcceptedDifference, CutoverGate]
    migration_reuse_policy: MigrationReusePolicy
    reuse_targets: frozenset[str]
    old_stack_role: str
    exact_rank_parity_required: bool
    product_compatibility_target: bool
    runtime_fallback_backend_allowed: bool
    productized_compatibility_shims_allowed: bool
    default_rechunk: bool
    default_reembed: bool
    default_reextract_entities: bool
    notes: tuple[str, ...] = field(default_factory=tuple)

    def cutover_gate_for(self, difference: AcceptedDifference) -> CutoverGate:
        """Return the default cutover gate for a classified difference."""

        return self.cutover_gates[difference]


def default_surreal_retrieval_contract() -> SurrealRetrievalContract:
    """Return dotMD's default v1.8 SurrealDB-native retrieval contract."""

    return SurrealRetrievalContract(
        surfaces=frozenset(
            {
                RetrievalSurface.WEIGHTED_FULL_TEXT,
                RetrievalSurface.VECTOR,
                RetrievalSurface.GRAPH_ENTITY,
                RetrievalSurface.HYBRID_FUSION,
                RetrievalSurface.RERANKER_INPUT,
            }
        ),
        accepted_differences=frozenset(
            {
                AcceptedDifference.IMPROVEMENT,
                AcceptedDifference.HARMLESS_REORDER,
                AcceptedDifference.REGRESSION,
                AcceptedDifference.UNCLEAR,
            }
        ),
        cutover_gates={
            AcceptedDifference.IMPROVEMENT: CutoverGate.ALLOW,
            AcceptedDifference.HARMLESS_REORDER: CutoverGate.ALLOW,
            AcceptedDifference.REGRESSION: CutoverGate.BLOCK,
            AcceptedDifference.UNCLEAR: CutoverGate.REQUIRES_ACCEPTANCE,
        },
        migration_reuse_policy=MigrationReusePolicy.PRESERVE_WHERE_PRACTICAL,
        reuse_targets=frozenset(
            {
                "chunks",
                "embeddings",
                "source_refs",
                "graph_relations",
                "feedback",
                "cursors",
                "checkpoints",
            }
        ),
        old_stack_role="historical comparison",
        exact_rank_parity_required=False,
        product_compatibility_target=False,
        runtime_fallback_backend_allowed=False,
        productized_compatibility_shims_allowed=False,
        default_rechunk=False,
        default_reembed=False,
        default_reextract_entities=False,
        notes=(
            "Historical comparison output is evidence for quality evaluation, not a product compatibility target.",
            "Existing stored data should be reused unless a later phase proves recomputation is required.",
            "Production storage and retrieval paths are SurrealDB-only.",
        ),
    )
