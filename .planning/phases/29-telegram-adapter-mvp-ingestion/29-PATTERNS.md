# Phase 29 Pattern Map: Telegram Adapter MVP Ingestion

**Generated:** 2026-05-07
**Purpose:** Give executors exact local analogs before implementing Phase 29.

## Files To Create Or Modify

| Target | Role | Closest Existing Analog | Notes |
|--------|------|-------------------------|-------|
| `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_api.py` | Add source export/read-window daemon handlers | `_list_messages`, `_list_messages_context_window`, `_dispatch` | Keep output raw structured JSON. Do not reuse formatted MCP text. |
| `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_client.py` | Add client wrappers for new daemon methods | `list_messages`, `get_sync_status` | Wrappers should pass `cursor`, `limit`, `unit_ref`, `before`, and `after` exactly. |
| `/home/j2h4u/repos/j2h4u/mcp-telegram/tests/test_daemon.py` | Daemon export/read-window tests | Existing patched sync DB daemon tests | Fixture rows should cover synced dialogs, topics, replies, edits, deleted flags, cursor paging. |
| `backend/src/dotmd/ingestion/telegram_provider.py` | dotMD provider/client mapping | `backend/src/dotmd/ingestion/source_provider.py`, test fixture provider | No Telethon or `mcp_telegram.sync_db` imports. |
| `backend/tests/ingestion/test_telegram_provider.py` | Provider mapping and low-signal tests | `backend/tests/ingestion/test_application_source_provider.py` | Use fixture payloads, not live daemon. |
| `backend/src/dotmd/ingestion/pipeline.py` | Application-source ingest path | `_index_file`, `_index_file_embed`, source checkpoint helpers | Add a focused method rather than pretending Telegram is a file. |
| `backend/tests/ingestion/test_telegram_ingestion.py` | Ingestion persistence/replay tests | `test_source_filesystem.py`, `test_metadata_m2m.py` | Assert documents, active bindings, source-unit fingerprints, chunk provenance, checkpoints. |
| `backend/src/dotmd/api/service.py` | Telegram read/drill resolver branch | `_require_active_source_document`, filesystem `read`, filesystem `drill` | Keep filesystem behavior unchanged; Telegram branch must not read frontmatter. |
| `backend/tests/api/test_service_search.py` | Resolver regression tests | Existing `drill(ref)` and inactive-binding tests | Add Telegram ref read/drill tests with fake provider/client. |
| `docs/mcp-telegram-source-contract.md` | Update contract note from planned to implemented payload shape | Existing Phase 28 contract note | Keep Phase 31 public smoke explicitly deferred. |
| `docs/source-adapter-architecture.md` | Record Phase 29 delivered state after execution | Phase 28 delivered state | Include no-full-reindex note. |

## Pattern Details

### Structured Daemon Methods

`DaemonAPIServer._dispatch()` is a linear method router. Add explicit source methods there and keep daemon-side SQL/private storage hidden behind that JSON API. This satisfies D-11 while avoiding a direct dotMD dependency on `sync.db`.

### Provider Mapping

Follow the Phase 28 fixture provider pattern: provider methods return Pydantic `ApplicationSourceDescription`, `ApplicationSourceChangeBatch`, and `SourceUnitWindow`. Mapping helpers should validate the ref shape and fingerprint inputs before constructing domain models.

### Chunk Provenance

Telegram chunks must carry `ChunkProvenance(namespace="telegram", document_ref="dialog:<id>", ref="telegram:dialog:<id>", source_unit_refs=[unit_ref], chunk_strategy=<active strategy>, parser_name="telegram-message")`. For anchored context chunks, `source_unit_refs` may include neighboring refs but the public search ref stays anchored to the target message.

### Checkpoint Ownership

Use `SQLiteMetadataStore.commit_source_checkpoint(namespace, checkpoint_cursor, conn=conn)` only inside the transaction that has already persisted the source document, binding, fingerprint, chunk/provenance rows, FTS/vector state, and diagnostics needed for that batch.

### Resolver Branch

`DotMDService.read()` and `drill()` currently call `_filesystem_path_for_source()`. Add a Telegram branch after active-binding validation. Do not add frontmatter or file path fallbacks for Telegram.

## Risk Notes

- Cross-repo execution should commit dotMD and `mcp-telegram` changes separately.
- Low-signal filtering must never drop source-unit fingerprints or provenance.
- The first live smoke may find zero synced messages; execution should report that honestly rather than fabricating a pass.
- Full public search quality validation remains Phase 31; do not let Phase 29 expand into ranking experiments.
