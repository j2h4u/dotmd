# Phase 28: Application Source Provider Contract - Research

**Researched:** 2026-05-07
**Domain:** Application-backed source provider protocol, source cursors, unit fingerprints, fixture validation, mcp-telegram contract boundary
**Confidence:** HIGH for dotMD codebase facts; MEDIUM for mcp-telegram future export shape because it is a proposed contract note, not implemented there yet.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Phase 28 should define a minimal generic provider contract, not a Telegram-only import path and not a broad plugin framework.
- **D-02:** The contract must work for future sources such as Slack, Notion, PDFs, and other services. Telegram is the first proof source, not the only design target.
- **D-03:** dotMD must not read `mcp-telegram` private SQLite tables directly. Any Telegram data consumed by dotMD must come through a structured, machine-oriented export/source contract.
- **D-04:** The minimum provider methods for Phase 28 are: `describe_source`, `export_changes(cursor, limit)`, and `read_unit_window(unit_ref, before, after)`.
- **D-05:** `export_changes` is the core pull primitive. For this phase it returns active records only, not mandatory delete/hidden/tombstone events. Full delete/hidden lifecycle semantics remain deferred.
- **D-06:** Do not add separate `export_documents` or `export_units` methods in Phase 28 unless research proves they are necessary for the smallest working contract. Documents and units can be included in `export_changes` payloads.
- **D-07:** The provider contract should include `checkpoint_cursor` semantics. dotMD saves the checkpoint only after the corresponding local persistence/indexing transaction succeeds.
- **D-08:** A single simple `next_cursor` is not sufficient as the only durable progress marker because saving it too early can lose data after a crash.
- **D-09:** Provider processing must be idempotent: seeing the same active record and fingerprint again should be safe and should not force redundant indexing work.
- **D-10:** Every provider must expose a stable `SourceDocument` envelope. Examples: Telegram dialog, Slack channel/thread, Notion page, PDF document.
- **D-11:** dotMD should process content through a unified `SourceUnit` shape. Providers emit real units when the source naturally has them, and dotMD can normalize simple document-only sources into one implicit root unit.
- **D-12:** Telegram should use real message units from the start. Slack should later use message/thread units. Notion and PDFs may begin with an implicit root unit and later move to block/page/section units when stable parsing makes that useful.
- **D-13:** A `SourceUnit` is the smallest provider-owned sync/indexing item that dotMD can fingerprint and reuse. It should not be over-modeled with source-specific Telegram/Slack/Notion concepts in the generic contract.
- **D-14:** Required minimum fields for a `SourceUnit` are `namespace`, `document_ref`, `unit_ref`, `text`, `fingerprint`, `updated_at`, `order_key`, and `metadata_json`.
- **D-15:** Lifecycle status such as `deleted`, `hidden`, or `tombstone` is not mandatory in Phase 28. Providers may carry such source-specific state in `metadata_json`, and a later lifecycle phase can promote it into the common contract if needed.
- **D-16:** `read_unit_window(unit_ref, before, after)` should be required by the provider contract.
- **D-17:** Providers that do not have meaningful neighboring units may return a fallback window containing only the requested unit.
- **D-18:** This keeps `search -> ref -> read/drill` behavior consistent while avoiding artificial complexity for simple sources.
- **D-19:** Phase 28 should include a short `mcp-telegram` contract note with example payloads, not a full `mcp-telegram` implementation plan.
- **D-20:** The note should show Telegram dialog as `SourceDocument`, Telegram message as `SourceUnit`, `export_changes(cursor, limit)` with `checkpoint_cursor`, and `read_unit_window(unit_ref, before, after)` with neighboring message context.
- **D-21:** The note should be concrete enough that Phase 29 can plan Telegram ingestion without re-opening the integration boundary.
- **D-22:** Research and planning may use graphify/codebase graph outputs to navigate relationships and find relevant code clusters faster.
- **D-23:** graphify is advisory only. Downstream agents must verify graphify findings against live source files before making a plan or code change.

### the agent's Discretion

- Decide exact Python names for provider protocol classes and payload models as long as they follow existing Protocol/Pydantic style and remain minimal.
- Decide whether the fixture provider lives under ingestion, tests, or a small provider module, as long as it exercises the provider contract without live Telegram.
- Decide the exact shape of `metadata_json` examples, but keep common fields minimal and avoid encoding Telegram-specific semantics into generic models.

### Deferred Ideas (OUT OF SCOPE)

