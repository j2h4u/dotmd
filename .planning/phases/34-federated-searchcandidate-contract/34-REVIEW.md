---
phase: "34"
reviewed: "2026-05-09T00:00:00Z"
depth: standard
files_reviewed: 13
files_reviewed_list:
  - backend/src/dotmd/core/models.py
  - backend/src/dotmd/search/fusion.py
  - backend/src/dotmd/api/service.py
  - backend/src/dotmd/mcp_server.py
  - backend/src/dotmd/ingestion/telegram_provider.py
  - backend/tests/core/test_search_candidate.py
  - backend/tests/test_fusion.py
  - backend/tests/api/test_service_search.py
  - backend/tests/mcp/test_mcp_search_envelope.py
  - backend/tests/ingestion/test_telegram_provider.py
  - backend/tests/ingestion/test_telegram_ingestion.py
  - docs/source-adapter-architecture.md
  - docs/mcp-telegram-source-contract.md
findings:
  critical: 4
  warning: 6
  info: 5
  total: 15
status: issues_found
---

# Phase 34: Code Review Report

**Reviewed:** 2026-05-09T00:00:00Z
**Depth:** standard
**Files Reviewed:** 13
**Status:** issues_found

## Summary

Phase 34 implements federated search infrastructure with SearchCandidate envelope, ref-keyed fusion, and Telegram provider integration. The work demonstrates solid architecture and comprehensive testing, but contains **4 critical bugs** and **6 warnings** that undermine search correctness, retrieval routing, and error handling.

**Critical issues:**
1. `build_candidates()` hardcodes `descriptor_key="filesystem-mnt"` — breaks multi-filesystem setups and incorrect for non-filesystem sources
2. `build_candidates()` hardcodes `retrieval_kind="semantic"` — erases actual engine attribution (keyword, graph_direct candidates lose identity)
3. `_read_telegram_message()` exception handling loses exception type information — RuntimeError becomes wrong exception class
4. Telegram ref parsing in `_resolve_telegram_read_path()` silently returns FEDERATED_ONLY on parse error — masks bad refs as valid federation fallback

**Impact:** Search result metadata is fundamentally incorrect; keyword-only results are misattributed; error handling is fragile; Telegram read routing is ambiguous.

---

## Critical Issues

### CR-01: `build_candidates()` Hardcodes `descriptor_key="filesystem-mnt"` — All Local Candidates Wrong

**File:** `backend/src/dotmd/search/fusion.py:378`

**Issue:** 
```python
descriptor_key="filesystem-mnt",  # Local chunks are always filesystem
```

This hardcoding breaks the contract:
- A system with multiple filesystem sources (e.g., `/mnt` and `/srv`) cannot distinguish results
- Cycle-2 HIGH-1 fix (`descriptor_key` required field) is circumvented — fusion layer ignores real descriptor metadata
- All 11 contract tests in `test_search_candidate.py` pass, but they DON'T test `build_candidates()` directly
- `test_search_candidate_descriptor_key_distinguishes_sources` proves two candidates with same ref but different `descriptor_key` must be distinguishable — fusion.py violates this invariant

**Root Cause:** `build_candidates()` takes only `active_provenance_map: dict[str, ChunkProvenance]` but `ChunkProvenance` has no `descriptor_key` field. The function cannot recover the original source descriptor without additional lookup.

**Fix:**
Add `descriptor_key_map: dict[str, str] | None = None` parameter to `build_candidates()`. In service layer, pre-build this map by resolving each ref to its source descriptor before calling fusion:

```python
# In service._execute_search() before build_candidates call:
descriptor_key_map: dict[str, str] = {}
for ref, _ in fused:
    doc = metadata_store.get_source_document_by_ref(ref)
    if doc:
        descriptor_key_map[ref] = f"{doc.namespace}-{doc.source_uri.split('/')[-1]}"

# In fusion.build_candidates():
def build_candidates(..., descriptor_key_map: dict[str, str] | None = None):
    ...
    descriptor_key = descriptor_key_map.get(provenance.ref, "unknown")
```

Alternatively, store `descriptor_key` in `ChunkProvenance` at index time.

**Severity:** BLOCKER — Contract invariant violated; search result identity broken.

---

