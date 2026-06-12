---
phase: 34-federated-searchcandidate-contract
reviewed: 2026-05-09T00:00:00Z
depth: standard
files_reviewed: 13
files_reviewed_list:
  - backend/src/dotmd/api/service.py
  - backend/src/dotmd/core/models.py
  - backend/src/dotmd/ingestion/telegram_provider.py
  - backend/src/dotmd/mcp_server.py
  - backend/src/dotmd/search/fusion.py
  - backend/tests/api/test_service_search.py
  - backend/tests/core/test_search_candidate.py
  - backend/tests/ingestion/test_telegram_ingestion.py
  - backend/tests/ingestion/test_telegram_provider.py
  - backend/tests/mcp/test_mcp_search_envelope.py
  - backend/tests/test_fusion.py
  - docs/mcp-telegram-source-contract.md
  - docs/source-adapter-architecture.md
findings:
  critical: 2
  warning: 6
  info: 3
  total: 11
status: issues_found
---

# Phase 34: Code Review Report

**Reviewed:** 2026-05-09T00:00:00Z  
**Depth:** standard  
**Files Reviewed:** 13  
**Status:** issues_found

## Summary

Phase 34 adds federated search support via SearchCandidate contract and Telegram provider integration. While the architecture is sound, the implementation has critical bugs in error handling and attribute mutation, plus several quality issues that degrade maintainability and observability. The frozen model contract has a documentation gap regarding intentional shallow-freeze semantics. All critical issues must be fixed before production deployment.

## Critical Issues

### CR-01: Shallow-Frozen Container Mutation Breaks Immutability Contract

**File:** `backend/src/dotmd/core/models.py:415`

**Issue:** SearchCandidate uses `frozen=True` to prevent attribute rebinding, but Pydantic's frozen implementation is shallow: attribute assignment is blocked, but list/dict content mutation succeeds silently. Test line 160 (`candidate.matched_engines.append("keyword")`) demonstrates this explicitly. This contradicts the semantic expectation of a frozen model and creates a vector for subtle data corruption.

The model docstring claims "shallow-frozen by Pydantic's frozen=True: ... callers must not mutate after construction" but this is not enforced—it's merely documented as caller responsibility.

**Fix:**

Convert matched_engines to tuple for true immutability:

```python
class SearchCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    
    matched_engines: tuple[str, ...] = Field(default_factory=tuple)
    # ... rest unchanged
```

---

### CR-02: Unhandled Exception Type Coercion in telegram_provider.py Risks Silent Failures

**File:** `backend/src/dotmd/ingestion/telegram_provider.py:600-601`

**Issue:** In `_read_telegram_message`, exceptions are re-raised with type coercion:

```python
except Exception as e:
    raise type(e)(f"Telegram provider error: {e}") from e
```

This fails if the exception's `__init__` has strict signature validation. Example: `RuntimeError("msg1", "msg2")` cannot be called as `RuntimeError("text")` on some exception types.

**Fix:**

```python
except Exception as e:
    raise RuntimeError(f"Telegram provider error: {e}") from e
```

---

## Warnings

### WR-01: Inconsistent Low-Signal Text Detection Has Logic Bug

**File:** `backend/src/dotmd/ingestion/telegram_provider.py:400-412`

**Issue:** The final condition uses AND instead of OR:

```python
return (
    not any(ch.isalnum() for ch in stripped)
    and any(unicodedata.category(ch).startswith("S") for ch in stripped)
)
```

Symbol-only text like "😀😀😀" will fail the first part and never reach the AND, so symbols are never detected as low-signal. Should be OR.

**Fix:**

```python
return (
    not any(ch.isalnum() for ch in stripped)
    or any(unicodedata.category(ch).startswith("S") for ch in stripped)
)
```

---

### WR-02: Missing Null Check Before String Operations in service.py

**File:** `backend/src/dotmd/api/service.py:826-827`

**Issue:** Ref is used without null validation:

```python
if ref.startswith("telegram:"):
```

If ref is None, this raises AttributeError. Add defensive check.

**Fix:**

```python
if isinstance(ref, str) and ref.startswith("telegram:"):
```

---

### WR-03: Test Fixture Accepts but Ignores Namespace Parameter

**File:** `backend/tests/api/test_service_search.py:29-47`

