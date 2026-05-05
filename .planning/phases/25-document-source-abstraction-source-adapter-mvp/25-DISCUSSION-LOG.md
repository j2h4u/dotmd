# Phase 25: Document Source Abstraction - source adapter MVP - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md - this log preserves the alternatives considered.

**Date:** 2026-05-05
**Phase:** 25-document-source-abstraction-source-adapter-mvp
**Areas discussed:** MVP boundary, architecture panel gate

---

## MVP Boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Filesystem shim first | Reproduce current filesystem Markdown behavior through the new source-aware model before adding a real non-filesystem adapter. | yes |
| Telegram in same phase | Include Telegram read-only MVP in Phase 25 after defining the model. | |
| Larger source platform | Design and implement a broad multi-source framework now. | |

**User's choice:** Filesystem shim first.
**Notes:** The user agreed that the phase should reproduce current behavior
with a different, more convenient implementation. Telegram remains the intended
validation source later, but not the first implementation target for this phase.

---

## Architecture Panel Gate

| Option | Description | Selected |
|--------|-------------|----------|
| Panel before planning | Use an expert panel of architects and adjacent specialists to agree the domain model and contracts before implementation planning. | yes |
| Use backlog context only | Let planning proceed directly from the existing backlog docs without a fresh panel pass. | |
| Defer domain modeling | Start coding the shim and refine contracts afterward. | |

**User's choice:** Panel before planning.
**Notes:** The user expects the backlog docs to contain enough context for the
panel. The relevant inputs are `docs/source-adapter-architecture.md` and
`docs/source-adapter-architecture-panel-review.md`.

---

## the agent's Discretion

- Decide whether the panel output becomes a separate design note or is folded
  into Phase 25 research/plan artifacts.
- Keep the panel practical and MVP-oriented rather than expanding Phase 25 into
  Telegram, assets, entity catalogs, or full cross-source identity work.

## Deferred Ideas

- Telegram read-only adapter implementation.
- `mcp-telegram` export API.
- Source assets and binary attachment parsing.
- Entity catalogs and canonical identity resolution.
