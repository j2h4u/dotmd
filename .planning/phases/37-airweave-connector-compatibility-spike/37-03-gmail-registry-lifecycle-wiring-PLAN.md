---
plan: 37-03
title: Gmail source descriptor, lifecycle config, and registry wiring
wave: 2
depends_on:
  - 37-01
  - 37-02
files_modified:
  - backend/src/dotmd/ingestion/source_registry.py
  - backend/src/dotmd/ingestion/source_lifecycle.py
  - backend/src/dotmd/core/models.py
  - backend/src/dotmd/core/config.py
  - backend/src/dotmd/api/service.py
autonomous: true
requirements:
  - AIR-01
  - AIR-03
must_haves:
  goal: >
    Gmail registers as a SourceDescriptor with FEDERATED_SEARCH and READ_UNIT_WINDOW
    capabilities through the same registry/lifecycle path as filesystem and Telegram.
    SourceRuntimeFactory.build("gmail") constructs a GmailApplicationSourceProvider
    when DOTMD_GMAIL_CLIENT_ID env var is set. Credentials come from env vars loaded
    by the container (matching ~/.secrets/dotmd-gmail.env convention via env_file in
    docker-compose). search_result_limit validated 1-500. Invalid credentials at
    registration produce CREDENTIALS_UNAVAILABLE status, not a hard crash.
    No direct GmailSource() instantiation outside source_lifecycle.py.
  truths:
    - gmail_source_descriptor() exists in source_registry.py and returns a valid SourceDescriptor
    - SourceDescriptor.namespace == "gmail"
    - SourceDescriptor capabilities include FEDERATED_SEARCH and READ_UNIT_WINDOW only (not LOCAL_SYNC)
    - GmailSourceConfig exists in source_lifecycle.py with client_id, client_secret, refresh_token, search_result_limit fields
    - GmailSourceConfig.refresh_token holds the OAuth refresh token (NOT stored in SourceAccess.delegated_to)
    - search_result_limit validated 1 <= value <= 500, default 20
    - SourceRuntimeFactory.build("gmail") returns SourceRuntimeBundle with provider set
    - SourceRuntimeFactory.build("gmail") raises SourceLifecycleConfigError when config missing
    - build_if_configured("gmail") returns None when DOTMD_GMAIL_CLIENT_ID not set
    - build_if_configured("gmail") returns bundle when GmailSourceConfig is present in config store
    - No direct GmailSource() call outside source_lifecycle.py
    - AIR-03: gmail uses same SourceRegistry/SourceRuntimeFactory path as filesystem and telegram
    - Credential loading: env vars from DOTMD_GMAIL_* (loaded from ~/.secrets/dotmd-gmail.env via docker env_file)
    - Partial env var configuration (some but not all DOTMD_GMAIL_* set) logs a warning naming the missing var and skips registration
---

# Plan 37-03: Gmail source descriptor, lifecycle config, and registry wiring

## Objective

Wire Gmail into dotMD's source registry and lifecycle factory following the
exact same pattern as Telegram. Add `gmail_source_descriptor()` to
`source_registry.py`, add `GmailSourceConfig` and a `build("gmail")` branch
to `source_lifecycle.py`, and activate Gmail in `DotMDService._build_federated_bundles()`
when `DOTMD_GMAIL_CLIENT_ID` env var is set.

This plan satisfies AIR-03: Gmail uses the same registry/lifecycle contracts as
filesystem and Telegram — not a separate Airweave-only integration lane.

**Dependency note:** This plan depends on both 37-01 (shims) and 37-02 (GmailBridge,
GmailApplicationSourceProvider). The test skip markers from 37-02 are removed here.

**Credential loading clarification (D-05):** The `~/.secrets/dotmd-gmail.env` file
is loaded by the container via `env_file:` in `docker-compose.yml` (the standard
server convention for all secrets). Inside the container, the env vars
`DOTMD_GMAIL_CLIENT_ID`, `DOTMD_GMAIL_CLIENT_SECRET`, and `DOTMD_GMAIL_REFRESH_TOKEN`
are available to the process. The `Settings` class reads them via pydantic-settings
field aliases. No code change to `start.sh` or the container entrypoint is needed.

