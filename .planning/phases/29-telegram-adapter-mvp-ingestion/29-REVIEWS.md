---
phase: 29
reviewers: [claude, opencode]
reviewed_at: 2026-05-08T00:15:28+05:00
plans_reviewed:
  - .planning/phases/29-telegram-adapter-mvp-ingestion/29-01-mcp-telegram-source-export-PLAN.md
  - .planning/phases/29-telegram-adapter-mvp-ingestion/29-02-dotmd-telegram-provider-PLAN.md
  - .planning/phases/29-telegram-adapter-mvp-ingestion/29-03-dotmd-telegram-ingestion-PLAN.md
  - .planning/phases/29-telegram-adapter-mvp-ingestion/29-04-telegram-read-drill-and-smoke-PLAN.md
---

# Cross-AI Plan Review - Phase 29

## Claude Review

# Phase 29 Plan Review - Telegram Adapter MVP Ingestion

## Plan 01: mcp-telegram Source Export API

### Summary
Adds three structured daemon methods (`describe_source`, `export_source_changes`, `read_source_unit_window`) on the mcp-telegram side. Scope is narrow and well-bounded. Test fixtures cover the synced-status filter and stable cursor shape. The biggest unaddressed concern is what happens when previously-exported messages are *edited* - cursor-only forward pagination cannot surface them, which conflicts with Plan 02's edit-fingerprint assertion.

### Strengths
- Cross-repo scope is explicit and minimal - just three handlers + client wrappers.
- Cursor shape `telegram:v1:dialog:<dialog_id>:message:<message_id>` is versioned and future-proof.
- Test asserts `not_synced` exclusion and absence of rendered `[resolved:` text - protects D-11.
- Limit clamping (1..500) and before/after clamping (0..50) prevent abuse.

### Concerns
- **HIGH - Edit detection is invisible to forward pagination.** The daemon emits records sorted by `(dialog_id, message_id)` past the cursor. An edit to an already-exported message won't reappear in `export_source_changes`. Plan 02 task 1 asserts "edited payload changes the fingerprint" and Plan 03 task 1 asserts "edit reindexes changed unit only" - but Plan 01 has no mechanism to *deliver* edits to dotMD. Either: (a) daemon needs an `updated_after` parameter or `edits` channel, (b) explicitly defer edit handling to Phase 30 and remove the edit assertions from later plans.
- **MEDIUM - Negative dialog ID cursor parsing.** Telegram supergroup/channel IDs are large negatives. The cursor should specify a parser such as `rsplit(":message:", 1)` rather than relying on a plain `split(":")`.
- **MEDIUM - Newly-synced older dialogs.** If a smaller dialog id becomes synced after the cursor has passed it, those messages can sort before the cursor and never be emitted.
- **LOW - Test action is vague on schema.** `topic_title` should be concrete: either it is stored or it is not.

### Suggestions
- Decide explicitly whether edits are in or out of scope for Phase 29. If out, remove `edit_date` change assertions from Plans 02/03 and document edits as Phase 30 work. If in, add an `updated_after` filter to `export_source_changes`.
- Add a test for cursor parsing of negative dialog IDs.
- Specify the `read_source_unit_window` payload shape in the test.

### Risk: **MEDIUM**

## Plan 02: dotMD Telegram Provider

### Summary
Maps daemon export payloads to `SourceDocument`/`SourceUnit`/`ApplicationSourceChangeBatch`. Conservative low-signal classifier and deterministic fingerprinting. Cleanly scoped, no Telethon imports, grep-asserted. Two real gaps: bilingual coverage in the low-signal vocabulary, and the concrete client wiring is left to a later executor decision.

### Strengths
- Grep guards (`telethon`, `sync_db`, `list_messages` absent) directly enforce D-11.
- Fingerprint includes `sent_at`, `edit_date`, `is_deleted`, `sender_id`, `topic_id`, `reply_to_msg_id` - covers D-16 fixture matrix.
- `standalone_search` metadata flag is a clean way to thread D-09 through to the ingestion path.
- Duplicate low-signal-with-different-ids test pins a real correctness invariant.

