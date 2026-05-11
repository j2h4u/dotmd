---
plan: 37-02
title: BaseConnectorBridge ABC, GmailBridge, and federated search
wave: 2
depends_on:
  - 37-01
files_modified:
  - backend/src/dotmd/ingestion/gmail_provider.py
  - backend/src/dotmd/api/service.py
  - backend/tests/test_gmail_bridge.py
autonomous: true
requirements:
  - AIR-01
must_haves:
  goal: >
    BaseConnectorBridge(ABC) defines the generic bridge contract (search_native,
    read_unit_window, to_search_candidate). GmailBridge implements it via direct
    Gmail API calls (GmailSource.search() is not implemented — direct API is
    correct). GmailApplicationSourceProvider wraps GmailBridge, satisfies
    ApplicationSourceProviderProtocol with explicit no-op stubs for describe_source
    and export_changes (federated-only sources do not support these), and implements
    search_native and read_unit_window. All Gmail httpx calls use an explicit
    connect/read timeout (GMAIL_API_TIMEOUT_SECONDS = 10.0). MIME decoding handles
    multipart, HTML-only, charset, and size limits. Error boundaries: 401 raises
    SourceAuthError, 429/5xx raises SourceTemporaryUnavailable. source_native_score=None
    is safe because federated candidates bypass RRF and flow through
    _merge_with_federated_quota (quota-based slots, not score-based fusion).
    The is_low_signal_telegram_text filter in _merge_with_federated_quota is
    generalized to a source-neutral predicate so Gmail candidates are not silently
    dropped.
  truths:
    - gmail_provider.py exists at backend/src/dotmd/ingestion/gmail_provider.py
    - BaseConnectorBridge(ABC) defined in gmail_provider.py with abstract methods search_native, read_unit_window, to_search_candidate
    - GmailBridge(BaseConnectorBridge) implements all three abstract methods
    - GmailApplicationSourceProvider wraps GmailBridge and implements ApplicationSourceProviderProtocol
    - GmailApplicationSourceProvider.describe_source() raises NotImplementedError with message "Gmail is a federated-only source; describe_source is not supported"
    - GmailApplicationSourceProvider.export_changes() raises NotImplementedError with message "Gmail is a federated-only source; export_changes is not supported"
    - All httpx calls in GmailBridge use timeout=httpx.Timeout(GMAIL_API_TIMEOUT_SECONDS, connect=5.0)
    - GMAIL_API_TIMEOUT_SECONDS = 10.0 defined as module-level constant
    - search_native(query, limit) returns list[SearchCandidate]
    - Every SearchCandidate has ref="gmail:message:<id>", namespace="gmail", descriptor_key="gmail"
    - source_native_score=None, source_native_rank=rank (zero-based)
    - MIME decoding: prefers text/plain, falls back to stripped text/html, caps body at 1MB
    - 401 response raises SourceAuthError; 429/5xx raises SourceTemporaryUnavailable
    - No direct secret file reads inside GmailBridge or GmailApplicationSourceProvider
    - provider_metadata whitelist: message_id, thread_id, sender, subject, sent_at
    - _merge_with_federated_quota in service.py uses a source-neutral low-signal filter (not is_low_signal_telegram_text)
    - O(n) individual metadata fetch round-trips are documented as a known limitation with a beads follow-up task
---

# Plan 37-02: BaseConnectorBridge ABC, GmailBridge, and federated search

## Objective

Implement the generic `BaseConnectorBridge(ABC)` contract and `GmailBridge` as
its first implementation. Wrap in `GmailApplicationSourceProvider` that satisfies
`ApplicationSourceProviderProtocol` — including explicit no-op stubs for
`describe_source` and `export_changes` (federated-only sources do not support
these). Add explicit httpx timeouts on all Gmail API calls. Generalize the
`_merge_with_federated_quota` low-signal filter in `service.py` so it does not
silently drop Gmail candidates. Full MIME decoding, error classification, and
a fusion-correctness test that confirms `source_native_score=None` is safe.

