---
phase: 37
reviewers: [codex, opencode]
reviewed_at: 2026-05-11T17:00:00Z
cycles: 4
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
- **LOW:** `AGENTS.md` should stay operational and concise; detailed compatibility analysis belongs in `docs/gmail-airweave-compatibility-spike.md`.

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
- Provide a template/skeleton for `docs/gmail-airweave-compatibility-spike.md` with required sections and expected formats.
- Add one manual E2E verification step to the checklist in Plan 37-04.
- Include the Airweave upstream commit hash and report generation date in `docs/gmail-airweave-compatibility-spike.md`.

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

---

<!-- ═══════════════════════════════════════════════════════════════
     CYCLE 3  (2026-05-11T16:15:00Z — plans updated to address Cycle 2:
               _is_low_signal_federated_candidate added (37-02 Task 1);
               GmailApplicationSourceProvider NotImplementedError stubs for
               describe_source/export_changes added (37-02);
               GMAIL_API_TIMEOUT_SECONDS=10.0 with explicit httpx.Timeout (37-02);
               O(n) documented as known limitation with follow-up task (37-02);
               GmailSourceConfig.refresh_token replaces SourceAccess.delegated_to (37-03);
               partial env-var named warnings added (37-03))
     ═══════════════════════════════════════════════════════════════ -->

## Cycle 3 — 2026-05-11T16:15:00Z

*Plans were updated after Cycle 2 to address the four HIGHs: Telegram-specific
filter generalized to `_is_low_signal_federated_candidate` (37-02 Task 1);
`GmailApplicationSourceProvider` now has explicit `NotImplementedError` stubs for
`describe_source` and `export_changes` (37-02); `GMAIL_API_TIMEOUT_SECONDS = 10.0`
applied to all httpx calls (37-02); O(n) metadata fetches documented as known
limitation with follow-up task (37-02); `GmailSourceConfig.refresh_token` used
instead of `SourceAccess.delegated_to` (37-03); partial env-var detection with
named warnings (37-03). This cycle reviews the updated plans.*

---

### Cycle 3 · Codex Review

## Plan 37-01

**Summary:** Solid spike boundary: vendoring only the Airweave schema/source slice and replacing platform dependencies with small shims is aligned with AIR-01/AIR-03.

**Strengths**
- Avoids adopting Airweave runtime/indexing stack.
- Token cache uses expiry margin and a lock, which is appropriate for shared provider use.
- Tests cover import isolation and concurrent refresh.

**Concerns**
- **MEDIUM:** Token refresh `httpx.post(...)` snippet does not explicitly show timeout/error mapping. A stuck OAuth refresh can still hang Gmail search startup/use.
- **LOW:** Refresh-token rotation mutates the credentials dict in memory, but the plan does not say whether persistence is intentionally out of scope.

**Suggestions**
- Add explicit OAuth token request timeout and map token refresh failures to source auth/temporary errors.
- State clearly that rotated refresh tokens are in-memory only for this spike unless persistence is added.

**Risk Assessment:** **LOW-MEDIUM.** The vendoring boundary is clean; the main residual risk is operational timeout/error behavior in the token shim.

---

## Plan 37-02

**Summary:** The Telegram filter fix is directionally correct, and Gmail pass-through is now explicitly protected. The timeout fix is only partial: per-call `httpx` timeouts do not create a true search-level deadline, and the O(n) metadata fetch can still make a single Gmail search take minutes or worse if `limit` is high.

**Strengths**
- `_is_low_signal_federated_candidate()` correctly scopes Telegram low-signal filtering by `namespace == "telegram"` or `retrieval_kind.startswith("tg:")`.
- Gmail candidates bypass the Telegram text-quality filter.
- `SourceAuthError` / `SourceTemporaryUnavailable` boundaries are specified.
- Provider stubs acknowledge that Gmail is federated-only.

**Concerns**
- **HIGH:** The "no search-level timeout" concern is not fully resolved. `httpx.Timeout(10.0)` applies per HTTP operation; with `1 + N` Gmail calls, `limit=500` can still create a very long search path. This needs either a hard per-search deadline or a much lower enforced Gmail fetch cap.
- **HIGH:** O(n) metadata fetch is documented, but documentation alone is weak with `search_result_limit` up to 500. For a spike, cap effective Gmail metadata fetches to something like `min(limit, search_result_limit, 50)` and test it.
- **MEDIUM:** `export_changes()` must exactly match the current protocol signature: `cursor`, `limit`, `updated_after=None`, `updated_after_cursor=None`. The plan's abbreviated `export_changes(cursor, limit, ...)` is still risky if implemented literally.
- **MEDIUM:** Timeout coverage says "all httpx calls," but the plan also has OAuth refresh in Plan 37-01. Gmail search may call token refresh before API calls, so token-provider HTTP needs the same explicit timeout discipline.
- **LOW:** Test `test_low_signal_filter_still_filters_telegram_candidates` should use a known low-signal Telegram snippet and a known normal Telegram snippet, not only `"ok"`, so it proves selective behavior.

**Suggestions**
- Add `GMAIL_SEARCH_TOTAL_TIMEOUT_SECONDS` or deadline accounting around list + metadata fetch.
- Enforce and test an effective metadata fetch cap.
- Require exact protocol method signatures in the plan.
- Add a test that Gmail candidates with very short snippets are retained, while Telegram short snippets are filtered.
- Add a test proving all Gmail API paths, including message list, message get, read window, and token refresh, use explicit timeouts.

**Risk Assessment:** **MEDIUM-HIGH.** The filter fix is good, but the original timeout/O(n) risk is still only partly solved.

---

## Plan 37-03

**Summary:** The lifecycle/registry direction is right and preserves AIR-03 by keeping Gmail in the same source system as filesystem and Telegram. The config model is cleaner after moving `refresh_token` out of `SourceAccess.delegated_to`.

**Strengths**
- Uses `GmailSourceConfig.refresh_token` directly, which avoids abusing delegated identity fields for secrets.
- Partial env-var warning names missing variables.
- `search_result_limit` validation prevents unbounded config values.
- Runtime construction through `SourceRuntimeFactory.build("gmail")` keeps Gmail out of a separate lane.

