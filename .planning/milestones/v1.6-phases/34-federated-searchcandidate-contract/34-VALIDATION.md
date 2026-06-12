---
phase: 34
slug: federated-searchcandidate-contract
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-08
last_audited: 2026-05-10
---

# Phase 34 - Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | pytest, `pytest-asyncio` for fan-out tests |
| Config file | `backend/pyproject.toml` |
| Quick run command | `cd backend && uv run pytest tests/core/test_search_candidate.py tests/search/test_fusion.py tests/search/test_federated.py -q` |
| Full suite command | `cd backend && uv run pytest tests/core/test_search_candidate.py tests/search/test_fusion.py tests/search/test_federated.py tests/api/test_service_search.py tests/ingestion/test_telegram_provider.py tests/ingestion/test_telegram_ingestion.py tests/mcp/test_mcp_search_envelope.py -q` |
| Static check command | `cd backend && uv run pyright src/dotmd/core/models.py src/dotmd/search/fusion.py src/dotmd/search/federated.py src/dotmd/api/service.py src/dotmd/mcp_server.py src/dotmd/ingestion/telegram_provider.py src/dotmd/ingestion/source_lifecycle.py tests/core/test_search_candidate.py tests/search/test_fusion.py tests/search/test_federated.py tests/api/test_service_search.py tests/ingestion/test_telegram_provider.py tests/ingestion/test_telegram_ingestion.py tests/mcp/test_mcp_search_envelope.py` |
| Estimated runtime | ~20s targeted; ~90s full search-related set |
| Container smoke | `docker exec -i dotmd dotmd mcp` + scripted MCP `search` tool call (Phase verification only) |

## Sampling Rate

- After every task commit: run the targeted test file(s) for the
  files_modified list (~5s per task).
- After each plan completion: run the quick run command + scoped pyright on
  modified files. Max latency between code change and feedback: one task
  commit.
- Before `gsd-verify-work`: run the full suite command, scoped pyright across
  all phase files, and one `docker compose restart dotmd` smoke test calling
  MCP `search` to confirm the envelope round-trip works against the live
  service.