**Cycle 2 HIGHs addressed in this plan:**
1. `ApplicationSourceProviderProtocol` conformance: explicit `describe_source` and `export_changes` no-op stubs on `GmailApplicationSourceProvider`.
2. Telegram-specific filter generalization: `_merge_with_federated_quota` must not use `is_low_signal_telegram_text` on non-Telegram sources.
3. Search-level httpx timeout: `GMAIL_API_TIMEOUT_SECONDS = 10.0` applied to all httpx calls in `GmailBridge`.
4. O(n) metadata round-trips: documented as known limitation with follow-up task filed.

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

**[Cycle 2 HIGH] ApplicationSourceProviderProtocol conformance:**
`ApplicationSourceProviderProtocol` in `source_provider.py` requires three methods:
`describe_source`, `export_changes`, and `read_unit_window`. Gmail is federated-only
and does not support `describe_source` (no persistent source description) or
`export_changes` (no cursor-based sync). `GmailApplicationSourceProvider` must
implement both as explicit `NotImplementedError` stubs so the class structurally
satisfies the protocol at runtime without silently failing. The stub messages
must make the federated-only constraint clear.

**[Cycle 2 HIGH] Telegram-specific filter in `_merge_with_federated_quota`:**
`service.py` line 194-197 applies `is_low_signal_telegram_text()` to ALL federated
candidates (not just Telegram). Gmail snippets are short email subjects/previews
and would be incorrectly filtered. The fix: replace `is_low_signal_telegram_text`
in `_merge_with_federated_quota` with a source-neutral `_is_low_signal_federated`
helper that only applies the text-quality filter to Telegram candidates (keyed by
`candidate.namespace == "telegram"` or `candidate.retrieval_kind.startswith("tg:")`).
Non-Telegram candidates are passed through the filter unconditionally.

**[Cycle 2 HIGH] Search-level httpx timeout:**
All Gmail API calls via `httpx.Client` must use an explicit timeout. A slow or
unreachable Gmail endpoint blocks the synchronous search pipeline indefinitely.
Define `GMAIL_API_TIMEOUT_SECONDS = 10.0` at module level and apply
`timeout=httpx.Timeout(GMAIL_API_TIMEOUT_SECONDS, connect=5.0)` to every
`self._client.get(...)` call in `GmailBridge`. On `httpx.TimeoutException`,
raise `SourceTemporaryUnavailable("Gmail API timed out")`.

**[Cycle 2 HIGH] O(n) metadata fetch round-trips — known limitation:**
For `limit=100`, the current design makes 1 search call + up to 100 individual
`GET /messages/{id}?format=metadata` calls (101 total HTTP round-trips). Gmail's
`batch` endpoint (`POST /batch`) could bundle multiple requests but has complex
multipart/mixed handling. For the spike this is acceptable (limit defaults to 20).
Document this explicitly in a code comment and file a follow-up beads task.
Do NOT silently assume batch works — the comment must state it does not in this
implementation.

## Tasks

### Task 1: Generalize `_merge_with_federated_quota` filter in service.py

**This task must run before Task 2.** The existing Telegram-specific filter silently
drops Gmail candidates. Fix it first so the Gmail provider is safe to add.

<read_first>
- backend/src/dotmd/api/service.py — _merge_with_federated_quota() at lines 166-204, is_low_signal_telegram_text import at line 33, full function body
- backend/src/dotmd/ingestion/telegram_provider.py — is_low_signal_telegram_text() definition
</read_first>

<action>
In `backend/src/dotmd/api/service.py`:

**Step 1: Replace the `is_low_signal_telegram_text` import** at the top of the file:

Change:
```python
from dotmd.ingestion.telegram_provider import is_low_signal_telegram_text
```
to keep the import but also define a source-neutral wrapper directly in service.py:
```python
from dotmd.ingestion.telegram_provider import is_low_signal_telegram_text as _is_low_signal_telegram_text
```

**Step 2: Add a source-neutral helper** `_is_low_signal_federated_candidate` immediately
before `_merge_with_federated_quota`:

