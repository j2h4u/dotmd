# Phase 39 Context — SurrealDB-native retrieval contract

## Goal

Define the target SurrealDB-native search semantics before implementation
starts.

Phase 39 is not a compatibility-mode phase. The current SQLite/sqlite-vec/FTS5
+ FalkorDB stack is a temporary baseline and evaluator only. The future product
contract is SurrealDB-native retrieval with quality gates based on user-facing
search behavior.

## Locked Decisions

- Do not attempt exact rank parity with the old stack as a product goal.
- Treat old-stack differences as evidence to classify: improvement, harmless
  reorder, regression, or unclear.
- Design for one future backend: SurrealDB.
- No runtime fallback backend after cutover.
- No compatibility shims for hypothetical external clients.
- After cutover acceptance, legacy SQLite/sqlite-vec/FTS5/FalkorDB/LadybugDB
  code is deleted in the same milestone.
- Data migration matters: the retrieval contract must preserve the intent to
  migrate existing chunks, embeddings, source refs, graph relations, feedback,
  cursors, and checkpoints where practical. It must not silently assume a full
  rechunk/reembed/re-extract.

## Phase Boundary

This phase should produce the contract and acceptance vocabulary that later
phases use. It should not implement the full SurrealDB backend.

Expected downstream use:

- Phase 40 uses this contract to build golden queries and diff reports.
- Phase 41 uses the migration constraints while hardening schema/import.
- Phase 42 implements SurrealDB retrieval against this contract.
- Phase 43 uses the accepted-difference categories for shadow-run gates.

## Canonical References

- `.planning/REQUIREMENTS.md` — v1.8 requirements and traceability.
- `.planning/milestones/v1.7-ROADMAP.md` — Phase 38 outcome and deferred
  SurrealDB work.
- `.planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-RECOMMENDATION.md`
  — why the Phase 38 compatibility/parity prototype was rejected.
- `.planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-03-RETRIEVAL-PARITY.md`
  — evidence on weighted FTS, vector, graph-direct, hybrid/RRF, and scale.
- `backend/src/dotmd/search/fusion.py` — current hybrid/RRF baseline.
- `backend/src/dotmd/search/fts5.py` — current weighted FTS behavior.
- `backend/src/dotmd/search/semantic.py` — current vector retrieval behavior.
- `backend/src/dotmd/search/graph_direct.py` — current graph-direct behavior.
- `backend/src/dotmd/storage/surreal.py` — Phase 38 thin Surreal prototype.
- `backend/src/dotmd/search/surreal_parity.py` — Phase 38 comparison harness.

## Success Shape

At the end of Phase 39, a developer should be able to answer:

- What does “good SurrealDB-native search” mean for dotMD?
- Which differences from the old stack are acceptable?
- Which differences block cutover?
- Which data must be migrated or reused instead of recomputed by default?
- What evidence must Phase 40/43 produce before production cutover?

---

*Phase: 39-surrealdb-native-retrieval-contract*
*Context gathered: 2026-06-12*
