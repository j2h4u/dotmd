---
phase: 32
phase_name: source-capability-registry
status: clean
depth: standard
files_reviewed: 11
findings:
  critical: 0
  warning: 0
  info: 0
  total: 0
reviewed_at: 2026-05-08T13:45:00Z
---

# Phase 32 Code Review

## Scope

- `backend/src/dotmd/core/models.py`
- `backend/src/dotmd/core/source_registry.py`
- `backend/src/dotmd/ingestion/source_registry.py`
- `backend/src/dotmd/ingestion/source_provider.py`
- `backend/src/dotmd/ingestion/telegram_provider.py`
- `backend/tests/ingestion/test_source_registry.py`
- `backend/tests/ingestion/test_source_filesystem.py`
- `backend/tests/ingestion/test_application_source_provider.py`
- `backend/tests/ingestion/test_telegram_provider.py`
- `docs/source-registry-airweave-mapping.md`
- `docs/source-adapter-architecture.md`

## Findings

No issues found.

## Review Notes

- Descriptor models are declarative Pydantic models and do not instantiate providers, read credentials, or persist cursors.
- Capability vocabulary is closed through `SourceCapability`; legacy Telegram daemon strings are accepted only as compatibility input and normalized through `normalized_capabilities()`.
- Mutable descriptor collections and metadata use `Field(default_factory=...)`; registry reads return deep copies.
- Default filesystem and Telegram descriptors do not import Telegram API clients, Airweave, Docker, SQLite, settings, or runtime lifecycle code.
- Docs keep Airweave as engineering reference material and explicitly reject/defer non-dotMD runtime/product subsystems.

## Verification Reviewed

- `cd backend && uv run pytest tests/ingestion/test_source_registry.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_application_source_provider.py tests/ingestion/test_telegram_provider.py -q` - passed.
- `cd backend && uv run pyright src/dotmd/core/models.py src/dotmd/core/source_registry.py src/dotmd/ingestion/source_registry.py src/dotmd/ingestion/source_provider.py src/dotmd/ingestion/telegram_provider.py tests/ingestion/test_source_registry.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_application_source_provider.py tests/ingestion/test_telegram_provider.py` - passed.
- Docs/import guard `rg` checks - passed.