```python
def _is_low_signal_federated_candidate(candidate: SearchCandidate) -> bool:
    """Return True if a federated candidate should be excluded from quota slots.

    Only applies the text-quality filter to Telegram candidates, where the
    low-signal heuristic (very short, emoji-only, or no alphanumeric content)
    is meaningful and proven in the trickle ingestion pipeline.

    Non-Telegram federated candidates (e.g., Gmail) are passed through
    unconditionally — their snippet quality semantics differ.
    """
    is_telegram = (
        candidate.namespace == "telegram"
        or (candidate.retrieval_kind or "").startswith("tg:")
    )
    if is_telegram:
        return _is_low_signal_telegram_text(candidate.snippet or "")
    return False
```

**Step 3: Update `_merge_with_federated_quota`** to use the new helper:

Change lines 194-197:
```python
    filtered_fed = [
        c for c in fed_candidates
        if not is_low_signal_telegram_text(c.snippet or "")
    ]
```
to:
```python
    filtered_fed = [
        c for c in fed_candidates
        if not _is_low_signal_federated_candidate(c)
    ]
```

**Step 4: Update the docstring** of `_merge_with_federated_quota` to replace:
```
    The is_low_signal_telegram_text pre-filter removes very short or emoji-only
    messages that FTS scored well by keyword but carry no semantic content. The
    filter is already proven in the trickle ingestion pipeline.
```
with:
```
    The _is_low_signal_federated_candidate pre-filter removes very short or
    emoji-only Telegram messages that FTS scored well by keyword but carry no
    semantic content. Non-Telegram sources (e.g., Gmail) are passed through
    unconditionally — their snippet quality semantics differ.
```
</action>

<acceptance_criteria>
- `_is_low_signal_federated_candidate` function exists in service.py
- `_merge_with_federated_quota` calls `_is_low_signal_federated_candidate`, not `is_low_signal_telegram_text` directly
- A `SearchCandidate` with `namespace="gmail"` and `snippet="ok"` is NOT filtered out by `_is_low_signal_federated_candidate` (returns False)
- A `SearchCandidate` with `namespace="telegram"` and `snippet="ok"` IS filtered out (returns True — "ok" is in LOW_SIGNAL_TEXTS)
- Existing Telegram behavior is preserved: `python -m pytest backend/tests/ -x -q` still passes
</acceptance_criteria>

### Task 2: Implement BaseConnectorBridge ABC and GmailBridge with timeout

<read_first>
- backend/src/dotmd/ingestion/telegram_provider.py — search_native() pattern, SearchCandidate construction, TELEGRAM_PROVIDER_METADATA_KEYS pattern
- backend/src/dotmd/core/models.py — SearchCandidate, SourceUnitWindow, SourceCapability fields
- backend/src/dotmd/ingestion/source_provider.py — ApplicationSourceProviderProtocol (ALL three required methods: describe_source, export_changes, read_unit_window)
- backend/src/dotmd/vendor/airweave/shims.py — GmailOAuthTokenProvider interface
- backend/src/dotmd/search/federated.py — FederatedEngineOutcome, confirm federated candidates bypass fuse_results()
- backend/src/dotmd/api/service.py — _merge_with_federated_quota() (after Task 1 edit), confirm score=None is safe
</read_first>

<action>
Create `backend/src/dotmd/ingestion/gmail_provider.py`.

**Section 1: Module-level constants and error types**

```python
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
GMAIL_PROVIDER_METADATA_KEYS = frozenset({"message_id", "thread_id", "sender", "subject", "sent_at"})
GMAIL_BODY_MAX_BYTES = 1024 * 1024  # 1MB cap on decoded body
GMAIL_API_TIMEOUT_SECONDS = 10.0    # explicit per-request timeout for all Gmail API calls
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
        """Search the external source and return SearchCandidate objects."""
        ...

    @abstractmethod
    def read_unit_window(self, unit_ref: str, before: int, after: int) -> SourceUnitWindow:
        """Fetch full content for a previously-returned ref."""
        ...

    @abstractmethod
    def to_search_candidate(self, entity_fields: dict, rank: int) -> SearchCandidate:
        """Map generic entity fields to a SearchCandidate.

        source_native_score is not set (None) — federated candidates bypass RRF
        and flow through _merge_with_federated_quota (quota-based, not score-based).
        """
        ...
```

**Section 3: GmailBridge(BaseConnectorBridge)**

