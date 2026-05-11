---
plan: 37-02
title: AirweaveConnectorBridge and Gmail federated search
wave: 2
depends_on:
  - 37-01
files_modified:
  - backend/src/dotmd/ingestion/gmail_provider.py
  - backend/tests/test_gmail_bridge.py
autonomous: true
requirements:
  - AIR-01
must_haves:
  goal: >
    GmailApplicationSourceProvider.search_native(query, limit) calls the Gmail
    API search endpoint directly (not GmailSource.search — it is not implemented),
    converts results to SearchCandidate objects conforming to the Phase 34
    contract, and GmailApplicationSourceProvider.read_unit_window() fetches the
    full message body and returns a SourceUnitWindow.
  truths:
    - gmail_provider.py exists at backend/src/dotmd/ingestion/gmail_provider.py
    - GmailApplicationSourceProvider implements ApplicationSourceProviderProtocol
    - search_native(query, limit) returns list[SearchCandidate]
    - Every SearchCandidate has ref="gmail:message:<id>", namespace="gmail", descriptor_key="gmail"
    - SearchCandidate.ref validates (namespace:document_ref format)
    - read_unit_window() returns SourceUnitWindow with namespace="gmail"
    - provider_metadata whitelist: message_id, thread_id, sender, subject, sent_at
    - No direct secret file reads inside GmailApplicationSourceProvider
    - Credentials enter only through injected GmailOAuthTokenProvider
---

# Plan 37-02: AirweaveConnectorBridge and Gmail federated search

## Objective

Implement `GmailApplicationSourceProvider` in `gmail_provider.py` — the bridge
between Gmail's REST API and dotMD's `ApplicationSourceProviderProtocol`. It
provides `search_native()` (federated search) and `read_unit_window()` (content
fetch). Credentials come through the `GmailOAuthTokenProvider` shim from Plan
37-01. No local indexing, no embedding, no FTS5.

## Context

**Critical finding from research:** `GmailSource.search()` is NOT implemented
in Airweave's `GmailSource` — the abstract base stub exists but is not overridden.
The bridge therefore calls the Gmail API directly via `httpx.AsyncClient` rather
than wrapping `GmailSource.search()`. This is the correct approach: simpler,
more direct, and avoids forcing `generate_entities()` for a search use case.

Pattern to follow: `TelegramApplicationSourceProvider.search_native()` in
`telegram_provider.py` — same SearchCandidate construction idiom.

## Tasks

### Task 1: Implement GmailApplicationSourceProvider

<read_first>
- backend/src/dotmd/ingestion/telegram_provider.py — search_native() pattern, SearchCandidate construction, TELEGRAM_PROVIDER_METADATA_KEYS pattern
- backend/src/dotmd/core/models.py — SearchCandidate, SourceUnitWindow, SourceCapability fields
- backend/src/dotmd/ingestion/source_provider.py — ApplicationSourceProviderProtocol
- backend/src/dotmd/vendor/airweave/shims.py — GmailOAuthTokenProvider interface
</read_first>

<action>
Create `backend/src/dotmd/ingestion/gmail_provider.py` with the following structure:

**Module-level constants:**
```
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
GMAIL_PROVIDER_METADATA_KEYS = frozenset({"message_id", "thread_id", "sender", "subject", "sent_at"})
```

**Class `GmailApplicationSourceProvider`:**
- Constructor: `__init__(self, token_provider: GmailOAuthTokenProvider, *, search_result_limit: int = 10)`
  - Stores token_provider and search_result_limit
  - Creates an `httpx.AsyncClient` instance for reuse (or creates per-call with `httpx.Client` sync)

