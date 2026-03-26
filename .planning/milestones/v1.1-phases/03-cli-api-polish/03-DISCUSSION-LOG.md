# Phase 3: CLI & API Polish - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-23
**Phase:** 03-cli-api-polish
**Areas discussed:** Progress output, Status command, API response

---

## Gray Area Selection

| Option | Description | Selected |
|--------|-------------|----------|
| Progress output | What to show after dotmd index? Currently generic totals. Need diff summary. | |
| Status command | What should dotmd status show? Add change detection? | |
| API response | POST /index — what to return in JSON? | |

**User's choice:** "Common sense, no special requirements beyond the obvious"
**Notes:** User declined to discuss individual areas — deferred all decisions to Claude's judgment with common-sense defaults. No flags raised, no preferences expressed.

---

## Claude's Discretion

All areas resolved by Claude using common-sense defaults:
- Progress output: one-line diff summary matching CA-03 requirement verbatim
- Status: extend with pending change detection via FileTracker.diff()
- API: return enriched IndexStats as JSON
- IndexStats: add diff count fields

## Deferred Ideas

None.