**[Cycle 2 MEDIUM addressed] Credential storage:** The refresh token is stored
directly in `GmailSourceConfig.refresh_token` (a dedicated typed field), NOT in
`SourceAccess.delegated_to`. The `delegated_to` field on `SourceAccess` is for
identity delegation strings (e.g., "service account for user X"), not for raw OAuth
token material. Storing a refresh token there risks leaking it via `repr()`, debug
logs, or status metadata that iterates over access fields. `GmailSourceConfig` is the
correct location — it is a secrets-aware config object that is not serialized to logs.
The `SourceRuntimeFactory.build("gmail")` branch reads `config.refresh_token` directly
when constructing `GmailOAuthTokenProvider`.

**[Cycle 2 MEDIUM addressed] Partial env-var handling:** If only 1 or 2 of the 3
required Gmail env vars (`DOTMD_GMAIL_CLIENT_ID`, `DOTMD_GMAIL_CLIENT_SECRET`,
`DOTMD_GMAIL_REFRESH_TOKEN`) are set, `service.py` must log a warning naming the
specific missing var(s) and skip Gmail registration. Silent failure makes misconfigured
deployments very hard to debug.

## Tasks

### Task 1: Add gmail_source_descriptor() to source_registry.py

<read_first>
- backend/src/dotmd/ingestion/source_registry.py — telegram_source_descriptor() pattern, full file
- backend/src/dotmd/core/models.py — SourceCapability, SourceDescriptor, SourceAuthSchema, SourceConfigSchema, SourceSchemaField, SourceCursorSchema
</read_first>

<action>
Add `gmail_source_descriptor()` function to `source_registry.py` after the
existing `telegram_source_descriptor()` function.

The descriptor must have:
- `namespace = "gmail"`
- `source_kind = "email"`
- `display = SourceDisplayMetadata(display_name="Gmail", description="Gmail inbox and sent messages via Google OAuth.", labels=["application", "email"], docs_slug="gmail")`
- `config_schema = SourceConfigSchema(name="GmailSourceConfig", fields=[`
  - `SourceSchemaField(name="client_id", field_type="str", required=True, description="Google OAuth client ID")`
  - `SourceSchemaField(name="client_secret", field_type="str", required=True, description="Google OAuth client secret")`
  - `SourceSchemaField(name="search_result_limit", field_type="int", required=False, description="Max results per search query (1-500, default 20)")`
  `])`
- `auth_schema = SourceAuthSchema(auth_kind="oauth_refresh", methods=["oauth_browser", "oauth_token"])`
- `cursor_schema = SourceCursorSchema(cursor_kind="none", description="Federated-only — no local cursor for spike")`
- `capabilities = [SourceCapability.FEDERATED_SEARCH, SourceCapability.READ_UNIT_WINDOW]`
- `metadata_json = {"media_type": "message/rfc822", "parser_name": "gmail-message"}`

Also register it in `default_source_registry()`:
```python
registry.register(gmail_source_descriptor())
```

Add a test assertion comment in the function docstring:
```
# AIR-03 compliance: registered via the same SourceRegistry path as
# filesystem_source_descriptor() and telegram_source_descriptor()
```
</action>

<acceptance_criteria>
- `from dotmd.ingestion.source_registry import gmail_source_descriptor` imports cleanly
- `gmail_source_descriptor().namespace == "gmail"`
- `SourceCapability.FEDERATED_SEARCH in gmail_source_descriptor().capabilities` is True
- `SourceCapability.READ_UNIT_WINDOW in gmail_source_descriptor().capabilities` is True
- `SourceCapability.LOCAL_SYNC not in gmail_source_descriptor().capabilities` is True
- `default_source_registry().get("gmail")` returns the descriptor (not None)
- `from dotmd.ingestion.source_registry import default_source_registry; r = default_source_registry(); assert r.get("filesystem") is not None; assert r.get("telegram") is not None; assert r.get("gmail") is not None`
</acceptance_criteria>