- `search_native(self, query: str, limit: int) -> list[SearchCandidate]`:
  - Get access token from `self._token_provider.get_token()`
  - Call `GET {GMAIL_API_BASE}/messages?q={query}&maxResults={limit}` with Authorization Bearer header
  - Response: `{"messages": [{"id": "...", "threadId": "..."}], ...}` — IDs only
  - For each message (up to limit, batch fetch metadata):
    - Call `GET {GMAIL_API_BASE}/messages/{id}?format=metadata&metadataHeaders=Subject,From,Date`
    - Extract: subject (Subject header), sender (From header), date (Date header), snippet from response
  - Construct `SearchCandidate` per message:
    - `ref = f"gmail:message:{message_id}"`
    - `namespace = "gmail"`
    - `descriptor_key = "gmail"`
    - `source_kind = "email"`
    - `retrieval_kind = "gmail:native"`
    - `title = subject` (or None if missing)
    - `snippet = response.get("snippet", "")` — Gmail API provides a short snippet
    - `fused_score = 0.0` (no score from Gmail API)
    - `can_read = True`
    - `can_materialize = False`
    - `source_native_score = None` (Gmail API does not return relevance scores)
    - `source_native_rank = rank` (zero-based position in result list)
    - `provider_metadata = {k: v for k in GMAIL_PROVIDER_METADATA_KEYS if ...}`
      Keys: message_id, thread_id, sender, subject, sent_at
  - On API error (non-200): log warning and return empty list (never raise to caller)
  - Use sync `httpx.Client` (not async) to match dotMD's sync provider pattern

- `read_unit_window(self, unit_ref: str, before: int, after: int) -> SourceUnitWindow`:
  - Parse message_id from unit_ref: strip `"gmail:message:"` prefix
  - Get access token from `self._token_provider.get_token()`
  - Call `GET {GMAIL_API_BASE}/messages/{message_id}?format=full`
  - Decode body: Gmail returns base64url-encoded body parts
    - Walk `payload.parts` (MIME tree), collect `text/plain` parts
    - Decode: `base64.urlsafe_b64decode(part["body"]["data"] + "==")`
  - Build a single `SourceUnit` from the decoded body:
    - `namespace = "gmail"`, `document_ref = f"message:{message_id}"`,
      `unit_ref = f"message:{message_id}"`, `unit_type = "email_body"`,
      `text = decoded_body`, `order_key = "0"`, `fingerprint = sha256(decoded_body)`,
      `updated_at = datetime.utcnow()`, `metadata_json = {sender, subject, ...}`
  - Return `SourceUnitWindow(namespace="gmail", document_ref=..., unit_ref=..., units=[unit], metadata_json={})`
  - On API error: raise `RuntimeError(f"Gmail read failed for {unit_ref}: {status_code}")`

**Module-level helpers:**
- `_extract_header(headers: list[dict], name: str) -> str | None` — case-insensitive header lookup
- `_decode_gmail_body(payload: dict) -> str` — recursively walk MIME parts, collect text/plain
- `_parse_gmail_date(date_str: str | None) -> str | None` — parse RFC2822 date to ISO8601