### Concerns
- **MEDIUM - Bilingual gap in low-signal vocabulary.** The project is RU/EN; low-signal set is English-only. Russian equivalents are equally common in Telegram.
- **MEDIUM - Emoji-only detection unspecified.** This is non-trivial in Python without a dependency. The plan should specify the approach.
- **LOW - `TelegramApplicationSourceProvider` constructor not specified.** Tests presumably instantiate it with a fake client; signature should be explicit.
- **LOW - `order_key=f"{message_id:020d}"` assumes non-negative.** Telegram message IDs within a dialog are non-negative, so this is safe but should be a visible assumption.

### Suggestions
- Pick the casefold list approach explicitly and either include common RU tokens or explicitly defer them.
- Specify the emoji-only detection approach.
- Add a test asserting fingerprint stability across equal-content batches.

### Risk: **LOW-MEDIUM**

## Plan 03: dotMD Telegram Ingestion

### Summary
The keystone plan adds `IndexingPipeline.ingest_application_source()` that persists Telegram batches as documents, bindings, fingerprints, chunks, provenance, and checkpoints atomically. Threat model is good. The biggest risk is a schema-compatibility unknown: the existing M2M chunk schema may not accept chunks with `file_paths=[]`, and existing FTS5/vector helpers may key on file path.

### Strengths
- Atomic checkpoint commit only after local persistence - D-14 honored.
- Explicit guard against `dotmd index --force`, `self.run()`, `_purge_file`, filesystem discovery.
- Replay-skip and edit-reindex tests pin the message-level recomputation invariant.
- Result counts surface enough metrics for Phase 30 sync metrics.

### Concerns
- **HIGH - Empty `file_paths` may not satisfy the M2M schema.** Phase 16 introduced `chunks <-> file_paths` many-to-many. If the schema or helper code treats absent file paths as invalid, this plan's `file_paths=[]` approach breaks. Verification is needed before execution.
- **HIGH - FTS5 and vector write helpers may require file path.** Existing helpers were written for filesystem chunks. Concrete code inspection is required to confirm they work or to specify a wrapper.
- **MEDIUM - `reused_units` semantically undefined.** Result has both `skipped_units` and `reused_units`. Define or remove one.
- **MEDIUM - Compact metadata embedded in chunk text affects embeddings.** This is consistent with context-prefix injection, but the plan should state that Telegram chunks intentionally carry metadata in text.
- **MEDIUM - No regression test for filesystem chunks coexisting with Telegram chunks.**
- **LOW - `record_source_checkpoint_error` path is asserted but not tested.**

### Suggestions
- Before execution, spike the schema and helper compatibility for chunks with zero file paths.
- Define `reused_units` vs `skipped_units`, or drop one.
- Add a mixed filesystem plus Telegram ingestion regression test.
- Add a failure-rollback test for checkpoint error handling.

### Risk: **MEDIUM-HIGH**

## Plan 04: Telegram Read/Drill Resolver and Smoke

### Summary
Wires Telegram-aware branches into `read(ref)` and `drill(ref)`, adds a CLI smoke command, and updates docs. Right scope for groundwork before Phase 31. The CLI smoke command and production daemon connectivity are underspecified.

### Strengths
- Inactive-binding rejection test protects D-15/R2 visibility invariant.
- `_filesystem_path_for_source` non-call assertion via grep is a strong guard.
- Live smoke instructions explicitly say not to fabricate a pass.
- Docs separation between Phase 29 delivered state and Phase 31 deferred work is clear.