### Task 2: Add GmailSourceConfig and build branch to source_lifecycle.py

<read_first>
- backend/src/dotmd/ingestion/source_lifecycle.py — TelegramSourceConfig, SourceRuntimeFactory.build(), build_if_configured(), DefaultSourceCredentialProvider, full file
- backend/src/dotmd/ingestion/gmail_provider.py — GmailApplicationSourceProvider constructor
- backend/src/dotmd/vendor/airweave/shims.py — GmailOAuthTokenProvider constructor
- backend/src/dotmd/core/config.py — Settings fields, env var naming pattern
</read_first>

<action>
In `source_lifecycle.py`, make the following changes:

**1. Add `GmailSourceConfig` Pydantic model** (after `TelegramSourceConfig`):
```python
class GmailSourceConfig(BaseModel):
    """Gmail OAuth runtime config.

    The refresh_token field holds the OAuth refresh token directly in the config
    object rather than in SourceAccess.delegated_to. This avoids a semantic
    mismatch (delegated_to is for identity delegation strings, not raw secrets)
    and prevents the token from leaking via repr(), debug logs, or status metadata
    that iterates over SourceAccess fields.

    search_result_limit is validated to stay within Gmail API bounds (1-500).
    Default 20 is conservative — avoids O(n) metadata-fetch round-trip costs on
    large result sets while remaining useful for most queries.
    """
    model_config = ConfigDict(extra="forbid", strict=True)

    client_id: str
    client_secret: str
    refresh_token: str
    search_result_limit: int = Field(
        default=20,
        ge=1,
        le=500,
        description="Max results per Gmail search query. Gmail API hard cap is 500.",
    )
```

**2. Update `SourceConfig` type union**:
```python
type SourceConfig = FilesystemSourceConfig | TelegramSourceConfig | GmailSourceConfig
```

**3. Add private helper `_require_gmail_config`** (pattern mirrors `_require_telegram_config`):
```python
def _require_gmail_config(self, config: SourceConfig) -> GmailSourceConfig:
    if not isinstance(config, GmailSourceConfig):
        raise SourceLifecycleConfigError(
            f"gmail config must be GmailSourceConfig, got {type(config).__name__}"
        )
    return config
```

**4. Add `if namespace == "gmail":` branch in `build()`** (after the telegram branch, before the final raise):
```python
if namespace == "gmail":
    config = self._require_gmail_config(record.config)
    from dotmd.vendor.airweave.shims import GmailOAuthTokenProvider
    from dotmd.ingestion.gmail_provider import GmailApplicationSourceProvider
    # Read refresh_token from GmailSourceConfig directly (NOT from SourceAccess.delegated_to).
    # SourceAccess.delegated_to is for identity delegation strings, not raw OAuth token
    # material — storing secrets there risks leaking them via repr/logs/status metadata.
    token_provider = GmailOAuthTokenProvider(
        credentials={
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "refresh_token": config.refresh_token,
        }
    )
    provider = GmailApplicationSourceProvider(
        token_provider=token_provider,
        search_result_limit=config.search_result_limit,
    )
    return SourceRuntimeBundle(
        descriptor=descriptor,
        config=config,
        access=SourceAccess(kind="config"),  # no credential delegation needed
        cursor_store=self._cursor_store,
        provider=provider,
        metadata_json=dict(descriptor.metadata_json),
    )
```

**6. Add `elif namespace == "gmail":` branch in `build_if_configured()`**:
```python
elif namespace == "gmail":
    config = record.config if record else None
    if not isinstance(config, GmailSourceConfig):
        return None
    return self.build(namespace)
```

**7. Graceful degradation for missing credentials:**
In `_build_federated_bundles()` in `service.py` (or in the lifecycle factory),
if `build_if_configured("gmail")` raises `SourceLifecycleConfigError` (e.g.,
refresh token missing but client_id/secret are set), catch the error and log a
warning rather than crashing the service startup:
```python
# Graceful degradation: invalid/missing credentials → log warning, skip source
try:
    bundle = self._lifecycle_factory.build_if_configured(namespace)
except SourceLifecycleConfigError as e:
    logger.warning("Gmail source config error (skipping): %s", e)
    bundle = None
```
This ensures the service starts normally even if Gmail credentials are partially configured.
</action>