Constructor: `__init__(self, token_provider: GmailOAuthTokenProvider, *, search_result_limit: int = 10)`
- Creates a `httpx.Client` instance with explicit timeout:
  `self._client = httpx.Client(timeout=httpx.Timeout(GMAIL_API_TIMEOUT_SECONDS, connect=5.0))`
- Stores token_provider and search_result_limit

`search_native(query, limit)`:
- Get access token via `self._token_provider.get_token()`
- Call `GET {GMAIL_API_BASE}/messages?q={query}&maxResults={limit}` with Authorization Bearer header
- Response: `{"messages": [{"id": "...", "threadId": "..."}], ...}` — IDs only
- For each message ID (up to limit), fetch metadata individually:
  - `GET {GMAIL_API_BASE}/messages/{id}?format=metadata&metadataHeaders=Subject,From,Date`
  - Extract: subject (Subject header), sender (From header), date (Date header), snippet
  - **KNOWN LIMITATION (O(n) round-trips):** For limit=N, this makes 1 + N individual
    HTTP calls. Gmail's batch endpoint (POST /batch) would reduce this to 2 calls but
    requires multipart/mixed request handling. Not implemented in this spike.
    Follow-up: file a beads task for batch metadata fetch optimization.
- Call `self.to_search_candidate(fields, rank)` for each message
- Error handling:
  - `httpx.TimeoutException`: raise `SourceTemporaryUnavailable("Gmail API timed out")`
  - 401/403: clear token cache via `self._token_provider._cached_token = None`, raise `SourceAuthError(f"Gmail auth failed: {status_code}")`
  - 429: raise `SourceTemporaryUnavailable("Gmail rate limited (429)")`
  - 5xx: raise `SourceTemporaryUnavailable(f"Gmail server error: {status_code}")`
  - Empty results: return `[]`

`read_unit_window(unit_ref, before, after)`:
- Parse message_id: strip `"gmail:message:"` prefix
- Get access token
- Call `GET {GMAIL_API_BASE}/messages/{message_id}?format=full` (uses client with timeout)
- Decode body via `_decode_gmail_body(payload)` helper
- Build and return `SourceUnitWindow` with one `SourceUnit` of `unit_type="email_body"`
- On `httpx.TimeoutException`: raise `SourceTemporaryUnavailable("Gmail read timed out")`
- On other API error: raise `RuntimeError(f"Gmail read failed for {unit_ref}: {status_code}")`

`to_search_candidate(entity_fields, rank)`:
- `source_native_score=None`, `source_native_rank=rank`, `fused_score=0.0`
- ref=`"gmail:message:{message_id}"`, namespace=`"gmail"`, descriptor_key=`"gmail"`
- Apply GMAIL_PROVIDER_METADATA_KEYS whitelist to provider_metadata

**Section 4: Module-level helpers**

`_extract_header(headers, name)`, `_decode_gmail_body(payload)`,
`_parse_gmail_date(date_str)`, `_strip_html(html_text)` — same as previously
specified with full MIME edge case handling.

**Section 5: GmailApplicationSourceProvider**

Thin wrapper satisfying `ApplicationSourceProviderProtocol`. ALL THREE protocol
methods must be implemented — `describe_source` and `export_changes` as explicit
no-op stubs, `read_unit_window` and `search_native` delegating to the bridge:

```python
class GmailApplicationSourceProvider:
    """ApplicationSourceProviderProtocol implementation for Gmail (federated-only).

    Gmail participates as a federated search provider only — it has no local
    cursor-based sync and no persistent source description. The describe_source
    and export_changes methods raise NotImplementedError explicitly so callers
    that attempt full source lifecycle operations fail with a clear message rather
    than an AttributeError.
    """

    def __init__(self, token_provider: GmailOAuthTokenProvider, *, search_result_limit: int = 10):
        self._bridge = GmailBridge(token_provider, search_result_limit=search_result_limit)

    def describe_source(self) -> ApplicationSourceDescription:
        raise NotImplementedError(
            "Gmail is a federated-only source; describe_source is not supported. "
            "Use search_native() or read_unit_window() instead."
        )

    def export_changes(
        self,
        cursor: str | None,
        limit: int,
        updated_after: str | None = None,
        updated_after_cursor: str | None = None,
    ) -> ApplicationSourceChangeBatch:
        raise NotImplementedError(
            "Gmail is a federated-only source; export_changes is not supported. "
            "Gmail does not participate in cursor-based incremental sync."
        )

    def search_native(self, query: str, limit: int) -> list[SearchCandidate]:
        return self._bridge.search_native(query, limit)

    def read_unit_window(self, unit_ref: str, before: int, after: int) -> SourceUnitWindow:
        return self._bridge.read_unit_window(unit_ref, before, after)
```
</action>

