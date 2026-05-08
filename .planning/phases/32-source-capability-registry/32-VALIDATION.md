---
phase: 32
slug: source-capability-registry
status: verified
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-08
last_audited: 2026-05-08
---

# Phase 32 - Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | `backend/pyproject.toml` |
| Quick run command | `cd backend && uv run pytest tests/ingestion/test_source_registry.py -q` |
| Full suite command | `cd backend && uv run pytest tests/ingestion/test_source_registry.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_telegram_provider.py tests/ingestion/test_application_source_provider.py -q` |
| Static check command | `cd backend && uv run pyright src/dotmd/core/models.py src/dotmd/core/source_registry.py src/dotmd/ingestion/source_registry.py src/dotmd/ingestion/source_provider.py src/dotmd/ingestion/telegram_provider.py tests/ingestion/test_source_registry.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_application_source_provider.py tests/ingestion/test_telegram_provider.py` |
| Estimated runtime | ~45-90 seconds for targeted tests, pyright depends on cache |

## Sampling Rate

- After every task commit: run the quick command when the task touches registry
  models, registry seeds, or descriptor compatibility.
- After every plan wave: run the full suite command for source-registry and
  existing source provider regression coverage.
- Before `$gsd-verify-work`: run the full suite command and the scoped Phase 32
  pyright command above. Repo-wide pyright still has pre-existing unrelated
  errors outside Phase 32, so it is not the Phase 32 Nyquist gate.
- Max feedback latency: one task commit.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 32-01-01 | 01 | 1 | SRC-01, SRC-03 | T-32-01 | Descriptors reject loose capability strings and malformed schemas. | unit | `cd backend && uv run pytest tests/ingestion/test_source_registry.py -q` | yes | passed |
| 32-01-02 | 01 | 1 | SRC-01 | T-32-02 | Registry rejects duplicate namespaces and returns copy-safe descriptors. | unit | `cd backend && uv run pytest tests/ingestion/test_source_registry.py -q` | yes | passed |
| 32-02-01 | 02 | 2 | SRC-02, SRC-03 | T-32-03 | Filesystem descriptor does not claim Telegram/provider capabilities. | unit | `cd backend && uv run pytest tests/ingestion/test_source_registry.py tests/ingestion/test_source_filesystem.py -q` | yes | passed |
| 32-02-02 | 02 | 2 | SRC-02, SRC-03 | T-32-04 | Telegram descriptor points at `mcp-telegram` and not direct Telegram API auth. | unit | `cd backend && uv run pytest tests/ingestion/test_source_registry.py tests/ingestion/test_telegram_provider.py -q` | yes | passed |
| 32-03-01 | 03 | 2 | SRC-01, SRC-02 | T-32-05 | Existing provider descriptions still construct and expose expected capability data. | regression | `cd backend && uv run pytest tests/ingestion/test_application_source_provider.py tests/ingestion/test_telegram_provider.py -q` | yes | passed |
| 32-04-01 | 04 | 3 | SRC-04 | T-32-06 | Airweave mapping docs do not introduce a runtime import or dependency. | docs/static | `rg -n "copied|adapted|rejected|deferred|runtime dependency" docs/source-registry-airweave-mapping.md` | yes | passed |

## Validation Audit 2026-05-08

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

### Audit Evidence

- `cd backend && uv run pytest tests/ingestion/test_source_registry.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_application_source_provider.py tests/ingestion/test_telegram_provider.py -q` - passed, 54 tests.
- `cd backend && uv run pyright src/dotmd/core/models.py src/dotmd/core/source_registry.py src/dotmd/ingestion/source_registry.py src/dotmd/ingestion/source_provider.py src/dotmd/ingestion/telegram_provider.py tests/ingestion/test_source_registry.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_application_source_provider.py tests/ingestion/test_telegram_provider.py` - passed, 0 errors.
- `rg -n "dotMD has no runtime Airweave dependency|copied|adapted|rejected|deferred" docs/source-registry-airweave-mapping.md` - passed.
- `rg -n "Phase 32|source registry|Phase 33|mcp-telegram" docs/source-adapter-architecture.md` - passed.
- `rg -n "from airweave|import airweave" backend/src backend/tests` - passed with no matches.
- `rg -n "supports_browse_tree|output_entity_definitions|class_name|feature_flag" backend/src backend/tests` - passed with no matches.

## Wave 0 Requirements

Existing infrastructure covers all phase requirements. No new test framework,
fixture harness, service container, database migration, or production data
setup is needed.

## Manual-Only Verifications

All Phase 32 behaviors have automated or static verification. No manual
production smoke is required because the registry is declarative and should
not alter indexing/search/read runtime behavior.

## Validation Sign-Off

- [x] All tasks have automated verify commands or grep/static checks.
- [x] Sampling continuity: no three consecutive tasks without automated verify.
- [x] Wave 0 covers all missing references.
- [x] No watch-mode flags.
- [x] Feedback latency is below one task commit.
- [x] `nyquist_compliant: true` set in frontmatter.

**Approval:** verified 2026-05-08