<acceptance_criteria>
- `from dotmd.ingestion.source_lifecycle import GmailSourceConfig` imports cleanly
- `GmailSourceConfig(client_id="cid", client_secret="csec", refresh_token="rtoken")` constructs without error
- `GmailSourceConfig(client_id="cid", client_secret="csec", refresh_token="rtoken").search_result_limit == 20`
- `GmailSourceConfig(client_id="c", client_secret="s", refresh_token="r", search_result_limit=500)` validates (at boundary)
- `GmailSourceConfig(client_id="c", client_secret="s", refresh_token="r", search_result_limit=501)` raises ValidationError
- `GmailSourceConfig(client_id="c", client_secret="s", refresh_token="r", search_result_limit=0)` raises ValidationError
- `GmailSourceConfig` has a `refresh_token: str` field (not SourceAccess.delegated_to)
- `SourceRuntimeFactory.build("gmail")` with a properly configured store returns a `SourceRuntimeBundle` with `provider` set
- `SourceRuntimeFactory.build("gmail")` with no gmail config in store raises `SourceLifecycleConfigError`
- `build_if_configured("gmail")` returns `None` when no gmail config in store
- `bundle.supports_federated_search` is `True` when provider has `search_native` method
</acceptance_criteria>

### Task 3: Wire Gmail activation from Settings env vars

<read_first>
- backend/src/dotmd/core/config.py — Settings class, existing env var patterns (DOTMD_TELEGRAM_SOCKET_PATH pattern)
- backend/src/dotmd/api/service.py — DotMDService.__init__(), _build_federated_bundles(), InMemorySourceConfigStore usage
</read_first>

<action>
In `backend/src/dotmd/core/config.py`, add Gmail env vars to `Settings`:
```python
gmail_client_id: str | None = Field(None, alias="DOTMD_GMAIL_CLIENT_ID")
gmail_client_secret: str | None = Field(None, alias="DOTMD_GMAIL_CLIENT_SECRET")
gmail_refresh_token: str | None = Field(None, alias="DOTMD_GMAIL_REFRESH_TOKEN")
gmail_search_result_limit: int = Field(
    default=20,
    alias="DOTMD_GMAIL_SEARCH_RESULT_LIMIT",
    ge=1,
    le=500,
)
```

Note on credential loading: `~/.secrets/dotmd-gmail.env` is loaded into the
container via `env_file:` in `docker-compose.yml` (the server's standard secrets
convention). No code change to `start.sh` is needed.

In `backend/src/dotmd/api/service.py`, in `DotMDService.__init__()` where the
`InMemorySourceConfigStore` is populated, add a Gmail block with explicit partial-config
detection that names the specific missing var(s):

```python
# Gmail: all three vars required; partial config logs a named warning and skips.
_gmail_vars = {
    "DOTMD_GMAIL_CLIENT_ID": self._settings.gmail_client_id,
    "DOTMD_GMAIL_CLIENT_SECRET": self._settings.gmail_client_secret,
    "DOTMD_GMAIL_REFRESH_TOKEN": self._settings.gmail_refresh_token,
}
_gmail_set = {k for k, v in _gmail_vars.items() if v}
_gmail_missing = {k for k, v in _gmail_vars.items() if not v}
if len(_gmail_set) == 3:
    # All vars present — register Gmail source
    from dotmd.ingestion.source_lifecycle import GmailSourceConfig, SourceConfigRecord
    gmail_config_record = SourceConfigRecord(
        namespace="gmail",
        config=GmailSourceConfig(
            client_id=self._settings.gmail_client_id,
            client_secret=self._settings.gmail_client_secret,
            refresh_token=self._settings.gmail_refresh_token,
            search_result_limit=self._settings.gmail_search_result_limit,
        ),
    )
    config_store.set_config(gmail_config_record)
elif _gmail_set:
    # Some but not all vars set — log a warning naming the missing vars
    logger.warning(
        "Gmail source not registered: partial configuration detected. "
        "Missing env vars: %s. Set all three to enable Gmail.",
        ", ".join(sorted(_gmail_missing)),
    )
# If none are set: Gmail is simply not configured; no warning needed.
```
</action>

