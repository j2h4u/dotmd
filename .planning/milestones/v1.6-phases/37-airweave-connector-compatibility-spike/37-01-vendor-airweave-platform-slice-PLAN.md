---
plan: 37-01
title: Vendor Airweave platform slice and DI shims
wave: 1
depends_on: []
files_modified:
  - backend/src/dotmd/vendor/__init__.py
  - backend/src/dotmd/vendor/airweave/__init__.py
  - backend/src/dotmd/vendor/airweave/entities_base.py
  - backend/src/dotmd/vendor/airweave/entities_gmail.py
  - backend/src/dotmd/vendor/airweave/source_base.py
  - backend/src/dotmd/vendor/airweave/source_gmail.py
  - backend/src/dotmd/vendor/airweave/gmail_config.py
  - backend/src/dotmd/vendor/airweave/decorators.py
  - backend/src/dotmd/vendor/airweave/shims.py
  - backend/src/dotmd/vendor/airweave/VENDOR_VERSION
  - backend/src/dotmd/vendor/airweave/VENDOR_NOTES.md
  - backend/tests/test_vendor_airweave_import.py
autonomous: true
requirements:
  - AIR-01
  - AIR-02
must_haves:
  goal: >
    Airweave source/entity classes importable inside dotMD without pip-installing
    the full airweave package. DI shim types (logger, http client, auth provider)
    satisfy GmailSource.__init__ structurally. No Temporal, Vespa, or
    organization-layer imports survive in the vendored tree. Token provider uses
    margin-based cache expiry (expires_in - 300) with threading.Lock to prevent
    concurrent refresh races.
  truths:
    - backend/src/dotmd/vendor/airweave/ directory exists with all required files
    - "from dotmd.vendor.airweave.source_gmail import GmailSource" imports cleanly
    - GmailSource(auth=shim_auth, logger=shim_logger, http_client=shim_http) constructs without error
    - No import of airweave.domains, airweave.core, or airweave.schemas survives in vendored tree
    - SparseEmbedding replaced with Any in entities_base.py
    - "@source" decorator in decorators.py is a no-op stub that sets ClassVar attributes only
    - GmailOAuthTokenProvider uses threading.Lock and margin-based expiry (expires_in - 300)
    - VENDOR_VERSION file exists with source Airweave commit SHA or branch reference
---

# Plan 37-01: Vendor Airweave platform slice and DI shims

## Objective

Copy 6 Airweave platform files into `backend/src/dotmd/vendor/airweave/`,
rewrite their cross-module imports to be self-contained, stub out the `@source`
decorator and external DI types, and implement the DI shim classes. The token
provider uses margin-based cache expiry with thread-safety.

## Context

The full `airweave` package has heavy deps (temporalio, redis, celery, sqlalchemy).
We need only the platform source/entity layer. The vendored subtree isolates that
layer and makes it importable without any Airweave runtime installed.

Research finding: `GmailSource.search()` is NOT implemented — `BaseSource` has an
abstract stub but `GmailSource` does not override it. The bridge (Plan 37-02) will
call the Gmail API directly for search, not via `GmailSource.search()`.

## Tasks

### Task 1: Create vendor package skeleton

<read_first>
- backend/src/dotmd/ingestion/telegram_provider.py — package structure reference
- /home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/entities/_base.py
- /home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/entities/gmail.py
- /home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/sources/_base.py
- /home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/sources/gmail.py
- /home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/configs/config.py
- /home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/decorators.py
</read_first>

<action>
Create empty `backend/src/dotmd/vendor/__init__.py` and
`backend/src/dotmd/vendor/airweave/__init__.py`.

Then copy and adapt 6 files into `backend/src/dotmd/vendor/airweave/`:

**entities_base.py** (from `platform/entities/_base.py`):
- Keep: `Breadcrumb`, `AirweaveSystemMetadata`, `BaseEntity`, `DeletionEntity`,
  `EmailEntity`, `FileEntity`, `AccessControl`
- Replace: `from airweave.domains.embedders.types import SparseEmbedding` →
  `SparseEmbedding = object  # vendored stub`
- Remove: any other `airweave.*` imports (substitute with stdlib/pydantic)

**entities_gmail.py** (from `platform/entities/gmail.py`):
- Replace: `from airweave.platform.entities._airweave_field import AirweaveField` →
  `from dotmd.vendor.airweave.entities_base import AirweaveField  # may need stub`
- Replace: `from airweave.platform.entities._base import ...` →
  `from dotmd.vendor.airweave.entities_base import ...`