<acceptance_criteria>
- `from dotmd.ingestion.gmail_provider import GmailApplicationSourceProvider, GmailBridge, BaseConnectorBridge` imports cleanly
- `BaseConnectorBridge` is an ABC with abstract methods `search_native`, `read_unit_window`, `to_search_candidate`
- `GmailBridge` is a concrete subclass of `BaseConnectorBridge`
- `GmailApplicationSourceProvider` has all four methods: `describe_source`, `export_changes`, `search_native`, `read_unit_window`
- `GmailApplicationSourceProvider().describe_source()` raises `NotImplementedError` with "federated-only source" in message
- `GmailApplicationSourceProvider().export_changes(None, 10)` raises `NotImplementedError` with "federated-only source" in message
- `GMAIL_API_TIMEOUT_SECONDS` is defined at module level as `10.0`
- `GmailBridge.__init__` constructs `httpx.Client` with `timeout=httpx.Timeout(GMAIL_API_TIMEOUT_SECONDS, connect=5.0)`
- A comment in `search_native` documents O(n) round-trips as a known limitation
- No `import airweave` at module level (only `dotmd.vendor.airweave.*`)
- `_decode_gmail_body` handles multipart/alternative, text/html fallback, and empty payload without raising
</acceptance_criteria>

### Task 3: Unit tests for the bridge

<read_first>
- backend/src/dotmd/ingestion/gmail_provider.py (just created in Task 2)
- backend/src/dotmd/api/service.py — _merge_with_federated_quota() and _is_low_signal_federated_candidate() (just updated in Task 1)
- backend/src/dotmd/core/models.py — SearchCandidate, SourceUnitWindow fields
- backend/tests/test_vendor_airweave_import.py — test file pattern
- backend/src/dotmd/search/federated.py — FederatedEngineOutcome, confirm federated bypass of fuse_results
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

test_gmail_provider_describe_source_raises_not_implemented:
  """GmailApplicationSourceProvider.describe_source must raise NotImplementedError
  with a clear 'federated-only source' message (Cycle 2 HIGH: protocol conformance)."""
  - Instantiate GmailApplicationSourceProvider with mock token provider
  - Call provider.describe_source()
  - Assert raises NotImplementedError
  - Assert "federated-only source" in str(exc)

test_gmail_provider_export_changes_raises_not_implemented:
  """GmailApplicationSourceProvider.export_changes must raise NotImplementedError
  with a clear 'federated-only source' message (Cycle 2 HIGH: protocol conformance)."""
  - Instantiate GmailApplicationSourceProvider with mock token provider
  - Call provider.export_changes(cursor=None, limit=10)
  - Assert raises NotImplementedError
  - Assert "federated-only source" in str(exc)

test_gmail_bridge_uses_explicit_timeout:
  """GmailBridge httpx.Client must be constructed with GMAIL_API_TIMEOUT_SECONDS timeout
  (Cycle 2 HIGH: no search-level timeout)."""
  - Import GMAIL_API_TIMEOUT_SECONDS from gmail_provider
  - Assert GMAIL_API_TIMEOUT_SECONDS == 10.0
  - Instantiate GmailBridge with mock token provider
  - Assert bridge._client.timeout.read == GMAIL_API_TIMEOUT_SECONDS
  - Assert bridge._client.timeout.connect == 5.0

test_search_native_timeout_raises_source_temporarily_unavailable:
  """httpx.TimeoutException during search must map to SourceTemporaryUnavailable
  (Cycle 2 HIGH: no search-level timeout)."""
  - Mock httpx.Client.get to raise httpx.TimeoutException("timed out")
  - Call provider.search_native("query", limit=5)
  - Assert raises SourceTemporaryUnavailable
  - Assert "timed out" in str(exc).lower() or "timeout" in str(exc).lower()