### CR-02: `build_candidates()` Hardcodes `retrieval_kind="semantic"` — Engine Attribution Lost

**File:** `backend/src/dotmd/search/fusion.py:380`

**Issue:**
```python
retrieval_kind="semantic",  # Will be updated by service layer
```

This hardcoding erases engine attribution:
- A keyword-only match gets `retrieval_kind="semantic"` — false attribution
- `matched_engines` is correctly populated (line 371), but `retrieval_kind` is always "semantic"
- Contract guarantees SearchCandidate.retrieval_kind reflects the actual engine ("keyword", "graph_direct", etc.)
- Comment says "will be updated by service layer" — but service._execute_search() calls `build_candidates()` and **returns those candidates directly** (line 711). No post-processing updates retrieval_kind.

**Root Cause:** Same as CR-01 — fusion layer cannot access engine-to-retrieval_kind mapping without external data. The function receives `per_engine` (dict[str, list[tuple[str, float]]]) but has no way to map engine names to retrieval_kind values.

**Fix:**
Add `engine_to_retrieval_kind: dict[str, str] | None = None` parameter:

```python
def build_candidates(..., engine_to_retrieval_kind: dict[str, str] | None = None):
    ...
    # Derive retrieval_kind from matched engines
    if matched_engines:
        retrieval_kind_val = engine_to_retrieval_kind.get(matched_engines[0], "unknown")
    else:
        retrieval_kind_val = "unknown"
    
    SearchCandidate(..., retrieval_kind=retrieval_kind_val, ...)
```

In service._execute_search(), pre-build the mapping:
```python
engine_to_retrieval_kind = {
    "semantic": "semantic",
    "keyword": "keyword",
    "graph_direct": "graph_direct",
    "tg:fts": "tg:fts",
}
```

**Severity:** BLOCKER — Search result metadata is incorrect; keyword-only candidates are misattributed as semantic.

---

### CR-03: `_read_telegram_message()` Exception Handler Loses Type — `RuntimeError(f"...")` Not Wrapping Correctly

**File:** `backend/src/dotmd/api/service.py:1600-1601`

**Issue:**
```python
except Exception as e:
    raise type(e)(f"Telegram provider error: {e}") from e
```

This pattern re-raises the **same exception type** with a modified message. If `e` is a `TimeoutError`, a new `TimeoutError` is raised. This breaks error handling:

- Comment says "provider-attributed RuntimeError" per D-15, but code raises `type(e)` (could be `TimeoutError`, `ConnectionError`, `OSError`, etc.)
- Callers catching `RuntimeError` will miss these exceptions
- Inconsistent with D-15 spec: "Federated read errors are provider-attributed RuntimeError"
- In `_drill_telegram_message()` (line 1682), same pattern is used

**Root Cause:** Intent was to wrap all provider errors as `RuntimeError` with context. Implementation accidentally preserves original type.

**Fix:**
Change both occurrences to explicitly wrap as RuntimeError:

```python
except Exception as e:
    raise RuntimeError(f"Telegram provider error: {e}") from e
```

**Severity:** BLOCKER — Error handling contract violation; exception types not normalized as documented.

---

### CR-04: `_resolve_telegram_read_path()` Silently Returns FEDERATED_ONLY on Parse Error — Masks Invalid Refs

**File:** `backend/src/dotmd/api/service.py:1476-1479`

**Issue:**
```python
try:
    document_ref, _unit_ref = _parse_telegram_message_ref(ref)
except ValueError:
    return TelegramReadPath.FEDERATED_ONLY  # Silently swallow parse error
```

When `_parse_telegram_message_ref()` raises `ValueError` (malformed ref), the code returns FEDERATED_ONLY and attempts provider fallback:

- A typo like `"telegram:dialog:1:message:xyz"` (non-numeric message_id) silently becomes a federated read attempt
- Provider fails with "unknown ref" (hiding the fact that the *local* parse failed)
- User gets confusing error: "Telegram provider error: unknown ref" instead of "malformed ref"
- Deferred error detection — invalid local refs should fail immediately with clear message

**Root Cause:** Assumes any ValueError means "no local entry, try federation." But ValueError means "malformed ref" — a programmer error, not a legitimate federation path.

