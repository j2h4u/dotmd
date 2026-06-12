# Phase 29: telegram-adapter-mvp-ingestion - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md - this log preserves the alternatives considered.

**Date:** 2026-05-07
**Phase:** 29-telegram-adapter-mvp-ingestion
**Areas discussed:** dialog scope, read shape, public refs, message chunking,
low-signal messages, mcp-telegram export boundary, live smoke, planning aids

---

## Existing Context Handling

| Option | Description | Selected |
|--------|-------------|----------|
| Update it | Load the existing context, clarify remaining decisions, and rewrite it if needed. | ✓ |
| View it | Show the current context first before deciding whether to change it. | |
| Skip | Leave the existing context unchanged and stop this discussion workflow. | |

**User's choice:** Update the existing Phase 29 context.
**Notes:** The existing context only pointed at requirements and did not capture
implementation decisions for downstream planning.

---

## Dialog Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Only selected in mcp-telegram | dotMD consumes dialogs already selected or marked in mcp-telegram. | |
| Separate dotMD allowlist | dotMD stores its own list of Telegram dialogs to index. | |
| All available synced dialogs | dotMD ingests all Telegram dialogs available through mcp-telegram sync/export. | ✓ |

**User's choice:** All available synced dialogs.
**Notes:** This makes `mcp-telegram` the source of coverage and keeps dotMD
focused on ingestion/search instead of a second selection surface.

---

## Read Shape

| Option | Description | Selected |
|--------|-------------|----------|
| Message window | `read(ref)` returns the target message plus neighboring messages. | ✓ |
| Target message only | `read(ref)` returns only the found message. | |
| Whole dialog or large dialog slice | `read(ref)` returns much broader dialog context. | |

**User's choice:** Message window.
**Notes:** The target message remains the anchor, while the window gives agents
enough conversational context.

---

## Public Ref Shape

| Option | Description | Selected |
|--------|-------------|----------|
| Message ref | Public ref points to a concrete Telegram message. | ✓ |
| Dialog plus position/time | Public ref points to a dialog location rather than a message identity. | |
| dotMD chunk ref | Public ref points to dotMD chunk identity. | |

**User's choice:** Message ref.
**Notes:** The accepted shape is message-oriented, e.g.
`telegram:dialog:<id>:message:<message_id>`.

---

## Message Chunking

| Option | Description | Selected |
|--------|-------------|----------|
| Message as base unit plus read window | Store/index message identity directly and rely on read window for context. | partial |
| Mini-sessions by word count | Merge nearby messages into artificial blocks until enough words accumulate. | |
| Whole dialog blocks | Index broad dialog-level blocks. | |
| Hybrid anchored context | Keep message as `SourceUnit`; use conservative context chunks for short messages where needed. | ✓ |

**User's choice:** Asked for an expert panel because short chat messages make
the decision non-obvious.
**Notes:** The panel rejected word-count blocks as the primary identity because
they create ref ambiguity and incremental recomputation churn. The converged
direction is a conservative hybrid: message identity remains durable; normal
messages can index directly; low-signal messages are stored but not promoted as
standalone hits; any richer retrieval context must remain anchored to concrete
message refs with full source-unit provenance.

---

## Low-Signal Messages

| Option | Description | Selected |
|--------|-------------|----------|
| Store but do not promote as standalone hits | Preserve short acknowledgements as source units/provenance/read context, but keep them from dominating normal search. | ✓ |
| Index as ordinary messages | Treat `ok`, `yes`, `+1`, and emoji-only messages like any other message. | |
| Index only with context | Index low-signal messages through anchored neighboring context. | |

**User's choice:** Store but do not promote as standalone hits.
**Notes:** Low-signal messages must remain available for provenance and read
windows.

---

## mcp-telegram Export Boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal export API in mcp-telegram | Add the smallest structured source/export API needed by dotMD. | ✓ |
| Fixture-only dotMD adapter first | Build only local fixtures and defer real runtime export. | |
| Temporarily parse list_messages | Parse the existing human-facing output. | |

**User's choice:** Minimal export API in `mcp-telegram` if needed.
**Notes:** dotMD must not read private `mcp-telegram` SQLite tables and must not
parse human-rendered `list_messages` as the durable ingest format.

---

## Live Smoke Boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Export -> ingest -> records exist | Prove real `mcp-telegram` export can be ingested into dotMD metadata/index state. | ✓ |
| Fixture tests only | Avoid live runtime smoke in Phase 29. | |
| Full search/read/drill smoke now | Verify the complete public workflow in Phase 29. | |

**User's choice:** Export -> ingest -> records exist.
**Notes:** Full public `search -> read/drill` smoke remains Phase 31 scope.

---

## Planning Aids

| Option | Description | Selected |
|--------|-------------|----------|
| Use Graphify as planning aid | Downstream agents may use the codebase graph for navigation, then verify against files. | ✓ |
| Do not mention Graphify | Keep planning references limited to source files and docs. | |

**User's choice:** Use Graphify as planning aid.
**Notes:** Graphify output is advisory only and must not replace live source
verification.

---

## the agent's Discretion

- Exact low-signal-message heuristic.
- Exact module/class naming for the Telegram adapter and any `mcp-telegram`
  client wrapper.
- Whether anchored-context indexing is implemented in Phase 29 or only
  prepared through provenance and fixtures, as long as standalone low-signal
  hits do not dominate search.

## Deferred Ideas

- Full incremental Telegram sync and reuse.
- Full search/read/drill live smoke.
- Edit/delete/tombstone lifecycle.
- Attachments/media indexing.
- Bidirectional Telegram actions.
- Shared contact/entity catalog.
- Broad chat search quality experiments beyond the conservative MVP.
