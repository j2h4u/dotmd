---
phase: 29
reviewers: [claude, opencode]
reviewed_at: 2026-05-08T00:54:42+05:00
cycle: 3
plans_reviewed:
  - .planning/phases/29-telegram-adapter-mvp-ingestion/29-01-mcp-telegram-source-export-PLAN.md
  - .planning/phases/29-telegram-adapter-mvp-ingestion/29-02-dotmd-telegram-provider-PLAN.md
  - .planning/phases/29-telegram-adapter-mvp-ingestion/29-03-dotmd-telegram-ingestion-PLAN.md
  - .planning/phases/29-telegram-adapter-mvp-ingestion/29-04-telegram-read-drill-and-smoke-PLAN.md
---

# Cross-AI Plan Review - Phase 29 - Cycle 3

## Claude Review

### Summary

The cycle 3 replan closes every cycle 2 HIGH with concrete mitigation and
verification: dual-stream cursor/watermark semantics with worked-example tests,
ISO-8601 microseconds plus tie-break cursor for `unit_updated_at`, mandatory
metadata embedding refactor with a grep guard against `e_meta = e_text`, an
explicit `save_chunks(file_paths=[])` pin test ordered before Telegram-specific
assertions, removal of the phantom HTTP transport in Plan 04, single-batch
bootstrap semantics with a dedicated test, and a single-transaction rollback
test that injects vector failure. Plan 04 now lists `29-01` as a direct
dependency and elevates the docker-compose socket bind-mount to a deliverable.

Remaining concerns are mostly fingerprint-stability hygiene, search-semantics
side effects from prefixed metadata, and operational coordination with the
trickle indexer. None rise to HIGH given the current mitigations.

### Strengths

- Plan 01 now separates identity rows from update rows: identity rows advance
  `checkpoint_cursor`; update rows advance `updated_after` and
  `updated_after_cursor`.
- The cursor/watermark interleave has a worked fixture: a cursor at
  `message:50` plus an edit at `message:30` should preserve the identity cursor
  semantics while advancing the update watermark.
- Same-second `unit_updated_at` equality is pinned with `(unit_updated_at,
  dialog_id, message_id)` tie-break behavior.
- Plan 03 bans the `e_meta = e_text` shortcut and requires real Telegram
  metadata text for the metadata embedding channel.
- Plan 03 pins `save_chunks(file_paths=[])` before relying on it.
- Plan 03's rollback test covers metadata, FTS5, vector writes, delete
  cascades, and checkpoint commits inside one transaction.
- Plan 04 is socket-only and includes a grep guard against the removed
  `DOTMD_TELEGRAM_DAEMON_URL` path.

### Concerns

- **MEDIUM - `unit_updated_at` in fingerprints may couple content identity to
  daemon cache churn.** If `mcp-telegram` rewrites cache rows without content
  changes, using `unit_updated_at` as a fingerprint input could make unchanged
  messages look changed. Safer direction: keep `unit_updated_at` for the export
  watermark only and fingerprint on content-bearing fields such as text,
  sent/edit/delete/topic/reply/sender.
- **MEDIUM - Low-signal vocabulary is still narrow for RU-heavy chat.** Common
  forms like `okay`, `sure`, `good`, `nice`, `понял`, `принято`, `хорошо`,
  `ясно`, and punctuation variants could slip through as standalone hits.
- **MEDIUM - Trickle/fcntl lock coordination is not explicit.**
  `ingest_application_source()` is a new writer to `index.db`; the plan should
  say whether it acquires the same exclusive lock as filesystem indexing or
  fails clearly when trickle is active.
- **MEDIUM - Prefixed metadata changes FTS5 semantics.** Sender/dialog/topic
  prefixes mean searches can match messages because of metadata, not message
  text. This can be acceptable, but the plan should document the product choice.
- **MEDIUM - Metadata embedding includes raw `sent_at`.** ISO timestamps are
  likely noisy in multilingual embeddings. Drop `sent_at` or coarsen it if
  temporal signal matters.
- **MEDIUM - `--dry-run` smoke semantics are ambiguous.** The smoke command is
  described as proving export/import/metadata state, but `--dry-run` usually
  means no persistence. The plan should pin whether dry-run writes nothing,
  writes to temporary storage, or skips only checkpoint commit.
- **MEDIUM - Stored-chunk fallback and live-provider read windows are
  asymmetric.** Live reads can include low-signal neighbors; fallback reads from
  persisted chunks may omit them. The plan should test or document the parity
  contract.
- **MEDIUM - MCP tool descriptions do not surface Telegram-specific
  `start`/`end` semantics.** For Telegram refs, these map to before/after
  message windows; MCP callers need that in the tool description.
- **MEDIUM - Missing cross-plan E2E test.** A fake daemon -> provider -> ingest
  -> read/drill fixture would catch format drift across the cross-repo boundary.
- **MEDIUM - No search-side wiring smoke in Phase 29.** A cheap assertion that
  a substantive Telegram text can surface as a telegram-namespaced ref would
  catch wiring failures before Phase 31.

### Risk Assessment

Overall risk: **LOW**. Cycle 3 closes the prior HIGHs with concrete tests,
grep guards, and acceptance criteria. Remaining issues are operational hygiene,
search-quality side effects, and contract polish.

---

## OpenCode Review

### Summary

All eight cycle 2 HIGH concerns have concrete mitigations and verification in
the current plans. The replan from stall detection is thorough: each HIGH now
has a `Review-HIGH` must-have truth, a dedicated test or acceptance criterion,
and often a grep guard. Remaining concerns cluster around deleted-message
handling, cross-plan integration coverage, trickle-lock coordination, and a
punctuation gap in the low-signal classifier. None are blocking.