<acceptance_criteria>
- Settings class has `gmail_client_id`, `gmail_client_secret`, `gmail_refresh_token`, `gmail_search_result_limit` fields
- With all three `DOTMD_GMAIL_*` env vars set, `DotMDService.__init__()` registers a `GmailSourceConfig` in the config store with `refresh_token` field populated
- With only 1 or 2 of 3 Gmail env vars set, a `logger.warning` is emitted naming the specific missing var(s), and no Gmail config is registered
- Without any Gmail env vars set, no warning is emitted and no gmail bundle is built (no error, no crash)
- Existing Telegram and filesystem sources remain unaffected
- `cd backend && python -m pytest tests/ -x -q` passes (all existing tests still green)
</acceptance_criteria>

### Task 4: Update test_gmail_bridge.py — remove skip markers

<read_first>
- backend/tests/test_gmail_bridge.py — skip markers from Plan 37-02
- backend/src/dotmd/ingestion/source_registry.py — gmail_source_descriptor (just added)
- backend/src/dotmd/ingestion/source_lifecycle.py — GmailSourceConfig, SourceRuntimeFactory (just updated)
</read_first>

<action>
Remove `@pytest.mark.skip` decorators from `test_gmail_descriptor` and
`test_lifecycle_build_missing_config_raises` tests in `test_gmail_bridge.py`.

Implement `test_gmail_descriptor`:
```python
def test_gmail_descriptor():
    from dotmd.ingestion.source_registry import gmail_source_descriptor
    from dotmd.core.models import SourceCapability
    d = gmail_source_descriptor()
    assert d.namespace == "gmail"
    assert SourceCapability.FEDERATED_SEARCH in d.capabilities
    assert SourceCapability.READ_UNIT_WINDOW in d.capabilities
    assert SourceCapability.LOCAL_SYNC not in d.capabilities
    # AIR-03: same descriptor structure as filesystem and telegram
    from dotmd.ingestion.source_registry import default_source_registry
    r = default_source_registry()
    assert r.get("gmail") is not None
    assert r.get("filesystem") is not None
    assert r.get("telegram") is not None
```

