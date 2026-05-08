---
phase: 33
slug: source-lifecycle-config-auth-cursor-boundary
status: passed
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-08
last_audited: 2026-05-08
---

# Phase 33 - Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | `backend/pyproject.toml` |
| Quick run command | `cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py -q` |
| Full suite command | `cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_telegram_ingestion.py tests/ingestion/test_telegram_provider.py tests/api/test_service_search.py tests/storage/test_metadata_m2m.py -q` |
| Static check command | `cd backend && uv run pyright src/dotmd/ingestion/source_lifecycle.py src/dotmd/ingestion/pipeline.py src/dotmd/api/service.py src/dotmd/cli.py tests/ingestion/test_source_lifecycle.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_telegram_ingestion.py tests/ingestion/test_telegram_provider.py tests/api/test_service_search.py tests/storage/test_metadata_m2m.py` |
| Estimated runtime | ~10 seconds for targeted tests plus scoped pyright |

## Sampling Rate

- After every task commit: run the quick lifecycle tests when touching
  lifecycle models/factory code.
- After each integration plan: run that plan's targeted regression command.
- Before `$gsd-verify-work`: run the full suite command, scoped pyright, and
  the static import scan.
- Max feedback latency: one task commit.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 33-01-01 | 01 | 1 | LIFE-01, LIFE-02 | T-33-01 | Lifecycle returns inspectable typed bundles and rejects missing config/credential refs. | unit | `cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py -q` | yes | covered |
| 33-01-02 | 01 | 1 | LIFE-01, LIFE-02, LIFE-03 | T-33-02 | Cursor access is behind a store wrapper that still requires caller-owned transactions for commits. | unit | `cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py tests/storage/test_metadata_m2m.py -q` | yes | covered |
| 33-02-01 | 02 | 2 | LIFE-01, LIFE-04 | T-33-03 | Filesystem runtime is built from descriptor and typed config without changing refs. | regression | `cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py tests/ingestion/test_source_filesystem.py -q` | yes | covered |
| 33-02-02 | 02 | 2 | LIFE-04 | T-33-04 | Pipeline filesystem discovery uses lifecycle instead of direct adapter construction. | regression | `cd backend && uv run pytest tests/ingestion/test_source_filesystem.py -q` | yes | covered |
| 33-03-01 | 03 | 3 | LIFE-01, LIFE-02, LIFE-04 | T-33-05 | Telegram provider is built through lifecycle and keeps auth delegated to `mcp-telegram`. | regression | `cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py tests/ingestion/test_telegram_provider.py tests/api/test_service_search.py -q` | yes | covered |
| 33-03-02 | 03 | 3 | LIFE-03, LIFE-04 | T-33-06 | Application-source ingest uses lifecycle cursor store and preserves checkpoint-after-transaction semantics. | regression | `cd backend && uv run pytest tests/ingestion/test_telegram_ingestion.py tests/storage/test_metadata_m2m.py -q` | yes | covered |

## Wave 0 Requirements

Existing infrastructure is enough for Phase 33. No production container,
database migration, live Telegram daemon, full reindex, TEI call, FTS rebuild,
vector rebuild, or graph rebuild is required to validate the planned work.

## Manual-Only Verifications

No mandatory manual verification is planned. Optional live Telegram smoke can
be deferred to later unified Telegram phases because Phase 33 changes runtime
construction and cursor boundaries, not provider payload semantics.

## Validation Audit 2026-05-08

| Metric | Count |
|--------|-------|
| Requirements audited | 4 |
| Task rows audited | 6 |
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

No missing automated coverage was found. Phase 33 already has regression tests
for lifecycle runtime bundles, delegated Telegram access, filesystem lifecycle
construction, service/CLI Telegram construction, and transaction-owned
application-source cursor commits.

## Audit Evidence

| Check | Result |
|-------|--------|
| Focused pytest | `128 passed, 71 warnings in 6.70s` |
| Scoped pyright | `0 errors, 0 warnings, 0 informations` |
| Airweave import scan | no matches |
| Direct Telegram/private SQLite scan | no matches |
| Filesystem direct construction scan | no matches |
| Service/CLI direct Telegram construction scan | no matches |

## Static Guards

Run before phase verification:

- `rg -n "from airweave|import airweave" backend/src backend/tests` returns no matches.
- `rg -n "Telethon|telegram\\.client|sqlite.*telegram|telegram.*sqlite" backend/src backend/tests` returns no new direct Telegram API/private database access in dotMD runtime code.
- `rg -n "FilesystemMarkdownSourceAdapter\\(\\)" backend/src/dotmd/ingestion/pipeline.py` returns no direct construction after Plan 02.
- `rg -n "TelegramApplicationSourceProvider\\(" backend/src/dotmd/api/service.py backend/src/dotmd/cli.py` returns no direct construction after Plan 03.

## Validation Sign-Off

- [x] All tasks have automated verify commands or grep/static checks.
- [x] Sampling continuity: no three consecutive tasks without automated verify.
- [x] Wave 0 covers missing references.
- [x] No watch-mode flags.
- [x] Feedback latency is below one task commit.
- [x] `nyquist_compliant: true` set in frontmatter.

**Approval:** audited 2026-05-08
