---
phase: 29
reviewers: [claude, opencode]
reviewed_at: 2026-05-08T00:36:12+05:00
cycle: 2
plans_reviewed:
  - .planning/phases/29-telegram-adapter-mvp-ingestion/29-01-mcp-telegram-source-export-PLAN.md
  - .planning/phases/29-telegram-adapter-mvp-ingestion/29-02-dotmd-telegram-provider-PLAN.md
  - .planning/phases/29-telegram-adapter-mvp-ingestion/29-03-dotmd-telegram-ingestion-PLAN.md
  - .planning/phases/29-telegram-adapter-mvp-ingestion/29-04-telegram-read-drill-and-smoke-PLAN.md
---

# Cross-AI Plan Review - Phase 29 - Cycle 2

## Claude Review

# Cross-AI Plan Review — Phase 29 (Cycle 2)

## Overall Summary

The four-plan slice cleanly separates the cross-repo `mcp-telegram` API change from dotMD provider mapping, ingestion, and resolver work, with TDD tasks that are concrete enough to grep-verify. Cycle 2's most important fix — adding the `updated_after` watermark for edits — closes the biggest gap from cycle 1. The remaining concerns cluster around three themes: (1) cursor + watermark interleaving semantics in Plan 01 are still under-specified for the dual-pagination case; (2) Plan 03's embedding/FTS approach pushes Telegram-specific hacks into shared code paths instead of refactoring the abstractions; (3) Plan 04's `DOTMD_TELEGRAM_DAEMON_URL` envelope appears to assume an HTTP transport that `mcp-telegram` doesn't expose.

---

## Plan 29-01: mcp-telegram Source Export API

### Strengths
- The watermark addition (`updated_after`) is well-specified with sort order, payload echo, and explicit edit-delivery tests — directly resolves cycle 1 HIGH on missing edits.
- Cursor format is explicit and parser-tested for negative dialog ids (`rsplit(":message:", 1)`).
- Tests prove behavior structurally (no rendered text in payload, namespace/refs/checkpoint shape) rather than just snapshot-matching.
- Synced-dialog status filter (`synced`, `syncing`, `access_lost`) is concrete.

### Concerns
- **HIGH — Cursor + watermark interleave is under-specified.** When a batch contains *both* bootstrap rows (identity-cursor branch) and watermark rows (already-exported edits), what is `checkpoint_cursor`? The plan says "last emitted unit cursor" but the two branches sort by different keys. If the last emitted row is a watermark-branch edit whose `(dialog_id, message_id)` is *behind* the highest bootstrap cursor, committing it as `checkpoint_cursor` could re-emit already-passed identity rows on the next call, or skip new bootstrap rows. This needs a worked example in the test plan: e.g., bootstrap cursor at `dialog:-1001:message:50`, edit comes in for `message:30` — what is the next batch's `checkpoint_cursor` and `updated_after`?
- **HIGH — `unit_updated_at` precision.** Plan says `max(sent_at, edit_date)` when no cache update timestamp exists. If two edits land in the same second (or same `edit_date` second), and `updated_after` uses `>` strictly, either one or both can be missed depending on equality handling. The test fixtures should pin equality semantics ("watermark uses strict >, ties broken by `(dialog_id, message_id)` secondary sort").
- **MEDIUM — Delete delivery is silent.** Plan defers delete lifecycle to Phase 30 but doesn't specify what happens to a message that's deleted on Telegram side after first export. If `is_deleted=True` rows aren't included in `export_source_changes`, dotMD never learns about them and they remain searchable forever. Consider: should deleted rows be exported with a `deleted: true` flag, then explicitly ignored by Phase 29 ingestion? This costs almost nothing now and unblocks Phase 30.
- **LOW — `topic_title` source.** Plan says "Assert exported record `unit.metadata_json.topic_title` is present with a string or `None`; do not leave topic title storage as an executor decision." Good clarification, but the daemon's actual storage layer for topic titles isn't pinned to a column — does `sync_db.py` already store this? If not, where does it come from? An extra schema task may be hidden here.