### Prior Cycle 2 HIGH Resolution Status

| # | Concern | Status | Evidence in current plans |
|---|---------|--------|---------------------------|
| 1 | Cursor + watermark interleave | Resolved | Plan 01 specifies identity/update stream separation and a mixed-stream fixture. |
| 2 | `unit_updated_at` precision/tie-break | Resolved | Plan 01 pins microseconds plus `(dialog_id, message_id)` tie-break behavior. |
| 3 | `e_meta = e_text` hack | Resolved | Plan 03 forbids it and adds a grep guard. |
| 4 | `save_chunks(file_paths=[])` unverified | Resolved | Plan 03 makes the behavior-pinning test first. |
| 5 | Phantom HTTP URL transport | Resolved | Plan 04 is socket-only and guards against URL config. |
| 6 | Plan 04 missing Plan 01 dependency | Resolved | Plan 04 depends on `29-01` and `29-03`. |
| 7 | Single-batch vs loop semantics | Resolved | Plan 03 and Plan 04 explicitly state single-batch semantics. |
| 8 | Transaction boundaries unverified | Resolved | Plan 03 injects vector failure and asserts rollback. |

### Strengths

- Plan 01 makes the two-stream merge deterministic and clamps the combined
  response to the total `limit`.
- Plan 01 excludes update-watermark rows that are also identity rows, avoiding
  duplicate emission.
- Plan 02 preserves `updated_after` and `updated_after_cursor` through
  `ApplicationSourceChangeBatch`.
- Plan 03 replaces the empty-key FTS5 convention with an explicit
  `add_chunks_with_source_meta` path.
- Plan 03 specifies delete cascade behavior across chunks, provenance,
  file-path M2M, FTS5, and vec tables.
- Plan 04 lists docker compose and `.env` updates as deliverables, not
  hidden deployment prerequisites.
- Plan 04 keeps deployment/restart batched and aligned with project guidance.

### Concerns

- **MEDIUM - Deleted messages are not explicitly filtered before indexing.**
  If Plan 01 exports `is_deleted=True` rows and Plan 03 ingests every exported
  unit as a normal chunk, deleted Telegram messages can become searchable.
  Choose one behavior: export-and-skip chunks, export deleted as provenance
  only, or filter at export with a documented Phase 30 lifecycle note.
- **MEDIUM - Low-signal classifier misses trailing punctuation.** Vocabulary
  checks against the full normalized text miss `ok!`, `thanks!`, `да!`, and
  similar chat forms. Strip trailing punctuation before vocabulary lookup.
- **MEDIUM - Trickle fcntl lock coordination is missing.** The new application
  source ingest path writes to `index.db`; the plan should say whether it
  acquires the same lock, runs in the same process, or requires trickle to be
  paused.
- **MEDIUM - `drill()` return shape for Telegram refs is under-specified.**
  The fields are named, but the return type and compatibility shape should be
  pinned.
- **MEDIUM - No end-to-end integration test across plans.** Layered fixture
  tests may all pass while the Plan 01 wire shape and Plan 02 mapping drift.
- **LOW - `topic_title` storage source is still ambiguous.** The plan asserts
  the field exists in exported metadata but should verify whether `sync_db.py`
  actually stores it.
- **LOW - Fixture payloads may diverge from actual export format.** A shared
  export sample or snapshot-based round-trip would reduce drift.
- **LOW - Metadata prefix changes FTS5 search behavior.** Sender names and
  timestamps become searchable content.
- **LOW - Counter naming could be clearer.** `hidden_units` should be defined
  as low-signal units not promoted to standalone search chunks.

### Risk Assessment

Overall risk: **LOW-MEDIUM**. All prior HIGHs are resolved with concrete
mitigations, tests, grep guards, and acceptance criteria. Remaining MEDIUM
concerns are addressable with small plan additions or code guards during
execution and are not architectural blockers.

---

## Consensus Summary

### Agreed Strengths

- Prior cycle HIGHs are closed in the current plans.
- Cursor/watermark interleave and same-second update ordering are now
  concretely specified and testable.
- Plan 03 no longer relies on the `e_meta = e_text` workaround.
- Empty file-path chunk persistence is pinned before Telegram code depends on
  it.
- Socket-only Telegram daemon connectivity removes the phantom HTTP transport.
- Deployment changes are explicit deliverables.

### Agreed Concerns

- **MEDIUM - Trickle/fcntl lock coordination should be explicit** before the
  new Telegram ingest path writes to `index.db`.
- **MEDIUM - Cross-plan integration coverage is thin** across
  export -> provider -> ingest -> read/drill.
- **MEDIUM - Low-signal handling needs small hardening** for punctuation and
  common short chat acknowledgements.
- **MEDIUM - Metadata in indexed text affects search semantics** and should be
  either accepted deliberately or bounded.

### Divergent Views

- Claude emphasized `unit_updated_at` as a fingerprint-stability risk.
  OpenCode treated fingerprinting as acceptable but highlighted deleted-message
  behavior as the more immediate risk.
- Claude wanted an early search-side wiring test in Phase 29. OpenCode treated
  that as useful but not central compared with cross-plan fixture drift.
- OpenCode marked deleted-message handling MEDIUM; Claude considered delete
  lifecycle deferral acceptable but worth documenting.

### Current HIGH Concerns

None.

CYCLE_SUMMARY: current_high=0