**Concerns**
- **HIGH:** `search_result_limit` allows 500, which conflicts with Plan 37-02's O(n) metadata call limitation. Validation should reflect spike safety, not only API plausibility.
- **MEDIUM:** The current lifecycle config union will need to include `GmailSourceConfig`; otherwise strict Pydantic config records may reject it.
- **MEDIUM:** Gmail descriptor capabilities should exclude incremental export if `describe_source()` / `export_changes()` are unsupported. Only `FEDERATED_SEARCH` and `READ_UNIT_WINDOW` should be advertised.
- **LOW:** Logging missing env var names is good, but tests should assert no secret values are logged.

**Suggestions**
- Lower the default/effective Gmail search cap for the spike, or add a separate internal fetch cap.
- Add tests for descriptor capabilities and `SourceRuntimeBundle.supports_federated_search`.
- Add a negative test for partial config that verifies secret values are not emitted.

**Risk Assessment:** **MEDIUM.** The architecture is aligned, but the config cap and union wiring need to match the bridge's real cost model.

---

## Plan 37-04

**Summary:** Good closeout plan. The report explicitly separates "Airweave compatibility" from "dotMD Gmail integration," which is the key AIR-02/AIR-03 distinction.

**Strengths**
- Requires report to be written after inspecting implementation.
- Calls out unused Airweave runtime systems explicitly.
- Includes SourceAsset deferred mapping instead of pretending attachment support is done.
- Requires full tests and no direct `airweave` imports.

**Concerns**
- **MEDIUM:** "Full test suite green" is necessary but may not verify live-ish Gmail failure modes unless mocked tests cover timeout, 401/403, 429, 5xx, malformed MIME, HTML-only, charset, and body cap.
- **LOW:** AGENTS.md update should avoid turning spike limitations into permanent operating guidance.

**Suggestions**
- Add a small implementation checklist to the report: implemented, deferred, intentionally avoided.
- Include the Gmail effective search cap and O(n) follow-up in the compatibility report.

**Risk Assessment:** **LOW-MEDIUM.** Documentation and verification are well scoped, assuming the remaining Plan 37-02 runtime risks are fixed first.

---

## Cycle 3 · Codex Overall Verdict

Cycle 2 HIGH #1 is resolved: the Telegram low-signal filter fix is complete in concept.

Cycle 2 HIGH #2 is mostly resolved, but requires the exact `ApplicationSourceProviderProtocol.export_changes()` signature to avoid a subtle conformance miss.

Cycle 2 HIGH #3 is only acknowledged, not sufficiently controlled. For a spike this can be acceptable only with a hard effective cap and an explicit follow-up.

Cycle 2 HIGH #4 is partially resolved. Per-call `httpx` timeouts are necessary, but they are not a search-level timeout when the implementation performs `1 + N` serial HTTP calls.

**Cycle 3 Codex Overall: MEDIUM-HIGH**

---

### Cycle 3 · OpenCode Review

## Plan 37-01: Vendor Airweave Platform Slice and DI Shims

### Summary
Plan 37-01 is mechanically sound. The vendored slice strategy (copy slimmed Airweave source/entity classes, replace heavy dependencies with stubs, ship `VENDOR_VERSION` for provenance) is well-scoped for a compatibility spike. The `GmailOAuthTokenProvider` with `threading.Lock` and margin-based expiry is correct. No Cycle 2 concerns are addressed here — those are in Plan 37-02 and 37-03.

### Strengths
- Double-checked locking pattern in `GmailOAuthTokenProvider.get_token()` is correct: outer check, lock acquire, inner check, then refresh.
- `expires_in - 300` margin-based expiry is standard practice and avoids edge-of-expiry races.
- `refresh_token` rotation handled: if Google responds with a new `refresh_token`, it updates credentials.
- `@source` decorator as no-op stub setting `ClassVar` attributes avoids the full Airweave decorator machinery.
- `test_no_airweave_package_required` is a strong integration-prevention test.

### Concerns
- **LOW** — `GmailOAuthTokenProvider` uses `httpx.post(...)` directly (sync, no timeout shown in pseudocode). Plan 37-02 adds explicit timeouts for `GmailBridge` httpx calls, but the token provider also makes an outbound HTTP call. Without a timeout on the OAuth refresh, a hung Google auth endpoint blocks ALL searches. The timeout fix from HIGH-4 should cover the token provider too.

### Suggestions
- Add the same `GMAIL_API_TIMEOUT_SECONDS` timeout to the token provider's `httpx.post` call (extract to shared constant, or use a separate `GMAIL_AUTH_TIMEOUT_SECONDS`).
- Verify during implementation that `refresh_token` rotation in the token provider is covered by a test.

### Risk Assessment: **LOW**
The vendored-slice approach is well-understood. The token provider is correct but has a minor timeout gap.

---

## Plan 37-02: BaseConnectorBridge ABC, GmailBridge, and Federated Search

### Summary
This is the most complex plan and carries the bulk of the Cycle 2 HIGH fixes. HIGH #1 (Telegram filter) and HIGH #4 (timeout) are properly resolved. HIGH #2 (protocol conformance) is addressed conceptually but has a signature gap in the plan pseudocode that must be corrected. HIGH #3 (O(n)) is correctly documented as a known limitation.

### Strengths
- `_is_low_signal_federated_candidate` correctly scopes to Telegram candidates via dual check (`namespace == "telegram"` OR `retrieval_kind.startswith("tg:")`). This correctly handles both the common case and any edge case where `retrieval_kind` is `None`.
- `GMAIL_API_TIMEOUT_SECONDS = 10.0` as module-level constant, used consistently for all httpx calls via `httpx.Timeout(read=10.0, connect=5.0)`. Connect timeout separate from read timeout is correct.
- Error boundary mapping is complete: `401/403 → SourceAuthError` (with cache clear), `429/5xx → SourceTemporaryUnavailable`, `httpx.TimeoutException → SourceTemporaryUnavailable`.
- `source_native_score=None` is safe because `_merge_with_federated_quota` does quota-based interleaving, not score-based fusion.
- `BaseConnectorBridge(ABC)` correctly defines the contract for any future connector-style bridge.
- Test coverage directly addresses each HIGH concern: timeout, `NotImplementedError` stubs for both `describe_source`/`export_changes`, Telegram filter paths, Gmail filter pass-through.

### Concerns
- **HIGH** — `export_changes` parameter signature is incomplete in the plan pseudocode. The Protocol requires:
  ```python
  def export_changes(
      self,
      cursor: str | None,
      limit: int,
      updated_after: str | None = None,
      updated_after_cursor: str | None = None,
  ) -> ApplicationSourceChangeBatch:
  ```
  Omitting the two optional parameters means the implementation won't structurally match `ApplicationSourceProviderProtocol`. Python's Protocol uses structural subtyping — if the method signature doesn't match, the type checker and runtime checks may reject it. This is a regression risk — the Plan 37-02 fix for HIGH-2 would itself be incomplete if the signature is wrong.