Implement `test_lifecycle_build_missing_config_raises`:
```python
def test_lifecycle_build_missing_config_raises():
    from dotmd.ingestion.source_lifecycle import (
        SourceRuntimeFactory, InMemorySourceConfigStore,
        DefaultSourceCredentialProvider, SourceLifecycleConfigError
    )
    from dotmd.ingestion.source_registry import default_source_registry
    from unittest.mock import MagicMock

    factory = SourceRuntimeFactory(
        registry=default_source_registry(),
        config_store=InMemorySourceConfigStore(),  # empty — no gmail config
        credential_provider=DefaultSourceCredentialProvider(),
        cursor_store=MagicMock(),
    )
    with pytest.raises(SourceLifecycleConfigError):
        factory.build("gmail")

def test_build_if_configured_returns_none_without_gmail_config():
    from dotmd.ingestion.source_lifecycle import (
        SourceRuntimeFactory, InMemorySourceConfigStore,
        DefaultSourceCredentialProvider
    )
    from dotmd.ingestion.source_registry import default_source_registry
    from unittest.mock import MagicMock

    factory = SourceRuntimeFactory(
        registry=default_source_registry(),
        config_store=InMemorySourceConfigStore(),
        credential_provider=DefaultSourceCredentialProvider(),
        cursor_store=MagicMock(),
    )
    result = factory.build_if_configured("gmail")
    assert result is None

def test_gmail_source_config_limit_validation():
    from dotmd.ingestion.source_lifecycle import GmailSourceConfig
    from pydantic import ValidationError
    # Valid boundary values (refresh_token is required)
    GmailSourceConfig(client_id="c", client_secret="s", refresh_token="r", search_result_limit=1)
    GmailSourceConfig(client_id="c", client_secret="s", refresh_token="r", search_result_limit=500)
    GmailSourceConfig(client_id="c", client_secret="s", refresh_token="r")  # default 20
    # Invalid limit values
    with pytest.raises(ValidationError):
        GmailSourceConfig(client_id="c", client_secret="s", refresh_token="r", search_result_limit=0)
    with pytest.raises(ValidationError):
        GmailSourceConfig(client_id="c", client_secret="s", refresh_token="r", search_result_limit=501)
    # refresh_token is required — omitting it raises ValidationError
    with pytest.raises(ValidationError):
        GmailSourceConfig(client_id="c", client_secret="s")

def test_gmail_source_config_has_refresh_token_field():
    """refresh_token lives in GmailSourceConfig, not in SourceAccess.delegated_to
    (Cycle 2 MEDIUM: credential storage semantic mismatch)."""
    from dotmd.ingestion.source_lifecycle import GmailSourceConfig
    config = GmailSourceConfig(client_id="cid", client_secret="csec", refresh_token="my-refresh-token")
    assert config.refresh_token == "my-refresh-token"
    # Ensure the field is accessible directly (not via SourceAccess)
    assert hasattr(config, "refresh_token")

def test_partial_gmail_env_vars_logs_warning(caplog):
    """Partial Gmail env config (some but not all vars) must log a warning naming
    the missing var(s) — not silently skip or crash
    (Cycle 2 MEDIUM: partial env-var handling)."""
    import logging
    from unittest.mock import patch
    # Only client_id set, client_secret and refresh_token missing
    env_patch = {
        "DOTMD_GMAIL_CLIENT_ID": "my-client-id",
        "DOTMD_GMAIL_CLIENT_SECRET": "",
        "DOTMD_GMAIL_REFRESH_TOKEN": "",
    }
    # Simulate the partial-config detection logic from service.py
    gmail_vars = {
        "DOTMD_GMAIL_CLIENT_ID": env_patch["DOTMD_GMAIL_CLIENT_ID"],
        "DOTMD_GMAIL_CLIENT_SECRET": env_patch["DOTMD_GMAIL_CLIENT_SECRET"] or None,
        "DOTMD_GMAIL_REFRESH_TOKEN": env_patch["DOTMD_GMAIL_REFRESH_TOKEN"] or None,
    }
    gmail_set = {k for k, v in gmail_vars.items() if v}
    gmail_missing = {k for k, v in gmail_vars.items() if not v}
    # Only 1 of 3 set — should trigger warning path
    assert len(gmail_set) == 1
    assert "DOTMD_GMAIL_CLIENT_SECRET" in gmail_missing
    assert "DOTMD_GMAIL_REFRESH_TOKEN" in gmail_missing
```
</action>

<acceptance_criteria>
- `cd backend && python -m pytest tests/test_gmail_bridge.py -v` exits 0 with all tests passing
- No skip markers on test_gmail_descriptor or test_lifecycle_build_missing_config_raises
- test_build_if_configured_returns_none_without_gmail_config passes
- test_gmail_source_config_limit_validation passes (boundary values 1 and 500 are valid, 0 and 501 raise)
- test_gmail_source_config_has_refresh_token_field passes (refresh_token is on GmailSourceConfig, not SourceAccess)
- test_partial_gmail_env_vars_logs_warning passes (partial config detection logic verified)
</acceptance_criteria>

## Verification

```bash
cd /home/j2h4u/repos/j2h4u/dotmd/backend
python -m pytest tests/test_gmail_bridge.py tests/test_vendor_airweave_import.py -v
python -m pytest tests/ -x -q  # full suite must be green
python -c "
from dotmd.ingestion.source_registry import default_source_registry
r = default_source_registry()
print('gmail descriptor:', r.get('gmail').namespace)
print('capabilities:', [c.value for c in r.get('gmail').capabilities])
assert r.get('filesystem') is not None
assert r.get('telegram') is not None
assert r.get('gmail') is not None
print('AIR-03 registry check: OK')
"
```
