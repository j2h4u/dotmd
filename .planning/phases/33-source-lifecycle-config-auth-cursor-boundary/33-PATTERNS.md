# Phase 33: Source lifecycle/config/auth/cursor boundary - Pattern Map

**Generated:** 2026-05-08
**Status:** Complete

## Purpose

Map Phase 33 planned files to existing dotMD patterns so execution agents can
build the lifecycle boundary without creating a second source plane.

## Planned File Roles

| Planned file | Role | Closest existing analog |
|--------------|------|-------------------------|
| `backend/src/dotmd/ingestion/source_lifecycle.py` | Source runtime bundle, typed source configs, credential provider, cursor store, lifecycle factory | `backend/src/dotmd/ingestion/source_provider.py`, `backend/src/dotmd/core/source_registry.py`, Airweave `domains/sources/lifecycle.py` as reference only |
| `backend/tests/ingestion/test_source_lifecycle.py` | Lifecycle unit tests | `backend/tests/ingestion/test_source_registry.py`, `backend/tests/ingestion/test_application_source_provider.py` |
| `backend/src/dotmd/ingestion/pipeline.py` | Filesystem and application-source runtime integration; cursor commit boundary | Existing `_discover_documents*`, `_source_document_for_file_info()`, `ingest_application_source()` |
| `backend/src/dotmd/api/service.py` | Optional Telegram runtime construction for public read/drill | Existing `_build_telegram_provider()` |
| `backend/src/dotmd/cli.py` | `dotmd telegram ingest` construction path | Existing `telegram_ingest()` command |
| `backend/tests/ingestion/test_source_filesystem.py` | Filesystem lifecycle regression | Existing `FilesystemMarkdownSourceAdapter` tests |
| `backend/tests/ingestion/test_telegram_ingestion.py` | Cursor and Telegram ingest regression | Existing fixture provider and checkpoint assertions |
| `backend/tests/api/test_service_search.py` | Service-level Telegram provider regression | Existing read/drill Telegram fixtures |
| `docs/source-adapter-architecture.md` | Main architecture note update for Phase 33 lifecycle boundary | Existing Phase 26-32 delivered/planned sections |
| `docs/source-registry-airweave-mapping.md` | Mapping update from registry to lifecycle | Existing Phase 32 mapping table |

## Code Excerpts And Patterns

### Registry pattern

The lifecycle factory should consume the registry through its public methods:

```python
descriptor = default_source_registry().require("telegram")
```

Do not mutate descriptors returned from the registry; they are deep copies.

### Provider protocol pattern

Application sources already use the minimal protocol:

```python
class ApplicationSourceProviderProtocol(Protocol):
    def describe_source(self) -> ApplicationSourceDescription: ...
    def export_changes(...): ...
    def read_unit_window(...): ...
```

Lifecycle should construct providers; it should not replace the protocol.

### Filesystem adapter pattern

Filesystem construction currently uses:

```python
FilesystemMarkdownSourceAdapter().discover_multi(paths, exclude)
```

The lifecycle migration should preserve that adapter's behavior while moving
construction behind the runtime bundle.

### Cursor transaction pattern

Checkpoint persistence currently requires the caller transaction:

```python
self._metadata_store.commit_source_checkpoint(namespace, cursor, conn=self._conn)
```

The cursor-store wrapper must preserve the `conn=` requirement so a cursor
cannot commit outside successful local persistence.

### Telegram delegation pattern

Telegram runtime must stay delegated:

```python
UnixSocketTelegramSourceClient(socket_path)
TelegramApplicationSourceProvider(client)
```

Lifecycle may build these objects, but dotMD must not import Telethon, read
private Telegram SQLite tables, or own raw Telegram sessions.

## Data Flow

Target Phase 33 flow:

```text
SourceRegistry descriptor
  -> typed local config store
  -> credential/auth provider interface
  -> cursor store
  -> SourceRuntimeBundle
  -> filesystem adapter or Telegram provider
  -> existing pipeline/service/CLI behavior
```

Forbidden flow:

```text
descriptor -> raw secret value -> adapter direct read
descriptor -> direct Telegram API client
descriptor -> checkpoint write before local persistence commits
filesystem path -> public source identity
```

## Risks To Watch

- Building a lifecycle module that tests pass but `pipeline.py`, `service.py`,
  and `cli.py` do not actually use.
- Letting the local source config store become a raw secret store.
- Treating filesystem fingerprints as provider-owned cursor commits.
- Moving Telegram auth into dotMD instead of keeping it delegated to
  `mcp-telegram`.
- Accidentally requiring full reindex for a construction-path refactor.
- Breaking existing optional service startup when Telegram socket is not
  configured.

## Pattern Mapping Complete
