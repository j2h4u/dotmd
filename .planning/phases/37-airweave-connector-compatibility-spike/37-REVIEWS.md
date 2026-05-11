---
phase: 37
reviewers: [codex, opencode]
reviewed_at: 2026-05-11T15:45:00Z
plans_reviewed:
  - 37-01-vendor-airweave-platform-slice-PLAN.md
  - 37-02-gmail-bridge-federated-search-PLAN.md
  - 37-03-gmail-registry-lifecycle-wiring-PLAN.md
  - 37-04-airweave-compatibility-report-and-tests-PLAN.md
---

# Cross-AI Plan Review — Phase 37

<!-- ═══════════════════════════════════════════════════════════════
     CYCLE 1  (2026-05-11T10:16:26Z — plans before threading.Lock /
               BaseConnectorBridge ABC were added)
     ═══════════════════════════════════════════════════════════════ -->

## Cycle 1 — 2026-05-11T10:16:26Z

### Cycle 1 · Codex Review

## Summary

The plans are directionally sound and mostly satisfy Phase 37's goal: prove Airweave connector compatibility through Gmail while keeping dotMD's existing source registry, lifecycle, read, and federated search contracts as the integration boundary. The main weakness is that the "generic bridge" claim is under-specified: most concrete behavior is Gmail-specific because Airweave's `GmailSource.search()` is unavailable and the plan directly calls Gmail APIs. That is acceptable for a spike, but the plan should explicitly separate the generic `BaseEntity -> dotMD contract` adapter from Gmail-specific search/read transport code.

## Strengths

- Keeps Airweave vendored and isolated, avoiding runtime adoption of Temporal, Vespa, SQLAlchemy, Celery, Redis, or Airweave organization-layer assumptions.
- Correctly treats Gmail as federated/search-read only, with no embedding, FTS5, graph, or trickle path.
- Uses the existing source registry/lifecycle model, which directly supports AIR-03.
- Good metadata minimization in `provider_metadata`.
- Good recognition that `SourceAsset` / attachments should be deferred instead of expanding the spike.
- Explicit AIR-02 report structure is useful and testable.

## Concerns

- **HIGH:** The generic bridge is not yet proven generic. `search_native()` and `read_unit_window()` are Gmail API implementations, not reusable Airweave `BaseSource` bridge behavior. The reusable layer should be clearly named and tested separately.
- **HIGH:** `source_native_score = None` may break or degrade RRF/fusion if existing code assumes a numeric score or uses score-based sorting before rank fallback. This needs a targeted test through federated search fusion, not only bridge unit tests.
- **HIGH:** OAuth token refresh needs concurrency handling. A simple 5-minute cache can still race under parallel searches, refresh simultaneously, or reuse an invalidated token after a 401.
- **MEDIUM:** Credential mapping via `access.delegated_to` sounds semantically odd for a refresh token. If that field was meant for delegation identity rather than secret material, this risks confusing future source providers.
- **MEDIUM:** MIME decoding is underspecified. Gmail messages may have nested multipart bodies, only `text/html`, no body in root payload, encoded headers, attachments mixed with body parts, quoted-printable edge cases, or very large messages.
- **MEDIUM:** Direct Gmail API search bypasses `GmailSource.search()` because it is not implemented, but the plan still vendors `GmailSource`. The report should be honest that the reusable value is mostly entity/schema/config patterns, not search execution.
- **MEDIUM:** Plan 37-03 modifies `core/models.py`; that can be a wide blast radius. The plan should name exact model additions and backwards-compatibility expectations.
- **LOW:** Grep checks for Airweave imports are helpful but brittle. They do not prove import-time dependency isolation.
- **LOW:** `maxResults={limit}` should clamp to Gmail API limits and validate configured values.

## Suggestions

- Add a small `AirweaveEntityAdapter` or equivalent with tests that convert generic `BaseEntity` fields into `SearchCandidate`, independent of Gmail transport.
- Add an integration-level unit test for federated fusion with Gmail candidates where `source_native_score is None` and only `source_native_rank` is set.
- Treat 401/403 from Gmail as token invalidation paths: clear cache, refresh once, retry once, then fail with a typed source error.
- Add a refresh lock around token cache updates, even if only a simple `threading.Lock`.
- Do not store refresh tokens in ambiguous fields if avoidable. Prefer a Gmail-specific credential payload or named credential secret returned through `CredentialProviderProtocol`.
- Define read fallback order: prefer `text/plain`; else convert/sanitize `text/html`; else return snippet plus metadata; never expose attachment bodies in this phase.
- Add tests for nested multipart, HTML-only, empty body, malformed base64url, and messages with attachments.
- Add a test or assertion that Gmail descriptor has exactly `FEDERATED_SEARCH` and `READ_UNIT_WINDOW`, and not `LOCAL_SYNC`.
- In AIR-02, explicitly state that Airweave's runtime/indexing stack is avoided and that direct Gmail API search is a dotMD provider concern, not generic Airweave compatibility.
- Add one final smoke path through `SourceRuntimeFactory.build("gmail")`, registry lookup, federated search provider call, and `read(ref)` resolution using mocks.

## Risk Assessment

**Overall risk: MEDIUM.**

The phase is scoped as a spike, and the plans mostly avoid the dangerous failure mode: accidentally importing Airweave's full runtime or creating a parallel Airweave-only lane. The biggest risks are contract correctness rather than implementation volume: rank-only candidates may not behave correctly in fusion, Gmail OAuth caching can fail under concurrency or expired tokens, and the "generic bridge" may remain Gmail-shaped unless deliberately split and tested. With the suggested contract tests and clearer bridge boundaries, this becomes a manageable medium-risk spike.

