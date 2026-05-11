---
plan: 37-04
title: AIR-02 compatibility report and end-to-end verification
wave: 3
depends_on:
  - 37-02
  - 37-03
files_modified:
  - docs/airweave-compatibility.md
  - backend/tests/test_gmail_bridge.py
autonomous: true
requirements:
  - AIR-02
  - AIR-03
must_haves:
  goal: >
    docs/airweave-compatibility.md exists and answers all three AIR-02 categories:
    reusable directly, requires shims, should be avoided. Full test suite is green.
    No Airweave-only integration lane exists separate from filesystem/Telegram paths.
  truths:
    - docs/airweave-compatibility.md exists and is non-empty
    - Report covers "Reusable directly" section
    - Report covers "Requires shims" section (SourceAuthProvider, ContextualLogger, AirweaveHttpClient, @source decorator, GmailMessageDeletionEntity)
    - Report covers "Should be avoided" section (AirweaveSystemMetadata, Vespa, Temporal, FileService, AccessControl, AirweaveHttpClient rate limiter, supports_access_control)
    - Report documents that GmailSource.search() is not implemented and bridge uses direct API
    - Report documents SourceAsset deferred mapping for GmailAttachmentEntity
    - cd backend && python -m pytest tests/ -x -q exits 0
---

# Plan 37-04: AIR-02 compatibility report and end-to-end verification

## Objective

Produce the `docs/airweave-compatibility.md` structured analysis (AIR-02
deliverable), then run the full test suite to verify the complete Phase 37
implementation is green. This plan is the evidence that the spike answered its
research question.

## Tasks

### Task 1: Write docs/airweave-compatibility.md

<read_first>
- .planning/phases/37-airweave-connector-compatibility-spike/37-CONTEXT.md — D-12 lists exact questions the report must answer
- .planning/phases/37-airweave-connector-compatibility-spike/37-RESEARCH.md — research findings to draw from
- /home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/sources/_base.py — BaseSource contract
- /home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/entities/_base.py — BaseEntity, AirweaveSystemMetadata
- /home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/sources/gmail.py — GmailSource, search() absence
- backend/src/dotmd/ingestion/gmail_provider.py — the bridge implementation
- backend/src/dotmd/vendor/airweave/ — vendored slice structure
</read_first>

<action>
Create `docs/airweave-compatibility.md` with the following structure:

```markdown
# Airweave Connector Compatibility Analysis

**Phase:** 37 — Airweave connector compatibility spike
**Date:** 2026-05-11
**Pilot connector:** Gmail (GmailSource from airweave/platform/sources/gmail.py)
**Conclusion:** dotMD can wrap Airweave-style connectors as federated search
providers without adopting Airweave's indexing, chunking, Vespa, Temporal,
billing, or organization stack. Three lightweight shims are required.

---

## 1. Reusable Directly

These Airweave platform pieces are used as-is in the vendored subtree
(`backend/src/dotmd/vendor/airweave/`):

### Source and Entity Definitions
- **`BaseSource`** — abstract base with `create()`, `generate_entities()`,
  constructor DI pattern. The constructor signature (`auth`, `logger`, `http_client`)
  is clean enough to satisfy with shims.
- **`GmailSource`** class body — `generate_entities()`, cursor handling, Gmail API
  helpers. Vendored without modification beyond import rewrites.
- **`GmailThreadEntity`**, **`GmailMessageEntity`**, **`GmailAttachmentEntity`** —
  entity schemas with typed fields. Used as reference for field mapping to
  `SearchCandidate`. Not instantiated directly by the bridge (raw API responses
  used instead, for simplicity).
- **`GmailMessageDeletionEntity`** — documented as future shim target (see §3).

### Entity Field Conventions
- **`AirweaveField`** pattern — field metadata (`is_entity_id`, `is_name`) useful
  for generic bridge field mapping. Retained in vendored tree.
- **`Breadcrumb`** model — `entity_id`, `name`, `entity_type`. Maps cleanly to
  `provider_metadata.breadcrumbs` in `SearchCandidate`.
- **`entity_id`** / **`textual_representation`** pattern — the two fields common
  across all `BaseEntity` subclasses. Generic bridge uses these for `ref` and `snippet`.

### Cursor Pattern
- **`SyncCursor.data: dict[str, object]`** — simple dict-based cursor state.
  dotMD's own cursor store already uses the same dict pattern. No shim needed.

### `@source` Decorator
- The decorator only sets `ClassVar` attributes (no global registry side-effects,
  no import-time DI wiring). Replaced with a no-op stub in the vendored tree;
  the class attributes are equivalent.

---

## 2. Requires Shims

These Airweave DI types are used by `GmailSource.__init__()` and must be
satisfied by shim implementations. All are Protocol-typed (structural subtyping)
or duck-typed — no inheritance from Airweave classes required.

### `SourceAuthProvider` / `TokenProviderProtocol`
- **What Airweave expects:** `@runtime_checkable Protocol` with `provider_kind: str`,
  `supports_refresh: bool`, `get_token() -> str` (async).
- **dotMD shim:** `GmailOAuthTokenProvider` — holds `client_id`, `client_secret`,
  `refresh_token`; calls `https://oauth2.googleapis.com/token` to exchange the
  refresh token for an access token; caches with 5-minute expiry.
