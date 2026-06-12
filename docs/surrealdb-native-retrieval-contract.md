# SurrealDB-Native Retrieval Contract

dotMD is moving toward one SurrealDB-native storage and retrieval backend. The
old SQLite/sqlite-vec/FTS5 + FalkorDB stack is a baseline/evaluator during the
cutover, not a product compatibility target.

## Contract

SurrealDB must provide these retrieval surfaces:

- **Weighted full-text:** title, tags, and body/text are distinct signals.
  Preserving their search intent matters more than matching SQLite FTS5 scores.
- **Vector search:** existing embeddings are reused where practical; the new
  vector index must pass production-like build and latency checks.
- **Graph/entity retrieval:** relation records preserve labels, weights, and
  metadata needed for entity and tag traversal.
- **Hybrid fusion:** full-text, vector, and graph candidates combine into an
  explainable candidate set with engine attribution.
- **Reranker input:** the reranker receives a strong candidate pool with stable
  source refs, snippets, and provenance.

Exact old-stack rank parity is not required. Differences are classified as:

| Difference | Cutover gate |
|------------|--------------|
| improvement | allow |
| harmless reorder | allow |
| regression | block |
| unclear | requires explicit acceptance |

## Migration

The default posture is to preserve existing stored data where practical:

- chunks
- embeddings
- source refs
- graph relations
- feedback
- cursors
- checkpoints

The cutover must not default to rechunking, TEI reembedding, or entity
re-extraction. A later phase may choose recomputation only after proving the
transform path is unsafe or materially worse.

## Non-Goals

- No productized compatibility mode for old SQLite/Falkor retrieval behavior.
- No runtime fallback backend after cutover acceptance.
- No compatibility shims for hypothetical external clients.
- No legacy SQLite/sqlite-vec/FTS5/FalkorDB/LadybugDB code kept after the
  SurrealDB cutover is accepted.

## Phase Handoff

- **Phase 40:** build golden queries and diff reports using the four difference
  categories above.
- **Phase 41:** harden schema/import while preserving the migration targets
  listed here.
- **Phase 42:** implement SurrealDB retrieval against these surfaces.
- **Phase 43:** shadow-run old stack versus SurrealDB and block unresolved
  regressions.
