---
phase: 33-source-lifecycle-config-auth-cursor-boundary
verified: 2026-05-08T15:56:47Z
status: passed
score: 21/21 must-haves verified
overrides_applied: 0
---

# Phase 33: Source lifecycle/config/auth/cursor boundary Verification Report

**Phase Goal:** Build the lifecycle service that constructs source runtimes from registry entries, typed config, credentials, cursor state, and runtime helpers.
**Verified:** 2026-05-08T15:56:47Z
**Status:** passed
**Re-verification:** No - initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | Source runtimes are built through one lifecycle/factory boundary. | VERIFIED | `SourceRuntimeFactory.build()` consumes registry descriptor, config store, credential provider, cursor store, and constructs filesystem/Telegram bundles in `backend/src/dotmd/ingestion/source_lifecycle.py:242-310`. |
| 2 | Credentials are accessed through a provider interface, not direct secret reads inside adapters. | VERIFIED | `SourceCredentialProviderProtocol.get_access()` is the credential boundary; `DefaultSourceCredentialProvider` returns no-auth or delegated access and rejects missing delegated refs in `source_lifecycle.py:91-100` and `source_lifecycle.py:152-184`. Static scan found no raw Airweave/Telethon/private Telegram SQLite access in runtime source. |
| 3 | Cursor commits happen only after local persistence succeeds. | VERIFIED | `SQLiteSourceCursorStore.commit_checkpoint()` requires caller `conn=` and delegates to metadata storage without committing in `source_lifecycle.py:187-225`; pipeline calls it after local writes/vectors inside `BEGIN` at `pipeline.py:490-505` and `pipeline.py:675-699`. |
| 4 | Filesystem and Telegram construction paths use the lifecycle boundary. | VERIFIED | Pipeline filesystem discovery and FileInfo bridge call `build("filesystem")` in `pipeline.py:1298-1314` and `pipeline.py:1362-1385`; service and CLI build Telegram through lifecycle in `service.py:202-214` and `cli.py:461-478`. |
| 5 | Airweave is architecture reference only, not runtime dependency. | VERIFIED | Static scan `rg -n "from airweave|import airweave" backend/src backend/tests` returned no matches; docs record Airweave-lite adaptation without runtime import. |
| 6 | Lifecycle returns a full minimal runtime bundle, not a bare object. | VERIFIED | `SourceRuntimeBundle` exposes descriptor, typed config, access, cursor store, source/provider, and metadata; factory returns this bundle for both filesystem and Telegram in `source_lifecycle.py:263-295`. |
| 7 | Runtime bundle remains inspectable for planning, tests, and debugging. | VERIFIED | Bundle fields are public Pydantic fields, and tests assert descriptor/config/access/provider/source/cursor store details in `test_source_lifecycle.py`. |
| 8 | Source config stays in local config store; descriptors do not hold runtime config or credential material. | VERIFIED | `SourceConfigRecord` separates `config` and `credential_ref`; `InMemorySourceConfigStore` stores records by namespace in `source_lifecycle.py:67-80` and `source_lifecycle.py:126-148`. Runtime settings are seeded by `source_runtime_factory_from_settings()`, not descriptors. |
| 9 | Local config store may hold typed config values and credential references but not raw secrets. | VERIFIED | Strict Pydantic models use `extra="forbid"` and expose only `socket_path`, `paths`, `exclude`, and `credential_ref`; raw token/password/secret validation rejection is covered by `test_telegram_lifecycle_does_not_accept_raw_secret_fields`. |
| 10 | Runtime construction fails fast on missing or invalid required config/credential references. | VERIFIED | Factory raises `SourceLifecycleConfigError` for missing filesystem paths, missing Telegram socket, unsupported config type, namespace mismatch, missing delegated target, and missing delegated credential ref in `source_lifecycle.py:161-179` and `source_lifecycle.py:312-342`. |
| 11 | `checkpoint_cursor` is durable progress; `next_cursor` remains only provider continuation hint. | VERIFIED | Pipeline reads durable checkpoint via `cursor_store.get_checkpoint()` and commits only `batch.checkpoint_cursor`; CLI dry-run prints `next_cursor` without committing in `pipeline.py:466-481`, `pipeline.py:685-695`, and `cli.py:466-475`. |
| 12 | Filesystem does not claim provider-owned cursor commits. | VERIFIED | Filesystem bundle has `source=FilesystemMarkdownSourceAdapter()` and no provider in `source_lifecycle.py:269-279`; filesystem tests assert provider is `None`. Pipeline filesystem call sites do not commit provider checkpoints. |
| 13 | Filesystem paths remain internal holder mechanics and not public identity. | VERIFIED | Pipeline bridge still asserts filesystem source refs while lifecycle only supplies adapter construction in `pipeline.py:1316-1328` and `pipeline.py:1370-1380`; filesystem lifecycle tests preserve `filesystem:<resolved_path>` ref semantics. |
| 14 | Phase 26 source-ref-first guardrail is preserved. | VERIFIED | No public search/read shape changes found; `test_pipeline_source_document_for_file_info_uses_lifecycle_adapter` checks lifecycle bridge preserves concrete filesystem refs. |
| 15 | Phase 27 retained-artifact visibility gate is preserved. | VERIFIED | Phase 33 did not alter retained-artifact binding logic; focused source filesystem suite passed, covering active bindings and holder mechanics. |
| 16 | Telegram remains delegated to `mcp-telegram`; dotMD is not a direct Telegram API client. | VERIFIED | Settings helper seeds `credential_ref="mcp-telegram"` in `source_lifecycle.py:360-371`; credential provider returns delegated access. Static scan found no `Telethon`, `telegram.client`, or private Telegram SQLite runtime access. |
| 17 | dotMD consumes structured `mcp-telegram` provider payloads, not private SQLite tables or human-rendered output. | VERIFIED | Lifecycle constructs `UnixSocketTelegramSourceClient` and `TelegramApplicationSourceProvider` inside the lifecycle boundary; no private SQLite reads were found in runtime source. |
| 18 | Telegram refs remain concrete message refs that round-trip through read/drill. | VERIFIED | Existing Telegram provider/API tests are included in the focused phase suite; no changes to Telegram ref parser or read/drill shape were introduced by lifecycle wiring. |
| 19 | Filesystem config is seeded from live settings paths and excludes. | VERIFIED | `source_runtime_factory_from_settings()` uses `settings.indexing_paths` and `settings.effective_indexing_exclude` in `source_lifecycle.py:345-358`; no `resolved_indexing_paths` alias exists. |
| 20 | Optional Telegram service startup works without a configured socket. | VERIFIED | `build_if_configured("telegram")` returns `None` when no record/socket exists in `source_lifecycle.py:299-310`; service uses it in `service.py:207-214`. |
| 21 | CLI Telegram ingest uses lifecycle after socket validation. | VERIFIED | `dotmd telegram ingest` validates configured socket, then calls `service._pipeline.source_runtime_factory.build("telegram")` and passes the bundle to `ingest_application_source_runtime()` in `cli.py:454-478`. |