**Issue:** `build_if_configured` accepts namespace but doesn't validate it; hardcodes Telegram behavior regardless. Will silently fail on unknown namespaces in the require() call.

**Fix:**

```python
def build_if_configured(self, namespace: str) -> object | None:
    self.calls.append(namespace)
    if namespace != "telegram" or self.provider is None:
        return None
    return SourceRuntimeBundle(...)
```

---

### WR-04: Missing Engine Attribution in Federated Candidate Building

**File:** `backend/src/dotmd/api/service.py:920`

**Issue:** Federated candidates get `matched_engines=list(per_engine_ref.keys())`, which is ALL engines, not just engines that scored this candidate.

**Fix:**

```python
matched_engines = [
    engine_name
    for engine_name, refs in per_engine_ref.items()
    if any(eng_ref == ref for eng_ref, _ in refs)
],
```

---

### WR-05: MCP Search Tool Rounds Score After Service Calculates Full Precision

**File:** `backend/src/dotmd/mcp_server.py:819`

**Issue:** Score is rounded for MCP output by creating a new SearchCandidate with mutated fused_score. This loses precision if the candidate is used downstream.

**Fix:**

Don't create a new SearchCandidate; let Pydantic JSON serializer handle rounding if needed, or return the full-precision value and let the MCP client round.

---

### WR-06: Misleading Parameter Names Hide Actual Types

**File:** `backend/src/dotmd/search/fusion.py:353-376`

**Issue:** Parameter named 'ref' but comment says it's actually chunk_id:

```python
chunk_id = ref  # The 'ref' passed in is actually the chunk_id
```

Confusing and error-prone. Rename for clarity.

**Fix:**

```python
def build_candidates(
    fused: list[tuple[str, float]],  # (chunk_id, fused_score) pairs, not refs
    per_engine: dict[str, list[tuple[str, float]]],  # (chunk_id, score)
    ...
) -> list[SearchCandidate]:
    for chunk_id, fused_score in fused[:top_k]:
        ...
```

---

## Info

### IN-01: Error Message Inconsistency in _parse_telegram_message_ref

**File:** `backend/src/dotmd/api/service.py:125-139`

**Issue:** Function-specific error message should clarify it parses Telegram refs specifically, not generic refs.

**Fix:**

```python
if not ref.startswith(TELEGRAM_REF_PREFIX):
    raise ValueError(f"Not a Telegram message ref: {ref}")
```

---

### IN-02: Magic Number Lacks Documentation

**File:** `backend/src/dotmd/api/service.py:44`

**Issue:** `ACTIVE_FILTER_OVERFETCH_FACTOR = 5` has no explanation.

**Fix:**

```python
# Overfetch factor: request 5x top_k from engines since inactive retention hides results.
# Balances latency vs. coverage (empirically calibrated).
ACTIVE_FILTER_OVERFETCH_FACTOR = 5
```

---

### IN-03: Hardcoded Window Sizes Should Be Named Constants

**File:** `backend/src/dotmd/api/service.py:1537-1544`

**Issue:** Values 50 and 5 are hardcoded without explanation.

**Fix:**

```python
TELEGRAM_WINDOW_BEFORE_MAX = 50
TELEGRAM_WINDOW_AFTER_DEFAULT = 5
TELEGRAM_WINDOW_AFTER_MAX = 50

def _telegram_window_sizes(self, start: int, end: int | None) -> tuple[int, int]:
    before = max(0, min(start, TELEGRAM_WINDOW_BEFORE_MAX))
    after = TELEGRAM_WINDOW_AFTER_DEFAULT if end is None else max(0, min(end, TELEGRAM_WINDOW_AFTER_MAX))
    return before, after
```

---

## Recommendations

**Priority 1 (Critical):**
1. Fix CR-01: Use tuple for matched_engines
2. Fix CR-02: Use explicit RuntimeError instead of type coercion

**Priority 2 (High):**
3. Fix WR-01: AND → OR in low-signal detection
4. Fix WR-02: Add isinstance check for ref
5. Fix WR-04: Fix per-candidate engine attribution

**Priority 3 (Medium):**
6. Fix WR-03, WR-05, WR-06, IN-01, IN-02, IN-03

---

_Reviewed: 2026-05-09T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
