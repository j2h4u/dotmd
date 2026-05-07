---
phase: "28"
status: passed
verified_at: 2026-05-07T18:41:00Z
requirements: ["R3", "R4", "R8"]
score: 23/23
human_verification: []
gaps: []
---

# Phase 28 Verification: Application Source Provider Contract

## Verdict

Phase 28 achieved its goal. The codebase now has a source-neutral provider
contract, typed provider payloads, additive source checkpoint/fingerprint
storage, deterministic fixture coverage, and an `mcp-telegram` contract note
for Phase 29 planning.

## Requirement Traceability

| Requirement | Status | Evidence |
|---|---|---|
| R3: Application Source Provider Contract | Passed | `ApplicationSourceProviderProtocol`, provider payload models, `SourceUnitWindow`, source-neutral docs. |
| R4: Telegram Provider Via mcp-telegram | Passed | `docs/mcp-telegram-source-contract.md` defines the structured boundary and states dotMD does not own Telegram auth/runtime or private SQLite reads. |
| R8: Validation And Smoke | Passed | Fixture tests cover provider behavior without live Telegram; typecheck, lint, focused tests, JSON validation, and code review passed. |

## Must-Have Checks

- Generic production code uses `ApplicationSourceDescription`,
  `ApplicationSourceChange`, `ApplicationSourceChangeBatch`,
  `SourceUnitWindow`, and `ApplicationSourceProviderProtocol`.
- Provider methods are exactly the planned generic set:
  `describe_source`, `export_changes`, and `read_unit_window`.
- Production provider code contains no `mcp_telegram`, `telethon`,
  `export_documents`, or `export_units` method.
- `SourceUnit.updated_at` is required and tested.
- `source_checkpoints` stores `checkpoint_cursor`; tests cover rollback before
  commit and standalone diagnostic error persistence.
- `source_unit_fingerprints` keys by namespace/document/unit, indexes
  `(namespace, document_ref)`, classifies unchanged replay as `False`, and has
  no lifecycle `deleted_at` column.
- Deterministic fixtures prove offset cursors, neighboring message windows,
  implicit root fallback, malformed cursor errors, unknown unit errors, invalid
  limit errors, and fingerprint replay idempotency.
- The contract note maps Telegram dialog to `SourceDocument`, message to
  `SourceUnit`, includes `next_cursor` and `checkpoint_cursor`, and documents
  the safe checkpoint commit order.
- Phase 28 did not run `dotmd index --force`, TEI re-embedding, FTS rebuild,
  vector rebuild, graph rebuild, or live Telegram smoke.

## Automated Checks

- `rg -n "class ApplicationSourceDescription|class ApplicationSourceChange|class ApplicationSourceChangeBatch|class SourceUnitWindow|updated_at: datetime|class ApplicationSourceProviderProtocol|describe_source|export_changes|read_unit_window|export_documents|export_units|mcp_telegram|telethon" backend/src/dotmd/core/models.py backend/src/dotmd/ingestion/source_provider.py backend/tests/ingestion/application_source_fixtures.py backend/tests/ingestion/test_application_source_provider.py` passed with expected production/test hits and no forbidden production imports or methods.
- `rg -n "source_checkpoints|source_unit_fingerprints|idx_source_unit_fingerprints_document|def commit_source_checkpoint|def get_source_checkpoint|def record_source_checkpoint_error|def upsert_source_unit_fingerprint|def get_source_unit_fingerprint|deleted_at|save_next_cursor" backend/src/dotmd/storage/metadata.py backend/tests/storage/test_metadata_m2m.py` passed; `deleted_at` appears only in the negative test assertion.
- `rg -n "checkpoint_cursor|read_unit_window|SourceDocument|SourceUnit|private .*SQLite|no direct Telegram API client|no dotmd index --force|Phase 28" docs/mcp-telegram-source-contract.md docs/source-adapter-architecture.md docs/architecture.md .planning/phases/28-application-source-provider-contract/28-04-SUMMARY.md` passed.
- JSON validation for `docs/mcp-telegram-source-contract.md` passed: 3 JSON examples validated.
- `just typecheck` passed: pyright ratchet 66 errors, baseline 69, improvements -3 across 2 files.
- `just lint` passed: all checks passed.
- `cd backend && uv run pytest tests/ingestion/test_application_source_provider.py tests/storage/test_metadata_m2m.py tests/ingestion/test_source_filesystem.py tests/api/test_service_search.py -q` passed: 94 passed, 45 warnings.

## Code Review

Code review status: clean.

Review artifact: `28-REVIEW.md`.

One cleanup was applied before final review closure: `delete_all()` now clears
the new `source_checkpoints` and `source_unit_fingerprints` tables, with test
coverage in `test_metadata_m2m.py`.

## Human Verification

None required. Phase 28 is a contract, storage-helper, fixture, and documentation
phase; all required validation is automated or source-inspection based.

## Gaps

None.
