# Airweave Connector Compatibility Analysis

**Phase:** 37 - Airweave connector compatibility spike
**Date:** 2026-05-13
**Pilot connector:** Gmail (`GmailSource` from `airweave/platform/sources/gmail.py`)
**Implementation:** `backend/src/dotmd/vendor/airweave/` plus `backend/src/dotmd/ingestion/gmail_provider.py`
**Conclusion:** dotMD can reuse Airweave's connector schema and constructor patterns, but live search/read behavior remains a dotMD provider concern because Gmail's Airweave source has no `search()` implementation.

---

## 1. Reusable Directly

The reusable portion is the platform-layer shape, not Airweave's runtime. The vendored source is tracked in `backend/src/dotmd/vendor/airweave/VENDOR_VERSION`, and per-file modifications are summarized in `backend/src/dotmd/vendor/airweave/VENDOR_NOTES.md`.

- **BaseSource constructor DI pattern:** Airweave's `BaseSource` starts at `/home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/sources/_base.py:36` and takes `auth`, `logger`, and `http_client` at construction. dotMD keeps that constructor shape in `backend/src/dotmd/vendor/airweave/source_base.py` with local structural stubs. This is reusable as a compatibility pattern, but not as the full original source file because Airweave imports `airweave.core`, `airweave.domains`, and `airweave.schemas`.

- **GmailSource metadata and config shape:** Airweave's `GmailSource` starts at `/home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/sources/gmail.py:78`. dotMD's vendored `backend/src/dotmd/vendor/airweave/source_gmail.py` preserves the class metadata, config extraction, and query-building shape while intentionally omitting Airweave's sync runtime internals. The class-level `@source` metadata remains useful for documenting connector capabilities.

- **Gmail entity schemas:** `GmailThreadEntity`, `GmailMessageEntity`, and `GmailAttachmentEntity` are in Airweave's `platform/entities/gmail.py` and are represented in `backend/src/dotmd/vendor/airweave/entities_gmail.py:57`, `:109`, and `:182`. These schemas are directly useful as field references for source identity, message metadata, and attachment mapping.

- **AirweaveField and Breadcrumb:** `Breadcrumb` and the flagged-field pattern from Airweave's `platform/entities/_base.py` are retained in `backend/src/dotmd/vendor/airweave/entities_base.py`. dotMD replaced `AirweaveField` with a local wrapper that stores flags in `json_schema_extra` so Pydantic v2 does not emit deprecated extra-key warnings.

- **SyncCursor shape:** Airweave uses a cursor object for sync-style connectors. dotMD's vendored `source_base.py` models this as `SyncCursor = dict[str, object]`, which is enough for compatibility analysis. Gmail in this phase is federated-only, so there is no local cursor.

- **`@source` decorator metadata:** Airweave's decorator sets class attributes at `/home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/decorators.py:26` and assigns `federated_search` at `:129`. dotMD keeps only that behavior in `backend/src/dotmd/vendor/airweave/decorators.py`; no global Airweave registry is used.

## 2. Requires Shims

- **SourceAuthProvider -> GmailOAuthTokenProvider:** Airweave expects an auth object with provider kind, refresh support, and token access. dotMD implements this in `backend/src/dotmd/vendor/airweave/shims.py:56`. The provider stores credentials, has `_refresh_lock = threading.Lock()` at `:66`, and computes expiry from `expires_in - 300` at `:93-94`. This is the right place for OAuth refresh-token material; Phase 37 lifecycle config does not put the token in `SourceAccess.delegated_to`.

- **ContextualLogger -> GmailLoggerShim:** Airweave source code calls logger methods such as `debug()` and `warning()`. `GmailLoggerShim` in `backend/src/dotmd/vendor/airweave/shims.py` wraps stdlib `logging.Logger` with the expected methods. There is no dependency on Airweave's JSON contextual logger.

- **AirweaveHttpClient -> GmailHttpClientShim:** Airweave's HTTP wrapper carries rate limiting and SSRF machinery for a multi-tenant platform. dotMD only needs an object with `get()` and `post()` over `httpx.AsyncClient`; `GmailHttpClientShim` provides that in `backend/src/dotmd/vendor/airweave/shims.py`.

