---
plan: 37-03
title: Gmail source descriptor, lifecycle config, and registry wiring
wave: 2
depends_on:
  - 37-01
files_modified:
  - backend/src/dotmd/ingestion/source_registry.py
  - backend/src/dotmd/ingestion/source_lifecycle.py
  - backend/src/dotmd/core/models.py
autonomous: true
requirements:
  - AIR-01
  - AIR-03
must_haves:
  goal: >
    Gmail registers as a SourceDescriptor with FEDERATED_SEARCH and READ_UNIT_WINDOW
    capabilities through the same registry/lifecycle path as filesystem and Telegram.
    SourceRuntimeFactory.build("gmail") constructs a GmailApplicationSourceProvider
    when DOTMD_GMAIL_CLIENT_ID env var is set. No direct GmailSource() instantiation
    outside source_lifecycle.py.
  truths:
    - gmail_source_descriptor() exists in source_registry.py and returns a valid SourceDescriptor
    - SourceDescriptor.namespace == "gmail"
    - SourceDescriptor capabilities include FEDERATED_SEARCH and READ_UNIT_WINDOW
    - GmailSourceConfig exists in source_lifecycle.py with client_id, client_secret, search_result_limit fields
    - SourceRuntimeFactory.build("gmail") returns SourceRuntimeBundle with provider set
    - SourceRuntimeFactory.build("gmail") raises SourceLifecycleConfigError when config missing
    - build_if_configured("gmail") returns None when DOTMD_GMAIL_CLIENT_ID not set
    - build_if_configured("gmail") returns bundle when GmailSourceConfig is present in config store
    - No direct GmailSource() call outside source_lifecycle.py
    - AIR-03: gmail uses same SourceRegistry/SourceRuntimeFactory path as filesystem and telegram
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
  - `SourceSchemaField(name="search_result_limit", field_type="int", required=False, description="Max results per search query (default 10)")`
  `])`
- `auth_schema = SourceAuthSchema(auth_kind="oauth_refresh", methods=["oauth_browser", "oauth_token"])`
- `cursor_schema = SourceCursorSchema(cursor_kind="none", description="Federated-only — no local cursor for spike")`
- `capabilities = [SourceCapability.FEDERATED_SEARCH, SourceCapability.READ_UNIT_WINDOW]`
- `metadata_json = {"media_type": "message/rfc822", "parser_name": "gmail-message"}`

Also register it in `default_source_registry()`:
```python
registry.register(gmail_source_descriptor())
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
- backend/src/dotmd/ingestion/source_lifecycle.py — TelegramSourceConfig, SourceRuntimeFactory.build(), build_if_configured(), full file
- backend/src/dotmd/ingestion/gmail_provider.py — GmailApplicationSourceProvider constructor
- backend/src/dotmd/vendor/airweave/shims.py — GmailOAuthTokenProvider constructor
- backend/src/dotmd/core/config.py — Settings fields, env var naming pattern
</read_first>

<action>
In `source_lifecycle.py`, make the following changes:

**1. Add `GmailSourceConfig` Pydantic model** (after `TelegramSourceConfig`):
```python
class GmailSourceConfig(BaseModel):
    """Gmail OAuth runtime config."""
    model_config = ConfigDict(extra="forbid", strict=True)
    
    client_id: str
    client_secret: str
    search_result_limit: int = 10
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
    access = self._credential_provider.get_access(descriptor, credential_ref)
    from dotmd.vendor.airweave.shims import GmailOAuthTokenProvider
    from dotmd.ingestion.gmail_provider import GmailApplicationSourceProvider
    token_provider = GmailOAuthTokenProvider(
        credentials={
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "refresh_token": access.delegated_to or "",
        }
    )
    provider = GmailApplicationSourceProvider(
        token_provider=token_provider,
        search_result_limit=config.search_result_limit,
    )
    return SourceRuntimeBundle(
        descriptor=descriptor,
        config=config,
        access=access,
        cursor_store=self._cursor_store,
        provider=provider,
        metadata_json=dict(descriptor.metadata_json),
    )