- Phase verification adds: end-to-end `read(ref)` against a live federated
  Telegram ref through the daemon socket (Plan 03 only).

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 34-01-01 | 01 | 1 | SEARCH-01, SEARCH-02 | T-34-01 | `SearchCandidate` Pydantic model rejects extra fields and freezes after construction; required fields enforced. | unit | `cd backend && uv run pytest tests/core/test_search_candidate.py -q` | yes | covered |
| 34-01-02 | 01 | 1 | SEARCH-01, SEARCH-02 | T-34-01 | Removing `SearchResult` produces zero residual references in production code; clean break per D-01. | unit + static | `cd backend && uv run pytest tests/core/test_search_candidate.py tests/search/test_fusion.py -q && rg -n 'class SearchResult\b' backend/src && rg -n 'from dotmd\.core\.models import.*SearchResult' backend/` | yes | covered |
| 34-01-03 | 01 | 1 | SEARCH-01, SEARCH-03 | T-34-02 | Fusion math unchanged when key migrates to ref; identical RRF score for equivalent ranked input. | unit | `cd backend && uv run pytest tests/search/test_fusion.py -q` | yes | covered |
| 34-01-04 | 01 | 1 | SEARCH-01, SEARCH-02 | T-34-03 | Local engine outputs are hydrated chunk_id → ref BEFORE fusion using the existing batch provenance call; per-engine `engine_scores` only populated for engines that returned the ref. | unit | `cd backend && uv run pytest tests/search/test_fusion.py tests/api/test_service_search.py::test_local_only_search_returns_searchcandidate -q` | yes | covered |
| 34-02-01 | 02 | 2 | SEARCH-01, SEARCH-03 | T-34-04 | `SearchResponse` and `SourceStatus` are forbid-extras Pydantic models; envelope shape stable. | unit | `cd backend && uv run pytest tests/core/test_search_candidate.py::test_search_response_envelope -q` | yes | covered |
| 34-02-02 | 02 | 2 | SEARCH-01, SEARCH-03 | T-34-05 | Federated fan-out runs in parallel; one slow source does not block the response beyond the configured per-source soft timeout. | unit + integration | `cd backend && uv run pytest tests/search/test_federated.py::test_soft_timeout_does_not_block_response -q` | yes | covered |
| 34-02-03 | 02 | 2 | SEARCH-01, SEARCH-03 | T-34-06 | Errored / timed-out sources soft-skip with attributed reason; local engines unaffected. | integration | `cd backend && uv run pytest tests/search/test_federated.py::test_source_error_soft_skip_does_not_break_query tests/search/test_federated.py::test_source_status_attributes_each_engine -q` | yes | covered |
| 34-02-04 | 02 | 2 | SEARCH-01, SEARCH-03 | T-34-07 | Federated rank participates in RRF identically to local engine rank; provider-native scores never directly compared. | unit | `cd backend && uv run pytest tests/search/test_fusion.py::test_federated_rank_parity -q` | yes | covered |
| 34-02-05 | 02 | 2 | SEARCH-01 | T-34-08 | Lifecycle bundle is built once at service init and reused; mock asserts no per-request rebuild. | unit | `cd backend && uv run pytest tests/api/test_service_search.py::test_lifecycle_bundles_built_once -q` | yes | covered |
| 34-02-06 | 02 | 2 | SEARCH-01, SEARCH-03 | T-34-09 | MCP `search` tool returns `SearchEnvelope` with `results` and `source_status`; output schema validates. | integration | `cd backend && uv run pytest tests/mcp/test_mcp_search_envelope.py -q` | yes | covered |
| 34-03-01 | 03 | 3 | SEARCH-04 | T-34-10 | `TelegramApplicationSourceProvider.search_native` returns ref-shaped `SearchCandidate` list given a fake daemon `search_messages` response. | unit | `cd backend && uv run pytest tests/ingestion/test_telegram_provider.py::test_search_native_returns_searchcandidate_list -q` | yes | covered |
| 34-03-02 | 03 | 3 | SEARCH-04 | T-34-11 | `UnixSocketTelegramSourceClient.search_messages` issues a `search_messages` daemon request shaped like other daemon methods; protocol covers it. | unit | `cd backend && uv run pytest tests/ingestion/test_telegram_provider.py::test_unix_socket_search_messages_request_shape -q` | yes | covered |
| 34-03-03 | 03 | 3 | SEARCH-04 | T-34-12 | `read(ref)` and `drill(ref)` for a federated-only Telegram ref route through provider `read_unit_window` (NOT through local store); never raise "no chunks". | integration | `cd backend && uv run pytest tests/ingestion/test_telegram_ingestion.py::test_federated_only_message_round_trip -q` | yes | covered |
| 34-03-04 | 03 | 3 | SEARCH-04 | T-34-13 | When daemon socket is unreachable, `read(ref)` raises `RuntimeError` with provider-attributed message; same provider attribution as `source_status` in search. | integration | `cd backend && uv run pytest tests/ingestion/test_telegram_ingestion.py::test_federated_read_provider_down_attribution -q` | yes | covered |
| 34-03-05 | 03 | 3 | SEARCH-01, SEARCH-04 | T-34-14 | `service.search()` end-to-end fan-out includes `tg:fts` engine when Telegram lifecycle bundle has `FEDERATED_SEARCH` capability and `search_native`. | integration | `cd backend && uv run pytest tests/api/test_service_search.py::test_telegram_federated_engine_participates -q` | yes | covered |
| 34-03-06 | 03 | 3 | SEARCH-04 | T-34-15 | `can_materialize=False` for every Phase 34 candidate; manual sweep + assertion test. | unit | `cd backend && uv run pytest tests/api/test_service_search.py::test_phase_34_candidates_never_materializable -q` | yes | covered |
| 34-03-07 | 03 | 3 | SEARCH-04 | T-34-16 | Live container smoke: MCP `search` for a known Telegram FTS query returns a Telegram ref; `read(ref)` returns daemon-sourced text. | manual / live | `docker exec -i dotmd dotmd mcp` (operator-driven scripted MCP call); marked `autonomous: false` if mcp-telegram daemon `search_messages` endpoint is not yet available. | yes | covered |

## Threat Catalog (cross-reference for `<threat_model>` blocks)

