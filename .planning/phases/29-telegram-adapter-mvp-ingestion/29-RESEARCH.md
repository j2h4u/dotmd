# Phase 29: Telegram Adapter MVP Ingestion - Research

**Researched:** 2026-05-07
**Domain:** Telegram structured export through mcp-telegram, dotMD application-source ingestion, message source-unit provenance, low-signal message handling, initial Telegram read/drill resolver support
**Confidence:** HIGH for dotMD codebase facts; MEDIUM for mcp-telegram export shape because the structured export API is not yet implemented there.

<user_constraints>
## User Constraints From CONTEXT.md

### Locked Decisions

- **D-01:** Ingest all Telegram dialogs already available/synced through `mcp-telegram`; do not add a separate dotMD allowlist in Phase 29.
- **D-02:** `mcp-telegram` owns Telegram coverage/sync state. dotMD consumes a structured source export.
- **D-03:** Public refs anchor concrete messages: `telegram:dialog:<dialog_id>:message:<message_id>`.
- **D-04:** `read(ref)` returns a window around the target message.
- **D-05:** `drill(ref)` exposes Telegram dialog/message metadata without filesystem frontmatter.
- **D-06:** A Telegram message is the durable `SourceUnit` and recomputation/provenance boundary.
- **D-07:** Do not use word-count merge blocks as primary identity.
- **D-08:** Substantive messages can be indexed as message-anchored chunks with compact Telegram context.
- **D-09:** Low-signal messages are stored as source units but should not become standalone normal search hits.
- **D-10:** If richer context is needed, keep the public ref anchored to one concrete message and record all included source units.
- **D-11:** dotMD must not read private `mcp-telegram` SQLite tables or parse human-rendered `list_messages`.
- **D-12:** If needed, include the minimal `mcp-telegram` structured export/source API change.
- **D-13:** Keep the API aligned with `describe_source`, `export_changes(cursor, limit)`, checkpoint cursor semantics, and `read_unit_window`.
- **D-14:** Live smoke only proves `mcp-telegram export -> dotMD ingest -> Telegram records exist in dotMD metadata/index state`.
- **D-15:** Full public `search -> ref -> read/drill` smoke remains Phase 31; Phase 29 adds enough resolver support/tests for Phase 31 to harden.
- **D-16:** Fixtures cover short acknowledgements, duplicate short messages, rapid chats, topic/reply metadata, edit fingerprint changes, and unchanged replay/idempotency.
- **D-17/D-18:** Graphify output is advisory only and must be verified against live source files.

### Deferred / Out Of Scope

- Full incremental sync hardening, lifecycle delete/edit policy, attachments/media, bidirectional Telegram actions, shared contact/entity catalog, generic plugin marketplace, and full public search/read/drill live smoke.
</user_constraints>

<research_summary>
## Summary

Phase 29 should be planned as a narrow MVP ingestion slice with four boundaries:

1. Add a structured export/read-window API to `mcp-telegram` because the existing daemon/MCP methods expose useful raw data but not the Phase 28 provider contract.
2. Add a dotMD Telegram provider/client that maps structured export payloads to `SourceDocument` and `SourceUnit`.
3. Add an application-source ingestion path in dotMD that persists Telegram documents, active bindings, source-unit fingerprints, chunk provenance, FTS/vector rows, and safe checkpoints without whole-dialog recomputation.
4. Add initial Telegram `read(ref)` / `drill(ref)` resolver support and fixture/live-smoke checks for the ingestion boundary only.

This can be done without `dotmd index --force`, a full TEI re-embedding pass, FTS/vector rebuild, or graph rebuild. New Telegram units will be encoded as new chunks; unchanged units should be skipped by `source_unit_fingerprints`.
</research_summary>

<current_code_findings>
## dotMD Findings

- `backend/src/dotmd/core/models.py` already defines `SourceDocument`, `SourceUnit`, `SourceUnitWindow`, `ApplicationSourceDescription`, `ApplicationSourceChange`, and `ApplicationSourceChangeBatch`.
- `backend/src/dotmd/ingestion/source_provider.py` already defines `ApplicationSourceProviderProtocol` with `describe_source`, `export_changes`, and `read_unit_window`.
- `backend/src/dotmd/storage/metadata.py` already has additive source checkpoint and source-unit fingerprint helpers: `commit_source_checkpoint`, `get_source_checkpoint`, `record_source_checkpoint_error`, and `upsert_source_unit_fingerprint`.
- `backend/tests/ingestion/application_source_fixtures.py` already provides a deterministic fixture provider with offset cursors and neighboring-unit windows.
- `backend/src/dotmd/api/service.py` currently resolves active refs, but `read()` and `drill()` still require filesystem-backed documents through `_filesystem_path_for_source`.
- `backend/src/dotmd/ingestion/chunker.py` can attach caller-owned `ChunkProvenance` to chunks, but `chunk_file()` still wants a `Path` and frontmatter parsing semantics. Phase 29 needs either a small message chunk builder or a content wrapper that does not pretend Telegram is a filesystem file.
- `IndexingPipeline` already owns chunk persistence, vector writes, FTS writes, and provenance persistence for filesystem files. Phase 29 should add a focused application-source method instead of routing Telegram through filesystem discovery.

## mcp-telegram Findings

- `DaemonConnection` sends newline-delimited JSON to the daemon and already has wrappers for `list_messages`, `search_messages`, `list_dialogs`, `mark_dialog_for_sync`, and `get_sync_status`.
- `DaemonAPIServer._dispatch()` currently handles those methods but has no structured source export/read-window method.
- `ReadMessage` exposes stable `dialog_id`, `message_id`, `sent_at`, `text`, sender fields, reply/topic metadata, delete/edit flags, and dialog name.
- `sync_db.py` stores messages keyed by `(dialog_id, message_id)` and synced dialog state. dotMD must not read that SQLite database directly, but daemon-side code may use it to serve structured exports.
- `list_messages(context_message_id=..., context_size=...)` can already serve an anchor window, but it is a generic read tool response, not a source-provider payload with source refs, fingerprints, and checkpoints.
</current_code_findings>