---

### Cycle 1 · OpenCode Review

# Phase 37 Plan Review — Airweave Connector Compatibility Spike

## Overall Assessment

The plans are well-structured, follow the established source lifecycle pattern, and correctly scope the spike to "adapt one connector" rather than build general-purpose infrastructure. The biggest risks cluster around three areas: (1) `source_native_score = None` may silently corrupt RRF fusion, (2) the "generic bridge" claim in D-03 has no design artifact across any plan, and (3) OAuth token caching with a hard 5-minute TTL is both overly aggressive and architecturally fragile. Below I address each plan individually, then call out cross-cutting concerns.

---

### Plan 37-01: Vendor Airweave Platform Slice and DI Shims

#### Summary

Solid scoping — vendor the platform layer only, strip heavy deps, provide structural DI shims. The acceptance criteria (import, grep, no temporalio) are precise and testable.

#### Strengths

- **Precise acceptance criteria.** `grep`-based checks for leaked cross-module imports and the import smoke test are concrete and automatable.
- **DI shim strategy is correct.** Airweave's `GmailSource.__init__` expects `SourceAuthProvider`, `ContextualLogger`, and `AirweaveHttpClient` — providing shim implementations rather than modifying Airweave code respects the vendor boundary.
- **Slim vendor target.** Stripping Temporal, Vespa, SQLAlchemy, Redis, Celery keeps the dependency footprint negligible.

#### Concerns

- **MEDIUM — Token cache expiry is too aggressive.** The plan says "5-min expiry." Google OAuth access tokens typically have a 1-hour lifetime. A 5-minute hard TTL means ~12x the refresh calls with no benefit. The cache should key on the actual `expires_in` from the token response minus a margin (e.g., `max(actual_expiry - 300, 0)` seconds). Otherwise every search triggers a refresh — wasteful and risks rate-limiting against Google's token endpoint.
- **MEDIUM — No token refresh race condition guard.** If two search requests arrive simultaneously and both find an expired cached token, they will both call Google's token endpoint. This is wasteful but not catastrophic for a single-user server. Still worth a simple lock or "pending refresh" sentinel in the cache to avoid the thundering-herd-on-refresh problem.
- **MEDIUM — Vendor version anchoring is missing.** The plan doesn't specify which Airweave commit/release the vendored files correspond to. Without a pinned SHA, future maintainers won't know what they're tracking. A `backend/src/dotmd/vendor/airweave/VENDOR_VERSION` file or a comment block with the source commit is essential.
- **LOW — "6 Airweave platform files" is vague.** The file list is enumerated, but the plan should clarify whether these are copied verbatim (modulo import rewrites) or modified. If modified, what's the modification delta?

#### Suggestions

1. Replace hard 5-min TTL with `token_response.expires_in - 300` margin-based caching.
2. Add a `_token_refresh_lock: threading.Lock` to `GmailOAuthTokenProvider` to serialize concurrent refreshes.
3. Include a `VENDOR_VERSION` file with the source Airweave commit SHA.
4. Document per-file modification delta in a `VENDOR_NOTES.md` inside the vendor directory.
5. Verify the vendored tree doesn't transitively pull `pydantic` if Airweave uses it directly — dotMD already has it, but version conflicts could arise.

---

### Plan 37-02: AirweaveConnectorBridge and Gmail Federated Search

#### Summary

The direct Gmail API approach is pragmatic given `GmailSource.search()` is a stub. The `SearchCandidate` shape and `read_unit_window` design are sound, but the plan is Gmail-specific despite D-03 demanding a generic bridge. The `source_native_score = None` decision needs reconciliation with the RRF fusion layer.

#### Strengths

- **Correctly bypasses the missing `search()` implementation.** Calling Gmail API directly is the right call — it avoids the temptation to implement `GmailSource.search()` inside the vendored tree, which would violate the vendor boundary.
- **Provider metadata whitelist is well-scoped.** `{message_id, thread_id, sender, subject, sent_at}` is exactly what's needed for display without leaking raw Gmail API payloads into search results.
- **Fixture-based testing with mock.** No network dependency in tests.

#### Concerns

- **HIGH — `source_native_score = None` breaks RRF fusion assumptions.** RRF (Reciprocal Rank Fusion) computes `score = 1 / (k + rank)` per result across engines. If `source_native_score` is `None`, the fusion layer must either: (a) treat it as unbounded (which biases fusion toward/away from Gmail results unpredictably), or (b) derive a rank-based fallback. The plan acknowledges this with a comment but doesn't check whether the existing RRF implementation handles `None` scores. Audit `backend/src/dotmd/search/fusion.py` before accepting this plan. If it doesn't handle `None`, the bridge should compute a positional decay score or the fusion layer needs a patch.
- **HIGH — No MIME decoding edge case handling specified.** The plan says "decodes base64url-encoded MIME body parts" but doesn't address: **Multipart messages** (multipart/alternative, multipart/mixed): which part is the "body"? **No text/plain part** (HTML-only emails): HTML decoding and tag stripping needed. **Charset handling**: Content-Type charset may not be UTF-8. **base64 vs base64url**: Gmail API returns both variants depending on the endpoint. **Large bodies**: The plan loads full body into memory for `read_unit_window`. What's the size guardrail?
- **MEDIUM — D-03 "generic bridge" has no design in this plan.** The plan is titled "AirweaveConnectorBridge and Gmail federated search," and D-03 says "Bridge must be generic across all BaseSource subclasses, not Gmail-specific." Yet the plan only describes Gmail-specific API calls. Where does the generic bridge abstraction live? What's the abstract interface?
- **MEDIUM — No error handling for Gmail API failures.** `GET /messages?q=...` can return 401 (expired token), 429 (rate limit), 500 (transient server error), or return empty results.
- **LOW — `SearchCandidate` doesn't reference `SourceDocument` or `SourceUnit`.** For a federated-search-only source, `SourceDocument` and `SourceUnit` may be virtual (constructed at query time), but this should be explicitly stated.

