# Coding Conventions

**Analysis Date:** 2026-05-10

## Naming Patterns

**Files:**
- `snake_case.py` throughout: `pipeline.py`, `sqlite_vec.py`, `source_lifecycle.py`
- Test files prefixed with `test_`: `test_pipeline_metadata.py`, `test_incremental_pipeline.py`
- Protocol modules named for their abstraction: `source_provider.py`, `base.py`
- Non-test helper modules in test dirs use plain names: `application_source_fixtures.py`, `conftest.py`

**Classes:**
- `PascalCase` for all classes: `IndexingPipeline`, `SQLiteMetadataStore`, `SemanticSearchEngine`
- Protocol classes suffixed with `Protocol`: `VectorStoreProtocol`, `GraphStoreProtocol`, `MetadataStoreProtocol`, `ApplicationSourceProviderProtocol`, `FederatedSearchProviderProtocol`
- Exception classes suffixed with `Error`: `DotMDError`, `IndexNotFoundError`, `IndexingLockError`, `StorageError`
- `StrEnum` subclasses named for the domain concept they enumerate: `SearchMode`, `DocKind`, `TrickleStatus`, `SourceCapability`
- Internal helper dataclasses prefixed with `_`: `_ExtractionBundle`

**Functions and methods:**
- `snake_case` everywhere: `encode_batch`, `add_chunks`, `delete_vectors_by_chunk_ids`
- Private methods prefixed with `_`: `_embed_chunks`, `_check_schema_version`, `_check_weights_changed`, `_validate_refs`
- Class methods decorated with `@classmethod` and named descriptively: `from_descriptor`, `normalized_capabilities`
- Module-level constants in `UPPER_SNAKE_CASE`: `SCHEMA_VERSION`, `ACTIVE_FILTER_OVERFETCH_FACTOR`, `TELEGRAM_REF_PREFIX`, `_DEFAULT_MODEL` (private constants prefixed with `_`)

**Variables:**
- `snake_case` throughout
- Private instance attributes prefixed with `_`: `self._vector_store`, `self._model_name`, `self._embedding_url`
- Loop variables and temporaries: descriptive short names (`chunk`, `embedding`, `file_path`)

**Pydantic models:**
- All field names in `snake_case`
- Validators using `@field_validator` and `@model_validator` are named with leading `_` to signal private: `_validate_refs`, `_validate_field_type`
- `ConfigDict(extra="forbid")` is the default for domain models; `frozen=True` added for result types (`SearchCandidate`, `SourceStatus`, `SearchResponse`)

## Code Style

**Formatting (ruff format):**
- Line length: 100 characters
- Quote style: double quotes (`"`)
- Indent style: 4 spaces
- Line endings: LF
- Config: `backend/pyproject.toml` `[tool.ruff.format]`

**Linting (ruff lint):**
- Rule sets active: `E`, `W`, `F`, `I`, `B`, `C4`, `SIM`, `UP`, `RUF`, `N`
- Notable ignores:
  - `E501` — line-too-long (formatter handles it; occasional long lines in docstrings accepted)
  - `B008` — default arg with function call (FastAPI/Click patterns)
  - `N802`, `N803`, `N806` — naming rules relaxed for MCP tool functions and Pydantic fields
  - `SIM108` — ternary not always mandated
  - `RUF002`, `RUF003` — ambiguous unicode allowed (Russian comments are intentional)
- Per-file ignores: `tests/**/*.py` exempt from `S101` (asserts fine in tests) and `B017`
- Config: `backend/pyproject.toml` `[tool.ruff.lint]`

**Type checking (pyright standard mode):**
- `typeCheckingMode = "standard"` — not strict
- `reportMissingTypeStubs = false` — stubs absent for several ML/DB libs; acceptable
- `# type: ignore[...]` used narrowly and always with a specific error code at the callsite
- Common suppression sites: untyped third-party imports (`sqlite_vec`, `yaml`, `gliner`, `sentence_transformers`), Protocol method-assign workarounds

## Import Organization

**Order (ruff `I` rules enforce this):**
1. `from __future__ import annotations` — always first line in every module
2. Standard library imports (grouped alphabetically)
3. Third-party imports
4. Local `dotmd.*` imports