| ID | Description | Mitigation |
|----|-------------|------------|
| T-34-01 | `SearchResult` shape silently re-introduced via alias / shim | Static scan + import scan; Pydantic schema test asserts `SearchResult` symbol absent from `dotmd.core.models`. |
| T-34-02 | RRF math regression when key changes | Unit test pins identical RRF scores for equivalent ranked inputs (chunk_id vs ref). |
| T-34-03 | Per-engine score map drifts (engines that didn't score a ref appear in `engine_scores`) | Test asserts only matching engines populate `engine_scores`. |
| T-34-04 | Envelope models accept extra fields, masking contract drift | `model_config = ConfigDict(extra="forbid", frozen=True)` + Pydantic validation tests. |
| T-34-05 | One stuck federated source blocks the entire response | Per-source `asyncio.wait_for` with config-driven timeout; total wall-time test pins behavior. |
| T-34-06 | Federated source error breaks the query (fail-fast regression) | Test stub raises; assert local results survive; assert `source_status` reports the error. |
| T-34-07 | Provider-native scores leak into RRF as direct comparisons | Test: federated candidate with absurd `source_native_score` cannot rank above a local hit purely on raw score. |
| T-34-08 | Lifecycle bundle rebuild per request inflates latency / TEI cost | Mock asserts `lifecycle_factory.build_if_configured` is called only at service init. |
| T-34-09 | MCP `search` envelope drift breaks Claude Code MCP client | Integration test calls the MCP tool through `mcp.server.fastmcp` test harness. |
| T-34-10 | Federated candidate refs malformed → `read(ref)` rejects | Unit test pins ref shape `telegram:dialog:<id>:message:<id>` for fake daemon payload. |
| T-34-11 | Daemon socket protocol drift (new method missing from protocol) | Protocol covers `search_messages`; pyright catches missing method. |
| T-34-12 | `read(ref)` for federated-only ref hits local store and 404s | Integration test ensures provider path is taken for non-indexed Telegram refs. |
| T-34-13 | Daemon-down read returns ambiguous error, no source attribution | Test asserts error message contains `telegram` and provider context. |
| T-34-14 | Federated engine silently absent because capability discovery is wrong | Integration test asserts `tg:fts` appears in `source_status` of any search response when Telegram bundle is constructible. |
| T-34-15 | Materialization slipped in unintentionally | Sweep test: every candidate `can_materialize is False` regardless of source. |
| T-34-16 | Live MCP call fails because daemon `search_messages` not implemented | Smoke task is `autonomous: false` if daemon-side coordination pending; PR description includes the coordination decision. |

## Wave 0 Requirements

Existing infrastructure is enough. No production container rebuild, database
migration, full reindex, TEI call, FTS rebuild, vector rebuild, or graph
rebuild is required to validate Phase 34. One `docker compose restart dotmd`
at Phase verification (bind-mounted source).

For Plan 03's live smoke task, the mcp-telegram daemon must expose a
`search_messages` socket method. **If it does not yet, that task is marked
`autonomous: false`** and a coordination note links to the open question in
RESEARCH.md.

## Manual-Only Verifications

- Plan 03, Task 34-03-07: live container smoke. Operator-driven scripted MCP
  `search` call against the live `dotmd` container against a known
  Telegram dialog FTS query, then `read(ref)` round-trip against the live
  daemon socket. Required only at Phase verification, not at every task
  commit.

## Validation Audit 2026-05-08

| Metric | Count |
|--------|-------|
| Requirements covered | 4 (SEARCH-01..04) |
| Tasks audited | 16 |
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

All four SEARCH requirements are covered by at least two distinct test
classes (unit + integration). Threats T-34-01 through T-34-16 each have a
named mitigation referenced from a Plan task acceptance criterion.

## Adversarial Gap Audit 2026-05-09

Gaps submitted for adversarial coverage: T-34-14 (GAP-04) and T-34-15 (GAP-05).

Test file: `backend/tests/api/test_phase34_gaps.py`

| Gap | Threat | Test | Result | Classification |
|-----|--------|------|--------|----------------|
| GAP-04 | T-34-14 | `test_telegram_federated_engine_participates` | FAIL — `source_status` contains only `{'filesystem'}`; `tg:fts` absent | BLOCKER |
| GAP-05 | T-34-15 | `test_phase_34_candidates_never_materializable` | PASS — all three candidate construction paths confirm `can_materialize=False` | FILLED |

**GAP-04 root cause:** `search_async()` in `src/dotmd/api/service.py` (line 527–553) contains an
explicit TODO stub: *"For Phase 34, federated fan-out is not yet fully integrated. This stub
returns local results only via the traditional path. TODO: Stage 1-7 full federated
orchestration (Plan 03+)"*. The `self._lifecycle_bundles` dict is populated at init (including
injected `telegram` bundle in the test), but `search_async` never iterates it — fan-out is
skipped entirely. The returned `SearchResponse.source_status` includes only lifecycle init
errors, not federated engine outcomes. Requirement SEARCH-01 (D-08: always-on fan-out for
bundles declaring `FEDERATED_SEARCH`) is unmet by construction.

**Status after 1/3 debug iterations:** Implementation bug confirmed — test assertion is
correct. Weakening the assertion would paper over an unimplemented requirement. ESCALATE.

## Validation Audit 2026-05-10

| Metric | Count |
|--------|-------|
| Gaps found | 5 |
| Resolved | 5 |
| Escalated | 0 |

Gaps resolved: (1) FakeClient `"hits"` key stale after search_native fix; (2) `@pytest.mark.asyncio` unusable without pytest-asyncio — replaced with `@pytest.mark.anyio`; (3) `pytest.raises(ImportError): pass` never raises — replaced with actual import attempt; (4) top_k=3 assertion expected all 5 unsorted results — corrected to top-3 desc-sorted; (5) `service.search.return_value = []` — server route accesses `.candidates`, fixed mock to return `SearchResponse`. Also: `_get_service` now explicitly passes `telegram_daemon_socket=None` to isolate unit tests from the production env var.

All 125 tests pass, 14 skipped (smoke/e2e requiring live stack).

## Audit Evidence

| Check | Expected Result |
|-------|-----------------|
| Focused pytest | Every Per-Task Verification Map row exits 0 after its plan completes. |
| Scoped pyright | `0 errors, 0 warnings, 0 informations` across listed files. |
| `SearchResult` residual scan | `rg -n 'class SearchResult\b' backend/src` returns no matches after Plan 01. |
| Federated fail-fast scan | `rg -n 'FederatedSearchError|fail.fast' backend/src/dotmd/search backend/src/dotmd/api` returns no matches (Airweave fail-fast pattern explicitly rejected). |
| `can_materialize=True` scan in Phase 34 sources | `rg -n 'can_materialize\s*=\s*True' backend/src/dotmd` returns no matches. |
| Live MCP smoke (Plan 03 only) | One `search` call through MCP returns at least one `tg:fts` candidate; one `read(ref)` round-trip returns daemon-sourced text. |