#### Suggestions

1. **Audit `fusion.py` RRF implementation for `None` score handling** before accepting the plan.
2. **Specify MIME body decoding logic** covering: part selection order, charset handling, HTML fallback, size limits.
3. **Define `BaseConnectorBridge` abstract class** with `search_native`, `read_unit_window`, and `to_search_candidate` as its protocol.
4. **Add error classification and retry strategy** for Gmail API HTTP responses.
5. **Clarify `SourceDocument`/`SourceUnit` mapping** for federated-search-only sources.

---

### Plan 37-03: Gmail Source Descriptor, Lifecycle Config, and Registry Wiring

#### Summary

Cleanly follows the filesystem/Telegram pattern for registry registration and lifecycle wiring. The credential flow through `SourceCredentialRef` → `DefaultSourceCredentialProvider` → `GmailOAuthTokenProvider` is architecturally correct.

#### Strengths

- **Correct capability set: FEDERATED_SEARCH + READ_UNIT_WINDOW, no LOCAL_SYNC.** Accurately reflects that Gmail is a read-only query source with no indexing/trickle involvement.
- **Credential provider boundary is respected.** OAuth tokens don't leak into the registry or search layer.
- **Env var activation is low-friction.** `DOTMD_GMAIL_*` vars follow the existing convention.

#### Concerns

- **MEDIUM — Credential storage location mismatch.** User decision D-05 says credentials live in `~/.secrets/dotmd-gmail.env`, but the plan wires env vars directly. The plan should specify how the `.env` file is loaded.
- **MEDIUM — No credential validation at registration time.** If `DOTMD_GMAIL_*` vars are set but the refresh token is expired or invalid, the descriptor should still register (degraded mode) but log a warning.
- **LOW — Plan depends only on 37-01, but references test removal from 37-02.** The dependency graph should show `Depends on: 37-01, 37-02`.
- **LOW — Search result limit env var.** `DOTMD_GMAIL_SEARCH_RESULT_LIMIT` should validate it stays within API bound (1–500).

#### Suggestions

1. Specify how `~/.secrets/dotmd-gmail.env` is loaded into env vars.
2. Add graceful degradation: if credentials are invalid, register the descriptor but mark it as `status=SourceLifecycleStatus.CREDENTIALS_UNAVAILABLE`.
3. Set `DOTMD_GMAIL_SEARCH_RESULT_LIMIT` default to 20, validate 1 ≤ value ≤ 500.
4. Fix dependency declaration to include 37-02, or move test skip-marker removal to 37-04.
5. Add a `health_check()` method that validates the Gmail OAuth token with a lightweight API call.

---

### Plan 37-04: AIR-02 Compatibility Report and End-to-End Verification

#### Summary

Good quality gate — the report structure is comprehensive and the verification grep checks are precise. The main risk is that the report is described as "pre-written," which suggests it may be aspirational rather than evidence-based.

#### Strengths

- **Report structure answers all three AIR-02 categories.** Reusable, shim, avoid — clear triage.
- **Verification checks are automatable.**
- **Attribution of `GmailSource.search()` being unimplemented.** The key research finding is correctly surfaced as a report section.

#### Concerns

- **MEDIUM — "Pre-written in the plan" is a smell.** If the report content is predetermined before the spike executes, it may miss actual findings.
- **MEDIUM — GmailAttachmentEntity deferred but not detailed.** The report template mentions it, but doesn't specify what the mapping would look like.
- **LOW — No mention of updating AGENTS.md.**
- **LOW — "Generic bridge extensibility assessment" is vague.**

#### Suggestions

1. Write the report as a template with `[TBD: filled after 37-01–37-03]` markers, not pre-written prose.
2. Include a concrete `SourceAsset` mapping table even if deferred.
3. Add an "Extensibility Assessment" table: for each bridge component, classify as `generic` or `connector-specific`.
4. Include an AGENTS.md update task in the plan.

---

### Cycle 1 · Cross-Cutting Concerns

#### 1. `source_native_score = None` and RRF Fusion (CRITICAL)

Both reviewers independently flagged this as the top risk. Gmail API returns no relevance score; setting `source_native_score = None` may crash or silently corrupt the fusion layer. `backend/src/dotmd/search/fusion.py` must be audited. If the fusion layer does not handle `None`, either add `source_native_score = 1.0 / (rank + 1)` positional decay in the bridge, or patch the fusion layer.

#### 2. Generic Bridge Abstraction (D-03) Not Designed (HIGH)

Both reviewers flagged that D-03 ("bridge must be generic across all BaseSource subclasses") has no design artifact in any plan. A `BaseConnectorBridge(ABC)` abstract class defining `search_native`, `read_unit_window`, and `to_search_candidate` must be added to Plan 37-02, with `GmailBridge` as its first implementation.

#### 3. OAuth Token Lifecycle (MEDIUM)