- **GmailMessageDeletionEntity -> dotMD binding deactivation:** `GmailMessageDeletionEntity` exists in `backend/src/dotmd/vendor/airweave/entities_gmail.py`, but dotMD has no Gmail local-sync path in Phase 37. Mapping Gmail deletions to `resource_bindings.active = false` is deferred until Gmail becomes a sync source.

## 3. Should Be Avoided

- **AirweaveSystemMetadata:** `AirweaveSystemMetadata` is retained for schema compatibility in `backend/src/dotmd/vendor/airweave/entities_base.py`, but it is not a dotMD persistence contract. Its embedding, chunk, sync, and database fields duplicate dotMD's own chunk/provenance/index schema.

- **Vespa, Temporal, Celery, Redis, FileService:** These are Airweave runtime/indexing dependencies, not connector schema dependencies. The vendored Python files under `backend/src/dotmd/vendor/airweave/` contain no direct `from airweave` or `import airweave` imports, and `grep -r "^from airweave\|^import airweave" backend/src/dotmd/ --include="*.py"` returns no matches.

- **AccessControl and supports_access_control:** Airweave's access-control shape is multi-tenant. dotMD is a personal/small-user knowledgebase and does not wire Gmail ACLs into Phase 37 search results.

- **AirweaveHttpClient rate limiter:** Airweave's original HTTP wrapper includes organization/source-connection rate limiting. dotMD's Gmail bridge uses explicit `httpx.Timeout(GMAIL_API_TIMEOUT_SECONDS, connect=5.0)` in `backend/src/dotmd/ingestion/gmail_provider.py` and leaves quota/batch optimization as a future operational concern.

## 4. Key Finding: GmailSource.search() Is Not Implemented

Airweave's base contract defines `async def search(self, query: str, limit: int)` at `/home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/sources/_base.py:249`. That method raises `NotImplementedError` when a source has `federated_search=True` but does not override `search()`.

`GmailSource` begins at `/home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/sources/gmail.py:78`. A grep over that file for `async def search` returns no matches. Therefore the Gmail bridge cannot wrap `GmailSource.search()`.

The implemented fallback is direct Gmail API search in `GmailBridge.search_native()` at `backend/src/dotmd/ingestion/gmail_provider.py:82`. It calls Gmail `messages.list`, then fetches per-message metadata and maps results to `SearchCandidate`. For a new Airweave connector, first check:

```bash
grep "async def search" platform/sources/<name>.py
```

If the connector implements search, a bridge may delegate to the source. If it does not, direct provider API search is required.

## 5. Generic Bridge: BaseConnectorBridge ABC (D-03)

`BaseConnectorBridge` is defined in `backend/src/dotmd/ingestion/gmail_provider.py:43`. It has three abstract methods:

- `search_native(query, limit)` returns ranked dotMD `SearchCandidate` objects.
- `read_unit_window(unit_ref, before, after)` fetches readable content for refs returned by search.
- `to_search_candidate(entity_fields, rank)` maps connector-native fields into dotMD's search result contract.

D-03 is satisfied by the ABC and provider protocol, not by Gmail-specific API calls. `GmailBridge` at `backend/src/dotmd/ingestion/gmail_provider.py:67` is the first implementation. A second connector should implement the same ABC and then register through `SourceRegistry` and `SourceRuntimeFactory`.

Airweave's runtime/indexing stack (Vespa, Temporal, Celery, Redis) is NOT used. Direct Gmail API search is a dotMD provider concern, implemented in `GmailBridge.search_native()`. This is not Airweave runtime compatibility; it is dotMD's own Gmail integration using Airweave's entity schemas and DI shape as a reference.

## 6. SourceAsset Deferred (GmailAttachmentEntity)

`GmailAttachmentEntity` is present in `backend/src/dotmd/vendor/airweave/entities_gmail.py:182`. dotMD does not add a `SourceAsset` model in this phase.

