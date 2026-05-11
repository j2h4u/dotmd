---
plan: 37-02
title: BaseConnectorBridge ABC, GmailBridge, and federated search
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
    BaseConnectorBridge(ABC) defines the generic bridge contract (search_native,
    read_unit_window, to_search_candidate). GmailBridge implements it via direct
    Gmail API calls (GmailSource.search() is not implemented — direct API is
    correct). GmailApplicationSourceProvider wraps GmailBridge and satisfies
    ApplicationSourceProviderProtocol. MIME decoding handles multipart, HTML-only,
    charset, and size limits. Error boundaries: 401 raises SourceAuthError,
    429/5xx raises SourceTemporaryUnavailable. source_native_score=None is safe
    because federated candidates bypass RRF and flow through _merge_with_federated_quota
    (quota-based slots, not score-based fusion).
  truths:
    - gmail_provider.py exists at backend/src/dotmd/ingestion/gmail_provider.py
    - BaseConnectorBridge(ABC) defined in gmail_provider.py with abstract methods search_native, read_unit_window, to_search_candidate
    - GmailBridge(BaseConnectorBridge) implements all three abstract methods
    - GmailApplicationSourceProvider wraps GmailBridge and implements ApplicationSourceProviderProtocol
    - search_native(query, limit) returns list[SearchCandidate]
    - Every SearchCandidate has ref="gmail:message:<id>", namespace="gmail", descriptor_key="gmail"
    - source_native_score=None, source_native_rank=rank (zero-based)
    - MIME decoding: prefers text/plain, falls back to stripped text/html, caps body at 1MB
    - 401 response raises SourceAuthError; 429/5xx raises SourceTemporaryUnavailable
    - No direct secret file reads inside GmailBridge or GmailApplicationSourceProvider
    - provider_metadata whitelist: message_id, thread_id, sender, subject, sent_at
---

# Plan 37-02: BaseConnectorBridge ABC, GmailBridge, and federated search

## Objective

Implement the generic `BaseConnectorBridge(ABC)` contract and `GmailBridge` as
its first implementation. Wrap in `GmailApplicationSourceProvider` that satisfies
`ApplicationSourceProviderProtocol`. Full MIME decoding, error classification,
and a fusion-correctness test that confirms `source_native_score=None` is safe.

## Context

**Critical finding from research:** `GmailSource.search()` is NOT implemented
in Airweave's `GmailSource` — the abstract base stub exists but is not overridden.
The bridge therefore calls the Gmail API directly via `httpx.Client` rather
than wrapping `GmailSource.search()`. This is the correct approach.

**D-03 requirement (generic bridge):** CONTEXT.md says the bridge must be generic
across all `BaseSource` subclasses. This is satisfied by `BaseConnectorBridge(ABC)`
with `GmailBridge` as the first implementation. Future connectors implement the
same ABC. Because `GmailSource.search()` is absent, the generic call path applies
only to connectors that implement `search()` — the ABC documents this, and
`GmailBridge.search_native()` is the Gmail-specific implementation of the contract.

**source_native_score=None safety:** Federated candidates do NOT go through RRF.
In `service.py`, `fanout_federated()` returns `FederatedEngineOutcome.candidates`
which flow directly into `_merge_with_federated_quota()` (quota-based slot
reservation, not score-based sorting). The `fused_score` on the final
`SearchCandidate` is set from the quota merge, not from `source_native_score`.
This is confirmed by `federated.py` — `FederatedEngineOutcome` holds pre-built
`SearchCandidate` objects that bypass `fuse_results()`. A test documents this.

**Pattern to follow:** `TelegramApplicationSourceProvider.search_native()` in
`telegram_provider.py` — same SearchCandidate construction idiom.

## Tasks

### Task 1: Implement BaseConnectorBridge ABC