Token refresh is mentioned across plans but never designed as a coherent lifecycle: 5-minute hard TTL is too short, no `threading.Lock` guard, no handling for refresh token rotation. Consolidate token handling into a `TokenCache` class in shims layer with thread-safe refresh serialization and margin-based expiry (`expires_in - 300`).

### Cycle 1 · Risk Summary

| Plan | Risk |
|------|------|
| 37-01 | **MEDIUM** — Token caching design needs revision |
| 37-02 | **HIGH** — `source_native_score=None` RRF risk unmitigated; generic bridge missing |
| 37-03 | **MEDIUM** — Credential source mismatch; graceful degradation unspecified |
| 37-04 | **LOW** — Pre-written report risk |

**Cycle 1 Overall: MEDIUM-HIGH**

---

<!-- ═══════════════════════════════════════════════════════════════
     CYCLE 2  (2026-05-11T15:45:00Z — plans updated to address Cycle 1:
               threading.Lock + expires_in-300 added to 37-01;
               BaseConnectorBridge ABC + source_native_score=None
               safety doc added to 37-02; MIME edge cases added;
               error boundaries added; 37-03/04 fleshed out)
     ═══════════════════════════════════════════════════════════════ -->

## Cycle 2 — 2026-05-11T15:45:00Z

*Plans were updated after Cycle 1 to address the three HIGHs: threading.Lock +
margin-based expiry added (37-01), BaseConnectorBridge(ABC) added with
source_native_score=None safety test (37-02), MIME decode edge cases and error
boundaries fully specified (37-02). This cycle reviews the updated plans.*

---

### Cycle 2 · Codex Review

## Summary

Overall the phase is directionally sound: it keeps Gmail in the federated-provider lane, avoids local indexing, preserves the existing source registry/lifecycle boundary, and explicitly avoids Airweave's heavier runtime stack. The biggest weakness is that the plans claim "generic BaseSource compatibility," but the concrete Gmail path bypasses `GmailSource.search()` and calls Gmail directly. That is reasonable for the spike, but the plans need sharper acceptance criteria proving the reusable part is the bridge/entity/config pattern, not actual Airweave search reuse.

## PLAN 37-01 Review

### Strengths

- Vendoring is scoped to the platform slice and explicitly rejects Temporal, Vespa, billing, and organization-layer imports.
- Import smoke tests and forbidden-import checks are good guardrails.
- Token refresh serialization with expiry margin and `threading.Lock` is the right risk to test early.
- `VENDOR_VERSION` and `VENDOR_NOTES.md` are important for future diffing against upstream.

### Concerns

- **HIGH:** This plan vendors `GmailSource`, but later plans do not actually use `GmailSource.search()` because it is absent. The plan should avoid implying that vendoring proves connector behavior end to end.
- **MEDIUM:** License/provenance handling is underspecified. Vendoring should preserve Airweave license headers or include explicit attribution.
- **MEDIUM:** Structural DI compatibility is weaker than runtime compatibility. A constructor smoke test is not enough if Airweave internals expect logger/http/client methods during listing or entity hydration.
- **LOW:** "Copy 6 files" conflicts with the longer modified-file list. That mismatch can cause review noise.

### Suggestions

- Add a test that instantiates `GmailSource.create(...)` or equivalent construction path with shims, even if search is not used.
- Add a vendored license/provenance checklist to acceptance.
- Add a forbidden-import test that scans the vendored package AST/import graph, not only raw grep strings.

### Risk Assessment

**MEDIUM.** The vendoring boundary is manageable, but there is reputational risk in calling this connector compatibility if the vendored connector is only partially exercised.

---

## PLAN 37-02 Review

### Strengths

- Correctly accepts the research finding that Gmail search must use the Gmail API directly.
- Keeps the provider behind a generic `BaseConnectorBridge`.
- MIME decoding coverage is appropriately broad for email: multipart, HTML-only, charset, malformed base64, and size cap.
- Error boundaries for 401 and retryable provider failures match federated soft-failure expectations.

### Concerns

- **HIGH:** `ApplicationSourceProviderProtocol` currently includes `describe_source`, `export_changes`, and `read_unit_window`, while federated search is a separate protocol shape. `GmailApplicationSourceProvider` must either implement `export_changes` as unsupported/empty or the protocol/runtime assumptions will be leaky.
- **HIGH:** The existing quota merge uses a Telegram-specific low-signal filter on all federated candidates in `service.py`. Gmail snippets may be incorrectly filtered. This phase should generalize or scope that filter before adding Gmail.
- **MEDIUM:** Gmail latency can exceed the current federated timeout if search does list + N message fetches. The plan needs explicit httpx timeouts, max fetch count, and partial-result behavior.
- **MEDIUM:** "batch metadata fetch" is vague. Gmail's batch behavior is not the same as a simple bulk endpoint; implementation should not assume a convenient batch API unless verified.
- **MEDIUM:** Query handling is underspecified. Gmail `q` syntax is powerful; raw user queries may behave unexpectedly or expose broad mailbox searches.
- **LOW:** Provider metadata whitelist is good, but sender/subject can still contain sensitive data. That is acceptable for search output, but logs/tests should avoid leaking it.

### Suggestions

- Add tests proving Gmail candidates survive `_merge_with_federated_quota`.
- Add per-request timeout and partial-result tests: one slow message fetch should not fail the whole Gmail provider.
- Make `BaseConnectorBridge` generic enough to carry source namespace, descriptor key, and capability metadata, not just conversion methods.
- Add a clear `export_changes` behavior for Gmail federated-only mode.