- **Credential boundary:** Refresh token enters through `SourceCredentialRef` /
  `CredentialProviderProtocol` — not read directly from env/files inside the provider.

### `ContextualLogger`
- **What Airweave expects:** Object with `debug()`, `info()`, `warning()`, `error()`
  methods accepting `(str, *args, **kwargs)`.
- **dotMD shim:** `GmailLoggerShim` — thin wrapper around Python stdlib `logging.Logger`.
  One line of code.

### `AirweaveHttpClient`
- **What Airweave expects:** Object with `.get(url, headers=None, params=None)` and
  `.post(url, ...)` returning `httpx.Response`.
- **dotMD shim:** `GmailHttpClientShim` — wraps `httpx.AsyncClient` (or `httpx.Client`
  for sync usage). No rate limiter injected (single-user spike).
- **Note:** The bridge bypasses `GmailSource` for search (see §4 for rationale) and
  calls the Gmail API directly via `httpx.Client`. The shim is needed only for
  `GmailSource.__init__()` if `generate_entities()` is ever called.

### `GmailMessageDeletionEntity` → dotMD binding deactivation
- **Airweave approach:** emits a `GmailMessageDeletionEntity` when Gmail History API
  reports a deleted message. The Airweave destination pipeline handles deletion.
- **dotMD shim required:** dotMD uses `resource_bindings.active = 0` for deletion.
  A future shim must detect deletion entities from `generate_entities()` and call
  `metadata_store.deactivate_binding(ref)` instead of indexing the entity.
- **Status:** Deferred — not needed for the federated-only spike (no local indexing).
  Document as required shim for any future local Gmail sync phase.

---

## 3. Should Be Avoided

These Airweave pieces are incompatible with dotMD's architecture or single-user model:

### `AirweaveSystemMetadata`
- Fields `embedding`, `chunk_index`, `sync_id`, `dense_embedding`, `sparse_embedding`
  conflict with dotMD's own `text_hash`, `chunk_id`, and sqlite-vec storage.
- **Verdict:** Never use. dotMD has its own equivalents and they are not compatible.

### Vespa / Temporal / `FileService`
- Airweave's indexing pipeline routes entities through Vespa (vector store) and
  Temporal (workflow orchestration). `FileService` abstracts file storage in that
  pipeline.
- **Verdict:** None of these are imported or referenced in the vendored slice.
  They live in `airweave.domains.*` which is not vendored.

### `AccessControl` / `supports_access_control`
- Multi-tenant ACL model with principals, groups, and `is_public` flags.
- **Verdict:** dotMD is single-user. `AccessControl` is stripped from the vendored
  `entities_base.py`. `supports_access_control=True` descriptors are not registered.

### `AirweaveHttpClient` rate limiter
- The production `AirweaveHttpClient` injects a `SourceRateLimiter` keyed by `org_id`
  and `source_short_name` — multi-tenant rate limiting backed by Redis.
- **Verdict:** The dotMD shim skips the rate limiter. Single-user; standard Gmail
  API quotas (250 quota units/user/second) apply without Redis coordination.

### `AirweaveSystemMetadata` `chunk_index` / `original_entity_id`
- Used by Airweave's chunker to track chunk position within an entity.
- **Verdict:** dotMD's chunker uses `chunk_id` (content-addressed) + `order_key`.
  These fields are not needed and would conflict.

