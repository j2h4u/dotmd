---
phase: 37-airweave-connector-compatibility-spike
plan: 37-04
subsystem: docs
tags: [airweave, gmail, compatibility, verification]
requires:
  - phase: 37-01
    provides: Vendored Airweave Gmail slice
  - phase: 37-02
    provides: Gmail federated bridge
  - phase: 37-03
    provides: Gmail registry and lifecycle wiring
provides:
  - Evidence-based Airweave compatibility report
  - AGENTS.md Phase 37 architecture notes
  - Registry, MCP schema, CLI, hybrid search, and Gmail test updates for current contracts
  - Green `just check` gate
affects: []
tech-stack:
  added: []
  patterns: [evidence-based-compatibility-report, vendored-connector-spike]
key-files:
  created:
    - docs/gmail-airweave-compatibility-spike.md
  modified:
    - AGENTS.md
    - backend/src/dotmd/ingestion/gmail_provider.py
    - backend/src/dotmd/ingestion/source_lifecycle.py
    - backend/tests/test_gmail_bridge.py
    - backend/tests/ingestion/test_source_registry.py
    - backend/tests/mcp/test_search_tool.py
    - backend/tests/test_cli.py
    - backend/tests/test_hybrid_bm25.py
key-decisions:
  - "Airweave entity schemas and decorator/source shell are useful references, but Airweave's runtime/indexing stack is intentionally avoided."
  - "Gmail federated search is dotMD direct API integration through BaseConnectorBridge, not reuse of Airweave's unimplemented GmailSource.search()."
  - "SourceAsset support for GmailAttachmentEntity remains deferred."
requirements-completed: [AIR-02, AIR-03]
duration: 45min
completed: 2026-05-13
commit: 60954a9
---

# Phase 37 Plan 04 Summary

**Airweave compatibility report completed and phase gate verified**

## Accomplishments

- Added `docs/gmail-airweave-compatibility-spike.md` from the implemented vendor slice, Gmail bridge, registry, lifecycle, and shim files.
- Documented the split between reusable Airweave pieces, shimmed pieces, and avoided Airweave runtime components.
- Documented that `GmailSource.search()` is not implemented and that `GmailBridge.search_native()` is dotMD-owned direct Gmail API behavior.
- Added `AGENTS.md` Phase 37 notes covering vendoring, token caching, generic bridge boundaries, and federated-only Gmail behavior.
- Updated current-contract tests uncovered by the full suite: Gmail default registry membership, MCP `SearchResponse` schema/output shape, CLI `SearchResponse` fixture, and hybrid search patch targets.
- Tightened Gmail settings activation so mock/dynamic attributes are not mistaken for configured credentials.
- Applied narrow lint/type fixes needed to keep `just check` green.

## Deviations from Plan

### Auto-fixed Issues

**1. Current test contracts lagged behind existing service/MCP shapes**
- **Found during:** Full non-e2e suite.
- **Issue:** Several tests still assumed older list or `SearchHit` contracts while production now returns `SearchResponse` and `SearchCandidate`.
- **Fix:** Updated tests to follow actual schema refs and response envelopes.
- **Committed in:** `60954a9`

**2. Mock settings were treated as Gmail credentials**
- **Found during:** Full non-e2e suite.
- **Issue:** `source_runtime_factory_from_settings()` treated truthy `MagicMock` attributes as complete Gmail env config.
- **Fix:** Added a non-empty-string guard before seeding Gmail config from settings.
- **Committed in:** `60954a9`

## Verification

- `uv run python -m pytest tests/ --ignore=tests/e2e -x -q` - 550 passed, 14 skipped.
- `just lint` - passed.
- `just typecheck` - passed; Pyright ratchet improved to 61 errors against baseline 79.
- `just check` - passed; 550 passed, 14 skipped, 36 deselected.

## Notes

- Live MCP e2e tests remain outside `just check`; earlier direct e2e attempts could not start a local MCP server because runtime settings expect production-style absolute paths and `/dotmd-index`.
- Pre-existing dirty changes in `backend/src/dotmd/ingestion/telegram_provider.py` and generated `graphify-out/` files were left uncommitted.

## Self-Check: PASSED

---
*Phase: 37-airweave-connector-compatibility-spike*
*Completed: 2026-05-13*