### Risk Assessment

**HIGH.** This is the behavior-critical plan. The direct Gmail API path is practical, but timeout, protocol conformance, and Telegram-specific merge behavior can easily break the federated-search goal.

---

## PLAN 37-03 Review

### Strengths

- Correctly routes Gmail through descriptor, lifecycle, config, and runtime factory instead of creating an Airweave-only lane.
- `build_if_configured("gmail")` being optional matches the production model.
- `search_result_limit` validation is useful and bounded.
- "No direct `GmailSource()` instantiation outside lifecycle" is a good architectural guardrail.

### Concerns

- **HIGH:** `SourceConfig` is currently a closed union in `source_lifecycle.py`. The plan mentions adding `GmailSourceConfig`, but must explicitly update the union and config validation paths.
- **HIGH:** Putting the refresh token into `SourceAccess.delegated_to` is a semantic mismatch with security risk. It may show up in reprs, errors, debug logs, or status metadata.
- **MEDIUM:** "Invalid credentials at registration produce `CREDENTIALS_UNAVAILABLE` status" needs a concrete status model. Current `SourceStatus.status` is only `ok | skipped | error`; if this is lifecycle status, name the exact field/model.
- **MEDIUM:** `service.py` populating `InMemorySourceConfigStore` only when all three env vars are present is fine, but partial config should produce an observable skipped/error reason, not silently disable Gmail.
- **LOW:** Docker `env_file` is declared out of code scope, but the phase should still verify expected env var names match `Settings`.

### Suggestions

- Prefer a credential ref such as `credential_ref="gmail:default"` and let the credential provider return token material without storing secrets in `SourceAccess.delegated_to`.
- Add tests for no config, partial config, invalid refresh token, and successful config.
- Add a grep/test guard that only `source_lifecycle.py` constructs the Gmail provider/bridge.

### Risk Assessment

**MEDIUM-HIGH.** The architecture is aligned, but credential handling and closed-union config wiring are easy places to create either a runtime crash or a secret leak.

---

## PLAN 37-04 Review

### Strengths

- The compatibility report requirements are concrete and tied to actual implemented code.
- The AIR-03 checklist is the right closeout artifact for this phase.
- Full suite plus targeted grep checks are appropriate for a spike that changes lifecycle and service wiring.
- Updating `AGENTS.md` with vendoring and bridge rules will prevent future drift.

### Concerns

- **MEDIUM:** Full test suite green may be too broad if there are known unrelated failures. If the suite is currently clean, keep it. If not, record exact known failures before starting.
- **MEDIUM:** The report can become post-hoc justification unless it includes evidence from tests and code paths.
- **LOW:** `AGENTS.md` should stay operational and concise; detailed compatibility analysis belongs in `docs/airweave-compatibility.md`.

### Suggestions

- Include a short evidence table in the report: claim, code path, test.
- Add verification for `read(ref)` on a Gmail ref, not only provider registration.
- Add a negative check that Gmail does not create local chunks, FTS rows, embeddings, graph nodes, or trickle registrations.

### Risk Assessment

**LOW-MEDIUM.** Documentation and verification are well scoped, but should explicitly prove "federated only" at storage boundaries.

---

## Cycle 2 · Codex Cross-Plan Concerns

- **HIGH:** The phase goal says "wrap any Airweave `BaseSource` connector," but the actual implementation is closer to "vendor Airweave entity/config/source shapes and build a dotMD bridge around provider APIs." That is acceptable if the report states it plainly.
- **HIGH:** The Telegram-specific federated merge filter must be fixed before Gmail is added, or Gmail results can be silently dropped.
- **MEDIUM:** There is no live OAuth/bootstrap plan. Even if token creation is manual, the phase should define the command or script used once to obtain the refresh token.
- **MEDIUM:** The plans need a "no local indexing side effects" assertion: no writes to chunk, FTS, vector, graph, or trickle state during Gmail search/read.
- **MEDIUM:** Rate limiting and Gmail quota behavior need backoff/soft-skip tests, especially for 429.
- **LOW:** Naming should avoid overclaiming. `BaseConnectorBridge` may be better than `AirweaveConnectorBridge` if the bridge is deliberately dotMD-owned.

**Cycle 2 Codex Overall: MEDIUM-HIGH.** The architecture direction is strong and consistent with the existing source lifecycle/federated-search model, but Plan 37-02 and 37-03 contain the real integration risk: Gmail live-search latency, secret handling, protocol conformance, and existing Telegram-specific merge behavior.

---

### Cycle 2 · OpenCode Review

# Phase 37: Airweave Connector Compatibility Spike — Plan Review

## Overall Assessment

Phase 37 is well-scoped with clear boundaries: prove the pattern, use Gmail as the test subject, don't over-integrate. The four plans form a coherent dependency chain (vendor → bridge → wire → verify), and the research finding that `GmailSource.search()` is a stub shapes the architecture correctly. The biggest gaps are around MIME edge case maturity, non-happy-path lifecycle handling, and a few missing handoff points between plans that could surface during execution.

---

## PLAN 37-01: Vendor Airweave Platform Slice and DI Shims

### Summary
Solid foundation plan. The vendoring strategy is disciplined — copy only the 6 necessary files, rewrite imports to be self-contained, and stub the decorator rather than pulling in the meta-programming framework. The token provider design with margin-based expiry and double-checked locking is production-correct.

