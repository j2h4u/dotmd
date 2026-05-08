---
phase: "32"
plan: "01"
type: tdd
wave: 1
depends_on: []
files_modified:
  - backend/src/dotmd/core/models.py
  - backend/src/dotmd/core/source_registry.py
  - backend/tests/ingestion/test_source_registry.py
autonomous: true
requirements: ["SRC-01", "SRC-03"]
requirements_addressed: ["SRC-01", "SRC-03"]
must_haves:
  truths:
    - "D-01: Use Airweave principles-first, not schema-first."
    - "D-04: A source descriptor is declarative only."
    - "D-05: Runtime construction, credential access, cursor state ownership, and provider factory wiring remain Phase 33 lifecycle scope."
    - "D-06: Descriptor schemas are structural Pydantic models, not loose untyped dictionaries or placeholder strings."
    - "D-07: Capability flags are a closed enum in Phase 32."
    - "D-08: The closed capability vocabulary covers local sync, federated/native search, read-unit windows, materialization, browse trees, ACL support, and incremental cursors."
    - "D-09: New capabilities require explicit model changes."
---

# Phase 32 Plan 01: Source Descriptor Contract

<objective>
Create the typed source descriptor and closed capability vocabulary that every
registered dotMD source will use.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Loose string capabilities drift across phases | HIGH | Add `SourceCapability(StrEnum)` and descriptor tests that reject unknown capability values. |
| Registry descriptors become runtime factories | HIGH | Keep descriptor models in `core` declarative and do not add provider/client construction methods. |
| Schema fields become untyped bags | HIGH | Add Pydantic schema models with `extra="forbid"` and concrete field lists. |
| Phase 32 accidentally owns credentials or cursor commits | HIGH | Model auth/cursor schemas as descriptions only; no secret access, no checkpoint persistence. |
</threat_model>

<tasks>
<task id="1" type="tdd">
<title>Add descriptor model tests first</title>
<read_first>
- `.planning/phases/32-source-capability-registry/32-CONTEXT.md`
- `.planning/phases/32-source-capability-registry/32-RESEARCH.md`
- `backend/src/dotmd/core/models.py`
- `backend/tests/ingestion/test_application_source_provider.py`
</read_first>
<files>
- `backend/tests/ingestion/test_source_registry.py`
</files>
<action>
Create `backend/tests/ingestion/test_source_registry.py` with failing tests for
the new descriptor contract.

Concrete tests:
- `test_source_capability_is_closed_enum` asserts the enum values are exactly:
  `local_sync`, `federated_search`, `read_unit_window`, `materialization`,
  `browse_tree`, `acl`, `incremental_cursor`.
- `test_source_descriptor_requires_structural_schemas` constructs a descriptor
  with display metadata, config schema, auth schema, cursor schema, and
  capability flags, then asserts those fields are accessible as typed models.
- `test_source_descriptor_rejects_unknown_capability` passes
  `capabilities=["made_up"]` and expects `pydantic.ValidationError`.
- `test_source_descriptor_forbids_extra_fields` passes an Airweave-only field
  such as `organization_id` and expects `pydantic.ValidationError`.
- `test_source_registry_rejects_duplicate_namespace` asserts duplicate
  namespace registration raises `ValueError`.
</action>
<acceptance_criteria>
- `backend/tests/ingestion/test_source_registry.py` contains `test_source_capability_is_closed_enum`.
- The expected enum value list contains `local_sync`, `federated_search`, `read_unit_window`, `materialization`, `browse_tree`, `acl`, and `incremental_cursor`.
- The tests import `ValidationError` from `pydantic`.
- `cd backend && uv run pytest tests/ingestion/test_source_registry.py -q` fails before the model implementation and exits 0 after task 2.
</acceptance_criteria>
</task>

<task id="2" type="tdd">
<title>Implement typed descriptor models and registry container</title>
<read_first>
- `backend/src/dotmd/core/models.py`
- `backend/tests/ingestion/test_source_registry.py`
</read_first>
<files>
- `backend/src/dotmd/core/models.py`
- `backend/src/dotmd/core/source_registry.py`
- `backend/tests/ingestion/test_source_registry.py`
</files>
<action>
Implement the descriptor model family.

Concrete target state:
- Add `SourceCapability(StrEnum)` with exactly these values:
  - `LOCAL_SYNC = "local_sync"`
  - `FEDERATED_SEARCH = "federated_search"`
  - `READ_UNIT_WINDOW = "read_unit_window"`
  - `MATERIALIZATION = "materialization"`
  - `BROWSE_TREE = "browse_tree"`
  - `ACL = "acl"`
  - `INCREMENTAL_CURSOR = "incremental_cursor"`
- Add strict Pydantic models:
  - `SourceDisplayMetadata(display_name: str, description: str, labels: list[str] = [], docs_slug: str | None = None)`
  - `SourceSchemaField(name: str, field_type: str, required: bool = False, description: str = "")`
  - `SourceConfigSchema(name: str, fields: list[SourceSchemaField] = [], empty: bool = False)`
  - `SourceAuthSchema(auth_kind: str, methods: list[str] = [], fields: list[SourceSchemaField] = [], delegated_to: str | None = None)`
  - `SourceCursorSchema(cursor_kind: str, examples: list[str] = [], description: str = "")`
  - `SourceDescriptor(namespace: str, source_kind: str, display: SourceDisplayMetadata, config_schema: SourceConfigSchema, auth_schema: SourceAuthSchema, cursor_schema: SourceCursorSchema, capabilities: list[SourceCapability], metadata_json: dict = {})`
- Put `SourceRegistry` in `backend/src/dotmd/core/source_registry.py` with:
  - `register(descriptor: SourceDescriptor) -> None`
  - `get(namespace: str) -> SourceDescriptor | None`
  - `require(namespace: str) -> SourceDescriptor`
  - `list() -> list[SourceDescriptor]`
- Duplicate `namespace` registration raises `ValueError("source namespace already registered: <namespace>")`.
- `get`, `require`, and `list` return `model_copy(deep=True)` results so callers cannot mutate the registry internals.
- Do not add provider construction, credential lookup, cursor checkpoint writes, storage tables, or Airweave imports.
</action>
<acceptance_criteria>
- `backend/src/dotmd/core/models.py` contains `class SourceCapability(StrEnum)`.
- `backend/src/dotmd/core/models.py` contains `class SourceDescriptor(BaseModel)`.
- `backend/src/dotmd/core/source_registry.py` contains `class SourceRegistry`.
- `backend/src/dotmd/core/source_registry.py` contains `model_copy(deep=True)`.
- `backend/src/dotmd/core/source_registry.py` does not contain `airweave`.
- `backend/src/dotmd/core/source_registry.py` does not contain `TokenProvider` or `credential`.
- `cd backend && uv run pytest tests/ingestion/test_source_registry.py -q` exits 0.
- `cd backend && uv run pyright` exits 0.
</acceptance_criteria>
</task>
</tasks>

<verification>
- `cd backend && uv run pytest tests/ingestion/test_source_registry.py -q`
- `cd backend && uv run pyright`
</verification>

<success_criteria>
- SRC-01 descriptor fields exist as typed Pydantic models.
- SRC-03 capability vocabulary is closed and exact.
- No Phase 33 lifecycle/runtime behavior is implemented.
</success_criteria>

