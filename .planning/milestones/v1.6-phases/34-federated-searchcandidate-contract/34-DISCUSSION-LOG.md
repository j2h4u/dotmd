# Phase 34: Federated SearchCandidate contract - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-08
**Phase:** 34-federated-searchcandidate-contract
**Mode:** Expert-panel interview (user requested panel-driven business-goal elicitation)
**Panel:** Product Manager, Business Owner, System Architect, Kaizen Master, SRE

---

## Panel Round 1 — Business Goals Interview

### PM — Search behavior with telegram added

| Option | Description | Selected |
|--------|-------------|----------|
| Always together | Every query searches both markdown and telegram; results visible from both sources, ranked together | ✓ |
| Markdown by default, telegram explicit | Plain search hits markdown only; telegram opted in via flag, prefix, or separate call | |
| Smart fallback | Markdown first; system auto-adds federated only when local results are weak | |

**User's choice:** Always together by default. User added: an MCP-tool-level filter to selectively include or exclude sources will be added later — but the default is search-everywhere.
**Notes:** Drove decisions D-08 (always-on fan-out) and D-10 (MCP filters deferred).

### Business Owner — Latency budget

| Option | Description | Selected |
|--------|-------------|----------|
| Norm, +200-500ms | Latency is secondary to having complete results | |
| Hard budget | Local search must stay snappy; federated only when it fits in the budget, otherwise skipped | |
| Don't care | Search is mostly an agent tool; a second or two is invisible | ✓ |

**User's choice:** Don't care.
**Notes:** Drove decision D-09: per-source soft timeout exists for failure detection only, not for throughput shaping.

### Architect — Source breadth in next 6-12 months

| Option | Description | Selected |
|--------|-------------|----------|
| Telegram only | Telegram is the second and last source on the horizon; can build telegram-specific shortcut | |
| 1-2 more | A couple more sources foreseeable (e.g. gmail, voice notes), but not a flood | |
| Many | Goal is a personal hub on many sources (notion, slack, mail, calendar, ...); need a real generic federated framework | ✓ |

**User's choice:** Many — minimum two more, with a horizon of 5-10.
**Notes:** Drove decision D-18: contract must accept new federated providers via descriptor + provider work only, no contract edits.

### Kaizen — Phase 34 minimum acceptable scope

| Option | Description | Selected |
|--------|-------------|----------|
| MVP — prove the contract | Telegram FTS returns candidates that round-trip via read/drill. Mixing with local results may be a side track. | |
| Full path now | Local and federated results merge into a single ranked list via real RRF in this phase. | ✓ |

**User's choice:** Full path now.
**Notes:** Drove decisions D-05 (ref-keyed RRF refactor) and D-06 (federated as peer engine in shared RRF).

---

## Panel Round 2 — Failure-mode follow-ups

### SRE — Behavior when a federated source is down or errors

| Option | Description | Selected |
|--------|-------------|----------|
| Quietly skip | Other sources and local search work as usual; agent does not see the problem | |
| Skip but report | Results return, but the response explicitly notes "telegram unavailable, results are partial". Agent can decide whether to retry | ✓ |
| Fail-fast | Whole query fails until the source recovers; completeness is more important than availability | |

**User's choice:** Skip but report.
**Notes:** Drove decisions D-11 (`source_status` envelope) and D-12 (no fail-fast).

### SRE — Federated hit on a message not yet in the local index

| Option | Description | Selected |
|--------|-------------|----------|
| Read via provider | `read(ref)` calls into mcp-telegram via `read_unit_window`. Nothing written to local index. Message will appear locally when trickle catches up | ✓ |
| Materialize on the fly | `read(ref)` calls mcp-telegram and writes the message into the local index. Subsequent queries find it locally | |
| Local-only | Federated candidates are filtered to those already in the local index. Simple and predictable, but loses much of the point of federated search | |

**User's choice:** Read via provider.
**Notes:** Drove decisions D-13, D-14 (no materialization in v1.6), and D-15 (clear provider-attributed errors on read failure).

---

## Panel Round 3 — Scope confirmation

### MCP filter parameters in Phase 34?

| Option | Description | Selected |
|--------|-------------|----------|
| In Phase 34 | Ship `sources` / `exclude_sources` MCP-tool parameters with the contract | |
| Defer | Phase 34 ships always-on fan-out only; filters land in the phase that introduces a second federated source and makes selective opt-out meaningful | ✓ |

**User's choice:** Defer.
**Notes:** Drove decision D-10. Without a second federated source, MCP filters are speculative API surface.

---

## Claude's Discretion

The following are explicitly delegated to the agent during planning and
implementation:

- Exact Pydantic field names on `SearchCandidate` and `SourceStatus`.
- Naming and shape of the `engine_scores` diagnostic structure (dict vs
  nested model).
- Whether `source_status` is a top-level field on `SearchResponse` or nested
  under a `meta` block.
- Default per-source soft timeout value within the 3-5 second range.
- Concrete shape of `provider_metadata` for Telegram (dialog, sender, topic,
  etc.) — provider-specific, not part of the public contract.
- Whether the FastAPI `/search` route migrates to the new envelope inside
  Phase 34 or as a small follow-up. The MCP tool is the canonical proof.

---

## Deferred Ideas

- **MCP source filters** (`sources` / `exclude_sources` on the search tool)
  — defer until a second federated source exists.
- **On-demand materialization** of federated hits into the local index —
  defer until live-read latency is shown to be a real operational problem.
- **gmail / slack / notion / voice-notes** federated providers — out of
  scope; land in later phases on top of the Phase 34 contract.
- **Per-source latency observability** beyond `source_status` reasons —
  defer unless ops pain emerges.
- **Federated reranker behavior changes** — leave the reranker alone in
  Phase 34.
- **FastAPI envelope migration** — agent's discretion within Phase 34 or
  small follow-up.

---

## Panel Conflicts Surfaced

| Topic | Tension | Resolution |
|-------|---------|------------|
| Per-source timeout | Business Owner: "latency не приоритет"; SRE: 5-10 async fan-outs need a per-source soft cap or one stuck source blocks the response | Soft timeout is for failure detection only, not performance. Tunable, default 3-5s. |
| MVP scope vs framework | Kaizen: "minimum to ship"; Architect: "framework for 5-10 sources" | "Full path now" in Phase 34 = contract + RRF + Telegram proof; future sources land via descriptor + provider only, not contract edits. |