```

Note: `access.delegated_to` holds the refresh_token value. The credential
provider resolves this from `SourceCredentialRef.credential_ref`. For the spike,
the refresh token comes from `DOTMD_GMAIL_REFRESH_TOKEN` env var wired in
Settings (see Task 3).

**5. Add `elif namespace == "gmail":` branch in `build_if_configured()`**:
```python
if namespace == "gmail":
    config = record.config
    if not isinstance(config, GmailSourceConfig):
        return None
    # client_id and client_secret are required fields — if we have a GmailSourceConfig, they are set
return self.build(namespace)
```
</action>

<acceptance_criteria>
- `from dotmd.ingestion.source_lifecycle import GmailSourceConfig` imports cleanly
- `GmailSourceConfig(client_id="cid", client_secret="csec")` constructs without error
- `GmailSourceConfig(client_id="cid", client_secret="csec").search_result_limit == 10`
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
gmail_search_result_limit: int = Field(10, alias="DOTMD_GMAIL_SEARCH_RESULT_LIMIT")
```

In `backend/src/dotmd/api/service.py`, in `DotMDService.__init__()` where the
`InMemorySourceConfigStore` is populated (search for where TelegramSourceConfig
is added to the config store), add a parallel block for Gmail:

```python
if self._settings.gmail_client_id and self._settings.gmail_client_secret and self._settings.gmail_refresh_token:
    from dotmd.ingestion.source_lifecycle import GmailSourceConfig, SourceConfigRecord, SourceCredentialRef
    gmail_config_record = SourceConfigRecord(
        namespace="gmail",
        config=GmailSourceConfig(
            client_id=self._settings.gmail_client_id,
            client_secret=self._settings.gmail_client_secret,
            search_result_limit=self._settings.gmail_search_result_limit,
        ),
        credential_ref=SourceCredentialRef(
            namespace="gmail",
            credential_ref=self._settings.gmail_refresh_token,
        ),
    )
    config_store.set_config(gmail_config_record)
```

Also update `DefaultSourceCredentialProvider.get_access()` to handle `auth_kind="oauth_refresh"`:
In `source_lifecycle.py`, add a branch:
```python
if descriptor.auth_schema.auth_kind == "oauth_refresh":
    if not credential_ref.credential_ref:
        raise SourceLifecycleConfigError(
            f"{descriptor.namespace}.credential_ref (refresh_token) is required"
        )
    return SourceAccess(kind="delegated", delegated_to=credential_ref.credential_ref)
```

This means `access.delegated_to` holds the refresh token string, which the
`GmailOAuthTokenProvider` receives as the `refresh_token` credential.
</action>

<acceptance_criteria>
- Settings class has `gmail_client_id`, `gmail_client_secret`, `gmail_refresh_token`, `gmail_search_result_limit` fields
- With `DOTMD_GMAIL_CLIENT_ID=x DOTMD_GMAIL_CLIENT_SECRET=y DOTMD_GMAIL_REFRESH_TOKEN=z` env set, `DotMDService._build_federated_bundles()` adds a gmail bundle to `self._lifecycle_bundles`
- Without Gmail env vars set, no gmail bundle is built (no error)
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
`test_lifecycle_build_missing_config_raises` tests.

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
```

Implement `test_lifecycle_build_missing_config_raises`:
```python
def test_lifecycle_build_missing_config_raises():
    from dotmd.ingestion.source_lifecycle import (
        SourceRuntimeFactory, InMemorySourceConfigStore,
        DefaultSourceCredentialProvider, SourceLifecycleConfigError
    )
    from dotmd.core.source_registry import SourceRegistry
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
```
</action>

<acceptance_criteria>
- `cd backend && python -m pytest tests/test_gmail_bridge.py -v` exits 0 with all tests passing
- No skip markers on test_gmail_descriptor or test_lifecycle_build_missing_config_raises
- test_build_if_configured_returns_none_without_gmail_config passes
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
"
```
