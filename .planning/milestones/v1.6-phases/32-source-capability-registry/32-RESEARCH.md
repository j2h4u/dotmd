# Phase 32: Source capability registry - Research

**Researched:** 2026-05-08
**Status:** Complete

## Research Question

What does the planner need to know to introduce a dotMD-native source
registry/capability model, seeded with filesystem and Telegram, without
turning Phase 32 into runtime lifecycle work?

## Current dotMD Surfaces

### Existing source identity models

`backend/src/dotmd/core/models.py` already has the source vocabulary Phase 32
must preserve:

- `SourceDocument`: namespace, document_ref, ref, source_uri, media_type,
  parser_name, document_type, fingerprints, metadata, and optional filesystem
  file_path.
- `ResourceBinding`: active/inactive binding state, fingerprints, source unit
  refs, and binding metadata.
- `SourceUnit` and `SourceUnitWindow`: provider-owned unit identity and
  neighboring unit reads.
- `ApplicationSourceDescription`: current small description shape with
  namespace, source_kind, display_name, capabilities, and metadata_json.
- `ApplicationSourceChangeBatch`: changes plus continuation/checkpoint cursor
  metadata.

The registry should build on this vocabulary instead of inventing a separate
source plane.

### Provider/runtime boundary

`backend/src/dotmd/ingestion/source_provider.py` defines the application-source
runtime protocol:

- `describe_source()`
- `export_changes(cursor, limit, updated_after, updated_after_cursor)`
- `read_unit_window(unit_ref, before, after)`

Phase 32 should not add construction, credential lookup, cursor commits, or
provider factories here. Those are Phase 33 lifecycle scope. The registry can
describe capabilities that the protocol and lifecycle will later consume.

### Filesystem source

`backend/src/dotmd/ingestion/source.py` has
`FilesystemMarkdownSourceAdapter`, `filesystem_document_ref()`, and
`source_document_to_file_info()`.

Important facts for the descriptor:

- namespace: `filesystem`
- source kind: local documents or filesystem markdown
- media type: `text/markdown`
- parser: `markdown`
- document_ref: resolved filesystem path
- internal holder mechanics still need `file_path`
- capabilities should include local sync, materialization, and browse trees
  only if the descriptor is careful that browse means local directory/file
  discovery, not a new product UI.

### Telegram source

`backend/src/dotmd/ingestion/telegram_provider.py` maps structured
`mcp-telegram` daemon payloads into dotMD models.

Important facts for the descriptor:

- namespace: `telegram`
- source kind: chat
- document_ref: `dialog:<dialog_id>`
- message unit_ref: `dialog:<dialog_id>:message:<message_id>`
- public message ref: `telegram:dialog:<dialog_id>:message:<message_id>`
- capabilities include local sync/export, read-unit windows, incremental
  cursors, and future federated search where supported by `mcp-telegram`.
- dotMD must not instantiate a Telegram API client directly; the provider
  boundary remains `mcp-telegram`.

### Tests and style

Existing source tests live under `backend/tests/ingestion/`:

- `test_source_filesystem.py`
- `test_application_source_provider.py`
- `test_telegram_provider.py`
- `test_application_source_ingestion.py`

Tests already assert Pydantic validation behavior, protocol shape, filesystem
ref invariants, Telegram payload mapping, cursor forwarding, and idempotent
fingerprints. Phase 32 tests should follow this pattern: small typed model
tests plus registry seed tests, not broad integration tests.

## Airweave Reference Findings

The useful Airweave source catalog concepts are in
`/home/j2h4u/repos/airweave-ai/airweave/backend/airweave/schemas/source.py`.
The `Source` schema carries:

- human display metadata: name, description, short_name, labels
- implementation metadata: class_name
- auth metadata: auth_methods, oauth_type, requires_byoc,
  auth_config_class, auth_fields, supported_auth_providers
- config metadata: config_class, config_fields
- capability metadata: supports_continuous, federated_search,
  supports_access_control, supports_browse_tree
- operational metadata: rate_limit_level, feature_flag,
  supports_temporal_relevance
- entity output metadata: output_entity_definitions

The Google Slides example shows the decorator pattern that binds source
metadata, auth methods, config class, rate limit level, continuous sync, and
cursor class to a runtime connector class. dotMD should not copy the decorator
runtime pattern in Phase 32; Phase 32 should copy the catalog categories and
adapt them into typed descriptors.

## Recommended Descriptor Shape

The descriptor should be declarative and importable from a stable module such
as `dotmd.core.source_registry` or `dotmd.core.models` plus
`dotmd.ingestion.source_registry`.

Recommended model family:

- `SourceCapability(StrEnum)`
  - `LOCAL_SYNC = "local_sync"`
  - `FEDERATED_SEARCH = "federated_search"`
  - `READ_UNIT_WINDOW = "read_unit_window"`
  - `MATERIALIZATION = "materialization"`
  - `BROWSE_TREE = "browse_tree"`
  - `ACL = "acl"`
  - `INCREMENTAL_CURSOR = "incremental_cursor"`
- `SourceDisplayMetadata(BaseModel)`
  - `display_name: str`
  - `description: str`
  - `labels: list[str]`
  - optional `docs_slug: str | None`
