# SurrealDB-Native Retrieval Contract

dotMD uses SurrealDB as the only production storage and retrieval backend.
This contract defines the current retrieval surfaces and the invariants that
the production/admin tooling must preserve.

## Contract

SurrealDB provides these retrieval surfaces:

- **Weighted full-text:** title, tags, and body/text remain distinct signals.
- **Vector search:** embeddings are reused where practical and the vector index
  is built and checked through the production admin path.
- **Graph/entity retrieval:** relation records preserve labels, weights, and
  metadata needed for entity and tag traversal.
- **Hybrid fusion:** full-text, vector, and graph candidates combine into an
  explainable candidate set with engine attribution.
- **Reranker input:** the reranker receives a strong candidate pool with stable
  source refs, snippets, and provenance.

## Data Preservation

The production backend preserves existing stored data where practical:

- chunks
- embeddings
- source refs
- graph relations
- feedback
- cursors
- checkpoints

The production path does not default to rechunking, TEI reembedding, or entity
re-extraction. Recompute only when the operator explicitly chooses it for a
targeted maintenance task.

## Non-Goals

- No productized compatibility mode for old SQLite/Falkor retrieval behavior.
- No alternate production runtime backend.
- No compatibility shims for hypothetical external clients.
- No legacy SQLite/sqlite-vec/FTS5/FalkorDB/LadybugDB code kept in the
  production retrieval path.