Note: `search_native()` is called from `DotMDService` which runs it in an asyncio context.
Check `fanout_federated` in `backend/src/dotmd/search/federated.py` to confirm whether
`search_native` must be sync or can be async. Use sync `httpx.Client` to keep it sync
(same pattern as Telegram's Unix socket client).
</action>

<acceptance_criteria>
- `from dotmd.ingestion.gmail_provider import GmailApplicationSourceProvider` imports cleanly
- `GmailApplicationSourceProvider` has `search_native` and `read_unit_window` methods
- `search_native` signature matches `ApplicationSourceProviderProtocol.search_native(query: str, limit: int) -> list[SearchCandidate]`
- `from dotmd.core.models import SearchCandidate; SearchCandidate(ref="gmail:message:abc123", namespace="gmail", descriptor_key="gmail", source_kind="email", retrieval_kind="gmail:native", snippet="test", fused_score=0.0, can_read=True)` validates without error
- No `import airweave` at module level (only `dotmd.vendor.airweave.*`)
</acceptance_criteria>

### Task 2: Unit tests for the bridge

<read_first>
- backend/src/dotmd/ingestion/gmail_provider.py (just created)
- backend/src/dotmd/core/models.py — SearchCandidate, SourceUnitWindow fields
- backend/tests/test_vendor_airweave_import.py — test file pattern
</read_first>

<action>
Create `backend/tests/test_gmail_bridge.py` with fixture-based unit tests using
`unittest.mock` (no real network calls):

**Fixtures:**
- `mock_token_provider` — a Mock object with `get_token()` returning `"fake-access-token"`
- `mock_gmail_messages_response` — dict simulating `GET /messages?q=...` response:
  `{"messages": [{"id": "msg001", "threadId": "thread001"}, {"id": "msg002", "threadId": "thread002"}]}`
- `mock_gmail_message_detail` — dict simulating `GET /messages/{id}?format=metadata`:
  ```json
  {
    "id": "msg001",
    "threadId": "thread001",
    "snippet": "Hello from the test",
    "payload": {
      "headers": [
        {"name": "Subject", "value": "Test Subject"},
        {"name": "From", "value": "sender@example.com"},
        {"name": "Date", "value": "Mon, 11 May 2026 10:00:00 +0000"}
      ]
    }
  }
  ```
- `mock_gmail_message_full` — dict with `payload.parts` containing a base64url-encoded body

**Tests:**

```
test_search_native_returns_candidates:
  - Mock httpx.Client.get to return messages list then message details
  - Call provider.search_native("test query", limit=2)
  - Assert len(candidates) == 2
  - Assert candidates[0].ref == "gmail:message:msg001"
  - Assert candidates[0].namespace == "gmail"
  - Assert candidates[0].descriptor_key == "gmail"
  - Assert candidates[0].retrieval_kind == "gmail:native"
  - Assert candidates[0].source_native_rank == 0
  - Assert candidates[0].source_native_score is None
  - Assert candidates[0].can_read is True
  - Assert candidates[0].can_materialize is False

test_search_candidate_ref_format:
  - Construct SearchCandidate with ref="gmail:message:abc"
  - Assert no ValidationError (ref validator passes)
  - Construct SearchCandidate with ref="gmail:abc" (no colon after namespace)
  - Assert ValidationError raised (ref must have namespace:document_ref)

test_search_native_api_error_returns_empty:
  - Mock httpx.Client.get to raise httpx.HTTPStatusError (500)
  - Call provider.search_native("query", limit=5)
  - Assert returns [] (empty list, no exception propagated)

test_provider_metadata_whitelist:
  - Call search_native with mock responses
  - Assert candidates[0].provider_metadata keys are subset of GMAIL_PROVIDER_METADATA_KEYS
  - Assert "body" not in candidates[0].provider_metadata (body is not in whitelist)

test_read_unit_window:
  - Mock httpx.Client.get to return full message with base64url body
  - Call provider.read_unit_window("gmail:message:msg001", before=0, after=0)
  - Assert result.namespace == "gmail"
  - Assert len(result.units) == 1
  - Assert result.units[0].unit_type == "email_body"
  - Assert result.units[0].text is non-empty (decoded from base64)

test_gmail_descriptor:
  - from dotmd.ingestion.source_registry import gmail_source_descriptor (may not exist yet — skip/xfail if plan 03 not done)

test_lifecycle_build_missing_config_raises:
  - SourceRuntimeFactory.build("gmail") with no gmail config in store
  - Assert raises SourceLifecycleConfigError
```

Mark `test_gmail_descriptor` and `test_lifecycle_build_missing_config_raises` as
`@pytest.mark.skip(reason="depends on 37-03")` if implementing before Plan 37-03.
Remove the skip markers after Plan 37-03 is done.
</action>

<acceptance_criteria>
- `cd backend && python -m pytest tests/test_gmail_bridge.py -v` exits 0
- test_search_native_returns_candidates passes
- test_search_candidate_ref_format passes (both valid and invalid ref cases)
- test_search_native_api_error_returns_empty passes
- test_provider_metadata_whitelist passes
- test_read_unit_window passes
- No network calls made during test run (all httpx calls mocked)
</acceptance_criteria>

## Verification

```bash
cd /home/j2h4u/repos/j2h4u/dotmd/backend
python -m pytest tests/test_gmail_bridge.py -v
python -m pytest tests/test_vendor_airweave_import.py tests/test_gmail_bridge.py -v
```