- `SourceConfigSchema(BaseModel)`
  - structural schema name, fields, required field names, and whether it is
    empty.
- `SourceAuthSchema(BaseModel)`
  - auth kind/methods and fields, with an explicit none/local mode for
    filesystem and daemon-owned auth for Telegram.
- `SourceCursorSchema(BaseModel)`
  - cursor kind and stable examples.
- `SourceDescriptor(BaseModel)`
  - `namespace`, `source_kind`, display metadata, config schema, auth schema,
    cursor schema, capability flags, metadata_json.
- `SourceRegistry(BaseModel or simple class)`
  - registers descriptors by namespace.
  - rejects duplicate namespace.
  - returns immutable/copy-safe descriptors.
  - exposes a default registry seeded with filesystem and Telegram.

This can coexist with `ApplicationSourceDescription`. Either evolve
`ApplicationSourceDescription` to hold optional descriptor-shaped fields or
add a conversion helper from descriptor to the legacy lightweight description.
For Phase 32, preserving provider compatibility is more important than forcing
all runtime providers to return the new descriptor immediately.

## Seed Descriptor Guidance

### Filesystem

Filesystem should be registered as a real source, not as a special case
outside the registry.

Suggested fields:

- namespace: `filesystem`
- source_kind: `local_filesystem`
- display_name: `Filesystem Markdown`
- config schema: local path roots and excludes are intentionally lifecycle
  inputs for Phase 33, but Phase 32 can describe `paths` and `exclude` without
  reading them.
- auth schema: none/local process permissions.
- cursor schema: file metadata and fingerprints, not a provider cursor.
- capabilities: `local_sync`, `materialization`, `browse_tree`.
- no `federated_search`, no `acl`, no provider-owned
  `incremental_cursor`.

### Telegram

Telegram should describe the `mcp-telegram` boundary, not direct Telegram API
ownership.

Suggested fields:

- namespace: `telegram`
- source_kind: `chat`
- display_name: `Telegram`
- config schema: daemon socket/path or provider endpoint descriptor, but no
  secrets.
- auth schema: daemon-owned/session-owned auth.
- cursor schema: `telegram:v1:dialog:<dialog_id>:message:<message_id>` plus
  update watermarks.
- capabilities: `local_sync`, `read_unit_window`, `incremental_cursor`, and
  `federated_search` as future/native support if the descriptor can mark it
  supported by provider rather than implemented in dotMD Phase 32.
- no `acl` unless later Telegram metadata proves enforceable ACL behavior.

## Planning Constraints

- Keep Phase 32 additive. It should not require `dotmd index --force`, a full
  reindex, TEI calls, FTS rebuilds, vector rebuilds, graph rebuilds, production
  restart, or direct database migrations unless implementation discovers an
  unavoidable metadata persistence need. The registry can be code-first.
- Keep all public APIs routed through established service/CLI/MCP boundaries.
  If a registry listing command is added, it should call an importable registry
  helper, not storage internals.
- Keep source descriptors structural and typed. Avoid `dict[str, Any]` as the
  main schema boundary.
- Do not add runtime construction, secret reads, cursor commits, or lifecycle
  factories in this phase.
- Do not import Airweave from dotMD runtime or tests. Use Airweave only as a
  documentation reference and mapping source.

## Validation Architecture

Phase 32 is best verified with targeted automated checks:

1. Model validation tests for `SourceCapability`, descriptor schema models,
   duplicate registry rejection, and immutable/copy-safe registry reads.
2. Seed registry tests asserting filesystem and Telegram descriptors contain
   exact namespaces, source kinds, display metadata, schemas, and capability
   flags.
3. Compatibility tests proving existing provider descriptions can still be
   constructed and either convert from or coexist with descriptors.
4. Documentation checks proving the Airweave mapping table covers copied,
   adapted, rejected, and deferred concepts and explicitly states that Airweave
   is not a runtime dependency.

Recommended commands:

- `cd backend && uv run pytest tests/ingestion/test_source_registry.py -q`
- `cd backend && uv run pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_telegram_provider.py tests/ingestion/test_application_source_provider.py -q`
- `cd backend && uv run pyright`

Manual validation is not required for Phase 32 because no production runtime
behavior should change.

## Source Audit

| Source | Item | Planning implication |
|--------|------|----------------------|
| GOAL | dotMD-native source registry/capability model | Plan a typed descriptor model and default registry. |
| REQ | SRC-01 | Descriptor must include kind, display metadata, config/auth/cursor schemas, and capability flags. |
| REQ | SRC-02 | Filesystem and Telegram descriptors must be present and tested. |
| REQ | SRC-03 | Closed capability vocabulary must distinguish local sync, federated search, read windows, materialization, browse trees, ACLs, and incremental cursors. |
| REQ | SRC-04 | Docs must map Airweave metadata to dotMD descriptors with no runtime dependency. |
| CONTEXT | D-04, D-05 | Keep descriptor declarative and keep lifecycle out of Phase 32. |
| CONTEXT | D-10, D-12 | Seed descriptors must be detailed enough to guide future source authors. |
| CONTEXT | D-13, D-14, D-15 | Include explicit Airweave mapping docs. |

## RESEARCH COMPLETE