### Strengths
- **Minimal vendoring footprint.** Copying only `sources/`, `entities/`, and `configs/` — explicitly excluding `domains/`, `core/`, `schemas/`, and the Temporal/Vespa stack. This makes the vendored tree auditable.
- **DI shim pattern is clean.** `GmailLoggerShim`, `GmailHttpClientShim`, `GmailOAuthTokenProvider` satisfy `GmailSource.__init__` structurally without inheriting Airweave's runtime wiring framework.
- **Token provider race protection.** `threading.Lock` + margin-based expiry (`expires_in - 300`) + double-check inside lock is excellent. The concurrent refresh serialization test (5 threads, only 1 `httpx.post`) proves correctness.
- **Source traceability.** `VENDOR_VERSION` + `VENDOR_NOTES.md` will matter when upstream Airweave eventually updates.
- **`@source` decorator as no-op.** Sets `ClassVar` attributes and returns the class unchanged. Correct.

### Concerns
- **MEDIUM — `@source` decorator may need to preserve more than `ClassVar` attrs.** If any vendored source uses decorator-managed metadata at class-load time (e.g., entity type registration), a pure no-op will miss it. A comment noting this limitation is fine for the spike, but it should be explicit.
- **MEDIUM — No mention of how vendored source/entity Pydantic models interact with dotMD's Pydantic v2.** Airweave's `BaseEntity` likely uses Pydantic v1 or a different version. Cross-Pydantic-version model inheritance is fragile. Plan should confirm both projects use Pydantic v2, or document the shim approach for model compatibility.
- **LOW — `VENDOR_VERSION` going stale.** `VENDOR_NOTES.md` should record the commit hash/date of the source files.

### Suggestions
- Add a comment in `@source` stub noting which Airweave decorator behaviors are intentionally not implemented.
- Verify Pydantic version compatibility between Airweave entities and dotMD models in `VENDOR_NOTES.md`.
- Record the Airweave commit hash in `VENDOR_VERSION` alongside the version tag.

---

## PLAN 37-02: BaseConnectorBridge ABC, GmailBridge, and Federated Search

### Summary
The heart of the phase. `BaseConnectorBridge(ABC)` is the right abstraction — generic enough for D-03, concrete enough that Gmail doesn't need special-casing. Direct Gmail API calls via `httpx.Client` (not wrapping `GmailSource.search()`) is the correct call. MIME decoding is handled with reasonable pragmatism but is the riskiest subsystem.

### Strengths
- **Generic bridge contract.** 3 abstract methods (`search_native`, `read_unit_window`, `to_search_candidate`) map cleanly to the federated search interface.
- **Error boundary taxonomy.** `SourceAuthError` for 401, `SourceTemporaryUnavailable` for 429/5xx.
- **`source_native_score=None` is handled correctly.** Federated candidates bypass RRF score fusion and flow through `_merge_with_federated_quota` (Phase 36). Architecturally sound.
- **`provider_metadata` whitelist is minimal.**
- **MIME decoding acknowledges complexity.** Prefers text/plain over stripped text/html, handles multipart/alternative recursion, charset detection, base64url decoding.

### Concerns
- **HIGH — Batch metadata fetch is O(n) individual requests.** For `limit=100`, that's 101 HTTP round-trips before the user sees anything. Gmail's `batch` endpoint (`POST /batch`) can bundle multiple requests. Plan should document this as a known limitation with a follow-up optimization task.
- **HIGH — No Gmail API quota/pagination awareness.** Gmail free tier has 250 quota units/user/second. `users.messages.list` costs 5 units, `users.messages.get` costs 5 units. For 100 messages, that's ~505 quota units — exceeds the per-second limit without retry/backoff. Plan mentions 429 handling but not quota unit awareness.
- **MEDIUM — MIME edge case: 1MB cap is arbitrary and undocumented behavior.** Truncating at 1MB silently loses content — the search result should flag truncated content so the user knows they're seeing a partial result.
- **MEDIUM — `to_search_candidate()` field mapping is underspecified.** What Gmail field becomes `SearchCandidate.title`? `SearchCandidate.snippet`? `SearchCandidate.timestamp`? These drive the search display.
- **MEDIUM — No integration test path for the Gmail API.** All smoke tests mock `httpx`. A single integration test (run manually, not in CI) that hits the real Gmail API with a known search query verifies the bridge actually works end-to-end.
- **LOW — Malformed base64 handling should specify base64url vs base64.** Gmail's raw MIME uses base64url encoding. Error handling paragraph should specify which encoding errors are caught.
- **LOW — HTML tag stripping is lossy for structured content.** Table-based emails, nested lists, and code blocks lose formatting. Acceptable for a spike, but worth noting in the compatibility report.

### Suggestions
- Add `POST /batch` as a follow-up optimization task.
- Add Gmail quota unit budget awareness in the comment above batch metadata fetch logic.
- In `to_search_candidate()`, include a `truncated: bool` field on SearchCandidate (or in provider_metadata) when MIME body exceeds the cap.
- Enumerate the SearchCandidate field mapping table in Plan 37-02's must-haves.
- Consider a single manual integration test script (`scripts/test_gmail_integration.py`) for the developer to run once with real credentials.

---

## PLAN 37-03: Gmail Source Descriptor, Lifecycle Config, and Registry Wiring

### Summary
Clean registry integration following Phase 36's patterns. Gmail enters through the same `SourceRegistry` → `SourceRuntimeFactory` → `SourceRuntimeBundle` path as filesystem and Telegram (satisfying AIR-03). The credential loading story is thin but correct for the spike.