### Suggestions
- Add a test fixture covering the interleave case (bootstrap pagination still in progress + an edit to an already-emitted message) with explicit assertion of cursor+watermark advance.
- Add a "deleted-but-was-exported" fixture row and assert *some* deterministic behavior (export with flag, or exclusion documented).
- Document the secondary-sort tie-breaker for watermark rows.

### Risk: **MEDIUM**
The watermark fix is correct but its interaction with identity pagination is the kind of edge case that bites in production data. Tests need to nail down the dual-pagination contract before implementation.

---

## Plan 29-02: dotMD Telegram Provider

### Strengths
- Pydantic-validated mapping with a clean Protocol boundary — no Telethon/sync_db imports proven by negative grep.
- Fingerprint inputs are explicit (text + sent/edit/delete/topic/reply/sender + `unit_updated_at`) with sorted-key JSON serialization to handle missing optional fields.
- Low-signal classification spans EN+RU with `casefold()` and `unicodedata` for emoji-only — no new dependency.
- `public_ref_for_unit` is an explicit module-level helper, not an inline f-string scattered through callers.

### Concerns
- **MEDIUM — Low-signal vocabulary completeness.** The list (`ok, yes, yep, no, +1, thanks, thx, да, нет, ок, окей, спасибо, ага, угу`) is reasonable but missing very common forms: `okay`, `sure`, `good`, `nice`, `👍/👌/❤️` standalone (these are caught by the emoji rule), `понял`, `принято`, `хорошо`. Plan acknowledges classifier is overrideable in Phase 31, but if the corpus is RU-dominant voicenotes-style chat, the miss rate will be high and Phase 31 will inherit a noisy index. Consider adding a length threshold (e.g., `< 4 alphanumeric chars`) as a backstop.
- **LOW — `order_key` for negative dialog ids.** Plan says message ids inside one dialog are non-negative, so `f"{message_id:020d}"` is fine. But if the Telegram client ever creates pseudo-message-ids (forwarding edge cases), the assumption could break. Non-blocking.
- **LOW — `ApplicationSourceChangeBatch.updated_after` schema change.** Adding a field to a shared model is fine but downstream tests using the model should not break — would benefit from a one-line note in the plan that this is additive only.

### Suggestions
- Make low-signal threshold a named constant with a length backstop, so Phase 31 can tune without grepping for a regex.
- Add one fixture asserting `ApplicationSourceChangeBatch` round-trips with `updated_after=None` for filesystem provider (no regression).

### Risk: **LOW**
Pure mapping logic, fixture-driven, well-bounded.

---

## Plan 29-03: dotMD Telegram Ingestion

### Strengths
- `ApplicationSourceIngestResult` counter definitions are precise (especially the explicit `reused_units = 0` decision for Phase 29).
- Threat model captures the right HIGH issues (whole-dialog reindex, checkpoint-before-persistence, low-signal dropout).
- Test cases enumerate concrete provenance lookups via `get_chunks_by_source_unit_ref` rather than file-path joins.
- Coexistence test with filesystem chunks prevents regression on the existing pipeline.

### Concerns
- **HIGH — `e_meta = e_text` is a smell, not a fix.** The plan acknowledges `_embed_meta_component(FileInfo)` requires filesystem frontmatter, then routes around it by reusing the text embedding for the meta slot. This:
  1. Pollutes the dual-component embedding semantics — every reader of the vector store now needs to know "Telegram rows have `e_meta == e_text` and the meta weight is effectively dead."
  2. Wastes the meta channel that could legitimately hold structured Telegram metadata (dialog title + sender + topic) as a separate signal.
  3. Couples Phase 30+ work to undoing this hack.
  Cleaner: refactor `_embed_meta_component` to accept a `dict | FileInfo` and synthesize Telegram meta text (`"Project Chat | Alice | topic: deploy"`), then embed it as a real meta component. This is a small abstraction lift in exchange for not paying interest on the hack indefinitely.