**Style:**
- Absolute imports only: `from dotmd.core.models import Chunk` not relative
- `TYPE_CHECKING` guard used for heavy imports needed only at type-check time (e.g., `SentenceTransformer` in `semantic.py`)
- Aliased imports with leading `_` to signal internal use: `import dotmd.ingestion.chunker as _chunker_module`, `from dataclasses import dataclass as _dataclass`

**Path aliases:** None — no `__init__.py` re-exports at package level; callers import from the concrete submodule.

## Error Handling

**Exception hierarchy** (`backend/src/dotmd/core/exceptions.py`):
- All custom exceptions derive from `DotMDError(Exception)`
- Domain-specific subclasses: `IndexError`, `IndexNotFoundError`, `ChunkingError`, `StorageError`, `SearchError`, `ExtractionError`, `ConfigError`, `IndexingLockError`
- Use the narrowest applicable subclass when raising; catch `DotMDError` at boundaries

**Patterns:**
- Raise on unrecoverable state with an informative message; no silent swallowing
- Federated search uses soft-skip: errors surface in `SourceStatus` (`.status = "error"`, `.reason = str(exc)`) and do not abort the whole search
- `contextlib.suppress` / `with contextlib.suppress(...)` used for expected benign failures (e.g., missing optional tables)
- Storage operations do not catch broadly; they let SQLite/FalkorDB exceptions propagate to the pipeline caller

## Logging

**Framework:** `logging` (stdlib), module-level logger created once per module.

**Pattern:**
```python
import logging
logger = logging.getLogger(__name__)
```

**Log levels:**
- `logger.debug(...)` — per-file or per-chunk progress details, timing, cache hit/miss
- `logger.info(...)` — pipeline phase starts/ends, file counts, significant state changes
- `logger.warning(...)` — recoverable issues (missing optional field, fallback triggered)
- `logger.error(...)` — hard failures before raising or before marking a source as errored

**Format:** Plain strings with f-strings; counts and identifiers interpolated directly. No structured/JSON logging in-process.

## Comments

**When to comment:**
- Module docstrings on every file explaining purpose and design choices
- Class docstrings on all public classes (Parameters/Returns sections in NumPy style for complex signatures)
- Inline comments for non-obvious invariants, schema decisions, and regression notes (e.g., `# CONCERN-01 regression`)
- Section separators using dashed lines (`# ---------------------------------------------------------------------------`) to group logical sections within long files
- Russian comments appear in server-facing config and scripts; English is the default for code

**Docstrings:**
- NumPy-style Parameters / Returns sections in Protocol method docstrings
- Public API methods (Protocols, service facade) have full docstrings
- Internal `_`-prefixed helpers often have a single-sentence docstring or none
- No docstrings on `__init__` — constructor arguments are documented on the class

## Function Design

**Size:** No strict line limit, but complex multi-phase operations (pipeline index stages) are broken into private `_`-prefixed methods called from one orchestrator method.

**Parameters:**
- Keyword-only parameters (`*`) used wherever callers could confuse positional order: `add_chunks(..., *, overwrite: bool = True, text_hashes: ... | None = None)`
- Boolean flags use keyword-only syntax
- Settings/config injected via `Settings` object at construction time, not threaded through function signatures

**Return values:**
- `None` for write operations; explicit return types on all public methods
- `list[T]` for collections; empty list rather than `None` when nothing found
- `T | None` for single-item lookups (`get_chunk`, `get_stats`)
- Named tuples and dataclasses over bare tuples where fields have meaning (search returns `(chunk_id, float)` tuples as an internal contract but surfaces `SearchCandidate` models publicly)

## Module Design

**Exports:** No barrel `__init__.py` re-exports. Callers import from concrete submodules:
```python
from dotmd.storage.base import VectorStoreProtocol
from dotmd.core.models import Chunk, SearchCandidate
```

**Protocols over ABCs:** All extension points defined as `typing.Protocol` with `@runtime_checkable`. No `abc.ABC` base classes used.

**Pydantic models are the public contract:** All cross-layer data uses Pydantic v2 models. Raw dicts/tuples are internal to storage implementations and converted before crossing layer boundaries.

**`TypedDict` for ad-hoc dicts:** Service layer uses `TypedDict` (`ReadPayload`, `DrillPayload`) for structured dict return values that aren't worth a full Pydantic model.

---

*Convention analysis: 2026-05-10*