- **MEDIUM** — O(n) round-trips with no limit cap. With `GMAIL_API_TIMEOUT_SECONDS = 10.0`, `search_native(query, limit=500)` would make 501 HTTP calls, worst case ~5010s (83 minutes). The existing `fanout_federated` per-source timeout will kill the overall call, but the thread continues running wasteful HTTP calls in the background. Consider `limit = min(limit, 50)` in `GmailBridge.search_native` with a log warning.

- **MEDIUM** — `GmailApplicationSourceProvider` class doesn't explicitly inherit `ApplicationSourceProviderProtocol` in the plan. The existing Telegram pattern does: `class TelegramApplicationSourceProvider(ApplicationSourceProviderProtocol):`. Without the inheritance, mypy will flag the assignment to `provider: ApplicationSourceProviderProtocol | None` in `SourceRuntimeBundle`.

- **LOW** — `_merge_with_federated_quota` docstring still references `is_low_signal_telegram_text` directly. When the code is changed to use `_is_low_signal_federated_candidate`, the docstring should be updated.

- **LOW** — `SourceTemporarilyUnavailable` and `SourceAuthError` are custom exception classes that need to exist in the codebase. The plan doesn't specify where they live (likely `dotmd.core.exceptions` or inline in the bridge module). Verify they exist or add them explicitly.

### Suggestions
- Fix the `export_changes` signature with all four parameters matching the Protocol exactly.
- Add `limit = min(limit, 50)` in `GmailBridge.search_native` with a logger warning for values > 50.
- Add `GMAIL_API_TIMEOUT_SECONDS` to the token provider's OAuth refresh call.
- Update `_merge_with_federated_quota` docstring.
- Verify `SourceTemporarilyUnavailable` and `SourceAuthError` exist in the codebase.

### Risk Assessment: **HIGH** (one unresolved gap from Cycle 2)
The `export_changes` signature gap is the only item preventing HIGH #2 from being fully resolved. All other HIGH concerns are correctly addressed.

---

## Plan 37-03: Gmail Source Descriptor, Lifecycle Config, and Registry Wiring

### Summary
Plan 37-03 correctly handles the decision to put `refresh_token` on `GmailSourceConfig` (not `SourceAccess.delegated_to`) and adds proper partial-env-var warnings. However, the plan underspecifies the integration with the existing lifecycle/auth machinery. `SourceAccess.kind` is `Literal["none", "delegated"]` — no OAuth variant exists — and `SourceConfig` union type isn't shown being extended.

### Strengths
- `refresh_token` stored on `GmailSourceConfig`, not `SourceAccess.delegated_to`. Correct: `delegated_to` is for identity delegation strings (e.g., `"mcp-telegram"`), not secrets.
- Partial env-var detection with named warnings names the specific missing vars.
- `search_result_limit` validated 1-500 via Pydantic `Field(ge=1, le=500)`.
- `build_if_configured("gmail")` returns `None` when config absent — consistent with Telegram's optional pattern.

### Concerns
- **HIGH** — No OAuth access kind in `SourceAccess` or `DefaultSourceCredentialProvider`. The current code has `kind: Literal["none", "delegated"]` and only handles `auth_kind == "none"` and `auth_kind == "delegated"`. If Gmail registers with `auth_kind="oauth_refresh"`, `build("gmail")` will fail in `get_access()`. The plan must either: (a) add `"oauth"` to `SourceAccess.kind` and extend `get_access()`, (b) skip `get_access()` for Gmail in the factory, or (c) use `auth_kind="none"` and pass credentials directly from `GmailSourceConfig` in the build branch. None of these are specified in the plan.

- **HIGH** — `SourceConfig` union type not extended. Current: `type SourceConfig = FilesystemSourceConfig | TelegramSourceConfig`. `GmailSourceConfig` must be added, otherwise `SourceRuntimeFactory._require_config()` and strict Pydantic config records will fail. The plan doesn't mention this.

- **MEDIUM** — Factory dispatch for `"gmail"` namespace is implied but not shown. The plan must show the `if namespace == "gmail":` branch in `SourceRuntimeFactory.build()`, credentials provider wiring, and how `GmailApplicationSourceProvider` is constructed from `GmailSourceConfig`.

- **MEDIUM** — The relationship between `search_result_limit` (max 500) and the O(n) limitation from Plan 37-02 creates a tension. A limit of 500 means 501 HTTP round-trips. Plan 37-03 should lower the cap to match the spike's safe operating range.

### Suggestions
- Decide on the auth model: either add `"oauth"` (or `"direct"`) to `SourceAccess.kind` and extend `get_access()`, or bypass `SourceAccess` for Gmail and pass `GmailSourceConfig` directly to `GmailApplicationSourceProvider.__init__`.
- Either way, update `SourceConfig` union type explicitly.
- Show the factory dispatch code for the `"gmail"` case.
- Consider lowering `search_result_limit` maximum to 50 for the spike.

### Risk Assessment: **MEDIUM**
The conceptual design is correct but two integration points with the existing lifecycle system (`SourceAccess` auth model, `SourceConfig` union) are not addressed. These are mechanical additions, not architectural redesigns.

---

## Plan 37-04: AIR-02 Compatibility Report and End-to-End Verification

### Summary
Plan 37-04 defines a solid post-implementation verification phase. The requirement that the report is written after inspecting actual code is the right discipline for a spike. The report structure covers all AIR-02 categories and includes an honest assessment of what is not present.

### Strengths
- Report structure covers all AIR-02 categories explicitly: reusable, shims, avoid, missing pieces, extensibility, AIR-03 compliance.
- Explicit statement disclaiming Airweave's runtime/indexing stack is a good fence against scope creep.
- `grep` command for import verification is targeted at `src/dotmd/`.
- Full test suite green requirement is the final quality gate.

### Concerns
- **MEDIUM** — The verification grep command checks `backend/src/dotmd/` for `from airweave|import airweave`. The vendored files in `backend/src/dotmd/vendor/airweave/` will contain these patterns in comments and string literals. The grep should exclude the vendor directory:
  ```bash
  grep -r "^from airweave\|^import airweave" backend/src/dotmd/ --include="*.py" --exclude-dir=vendor
  ```