- **HIGH — `save_chunks()` with `file_paths=[]` is asserted, not verified.** Plan says "current `save_chunks()` permits `file_paths=[]` because it only iterates file paths for M2M inserts." This is a load-bearing assumption with no test in Plan 03 task 1 that *first* pins the existing behavior. If the executor finds `save_chunks` short-circuits empty paths or asserts non-empty, the whole plan unwinds. Add a behavior-pinning test as task 1's first assertion (per `feedback_tests_before_refactor`).
- **MEDIUM — FTS5 metadata route is left ambiguous.** Plan offers two options: pass `file_meta={"": (title, "telegram")}` per-document, OR add `add_chunks_with_source_meta`. Pick one — the second is cleaner because it makes the Telegram intent explicit at the call site and avoids the "empty-key as Telegram convention" magic that future readers will misread.
- **MEDIUM — `delete_chunks_for_source_unit` cascade.** Plan mentions the helper but doesn't enumerate everything that must cascade: chunk row, vector row in sqlite-vec, FTS5 row, provenance row. Test should assert all four are gone after edit replay (currently only chunk-existence is implied).
- **MEDIUM — Concurrency with trickle.** Plan 03 adds an ingestion path but doesn't mention the fcntl lock that trickle holds. If `dotmd telegram ingest` (Plan 04) runs while trickle is active, both write to `index.db`. Per project memory `feedback_no_parallel_indexing.md`, this is exactly the foot-gun the project has previously hit. Either acquire the same lock or document explicitly that ingest_application_source is gated.
- **LOW — Resource binding `source_unit_refs` merge.** Plan says binding's `source_unit_refs=<merged existing refs plus change.unit.unit_ref>`. For a 10K-message dialog, this list grows unbounded on every batch and rewrites the binding row repeatedly. Either drop the per-binding unit list (it's redundant with the fingerprints table), or mark it as bounded/sampled.

### Suggestions
- Add a "pin existing behavior" test as the first task-1 assertion: write a chunk with `file_paths=[]` and assert `save_chunks()` accepts it, *before* writing any Telegram-specific test.
- Pick the named-wrapper FTS5 option (`add_chunks_with_source_meta`) and drop the empty-key alternative.
- Refactor `_embed_meta_component` to accept generic metadata dicts; Telegram meta becomes a synthesized one-line string. This is ~15 lines of refactor and removes the load-bearing hack.
- Add concurrency note: ingest_application_source must coordinate with trickle's fcntl lock or run inside the same process.
- Drop `ResourceBinding.source_unit_refs` accumulation, or replace with `unit_count: int`.

### Risk: **MEDIUM-HIGH**
The plan is functionally correct but the embedding hack and unverified `save_chunks` assumption are exactly the kind of "works in tests, breaks in prod" surface dotMD has hit before. The trickle concurrency gap is a known foot-gun.

---

## Plan 29-04: Telegram Read/Drill Resolver And Smoke

### Strengths
- Active-binding lookup correctly uses `dialog:<dialog_id>` (resource ref) while preserving message-level target — directly addresses the cycle 1 HIGH.
- Stored-chunk fallback for `read()` when no live provider is configured is a thoughtful Phase-29-shippable behavior.
- Smoke command is bounded (`--limit 10 --dry-run`) and explicitly does not call `dotmd index --force`.
- Connectivity verification step (`docker exec dotmd test -S "$DOTMD_TELEGRAM_DAEMON_SOCKET"`) is a real precondition check, not aspirational.

### Concerns
- **HIGH — `DOTMD_TELEGRAM_DAEMON_URL` assumes HTTP transport that doesn't exist.** Per Phase 29 research findings, `mcp-telegram`'s `DaemonConnection` uses *newline-delimited JSON over UNIX socket*. Plan 01 doesn't add an HTTP listener to the daemon. So `telegram_daemon_url` either:
  - is dead config (always falls back to socket), or
  - requires another mcp-telegram change not in Plan 01.
  Either drop URL from this plan or add the HTTP endpoint to Plan 01 explicitly. The "socket wins when both are set" rule papers over the missing transport.
