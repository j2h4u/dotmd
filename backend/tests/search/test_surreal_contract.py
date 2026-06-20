"""SurrealDB-native retrieval contract invariants."""

from __future__ import annotations

from dotmd.search.surreal_contract import (
    AcceptedDifference,
    CutoverGate,
    MigrationReusePolicy,
    RetrievalSurface,
    default_surreal_retrieval_contract,
)


def test_contract_covers_required_retrieval_surfaces() -> None:
    contract = default_surreal_retrieval_contract()

    assert contract.surfaces == frozenset(
        {
            RetrievalSurface.WEIGHTED_FULL_TEXT,
            RetrievalSurface.VECTOR,
            RetrievalSurface.GRAPH_ENTITY,
            RetrievalSurface.HYBRID_FUSION,
            RetrievalSurface.RERANKER_INPUT,
        }
    )


def test_contract_uses_quality_differences_not_rank_parity() -> None:
    contract = default_surreal_retrieval_contract()

    assert contract.old_stack_role == "historical comparison"
    assert contract.exact_rank_parity_required is False
    assert contract.product_compatibility_target is False
    assert contract.accepted_differences == frozenset(
        {
            AcceptedDifference.IMPROVEMENT,
            AcceptedDifference.HARMLESS_REORDER,
            AcceptedDifference.REGRESSION,
            AcceptedDifference.UNCLEAR,
        }
    )


def test_cutover_gate_blocks_regressions_and_requires_unclear_acceptance() -> None:
    contract = default_surreal_retrieval_contract()

    assert contract.cutover_gate_for(AcceptedDifference.IMPROVEMENT) is CutoverGate.ALLOW
    assert contract.cutover_gate_for(AcceptedDifference.HARMLESS_REORDER) is CutoverGate.ALLOW
    assert contract.cutover_gate_for(AcceptedDifference.REGRESSION) is CutoverGate.BLOCK
    assert contract.cutover_gate_for(AcceptedDifference.UNCLEAR) is CutoverGate.REQUIRES_ACCEPTANCE


def test_migration_reuse_policy_preserves_existing_stored_data() -> None:
    contract = default_surreal_retrieval_contract()

    assert contract.migration_reuse_policy is MigrationReusePolicy.PRESERVE_WHERE_PRACTICAL
    assert contract.reuse_targets == frozenset(
        {
            "chunks",
            "embeddings",
            "source_refs",
            "graph_relations",
            "feedback",
            "cursors",
            "checkpoints",
        }
    )
    assert contract.default_rechunk is False
    assert contract.default_reembed is False
    assert contract.default_reextract_entities is False


def test_contract_forbids_fallback_backend_and_compatibility_shims() -> None:
    contract = default_surreal_retrieval_contract()

    assert contract.runtime_fallback_backend_allowed is False
    assert contract.productized_compatibility_shims_allowed is False
