---
plan: 37-04
title: AIR-02 compatibility report and end-to-end verification
wave: 3
depends_on:
  - 37-02
  - 37-03
files_modified:
  - docs/airweave-compatibility.md
  - backend/tests/test_gmail_bridge.py
  - AGENTS.md
autonomous: true
requirements:
  - AIR-02
  - AIR-03
must_haves:
  goal: >
    docs/airweave-compatibility.md exists and answers all three AIR-02 categories
    based on the ACTUAL implemented code from Plans 37-01 through 37-03 (not
    pre-written prose). Report includes extensibility assessment table, honest
    accounting of GmailSource.search() absence, and SourceAsset deferred mapping.
    AGENTS.md updated with key architectural decisions. Full test suite is green.
    No Airweave-only integration lane exists separate from filesystem/Telegram paths.
  truths:
    - docs/airweave-compatibility.md exists and is non-empty
    - Report was written AFTER inspecting actual implementation files (not pre-written)
    - Report covers "Reusable directly" section with specific class/file references from vendor/
    - Report covers "Requires shims" section citing actual shim implementations in shims.py
    - Report covers "Should be avoided" section (AirweaveSystemMetadata, Vespa, Temporal, etc.)
    - Report documents that GmailSource.search() is not implemented and bridge uses direct API
    - Report documents SourceAsset deferred mapping for GmailAttachmentEntity
    - Report includes extensibility assessment table (generic vs connector-specific per component)
    - Report explicitly states Airweave's runtime/indexing stack is avoided and direct Gmail API is dotMD's concern
    - AGENTS.md updated with vendoring decision, token handling strategy, and generic bridge pattern
    - cd backend && python -m pytest tests/ -x -q exits 0
---

# Plan 37-04: AIR-02 compatibility report and end-to-end verification

## Objective

Produce the `docs/airweave-compatibility.md` structured analysis (AIR-02
deliverable) based on the ACTUAL implemented code, run the full test suite,
and update AGENTS.md with architectural decisions. The report must be written
by inspecting the real implementation — not pre-written prose.

## Context

**Report must be evidence-based, not aspirational.** The executor must read the
actual files in `backend/src/dotmd/vendor/airweave/`, `backend/src/dotmd/ingestion/gmail_provider.py`,
and `backend/src/dotmd/ingestion/source_registry.py` before writing any section.
Template placeholders (`[TBD: filled after implementation]`) should be used for
any finding that requires running the code or observing runtime behavior, then
filled in during this task after inspecting the real implementation.

## Tasks

### Task 1: Write docs/airweave-compatibility.md (evidence-based)

<read_first>
- backend/src/dotmd/vendor/airweave/ — ALL files (inspect actual vendored content)
- backend/src/dotmd/vendor/airweave/VENDOR_VERSION — what was actually vendored
- backend/src/dotmd/vendor/airweave/VENDOR_NOTES.md — per-file modification delta
- backend/src/dotmd/ingestion/gmail_provider.py — BaseConnectorBridge, GmailBridge (actual implementation)
- backend/src/dotmd/ingestion/source_registry.py — gmail_source_descriptor (actual registration)
- backend/src/dotmd/ingestion/source_lifecycle.py — GmailSourceConfig, build branch (actual lifecycle)
- backend/src/dotmd/vendor/airweave/shims.py — actual shim implementations
- .planning/phases/37-airweave-connector-compatibility-spike/37-CONTEXT.md — D-12 questions to answer
- /home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/sources/gmail.py — verify search() absence
- /home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/sources/_base.py — BaseSource contract
</read_first>

<action>
After reading all implementation files, write `docs/airweave-compatibility.md`
with the following structure. Every claim must cite specific files, class names,
or line-level observations from the actual code — no aspirational statements.

Use this template structure, filling each section from the real code:

```markdown
# Airweave Connector Compatibility Analysis

**Phase:** 37 — Airweave connector compatibility spike
**Date:** [actual date]
**Pilot connector:** Gmail (GmailSource from airweave/platform/sources/gmail.py)
**Implementation:** backend/src/dotmd/vendor/airweave/ + backend/src/dotmd/ingestion/gmail_provider.py
**Conclusion:** [one sentence summary of what was learned — fill from actual findings]

---

## 1. Reusable Directly

[For each item: cite the actual class name, source file in the Airweave repo,
and the corresponding file in backend/src/dotmd/vendor/airweave/ where it was placed.
Include any modifications made (from VENDOR_NOTES.md). Do not list something as
"reusable" if it required more than import-rewrite modifications.]

Items to evaluate (fill from actual files):
- BaseSource class and constructor DI pattern
- GmailSource class body (generate_entities, cursor handling)
- GmailThreadEntity, GmailMessageEntity, GmailAttachmentEntity schemas
- AirweaveField pattern and Breadcrumb model
- SyncCursor dict-based cursor state
- @source decorator (as no-op stub)

---

## 2. Requires Shims

[For each shim: cite the actual shim class name in shims.py, what Airweave
expects (from source_base.py), and how the shim satisfies it structurally.
Include the token caching strategy actually implemented.]

Items to cover:
- SourceAuthProvider / GmailOAuthTokenProvider (cite actual implementation: threading.Lock, expires_in-300)
- ContextualLogger / GmailLoggerShim
- AirweaveHttpClient / GmailHttpClientShim
- GmailMessageDeletionEntity → dotMD binding deactivation (future shim, deferred)

---

## 3. Should Be Avoided

[For each item: explain why it conflicts with dotMD's architecture.
Verify that the vendored tree does NOT contain these (grep to confirm).]

Items to cover:
- AirweaveSystemMetadata (embedding, chunk_index, sync_id — conflicts with dotMD's own)
- Vespa / Temporal / FileService (in airweave.domains, not vendored)
- AccessControl / supports_access_control (multi-tenant, dotMD is single-user)
- AirweaveHttpClient rate limiter (Redis-backed multi-tenant, not needed)

---

## 4. Key Finding: GmailSource.search() Is Not Implemented

[Verify this by actually reading the file. Cite the exact location of the abstract
stub in BaseSource and confirm GmailSource does not override it. State what this
means for connectors without search() vs connectors with search().]

Specifically document:
- Where search() is defined in BaseSource (file + method signature)
- Confirm GmailSource does NOT override it (grep result)
- What this means for the generic bridge: direct API search is the fallback
- How to check a new connector: `grep "async def search" platform/sources/<name>.py`
- The @source decorator's federated_search=True flag as the indicator

---

## 5. Generic Bridge: BaseConnectorBridge ABC (D-03)

[Cite the actual BaseConnectorBridge class from gmail_provider.py.
Describe the three abstract methods and what they guarantee.
Explicitly state that D-03 is satisfied: the bridge IS generic — Gmail is
one implementation. The "bridge" in the sense of D-03 is the ABC + protocol,
not the Gmail-specific API calls.]

Also explicitly state:
- "Airweave's runtime/indexing stack (Vespa, Temporal, Celery, Redis) is NOT
  used. Direct Gmail API search is a dotMD provider concern, implemented in
  GmailBridge.search_native(). This is not Airweave compatibility — it is
  dotMD's own Gmail integration using Airweave's entity schemas as a reference."
- This is the honest characterization per OpenCode's suggestion.

---

## 6. SourceAsset Deferred (GmailAttachmentEntity)

[Fill the mapping table from actual GmailAttachmentEntity fields in entities_gmail.py:]

| GmailAttachmentEntity field | Future SourceAsset field | Notes |
|----------------------------|--------------------------|-------|
| attachment_id              | asset_ref                | unique per message |
| filename                   | display_name             |       |
| mime_type                  | media_type               |       |
| size                       | size_bytes               |       |
| data (base64)              | [via FileService equiv]  | deferred |

Status: Deferred per D-11. No SourceAsset model added to models.py in this phase.

---

## 7. Generic Bridge Extensibility Assessment

[Fill this table from the actual gmail_provider.py implementation:]

| Component | Generic/Specific | Reuse for 2nd connector | Notes |
|-----------|-----------------|------------------------|-------|
| BaseConnectorBridge ABC | Generic | Yes — implement the ABC | 3 abstract methods |
| to_search_candidate() | Generic | Yes — override with connector mapping | maps entity_fields → SearchCandidate |
| GmailBridge.search_native() | Gmail-specific | No — implement per connector | direct Gmail API calls |
| GmailBridge.read_unit_window() | Gmail-specific | No — implement per connector | Gmail message fetch + MIME decode |
| MIME decode helpers | Gmail-specific | Partial — other email connectors | multipart/base64url logic |
| SourceDescriptor registration | Generic pattern | Yes — copy descriptor structure | ~30 lines per connector |
| GmailSourceConfig / lifecycle | Generic pattern | Yes — copy config structure | ~20 lines per connector |
| DI shims (logger, http, auth) | Generic | Yes — reuse shims | GmailLoggerShim reusable; GmailOAuthTokenProvider Gmail-specific |

Estimated effort for a second connector (e.g., Notion, GitHub):
- If connector implements search(): ~80 lines (descriptor + config + thin bridge subclass)
- If connector lacks search(): ~180 lines (above + direct API search implementation)

---

## 8. AIR-03 Compliance

[Verify from actual source_registry.py and source_lifecycle.py that Gmail
uses the same code path as filesystem and telegram. Cite specific function
names and the structure of build() branches.]

Checklist (fill from actual code):
- [ ] gmail_source_descriptor() in source_registry.py alongside filesystem_ and telegram_
- [ ] SourceRuntimeFactory.build("gmail") branch in source_lifecycle.py
- [ ] DotMDService._build_federated_bundles() picks up Gmail via build_if_configured()
- [ ] No Gmail-specific code in the fan-out loop
- [ ] grep confirms no direct `from airweave` imports outside vendor/
```

