# Phase 39 Research — SurrealDB-native retrieval contract

## Inputs

Phase 38 showed that the first SurrealDB prototype was a weak compatibility
proxy, not a proof that SurrealDB cannot replace the current stack.

Important Phase 38 evidence:

- Transform-only import can preserve existing stored chunks, vectors, graph
  rows, feedback, cursors, and checkpoints in a thin SurrealDB representation.
- Embedded `surrealkv://` transaction and writer-guard probes passed for local
  spike boundaries.
- Vector parity passed on the imported sample.
- FTS and hybrid/RRF failed because the prototype used a text-only FTS proxy and
  then fed a different candidate set into fusion.
- Scale evidence was incomplete; HNSW build timing was not produced.

## SurrealDB Capability Notes

SurrealDB has the primitives needed for a real implementation:

- Full-text indexes with analyzers and BM25 scoring.
- Separate full-text indexes per field, with `search::score(...)` usable in
  query expressions.
- Vector indexes, including HNSW and DISKANN depending on version/target.
- Relation records that can model graph edges with labels, weights, and
  metadata.
- Hybrid helpers such as RRF/linear fusion, though dotMD may keep app-side
  fusion if that gives clearer attribution and debugging.

## Research Conclusion

The next contract should not try to exactly imitate SQLite FTS5 + sqlite-vec +
FalkorDB. Instead:

- Define SurrealDB-native retrieval semantics.
- Preserve title/tags/body weighting as a user-facing search intent, not as a
  SQLite compatibility detail.
- Preserve graph/entity search as a user-facing capability, not as a FalkorDB
  compatibility detail.
- Preserve existing embeddings and chunk/source state where practical, because
  recomputing them by default would waste CPU and erase the main benefit of
  Phase 38 import proof.
- Use old-stack output as a baseline for evaluation, not as the target.

## Planning Implication

Phase 39 should produce both:

- a human-readable contract document for product/architecture decisions;
- a small typed contract module so Phase 40 evaluation and Phase 43 shadow-run
  reporting share the same accepted-difference and gate vocabulary.

---

*Phase: 39-surrealdb-native-retrieval-contract*
*Research captured: 2026-06-12*
