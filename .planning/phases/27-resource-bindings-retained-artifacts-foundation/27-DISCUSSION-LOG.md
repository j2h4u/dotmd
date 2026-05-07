# Phase 27: resource-bindings-retained-artifacts-foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-07
**Phase:** 27-resource-bindings-retained-artifacts-foundation
**Areas discussed:** active bindings, retained artifacts, reuse identity, filesystem unbind, diagnostics, service filtering, graph, Telegram deletion metadata, validation

---

## Todo Folding

| Option | Description | Selected |
|--------|-------------|----------|
| Soft-delete with TTL for removed source files | Fold as historical intent for retention/soft-delete thinking, but update to current source-ref/resource-binding reality. | yes |
| Background trickle indexer | Possible future lifecycle/sync relevance, likely Phase 30. | |
| Graph migration / embedding replacement / fork scouting / old smoke tests | Broad or historical matches, not Phase 27 scope. | |

**User's choice:** Fold only `Soft-delete with TTL for removed source files`.
**Notes:** User explicitly said the todo is old and should be used only to read intent, not as source of current truth.

---

## Active Binding Semantics

| Option | Description | Selected |
|--------|-------------|----------|
| Visibility gate only | Active binding controls whether ordinary public search/read can show the resource. | yes |
| Visibility plus sync permission | Active binding also controls whether dotMD continues updating the resource. | |
| Source exists | Binding merely records source existence; visibility/sync are separate states. | |

**User's choice:** Visibility gate only.
**Notes:** The discussion clarified that whole-resource unbind is separate from source-internal deletion metadata.

---

## Whole Resource Unbind

| Option | Description | Selected |
|--------|-------------|----------|
| Hide from ordinary search, retain artifacts | No active binding means no public visibility, but retained work stays reusable. | yes |
| Keep visible with inactive marker | Archive-like behavior in normal search. | |
| Delete immediately | Current filesystem-style hard purge. | |

**User's choice:** Hide from ordinary search, retain artifacts.
**Notes:** User wanted to postpone complex recycle-bin/TTL mechanics while keeping a future path open.

---

## Retained Artifact Boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Retain all artifacts | Keep chunks, embeddings, FTS, graph, and provenance; filter public output by active binding. | yes |
| Retain chunks and embeddings only | Recompute FTS/graph on rebind. | |
| Retain identity/provenance only | Strong visibility safety but weak reuse. | |

**User's choice:** Retain all artifacts.
**Notes:** Reuse and avoiding recomputation are the main value.

---

## Reuse Identity

| Option | Description | Selected |
|--------|-------------|----------|
| Content/source-unit fingerprint | Reuse when equivalent content appears again even under a new binding/ref. | yes |
| Same source ref only | Simpler but weaker for filesystem rename/move and rebinding. | |
| Preserve only, no reuse yet | Smallest scope but leaves main benefit deferred. | |

**User's choice:** Content/source-unit fingerprint.
**Notes:** Reuse should not depend only on the old path or source ref.

---

## Filesystem Delete Path

| Option | Description | Selected |
|--------|-------------|----------|
| Convert filesystem delete to inactive binding | Missing file hides resource but preserves retained artifacts. | yes |
| Add foundation, keep current purge | Less risky but less validated. | |
| Dry-run/count only | Most conservative, little product effect. | |

**User's choice:** Convert filesystem delete to inactive binding.
**Notes:** This is the first real validation source for the binding model.

---

## Inactive Resource Diagnostics

| Option | Description | Selected |
|--------|-------------|----------|
| Counts/logs only | Track active, inactive, retained, reused counts; no user-facing inactive search. | yes |
| Read-only CLI list | Show inactive resources without searching inside them. | |
| Search mode include_inactive | Recycle-bin-like search behavior. | |

**User's choice:** Counts/logs only.
**Notes:** Keep recycle-bin/inactive browsing out of Phase 27.

---

## Search Filtering

| Option | Description | Selected |
|--------|-------------|----------|
| Filter at service hydration/results | Engines may return retained chunks; public output drops inactive chunks centrally. | yes |
| Filter inside every engine | More distributed and higher risk of drift. | |
| Service filter now, engine optimization later | Future path, but service filter remains mandatory. | |

**User's choice:** Filter at service hydration/results.
**Notes:** `DotMDService` is the public boundary that must enforce visibility.

---

## Graph Retention

| Option | Description | Selected |
|--------|-------------|----------|
| Preserve graph, filter public results | Do not delete graph nodes/edges on unbind; inactive graph hits are dropped by service filter. | yes |
| Mark graph nodes inactive | Potentially useful but larger schema work. | |
| Delete graph nodes on unbind | Contradicts retained artifact reuse. | |

**User's choice:** Preserve graph, filter public results.
**Notes:** Graph is retained derived work and should not be rebuilt unnecessarily.

---

## Telegram Deleted Messages

| Option | Description | Selected |
|--------|-------------|----------|
| Normal source unit with metadata flag | If `mcp-telegram` retains the content and marks it deleted upstream, dotMD indexes it as data plus metadata. | yes |
| Inactive source unit | Hide deleted Telegram messages from ordinary search. | |
| Do not decide in Phase 27 | Leave for Telegram phases. | |

**User's choice:** Normal source unit with metadata flag.
**Notes:** User clarified that `mcp-telegram` does not physically delete such messages; it marks them as deleted upstream. For dotMD this is metadata, not unbinding.

---

## Validation

| Option | Description | Selected |
|--------|-------------|----------|
| SQLite/service integration test | Prove unbind hides from search/read while retaining artifacts/provenance for reuse. | yes |
| Metadata unit tests only | Faster but may miss public-output leaks. | |
| Live container smoke | Stronger but better suited to later Telegram smoke phase. | |

**User's choice:** SQLite/service integration test.
**Notes:** Phase 27 must prove both halves: not visible publicly, not physically thrown away.

---

## Research Tooling

| Option | Description | Selected |
|--------|-------------|----------|
| Mention graphify as optional advisory research tool | Researchers/planners can use graphify to inspect codebase relationships, but must verify against source. | yes |
| Do not mention graphify | Keep context limited to source files. | |

**User's choice:** Mention graphify as optional advisory research tool.
**Notes:** User asked whether this belongs in context; it is captured as a codebase research note, not as a source of truth.

## the agent's Discretion

- Exact active-binding schema and helper shape.
- Exact metadata query/service helper used for public active-binding filtering.
- Exact migration/backfill mechanics, as long as they are idempotent, countable, and avoid full reindex.

## Deferred Ideas

- Recycle-bin or `include_inactive` search.
- User-facing inactive resource browsing.
- TTL/hard garbage collection for retained artifacts.
- Telegram adapter ingestion and live smoke.
- Graph inactive schema changes unless proven necessary.