- **LOW** — "No unreplaced `[TBD: ...]` placeholders" is a documentation quality check that `pytest` can't verify. Add a simple `grep "[TBD:" docs/gmail-airweave-compatibility-spike.md` step.

### Suggestions
- Fix the import-verification grep to exclude the vendor directory.
- Add a separate documentation verification step (grep for `[TBD:` in the report).

### Risk Assessment: **LOW**
End-to-end verification plan is well scoped. The grep command has a false-positive issue but it is minor.

---

## Cycle 3 · OpenCode Cross-Cutting Concerns

| # | Concern | Severity | Affected Plans |
|---|---------|----------|---------------|
| N1 | `export_changes` pseudocode missing `updated_after`/`updated_after_cursor` params — blocks HIGH #2 resolution | **HIGH** | 37-02 |
| N2 | No OAuth access kind in `SourceAccess`/`SourceAuthSchema` — Gmail will fail in `get_access()` with `auth_kind="oauth_refresh"` | **HIGH** | 37-03 |
| N3 | `SourceConfig` union type not extended with `GmailSourceConfig` — Pydantic/factory will reject it | **HIGH** | 37-03 |
| N4 | O(n) round-trips with no limit cap — worst case 83 minutes for limit=500 in background thread | MEDIUM | 37-02, 37-03 |
| N5 | Factory dispatch for `"gmail"` + bridge/provider construction not shown in plan | MEDIUM | 37-03 |
| N6 | `GmailApplicationSourceProvider` doesn't inherit `ApplicationSourceProviderProtocol` in plan pseudocode | MEDIUM | 37-02 |
| N7 | `_merge_with_federated_quota` docstring still references old filter — misleading for maintainers | LOW | 37-02 |
| N8 | `GmailOAuthTokenProvider` httpx call has no explicit timeout — hung auth blocks all searches | LOW | 37-01 |
| N9 | Import-verification grep in Plan 37-04 will false-positive on vendored files | LOW | 37-04 |

**Cycle 3 OpenCode Overall: MEDIUM-HIGH**

Three new HIGH concerns (N1-N3) are all implementation-level gaps fixable without architectural redesign:
1. N1: Add `updated_after`/`updated_after_cursor` to `export_changes` — 2-line fix.
2. N2: Decide OAuth auth model and extend types — mechanical change to 3-4 types.
3. N3: Add `GmailSourceConfig` to `SourceConfig` union — 1-line fix.

---

## Cycle 3 · Consensus Summary

Both reviewers assessed the Cycle 2 HIGH fixes and converged on the same three new HIGH concerns.

### What Changed Since Cycle 2 (HIGHs Status in Cycle 3)

| Cycle 2 HIGH | Resolution in Plans | Cycle 3 Verdict |
|---|---|---|
| HIGH #1: Telegram filter drops Gmail | `_is_low_signal_federated_candidate` helper, tests verify both paths | **FULLY RESOLVED** |
| HIGH #2: ApplicationSourceProviderProtocol conformance | `NotImplementedError` stubs for `describe_source`/`export_changes` | **PARTIALLY RESOLVED** — `export_changes` signature is missing `updated_after`/`updated_after_cursor` params |
| HIGH #3: O(n) metadata fetch round-trips | Documented as known limitation, follow-up task planned | **ACKNOWLEDGED** — acceptable for spike; no hard cap is a medium concern |
| HIGH #4: No search-level timeout | `GMAIL_API_TIMEOUT_SECONDS=10.0`, explicit `httpx.Timeout`, `TimeoutException` mapped, tested | **SUBSTANTIALLY RESOLVED** — per-call timeouts in place; overall search deadline still lacks a hard cap for high `limit` values |

### New HIGHs (Cycle 3)

1. **HIGH — `export_changes` signature incomplete (N1):** Both reviewers independently flagged that the plan pseudocode for `GmailApplicationSourceProvider.export_changes()` is abbreviated as `export_changes(self, cursor, limit, ...)` but the actual `ApplicationSourceProviderProtocol` requires two additional parameters: `updated_after: str | None = None` and `updated_after_cursor: str | None = None`. Python's structural subtyping will reject the abbreviated signature. The fix is trivial (2 lines) but must be explicit in the plan.

2. **HIGH — `SourceAccess.kind` has no OAuth variant (N2):** The current `source_lifecycle.py` has `kind: Literal["none", "delegated"]` and `DefaultSourceCredentialProvider.get_access()` only handles `auth_kind == "none"` and `auth_kind == "delegated"`. Gmail's descriptor registers with `auth_kind="oauth_refresh"` which will raise `SourceLifecycleConfigError(f"auth_kind unsupported")` before the build branch can run. Plan 37-03 must specify how to resolve this: either extend the Literal and add a handler, or bypass `get_access()` in the Gmail build branch.

3. **HIGH — `SourceConfig` union type not extended (N3):** `type SourceConfig = FilesystemSourceConfig | TelegramSourceConfig` in `source_lifecycle.py` must include `GmailSourceConfig`. Without it, `SourceRuntimeFactory` and Pydantic validation will reject `GmailSourceConfig` instances. One-line fix but must be explicit.

### Agreed Strengths (Cycle 3)

- **HIGH #1 fully resolved.** `_is_low_signal_federated_candidate` is correctly scoped by `namespace == "telegram"` or `retrieval_kind.startswith("tg:")`. Tests verify both Telegram filtering and Gmail pass-through. Regression-safe.
- **HIGH #4 substantially resolved.** `GMAIL_API_TIMEOUT_SECONDS = 10.0` applied via `httpx.Timeout(read=10.0, connect=5.0)` to all Gmail API calls. `httpx.TimeoutException` mapped to `SourceTemporaryUnavailable`. Tests verify the constant and the exception mapping. The residual concern (no overall search deadline) is acceptable for a spike.
- **`GmailSourceConfig.refresh_token` design is correct.** Moving secrets off `SourceAccess.delegated_to` and onto a typed config field is the right call and prevents secret leaks through reprs/logs.
- **Partial env-var warnings are correct.** Naming the specific missing vars makes misconfigured deployments debuggable.

### Agreed Concerns (Cycle 3)

1. **HIGH — `export_changes` signature gap** (both reviewers). Two optional params missing in pseudocode. Must be exact match for Protocol structural subtyping.

2. **HIGH — `SourceAccess.kind` OAuth gap** (OpenCode). `DefaultSourceCredentialProvider.get_access()` will raise for `auth_kind="oauth_refresh"`. Plan must specify resolution.