**Score:** 21/21 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `backend/src/dotmd/ingestion/source_lifecycle.py` | Lifecycle factory, config store, credential provider, cursor store, runtime bundle | VERIFIED | Substantive implementation with typed configs, protocols, factory, settings helper, delegated Telegram config, and transaction-owned cursor wrapper. |
| `backend/src/dotmd/ingestion/pipeline.py` | Filesystem and application-source lifecycle integration | VERIFIED | Stores `_source_runtime_factory`; filesystem call sites use `build("filesystem")`; application-source ingest accepts lifecycle bundle and uses `SourceCursorStoreProtocol`. |
| `backend/src/dotmd/api/service.py` | Optional Telegram provider construction through lifecycle | VERIFIED | `_build_telegram_provider()` calls `build_if_configured("telegram")`; static scan found no direct Telegram provider/client construction in service. |
| `backend/src/dotmd/cli.py` | Telegram ingest construction through lifecycle | VERIFIED | CLI validates socket, builds Telegram runtime through lifecycle, and ingests with `ingest_application_source_runtime()`. |
| `backend/tests/ingestion/test_source_lifecycle.py` | Lifecycle contract and credential/cursor tests | VERIFIED | Contains tests for bundle contents, config seeding, raw secret rejection, required delegated credential ref, and rollback-owned cursor commits. |
| `backend/tests/ingestion/test_source_filesystem.py` | Filesystem lifecycle regression tests | VERIFIED | Contains tests proving pipeline discovery and FileInfo bridge obtain filesystem adapter through lifecycle. |
| `backend/tests/ingestion/test_telegram_ingestion.py` | Telegram lifecycle cursor and rollback tests | VERIFIED | Contains tests proving lifecycle cursor store get/commit/error calls and rollback behavior on transaction failure. |
| `backend/tests/api/test_service_search.py` | Service lifecycle provider regression | VERIFIED | Contains test proving `_build_telegram_provider()` uses lifecycle factory. |
| `backend/tests/storage/test_metadata_m2m.py` | Storage transaction/cursor regression | VERIFIED | Included in focused phase suite and broad local gate. |
| `docs/source-adapter-architecture.md` | Phase 33 lifecycle documentation | VERIFIED | Documents runtime bundles, delegated `mcp-telegram`, no raw Telegram auth, checkpoint semantics, and no full reindex. |
| `docs/source-registry-airweave-mapping.md` | Airweave-lite runtime boundary documentation | VERIFIED | Documents Phase 33 runtime bundle/factory adaptation and rejects Airweave runtime imports/platform subsystems. |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `IndexingPipeline.__init__` | `source_runtime_factory_from_settings()` | Factory assignment | VERIFIED | `pipeline.py:234-237` creates the lifecycle factory from live settings and metadata store. |
| Filesystem pipeline methods | Filesystem adapter | `self._source_runtime_factory.build("filesystem")` | VERIFIED | `_discover_documents`, `_discover_documents_multi`, and `_source_document_for_file_info` all route through lifecycle. |
| `DotMDService._build_telegram_provider()` | Telegram provider | `build_if_configured("telegram")` | VERIFIED | Optional service startup uses lifecycle and returns `None` when unconfigured. |
| `dotmd telegram ingest` | Telegram runtime bundle | `source_runtime_factory.build("telegram")` | VERIFIED | CLI socket checks precede lifecycle build; ingest receives lifecycle bundle. |
| Application-source ingest | Cursor persistence | `SourceCursorStoreProtocol` | VERIFIED | `get_checkpoint`, `commit_checkpoint`, and `record_error` calls are all through cursor store protocol. |
| Lifecycle factory | Telegram delegated access | `DefaultSourceCredentialProvider.get_access()` | VERIFIED | Delegated Telegram build requires concrete `credential_ref` and produces `SourceAccess(kind="delegated")`. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|---|---|---|---|---|
| `source_runtime_factory_from_settings()` | Filesystem config paths/excludes | `Settings.indexing_paths`, `Settings.effective_indexing_exclude` | Yes | FLOWING |
| `source_runtime_factory_from_settings()` | Telegram socket and credential ref | `Settings.telegram_daemon_socket`, hardcoded credential ref name `mcp-telegram` | Yes, ref only, no raw secret | FLOWING |
| `SourceRuntimeFactory.build("filesystem")` | Filesystem source adapter | Registry descriptor plus config/access/cursor store | Yes | FLOWING |
| `SourceRuntimeFactory.build("telegram")` | Telegram provider | Registry descriptor, typed socket config, delegated access, client factory | Yes | FLOWING |
| `IndexingPipeline._ingest_application_source()` | Checkpoint state | `cursor_store.get_checkpoint(namespace)` and provider batch checkpoint | Yes | FLOWING |
| `DotMDService._telegram_provider` | Optional provider | Pipeline lifecycle factory `build_if_configured("telegram")` | Yes when configured, `None` when absent | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Focused Phase 33 test suite | `cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_telegram_ingestion.py tests/ingestion/test_telegram_provider.py tests/api/test_service_search.py tests/storage/test_metadata_m2m.py -q` | `128 passed, 71 warnings in 5.72s` | PASS |
| Broad local regression gate | `just check` | User-provided evidence: Ruff clean; pyright ratchet 50 errors vs baseline 69; selected local pytest `443 passed, 36 deselected, 183 warnings` | PASS |
| No Airweave runtime import | `rg -n "from airweave|import airweave" backend/src backend/tests` | No matches | PASS |
| No direct Telegram/private SQLite runtime access | `rg -n "Telethon|telegram\\.client|sqlite.*telegram|telegram.*sqlite" backend/src backend/tests` | No matches | PASS |
| Filesystem pipeline no direct adapter construction | `rg -n "FilesystemMarkdownSourceAdapter\\(\\)" backend/src/dotmd/ingestion/pipeline.py` | No matches | PASS |
| Service/CLI no direct Telegram provider/client construction | `rg -n "TelegramApplicationSourceProvider\\(|UnixSocketTelegramSourceClient\\(" backend/src/dotmd/api/service.py backend/src/dotmd/cli.py` | No matches | PASS |
| No resolved-indexing-path alias | `rg -n "resolved[_]indexing[_]paths" backend/src/dotmd/ingestion/source_lifecycle.py` | No matches | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| LIFE-01 | 33-01, 33-02, 33-03 | dotMD can construct source runtimes through one lifecycle service/factory from registry entry, typed config, credentials, and cursor state. | SATISFIED | `SourceRuntimeFactory` and `SourceRuntimeBundle` exist and are wired into filesystem, Telegram service, CLI, and pipeline ingest. |
| LIFE-02 | 33-01, 33-03 | Credentials are accessed through a provider interface; source adapters do not read raw secret storage directly. | SATISFIED | `SourceCredentialProviderProtocol` and `DefaultSourceCredentialProvider`; Telegram requires `credential_ref="mcp-telegram"` and strict models reject raw secret fields. |
| LIFE-03 | 33-01, 33-03 | Cursor/checkpoint commits happen only after local persistence succeeds. | SATISFIED | `SQLiteSourceCursorStore.commit_checkpoint()` requires caller `conn`; pipeline commits checkpoint inside transaction after local writes and rolls back before error recording. |
| LIFE-04 | 33-02, 33-03 | Filesystem and Telegram construction paths use the lifecycle boundary instead of bespoke adapter setup. | SATISFIED | Filesystem pipeline call sites use `build("filesystem")`; service uses `build_if_configured("telegram")`; CLI uses `build("telegram")`. |

No orphaned Phase 33 requirements were found: `.planning/REQUIREMENTS.md` maps only LIFE-01 through LIFE-04 to Phase 33, and all appear in plan frontmatter.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---:|---|---|---|
| `backend/src/dotmd/ingestion/pipeline.py` | multiple | SQL variable name `placeholders`; benign empty-list returns in no-data branches | INFO | Not a stub. These are SQL placeholder strings and normal empty-result paths, not user-visible placeholder implementation. |
| `backend/tests/*` | multiple | Empty list/dict returns in fixtures | INFO | Test fixture behavior only, not production stubs. |

No blocker anti-patterns were found.

### Human Verification Required

None. This phase is backend lifecycle/config/cursor wiring and was verified through code tracing, focused tests, static boundary scans, and the broad local gate.

### Gaps Summary

No gaps found. The phase goal is achieved: source runtime construction is centralized behind the lifecycle factory, credentials are provider-mediated with delegated Telegram refs, cursor commits remain transaction-owned, and filesystem plus Telegram call sites use the lifecycle boundary.

---

_Verified: 2026-05-08T15:56:47Z_
_Verifier: the agent (gsd-verifier)_
