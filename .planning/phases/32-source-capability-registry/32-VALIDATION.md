---
phase: 32
slug: source-capability-registry
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-08
---

# Phase 32 - Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | `backend/pyproject.toml` |
| Quick run command | `cd backend && uv run pytest tests/ingestion/test_source_registry.py -q` |
| Full suite command | `cd backend && uv run pytest tests/ingestion/test_source_registry.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_telegram_provider.py tests/ingestion/test_application_source_provider.py -q` |
| Static check command | `cd backend && uv run pyright` |
| Estimated runtime | ~45-90 seconds for targeted tests, pyright depends on cache |

## Sampling Rate

- After every task commit: run the quick command when the task touches registry
  models, registry seeds, or descriptor compatibility.
- After every plan wave: run the full suite command for source-registry and
  existing source provider regression coverage.
- Before `$gsd-verify-work`: run the full suite command and `cd backend && uv run pyright`.
- Max feedback latency: one task commit.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 32-01-01 | 01 | 1 | SRC-01, SRC-03 | T-32-01 | Descriptors reject loose capability strings and malformed schemas. | unit | `cd backend && uv run pytest tests/ingestion/test_source_registry.py -q` | yes | pending |
| 32-01-02 | 01 | 1 | SRC-01 | T-32-02 | Registry rejects duplicate namespaces and returns copy-safe descriptors. | unit | `cd backend && uv run pytest tests/ingestion/test_source_registry.py -q` | yes | pending |
| 32-02-01 | 02 | 2 | SRC-02, SRC-03 | T-32-03 | Filesystem descriptor does not claim Telegram/provider capabilities. | unit | `cd backend && uv run pytest tests/ingestion/test_source_registry.py tests/ingestion/test_source_filesystem.py -q` | yes | pending |
| 32-02-02 | 02 | 2 | SRC-02, SRC-03 | T-32-04 | Telegram descriptor points at `mcp-telegram` and not direct Telegram API auth. | unit | `cd backend && uv run pytest tests/ingestion/test_source_registry.py tests/ingestion/test_telegram_provider.py -q` | yes | pending |
| 32-03-01 | 03 | 2 | SRC-01, SRC-02 | T-32-05 | Existing provider descriptions still construct and expose expected capability data. | regression | `cd backend && uv run pytest tests/ingestion/test_application_source_provider.py tests/ingestion/test_telegram_provider.py -q` | yes | pending |
| 32-04-01 | 04 | 3 | SRC-04 | T-32-06 | Airweave mapping docs do not introduce a runtime import or dependency. | docs/static | `rg -n "copied|adapted|rejected|deferred|runtime dependency" docs/source-registry-airweave-mapping.md` | yes | pending |

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

**Approval:** pending execution