3. **HIGH — `SourceConfig` union not extended** (OpenCode). Pydantic/factory will reject `GmailSourceConfig` unless union is updated.

4. **MEDIUM — O(n) fetch with no cap** (both reviewers). `limit=500` allows 501 serial HTTP calls. Even with per-call timeouts, the background thread wastes resources. A hard cap of `min(limit, 50)` in `GmailBridge.search_native` is recommended for the spike.

5. **MEDIUM — `GmailApplicationSourceProvider` inheritance not shown** (OpenCode). Should explicitly inherit `ApplicationSourceProviderProtocol` for type-checker compatibility, matching Telegram's pattern.

6. **MEDIUM — Factory dispatch code not shown in Plan 37-03** (OpenCode). The `if namespace == "gmail":` branch in `SourceRuntimeFactory.build()` and `GmailApplicationSourceProvider` construction from config/token_provider must be shown explicitly.

7. **LOW — OAuth token provider httpx call has no explicit timeout** (both reviewers). Hung token endpoint blocks all searches. Should use the same `GMAIL_API_TIMEOUT_SECONDS` constant.

### Divergent Views (Cycle 3)

- **Hard limit cap vs. documented limitation** (Codex requires cap, OpenCode recommends it): Codex says O(n) without a cap is HIGH for a spike; OpenCode classifies it MEDIUM since `fanout_federated` timeout will kill the overall call. Consensus: a cap at 50 is recommended but not blocking for an initial spike, provided it is in the plan.
- **Overall search deadline** (Codex raised, OpenCode did not as HIGH): Codex wants a `GMAIL_SEARCH_TOTAL_TIMEOUT_SECONDS` deadline; OpenCode notes the existing `fanout_federated` per-source timeout provides this implicitly. Consensus: document the fanout timeout as the effective deadline; a separate constant is optional.

### Cycle 3 Risk Summary

| Plan | Cycle 2 Risk | Cycle 3 Risk | Change |
|------|-------------|-------------|--------|
| 37-01 | MEDIUM | LOW-MEDIUM | Token cache design resolved; minor OAuth timeout gap remains |
| 37-02 | HIGH | HIGH | `export_changes` signature gap is new HIGH; filter/timeout HIGHs resolved |
| 37-03 | MEDIUM-HIGH | MEDIUM-HIGH | `SourceAccess` OAuth gap and `SourceConfig` union gap are new HIGHs |
| 37-04 | LOW-MEDIUM | LOW | Grep false-positive minor; overall low risk |

**Cycle 3 Overall: MEDIUM-HIGH**

Three new HIGH concerns (N1: `export_changes` signature, N2: `SourceAccess.kind` OAuth, N3: `SourceConfig` union) remain unresolved. All three are small mechanical fixes — no architectural redesign required. Fix these three items and the plans are ready for execution.

---

<!-- ═══════════════════════════════════════════════════════════════
     CYCLE 4  (2026-05-11 — plans updated to address Cycle 3 HIGHs:
               N1: export_changes 4-param Protocol signature added (37-02);
               N2: SourceRuntimeFactory.build("gmail") bypasses get_access(),
                   constructs SourceAccess(kind="none") directly (37-03);
               N3: SourceConfig union updated to include GmailSourceConfig (37-03);
               Tests added for all three: test_gmail_provider_export_changes_accepts_all_protocol_params,
               test_build_gmail_bypasses_credential_provider, test_source_config_union_includes_gmail)
     ═══════════════════════════════════════════════════════════════ -->

## Cycle 4 — 2026-05-11T17:00:00Z

*Plans were updated after Cycle 3 to address the three HIGHs: N1
(`export_changes` exact 4-param Protocol signature now specified in 37-02 with
a dedicated test); N2 (`SourceRuntimeFactory.build("gmail")` now explicitly
bypasses `DefaultSourceCredentialProvider.get_access()` and constructs
`SourceAccess(kind="none")` directly, with monkeypatched negative test in 37-03);
N3 (`SourceConfig` union explicitly updated to include `GmailSourceConfig`, with
`typing.get_args()` test in 37-03). This cycle reviews the updated plans.*

---

### Cycle 4 · Codex Review

## Summary

The Cycle 4 plans substantially address the three Cycle 3 HIGHs. N1, N2, and N3 are
resolved as written at the plan level, with explicit acceptance tests. The overall
architecture also stays aligned with AIR-03 by routing Gmail through the shared source
registry/lifecycle/federated provider path instead of creating a separate Airweave lane.
Remaining risks are mostly implementation precision: making sure Gmail search/read outputs
actually map to dotMD's `SourceUnit`/read contracts, preventing OAuth refresh hangs, and
keeping vendored Airweave code isolated from heavy platform dependencies.

## Strengths

- The three prior HIGHs now have concrete code-level acceptance criteria and tests.
- Gmail is intentionally federated-only, which fits the finding that Airweave's `GmailSource.search()` is absent.
- `SourceRuntimeFactory.build("gmail")` correctly avoids forcing OAuth refresh tokens through `SourceAccess.delegated_to`.
- Registry/lifecycle wiring keeps Gmail in the same architecture as filesystem and Telegram, satisfying AIR-03.
- The compatibility report is evidence-based and explicitly separates reusable, shimmed, and avoided Airweave pieces.
- Timeout handling is planned for Gmail API calls, with clear auth and temporary-unavailable error boundaries.

## Concerns

- **MEDIUM: AIR-01 SourceDocument/SourceUnit proof is still a little under-specified.**
  The plans clearly cover `SearchCandidate` and `read_unit_window`, but AIR-01 says the spike
  adapts Airweave connector-style output into `SourceDocument`, `SourceUnit`, optional
  `SourceAsset`, and `SearchCandidate` contracts. Since `export_changes()` is intentionally
  unsupported, the plan should explicitly state where `SourceDocument` and `SourceUnit` mapping
  is proven for Gmail, or explain why federated-only read windows are the accepted `SourceUnit` proof.

- **MEDIUM: OAuth token refresh lacks an explicit timeout in Plan 37-01.**
  Cycle 3 marked this LOW, but it can block all Gmail search/read flows if the refresh endpoint
  hangs. Add `timeout=httpx.Timeout(..., connect=...)` or a module-level token timeout constant.

- **MEDIUM: Vendored Airweave isolation depends on import tests being broad enough.**
  Grepping for `airweave.domains/core/schemas` helps, but import-time failures can also come
  from other transitive platform dependencies. The import test should instantiate or minimally
  exercise `GmailSource`, Gmail entities, and config objects, not only import one module.