### Concerns
- **HIGH - Production daemon connectivity unspecified for live smoke.** The smoke command requires the dotMD container to reach the mcp-telegram daemon, but no env var, network config, or socket path is added in the plans.
- **MEDIUM - `read(ref, start, end)` semantic shift.** Existing contract is line-based for files. Telegram semantics should be defined in the test.
- **MEDIUM - CLI command name is a TBD.** Pin the name before execution.
- **LOW - Drill payload `frontmatter` ambiguity.** Pick either absent or `{}`.
- **LOW - Scope creep risk.** A new top-level `dotmd telegram` namespace may be more than Phase 29 needs.

### Suggestions
- Add an explicit daemon URL/socket config for Plan 04 and verify it before live smoke.
- Decide and pin the CLI command name and `start/end` semantics.
- Consider whether the CLI surface is in scope or whether a service-layer bounded smoke is enough.

### Risk: **MEDIUM**

## Cross-Cutting Observations

- Wave numbering is misleading because the plans are sequential, not parallel.
- Edit-detection consistency needs a Plan 01-level decision or removal of edit assertions from later plans.
- Cross-repo coordination should state commit/deployment order.
- Graph extraction for Telegram is not addressed; likely deferred, but should be explicit.

## Overall Risk Assessment: **MEDIUM**

Two high-confidence blockers need resolution before execution: M2M/storage helper compatibility for non-filesystem chunks and the edit-delivery mismatch. A third blocker, production daemon connectivity, needs either verification or a config addition before the smoke step.

---

## OpenCode Review

# Cross-AI Plan Review: Phase 29 - Telegram Adapter MVP Ingestion

## Plan 01: mcp-telegram Source Export API

### Summary
Clean, well-scoped TDD plan that adds structured export/read-window API to the mcp-telegram daemon. The cross-repo boundary is clearly defined and the plan correctly avoids exposing private SQLite internals.

### Strengths
- Precise TDD structure: tests first, then implementation, with concrete fixture data.
- Correctly scopes to synced/syncing/access_lost dialogs only, excluding not_synced.
- Cursor shape `telegram:v1:dialog:<dialog_id>:message:<message_id>` is deterministic and supports multi-dialog pagination via `(dialog_id, message_id)` sort order.
- Explicit guards against rendering `list_messages` text in export payloads.
- Limit clamping and window clamping prevent abuse.

### Concerns
- **MEDIUM**: Cross-repo coordination risk - Plans 02-04 depend on the exact JSON payload shape from Plan 01, but the payload contract is defined in prose, not a shared schema.
- **LOW**: The cursor format includes a `v1` version prefix but no migration strategy is discussed if the format changes. Acceptable for MVP.

### Suggestions
- Extract the export payload shape into a documented contract that both repos can reference.
- Add a test that asserts the exported JSON is valid against a minimal schema.

### Risk Assessment: **LOW**

## Plan 02: dotMD Telegram Provider

### Summary
Solid mapping layer between mcp-telegram JSON payloads and dotMD's Pydantic domain models. The low-signal classification is conservative and well-tested. The clean protocol boundary prevents coupling to Telegram internals.

### Strengths
- `TelegramSourceClientProtocol` correctly decouples dotMD from mcp-telegram internals.
- `is_low_signal_telegram_text` is deterministic, conservative, and fixture-tested.
- Tests include the required edge cases for duplicate short messages, edited fingerprints, and rapid chats.
- Grep guard against `telethon`/`sync_db`/`list_messages` imports is a good defensive pattern.

### Concerns
- **MEDIUM**: Tests reference `public_ref_for_unit(change.unit)` but this function is not defined anywhere in the plan's implementation task or the existing codebase.
- **LOW**: Fingerprint includes optional fields. The plan should specify how missing optional fields affect fingerprint computation.

### Suggestions
- Define `public_ref_for_unit` explicitly, preferably `f"telegram:{unit.unit_ref}"`.
- Specify deterministic handling of missing optional metadata fields.

### Risk Assessment: **LOW**

## Plan 03: dotMD Telegram Ingestion

### Summary
The most complex plan in the phase. It adds an application-source ingestion path to the pipeline, but underspecifies critical integration points with the existing embedding, FTS5, and vector subsystems.