- **MEDIUM — Read window mapping is a semantic overload.** `read(ref, start, end)` for filesystem refs means line/chunk offsets. For Telegram it's reinterpreted as `before/after` neighbors. This is footgun-y for callers who don't realize the same parameter name means different things. Consider a separate keyword (`window_before`, `window_after`) or at minimum document the overload prominently in the MCP tool description.
- **MEDIUM — Stored-chunk vs live-provider asymmetry.** When live provider is configured, `read()` returns a window including low-signal neighbors (because `read_unit_window` returns all messages). When provider is unavailable, fallback uses `get_chunks_by_source_unit_ref` which only returns substantive chunks (low-signal messages have no chunk). So `read("telegram:...:message:43")` returns different content depending on runtime state. Document this or unify.
- **MEDIUM — Production compose changes implied but not enumerated.** To bind-mount the mcp-telegram socket into the dotMD container requires editing `/opt/docker/dotmd/docker-compose.yml`. Plan task 3 mentions verifying connectivity but doesn't list the compose change as a deliverable. Per project memory `feedback_no_prod_restarts.md`, this should be batched and explicit, not surprise-discovered during smoke.
- **LOW — `ValueError("Unknown source ref: ...")` matches existing.** Good consistency, but the test asserts the exact message — if the existing code uses different phrasing, the test will fail. Worth grepping the current behavior first.

### Suggestions
- Drop `telegram_daemon_url` from Plan 04 (or move HTTP transport to Plan 01 as an explicit task). Socket-only is sufficient for the deployment topology described in AGENTS.md.
- Use `before`/`after` keywords on the MCP tool surface for Telegram refs, even if the Python signature still maps from `start`/`end`.
- Explicitly list the `/opt/docker/dotmd/docker-compose.yml` socket bind-mount as a Plan 04 task 3 deliverable, not a verification step.
- Add a test that `read()` produces equivalent target_ref + window in both live and fallback modes (asymmetry-detector).

### Risk: **MEDIUM**
Resolver logic is sound. The transport ambiguity (`URL` config) and missing compose change are deployment-time foot-guns that should be resolved at planning time.

---

## Cross-Plan Concerns

- **HIGH — Wave dependency is correct but transitive.** Plan 04's smoke command depends on Plan 01's daemon API, but Plan 04's `depends_on` only lists `29-03`. If executed via wave parallelism, the executor must trust the transitive chain. Add `29-01` to Plan 04's `depends_on` for honesty.
- **MEDIUM — No plan addresses what happens if mcp-telegram daemon restarts mid-export.** Cursor is committed in dotMD; daemon's view of "synced" rows is stable; should be fine. But there's no test for "daemon disconnects mid-batch" — does the dotMD provider raise cleanly and call `record_source_checkpoint_error`? Plan 03 mentions this on exception generally, but it's worth one fixture.
- **MEDIUM — Phase 29 vs Phase 31 boundary leaves a coverage gap.** Phase 29 ships ingestion + resolver but Phase 31 owns full search round-trip smoke. Between them, *no* test proves that an indexed Telegram chunk actually surfaces in `search()` results. Plan 03's chunks land in the FTS5 + vector indexes — a single search-side smoke ("search for substantive Telegram text, assert at least one telegram-namespaced ref in results") would catch wiring breakage at Phase 29 and unblock Phase 31. Cheap insurance.
- **LOW — Counter naming consistency.** Plan 03 uses `new_units, changed_units, skipped_units, hidden_units, failed_units, reused_units, chunks_indexed`. Some are redundant with each other (`hidden_units` overlap with low-signal classification?). Worth pinning what each maps to before implementation.

---

## Overall Risk: **MEDIUM**

**Justification:** The cycle 2 replan addressed the cycle 1 HIGH issues (edit delivery via watermark, message-level vs dialog-level binding refs, deployment connectivity). The remaining HIGHs (`e_meta = e_text` hack, unverified `save_chunks` behavior, phantom HTTP transport in URL config, cursor+watermark interleave) are all addressable with narrow plan edits — none are structural. Phase 29's TDD discipline and concrete grep acceptance criteria mean the plan-execution gap should be small once these are pinned.

**Top 5 fixes that would lower risk to LOW:**
1. Refactor `_embed_meta_component` to accept generic dicts; remove `e_meta = e_text` hack.
2. Add a behavior-pinning test for `save_chunks(file_paths=[])` before any Telegram test.
3. Drop `DOTMD_TELEGRAM_DAEMON_URL` (or add HTTP transport to Plan 01).
4. Add cursor+watermark interleave fixture to Plan 01 with explicit checkpoint advance assertion.
5. Add docker-compose socket bind-mount as a Plan 04 task 3 deliverable, not a precondition.

---

