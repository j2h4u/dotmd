---
status: complete
phase: 34-federated-searchcandidate-contract
source:
  - 34-01-searchcandidate-contract-and-ref-keyed-fusion-SUMMARY.md
  - 34-02-federated-fanout-and-source-status-SUMMARY.md
  - 34-03-telegram-federated-proof-and-read-roundtrip-SUMMARY.md
started: 2026-05-09T00:00:00Z
updated: 2026-05-10T01:00:00Z
---

## Current Test

[testing complete]

## Tests

### 1. MCP search — envelope shape
expected: MCP `search` tool returns envelope with `results` AND `source_status` keys (not a plain list).
result: pass

### 2. source_status includes local engine entries
expected: After a search, `source_status` contains at least one entry. Each entry has `name`, `status`, and `candidate_count`.
result: pass

### 3. Telegram search — ref shape
expected: When Telegram is configured and `search(query)` returns Telegram hits, refs are shaped as `telegram:dialog:<id>:message:<id>` (not dialog-level refs).
result: issue
reported: "search_native now returns message-level refs correctly, but they never appear in search() results: all tg:fts candidates have fused_score=0.0 (daemon returns no score field), and the merge sorts by fused_score desc then slices [:top_k] — local filesystem results fill all 10 slots, Telegram candidates always dropped. source_status correctly shows tg:fts ok 10 (counted before the slice)."
severity: major

### 4. tg:fts appears in source_status
expected: When Telegram lifecycle bundle is active, `source_status` contains an entry with `name: "tg:fts"` and `status: "ok"` (or `"skipped"` on timeout).
result: pass

### 5. read(ref) — Telegram ref routes through provider
expected: `read(ref)` with a `telegram:dialog:...:message:...` ref returns the message text. Does not raise "no chunks" error.
result: pass

### 6. drill(ref) — Telegram ref returns metadata
expected: `drill(ref)` with a Telegram ref returns a metadata payload.
result: pass

### 7. Daemon-down error attribution
expected: When daemon is unreachable, `source_status` tg:fts entry has status=error with attributed reason.
result: pass

### 8. can_materialize=False for all candidates
expected: Every `SearchCandidate` has `can_materialize: false`.
result: pass

## Summary

total: 8
passed: 7
issues: 1
pending: 0
skipped: 0
blocked: 0

## Gaps

- truth: "search(query) returns Telegram candidates with message-level refs in the results list"
  status: failed
  reason: "User reported: tg:fts candidates have fused_score=0.0 (daemon returns no score field). Sorted merge against local results with positive scores fills all top_k=10 slots with filesystem candidates. Telegram candidates are always dropped. source_status correctly counts them before the slice."
  severity: major
  test: 3
  artifacts:
    - backend/src/dotmd/api/service.py (merge logic lines 570-574)
    - backend/src/dotmd/ingestion/telegram_provider.py (search_native fused_score=0.0)
  missing:
    - fused_score assignment strategy for federated candidates when daemon returns no score
    - merge must not uniformly cut off zero-scored candidates when local fills top_k