- **LOW: 401/403 handling may be too broad.**
  Clearing token cache on 401 is right. For 403, Gmail may mean insufficient scope, disabled
  API, quota policy, or forbidden mailbox access. Treating all 403s as `SourceAuthError` is
  acceptable for a spike, but the report should document this simplification.

- **LOW: O(n) message fetch is acceptable but should be quota-aware.**
  With `search_result_limit <= 500`, worst-case API fanout is still high. For the spike this
  is fine, but keep default 20 and avoid encouraging large limits.

- **LOW: Secret handling needs explicit guardrails.**
  `GmailSourceConfig.refresh_token` in config is acceptable for env-based local deployment,
  but tests/docs should avoid printing model dumps, reprs, or warning messages that include
  the refresh token.

## Suggestions

- Add an explicit test proving Gmail native result → dotMD read/search contracts: `GmailBridge.to_search_candidate()` produces a stable Gmail ref, and `read_unit_window()` resolves that ref into the expected unit/window shape.
- In `docs/gmail-airweave-compatibility-spike.md`, add a short AIR-01 mapping table: `Gmail message → SourceDocument?`, `Gmail message/body → SourceUnit/read window`, `Gmail attachment → deferred SourceAsset`, `Gmail search hit → SearchCandidate`.
- Add timeout to `GmailOAuthTokenProvider.get_token()` now; it is small and removes a real operational footgun.
- Add tests that partial Gmail env configuration logs only missing variable names, never present values.
- Make the `SourceAuthError` / `SourceTemporaryUnavailable` import decision deterministic. Prefer importing from `dotmd.core.exceptions`; only define locally if the exceptions truly do not exist.

## Risk Assessment

**Overall risk: MEDIUM-LOW.**
The architecture is coherent and the prior HIGHs are resolved in the written plans. The remaining
risk is not architectural direction; it is contract completeness and operational polish. The biggest
thing to tighten before execution is the explicit proof that Gmail data maps to the dotMD
source/read/search contracts required by AIR-01, despite being federated-only.

---

### Cycle 4 · OpenCode Review

## Plan 37-01: Vendor Airweave Platform Slice and DI Shims (Wave 1)

**Summary:** Well-architected vendoring strategy that surgically extracts only the
source/entity classes from Airweave without inheriting its heavy infrastructure stack. The
DI shim layer (logger, http client, token provider) is appropriately minimal and the
threading.Lock-based token refresh with margin-based expiry is a solid production pattern.
The SparseEmbedding→`object` stub and `@source`→no-op decorator stub are pragmatic choices
that keep the dependency surface small. One LOW concern from Cycle 3 remains unaddressed.

**Strengths:**
- Surgical vendoring: only platform files plucked from Airweave — avoids the entire Temporal/Vespa/domain stack
- Provenance tracking via VENDOR_VERSION and VENDOR_NOTES.md for every file — critical for maintenance when Airweave upstream changes
- GmailOAuthTokenProvider's threading.Lock + double-check inside lock + `expires_in - 300` margin is correct and race-free for a single-process Python app
- Must-have truth "5 threads, only 1 httpx.post call" is testable and proves the lock works
- No `airweave.domains`, `airweave.core`, `airweave.schemas` survives — grep-based acceptance criteria is verifiable
- Stub types (`SparseEmbedding → object`, no-op `@source`) are honest about what's not needed

**Concerns:**
- **MEDIUM — Vendored files must have imports rewritten from `from airweave.*` to `from dotmd.vendor.airweave.*`.**
  The plan is silent on import path rewriting. Without it, the vendored tree won't import. This is
  mechanical but critical — all cross-file imports within the vendored slice must be identified and updated.
- **LOW — `httpx.post()` in `GmailOAuthTokenProvider.get_token()` still has no explicit timeout.**
  Was flagged as LOW in Cycle 3 by both reviewers and remains unfixed. One keyword argument fix:
  `httpx.post(url, ..., timeout=10.0)`.
- **MEDIUM — `SparseEmbedding` stub as bare `object` could cause runtime failures** if any vendored
  code does `isinstance(x, SparseEmbedding)` or `SparseEmbedding.from_list(...)`. Plan should verify
  no such usage exists in the vendored entity files, or provide a minimal stub class.

**Suggestions:**
- Add explicit timeout to the `httpx.post()` call in `GmailOAuthTokenProvider.get_token()`
- Add acceptance criterion: `grep -r 'from airweave\.' backend/src/dotmd/vendor/airweave/*.py` returns zero matches (only `from dotmd.vendor.airweave.` forms should exist)
- Verify that none of the vendored entity code does `isinstance` checks against `SparseEmbedding`; if it does, provide a stub class with `from_list` classmethod rather than bare `object`

**Risk Assessment:** MEDIUM — Import rewriting gap is the main risk. LOW timeout concern is trivial to fix.

---

## Plan 37-02: BaseConnectorBridge ABC, GmailBridge, Federated Search (Wave 2)

**Summary:** The strongest plan of the four. The BaseConnectorBridge ABC provides a clean,
generic abstraction layer that satisfies D-03 (no Airweave-only lane). GmailBridge's direct
Gmail API approach is correct given Airweave's `GmailSource.search()` is unimplemented. The
`_is_low_signal_federated_candidate` generalization in `service.py` is elegant — namespace-based
routing avoids coupling the merge logic to specific source implementations. Error boundaries
(401→SourceAuthError with token cache clear, 429/5xx→SourceTemporaryUnavailable) are comprehensive.

**Strengths:**
- BaseConnectorBridge(ABC) with 3 abstract methods is the right level of abstraction — generic enough for any HTTP API source, specific enough to be useful
- GmailBridge's error boundary taxonomy (SourceAuthError, SourceTemporaryUnavailable) matches real Gmail API failure modes
- Token cache clearing on 401 is production-grade — stale tokens won't cause cascading failures
- O(n) round-trips explicitly documented as known limitation — honest about tradeoffs, appropriate for a spike
- `source_native_score=None` on federated candidates is correct: federated results bypass RRF entirely, flow through `_merge_with_federated_quota` quota merge
- `export_changes()` exact 4-param signature with `updated_after: str | None = None` and `updated_after_cursor: str | None = None` matches Protocol — **Cycle 3 HIGH N1 FULLY RESOLVED**
- `_is_low_signal_federated_candidate()` namespace-based routing keeps Telegram and Gmail filter logic separate without coupling the service layer to provider internals
- httpx timeout at both connect (5.0s) and read (10.0s) level — prevents hanging on slow Gmail API endpoints

