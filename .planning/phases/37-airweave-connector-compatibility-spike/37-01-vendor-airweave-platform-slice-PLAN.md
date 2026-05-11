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
autonomous: true
requirements:
  - AIR-01
  - AIR-02
must_haves:
  goal: >
    Airweave source/entity classes importable inside dotMD without pip-installing
    the full airweave package. DI shim types (logger, http client, auth provider)
    satisfy GmailSource.__init__ structurally. No Temporal, Vespa, or
    organization-layer imports survive in the vendored tree.
  truths:
    - backend/src/dotmd/vendor/airweave/ directory exists with 8 files
    - "from dotmd.vendor.airweave.source_gmail import GmailSource" imports cleanly
    - GmailSource(auth=shim_auth, logger=shim_logger, http_client=shim_http) constructs without error
    - No import of airweave.domains, airweave.core, or airweave.schemas survives in vendored tree
    - SparseEmbedding replaced with Any in entities_base.py
    - "@source" decorator in decorators.py is a no-op stub that sets ClassVar attributes only
---

# Plan 37-01: Vendor Airweave platform slice and DI shims

## Objective

Copy 6 Airweave platform files into `backend/src/dotmd/vendor/airweave/`,
rewrite their cross-module imports to be self-contained, stub out the `@source`
decorator and external DI types, and verify the vendored slice imports cleanly
inside the dotMD package.

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
</action>

<acceptance_criteria>
- `python -c "from dotmd.vendor.airweave.entities_base import BaseEntity, Breadcrumb"` exits 0
- `python -c "from dotmd.vendor.airweave.entities_gmail import GmailThreadEntity, GmailMessageEntity"` exits 0
- `python -c "from dotmd.vendor.airweave.source_gmail import GmailSource"` exits 0
- `python -c "from dotmd.vendor.airweave.gmail_config import GmailConfig"` exits 0
- `grep -r "airweave.domains\|airweave.core\|airweave.schemas" backend/src/dotmd/vendor/` returns no matches
- `python -c "import temporalio"` is NOT required (airweave not installed)
</acceptance_criteria>

### Task 2: Create DI shim classes

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
Method `get_token() -> str`: reads refresh_token from an injected credential dict
(`{"client_id": ..., "client_secret": ..., "refresh_token": ...}`),
calls `https://oauth2.googleapis.com/token` with `grant_type=refresh_token`,
returns the `access_token` from the response. Use `httpx` synchronously (this
is called from sync contexts in the bridge). Cache the token with 5-minute
expiry to avoid a token request per search call.

Do NOT make this class inherit from any Airweave class.
</action>

<acceptance_criteria>
- `from dotmd.vendor.airweave.shims import GmailLoggerShim, GmailHttpClientShim, GmailOAuthTokenProvider` imports cleanly
- `GmailLoggerShim(logger=logging.getLogger("test")).debug("hi")` runs without error
- `GmailOAuthTokenProvider(credentials={"client_id": "x", "client_secret": "y", "refresh_token": "z"})` constructs without error (no network call at construction time)
- shims.py contains no imports from `airweave.*`
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

def test_no_airweave_package_required():
    import sys
    # vendored imports must not pull in the full airweave package
    for mod_name in list(sys.modules.keys()):
        assert not (mod_name.startswith("airweave.domains") or
                    mod_name.startswith("airweave.core") or
                    mod_name.startswith("temporalio")), \
            f"Unexpected heavy airweave module loaded: {mod_name}"
```
</action>

<acceptance_criteria>
- `cd backend && python -m pytest tests/test_vendor_airweave_import.py -v` exits 0
- All 4 test functions pass
- No import of temporalio, celery, redis, sqlalchemy triggered by the import chain
</acceptance_criteria>

## Verification

```bash
cd /home/j2h4u/repos/j2h4u/dotmd/backend
python -m pytest tests/test_vendor_airweave_import.py -v
grep -r "airweave.domains\|airweave.core\|airweave.schemas\|temporalio" src/dotmd/vendor/
```