### Strengths
- Correctly adds `ingest_application_source` as a focused method rather than routing Telegram through filesystem discovery.
- Checkpoint-committed-after-local-persistence pattern is correct.
- Rollback plus `record_source_checkpoint_error` on exception is sound error handling.
- Low-signal suppression at chunk creation time is the right layer.
- Test coverage for unchanged replay, edit-only reindex, and low-signal chunk suppression.

### Concerns
- **HIGH**: **Embedding path underspecified.** The existing pipeline's embedding flow requires `FileInfo` for the metadata component (`_embed_meta_component` encodes `title + tags` from frontmatter). Telegram messages have no frontmatter. The plan does not decide whether Telegram uses e_meta, what text feeds it, or whether Telegram chunks use e_text only.
- **HIGH**: **FTS5 integration gap.** `FTS5SearchEngine.add_chunks()` accepts `file_meta: dict[str, tuple[str, str]]` keyed by file path string. Telegram chunks have `file_paths=[]`, so the insertion path can produce empty title/tags columns. The plan does not address whether this is intentional for Phase 29 or an integration gap.
- **MEDIUM**: **Chunk discovery for read/drill.** Chunks with `file_paths=[]` will not appear in file-path-based lookups. The provenance table tracks them, but there is no planned helper such as `get_chunks_by_provenance`.
- **MEDIUM**: **`source_unit_refs` overwrite in binding upsert.** A dialog-level binding upsert with a single source unit ref can leave only the last message in the binding's informational field.
- **MEDIUM**: **Provenance ref is document-level, not message-level.** `ChunkProvenance.ref` becomes `telegram:dialog:-1001`, while D-03 requires message-level refs.

### Suggestions
- Specify the embedding strategy for Telegram chunks explicitly. The reviewer recommends text-only embeddings for Phase 29.
- Add a `get_chunks_by_source_provenance` helper in `SQLiteMetadataStore`.
- Accumulate `source_unit_refs` in binding upsert or explicitly make the fingerprint table authoritative for unit tracking.
- Decide whether Phase 29 accepts dialog-level refs or changes provenance to message-level refs.

### Risk Assessment: **HIGH**

## Plan 04: Telegram Read/Drill Resolver and Smoke

### Summary
Adds initial Telegram resolver support to `DotMDService.read()` and `drill()` plus a bounded CLI smoke command. Correctly scopes to Phase 29 ingestion boundary. However, the critical ref-parsing integration with `_require_active_source_document` is underspecified.

### Strengths
- Clear Phase 29/31 boundary.
- Dry-run smoke command is safe.
- Test structure is sound: active binding resolution, window shape, inactive rejection.
- Explicit instruction not to fabricate a live smoke pass.

### Concerns
- **HIGH**: **`_parse_ref` breaks on message-level refs.** Existing parsing and active-binding checks would treat `telegram:dialog:-1001:message:42` as document ref `dialog:-1001:message:42`, but bindings are keyed by `dialog:-1001`. The plan says to extend `_require_active_source_document` or add a wrapper, but does not specify the mechanism.
- **MEDIUM**: **How `read(ref)` retrieves Telegram chunks is unclear.** Existing `read()` is file-path based. The plan should decide whether reads query stored chunks by provenance, call the provider, or store the provider on the service.
- **LOW**: A new top-level `dotmd telegram` CLI group is the first source-specific CLI surface. A generic `dotmd source ingest --source telegram` may age better.

### Suggestions
- Pre-decide the ref resolution mechanism, such as mapping `telegram:dialog:-1001:message:42` to document ref `dialog:-1001` for active-binding checks.
- Prefer stored chunk retrieval by provenance so reads do not depend on mcp-telegram availability.
- Add a dedicated `get_chunks_for_source_document` helper.

### Risk Assessment: **HIGH**

## Cross-Cutting Observations

### Dependency Chain
The wave structure is sequential and correct: Plan 01 can execute independently, Plans 02-03 depend on the API shape, and Plan 04 depends on ingestion and provider behavior.

