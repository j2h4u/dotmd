---
status: diagnosed
phase: 34-federated-searchcandidate-contract
source:
  - 34-01-searchcandidate-contract-and-ref-keyed-fusion-SUMMARY.md
  - 34-02-federated-fanout-and-source-status-SUMMARY.md
  - 34-03-telegram-federated-proof-and-read-roundtrip-SUMMARY.md
started: 2026-05-09T00:00:00Z
updated: 2026-05-09T00:00:00Z
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
reported: "Live search returns dialog-level refs (telegram:dialog:-1003897013523) from the local index. The new search_native() federated path correctly generates message-level refs, but local index entries from Phase 29/31 use the old dialog-level format."
severity: major

### 4. tg:fts appears in source_status
expected: When Telegram lifecycle bundle is active, `source_status` contains an entry with `name: "tg:fts"` and `status: "ok"` (or `"skipped"` on timeout).
result: pass

### 5. read(ref) — Telegram ref routes through provider
expected: `read(ref)` with a `telegram:dialog:...:message:...` ref returns the message text. Does not raise "no chunks" error.
result: issue
reported: "read(telegram:dialog:-1003897013523) raises 'Unsupported source namespace: telegram' — dialog-level ref from local index cannot route through provider. Phase 34 read routing expects message-level refs."
severity: major

### 6. drill(ref) — Telegram ref returns metadata
expected: `drill(ref)` with a Telegram ref returns a metadata payload.
result: skipped
reason: No message-level Telegram refs available to test (see issue in test 3)

### 7. Daemon-down error attribution
expected: When daemon is unreachable, `source_status` tg:fts entry has status=error with attributed reason.
result: pass

### 8. can_materialize=False for all candidates
expected: Every `SearchCandidate` has `can_materialize: false`.
result: pass

## Summary

total: 8
passed: 5
issues: 2
pending: 0
skipped: 1
blocked: 0

## Gaps

[none yet]