After reading all files, replace all template brackets with actual content.
Do not publish template placeholders in the final document — every section
must be filled with real observations from the code.
</action>

<acceptance_criteria>
- `test -f docs/airweave-compatibility.md` exits 0
- `wc -l docs/airweave-compatibility.md` shows > 80 lines
- Report contains "Reusable directly" section with specific class names
- Report contains "Requires shims" section citing GmailOAuthTokenProvider with threading.Lock and expires_in-300
- Report contains "Should be avoided" section
- Report contains GmailSource.search() finding with file/line citation
- Report contains BaseConnectorBridge ABC section (D-03 compliance)
- Report contains SourceAsset deferred mapping table
- Report contains extensibility assessment table with generic/specific classification
- Report explicitly states Airweave runtime/indexing stack is avoided and direct Gmail API is dotMD's concern
- No unreplaced template placeholders ([TBD: ...]) remain in the final document
</acceptance_criteria>

### Task 2: Update AGENTS.md with architectural decisions

<read_first>
- AGENTS.md — current project AGENTS.md
- backend/src/dotmd/vendor/airweave/VENDOR_NOTES.md (just created)
- backend/src/dotmd/ingestion/gmail_provider.py — BaseConnectorBridge location
</read_first>

<action>
Update the project `AGENTS.md` (at repo root, not ~/AGENTS.md) to add a section
documenting the Phase 37 architectural decisions. Add under the "What Changed From
Upstream" section or create a new "Architecture Decisions" subsection:

```markdown
## Phase 37: Airweave Connector Compatibility

**Decision: vendored Airweave platform slice**
Airweave package not pip-installed (pulls in temporalio, redis, celery, sqlalchemy).
Only 6 platform files vendored into `backend/src/dotmd/vendor/airweave/`.
See `VENDOR_VERSION` for source tracking.

**Decision: direct Gmail API search (not GmailSource.search())**
GmailSource.search() is not implemented in Airweave. Gmail bridge calls
Gmail API directly. Future connectors: check for search() before wrapping.

**Decision: BaseConnectorBridge ABC (D-03 generic bridge)**
`backend/src/dotmd/ingestion/gmail_provider.py` — abstract methods:
search_native(), read_unit_window(), to_search_candidate().
GmailBridge is the first implementation.

**Decision: OAuth token caching with threading.Lock**
GmailOAuthTokenProvider uses margin-based expiry (expires_in - 300) and
threading.Lock to serialize concurrent refresh calls. Located in shims.py.

**Decision: Gmail as federated-only (no local indexing)**
Gmail participates via _merge_with_federated_quota (quota-based slots).
source_native_score=None is safe — federated candidates bypass RRF.
```
</action>

<acceptance_criteria>
- AGENTS.md contains a Phase 37 section with the vendoring decision
- AGENTS.md mentions BaseConnectorBridge location
- AGENTS.md mentions threading.Lock token caching decision
- Existing AGENTS.md content is preserved (no deletions)
</acceptance_criteria>

### Task 3: Full test suite verification

<read_first>
- backend/tests/test_gmail_bridge.py — all tests from Plans 37-02 and 37-03
- backend/tests/test_vendor_airweave_import.py — smoke tests from Plan 37-01
</read_first>

<action>
Run the full test suite. Fix any failures found.