**Fix:**
Distinguish between "ref doesn't match expected pattern" (programmer error) and "no local document found" (federation fallback):

```python
def _resolve_telegram_read_path(self, ref: str) -> TelegramReadPath:
    if not _is_telegram_message_ref(ref):
        # Not a Telegram ref at all — immediate failure
        raise ValueError(f"Invalid Telegram message ref format: {ref}")
    
    try:
        document_ref, _unit_ref = _parse_telegram_message_ref(ref)
    except ValueError:
        # Malformed Telegram ref — clear error
        raise ValueError(f"Malformed Telegram message ref: {ref}") from None
    
    # Now check local presence (federation fallback)
    document = self._pipeline.metadata_store.get_source_document("telegram", document_ref)
    if document is None:
        return TelegramReadPath.FEDERATED_ONLY  # Legitimate federation case
    ...
```

**Severity:** BLOCKER — Ref parsing errors silently convert to federation attempts, masking bugs and producing confusing error messages.

---

## Warnings

### WR-01: `build_candidates()` Hardcoded `source_kind="markdown"` — Not Source-Agnostic

**File:** `backend/src/dotmd/search/fusion.py:379`

**Issue:**
```python
source_kind="markdown",
```

Like CR-01 and CR-02, this assumes all local sources are markdown. This breaks the design:
- What if a filesystem source is JSON, YAML, or CSV?
- Future sources added to filesystem (e.g., code files, logs) get wrong source_kind
- Contract specifies `source_kind: str` should be source-aware

**Root Cause:** Same root as CR-01/CR-02 — fusion layer has no access to source metadata.

**Fix:**
Add to `ChunkProvenance` or pass external map (same pattern as descriptor_key and retrieval_kind).

**Severity:** WARNING — Affects future sources; current code only indexes markdown, so impact is deferred.

---

### WR-02: `telegram_provider.search_native()` Derives `can_read` From Callable Check — Runtime Fragile

**File:** `backend/src/dotmd/ingestion/telegram_provider.py:238-240`

**Issue:**
```python
can_read_local = callable(
    getattr(self._client, "read_source_unit_window", None),
)
```

This checks if the client object has a callable `read_source_unit_window` attribute. But:
- If the attribute exists but is broken (raises NotImplementedError), `can_read=True` but reads will fail
- Better to check the provider's declared capabilities via descriptor or test it explicitly
- Cycle-2 MEDIUM fix (D-13) intended: "can_read derived from runtime provider capability check" — but this check is too shallow

**Root Cause:** No formal capability registry; relying on duck-typing.

**Fix:**
Better approach:
```python
# Via descriptor capabilities
capabilities = self._client.describe_source().get("capabilities", [])
can_read_local = "read_unit_window" in capabilities

# Or explicit test at init time
can_read_local = True
try:
    self._client.read_source_unit_window("test:ref", 0, 0)
except NotImplementedError:
    can_read_local = False
except:
    pass  # Other errors are transient
```

**Severity:** WARNING — Potential false positive (can_read=True when reads will fail).

---

### WR-03: `service.search_async()` Stub Ignores Federated Bundles — Phase 34 Incomplete Orchestration

**File:** `backend/src/dotmd/api/service.py:527-530`

**Issue:**
```python
# For Phase 34, federated fan-out is not yet fully integrated.
# This stub returns local results only via the traditional path.
# TODO: Stage 1-7 full federated orchestration (Plan 03+)
```

The SUMMARY says "Plan 34-03 delivers end-to-end federated search" with Telegram proof, but `search_async()` is a **stub** that doesn't call the federated orchestration:

- `self._lifecycle_bundles` is built (line 225) but never used in search
- `fanout_federated()` from `dotmd.search.federated` is never called
- Telegram search_native() is never invoked during search
- Phase 34-03 description claims "Full async fan-out composition" is complete, but code shows it's deferred ("Plan 03+")

**Root Cause:** The SUMMARY conflates implementation goals with actual implementation. Stage 1-7 orchestration is deferred; current code is local-only.

**Impact:** Medium — Search results don't include federated sources. But this matches the plan's own scope statement. The SUMMARY is misleading.