### Strengths
- **Same registry path as existing sources.** `gmail_source_descriptor()` registers with `namespace="gmail"`, `capabilities=[FEDERATED_SEARCH, READ_UNIT_WINDOW]`, same shape as Telegram's descriptor.
- **Graceful credential absence.** `build_if_configured("gmail")` returns `None` when `DOTMD_GMAIL_CLIENT_ID` is unset.
- **Invalid credentials → `CREDENTIALS_UNAVAILABLE`.** Registration doesn't hard-crash.
- **`search_result_limit` validation.** `Field(ge=1, le=500)` catches configuration errors at startup.
- **No direct `GmailSource()` outside lifecycle.**

### Concerns
- **MEDIUM — `access.delegated_to` holding `refresh_token` is a semantic mismatch.** `AccessCredential.delegated_to` usually holds a user identity string. Using it for a raw OAuth refresh token means any code that iterates over `delegated_to` values will leak secrets. A dedicated `GmailAccessCredential` subclass or a `refresh_token` field on the config object would be safer.
- **MEDIUM — `InMemorySourceConfigStore` population condition.** What happens when only 2 of 3 Gmail env vars are set? The plan should specify: partial env sets log a warning with the specific missing var name and don't register.
- **MEDIUM — Start-up token validation.** Does `build("gmail")`'s "get access" mean a live HTTP call to Google's token endpoint? If so, container startup blocks on external network I/O. Plan should clarify whether token acquisition is eager or lazy.
- **LOW — `env_file: ~/.secrets/dotmd-gmail.env` in docker-compose.** Path `~/.secrets/` resolves to root's home (`/root/.secrets/`) inside the container, not the host. Need absolute host path or explicit env injection.
- **LOW — No mention of how `DOTMD_GMAIL_REFRESH_TOKEN` gets into the env in the first place.** D-05 says "initial OAuth flow run once to obtain refresh token." Is there a CLI command or a manual `curl`? Plans don't address token bootstrapping.

### Suggestions
- Create a `GmailSourceConfig.refresh_token` field instead of abusing `AccessCredential.delegated_to`.
- Add partial-env-var detection: if some Gmail vars are set but not all, log a warning listing which are missing and skip registration.
- Clarify whether startup-time token validation is synchronous (blocking) or lazy (deferred to first search).
- Add a small `dotmd gmail auth` CLI command or a `scripts/gmail_oauth_flow.py` script for token bootstrapping.

---

## PLAN 37-04: AIR-02 Compatibility Report and E2E Verification

### Summary
The capstone plan. The report is generated from actual implemented code rather than pre-written prose — that's the right way to ensure honesty. The verification checklist is thorough and cleanup checks enforce the boundaries set by Plans 37-01 through 37-03.

### Strengths
- **Report from code, not before code.** "Based on ACTUAL implemented code (not pre-written prose)" — avoids the common trap of writing optimistic architecture docs that reality never matches.
- **Three-axis compatibility taxonomy.** "Reusable directly," "Requires shims," "Should be avoided" — matches AIR-02 exactly.
- **Cleanup verification.** `grep -r "^from airweave|^import airweave"` ensures no Airweave module-level imports leaked through.
- **No skipped tests.**
- **AGENTS.md update.** Preserves vendoring decision, token handling pattern, and generic bridge pattern as institutional knowledge.

### Concerns
- **MEDIUM — Compatibility report structure underspecified.** "Extensibility assessment table" and "AIR-03 compliance checklist" are mentioned but not detailed. Without a template, the report risks being a narrative document rather than a structured assessment.
- **MEDIUM — No integration/end-to-end test exercising the full path.** A single manual end-to-end test (search for "receipt" → get Gmail results mixed with filesystem/Telegram results → read one Gmail message body) proves the integration works.
- **LOW — `grep` check may miss re-exported imports.** If a vendored file does `from airweave.x import Y as _Y` and re-exports it, the regex won't catch it.
- **LOW — Report doesn't mention what happens when Airweave upstream changes.**

### Suggestions
- Provide a template/skeleton for `docs/airweave-compatibility.md` with required sections and expected formats.
- Add one manual E2E verification step to the checklist in Plan 37-04.
- Include the Airweave upstream commit hash and report generation date in `docs/airweave-compatibility.md`.

---

## Cycle 2 · OpenCode Cross-Cutting Concerns

| # | Concern | Severity | Affected Plans |
|---|---------|----------|---------------|
| 1 | **No search timeout for live Gmail calls.** When Gmail API is slow or unreachable, `search()` blocks — potentially impacting the entire search pipeline if synchronous. | **HIGH** | 37-02, 37-03 |
| 2 | **No retry strategy for OAuth token refresh failure.** If Google's token endpoint returns 5xx, does the bridge retry with backoff or fail immediately? | **MEDIUM** | 37-01, 37-02 |
| 3 | **Telemetry/logging not addressed.** When Gmail search fails, what shows up in the container logs? No plan mentions structured logging or trace context for federated providers. | MEDIUM | 37-02, 37-03 |
| 4 | **`httpx.Client` lifecycle.** Is the client created once per `GmailBridge` instance and reused across `search_native()` calls, or created per call? Connection pooling matters for production. | LOW | 37-01, 37-02 |
| 5 | **Concurrent search handling.** If two search requests arrive simultaneously, do they share the same `GmailBridge` instance? Is the token provider's `threading.Lock` sufficient or does search need its own serialization? | LOW | 37-01, 37-02 |

**Cycle 2 OpenCode Overall: MEDIUM**