**Concerns:**
- **MEDIUM — `_is_low_signal_federated_candidate` returns `False` for all non-Telegram candidates.**
  Gmail candidates with empty bodies or single-character content pass through unfiltered. Should
  there be a minimal quality gate (e.g., at least N characters)? Or is this intentionally deferred?
  The plan is silent on this.
- **LOW — `to_search_candidate()` `retrieval_kind` value not specified.**
  The plan mentions `tg:fts` for Telegram. What value goes for Gmail (e.g., `"gmail:api"`)? Without it,
  downstream consumers can't distinguish result sources in filter logic.
- **LOW — `export_changes` Protocol signature verification.**
  Verify that `ApplicationSourceProviderProtocol.export_changes` in `source_provider.py` actually has
  exactly this 4-param signature. The test should catch any mismatch, but plan should cite the Protocol's
  actual method signature for certainty.

**Suggestions:**
- Specify `retrieval_kind` value for Gmail candidates (e.g., `"gmail:api"`)
- Add a comment at `_is_low_signal_federated_candidate` about why Gmail candidates receive no quality filtering (intentionally deferred or permissive)
- Verify the `export_changes` test actually checks structural compatibility with the Protocol

**Risk Assessment:** LOW — The plan is thorough, follows the established Telegram pattern precisely, and resolves Cycle 3 HIGH N1. The concerns are minor clarifications.

---

## Plan 37-03: Gmail Source Descriptor, Lifecycle Config, Registry Wiring (Wave 2)

**Summary:** Clean integration into the existing source lifecycle system. All three contract
boundaries (descriptor, config, runtime factory) are properly extended without disrupting the
existing filesystem and Telegram paths. The `SourceAccess(kind="none")` bypass for `get_access()`
is the correct fix for the OAuth gap. The env var activation logic (all-3-or-nothing with
partial-var warnings) is good UX.

**Strengths:**
- `SourceAccess(kind="none")` directly constructed, never calls `DefaultSourceCredentialProvider.get_access()` — **Cycle 3 HIGH N2 FULLY RESOLVED**
- `type SourceConfig = FilesystemSourceConfig | TelegramSourceConfig | GmailSourceConfig` — **Cycle 3 HIGH N3 FULLY RESOLVED**
- `test_build_gmail_bypasses_credential_provider` monkeypatches `get_access()` to assert it is NOT called — strong negative test
- `test_source_config_union_includes_gmail` verifies `GmailSourceConfig in typing.get_args(SourceConfig)` — strong positive test
- `GmailSourceConfig.refresh_token` is NOT in `SourceAccess.delegated_to` — keeps credential storage in config, matches how Telegram's credentials work
- `search_result_limit` validated 1-500 with default 20 — bounded range, prevents resource exhaustion
- Partial env var detection with specific naming of missing vars is good operations UX
- `build_if_configured("gmail")` returns None when `DOTMD_GMAIL_CLIENT_ID` not set — follows the Telegram pattern exactly

**Concerns:**
- **MEDIUM — `GmailSourceConfig.client_secret` and `refresh_token` are plain `str` fields.**
  If the config is ever logged, serialized with `model_dump()`, or captured in error messages, secrets
  leak. Consider Pydantic `SecretStr` for these two fields. `client_id` is a public identifier and
  can remain `str`.
- **MEDIUM — Tight coupling between lifecycle layer and OAuth token implementation.**
  `GmailApplicationSourceProvider` receives `token_provider` as a constructor argument, and
  `SourceRuntimeFactory.build()` constructs the token provider directly from config secrets.
  If the token provider API changes, both the provider and the factory must change. The Telegram
  pattern uses a factory function passed to `source_runtime_factory_from_settings()` — Gmail
  should follow the same pattern for consistency.
- **LOW — No automated enforcement that `GmailSource()` is never instantiated outside source_lifecycle.py.**
  A grep in Plan 37-04's verification script is the only check. Consider a test that imports
  `gmail_provider` and verifies no direct `GmailSource` construction happens outside the lifecycle layer.
- **LOW — `extra="forbid"` with `strict=True` may break forward compatibility.** If a future
  connector adds new config fields and the ConfigDict is not updated, validation fails hard. Tradeoff
  is acceptable for a spike, but should be documented.

**Suggestions:**
- Use Pydantic `SecretStr` for `client_secret` and `refresh_token` fields
- Extract Gmail client construction into a factory function, passed to `source_runtime_factory_from_settings()`, matching Telegram's pattern
- Add a test that verifies `GmailSourceConfig.__repr__()` does not expose `client_secret` or `refresh_token` values
- Document why `extra="forbid"` is chosen over `extra="ignore"` in the model docstring

**Risk Assessment:** MEDIUM — The secrets-in-clear-config concern is the main issue. The plan
correctly resolves both Cycle 3 HIGHs N2 and N3.

---

## Plan 37-04: AIR-02 Compatibility Report and End-to-End Verification (Wave 3)

**Summary:** Well-defined documentation deliverable with concrete structure and verification
commands. The report template covers all three AIR-02 categories plus the extensibility
assessment required for D-03 compliance. The verification script is practical and testable.
This plan is a documentation + cleanup phase and carries low implementation risk.

**Strengths:**
- Report structure covers all three AIR-02 categories plus extensibility, deferred mappings, and AIR-03 compliance checklist
- "Evidence-based" requirement — report cites actual code locations, not speculation
- `GmailSource.search()` absence is explicitly called out with cited Airweave source location — honest accounting
- Verification commands are specific and executable
- AGENTS.md update is scoped to Phase 37 architectural decisions — targeted, not a full rewrite
- Import-verification grep now excludes vendor directory (`--exclude-dir=vendor`) to avoid false positives on vendored files — correct fix from Cycle 3

**Concerns:**
- **LOW — End-to-end integration test not specified.**
  The plan adds "lifecycle tests" but doesn't specify whether these test the full
  `build_if_configured → search_native` path end-to-end or just isolated lifecycle wiring.
  An integration test that exercises the full Gmail federated search path (with a mock HTTP backend)
  would provide strong confidence that Plans 37-01 through 37-03 properly integrate.
- **LOW — grep pattern may miss multi-line imports.**
  `grep -r "^from airweave\|^import airweave"` won't catch multi-line imports or imports with
  leading whitespace. A more robust pattern: `grep -rE '(^|\s)(from|import)\s+airweave'`.
