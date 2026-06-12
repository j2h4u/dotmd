---
phase: 34-federated-searchcandidate-contract
fixed_at: 2026-05-09T21:45:00Z
review_path: .planning/phases/34-federated-searchcandidate-contract/34-REVIEW.md
iteration: 1
findings_in_scope: 8
fixed: 8
skipped: 0
status: all_fixed
---

# Phase 34: Code Review Fix Report

**Fixed at:** 2026-05-09T21:45:00Z  
**Source review:** .planning/phases/34-federated-searchcandidate-contract/34-REVIEW.md  
**Iteration:** 1

**Summary:**
- Findings in scope: 8 (2 Critical, 6 Warning)
- Fixed: 8
- Skipped: 0

## Fixed Issues

### CR-01: Shallow-Frozen Container Mutation Breaks Immutability Contract

**Files modified:** `backend/src/dotmd/core/models.py`  
**Commit:** 3f7e356  
**Applied fix:** Converted `matched_engines` from `list[str]` to `tuple[str, ...]` to enforce true immutability at the type level. Pydantic's `frozen=True` is shallow and allows container mutation; tuples prevent this structurally.

### CR-02: Unhandled Exception Type Coercion in telegram_provider.py Risks Silent Failures

**Files modified:** `backend/src/dotmd/api/service.py`  
**Commit:** a88d3e7  
**Applied fix:** Replaced unsafe exception type coercion pattern `raise type(e)(...)` with explicit `RuntimeError(...)` at two locations (_read_unit_telegram and _drill_unit_telegram). Type coercion can fail if exception's `__init__` has strict signature validation.

### WR-01: Inconsistent Low-Signal Text Detection Has Logic Bug

**Files modified:** `backend/src/dotmd/ingestion/telegram_provider.py`  
**Commit:** 63587d0  
**Applied fix:** Fixed logic bug in `is_low_signal_telegram_text`: changed final condition from AND to OR so symbol-only text like "😀😀😀" is correctly detected as low-signal. The AND meant text could never reach the symbol-detection case if it failed the alphanumeric check.

### WR-02: Missing Null Check Before String Operations in service.py

**Files modified:** `backend/src/dotmd/api/service.py`  
**Commit:** 44de7c2  
**Applied fix:** Added `isinstance(ref, str)` guard before calling `ref.startswith()` in the federated search filtering logic to prevent AttributeError if ref is None.

### WR-03: Test Fixture Accepts but Ignores Namespace Parameter

**Files modified:** `backend/tests/api/test_service_search.py`  
**Commit:** a736959  
**Applied fix:** Added namespace validation to `_LifecycleFactoryFixture.build_if_configured()` to return None if namespace != "telegram". Previously it accepted any namespace but hardcoded Telegram behavior, causing silent failures on unknown namespaces.

### WR-04: Missing Engine Attribution in Federated Candidate Building

**Files modified:** `backend/src/dotmd/api/service.py`  
**Commit:** 15b89e9  
**Applied fix:** Fixed federated candidate engine attribution to only include engines that actually scored this specific ref, rather than all engines in per_engine_ref. Now filters to engines whose results contain this ref.

### WR-05: MCP Search Tool Rounds Score After Service Calculates Full Precision

**Files modified:** `backend/src/dotmd/mcp_server.py`  
**Commit:** 57a8b1e  
**Applied fix:** Removed premature rounding of fused_score when reconstructing SearchCandidate for MCP output. The score now retains full precision throughout the pipeline; JSON serialization can handle rounding at output time if needed.

### WR-06: Misleading Parameter Names Hide Actual Types

**Files modified:** `backend/src/dotmd/search/fusion.py`  
**Commit:** 2c7c802  
**Applied fix:** Clarified parameter names in `build_candidates()`: renamed loop variable from misleading 'ref' to 'chunk_id', updated docstring comments, and renamed internal variable to 'chunk_lookup_id' where both values coexist. The function processes chunk_ids from metadata store lookups, not refs from provenance records.

---

_Fixed: 2026-05-09T21:45:00Z_  
_Fixer: Claude (gsd-code-fixer)_  
_Iteration: 1_