- Check if `AirweaveField` exists in `_base.py`; if not, create a minimal stub:
  `AirweaveField = Field  # vendored stub using pydantic.Field`

**source_base.py** (from `platform/sources/_base.py`):
- Keep the `BaseSource` class and its public interface
- Replace all `airweave.*` imports with local stubs or stdlib equivalents:
  - `ContextualLogger` → stub class with debug/info/warning/error methods
  - `AirweaveHttpClient` → stub class with get/post methods wrapping httpx
  - `SourceAuthProvider` → stub Protocol with provider_kind + supports_refresh
  - `FileService` → remove (not used by bridge)
  - `SyncCursor` → keep as `dict[str, object]` alias or minimal dataclass
  - `NodeSelectionData` → `Any` alias
  - `AuthenticationMethod`, `OAuthType` → simple string enums (stub)
  - `RateLimitLevel` → simple string enum (stub)

**source_gmail.py** (from `platform/sources/gmail.py`):
- Replace all `airweave.*` imports with `dotmd.vendor.airweave.*` equivalents
- Keep `GmailSource` class body intact
- Remove `@source(...)` decorator call temporarily (apply after decorators.py stub is in place)
- The `search()` method from BaseSource is abstract and NOT overridden in GmailSource —
  document this in a comment: `# NOTE: GmailSource does not implement search() — bridge uses direct API`

**gmail_config.py** (extract from `platform/configs/config.py`):
- Copy only `GmailConfig` class and its `SourceConfig` base
- Remove all other config classes
- Replace `from airweave.platform.configs._base import BaseConfig, RequiredTemplateConfig` →
  `from pydantic import BaseModel as BaseConfig`

**decorators.py** (from `platform/decorators.py`):
- Replace the full `source()` decorator with a no-op stub that sets ClassVar attributes:
  ```
  def source(name, short_name, auth_methods=None, oauth_type=None, **kwargs):
      def decorator(cls):
          cls.is_source = True
          cls.source_name = name
          cls.short_name = short_name
          cls.auth_methods = auth_methods or []
          cls.oauth_type = oauth_type
          for k, v in kwargs.items():
              setattr(cls, k, v)
          return cls
      return decorator
  ```
- Do NOT import from airweave.schemas or airweave.core in the stub

Also create `VENDOR_VERSION` with the source commit reference:
```
Source: https://github.com/airweave-ai/airweave
Branch/commit: main (vendored 2026-05-11)
Files vendored:
  - backend/airweave/platform/entities/_base.py
  - backend/airweave/platform/entities/gmail.py
  - backend/airweave/platform/sources/_base.py
  - backend/airweave/platform/sources/gmail.py
  - backend/airweave/platform/configs/config.py (GmailConfig only)
  - backend/airweave/platform/decorators.py
Modifications: imports rewritten to dotmd.vendor.airweave.*, heavy DI deps shimmed
```

And `VENDOR_NOTES.md` documenting per-file modification delta:
- entities_base.py: SparseEmbedding stub, removed airweave.domains imports
- entities_gmail.py: import path rewrites only
- source_base.py: ContextualLogger/AirweaveHttpClient/SourceAuthProvider replaced with stubs
- source_gmail.py: import rewrites, @source decorator applied after stub available
- gmail_config.py: extracted GmailConfig only, SourceConfig base replaced with pydantic.BaseModel
- decorators.py: replaced with no-op stub preserving ClassVar attribute setting
</action>

<acceptance_criteria>
- `python -c "from dotmd.vendor.airweave.entities_base import BaseEntity, Breadcrumb"` exits 0
- `python -c "from dotmd.vendor.airweave.entities_gmail import GmailThreadEntity, GmailMessageEntity"` exits 0
- `python -c "from dotmd.vendor.airweave.source_gmail import GmailSource"` exits 0
- `python -c "from dotmd.vendor.airweave.gmail_config import GmailConfig"` exits 0
- `grep -r "airweave.domains\|airweave.core\|airweave.schemas" backend/src/dotmd/vendor/` returns no matches
- `python -c "import temporalio"` is NOT required (airweave not installed)
- `test -f backend/src/dotmd/vendor/airweave/VENDOR_VERSION` exits 0
- `test -f backend/src/dotmd/vendor/airweave/VENDOR_NOTES.md` exits 0
</acceptance_criteria>

### Task 2: Create DI shim classes with thread-safe token caching