**Fix:**
Update SUMMARY to clarify that Phase 34-03 adds the infrastructure and Telegram proof, but full federated result composition is deferred. Or implement the orchestration per the SUMMARY's claims.

**Severity:** WARNING — Scope clarity issue; code matches deferred intent but SUMMARY overstates completion.

---

### WR-04: `_telegram_unit_payload()` Missing Sender Name Fallback — Silent Data Loss

**File:** `backend/src/dotmd/api/service.py:1562-1564`

**Issue:**
```python
"sender_id": metadata.get("sender_id"),
"sender_name": metadata.get("sender_name"),
```

If metadata lacks `sender_name`, the payload includes `"sender_name": None`. During rendering (in MCP or UI), callers must handle None explicitly. Better to provide a fallback:

```python
"sender_name": metadata.get("sender_name") or f"User {metadata.get('sender_id')}",
```

**Severity:** WARNING — Degrades data quality in read results.

---

### WR-05: Exception Wrapping in `_read_telegram_message()` Line 1601 — Message Format Odd

**File:** `backend/src/dotmd/api/service.py:1600-1601`

**Issue:**
```python
except Exception as e:
    raise type(e)(f"Telegram provider error: {e}") from e
```

If the provider raises `RuntimeError("Connection timeout")`, the code produces:
```
RuntimeError("Telegram provider error: Connection timeout")
```

But per D-15, should be:
```
RuntimeError("telegram: Connection timeout")
```

The message format is inconsistent. Use descriptor-namespaced messages:

```python
except Exception as e:
    raise RuntimeError(f"telegram: {e}") from e
```

**Severity:** WARNING — Inconsistent error message format; reduces clarity.

---

### WR-06: `_public_ref_for_provenance()` Special Cases Telegram — Fragile Logic

**File:** `backend/src/dotmd/search/fusion.py:184-188`

**Issue:**
```python
def _public_ref_for_provenance(provenance: ChunkProvenance) -> str:
    if provenance.namespace == "telegram" and len(provenance.source_unit_refs) == 1:
        return f"telegram:{provenance.source_unit_refs[0]}"
    return provenance.ref
```

This special case:
- Assumes Telegram refs have exactly 1 source_unit_ref (fragile heuristic)
- What if a future Telegram chunk spans multiple messages? Logic breaks.
- Better: store the desired public ref directly in provenance, not computed from heuristics

**Root Cause:** Trying to infer shape from data structure instead of storing explicit intent.

**Fix:**
Add `public_ref: str | None` field to `ChunkProvenance`, set at index time. At search time, use it directly:

```python
def _public_ref_for_provenance(provenance: ChunkProvenance) -> str:
    return provenance.public_ref or provenance.ref
```

**Severity:** WARNING — Heuristic-based ref derivation is fragile for future changes.

---

## Info

### IN-01: `SearchCandidate` Frozen-Shallow Semantics Not Enforced at Serialization

**File:** `backend/src/dotmd/core/models.py:416`

**Issue:**
The docstring documents frozen-shallow semantics:
```python
"""Container fields (matched_engines, engine_scores, provider_metadata) are
shallow-frozen by Pydantic's frozen=True: attribute rebinding is rejected,
but container content mutation (list.append, dict assignment) succeeds."""
```

But MCP serialization (JSON) doesn't preserve this invariant:
- When `SearchCandidate` is serialized to JSON and deserialized by an MCP client, `matched_engines` becomes a regular list (not frozen)
- Client code can mutate it freely
- The frozen contract is lost in transit

**Fix:** Document that frozen-shallow guarantees only apply within Python process. MCP clients receive plain JSON; they must not rely on immutability.

**Severity:** INFO — Documentation clarity; architectural boundary.

---

### IN-02: `SearchResponse` Envelope Frozen But Cannot Modify Contents

**File:** `backend/src/dotmd/core/models.py:469-476`

**Issue:**
`SearchResponse` is frozen:
```python
model_config = ConfigDict(extra="forbid", frozen=True)
candidates: list[SearchCandidate] = Field(default_factory=list)
```

So `response.candidates.append(...)` succeeds (shallow freeze), but the appended `SearchCandidate` is also frozen. This is semantically consistent but worth documenting: the envelope is frozen but its contents' contents are also frozen.