The architecture is sound and the DI shim + ABC pattern is the right abstraction level for a spike. Plans 37-01 through 37-04 form a logical dependency chain. The boundary is well-enforced: no embedding, no FTS5, no graph, no trickle for Gmail — pure federated search.

The HIGH concerns are all operational rather than architectural: Gmail batch API underuse (O(n) round-trips), quota unit budgeting, and search timeout. None of these block the spike — they're documentation items for the compatibility report.

**Verdict:** Approve with the noted edge cases addressed during implementation.

---

## Cycle 2 · Consensus Summary

Both reviewers assessed the updated plans (which address the Cycle 1 HIGH concerns) and converged on remaining issues.

### What Changed Since Cycle 1 (HIGHs Addressed in Plans)

The three Cycle 1 HIGHs were addressed in the updated plans:
1. **`source_native_score=None` RRF risk** → Plan 37-02 now documents the federated bypass path (`_merge_with_federated_quota`) and includes a fusion-correctness test. **Partially resolved** — documented and tested in plan, but Codex raised a NEW HIGH that the Telegram-specific filter in `_merge_with_federated_quota` may still drop Gmail candidates.
2. **Generic bridge abstraction absent (D-03)** → Plan 37-02 now has `BaseConnectorBridge(ABC)` with 3 abstract methods and `GmailBridge` as the implementation. **Resolved.**
3. **OAuth token caching fragile** → Plan 37-01 now specifies `threading.Lock` + `expires_in - 300` margin + double-check-inside-lock + concurrent refresh serialization test. **Resolved.**

### Agreed Strengths (Cycle 2)

- **Token provider design is now production-correct.** `threading.Lock` + margin-based expiry + double-check inside lock + serialization test.
- **`BaseConnectorBridge(ABC)` satisfies D-03.** Generic 3-method contract, `GmailBridge` as first implementation.
- **MIME decoding is now comprehensively specified.** Multipart, HTML-only, charset, malformed base64, 1MB cap all addressed.
- **Error boundaries are defined.** 401 → `SourceAuthError`, 429/5xx → `SourceTemporaryUnavailable`.
- **AIR-03 pattern is symmetric.** Gmail uses the same registry/lifecycle/service path as filesystem and Telegram.

### Agreed Concerns (Cycle 2)

1. **HIGH — Telegram-specific filter in `_merge_with_federated_quota` may drop Gmail candidates silently** (Codex). The quota merge may have Telegram-specific logic; Gmail snippets could be incorrectly filtered. Verify and generalize before accepting Plan 37-02.

2. **HIGH — `ApplicationSourceProviderProtocol` conformance gap for `GmailApplicationSourceProvider`** (Codex). If the protocol requires `export_changes` or `describe_source` methods not planned for Gmail, the thin wrapper will fail at runtime. Explicit implementation with no-op stubs needed.

3. **HIGH — O(n) metadata fetch round-trips** (OpenCode). For `limit=100`, 101 individual HTTP calls before any results. Plan should document this explicitly as a known limitation with a follow-up task.

4. **HIGH — No search-level timeout** (OpenCode). A slow or unreachable Gmail API blocks the synchronous search pipeline. Explicit httpx timeout needed.

5. **MEDIUM — `access.delegated_to` stores raw refresh_token** (both reviewers). Semantic mismatch may cause secret leak in logs/reprs. Prefer `GmailSourceConfig.refresh_token` field.

6. **MEDIUM — Partial env-var handling** (OpenCode). If only 2 of 3 Gmail env vars are set, the current plan silently disables Gmail with no observable reason. Log which specific var is missing.

7. **MEDIUM — `to_search_candidate()` field mapping underspecified** (OpenCode). Which Gmail field maps to `SearchCandidate.title`, `.snippet`, `.timestamp`? Affects search result display.

8. **MEDIUM — Token bootstrapping unaddressed** (OpenCode). No plan for the initial OAuth flow to obtain the refresh token. A `dotmd gmail auth` CLI or `scripts/gmail_oauth_flow.py` is needed.

### Divergent Views (Cycle 2)

- **License/provenance of vendored files** (Codex raised, OpenCode did not). Vendoring should preserve Airweave license headers or include explicit attribution.
- **Scope characterization** (Codex raised). The phase claims "wrap any Airweave BaseSource connector" but the implementation is closer to "vendor Airweave entity schemas and build a dotMD bridge around provider APIs." The compatibility report should state this honestly.
- **`@source` decorator gap** (OpenCode raised). A pure no-op may miss entity-type registration if other connectors depend on decorator-managed metadata at class-load time.
- **Pydantic version compatibility** (OpenCode raised). Airweave may use Pydantic v1; cross-version model inheritance is fragile and should be verified in `VENDOR_NOTES.md`.

### Cycle 2 Risk Summary

| Plan | Cycle 1 Risk | Cycle 2 Risk | Change |
|------|-------------|-------------|--------|
| 37-01 | MEDIUM | MEDIUM | No change — token/vendor risks now lower, license gap raised |
| 37-02 | HIGH | HIGH | Telegram filter + protocol conformance + O(n) + timeout are new HIGHs |
| 37-03 | MEDIUM | MEDIUM-HIGH | `delegated_to` secret leak risk sharpened |
| 37-04 | LOW | LOW-MEDIUM | Report structure risk remains |

**Cycle 2 Overall: MEDIUM-HIGH**

Four new HIGH concerns remain unresolved (Telegram filter gap, `ApplicationSourceProviderProtocol`
conformance, O(n) metadata fetch, search timeout). These are all in Plan 37-02 and should be
addressed before execution begins on that wave.