test_low_signal_filter_passes_gmail_candidates:
  """Gmail candidates must NOT be filtered by _is_low_signal_federated_candidate
  even for short snippets like 'ok' (Cycle 2 HIGH: Telegram-specific filter)."""
  - from dotmd.api.service import _is_low_signal_federated_candidate
  - Create SearchCandidate with namespace="gmail", snippet="ok"
  - Assert _is_low_signal_federated_candidate(candidate) is False
  - Create SearchCandidate with namespace="gmail", snippet="да"
  - Assert _is_low_signal_federated_candidate(candidate) is False

test_low_signal_filter_still_filters_telegram_candidates:
  """Telegram candidates with low-signal text must still be filtered
  (Cycle 2 HIGH: regression guard for Telegram behavior)."""
  - from dotmd.api.service import _is_low_signal_federated_candidate
  - Create SearchCandidate with namespace="telegram", retrieval_kind="tg:fts", snippet="ok"
  - Assert _is_low_signal_federated_candidate(candidate) is True
  - Create SearchCandidate with namespace="telegram", retrieval_kind="tg:fts", snippet="Meeting notes about the Q4 roadmap"
  - Assert _is_low_signal_federated_candidate(candidate) is False
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
- test_gmail_provider_describe_source_raises_not_implemented passes
- test_gmail_provider_export_changes_raises_not_implemented passes
- test_gmail_bridge_uses_explicit_timeout passes
- test_search_native_timeout_raises_source_temporarily_unavailable passes
- test_low_signal_filter_passes_gmail_candidates passes
- test_low_signal_filter_still_filters_telegram_candidates passes
- No network calls made during test run (all httpx calls mocked)
</acceptance_criteria>

## Verification

```bash
cd /home/j2h4u/repos/j2h4u/dotmd/backend

# All bridge tests pass
python -m pytest tests/test_gmail_bridge.py -v

# ABC contract
python -c "
from dotmd.ingestion.gmail_provider import BaseConnectorBridge, GmailBridge
import inspect
assert inspect.isabstract(BaseConnectorBridge)
assert issubclass(GmailBridge, BaseConnectorBridge)
print('ABC contract: OK')
"

# Protocol stubs: describe_source and export_changes raise NotImplementedError
python -c "
from unittest.mock import MagicMock
from dotmd.ingestion.gmail_provider import GmailApplicationSourceProvider
p = GmailApplicationSourceProvider(MagicMock())
try:
    p.describe_source()
    assert False, 'should have raised'
except NotImplementedError as e:
    assert 'federated-only source' in str(e), f'Wrong message: {e}'
    print('describe_source NotImplementedError: OK')
try:
    p.export_changes(None, 10)
    assert False, 'should have raised'
except NotImplementedError as e:
    assert 'federated-only source' in str(e), f'Wrong message: {e}'
    print('export_changes NotImplementedError: OK')
"

# Timeout constant defined
python -c "
from dotmd.ingestion.gmail_provider import GMAIL_API_TIMEOUT_SECONDS
assert GMAIL_API_TIMEOUT_SECONDS == 10.0
print(f'GMAIL_API_TIMEOUT_SECONDS={GMAIL_API_TIMEOUT_SECONDS}: OK')
"

# Filter generalization: Gmail candidates pass through, Telegram low-signal still filtered
python -c "
from dotmd.api.service import _is_low_signal_federated_candidate
from dotmd.core.models import SearchCandidate
gmail_ok = SearchCandidate(ref='gmail:message:x', namespace='gmail', descriptor_key='gmail', source_kind='email', retrieval_kind='gmail:native', snippet='ok', fused_score=0.0, can_read=True)
assert not _is_low_signal_federated_candidate(gmail_ok), 'Gmail ok snippet should pass through'
tg_ok = SearchCandidate(ref='telegram:dialog:1:message:1', namespace='telegram', descriptor_key='telegram', source_kind='chat', retrieval_kind='tg:fts', snippet='ok', fused_score=0.0, can_read=True)
assert _is_low_signal_federated_candidate(tg_ok), 'Telegram ok snippet should be filtered'
print('Filter generalization: OK')
"
```