## OpenCode Review

# Phase 29 Plan Review — Cycle 2

## Plan 01: mcp-telegram Source Export API

### Summary

Plan 01 adds the structured export/read-window API to the `mcp-telegram` daemon. It correctly addresses the cycle 1 feedback about edited message delivery via `updated_after` watermark and handles negative dialog IDs with `rsplit(":message:", 1)`. The TDD structure with two tasks (tests then implementation) is clean.

### Strengths

- The `updated_after` watermark mechanism for delivering edited messages is a meaningful improvement over cursor-only pagination and directly addresses the cycle 1 HIGH concern.
- Cursor parsing with `rsplit(":message:", 1)` correctly handles negative dialog IDs like `-1001`.
- Explicit test assertions against rendered `list_messages` output enforce the D-11 boundary.
- `unit_updated_at` computation using `max(sent_at, edit_date)` is documented as a simplification with a clear Phase 30 note about delete lifecycle.

### Concerns

- **[HIGH] Mixed sort order for identity + update streams:** The plan describes two separate orderings — "primary bootstrap rows by dialog_id ASC, message_id ASC" and "edited/update-watermark rows by unit_updated_at ASC, dialog_id ASC, message_id ASC" — but doesn't specify how they merge into a single result set. A SQL query can only have one ORDER BY. If these are two sub-queries concatenated, the `checkpoint_cursor` (identity-based) from a row in the update stream could cause the next identity-ordered call to skip past valid new messages. The plan needs to specify a single deterministic merge order or explicitly separate the two streams into distinct response fields.

- **[MEDIUM] Batch limit clamping semantics for dual-stream results:** With `limit=500` and two OR'd filters, does the limit apply to the total combined result or per-stream? If total, an initial bootstrap with many edited messages could fill the limit before reaching new messages at the identity cursor position.

- **[LOW] `unit_updated_at` fallback when no cache timestamp exists:** The plan says "if no cache update timestamp exists, use `max(sent_at, edit_date)`". This is reasonable but means a message edited yesterday will have `unit_updated_at = yesterday` while an unedited message sent today has `unit_updated_at = today`. The `updated_after` watermark comparison works correctly with this, but it should be documented that `unit_updated_at` is NOT a sync timestamp — it's a content-change timestamp.

### Suggestions

- Specify a single merged sort order (e.g., all rows sorted by `unit_updated_at ASC, dialog_id ASC, message_id ASC`) and let the identity cursor also work within that ordering, OR separate the response into `identity_rows` and `update_rows` with separate cursors. The current "two orderings in one batch" description will cause implementation ambiguity.
- Add a test case where an edited message has `message_id` numerically BEFORE the identity cursor AND `edit_date` after the `updated_after` watermark — this is the critical edge case the `updated_after` mechanism exists to solve, and the test should assert it appears in the result.
- Consider adding `has_more: bool` alongside `next_cursor` so the client doesn't need to compare cursors to detect pagination end.

---

## Plan 02: dotMD Telegram Provider

### Summary

Plan 02 maps structured export payloads into dotMD's provider contract with clean separation from Telegram internals. The low-signal classification is conservative and well-specified with bilingual vocabulary. The fingerprint design includes all relevant metadata fields.

### Strengths

- `TelegramSourceClientProtocol` enforces the D-11 boundary at the type system level — dotMD never sees Telethon or sync_db.
- `public_ref_for_unit` is a simple, deterministic function that's easy to test and reason about.
- Low-signal vocabulary includes both English and Russian tokens with `casefold()` normalization.
- Fingerprint serialization uses sorted JSON keys with explicit `None`/`null` for missing fields — this prevents key-ordering drift across Python versions.
- The grep guard test (no `telethon`/`sync_db`/`list_messages` imports) is a good defensive pattern.

### Concerns

- **[MEDIUM] Fixture payloads may diverge from actual export format:** Plan 02 tests use hand-crafted JSON payloads. If Plan 01's actual export format differs (different key names, nesting, null handling), the provider mapping will silently break. There's no schema contract test between the two plans.

- **[LOW] `order_key` assumes non-negative message IDs per dialog:** The plan acknowledges this and Telegram message IDs are indeed positive integers within a dialog, so this is safe. But if dotMD ever needs to ingest non-Telegram chat sources with negative message IDs, `f"{message_id:020d}"` would produce incorrect sort order for negative values.

