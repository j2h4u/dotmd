# Phase 37: Airweave Connector Compatibility Spike — Research

**Researched:** 2026-05-11
**Phase:** 37 — airweave-connector-compatibility-spike
**Requirements:** AIR-01, AIR-02, AIR-03

---

## 1. Research Summary

The core question is: **can dotMD wrap `GmailSource` as a federated search
provider without adopting Airweave's Vespa/Temporal/billing stack?**

Answer: **Yes, with three targeted shims.** The Airweave DI types
(`SourceAuthProvider`, `ContextualLogger`, `AirweaveHttpClient`) are all
Protocol-based or structurally typed — no inheritance required. Gmail's
`generate_entities()` is async and tightly coupled to Airweave internals, but
`search()` does **not exist** on `GmailSource` (the base class has a stub at
line 249 of `_base.py`, but it is an abstract `AsyncGenerator` — Gmail does not
implement it). This changes the spike approach: the federated search path for
Gmail must be built on direct Gmail API calls using the OAuth token, not on
wrapping `GmailSource.search()`.

**Vendoring verdict:** The Airweave package installs with `httpx`, `pydantic`,
`tenacity` and a few more lightweight deps at platform layer — but the full
`airweave` package also pulls in `sqlalchemy`, `celery`, `temporalio`, `redis`,
and organization/billing schemas. **Do not `pip install airweave`.** Vendor
only `platform/sources/gmail.py`, `platform/entities/gmail.py`,
`platform/entities/_base.py`, `platform/configs/config.py` (GmailConfig only),
and `platform/decorators.py`. These are self-contained after stripping the
`@source` decorator call (decorator imports `RateLimitLevel`, `AuthenticationMethod`,
`OAuthType` from `airweave.schemas.source_connection` — shimmable).

---

## 2. Key Findings

### 2.1 GmailSource.search() Does Not Exist

The `BaseSource` abstract class defines `search()` as an abstract
`AsyncGenerator[BaseEntity, None]` (line 249 of `_base.py`). `GmailSource`
**does not override it**. This means:

- The CONTEXT.md D-02 assumption ("GmailSource.search() powering live query-time
  search") needs a revision: we must call the Gmail API search endpoint directly.
- The generic `AirweaveConnectorBridge.search()` cannot delegate to
  `GmailSource.search()` — it does not exist.
- **Recommended approach:** The bridge calls the Gmail API `users.messages.list`
  with `q=<query>` directly using the OAuth token, converts results to
  `GmailMessageEntity`-shaped dicts, then maps them to `SearchCandidate`.
  This is cleaner than forcing `generate_entities()` for a search operation.

### 2.2 DI Type Shapes — Protocol-Based, Shimmable

**`SourceAuthProvider`** (`domains/sources/token_providers/protocol.py`):
- `@runtime_checkable` Protocol
- Required: `provider_kind: AuthProviderKind`, `supports_refresh: bool`
- Token access: `get_token() -> str` (async, on subprotocol `TokenProviderProtocol`)
- Shim: a simple dataclass/class with `provider_kind`, `supports_refresh=True`,
  and `get_token()` that reads the refresh_token from the credential provider
  and calls Google's token endpoint. No inheritance from Airweave classes needed.

**`ContextualLogger`** (`core/logging.py`):
- A standard Python class wrapping `logging.Logger` with JSON formatting.
- `GmailSource` uses `self.logger.debug(...)`, `self.logger.warning(...)`.
- Shim: any object with `.debug()`, `.warning()`, `.info()`, `.error()` methods.
  A thin wrapper around Python's stdlib logger suffices.

**`AirweaveHttpClient`** (`platform/http_client/airweave_client.py`):
- Wraps `httpx.AsyncClient`, adds rate limiting.
- `GmailSource` uses `self.http_client.get(url, headers=..., params=...)`.
- Shim: an object holding an `httpx.AsyncClient` with a `.get()` method that
  delegates. No rate limiter needed for single-user spike.

### 2.3 `@source` Decorator — Strips Cleanly

The `@source` decorator only sets `ClassVar` attributes on the decorated class:
`is_source`, `source_name`, `short_name`, `auth_methods`, `oauth_type`,
`config_class`, etc. It does not register the class in a global registry at
import time (no side-effects). In the vendored subtree, the decorator can be
left as-is (it imports only `pydantic.BaseModel`, `RateLimitLevel`,
`AuthenticationMethod`, `OAuthType` — all shimmable enums) or replaced with a
no-op decorator that just sets the same class attributes.

### 2.4 Vendoring Scope

Files to vendor into `backend/src/dotmd/vendor/airweave/`:

| File | Why needed | Notes |
|------|-----------|-------|
| `platform/entities/_base.py` | `BaseEntity`, `Breadcrumb`, `AirweaveSystemMetadata` | Remove `SparseEmbedding` import (not needed) |
| `platform/entities/gmail.py` | `GmailThreadEntity`, `GmailMessageEntity`, `GmailAttachmentEntity` | Keep as-is |
| `platform/sources/_base.py` | `BaseSource` abstract class | Remove `FileService`, `AccessControl` imports |
| `platform/sources/gmail.py` | `GmailSource` class | Keep `generate_entities()`, strip unused imports |
| `platform/configs/config.py` | `GmailConfig` only | Extract GmailConfig + SourceConfig base |
| `platform/decorators.py` | `@source` decorator | Replace with stub that sets ClassVars |

Not needed: `domains/`, `core/`, `schemas/`, `platform/destinations/`,
`platform/rate_limiters/`, `platform/tokenizers/`.

### 2.5 Federated Search Path — Direct Gmail API

Since `GmailSource.search()` is not implemented, the bridge's search path is:

```
GmailBridge.search_native(query, limit)
  → GET https://gmail.googleapis.com/gmail/v1/users/me/messages?q=<query>&maxResults=<limit>
  → for each message_id: GET messages/{id}?format=metadata&metadataHeaders=Subject,From,Date
  → construct SearchCandidate with ref="gmail:message:<message_id>"
```

This is simpler and more direct than wrapping `generate_entities()`. The OAuth
access token comes through the `CredentialProviderProtocol` boundary (D-07).

### 2.6 `read_unit_window` — Fetch Full Message

For `read(ref)` on Gmail refs:
- Parse `message_id` from ref `gmail:message:<message_id>`
- Call `GET messages/{id}?format=full`
- Decode body from base64 (Gmail API returns base64url-encoded parts)
- Return as `SourceUnitWindow`

This is straightforward using `httpx` directly with the access token.

### 2.7 Entity Field Mapping to SearchCandidate

From `GmailMessageEntity` (via raw Gmail API response):

| Gmail field | SearchCandidate field |
|-------------|----------------------|
| `message_id` | `ref = "gmail:message:{message_id}"` |
| `subject` (header) | `title` |
| `body_text` / snippet | `snippet` |
| `sender` | `provider_metadata.sender` |
| `date` | `provider_metadata.sent_at` |
| `thread_id` | `provider_metadata.thread_id` |
| API result rank | `source_native_rank` (zero-based) |
| — | `source_native_score = None` (Gmail API does not return scores) |
| — | `namespace = "gmail"` |
| — | `descriptor_key = "gmail"` |
| — | `source_kind = "email"` |
| — | `retrieval_kind = "gmail:native"` |
| — | `can_read = True` |
| — | `can_materialize = False` |

### 2.8 GmailSourceConfig for dotMD Lifecycle

The dotMD `TelegramSourceConfig` pattern (a Pydantic model in `source_lifecycle.py`)
is directly reusable. For Gmail:

```python
class GmailSourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    
    client_id: str
    client_secret: str
    # refresh_token comes through credential provider, not config
    token_endpoint: str = "https://oauth2.googleapis.com/token"
    scopes: list[str] = Field(default_factory=lambda: ["https://www.googleapis.com/auth/gmail.readonly"])
    search_result_limit: int = 10
```

The refresh token is stored in `~/.secrets/dotmd-gmail.env` and read through
`CredentialProviderProtocol` — never inside the provider class directly.

### 2.9 SourceRegistry Integration

Gmail registers as a new `SourceDescriptor` in `source_registry.py`:
- `namespace = "gmail"`
- `source_kind = "email"`
- `capabilities = [FEDERATED_SEARCH, READ_UNIT_WINDOW]`
- `auth_schema = SourceAuthSchema(auth_kind="oauth_refresh", ...)`
- No `LOCAL_SYNC`, no `INCREMENTAL_CURSOR` for the spike

Pattern follows `telegram_source_descriptor()` exactly.

### 2.10 SourceRuntimeFactory Integration

`SourceRuntimeFactory.build("gmail")` in `source_lifecycle.py` must:
1. Read `GmailSourceConfig` from `InMemorySourceConfigStore`
2. Resolve OAuth refresh token through `SourceCredentialProviderProtocol`
3. Construct `GmailOAuthTokenProvider` (shim — calls Google token endpoint)
4. Construct `GmailApplicationSourceProvider` (the bridge)
5. Return a `SourceRuntimeBundle` with the provider

The existing `SourceLifecycleConfigError` is the correct exception for missing config.

### 2.11 DotMDService Integration

`DotMDService._build_federated_bundles()` already fans out to multiple providers.
Gmail registers as a federated bundle when `DOTMD_GMAIL_CLIENT_ID` env var is set
(similar to how Telegram activates when `DOTMD_TELEGRAM_SOCKET_PATH` is set).

No changes needed to `_build_federated_bundles()` itself — it iterates all bundles
with `FEDERATED_SEARCH` capability automatically.

---

## 3. Validation Architecture

### What to verify at the end of this phase

| Test | Method |
|------|--------|
| `gmail_source_descriptor()` returns valid `SourceDescriptor` | Unit test |
| `GmailSourceConfig` construction from env vars | Unit test |
| `AirweaveConnectorBridge` maps raw Gmail API message dict to `SearchCandidate` | Unit test with fixture |
| `SearchCandidate` ref validates as `"gmail:message:<id>"` | Model validation test |
| `read_unit_window` returns `SourceUnitWindow` from message dict | Unit test with fixture |
| Bridge `search_native()` called with shim auth returns candidates | Integration test with mock httpx |
| `docs/airweave-compatibility.md` exists and covers all 3 AIR-02 categories | File existence check |
| `SourceRuntimeFactory.build("gmail")` raises `SourceLifecycleConfigError` on missing config | Unit test |

### Live smoke (manual, needs real credentials)

- Run `dotmd search "project update"` → Gmail candidates appear in results
- Run `dotmd read "gmail:message:<id>"` → returns message content
- Verify `descriptor_key="gmail"`, `namespace="gmail"` in search output

---

## 4. Risks and Decisions for Planner

### R-01: No GmailSource.search() — direct API approach

**Risk:** CONTEXT.md D-02 assumes `GmailSource.search()` exists. It does not.
**Decision for planner:** Use direct Gmail API calls for search. The bridge's
`search_native()` calls `users/messages.list?q=<query>` directly. This is
simpler and more reliable than forcing `generate_entities()` in batch mode.

### R-02: Async GmailSource vs sync dotMD provider pattern

**Risk:** `GmailSource.create()`, `generate_entities()`, and all HTTP methods
are `async`. dotMD's `ApplicationSourceProviderProtocol` uses sync methods
(`search_native`, `read_unit_window`). The Telegram bridge (`telegram_provider.py`)
is sync because it talks to a sync Unix socket.
**Decision for planner:** The Gmail bridge is async. Use `asyncio.run()` or
run inside an async context. `DotMDService._build_federated_bundles()` calls
`search_native()` — check if it is already async or needs to be.

### R-03: OAuth flow setup is manual for the spike

**Risk:** The initial OAuth refresh token must be obtained once interactively.
**Decision for planner:** Add a CLI helper `dotmd gmail auth` (or document the
`oauth2l` / Google's `gcloud` approach) that runs the consent flow and writes
`~/.secrets/dotmd-gmail.env`. This is a one-time setup, not a daemon.

### R-04: Vendored subtree import conflicts

**Risk:** Vendored `airweave/` imports from `airweave.*` internally.
**Decision for planner:** After vendoring, rewrite relative imports to
`dotmd.vendor.airweave.*` using `sed` or a simple script. Only 5-6 files need
rewriting. Alternative: keep the vendored code as-is and add the vendor path to
`sys.path` at import — but the rewrite approach is cleaner.

### R-05: `AirweaveSystemMetadata` has `SparseEmbedding` dep

**Risk:** `_base.py` imports `SparseEmbedding` from `airweave.domains.embedders.types`.
**Decision for planner:** In the vendored copy, replace `SparseEmbedding` with
`Any` or `list[float] | None`. `AirweaveSystemMetadata` is not used by the bridge
(D-12 explicitly says to avoid it), so this is a one-line type stub.

---

## 5. Implementation Approach

### Recommended Plan Structure (4 plans, 3 waves)

**Wave 1:**
- `37-01`: Vendor Airweave platform slice + shim DI types
  - Copy 6 files to `backend/src/dotmd/vendor/airweave/`
  - Rewrite imports, stub `@source` decorator, remove `SparseEmbedding`
  - Add `GmailOAuthTokenProvider` shim (calls Google token endpoint)
  - Add `GmailLoggerShim` (wraps stdlib logger)
  - Add `GmailHttpClientShim` (wraps httpx.AsyncClient)

**Wave 2 (parallel after Wave 1):**
- `37-02`: `AirweaveConnectorBridge` + Gmail federated search
  - `backend/src/dotmd/ingestion/gmail_provider.py`
  - `search_native(query, limit)` → direct Gmail API → `list[SearchCandidate]`
  - `read_unit_window()` → Gmail API fetch full message → `SourceUnitWindow`
  - Entity field mapping (D-08, D-09)
  - Metadata whitelist for `provider_metadata`

- `37-03`: Gmail source descriptor + lifecycle wiring
  - `gmail_source_descriptor()` in `source_registry.py`
  - `GmailSourceConfig` in `source_lifecycle.py`
  - `SourceRuntimeFactory.build("gmail")` branch
  - Env var activation gate (`DOTMD_GMAIL_CLIENT_ID`)
  - `DotMDService._build_federated_bundles()` picks up Gmail when configured

**Wave 3 (after Wave 2):**
- `37-04`: AIR-02 compatibility report + tests
  - `docs/airweave-compatibility.md` — structured analysis per D-12
  - Unit tests for bridge mapping, descriptor, SearchCandidate validation
  - Manual smoke test notes (credentials required)

---

## 6. Files to Create/Modify

| File | Action |
|------|--------|
| `backend/src/dotmd/vendor/__init__.py` | Create (empty) |
| `backend/src/dotmd/vendor/airweave/__init__.py` | Create (empty) |
| `backend/src/dotmd/vendor/airweave/entities_base.py` | Create (vendored `_base.py`) |
| `backend/src/dotmd/vendor/airweave/entities_gmail.py` | Create (vendored `gmail.py`) |
| `backend/src/dotmd/vendor/airweave/source_base.py` | Create (vendored `_base.py`) |
| `backend/src/dotmd/vendor/airweave/source_gmail.py` | Create (vendored `gmail.py`) |
| `backend/src/dotmd/vendor/airweave/gmail_config.py` | Create (vendored GmailConfig) |
| `backend/src/dotmd/ingestion/gmail_provider.py` | Create — bridge + shims |
| `backend/src/dotmd/ingestion/source_registry.py` | Modify — add `gmail_source_descriptor()` |
| `backend/src/dotmd/ingestion/source_lifecycle.py` | Modify — add `GmailSourceConfig`, factory branch |
| `backend/src/dotmd/api/service.py` | Modify — activate Gmail in `_build_federated_bundles()` |
| `docs/airweave-compatibility.md` | Create — AIR-02 deliverable |
| `backend/tests/test_gmail_bridge.py` | Create — bridge unit tests |

## RESEARCH COMPLETE