### Missing: How Telegram Chunks Enter Search
No plan explicitly addresses how Telegram chunks become discoverable by the search pipeline. Semantic and FTS5 paths can work if vectors and FTS rows are written, but graph search is not covered and should be documented as out of scope for the MVP.

### Provenance Ref Level Mismatch
`ChunkProvenance.ref` is document-level by existing convention, while D-03 requires message-level refs. Either accept dialog-level refs for Phase 29 with a Phase 31 follow-up, or change provenance to include message identity and adjust active-binding joins.

## Overall Phase Risk: **MEDIUM-HIGH**

Three issues need resolution before or during execution:

1. **Embedding strategy for Telegram** - Plan 03, HIGH.
2. **Ref parsing for message-level Telegram refs** - Plan 04, HIGH.
3. **Provenance ref level** - cross-cutting, MEDIUM.

All three are design decisions rather than implementation errors. The plans identify the right questions but do not pre-answer them.

---

## Consensus Summary

Both reviewers agree the phase is valuable and mostly scoped correctly, but execution should not start until a small set of storage/search/ref decisions are made explicit. The main shared risk is that Telegram is a non-filesystem source, while parts of the current indexing/search/read path still assume file paths or document-level refs.

### Agreed Strengths
- The phase is correctly split into mcp-telegram export, dotMD provider mapping, ingestion, and resolver/smoke work.
- The plans preserve the important boundary: no Telethon or mcp-telegram SQLite internals inside dotMD.
- Tests and grep guards are concrete and aligned with the source-adapter design direction.
- The checkpoint-after-local-persistence approach is sound and avoids cursor loss.

### Agreed Concerns
- **HIGH - Non-filesystem chunk persistence and search indexing are underspecified.** This includes empty `file_paths`, vector/FTS helper compatibility, and whether Telegram chunks need a text-only embedding path.
- **HIGH - Message-level refs are not fully reconciled with active binding and provenance rules.** The existing document-level binding model needs an explicit resolver for `telegram:dialog:<id>:message:<id>`.
- **HIGH - Edit delivery is inconsistent across plans.** Later plans test edit reindexing, but the export cursor API cannot deliver edits for already-exported messages.
- **HIGH - Live smoke connectivity needs a documented runtime path.** The dotMD container must know how to reach the mcp-telegram daemon.
- **MEDIUM - Read/drill retrieval should be provenance-based or otherwise explicitly specified, not left to the executor.**
- **MEDIUM - Cross-repo payload shape should be pinned with a contract/schema-style test.**

### Divergent Views
- Claude treats `file_paths=[]` schema compatibility as the core storage blocker; OpenCode focuses more on embedding metadata and FTS5 semantics. These are closely related and should be resolved together before Plan 03 execution.
- Claude raises production daemon connectivity as HIGH; OpenCode did not highlight it as a top issue. Because Phase 04 includes live smoke, the concern remains unresolved until verified.
- OpenCode recommends accepting dialog-level refs as a Phase 29 limitation or changing provenance; Claude emphasizes message-level edit delivery and smoke readiness. Both point to the same need: make the public ref contract explicit before execution.

### Current HIGH Concerns
- Edit delivery mechanism mismatch: cursor-only export cannot surface edits to already-exported messages while later plans test edit reindexing.
- M2M storage compatibility: chunks with `file_paths=[]` may not be representable or may bypass required file-path joins.
- Embedding strategy for Telegram chunks: existing metadata embedding path expects filesystem `FileInfo`/frontmatter, and Telegram behavior is not specified.
- FTS5/vector helper compatibility: existing write helpers may require file-path metadata or produce degraded/incorrect rows for Telegram chunks.
- Production daemon connectivity: the dotMD container's runtime path to mcp-telegram is not specified for live smoke.
- Message-level ref resolution: existing active-binding/provenance parsing does not clearly map message refs to dialog-level bindings.