- **[LOW] Emoji-only detection via `unicodedata.category(ch).startswith("S")`:** This catches Symbol categories but will also classify characters like `©`, `°`, `±` as emoji-like. For a conservative classifier this is acceptable, but worth a brief comment in the implementation.

### Suggestions

- Add a shared schema test or contract fixture file (e.g., `backend/tests/ingestion/telegram_export_sample.json`) that Plan 01's tests and Plan 02's fixture factory both reference. This catches format drift between the two repos without coupling their test runs.
- Consider making `is_low_signal_telegram_text` return a structured result or setting a `low_signal_reason` in metadata so Phase 31 can tune the heuristic without re-indexing.
- The `ApplicationSourceChangeBatch.updated_after` field addition to `models.py` is clean but consider naming it `max_updated_after` to distinguish it from a filter parameter vs. a returned watermark value.

---

## Plan 03: dotMD Telegram Ingestion

### Summary

Plan 03 is the core ingestion path that persists Telegram source documents, bindings, fingerprints, chunks, and checkpoints. It addresses key concerns about `file_paths=[]` Telegram chunks, text-only embeddings without `FileInfo`, and explicit FTS5 metadata. The approach is well-aligned with the existing pipeline architecture.

### Strengths

- The `ApplicationSourceIngestResult` dataclass with explicit count fields (`discovered`, `new_units`, `changed_units`, etc.) provides the structured metrics the should-have requirements call for.
- `file_paths=[]` with provenance-based lookup (`get_chunks_by_source_unit_ref`) cleanly separates Telegram chunks from the M2M file-path join pattern.
- Checkpoint committed inside the transaction after all persistence succeeds — this is crash-safe.
- `e_meta = e_text` fusion is a pragmatic Phase 29 simplification that avoids the `FileInfo` dependency without changing the dual-component table contract.
- Explicit FTS5 metadata via `file_meta={"": (title, "telegram")}` prevents accidental blank title/tags.

### Concerns

- **[HIGH] Single-batch vs. loop semantics for initial bootstrap:** `ingest_application_source` calls `provider.export_changes(checkpoint_cursor, limit)` once and processes the returned batch. For initial bootstrap with thousands of messages and `limit=500`, only 500 messages would be ingested per call. The plan doesn't specify whether the method loops internally or whether the CLI/operator must call it repeatedly. For the MVP smoke (`--limit 10`), this is fine, but the plan should document that a full initial ingest requires multiple calls or an explicit loop.

- **[HIGH] Transaction boundary across metadata + vector stores:** The plan says "commit checkpoint inside the successful transaction" but SQLite metadata and sqlite-vec vector data are in `index.db` (same file). If vector writes fail after chunk/FTS metadata is written, does the rollback cover both? The plan should confirm that all writes (metadata, FTS, vectors) happen within a single SQLite transaction or document the partial-write recovery path.

- **[MEDIUM] `delete_chunks_for_source_unit` cascading:** When an edited message triggers chunk replacement, the plan says to "remove previous Telegram chunk/provenance/FTS/vector rows for that unit before replacement." Deleting vector rows from sqlite-vec requires knowing the chunk IDs. The helper needs to: (1) find chunk IDs by provenance, (2) delete from `chunks_<strategy>`, (3) delete from `chunk_source_provenance_<strategy>`, (4) delete from `chunk_file_paths_<strategy>` (no-op for empty), (5) delete from FTS, (6) delete from vec table. This is a multi-step cascade that should be atomic.

- **[MEDIUM] Metadata prefix in chunk text affects FTS search quality:** Prepending compact metadata lines (dialog, sender, sent_at, topic) to chunk `text` means FTS5 will index sender names and timestamps as searchable content. A search for "John" would match messages from John even if the content doesn't mention John. This is a design trade-off worth documenting — it's not wrong, but it changes search semantics for Telegram content vs. filesystem content.

- **[LOW] `reused_units` count is hardcoded to 0:** The plan acknowledges this. It's honest but means Phase 30 will need to revisit the count semantics.

### Suggestions