Common failure modes to check:
1. Import chain pulling in an Airweave module that is not vendored
2. `SourceConfig` type union in `source_lifecycle.py` not updated to include `GmailSourceConfig`
3. `default_source_registry()` missing the `gmail_source_descriptor()` registration
4. `GmailOAuthTokenProvider.get_token()` called in tests without mocking the httpx.post call
5. `SearchCandidate` validation error if `snippet` is missing (Gmail API may return
   empty snippet for draft messages — ensure `snippet = response.get("snippet") or ""`
   so empty string is used, not None)
6. `BaseConnectorBridge` not importable from `gmail_provider` (missing ABC import or
   wrong module structure)
7. `SourceAuthError` / `SourceTemporaryUnavailable` not importable — if they were
   defined locally in gmail_provider.py, tests that import them must import from there

After fixing any failures, confirm the full suite passes.
</action>

<acceptance_criteria>
- `cd backend && python -m pytest tests/ -x -q` exits 0
- `cd backend && python -m pytest tests/test_gmail_bridge.py tests/test_vendor_airweave_import.py -v` exits 0
- No regressions in existing tests (filesystem, Telegram, search pipeline tests)
</acceptance_criteria>

### Task 4: Verify AIR-03 — no Airweave-only lane

<read_first>
- backend/src/dotmd/ingestion/source_registry.py — all descriptors
- backend/src/dotmd/ingestion/source_lifecycle.py — all build branches
- backend/src/dotmd/api/service.py — _build_federated_bundles()
</read_first>

<action>
Perform a structural check that Gmail follows the same code path as Telegram:

1. `source_registry.py` exports: `filesystem_source_descriptor`, `telegram_source_descriptor`,
   `gmail_source_descriptor`, `default_source_registry` — all in the same module, same pattern.

2. `source_lifecycle.py` `SourceRuntimeFactory.build()`: three branches
   (`filesystem`, `telegram`, `gmail`), all following the same structure:
   - validate config type
   - get access via credential provider
   - construct provider
   - return `SourceRuntimeBundle`

3. `service.py` `_build_federated_bundles()`: iterates `registry.list()` and calls
   `build_if_configured(namespace)` — no special Gmail-specific code in the loop.
   Gmail bundle is picked up automatically when configured, same as Telegram.

4. Check that no file in `backend/src/dotmd/` (outside of `vendor/`) directly imports
   from `airweave.*` (the full Airweave package):
   ```
   grep -r "^from airweave\|^import airweave" backend/src/dotmd/ --include="*.py"
   ```
   Expected: no output (all Airweave imports go through `dotmd.vendor.airweave.*`).
</action>

<acceptance_criteria>
- `grep -r "^from airweave\|^import airweave" backend/src/dotmd/ --include="*.py"` returns no matches
- `SourceRuntimeFactory.build()` has filesystem, telegram, gmail branches in the same method
- `_build_federated_bundles()` has no Gmail-specific conditional logic
- source_registry.py, source_lifecycle.py, service.py changes are symmetric with the Telegram pattern
</acceptance_criteria>

## Verification

```bash
# Full test suite
cd /home/j2h4u/repos/j2h4u/dotmd/backend
python -m pytest tests/ -x -q

# Compatibility report exists and is filled
test -f /home/j2h4u/repos/j2h4u/dotmd/docs/airweave-compatibility.md && echo "OK"
grep -c "TBD:" /home/j2h4u/repos/j2h4u/dotmd/docs/airweave-compatibility.md || echo "No TBD placeholders: OK"

# No direct airweave imports outside vendor
grep -r "^from airweave\|^import airweave" src/dotmd/ --include="*.py" && echo "FAIL" || echo "OK"

# Registry has all three descriptors
python -c "
from dotmd.ingestion.source_registry import default_source_registry
r = default_source_registry()
assert r.get('filesystem') is not None
assert r.get('telegram') is not None
assert r.get('gmail') is not None
print('All three descriptors registered: OK')
"

# BaseConnectorBridge is abstract, GmailBridge implements it
python -c "
import inspect
from dotmd.ingestion.gmail_provider import BaseConnectorBridge, GmailBridge
assert inspect.isabstract(BaseConnectorBridge)
assert issubclass(GmailBridge, BaseConnectorBridge)
print('BaseConnectorBridge ABC contract: OK')
"
```

## Phase Completion

When this plan passes verification, Phase 37 deliverables are complete:
- AIR-01: `BaseConnectorBridge(ABC)` + `GmailBridge` bridges Airweave-style connector to dotMD contracts
- AIR-02: `docs/airweave-compatibility.md` documents reusable/shim/avoid analysis (evidence-based)
- AIR-03: Gmail uses same registry/lifecycle/search contracts as filesystem and Telegram
