# Source Registry Airweave Mapping

dotMD has no runtime Airweave dependency. Phase 32 uses Airweave as an
engineering reference for source catalog vocabulary, not as a schema or runtime
to import. The useful idea is a declarative source catalog entry that says what
a source can do before lifecycle code constructs clients, opens credentials, or
commits cursors.

## Mapping Table

| Airweave concept | dotMD descriptor field | Status | Reason |
|---|---|---|---|
| `name` | `SourceDisplayMetadata.display_name` | adapted | dotMD keeps the human-facing label but stores it under display metadata. |
| `description` | `SourceDisplayMetadata.description` | adapted | dotMD preserves the explanatory text as display metadata instead of a top-level source field. |
| `short_name` | `SourceDescriptor.namespace` | adapted | dotMD uses stable namespaces such as `filesystem` and `telegram` as public source identity. |
| `class_name` | none | rejected | Phase 32 descriptors must not point at runtime implementation classes or factories. |
| `auth_methods` | `SourceAuthSchema.methods` | adapted | dotMD can describe supported auth methods, but runtime auth handling belongs to Phase 33. |
| `oauth_type` | `SourceAuthSchema.metadata_json` in a later lifecycle model | deferred | OAuth token semantics are lifecycle/auth configuration, not required for the Phase 32 descriptor seeds. |
| `requires_byoc` | future lifecycle/auth policy | deferred | Bring-your-own-client behavior is credential setup policy and belongs with Phase 33 auth handling. |
| `auth_config_class` | `SourceAuthSchema.fields` | adapted | dotMD uses structural Pydantic schema fields rather than naming Python config classes. |
| `auth_fields` | `SourceAuthSchema.fields` | copied | Field-level auth requirements are useful declarative metadata. |
| `config_class` | `SourceConfigSchema.name` | adapted | dotMD keeps a schema name but does not require a runtime Python config class. |
| `config_fields` | `SourceConfigSchema.fields` | copied | Source configuration fields are direct descriptor metadata. |
| `supports_continuous` | `SourceCapability.INCREMENTAL_CURSOR` | adapted | dotMD models this as a capability flag and leaves cursor commits to lifecycle code. |
| `federated_search` | `SourceCapability.FEDERATED_SEARCH` | copied | The capability is useful for sources that can produce native search candidates. |
| `supports_access_control` | `SourceCapability.ACL` | adapted | ACL support is represented as a capability marker without adding ACL enforcement in Phase 32. |
| `supports_browse_tree` | `SourceCapability.BROWSE_TREE` | copied | Browse-tree support is useful source capability metadata for later selective discovery. |
| `rate_limit_level` | future lifecycle/runtime policy | deferred | Rate limits matter during execution, not for the minimal Phase 32 descriptor contract. |
| `feature_flag` | none | rejected | dotMD is a local knowledgebase tool and does not need marketplace feature gates in this phase. |
| `output_entity_definitions` | future parser/entity catalog layer | deferred | Output entity catalogs are useful later, but Phase 32 only describes sources and capabilities. |
| `supported_auth_providers` | future lifecycle/auth policy | deferred | External auth provider selection belongs with runtime lifecycle and credentials. |
| `Temporal orchestration` | none | rejected | dotMD does not adopt Airweave orchestration infrastructure or worker runtime. |
| `organizations/collections/billing` | none | rejected | dotMD has no multi-tenant organization, collection, or billing plane in this project. |

## Copied Concepts

dotMD copies the concepts that are pure declarative source metadata:
configuration fields, authentication fields, federated-search support, and
browse-tree support. These map cleanly onto strict Pydantic descriptor models
and closed `SourceCapability` values without requiring runtime code.

## Adapted Concepts

dotMD adapts Airweave's catalog language into the existing source-ref model.
Airweave `short_name` becomes the dotMD namespace; display fields move under
`SourceDisplayMetadata`; class/config names become structural schemas instead
of runtime Python import paths; continuous sync becomes an
`incremental_cursor` capability marker.

This adaptation keeps local source refs, retained artifacts, typed Pydantic
contracts, and no runtime Airweave dependency as the core design constraints.

## Rejected Concepts

Phase 32 rejects runtime class binding, Airweave orchestration, marketplace
feature gates, and multi-tenant organization/collection/billing concepts. Those
subsystems solve Airweave product problems that dotMD does not currently have.

## Deferred Concepts

OAuth token shape, bring-your-own-client policy, rate limits, supported auth
providers, and output entity definitions are real concepts but not descriptor
MVP requirements. They should be revisited only when lifecycle/auth or entity
catalog phases need them.

## Runtime Boundary

Source descriptors are declarative. Phase 33 owns runtime construction,
credentials, and cursor commit behavior. Phase 32 does not instantiate
providers, open clients, read secrets, persist cursor checkpoints, import
Airweave, or copy Airweave runtime identifiers into dotMD source code.

Phase 33 adapts Airweave's lifecycle idea as a compact dotMD runtime bundle and
factory. The bundle combines the descriptor, typed local config, delegated or
no-auth access, cursor store, and the constructed filesystem source or Telegram
provider. This keeps the useful construction boundary while still rejecting
Airweave organizations, Temporal orchestration, billing, marketplace runtime,
and runtime Airweave imports.
