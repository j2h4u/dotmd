# Phase 26: source-ref-first-read-search-contract-cleanup - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-06
**Phase:** 26-source-ref-first-read-search-contract-cleanup
**Areas discussed:** public source identity, search result shape, read/drill split, cleanup depth

---

## Public Source Identity

| Option | Description | Selected |
|--------|-------------|----------|
| String `ref` | `search` returns one string such as `filesystem:/mnt/.../transcript.md`; `read(ref)` passes that same value. | yes |
| `namespace` + `document_ref` args | Public tools take two simple fields. | |
| Structured `source_ref` object | Public tools take a JSON object with namespace/document_ref. | |

**User's choice:** String `ref`.
**Notes:** The user selected option 1. Public MCP ergonomics matter: search hit
identity should copy directly into read/drill.

---

## Search Result Shape

| Option | Description | Selected |
|--------|-------------|----------|
| Remove `file_paths` immediately | Public search hit contains `ref`, snippet, score, and optional heading. | yes |
| Keep path as display metadata | Add a non-key field such as `source_uri` or `display_path`. | |
| Keep deprecated `file_paths` beside `ref` | Soft transition while old agents keep working. | |

**User's choice:** Remove `file_paths` immediately.
**Notes:** The agent initially argued for display metadata, but the user pointed
out that filesystem `ref` already contains the path. The final decision is to
avoid duplicate display path fields and remove the path-shaped contract.

---

## Read and Drill Split

| Option | Description | Selected |
|--------|-------------|----------|
| Keep `drill(ref)` separate | `read(ref)` is content; `drill(ref)` is metadata/entities/chunk_count. | yes |
| Merge drill into read | One tool returns both metadata and optional text ranges. | |
| Remove drill now | Keep only `read(ref)` and revisit metadata later. | |

**User's choice:** Keep `drill(ref)` separate.
**Notes:** Existing `drill` workflow is useful, but it must stop accepting
`file_path`.

---

## Cleanup Depth

| Option | Description | Selected |
|--------|-------------|----------|
| Public contract only | Change MCP/API arguments but leave `SearchResult.file_paths` as the service/domain shape. | rejected |
| Public contract + `SearchResult` domain model | Make MCP/API/service results source-ref-first while keeping lower-level holder tables if needed. | yes |
| Aggressive storage/graph rewrite | Replace `Chunk.file_paths`, `chunk_file_paths_*`, and graph `File` internals now. | |

**User's choice:** Public contract plus `SearchResult` domain model.
**Notes:** The user explicitly rejected the shallow public-only option. The
agent compared the middle and aggressive options. The accepted recommendation:
do not model Telegram dialogs as `File`, but also do not rewrite all storage and
graph internals in the same phase unless research proves an incremental
no-full-reindex path.

---

## the agent's Discretion

- Choose exact internal parsing/resolution helpers for string `ref`.
- Decide plan slicing across MCP/API/service/tests/docs.
- Decide whether internal holder terminology needs immediate docs/renaming.

## Deferred Ideas

- Telegram source adapter implementation.
- Deep graph/storage rename away from `File` and `chunk_file_paths_*` if it
  risks full reindex or graph rebuild.
- Optional pretty display labels for search hits if `ref` later proves too
  noisy.
