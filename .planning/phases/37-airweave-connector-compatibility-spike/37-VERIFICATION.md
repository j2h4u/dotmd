---
phase: 37-airweave-connector-compatibility-spike
status: passed
verified_at: 2026-05-13
verifier: codex-inline
requirements: [AIR-01, AIR-02, AIR-03]
automated_checks:
  - just check
  - verify.schema-drift
  - verify.codebase-drift
---

# Phase 37 Verification

## Verdict

Passed. Phase 37 proves dotMD can reuse an Airweave connector-style schema/source slice for Gmail without adopting Airweave's runtime stack or creating an Airweave-only integration lane.

## Requirement Traceability

| Requirement | Status | Evidence |
|-------------|--------|----------|
| AIR-01 | Passed | Vendored Gmail source/entity/config slice in `backend/src/dotmd/vendor/airweave/`; `BaseConnectorBridge` and `GmailBridge` convert Gmail-native results into `SearchCandidate` and `SourceUnitWindow`. `docs/airweave-compatibility.md` explicitly records deferred `SourceDocument`, `SourceUnit`, and `SourceAsset` mapping for the federated-only spike. |
| AIR-02 | Passed | `docs/airweave-compatibility.md` covers reusable pieces, required shims, avoided Airweave runtime components, `GmailSource.search()` absence, SourceAsset deferred mapping, and a generic bridge extensibility table. |
| AIR-03 | Passed | Gmail is registered via `gmail_source_descriptor()`, built through `SourceRuntimeFactory.build("gmail")`, and discovered by `DotMDService._build_federated_bundles()` through the same descriptor/lifecycle path as filesystem and Telegram. |

## Must-Have Verification

- `docs/airweave-compatibility.md` exists and is evidence-based.
- Report covers "Reusable Directly", "Requires Shims", and "Should Be Avoided".
- Report documents `GmailSource.search()` absence and `GmailBridge.search_native()` direct Gmail API fallback.
- Report documents deferred `SourceAsset` mapping for `GmailAttachmentEntity`.
- Report includes the extensibility assessment table and AIR-03 compliance checklist.
- `AGENTS.md` includes Phase 37 architecture notes for vendoring, token handling, and the bridge pattern.
- Grep for direct `from airweave` / `import airweave` imports under `backend/src/dotmd` returned no matches.
- `BaseConnectorBridge` is abstract and `GmailBridge` implements it.
- No separate Airweave-only source lane was introduced.

## Automated Checks

- `just check` - passed.
  - Ruff: passed.
  - Pyright ratchet: passed, 61 errors against baseline 79.
  - Pytest: 550 passed, 14 skipped, 36 deselected.
- `gsd-sdk query verify.schema-drift 37` - no drift detected.
- `gsd-sdk query verify.codebase-drift 37` - non-blocking warning only; suggested refreshing broad codebase maps. No phase blocker.

## Residual Risks

- Gmail remains federated-only. Durable `SourceDocument` / `SourceUnit` materialization and deletion handling are intentionally deferred.
- Gmail native search currently performs one metadata round-trip per result. Batch metadata fetch is a future optimization.
- Live MCP e2e was not run locally because the local server startup path expects production-style absolute runtime paths and `/dotmd-index`; the workflow gate `just check` excludes e2e/smoke tests and passed.

## Human Verification

No human verification required for this spike.