---

## 4. Key Finding: GmailSource.search() Is Not Implemented

**Critical spike finding:** `BaseSource` declares `search()` as an abstract
`AsyncGenerator[BaseEntity, None]` method. `GmailSource` does **not** override it.

**Consequence:** The `AirweaveConnectorBridge.search_native()` cannot delegate to
`GmailSource.search()`. The bridge calls the Gmail API search endpoint directly:
`GET /gmail/v1/users/me/messages?q=<query>&maxResults=<limit>`.

**Implication for generic bridge design:** The CONTEXT.md D-03 goal (generic bridge
across all `BaseSource` subclasses via `GmailSource.search()`) needs qualification.
The bridge is generic in entity-field mapping (`BaseEntity` → `SearchCandidate`),
but the search invocation path must be source-specific if the connector does not
implement `search()`. Connectors that implement `search()` (those with
`federated_search=True` in the `@source` decorator) can use a generic call path.
Gmail does not have `federated_search=True` in its decorator.

**For future connectors:** Before wrapping a new Airweave connector, check:
1. Does it implement `search()`? (`grep "async def search" platform/sources/<name>.py`)
2. Is `federated_search=True` in its `@source` decorator?

If yes → generic `bridge.source.search(query, limit)` works.
If no → implement source-specific direct API search (as done for Gmail).

---

## 5. SourceAsset Deferred (GmailAttachmentEntity)

`GmailAttachmentEntity` maps conceptually to a `SourceAsset` shape (file-like artifact
attached to a document). dotMD does not have a `SourceAsset` model yet.

**Future mapping:**
- `GmailAttachmentEntity.attachment_id` → `SourceAsset.asset_ref`
- `GmailAttachmentEntity.filename` → `SourceAsset.display_name`
- `GmailAttachmentEntity.mime_type` → `SourceAsset.media_type`
- `GmailAttachmentEntity.size` → `SourceAsset.size_bytes`
- `GmailAttachmentEntity.data` (base64) → stored via `FileService` equivalent

**Status:** Deferred per D-11. No `SourceAsset` model added to `models.py` in this phase.
When `SourceAsset` is introduced, the Gmail bridge can emit attachment assets from
`generate_entities()` with no bridge-layer changes — only a new entity type handler.

---

## 6. Generic Bridge Extensibility Assessment

**Adding a second Airweave connector (e.g., Notion, GitHub):**

Estimated effort per new connector:
1. Vendor 2 files: `platform/sources/<name>.py` + `platform/entities/<name>.py`
2. Rewrite imports (automated: `sed -i 's/airweave\.platform/dotmd.vendor.airweave/g'`)
3. Check if connector implements `search()` (5 minutes inspection)
4. If yes: implement generic bridge call (10 lines)
   If no: implement direct API search (50-100 lines, connector-specific)
5. Add `SourceDescriptor` (follows Gmail pattern, ~30 lines)
6. Add `SourceConfig` + lifecycle branch (follows Gmail pattern, ~20 lines)
7. Add env var activation gate (~5 lines)

**Verdict:** The architecture is extensible. A second connector is a configuration
+ descriptor exercise for connectors that implement `search()`. Connectors without
`search()` require source-specific API integration (the unavoidable work).

---

## 7. Anti-Legacy Gate Compliance (AIR-03)

Gmail uses the same registry/lifecycle contracts as filesystem and Telegram:
- Registered via `SourceDescriptor` in `source_registry.py`
- Constructed via `SourceRuntimeFactory.build("gmail")` in `source_lifecycle.py`
- Activated via env var in `DotMDService` (same pattern as Telegram socket path)
- Federated search fan-out via `_build_federated_bundles()` (no Gmail-specific code)
- `SearchCandidate` shape identical to Telegram federated candidates