<read_first>
- backend/src/dotmd/ingestion/telegram_provider.py — search_native() pattern, SearchCandidate construction, TELEGRAM_PROVIDER_METADATA_KEYS pattern
- backend/src/dotmd/core/models.py — SearchCandidate, SourceUnitWindow, SourceCapability fields
- backend/src/dotmd/ingestion/source_provider.py — ApplicationSourceProviderProtocol
- backend/src/dotmd/vendor/airweave/shims.py — GmailOAuthTokenProvider interface
- backend/src/dotmd/search/federated.py — FederatedEngineOutcome, confirm federated candidates bypass fuse_results()
- backend/src/dotmd/api/service.py — _merge_with_federated_quota(), confirm score=None is safe
</read_first>

<action>
Create `backend/src/dotmd/ingestion/gmail_provider.py`.

**Section 1: Module-level constants and error types**

```python
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
GMAIL_PROVIDER_METADATA_KEYS = frozenset({"message_id", "thread_id", "sender", "subject", "sent_at"})
GMAIL_BODY_MAX_BYTES = 1024 * 1024  # 1MB cap on decoded body
```

Import `SourceAuthError` and `SourceTemporaryUnavailable` from
`dotmd.core.exceptions` (or define them locally if they don't exist yet):
```python
# If these don't exist in dotmd.core.exceptions, define them here:
class SourceAuthError(RuntimeError):
    """Raised when a source returns 401/403 — credential needs refresh."""
class SourceTemporaryUnavailable(RuntimeError):
    """Raised when a source returns 429/5xx — transient failure."""
```

**Section 2: BaseConnectorBridge ABC**

```python
from abc import ABC, abstractmethod

class BaseConnectorBridge(ABC):
    """Generic bridge contract for Airweave-style connectors to dotMD.

    Implementations provide connector-specific search and read logic.
    The abstract interface satisfies D-03 (generic across BaseSource subclasses).

    Note on search() availability: connectors that implement BaseSource.search()
    (those with federated_search=True in @source decorator) can delegate
    search_native() to source.search(). Connectors without search() (e.g., Gmail)
    must implement direct API search. Inspect the connector before wrapping:
        grep "async def search" platform/sources/<name>.py
    """

    @abstractmethod
    def search_native(self, query: str, limit: int) -> list[SearchCandidate]:
        """Search the external source and return SearchCandidate objects.

        Implementations call the source's native search API (or BaseSource.search()
        if available) and map results to SearchCandidate using to_search_candidate().
        Must return [] on empty results. Must raise SourceAuthError on 401/403,
        SourceTemporaryUnavailable on 429/5xx.
        """
        ...

    @abstractmethod
    def read_unit_window(self, unit_ref: str, before: int, after: int) -> SourceUnitWindow:
        """Fetch full content for a previously-returned ref.

        unit_ref has the form "namespace:document_ref:..." as returned by search_native().
        Must raise RuntimeError on non-recoverable errors.
        """
        ...

    @abstractmethod
    def to_search_candidate(self, entity_fields: dict, rank: int) -> SearchCandidate:
        """Map generic entity fields to a SearchCandidate.

        entity_fields: connector-specific metadata dict (e.g., from Gmail API response
        or from BaseEntity field extraction). rank: zero-based position in result list.
        source_native_score is not set (None) — federated candidates bypass RRF and
        flow through _merge_with_federated_quota (quota-based, not score-based).
        """
        ...
```

**Section 3: GmailBridge(BaseConnectorBridge)**

Implements all three abstract methods using direct Gmail API calls.

Constructor: `__init__(self, token_provider: GmailOAuthTokenProvider, *, search_result_limit: int = 10)`
- Creates a `httpx.Client` instance (sync, matches dotMD's sync provider pattern)
- Stores token_provider and search_result_limit

`search_native(query, limit)`:
- Get access token via `self._token_provider.get_token()`
- Call `GET {GMAIL_API_BASE}/messages?q={query}&maxResults={limit}` with Authorization Bearer header
- Response: `{"messages": [{"id": "...", "threadId": "..."}], ...}` — IDs only
- For each message (up to limit, batch fetch metadata):
  - Call `GET {GMAIL_API_BASE}/messages/{id}?format=metadata&metadataHeaders=Subject,From,Date`
  - Extract: subject (Subject header), sender (From header), date (Date header), snippet
- Call `self.to_search_candidate(fields, rank)` for each message
- Error handling:
  - 401/403: clear token cache via `self._token_provider._cached_token = None`, then raise `SourceAuthError(f"Gmail auth failed: {status_code}")`
  - 429: raise `SourceTemporaryUnavailable(f"Gmail rate limited (429)")`
  - 5xx: raise `SourceTemporaryUnavailable(f"Gmail server error: {status_code}")`
  - Empty results: return `[]` (not an error)
- Use `httpx.Client` (sync) to match Telegram provider pattern

`read_unit_window(unit_ref, before, after)`:
- Parse message_id: strip `"gmail:message:"` prefix
- Get access token
- Call `GET {GMAIL_API_BASE}/messages/{message_id}?format=full`
- Decode body via `_decode_gmail_body(payload)` helper
- Build `SourceUnit(namespace="gmail", document_ref=f"message:{message_id}", unit_ref=f"message:{message_id}", unit_type="email_body", text=decoded_body, order_key="0", fingerprint=sha256(decoded_body), updated_at=datetime.utcnow(), metadata_json={sender, subject})`
- Return `SourceUnitWindow(namespace="gmail", document_ref=..., unit_ref=..., units=[unit], metadata_json={})`
- On API error: raise `RuntimeError(f"Gmail read failed for {unit_ref}: {status_code}")`

`to_search_candidate(entity_fields, rank)`:
- Builds `SearchCandidate` from entity_fields dict using GMAIL_PROVIDER_METADATA_KEYS whitelist
- `source_native_score=None` (Gmail API returns no relevance score — safe because federated candidates bypass RRF, confirmed by reading federated.py and service.py)
- `source_native_rank=rank` (zero-based)
- `fused_score=0.0` (populated by service layer after quota merge)

**Section 4: Module-level helpers**

`_extract_header(headers: list[dict], name: str) -> str | None`:
- Case-insensitive header lookup in Gmail API header list format
- `[{"name": "Subject", "value": "..."}, ...]`

`_decode_gmail_body(payload: dict) -> str`:
- MIME body decoding with full edge case handling:
  1. **Part selection order**: prefer `text/plain` > stripped `text/html` > any text/* part
  2. **Multipart handling**: recursively walk `payload.parts` for multipart/alternative and multipart/mixed
  3. **Encoding variants**: handle both standard base64 and URL-safe base64url (Gmail API uses base64url)
     - Always pad before decoding: `base64.urlsafe_b64decode(data + "==")`
  4. **Charset**: decode per part's Content-Type charset, fall back to UTF-8 on error
     - Extract charset from `Content-Type` header: `text/plain; charset=utf-8`
  5. **HTML fallback**: if only text/html found, strip tags with a simple regex or html.parser
  6. **Size limit**: truncate decoded text at `GMAIL_BODY_MAX_BYTES` with `\n[truncated]` suffix
  7. **Empty body**: if no body found, return the API-provided snippet or empty string
  8. **Malformed base64**: catch `binascii.Error` and return empty string with a log warning

`_parse_gmail_date(date_str: str | None) -> str | None`:
- Parse RFC2822 date to ISO8601, return None on parse error

`_strip_html(html_text: str) -> str`:
- Strip HTML tags using `html.parser.HTMLParser` (no external deps)
- Collapse whitespace

**Section 5: GmailApplicationSourceProvider**

Thin wrapper that delegates to `GmailBridge` and satisfies `ApplicationSourceProviderProtocol`.

```python
class GmailApplicationSourceProvider:
    def __init__(self, token_provider: GmailOAuthTokenProvider, *, search_result_limit: int = 10):
        self._bridge = GmailBridge(token_provider, search_result_limit=search_result_limit)

    def search_native(self, query: str, limit: int) -> list[SearchCandidate]:
        return self._bridge.search_native(query, limit)

    def read_unit_window(self, unit_ref: str, before: int, after: int) -> SourceUnitWindow:
        return self._bridge.read_unit_window(unit_ref, before, after)
```

This thin wrapper exists so `SourceRuntimeFactory.build("gmail")` can construct
a concrete `ApplicationSourceProviderProtocol` without knowing the bridge internals.
</action>

<acceptance_criteria>
- `from dotmd.ingestion.gmail_provider import GmailApplicationSourceProvider, GmailBridge, BaseConnectorBridge` imports cleanly
- `BaseConnectorBridge` is an ABC with abstract methods `search_native`, `read_unit_window`, `to_search_candidate`
- `GmailBridge` is a concrete subclass of `BaseConnectorBridge` (all abstract methods implemented)
- `GmailApplicationSourceProvider` has `search_native` and `read_unit_window` methods
- `search_native` signature matches `ApplicationSourceProviderProtocol.search_native(query: str, limit: int) -> list[SearchCandidate]`
- `from dotmd.core.models import SearchCandidate; SearchCandidate(ref="gmail:message:abc123", namespace="gmail", descriptor_key="gmail", source_kind="email", retrieval_kind="gmail:native", snippet="test", fused_score=0.0, can_read=True)` validates without error
- No `import airweave` at module level (only `dotmd.vendor.airweave.*`)
- `_decode_gmail_body` handles multipart/alternative, text/html fallback, and empty payload without raising
</acceptance_criteria>

### Task 2: Unit tests for the bridge

<read_first>
- backend/src/dotmd/ingestion/gmail_provider.py (just created)
- backend/src/dotmd/core/models.py — SearchCandidate, SourceUnitWindow fields
- backend/tests/test_vendor_airweave_import.py — test file pattern
- backend/src/dotmd/search/federated.py — FederatedEngineOutcome, confirm federated bypass of fuse_results
- backend/src/dotmd/api/service.py — _merge_with_federated_quota(), confirm quota-based not score-based
</read_first>

<action>
Create `backend/tests/test_gmail_bridge.py` with fixture-based unit tests using
`unittest.mock` (no real network calls):

**Fixtures:**
- `mock_token_provider` — a Mock with `get_token()` returning `"fake-access-token"`, `_cached_token=None`
- `mock_gmail_messages_response` — `{"messages": [{"id": "msg001", "threadId": "thread001"}, {"id": "msg002", "threadId": "thread002"}]}`
- `mock_gmail_message_detail` — full metadata response with Subject, From, Date headers + snippet
- `mock_gmail_message_full` — full message with multipart MIME body (text/plain part with base64url-encoded text)
- `mock_gmail_html_only_message` — message with only text/html part (no text/plain)
- `mock_gmail_empty_body_message` — message with empty payload.parts and a snippet field

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

test_source_native_score_none_is_safe_for_federated_pipeline:
  """
  source_native_score=None is safe because federated candidates bypass RRF.
  In service.py, fanout_federated() returns FederatedEngineOutcome.candidates
  which flow into _merge_with_federated_quota() (quota-based slot reservation).
  The fused_score on the final SearchCandidate is set from quota merge,
  not from source_native_score. This test documents the verified behavior.
  """
  - Construct a SearchCandidate with source_native_score=None
  - Import FederatedEngineOutcome from dotmd.search.federated
  - Create FederatedEngineOutcome(name="gmail:native", status="ok", candidates=[candidate], reason=None, elapsed_ms=0.0)
  - Assert outcome.candidates[0].source_native_score is None
  - Assert outcome.status == "ok"
  - Assert len(outcome.candidates) == 1
  (This test documents that None score is structurally accepted by the outcome type)

test_search_candidate_ref_format:
  - Construct SearchCandidate with ref="gmail:message:abc"
  - Assert no ValidationError (ref validator passes)

test_search_native_api_error_401_raises_source_auth_error:
  - Mock httpx.Client.get to return 401 on message list call
  - Call provider.search_native("query", limit=5)
  - Assert raises SourceAuthError

test_search_native_api_error_429_raises_source_temporarily_unavailable:
  - Mock httpx.Client.get to return 429
  - Call provider.search_native("query", limit=5)
  - Assert raises SourceTemporaryUnavailable

test_search_native_api_error_500_raises_source_temporarily_unavailable:
  - Mock httpx.Client.get to return 500
  - Assert raises SourceTemporaryUnavailable

test_provider_metadata_whitelist:
  - Call search_native with mock responses
  - Assert candidates[0].provider_metadata keys are subset of GMAIL_PROVIDER_METADATA_KEYS
  - Assert "body" not in candidates[0].provider_metadata

test_read_unit_window_text_plain:
  - Mock httpx.Client.get to return full message with base64url-encoded text/plain body
  - Call provider.read_unit_window("gmail:message:msg001", before=0, after=0)
  - Assert result.namespace == "gmail"
  - Assert len(result.units) == 1
  - Assert result.units[0].unit_type == "email_body"
  - Assert result.units[0].text is non-empty (decoded from base64url)

test_read_unit_window_html_only:
  - Mock response has only text/html part (no text/plain)
  - Call read_unit_window
  - Assert result.units[0].text is non-empty (HTML stripped)
  - Assert "<" not in result.units[0].text (tags removed)

test_decode_gmail_body_multipart_alternative:
  - Call _decode_gmail_body with multipart/alternative payload containing text/plain and text/html
  - Assert returns text/plain content (preferred over HTML)

test_decode_gmail_body_empty_payload:
  - Call _decode_gmail_body with payload that has no parts and no body data
  - Assert returns "" without raising

test_decode_gmail_body_size_limit:
  - Create payload with body data that decodes to > 1MB text
  - Call _decode_gmail_body
  - Assert len(result) <= GMAIL_BODY_MAX_BYTES + len("[truncated]")
  - Assert result ends with "[truncated]" or similar marker

test_decode_gmail_body_malformed_base64:
  - Create payload with invalid base64url data
  - Call _decode_gmail_body
  - Assert returns "" without raising (malformed base64 is handled gracefully)

test_gmail_descriptor:
  @pytest.mark.skip(reason="depends on 37-03")
  - from dotmd.ingestion.source_registry import gmail_source_descriptor

test_lifecycle_build_missing_config_raises:
  @pytest.mark.skip(reason="depends on 37-03")
  - SourceRuntimeFactory.build("gmail") with no gmail config in store
  - Assert raises SourceLifecycleConfigError

test_base_connector_bridge_is_abstract:
  - Assert that instantiating BaseConnectorBridge() directly raises TypeError
  - Assert that GmailBridge is a subclass of BaseConnectorBridge
  - Assert issubclass(GmailBridge, BaseConnectorBridge) is True

test_to_search_candidate_generic_fields:
  - Call GmailBridge.to_search_candidate with a minimal entity_fields dict
  - Assert returned SearchCandidate has correct namespace, descriptor_key
  - Assert source_native_score is None
  - Assert source_native_rank == 0 for rank=0 input
  - Assert provider_metadata keys are subset of GMAIL_PROVIDER_METADATA_KEYS
```

All tests use `unittest.mock`; no real network calls.
</action>

<acceptance_criteria>
- `cd backend && python -m pytest tests/test_gmail_bridge.py -v` exits 0
- test_search_native_returns_candidates passes
- test_source_native_score_none_is_safe_for_federated_pipeline passes (documents verified behavior)
- test_search_native_api_error_401_raises_source_auth_error passes
- test_search_native_api_error_429_raises_source_temporarily_unavailable passes
- test_search_native_api_error_500_raises_source_temporarily_unavailable passes
- test_provider_metadata_whitelist passes
- test_read_unit_window_text_plain passes
- test_read_unit_window_html_only passes
- test_decode_gmail_body_multipart_alternative passes
- test_decode_gmail_body_empty_payload passes
- test_decode_gmail_body_size_limit passes
- test_base_connector_bridge_is_abstract passes
- No network calls made during test run (all httpx calls mocked)
</acceptance_criteria>

## Verification

```bash
cd /home/j2h4u/repos/j2h4u/dotmd/backend
python -m pytest tests/test_gmail_bridge.py -v
python -m pytest tests/test_vendor_airweave_import.py tests/test_gmail_bridge.py -v
# Confirm BaseConnectorBridge is ABC and GmailBridge implements it
python -c "
from dotmd.ingestion.gmail_provider import BaseConnectorBridge, GmailBridge
import inspect
assert inspect.isabstract(BaseConnectorBridge)
assert issubclass(GmailBridge, BaseConnectorBridge)
print('ABC contract: OK')
"
```
