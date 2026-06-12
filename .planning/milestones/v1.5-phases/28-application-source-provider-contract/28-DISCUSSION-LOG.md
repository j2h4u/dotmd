# Phase 28: application-source-provider-contract - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-07
**Phase:** 28-application-source-provider-contract
**Areas discussed:** export shape, cursor guarantees, document/unit model,
unit fields, mcp-telegram boundary, provider methods, export payload shape,
read window, mcp-telegram payload note, graphify planning aid

---

## Existing Context Handling

| Option | Description | Selected |
|--------|-------------|----------|
| Update it | Use the existing context as a starting point and refresh it through discussion. | ✓ |
| View it | Show the existing context first before deciding whether to change it. | |
| Skip | Leave the existing context untouched and stop the workflow. | |

**User's choice:** Update it.
**Notes:** Existing `CONTEXT.md` was only a short placeholder.

---

## Todo Folding

| Option | Description | Selected |
|--------|-------------|----------|
| Fold matched todos | Fold one or more keyword-matched pending todos into Phase 28. | |
| Fold none | Treat matched todos as reviewed but out of Phase 28 scope. | ✓ |

**User's choice:** none.
**Notes:** Matched todos were broad or stale against the provider-contract
scope.

---

## Export Shape

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal contract for changes | Lock the smallest source-change contract needed for the next phase. | ✓ |
| Full baseline contract | Define documents, units, windows, statuses, metadata, and cursors immediately. | |
| dotMD-side protocol only | Build dotMD abstraction first and defer mcp-telegram requirements. | |

**User's choice:** Minimal contract for changes.
**Notes:** User clarified this must be reusable for future sources such as
Slack, Notion, and other services, not Telegram-only.

---

## Cursor Guarantees

| Option | Description | Selected |
|--------|-------------|----------|
| checkpoint_cursor after successful write | Save progress only after durable local write/index commit. | ✓ |
| Single next_cursor | Simpler cursor model with higher risk if saved too early. | |
| No cursor in Phase 28 | Defer progress semantics to later sync phases. | |

**User's choice:** checkpoint_cursor after successful write.
**Notes:** Reliability matters even for a one- or two-user system because lost
sync progress can silently drop source content.

---

## Document And Unit Model

| Option | Description | Selected |
|--------|-------------|----------|
| Hybrid with implicit root unit | Providers emit units when natural; dotMD normalizes document-only sources into one implicit root unit. | ✓ |
| SourceUnit required for all providers | Uniform but may force fake units onto simple sources. | |
| Document-only for now | Fastest now, but poor fit for Telegram/Slack incremental sync. | |

**User's choice:** Hybrid with implicit root unit.
**Notes:** The user asked for an expert panel because the decision required
looking ahead. Panel input split between required minimal `SourceUnit` and a
hybrid contract. The resolved decision keeps one internal unit shape while
allowing simple providers such as PDFs or page-like sources to start as a root
unit.

---

## PDF Source Implications

| Option | Description | Selected |
|--------|-------------|----------|
| One PDF root unit first | Start with one implicit root unit for PDF sources. | ✓ |
| Page/section units later | Move to page/section units once parser output is stable enough. | ✓ |

**User's choice:** Accepted hybrid interpretation for PDFs.
**Notes:** PDF can be a `SourceDocument` with one implicit root unit now, and
later page/section units if that improves reuse/read context without unstable
parser coupling.

---

## SourceUnit Required Fields

| Option | Description | Selected |
|--------|-------------|----------|
| Minimum for reliable sync | `namespace`, `document_ref`, `unit_ref`, `text`, `fingerprint`, `updated_at`, `order_key`, `metadata_json`. | ✓ |
| Minimum plus lifecycle status | Add mandatory `active/deleted/hidden` status now. | |
| Very narrow MVP | Only `document_ref`, `unit_ref`, `text`, `fingerprint`. | |

**User's choice:** Minimum for reliable sync.
**Notes:** Lifecycle status remains optional/source-specific for now.

---

## mcp-telegram Boundary

| Option | Description | Selected |
|--------|-------------|----------|
| General protocol plus small mcp-telegram note | Define dotMD contract and add a concrete mcp-telegram contract note. | ✓ |
| General dotMD protocol only | Keep mcp-telegram requirements out of Phase 28. | |
| Full mcp-telegram API design | Specify complete API, errors, pagination, and schemas now. | |

**User's choice:** General protocol plus small mcp-telegram note.
**Notes:** The note should be concrete enough for Phase 29 without becoming an
mcp-telegram implementation phase.

---

## Provider Methods

| Option | Description | Selected |
|--------|-------------|----------|
| describe_source, export_changes, read_unit_window | Smallest practical core. Documents and units travel in changes. | ✓ |
| Add export_documents and export_units | More explicit but wider than MVP. | |
| export_changes only | Narrowest but weak for read/drill context. | |

**User's choice:** describe_source, export_changes, read_unit_window.
**Notes:** Separate document/unit export methods remain deferred.

---

## export_changes Payload Shape

| Option | Description | Selected |
|--------|-------------|----------|
| Change events | Items are explicit events such as document_upsert, unit_upsert, delete/hidden. | |
| Active records only | Source returns current active records for indexing. | ✓ |
| Upsert now, delete/hidden later | Similar compromise with narrower wording. | |

**User's choice:** Active records only.
**Notes:** Delete/hidden/tombstone lifecycle remains deferred to avoid
overloading Phase 28.

---

## read_unit_window Requirement

| Option | Description | Selected |
|--------|-------------|----------|
| Required with simple fallback | Every provider supports the method; simple providers return the requested unit only. | ✓ |
| Optional method | Only providers with natural neighboring context implement it. | |
| Defer from Phase 28 | Leave search-to-read context for later phases. | |

**User's choice:** Required with simple fallback.
**Notes:** Keeps source providers consistent without forcing artificial windows.

---

## mcp-telegram Payload Note

| Option | Description | Selected |
|--------|-------------|----------|
| Contract note with example payload | Include methods, fields, and one or two JSON examples. | ✓ |
| Text requirements only | Faster but less useful for Phase 29. | |
| Full API specification | Clearer but too heavy for this phase. | |

**User's choice:** Contract note with example payload.
**Notes:** Examples should show dialog as `SourceDocument`, message as
`SourceUnit`, checkpoint cursor, and neighboring message context.

---

## Completion Gate

| Option | Description | Selected |
|--------|-------------|----------|
| Fix context | Write the decisions into CONTEXT.md and discussion log. | ✓ |
| Discuss errors/failures more | Continue on provider outages, invalid cursors, and partial batches. | |
| Discuss metadata/display more | Continue on labels, sender, timestamps, and display metadata. | |

**User's choice:** Fix context.
**Notes:** User also requested that graphify be available to downstream
research/planning as a codebase graph aid.

---

## the agent's Discretion

- Exact class names, module placement, and schema details may be chosen during
  planning, as long as they preserve the decisions in `28-CONTEXT.md`.
- graphify may guide codebase research, but source files remain authoritative.

## Deferred Ideas

- Full delete/hidden/tombstone provider lifecycle.
- Separate `export_documents` and `export_units` methods.
- Full `mcp-telegram` API implementation.
- Slack, Notion, PDF parser, and other provider implementations beyond
  examples/fixtures.