- Telegram ingestion implementation.
- Full incremental Telegram sync.
- Full delete/hidden/tombstone lifecycle in the common provider contract.
- Separate `export_documents` and `export_units` methods.
- Direct Telegram API client inside dotMD.
- Generic plugin marketplace or UI for arbitrary source apps.
- Slack, Notion, Google Docs, and PDF parser implementation beyond contract examples/fixtures.
</user_constraints>

## Project Constraints (from AGENTS.md)

- Work on branch `dev`; `main` tracks upstream and is not a development target.
- Public APIs go through `api/service.py`; do not expose storage internals directly.
- Never reload indexes per request.
- Never run `dotmd index --force` while the container is running; avoid hidden full reindex by default.
- New storage backends implement `storage/base.py`; new extractors implement `extraction/base.py`; new search engines implement `search/base.py`.
- Production uses a single dotMD MCP HTTP process plus external TEI/FalkorDB; code changes should be batched for restart.

<research_summary>
## Summary

Phase 28 can be implemented as a narrow contract foundation with no new external dependency and no full reindex. The live dotMD checkout already has the core pieces a provider contract should reuse: `SourceDocument`, `SourceUnit`, `ResourceBinding`, `ChunkProvenance`, source-ref-first `read/drill`, and active-binding filtering. The missing pieces are a small application-provider protocol, payload models for export batches and read windows, durable checkpoint/source-unit fingerprint helpers, a fixture provider that proves the contract without Telegram, and a concrete mcp-telegram payload note for Phase 29.

The graphify report was useful only as navigation and was stale against the live checkout (`d6578da6` vs current `e90bbf0`). All findings below were verified against live source files.
</research_summary>

<standard_stack>
## Standard Stack

No new external library is needed.

| Component | Current Tool | Role |
|-----------|--------------|------|
| Models | Pydantic v2 | Existing `SourceDocument`, `SourceUnit`, `ResourceBinding`, and new provider payload models. |
| Provider boundary | `typing.Protocol` | Matches existing `SourceAdapterProtocol` style in `backend/src/dotmd/ingestion/source.py`. |
| Storage | SQLite | Existing metadata store plus source checkpoint and source-unit fingerprint tables. |
| Tests | pytest via `uv run pytest` | Fixture provider, storage helpers, and contract documentation checks. |
| Docs | Markdown | Architecture update plus `mcp-telegram` contract note. |
</standard_stack>

<architecture_patterns>
## Architecture Patterns

### Pattern 1: Protocol and Pydantic Payloads

`backend/src/dotmd/ingestion/source.py` already uses a Protocol for filesystem discovery. Use the same style for application-backed providers, but keep it adjacent or in a new small module so filesystem discovery is not forced through application sync semantics.

Recommended names:

- `ApplicationSourceProviderProtocol`
- `ApplicationSourceDescription`
- `ApplicationSourceChange`
- `ApplicationSourceChangeBatch`
- `SourceUnitWindow`

The concrete minimum batch shape should be:

```python
class ApplicationSourceChange(BaseModel):
    document: SourceDocument
    unit: SourceUnit

class ApplicationSourceChangeBatch(BaseModel):
    changes: list[ApplicationSourceChange]
    next_cursor: str | None = None
    checkpoint_cursor: str | None = None
```

This satisfies D-06 by carrying document and unit data in `export_changes` rather than adding separate export methods.

### Pattern 2: Checkpoint Cursor Saved After Transaction

Persist source checkpoint state in metadata storage, but make helper naming force the safe ordering:

1. provider returns `changes`, `next_cursor`, and `checkpoint_cursor`;
2. dotMD persists documents/units/bindings/provenance/fingerprints in one transaction;
3. only inside or immediately after that successful transaction does dotMD call a helper such as `commit_source_checkpoint(namespace, checkpoint_cursor, *, conn)`.

Do not store `next_cursor` as durable progress before local persistence succeeds.

### Pattern 3: SourceUnit as the Reuse Boundary

`SourceUnit` exists but currently lacks `updated_at`; Phase 28 should add it and test that units require D-14 fields. Source-unit fingerprints should be persisted independently from dialog/document fingerprints so future Telegram incremental sync can skip unchanged messages without hashing an entire dialog.

### Pattern 4: Fixture Provider Before Telegram Adapter

A deterministic fixture provider should emit:

- one Telegram-like dialog document with message units;
- one document-only source normalized to an implicit root unit;
- stable cursors and duplicate batches proving idempotent fingerprint behavior;
- `read_unit_window()` for a middle message and fallback single-unit window for a document-only source.