- Clarify whether `ingest_application_source` loops until the export returns an empty batch or is a single-batch call. For the MVP, a single-batch call with explicit operator re-invocation is simpler and easier to debug. Document this choice.
- Add a helper method like `_delete_telegram_chunk_cascade(chunk_ids, strategy, conn)` that handles all six deletion steps atomically, with a test that verifies no orphan rows remain after a replacement.
- Consider prefixing metadata lines with a marker (e.g., `[meta]`) so future FTS tokenizers or search logic can distinguish metadata content from message content if needed.
- Add a test for concurrent ingest attempts — the existing `fcntl.flock` should protect the pipeline, but an explicit test that a second ingest call while one is in progress fails gracefully would be valuable.

---

## Plan 04: Telegram Read/Drill Resolver And Smoke

### Summary

Plan 04 adds resolver support for Telegram message refs in `read()` and `drill()`, a bounded CLI smoke command, and documentation updates. It correctly scopes live smoke to the ingestion boundary only and defers full search round-trip validation to Phase 31.

### Strengths

- The fallback order for `read()` (live provider first, then stored chunks) means reads work even when mcp-telegram is unavailable after ingestion.
- `_parse_telegram_message_ref` extracting dialog-level `document_ref` from message-level ref for binding checks is the right granularity.
- `--dry-run` flag on the CLI command is a safe default for operational smoke.
- Explicit connectivity verification commands before claiming live smoke pass.
- "Do not fabricate a pass" instruction for unavailable runtimes is good operational hygiene.

### Concerns

- **[HIGH] Docker networking path is unspecified:** Plan 04 adds `DOTMD_TELEGRAM_DAEMON_SOCKET` and `DOTMD_TELEGRAM_DAEMON_URL` config but doesn't determine which path is actually deployed. The threat model identifies this but the resolution is deferred to execution. If the executor picks socket bind-mount, the `mcp-telegram` Unix socket must be in a shared volume. If URL, the containers must share a Docker network. The actual compose change is not in any plan's file list. This is an operational gap that could block the live smoke.

- **[MEDIUM] `read(ref, start, end)` semantic shift:** For filesystem refs, `start`/`end` are chunk offsets. For Telegram refs, they map to `before`/`after` window sizes. This means the same `read(ref, 2, 4)` call has different semantics depending on the ref type. The plan documents the mapping but doesn't discuss whether the MCP contract should normalize this or whether callers need to handle both semantics.

- **[MEDIUM] The `drill()` return shape isn't fully specified:** The plan says "return title/source_uri/document_type/parser_name plus Telegram metadata from SourceDocument.metadata_json" but doesn't define whether the return type is a new model, a dict, or extends the existing `drill()` return. If it extends the existing return, what happens to `frontmatter` field that filesystem docs return?

- **[LOW] `just typecheck` and `just lint` as acceptance criteria with ratchet escape hatch:** "exits 0 or records a pre-existing ratchet" is pragmatic but means a plan could be marked complete with new typecheck/lint warnings if the executor decides they're pre-existing.

### Suggestions

- Add the Docker compose/networking change (socket volume mount or network join) to the file list in Plan 04 task 2 or 3. The smoke cannot pass without it, so it should be planned, not discovered during execution.
- Define an explicit `TelegramDrillResult` or document how the existing `drill()` return shape accommodates Telegram metadata. At minimum, specify that `frontmatter` is `{}` for Telegram refs.
- Consider adding a `dotmd telegram status` CLI command (or extending the existing `status` command) that checks provider connectivity and reports the current checkpoint without ingesting. This is useful for operations and doesn't require the full ingest path.
- For the `start`/`end` → `before`/`after` mapping, document in the MCP tool description that Telegram refs use window semantics so callers can adjust expectations.

---

## Cross-Plan Assessment

### Dependency Chain Risks

The wave structure (1 → 2 → 3 → 4) is correct but creates a single critical path. If Plan 01's export API design needs revision during execution, all downstream plans are affected. The mixed sort order issue in Plan 01 is the most likely source of rework.

### Missing Test Coverage