**Severity:** INFO — Clarification needed in docstring.

---

### IN-03: `_collect_active_candidate_pool()` Not Shown in Review — Missing 4-Tuple Return Details

**File:** `backend/src/dotmd/api/service.py:590-598`

**Issue:**
The code calls `self._collect_active_candidate_pool()` and unpacks a 4-tuple:
```python
pool, filtered_fused, active_provenance_map, inactive_count = (
    self._collect_active_candidate_pool(...)
)
```

But the function definition is not visible in the reviewed file range. The SUMMARY claims "fixed mocks to return proper 4-tuple structure" (34-01 deviation), but the actual implementation is out of scope.

**Recommendation:** Review `_collect_active_candidate_pool()` in a follow-up to verify the 4-tuple contract is correctly implemented.

**Severity:** INFO — Scope note; not a bug in reviewed code.

---

### IN-04: `test_search_candidate.py` Contract Tests Don't Call `build_candidates()` Directly

**File:** `backend/tests/core/test_search_candidate.py`

**Issue:**
The 11 contract tests construct `SearchCandidate` directly via constructor, but don't test the `build_candidates()` function that actually produces candidates. This means:
- CR-01 and CR-02 bugs (hardcoded descriptor_key, retrieval_kind) are hidden from contract tests
- Service integration tests may catch these, but the contract-level tests don't enforce them

**Fix:** Add tests for `build_candidates()` output shape:
```python
def test_build_candidates_preserves_descriptor_key_from_map():
    # Verify descriptor_key is not hardcoded
    
def test_build_candidates_sets_retrieval_kind_based_on_matched_engines():
    # Verify retrieval_kind matches actual engine
```

**Severity:** INFO — Test coverage gap.

---

### IN-05: `TELEGRAM_PROVIDER_METADATA_KEYS` Whitelist Excludes Many Useful Fields

**File:** `backend/src/dotmd/ingestion/telegram_provider.py:42-48`

**Issue:**
The whitelist is restrictive:
```python
TELEGRAM_PROVIDER_METADATA_KEYS: frozenset[str] = frozenset({
    "dialog_id",
    "message_id",
    "sender",
    "sent_at",
    "dialog_name",
})
```

But the provider includes many other useful fields:
- `sender_id`, `sender_name` (separate from "sender")
- `topic_id`, `topic_title`
- `reply_to_msg_id`
- `edit_date`

These are filtered out. Not a bug, but limits future usefulness of provider_metadata.

**Severity:** INFO — Design note; whitelisting is intentional per D-METADATA-WHITELIST.

---

## Deviations from Spec

### Auto-Fixed During Implementation (Rule 1 — Bugs)

The SUMMARY notes 4 test bugs fixed during execution:
1. Test mocks returning wrong structure for active_provenance_map — fixed (CBD210D)
2. build_candidates using chunk_id instead of ref for SearchCandidate.ref — fixed (CBD210D)
3. test_read_telegram_ref_* expecting ValueError instead of PermissionError — fixed (EA6FAB4)

These are documented and committed. However, **CR-01, CR-02, CR-03, CR-04 are NOT noted as auto-fixes**, suggesting they were not caught during the review process.

---

## Recommendations

### High Priority (Fixes Required Before Deployment)

1. **Fix CR-01:** Add `descriptor_key_map` parameter to `build_candidates()`
2. **Fix CR-02:** Add `engine_to_retrieval_kind` parameter to `build_candidates()`
3. **Fix CR-03:** Change `raise type(e)()` to `raise RuntimeError()` in both read/drill methods
4. **Fix CR-04:** Distinguish parse errors from federation fallback in `_resolve_telegram_read_path()`

### Medium Priority (Before Phase 35)

5. Fix WR-01: Add source_kind to external map or ChunkProvenance
6. Fix WR-02: Improve can_read capability check from callable to declared capability
7. Fix WR-05: Normalize error message format per D-15
8. Fix WR-06: Store public_ref explicitly in ChunkProvenance

### Low Priority (Nice-to-Have)

9. Update SUMMARY to clarify federated orchestration is deferred
10. Add test coverage for `build_candidates()` output
11. Document frozen-shallow semantics at serialization boundary

---

_Reviewed: 2026-05-09T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