<implementation_strategy>
## Recommended Implementation Strategy

### Structured mcp-telegram Export

Add daemon/client methods named `describe_source`, `export_source_changes`, and `read_source_unit_window` or similarly explicit source-oriented names. The payloads should be stable JSON dicts matching the Phase 28 contract, not rendered text.

Recommended cursor for the MVP:

```text
telegram:v1:dialog:<dialog_id>:message:<message_id>
```

Sort exported units by `(dialog_id, message_id)` over all synced dialogs that have status `synced`, `syncing`, or `access_lost` and have stored messages. This satisfies D-01 by using all available synced dialogs while staying deterministic. The export should include `checkpoint_cursor` for the last emitted unit in each non-empty batch.

### dotMD Telegram Provider

Create a small provider module such as `backend/src/dotmd/ingestion/telegram_provider.py` with:

- `TelegramMCPClientProtocol` or `TelegramSourceClientProtocol`
- `TelegramApplicationSourceProvider(ApplicationSourceProviderProtocol)`
- pure mapping helpers from source export dicts to Pydantic domain models
- deterministic fingerprint helpers using normalized text plus relevant metadata

Do not import Telethon or `mcp_telegram.sync_db` in dotMD.

### dotMD Ingestion Path

Add an `IndexingPipeline.ingest_application_source(provider, *, limit=...)` style method. It should:

1. read `get_source_checkpoint("telegram")`;
2. call `provider.export_changes(checkpoint_cursor, limit)`;
3. skip unchanged units via `upsert_source_unit_fingerprint`;
4. create/refresh `SourceDocument` and active `ResourceBinding`;
5. create Telegram chunks only for substantive units, attaching `ChunkProvenance(namespace="telegram", document_ref=..., source_unit_refs=[unit_ref], ...)`;
6. add vector/FTS rows for new/changed chunks;
7. commit `checkpoint_cursor` only after local persistence succeeds;
8. record counts for discovered/new/changed/skipped/hidden/failed/reused.

Low-signal units should still be fingerprinted and bound but not emitted as standalone normal chunks. A conservative default is: stripped normalized text length under a small threshold or in an acknowledgement vocabulary, with emoji-only and punctuation-only messages treated as low signal.

### Initial Resolver Support

Extend `DotMDService.read()` and `drill()` with a Telegram branch:

- `read(ref)` parses `telegram:dialog:<dialog_id>:message:<message_id>`, uses provider/client `read_unit_window(unit_ref, before, after)`, and returns chunks/window records anchored on the target message.
- `drill(ref)` resolves active binding/document metadata and returns Telegram metadata without calling filesystem frontmatter parsing.

Phase 29 tests should prove the resolver shape with fixtures. Live smoke should stop at export/import/metadata/index state; Phase 31 owns public search round-trip smoke.
</implementation_strategy>

<common_pitfalls>
## Common Pitfalls

- Parsing `list_messages` human text would violate D-11 and create brittle ingestion.
- Hashing an entire dialog would violate D-06/R5 because one new message would force recomputation for unchanged messages.
- Merging short messages into word-count blocks as primary identity would violate D-07 and make refs ambiguous.
- Saving the provider cursor before local chunk/fingerprint/provenance persistence can lose units after a crash.
- Reusing filesystem holder tables as the public identity for Telegram would regress the Phase 26 source-ref-first contract.
- A live public search/read/drill proof belongs to Phase 31; Phase 29 should not overreach into search quality hardening.
</common_pitfalls>

## Validation Architecture

Automated validation should cover:

1. `mcp-telegram` structured export/read-window tests with fixture sync DB rows: synced dialog filtering, cursor pagination, checkpoint cursor, topic/reply/edit/delete metadata, and no rendered text parsing.
2. dotMD provider mapping tests: ref shape, fingerprints, metadata fields, no Telethon/private SQLite import, and low-signal classification.
3. dotMD ingestion tests: source documents, active resource bindings, source-unit fingerprints, chunk provenance, checkpoint-after-transaction, unchanged replay skipped, edited unit changed.
4. dotMD resolver tests: Telegram `drill(ref)` metadata and `read(ref)` window shape without filesystem frontmatter.
5. Focused runtime smoke: daemon export returns at least one structured unit; dotMD ingest records Telegram metadata/index rows.

Recommended commands:

```bash
cd /home/j2h4u/repos/j2h4u/mcp-telegram && uv run pytest tests/test_daemon.py -q
cd backend && uv run pytest tests/ingestion/test_application_source_provider.py tests/ingestion/test_telegram_provider.py tests/ingestion/test_telegram_ingestion.py tests/api/test_service_search.py -q
just typecheck
just lint
```

<sources>
## Sources

- `.planning/phases/29-telegram-adapter-mvp-ingestion/29-CONTEXT.md`
- `.planning/REQUIREMENTS.md`
- `docs/mcp-telegram-source-contract.md`
- `docs/source-adapter-architecture.md`
- `backend/src/dotmd/core/models.py`
- `backend/src/dotmd/ingestion/source_provider.py`
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/src/dotmd/api/service.py`
- `backend/tests/ingestion/application_source_fixtures.py`
- `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_api.py`
- `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_client.py`
- `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/models.py`
- `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/sync_db.py`
</sources>

## RESEARCH COMPLETE