No separate Airweave-only integration lane was created.
```
</action>

<acceptance_criteria>
- `test -f docs/airweave-compatibility.md` exits 0
- `wc -l docs/airweave-compatibility.md` shows > 50 lines
- Report contains "Reusable directly" section
- Report contains "Requires shims" section
- Report contains "Should be avoided" section
- Report contains the GmailSource.search() finding
- Report contains SourceAsset deferred mapping
- Report contains generic bridge extensibility assessment
</acceptance_criteria>

### Task 2: Full test suite verification

<read_first>
- backend/tests/test_gmail_bridge.py — all tests from Plans 37-02 and 37-03
- backend/tests/test_vendor_airweave_import.py — smoke tests from Plan 37-01
</read_first>

<action>
Run the full test suite. Fix any failures found.

Common failure modes to check:
1. Import chain pulling in an Airweave module that is not vendored
2. `SourceConfig` type union in `source_lifecycle.py` not updated to include `GmailSourceConfig`
3. `default_source_registry()` missing the `gmail_source_descriptor()` registration
4. `GmailOAuthTokenProvider.get_token()` not cached — if tests call it, it may attempt network I/O
   (ensure tests mock the token provider's `get_token()` method)
5. `SearchCandidate` validation error if `snippet` is missing (Gmail API sometimes returns
   empty snippet for draft messages — ensure `snippet = response.get("snippet") or ""`
   so empty string is used, not None)

After fixing any failures, confirm the full suite passes.
</action>

<acceptance_criteria>
- `cd backend && python -m pytest tests/ -x -q` exits 0
- `cd backend && python -m pytest tests/test_gmail_bridge.py tests/test_vendor_airweave_import.py -v` exits 0
- No regressions in existing tests (filesystem, Telegram, search pipeline tests)
</acceptance_criteria>

### Task 3: Verify AIR-03 — no Airweave-only lane

<read_first>
- backend/src/dotmd/ingestion/source_registry.py — all descriptors
- backend/src/dotmd/ingestion/source_lifecycle.py — all build branches
- backend/src/dotmd/api/service.py — _build_federated_bundles()
</read_first>

<action>
Perform a structural check that Gmail follows the same code path as Telegram:

1. `source_registry.py` exports: `filesystem_source_descriptor`, `telegram_source_descriptor`,
   `gmail_source_descriptor`, `default_source_registry` — all in the same module, same pattern.

2. `source_lifecycle.py` `SourceRuntimeFactory.build()`: three branches
   (`filesystem`, `telegram`, `gmail`), all following the same structure:
   - validate config type
   - get access via credential provider
   - construct provider
   - return `SourceRuntimeBundle`

3. `service.py` `_build_federated_bundles()`: iterates `registry.list()` and calls
   `build_if_configured(namespace)` — no special Gmail-specific code in the loop.
   Gmail bundle is picked up automatically when configured, same as Telegram.

4. Check that no file in `backend/src/dotmd/` (outside of `vendor/`) directly imports
   from `airweave.*` (the full Airweave package):
   ```
   grep -r "^from airweave\|^import airweave" backend/src/dotmd/ --include="*.py"
   ```
   Expected: no output (all Airweave imports go through `dotmd.vendor.airweave.*`).
</action>

<acceptance_criteria>
- `grep -r "^from airweave\|^import airweave" backend/src/dotmd/ --include="*.py"` returns no matches
- `SourceRuntimeFactory.build()` has filesystem, telegram, gmail branches in the same method
- `_build_federated_bundles()` has no Gmail-specific conditional logic
- source_registry.py, source_lifecycle.py, service.py changes are symmetric with the Telegram pattern
</acceptance_criteria>

## Verification

```bash
# Full test suite
cd /home/j2h4u/repos/j2h4u/dotmd/backend
python -m pytest tests/ -x -q

# Compatibility report exists
test -f /home/j2h4u/repos/j2h4u/dotmd/docs/airweave-compatibility.md && echo "OK"

# No direct airweave imports outside vendor
grep -r "^from airweave\|^import airweave" src/dotmd/ --include="*.py" && echo "FAIL" || echo "OK"

# Registry has all three descriptors
python -c "
from dotmd.ingestion.source_registry import default_source_registry
r = default_source_registry()
assert r.get('filesystem') is not None
assert r.get('telegram') is not None
assert r.get('gmail') is not None
print('All three descriptors registered: OK')
"
```

## Phase Completion

When this plan passes verification, Phase 37 deliverables are complete:
- AIR-01: `GmailApplicationSourceProvider` bridges Airweave-style connector to dotMD contracts
- AIR-02: `docs/airweave-compatibility.md` documents reusable/shim/avoid analysis
- AIR-03: Gmail uses same registry/lifecycle/search contracts as filesystem and Telegram
