# Phase 39 Retrieval Contract

## Decision

dotMD's target is SurrealDB-native retrieval. The old SQLite/sqlite-vec/FTS5 +
FalkorDB stack remains available during migration only as a baseline/evaluator.
It is not the compatibility target.

## Retrieval Surfaces

| Surface | Contract |
|---------|----------|
| weighted full-text | Title, tags, and body/text keep distinct weights or equivalent intent. |
| vector | Existing embeddings are reused where practical and indexed with the selected SurrealDB vector strategy. |
| graph/entity | Relations preserve labels, weights, and metadata needed for entity/tag traversal. |
| hybrid fusion | Candidate sets are explainable and retain engine attribution. |
| reranker input | Reranker receives stable refs, snippets, provenance, and enough candidate diversity. |

## Difference Classes

| Class | Meaning | Gate |
|-------|---------|------|
| improvement | SurrealDB result is clearly better for the user scenario. | allow |
| harmless reorder | Order changed without losing important results. | allow |
| regression | Important result is missing, demoted, unreadable, or unexplained. | block |
| unclear | The evidence does not show whether the change is good or bad. | requires explicit acceptance |

Exact rank parity with the old stack is not a success criterion.

## Migration Constraint

Later phases must preserve existing stored data where practical:

- chunks
- embeddings
- source refs
- graph relations
- feedback
- cursors
- checkpoints

Default rechunking, TEI reembedding, and entity re-extraction are not allowed.
If a later phase needs recomputation, it must prove the transform/import path is
unsafe or materially worse.

## Cutover Policy

- No runtime fallback backend after cutover acceptance.
- No productized compatibility shims.
- Legacy SQLite/sqlite-vec/FTS5, FalkorDB, and LadybugDB paths are deleted in
  the same milestone after SurrealDB cutover acceptance.

## Consumers

- **Phase 40:** use these classes in golden-query and diff reports.
- **Phase 41:** use the migration constraint for production schema/import.
- **Phase 42:** implement the five retrieval surfaces in SurrealDB.
- **Phase 43:** classify shadow-run differences and block unresolved
  regressions.