AIR-01 mapping status:

| Airweave/Gmail concept | dotMD target | Phase 37 status |
|------------------------|--------------|-----------------|
| Gmail message identity and metadata | `SearchCandidate` + provider metadata | Implemented by `GmailBridge.to_search_candidate()`. |
| Gmail message body | `SourceUnitWindow` read surface | Implemented by `GmailBridge.read_unit_window()`. |
| Gmail message as durable source document | `SourceDocument` | Deferred because Gmail is federated-only in this spike. |
| Gmail message as source unit | `SourceUnit` | Deferred for the same reason; no local Gmail sync cursor exists. |
| Gmail attachment | Future `SourceAsset` | Deferred per D-11; mapping below records the expected fields. |

| GmailAttachmentEntity field | Future SourceAsset field | Notes |
|----------------------------|--------------------------|-------|
| `attachment_id` | `asset_ref` | Unique within the parent Gmail message. |
| `filename` | `display_name` | Already marked as the entity name in the vendored schema. |
| `mime_type` | `media_type` | Inherited through `FileEntity`. |
| `size` | `size_bytes` | Inherited through `FileEntity`. |
| `data` (base64 API attachment payload) | via future FileService equivalent | Deferred because Phase 37 has no Gmail local materialization path. |

Status: Deferred per D-11. No `SourceAsset` model was added to `backend/src/dotmd/core/models.py`.

## 7. Generic Bridge Extensibility Assessment

| Component | Generic/Specific | Reuse for 2nd connector | Notes |
|-----------|------------------|--------------------------|-------|
| `BaseConnectorBridge` ABC | Generic | Yes - implement the ABC | Three abstract methods in `gmail_provider.py`. |
| `to_search_candidate()` | Generic pattern | Yes - override with connector mapping | Maps connector fields to `SearchCandidate`; Gmail sets `source_native_score=None`. |
| `GmailBridge.search_native()` | Gmail-specific | No - implement per connector | Uses Gmail `messages.list` and metadata fetch. |
| `GmailBridge.read_unit_window()` | Gmail-specific | No - implement per connector | Fetches one Gmail message and decodes MIME payload. |
| MIME decode helpers | Email-specific | Partial - useful for email connectors | Handles base64url, `text/plain`, HTML fallback, and 1MB cap. |
| SourceDescriptor registration | Generic pattern | Yes - copy descriptor structure | `gmail_source_descriptor()` sits beside filesystem and Telegram descriptors. |
| `GmailSourceConfig` / lifecycle | Generic pattern | Yes - copy config/build structure | Build branch creates a provider bundle through `SourceRuntimeFactory`. |
| DI shims | Mixed | Logger and HTTP reusable; OAuth provider connector-specific | `GmailOAuthTokenProvider` is Google-token specific. |

Estimated effort for a second connector:

- If connector implements `search()`: about 80 lines for descriptor, config, and a thin bridge subclass.
- If connector lacks `search()`: about 180 lines for descriptor/config plus direct API search/read implementation.

## 8. AIR-03 Compliance

- [x] `gmail_source_descriptor()` exists in `backend/src/dotmd/ingestion/source_registry.py:106` beside `filesystem_source_descriptor()` and `telegram_source_descriptor()`.
- [x] `default_source_registry()` registers filesystem, Telegram, and Gmail in the same function.
- [x] `SourceRuntimeFactory.build("gmail")` is implemented in `backend/src/dotmd/ingestion/source_lifecycle.py:342` as a branch in the same method as filesystem and Telegram.
- [x] `DotMDService._build_federated_bundles()` in `backend/src/dotmd/api/service.py:308` iterates registered descriptors and calls `build_if_configured(namespace)`. There is no Gmail-specific fan-out loop.
- [x] `grep -r "^from airweave\|^import airweave" backend/src/dotmd/ --include="*.py"` returns no matches.

The implementation therefore does not create an Airweave-only integration lane. Gmail is a normal source descriptor and lifecycle runtime bundle that participates in the same federated search path as other providers.