- No test covers the **full pipeline** from Plan 01 export format → Plan 02 provider mapping → Plan 03 ingestion → Plan 04 read/drill. Each plan tests its layer in isolation with fixtures. An end-to-end fixture test that exercises the full path with a single set of test data would catch integration bugs early.
- No test covers **partial batch failure** (e.g., vector write failure at message 250 of a 500-message batch) and subsequent resume.

### Scope Adherence

All four plans stay within the Phase 29 boundary. The deferral of search quality, lifecycle policy, and full live smoke to Phase 31 is consistently maintained across plans. The `--dry-run` flag and explicit Phase 31 references in docs are good scope guards.

---

## Overall Risk Assessment: **MEDIUM**

**Justification:** The plans are well-structured and address cycle 1 feedback. The main risks are:

1. **Plan 01's dual-stream sort order ambiguity** (HIGH) — could cause implementation confusion or missed messages during execution. Requires clarification before execution.
2. **Transaction boundary across metadata + vector writes** (HIGH in Plan 03) — crash safety depends on correct transaction scoping. Documented but untested.
3. **Docker networking gap** (HIGH in Plan 04) — the live smoke depends on infrastructure not specified in any plan's file list.
4. **Fixture format divergence** between Plans 01 and 02 (MEDIUM) — no shared schema contract between repos.

None of these are blocking if addressed during execution, but the sort order issue in Plan 01 should be resolved before the executor starts coding to avoid rework in Plans 02-04.

---

## Consensus Summary

Cycle 2 confirms that the replan closed several cycle 1 blockers, especially edit delivery, negative dialog-id cursor parsing, message-level read/ref handling, and explicit storage/search decisions for Telegram chunks. The remaining risk is concentrated in the transition from a filesystem-indexing pipeline to a mixed filesystem/application-source pipeline: the export pagination contract, transaction boundaries, storage helper assumptions, and production daemon connectivity still need sharper plan commitments before execution.

### Agreed Strengths
- The phase remains correctly split across mcp-telegram export, dotMD provider mapping, ingestion, and read/drill smoke work.
- Both reviewers agree the `updated_after` watermark is a real improvement over cursor-only edit detection.
- The plans preserve the boundary that dotMD must not parse Telethon internals, `sync_db`, or human-rendered `list_messages` output.
- The TDD structure and grep guards are concrete enough to guide execution.

### Agreed Concerns
- HIGH: Plan 01 still underspecifies how identity-cursor bootstrap rows and `updated_after` update rows merge into one deterministic batch/checkpoint contract.
- HIGH: Plan 03 needs stronger proof around shared storage writes: empty `file_paths`, chunk/vector/FTS replacement, and transaction rollback boundaries.
- HIGH: Plan 04 still leaves production mcp-telegram connectivity ambiguous, especially URL-vs-socket transport and compose/network deliverables.
- MEDIUM: Several integration contracts remain fixture-local rather than shared across the mcp-telegram export, dotMD provider, ingestion, and resolver layers.

### Divergent Views
- Claude treats `e_meta = e_text` as a HIGH-risk semantic shortcut and recommends refactoring `_embed_meta_component` for generic source metadata; OpenCode views it as an acceptable Phase 29 simplification.
- OpenCode raises full-bootstrap loop semantics and transaction scoping as HIGH concerns; Claude emphasizes the unverified `save_chunks(file_paths=[])` assumption and trickle-lock coordination.
- Claude flags the `DOTMD_TELEGRAM_DAEMON_URL` HTTP assumption directly; OpenCode frames the same area as an unspecified Docker/socket/network deployment path.

### Current HIGH Concerns
- Cursor plus watermark interleave/mixed ordering is under-specified in Plan 01.
- `unit_updated_at` precision and equality/tie-break semantics are not pinned in Plan 01.
- `e_meta = e_text` may weaken the dual-component embedding contract in Plan 03.
- `save_chunks(file_paths=[])` is a load-bearing assumption without a behavior-pinning test in Plan 03.
- Telegram daemon transport/deployment connectivity remains ambiguous in Plan 04.
- Plan 04 dependency metadata omits the direct Plan 01 daemon API dependency.
- Initial bootstrap single-batch vs loop semantics are not specified in Plan 03.
- Metadata, FTS5, and vector write transaction boundaries are not verified in Plan 03.

CYCLE_SUMMARY: current_high=8
