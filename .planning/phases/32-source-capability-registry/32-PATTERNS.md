# Phase 32: Source capability registry - Pattern Map

**Generated:** 2026-05-08
**Status:** Complete

## Purpose

Map Phase 32 planned files to the closest existing dotMD patterns so execution
agents can implement the registry without inventing a new source plane.

## Planned File Roles

| Planned file | Role | Closest existing analog |
|--------------|------|-------------------------|
| `backend/src/dotmd/core/models.py` or `backend/src/dotmd/core/source_registry.py` | Typed descriptor models and `SourceCapability` enum | `SearchMode`, `ExtractDepth`, `SourceDocument`, `ApplicationSourceDescription` in `core/models.py` |
| `backend/src/dotmd/ingestion/source_registry.py` | Default registry and seed descriptors | `ingestion/source.py` for filesystem constants; `ingestion/telegram_provider.py` for Telegram namespace/capabilities |
| `backend/tests/ingestion/test_source_registry.py` | Descriptor/registry tests | `test_application_source_provider.py`, `test_source_filesystem.py`, `test_telegram_provider.py` |
| `docs/source-registry-airweave-mapping.md` | Airweave-to-dotMD mapping docs | `docs/source-adapter-architecture.md`, `docs/mcp-telegram-source-contract.md` |
| `docs/source-adapter-architecture.md` | Main architecture note update | Existing Phase 26-29 delivered-state sections |

## Code Excerpts And Patterns

### Pydantic model pattern

Use the existing strict model style:

```python
class SourceDocument(BaseModel):
    """Source-aware document identity and metadata."""

    model_config = ConfigDict(extra="forbid")
```

Apply the same `ConfigDict(extra="forbid")` to descriptor, schema, and registry
models so unknown Airweave fields cannot leak into dotMD descriptors.

### Enum pattern

Use the existing `StrEnum` pattern:

```python
class SearchMode(StrEnum):
    SEMANTIC = "semantic"
```

`SourceCapability` should be a closed `StrEnum`, not a loose string list.

### Provider shape pattern

`ApplicationSourceProviderProtocol.describe_source()` currently returns an
`ApplicationSourceDescription`. Phase 32 should preserve this runtime protocol
and add descriptor compatibility around it instead of replacing provider
construction.

### Filesystem seed pattern

Filesystem constants already exist:

```python
class FilesystemMarkdownSourceAdapter:
    namespace = "filesystem"
    media_type = "text/markdown"
    parser_name = "markdown"
```

The filesystem descriptor should reuse these exact values.

### Telegram seed pattern

Telegram payload fixtures and provider code already use:

```python
{
    "namespace": "telegram",
    "source_kind": "chat",
    "display_name": "Telegram",
    "capabilities": ["incremental-export", "unit-window"],
}
```

The registry descriptor should normalize capability names to the new closed
enum while preserving compatibility with current description payloads where
needed.

## Data Flow

Phase 32 descriptor flow is intentionally code-only and declarative:

```text
source descriptor models
  -> default registry seeds
  -> tests/docs
  -> later Phase 33 lifecycle consumes descriptors
```

It must not flow into:

```text
registry -> credentials -> provider construction -> cursor commit
```

That lifecycle path is Phase 33.

## Risks To Watch

- Conflating `SourceDescriptor` with `ApplicationSourceProviderProtocol`.
- Letting `capabilities: list[str]` stay as the main future contract.
- Adding an Airweave import or copying Airweave runtime decorators.
- Claiming filesystem supports provider-owned incremental cursors.
- Claiming Telegram ACL support before there is enforceable ACL behavior.

## Pattern Mapping Complete