- **LOW — TBD placeholder verification.**
  "No unreplaced `[TBD: ...]` placeholders" is a documentation quality check that `pytest` can't
  verify. Add a simple `grep "[TBD:" docs/gmail-airweave-compatibility-spike.md` step.

**Suggestions:**
- Add an integration test using `pytest-httpx` or `responses` to mock the Gmail API and test the full `build_if_configured("gmail") → search_native(query) → to_search_candidate() → fanout_federated()` flow
- Use a more robust grep pattern for import verification: `grep -rPE '(^|\s)(from|import)\s+airweave'`
- Add a verification step: `grep "\[TBD:" docs/gmail-airweave-compatibility-spike.md || echo "No TBD placeholders: OK"`

**Risk Assessment:** LOW — Documentation phase with clear acceptance criteria and verifiable outputs.

---

## Cycle 4 · Consensus Summary

### Cycle 3 HIGH Resolution Status

| HIGH | Issue | Cycle 4 Verdict | Evidence |
|------|-------|-----------------|---------|
| **N1** | `export_changes` signature incomplete | **FULLY RESOLVED** | Plan 37-02 specifies exact 4-param Protocol signature including `updated_after: str \| None = None` and `updated_after_cursor: str \| None = None`. Test `test_gmail_provider_export_changes_accepts_all_protocol_params` explicitly verifies all four params are accepted. |
| **N2** | `SourceAccess.kind` OAuth gap | **FULLY RESOLVED** | Plan 37-03 explicitly bypasses `DefaultSourceCredentialProvider.get_access()` and constructs `SourceAccess(kind="none")` directly. Test `test_build_gmail_bypasses_credential_provider` monkeypatches `get_access()` to assert it is NOT called. |
| **N3** | `SourceConfig` union not extended | **FULLY RESOLVED** | Plan 37-03 explicitly updates union to `FilesystemSourceConfig \| TelegramSourceConfig \| GmailSourceConfig`. Test `test_source_config_union_includes_gmail` verifies `GmailSourceConfig in typing.get_args(SourceConfig)`. |

### Agreed Strengths (Cycle 4)

- The surgical vendoring strategy extracts only needed Airweave source/entity classes without pulling in Temporal, Vespa, or organization-layer dependencies
- `BaseConnectorBridge(ABC)` provides a generic, reusable abstraction that satisfies D-03 — not specific to Gmail
- The `_is_low_signal_federated_candidate` generalization in `service.py` uses namespace-based routing, keeping the merge layer decoupled from provider internals
- `GmailOAuthTokenProvider` with `threading.Lock` + double-check + `expires_in-300` margin is a correct, race-free pattern for single-process Python
- Error boundaries (401→token clear+SourceAuthError, 429/5xx→SourceTemporaryUnavailable) are production-grade
- All three Cycle 3 HIGHs have explicit must-have truths and corresponding tests that prove resolution
- The plan integration respects existing patterns: descriptor→config→lifecycle→federated fan-out — no custom integration lane

### Agreed Concerns (Cycle 4)

| # | Concern | Severity | Plans Affected |
|---|---------|----------|----------------|
| C1 | **Vendored import rewriting not specified in plan** — vendored `.py` files still contain `from airweave.*`; must be rewritten to `from dotmd.vendor.airweave.*` | MEDIUM | 37-01 |
| C2 | **OAuth secrets in plain Pydantic `str` fields** — `client_secret` and `refresh_token` could leak via `model_dump()`, repr, or error messages; use `SecretStr` | MEDIUM | 37-03 |
| C3 | **`SparseEmbedding` stub as bare `object`** — risk if vendored code does `isinstance(x, SparseEmbedding)` or `SparseEmbedding.from_list(...)` | MEDIUM | 37-01 |
| C4 | **`httpx.post()` timeout unspecified in token provider** — hung OAuth endpoint blocks all searches; one-line fix | LOW | 37-01 |
| C5 | **No end-to-end integration test** — no single test exercises full `build → search_native → to_search_candidate → fanout_federated` path with mocked HTTP | LOW | 37-04 |
| C6 | **Gmail content quality gate absent** — `_is_low_signal_federated_candidate` passes all Gmail candidates unconditionally; should be documented as intentional | LOW | 37-02 |
| C7 | **AIR-01 SourceDocument/SourceUnit proof implicit** — federated-only path covers `SearchCandidate` and `read_unit_window` but AIR-01 also mentions `SourceDocument` and `SourceUnit`; compatibility report should explicitly map these | MEDIUM | 37-04 |

### Divergent Views (Cycle 4)

- **Secrets handling severity** (OpenCode rates MEDIUM, Codex rates LOW): OpenCode focuses on `SecretStr` for `client_secret`/`refresh_token` as a MEDIUM concern; Codex acknowledges it as LOW with "acceptable for env-based local deployment." Consensus for a single-user server: `SecretStr` is a hardening recommendation, not a blocker for execution.
- **Import path rewriting explicitness** (OpenCode raises as MEDIUM, Codex does not explicitly call out): OpenCode flags that the plan is silent on how vendored `from airweave.*` imports get rewritten; Codex focuses on test coverage. Consensus: the rewriting step should be explicit in must-have truths of Plan 37-01 — add "no `from airweave.*` in vendored tree" to acceptance criteria.

### Cycle 4 Risk Summary

| Plan | Cycle 3 Risk | Cycle 4 Risk | Change |
|------|-------------|-------------|--------|
| 37-01 | LOW-MEDIUM | LOW-MEDIUM | Import rewriting gap surfaced; SparseEmbedding stub risk noted; token timeout still LOW |
| 37-02 | HIGH | LOW | All Cycle 3 HIGHs resolved; only minor LOW/MEDIUM clarifications remain |
| 37-03 | MEDIUM-HIGH | MEDIUM | N2 and N3 fully resolved; secrets-in-clear-config is new MEDIUM |
| 37-04 | LOW | LOW | Grep false-positive fixed; minor LOW enhancements suggested |

**Cycle 4 Overall: LOW-MEDIUM**

All three Cycle 3 HIGHs (N1: `export_changes` signature, N2: `SourceAccess.kind` OAuth gap,
N3: `SourceConfig` union) are FULLY RESOLVED. No new HIGH concerns raised in Cycle 4.
Remaining concerns are MEDIUM implementation details (import rewriting, secrets hardening,
SparseEmbedding stub verification) and LOW polish items. The plans are ready for execution.