This proves the provider contract without live Telegram or direct reads from `mcp-telegram` private SQLite.
</architecture_patterns>

<mcp_telegram_findings>
## mcp-telegram Boundary Findings

The current `mcp-telegram` runtime already has daemon/client primitives that can inform a future export API:

- `DaemonConnection` sends newline-delimited JSON over a Unix socket and already exposes `list_messages`, `search_messages`, `list_dialogs`, `mark_dialog_for_sync`, and `get_sync_status`.
- `ReadMessage` rows expose stable `dialog_id`, `message_id`, `sent_at`, `text`, sender fields, media description, reply/topic metadata, deletion/edit markers, and dialog name.
- `sync_db.py` stores `messages` keyed by `(dialog_id, message_id)` and `synced_dialogs` with sync status/progress fields.
- Existing MCP tools are human/agent-facing and formatted; Phase 28 should not make dotMD depend on those rendered responses.

The contract note should propose structured daemon/MCP payloads that map:

```text
SourceDocument(namespace="telegram", document_ref="dialog:<dialog_id>")
SourceUnit(unit_ref="dialog:<dialog_id>:message:<message_id>")
```

The note must not require dotMD to instantiate Telethon or read `sync.db` directly.
</mcp_telegram_findings>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: Accidental Telegram-Only Naming

Names such as `TelegramProvider`, `TelegramCursor`, or `dialog_message` in generic models would leak the first source into the contract. Use generic names and keep Telegram examples in docs/tests.

### Pitfall 2: Persisting `next_cursor` Too Early

Saving `next_cursor` before local persistence can skip messages after a crash. Store `checkpoint_cursor` only after the successful local transaction.

### Pitfall 3: Treating Rendered MCP Output as an Indexing API

`list_messages` and `search_messages` produce human-oriented text and snippets. dotMD needs machine payloads with stable refs, timestamps, fingerprints, metadata, and cursor fields.

### Pitfall 4: Adding Delete Semantics Prematurely

The panel previously recommended delete events, but Phase 28 explicitly defers mandatory lifecycle events. Preserve lifecycle fields in `metadata_json` only; do not design tombstone behavior into the common contract yet.

### Pitfall 5: Reindex Hidden Cost

Adding provider protocol, source checkpoints, and source-unit fingerprints is additive metadata work. It should not require `dotmd index --force`, TEI re-embedding, vector/FTS rebuild, or graph rebuild.
</common_pitfalls>

## Validation Architecture

Automated validation should cover:

1. Provider model/protocol tests for D-04, D-06, D-14, and D-16 through fixture payloads.
2. Storage tests for checkpoint and source-unit fingerprint persistence, including idempotent duplicate active records and checkpoint-after-transaction helper usage.
3. Fixture provider tests proving message-window and single-unit fallback behavior without live Telegram.
4. Documentation grep/tests proving the mcp-telegram contract note includes `checkpoint_cursor`, `SourceDocument`, `SourceUnit`, `read_unit_window`, and says dotMD does not read private `mcp-telegram` SQLite tables.

Recommended focused commands:

```bash
cd backend && uv run pytest tests/ingestion/test_application_source_provider.py tests/storage/test_metadata_m2m.py -q
cd backend && uv run pytest tests/ingestion/test_source_filesystem.py tests/api/test_service_search.py -q
just typecheck
just lint
```

<sources>
## Sources

### Primary (HIGH confidence)

- `.planning/phases/28-application-source-provider-contract/28-CONTEXT.md` - locked decisions and boundary.
- `.planning/REQUIREMENTS.md` - R3, R4, R8 acceptance criteria.
- `backend/src/dotmd/core/models.py` - existing source document/unit/binding/provenance models.
- `backend/src/dotmd/ingestion/source.py` - existing Protocol-style source adapter boundary.
- `backend/src/dotmd/storage/metadata.py` - resource bindings, provenance, active filtering helpers, metadata-store patterns.
- `backend/src/dotmd/api/service.py` and `backend/src/dotmd/mcp_server.py` - source-ref-first public behavior.
- `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_client.py`, `daemon_api.py`, `models.py`, `sync_db.py` - current mcp-telegram daemon and message data shape.

### Secondary (MEDIUM confidence)

- `docs/source-adapter-architecture.md` - source adapter contract and Telegram mirror notes.
- `docs/source-adapter-architecture-panel-review.md` - cursor/idempotency/provider API concerns.
- `.planning/graphs/GRAPH_REPORT.md` - stale navigation aid only; verified against live source before use.
</sources>

## RESEARCH COMPLETE