<read_first>
- backend/src/dotmd/vendor/airweave/source_base.py (just created)
- /home/j2h4u/repos/airweave-ai/airweave/backend/airweave/domains/sources/token_providers/protocol.py
- /home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/http_client/airweave_client.py
</read_first>

<action>
Create `backend/src/dotmd/vendor/airweave/shims.py` with three shim classes:

**GmailLoggerShim**: wraps a stdlib `logging.Logger`. Methods: `debug(msg, *args, **kwargs)`,
`info(...)`, `warning(...)`, `error(...)`. Satisfies `ContextualLogger` structurally.

**GmailHttpClientShim**: wraps `httpx.AsyncClient`. Methods: `get(url, headers=None, params=None)`,
`post(url, headers=None, json=None)` — return `httpx.Response` objects directly.
No rate limiter. Constructor takes `httpx.AsyncClient`.

**GmailOAuthTokenProvider**: provides OAuth tokens for Gmail API.
Fields: `provider_kind = "oauth"` (string), `supports_refresh = True`.

The token cache MUST use margin-based expiry and thread-safe refresh:

```python
import threading
import time

class GmailOAuthTokenProvider:
    provider_kind: str = "oauth"
    supports_refresh: bool = True

    def __init__(self, credentials: dict[str, str]) -> None:
        # credentials = {"client_id": ..., "client_secret": ..., "refresh_token": ...}
        self._credentials = credentials
        self._cached_token: str | None = None
        self._token_expires_at: float = 0.0  # epoch seconds
        self._refresh_lock = threading.Lock()  # prevents concurrent refresh races

    def get_token(self) -> str:
        now = time.time()
        # Fast path: token still valid (check before acquiring lock)
        if self._cached_token and now < self._token_expires_at:
            return self._cached_token

        # Slow path: refresh needed — serialize under lock
        with self._refresh_lock:
            # Re-check after acquiring lock (another thread may have refreshed)
            if self._cached_token and time.time() < self._token_expires_at:
                return self._cached_token

            import httpx
            response = httpx.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": self._credentials["client_id"],
                    "client_secret": self._credentials["client_secret"],
                    "refresh_token": self._credentials["refresh_token"],
                    "grant_type": "refresh_token",
                },
                timeout=10.0,
            )
            response.raise_for_status()
            token_data = response.json()
            self._cached_token = token_data["access_token"]
            # Use actual expires_in from response with 300s safety margin
            expires_in = token_data.get("expires_in", 3600)
            self._token_expires_at = time.time() + max(expires_in - 300, 0)
            return self._cached_token
```

Key behaviors:
- Lock is held only during the actual refresh call, not during normal reads
- Double-check inside lock prevents thundering herd (multiple threads refreshing simultaneously)
- `expires_in - 300` margin means refresh triggers 5 min before actual expiry (Google tokens
  typically have 3600s lifetime, so cache lasts ~55 min, not hard-coded 5 min)
- Token response may include a new refresh token — if `refresh_token` is present in response,
  update `self._credentials["refresh_token"]` to support token rotation

Do NOT make this class inherit from any Airweave class.
</action>

<acceptance_criteria>
- `from dotmd.vendor.airweave.shims import GmailLoggerShim, GmailHttpClientShim, GmailOAuthTokenProvider` imports cleanly
- `GmailLoggerShim(logger=logging.getLogger("test")).debug("hi")` runs without error
- `GmailOAuthTokenProvider(credentials={"client_id": "x", "client_secret": "y", "refresh_token": "z"})` constructs without error (no network call at construction time)
- `GmailOAuthTokenProvider` has `_refresh_lock: threading.Lock` attribute
- shims.py contains no imports from `airweave.*`
- Token cache uses `expires_in - 300` margin, not hard-coded 300 seconds
</acceptance_criteria>

### Task 3: Verify GmailSource construction with shims

<read_first>
- backend/src/dotmd/vendor/airweave/source_gmail.py (just created)
- backend/src/dotmd/vendor/airweave/shims.py (just created)
</read_first>

<action>
Write a minimal smoke test in `backend/tests/test_vendor_airweave_import.py`:

```python
"""Smoke tests: vendored Airweave slice imports cleanly and shims satisfy GmailSource constructor."""

import logging
import threading
import pytest
import httpx

def test_entities_import():
    from dotmd.vendor.airweave.entities_base import BaseEntity, Breadcrumb
    from dotmd.vendor.airweave.entities_gmail import GmailThreadEntity, GmailMessageEntity

def test_gmail_source_import():
    from dotmd.vendor.airweave.source_gmail import GmailSource

def test_gmail_config_import():
    from dotmd.vendor.airweave.gmail_config import GmailConfig
    cfg = GmailConfig()
    assert cfg.included_labels == ["inbox", "sent"]

def test_shim_construction():
    from dotmd.vendor.airweave.shims import GmailLoggerShim, GmailHttpClientShim, GmailOAuthTokenProvider
    log_shim = GmailLoggerShim(logging.getLogger("test"))
    log_shim.debug("test message")
    creds = {"client_id": "cid", "client_secret": "csec", "refresh_token": "rtoken"}
    auth_shim = GmailOAuthTokenProvider(credentials=creds)
    assert auth_shim.supports_refresh is True
    assert auth_shim.provider_kind == "oauth"
    # Verify thread-safe refresh lock exists
    assert isinstance(auth_shim._refresh_lock, threading.Lock)
    # Verify no network call at construction time
    assert auth_shim._cached_token is None

def test_token_provider_uses_expires_in_margin():
    """Token cache expiry must be margin-based (expires_in - 300), not hard-coded."""
    import time
    from unittest.mock import patch, MagicMock
    from dotmd.vendor.airweave.shims import GmailOAuthTokenProvider

    creds = {"client_id": "cid", "client_secret": "csec", "refresh_token": "rtoken"}
    provider = GmailOAuthTokenProvider(credentials=creds)

    mock_response = MagicMock()
    mock_response.json.return_value = {"access_token": "fake-token", "expires_in": 3600}
    mock_response.raise_for_status.return_value = None

    with patch("httpx.post", return_value=mock_response):
        token = provider.get_token()
        assert token == "fake-token"
        # Cache should last ~3300 seconds (3600 - 300), not 5 minutes (300)
        expected_min_expiry = time.time() + 3000  # allow some test slack
        assert provider._token_expires_at > expected_min_expiry

def test_token_provider_concurrent_refresh_serialized():
    """Concurrent get_token() calls must not issue multiple refresh requests."""
    import time
    from unittest.mock import patch, MagicMock
    from dotmd.vendor.airweave.shims import GmailOAuthTokenProvider

    creds = {"client_id": "cid", "client_secret": "csec", "refresh_token": "rtoken"}
    provider = GmailOAuthTokenProvider(credentials=creds)

    call_count = 0
    original_post = None

    def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        time.sleep(0.05)  # simulate latency
        m = MagicMock()
        m.json.return_value = {"access_token": f"token-{call_count}", "expires_in": 3600}
        m.raise_for_status.return_value = None
        return m

    tokens = []
    errors = []

    def get_token():
        try:
            tokens.append(provider.get_token())
        except Exception as e:
            errors.append(e)

    with patch("httpx.post", side_effect=mock_post):
        threads = [threading.Thread(target=get_token) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert not errors
    assert len(tokens) == 5
    # Only ONE refresh call should have been made (double-check inside lock)
    assert call_count == 1, f"Expected 1 refresh call, got {call_count}"

def test_no_airweave_package_required():
    import sys
    # vendored imports must not pull in the full airweave package
    for mod_name in list(sys.modules.keys()):
        assert not (mod_name.startswith("airweave.domains") or
                    mod_name.startswith("airweave.core") or
                    mod_name.startswith("temporalio")), \
            f"Unexpected heavy airweave module loaded: {mod_name}"

def test_vendor_version_file_exists():
    import os
    from pathlib import Path
    vendor_version = Path("src/dotmd/vendor/airweave/VENDOR_VERSION")
    assert vendor_version.exists(), "VENDOR_VERSION must exist for source traceability"
    content = vendor_version.read_text()
    assert "airweave" in content.lower(), "VENDOR_VERSION must reference airweave source"
```
</action>

<acceptance_criteria>
- `cd backend && python -m pytest tests/test_vendor_airweave_import.py -v` exits 0
- All 6 test functions pass (including concurrent refresh serialization test)
- test_token_provider_uses_expires_in_margin confirms margin-based expiry
- test_token_provider_concurrent_refresh_serialized confirms only 1 refresh under concurrent load
- No import of temporalio, celery, redis, sqlalchemy triggered by the import chain
</acceptance_criteria>

## Verification

```bash
cd /home/j2h4u/repos/j2h4u/dotmd/backend
python -m pytest tests/test_vendor_airweave_import.py -v
grep -r "airweave.domains\|airweave.core\|airweave.schemas\|temporalio" src/dotmd/vendor/
test -f src/dotmd/vendor/airweave/VENDOR_VERSION && echo "VENDOR_VERSION OK"
```
