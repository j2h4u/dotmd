---
phase: 37
reviewers: [codex, opencode]
reviewed_at: 2026-05-11T10:16:26Z
plans_reviewed:
  - 37-01-vendor-airweave-platform-slice-PLAN.md
  - 37-02-gmail-bridge-federated-search-PLAN.md
  - 37-03-gmail-registry-lifecycle-wiring-PLAN.md
  - 37-04-airweave-compatibility-report-and-tests-PLAN.md
---

# Cross-AI Plan Review — Phase 37

## Codex Review

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

## OpenCode Review

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
- **HIGH — No MIME decoding edge case handling specified.** The plan says "decodes base64url-encoded MIME body parts" but doesn't address:
  - **Multipart messages** (multipart/alternative, multipart/mixed): which part is the "body"? If the email has both `text/plain` and `text/html`, does the bridge prefer plain text or HTML-stripped?
  - **No text/plain part** (HTML-only emails): HTML decoding and tag stripping needed.
  - **Charset handling**: Content-Type charset may not be UTF-8. The bridge must decode using the declared charset, not assume.
  - **base64 vs base64url**: Gmail API returns both variants depending on the endpoint. The decoder must handle both.
  - **Large bodies**: The plan loads full body into memory for `read_unit_window`. What's the size guardrail? A 100MB attachment shouldn't crash the MCP server.
- **MEDIUM — D-03 "generic bridge" has no design in this plan.** The plan is titled "AirweaveConnectorBridge and Gmail federated search," and D-03 says "Bridge must be generic across all BaseSource subclasses, not Gmail-specific." Yet the plan only describes Gmail-specific API calls. Where does the generic bridge abstraction live? What's the abstract interface? How would a second connector (say, Slack or Notion) plug into the same bridge without rewriting it? The bridge class should be abstract with `search_native(query, limit) -> list[SearchCandidate]` and `read_unit_window(ref) -> SourceUnitWindow` as its protocol, with `GmailBridge` as one implementation. This abstraction is missing.
- **MEDIUM — No error handling for Gmail API failures.** `GET /messages?q=...` can return 401 (expired token), 429 (rate limit), 500 (transient server error), or return empty results (valid but confusing). The bridge should:
  - Return `[]` on empty results (correct, not an error).
  - Raise `SourceAuthError` on 401 → triggers credential refresh upstream.
  - Raise `SourceTemporaryUnavailable` on 429/5xx → fusion can degrade gracefully.
  - Log transient errors with throttling to avoid log spam.
- **LOW — `SearchCandidate` doesn't reference `SourceDocument` or `SourceUnit`.** The success criteria say "maps into `SourceDocument`, `SourceUnit`, optional `SourceAsset`, and `SearchCandidate`." The plan only shows `SearchCandidate` mapping. For a federated-search-only source, `SourceDocument` and `SourceUnit` may be virtual (constructed at query time from `SearchCandidate` metadata), but this should be explicitly stated in the design.

#### Suggestions

1. **Audit `fusion.py` RRF implementation for `None` score handling** before accepting the plan. If it doesn't handle `None`, either add a positional decay score (`1.0 / (rank + 1)`) in the bridge or patch the fusion layer.
2. **Specify MIME body decoding logic in a decision record** covering: part selection order, charset handling, HTML fallback, size limits (e.g., 1MB cap on body, truncate with `...` suffix).
3. **Define `BaseConnectorBridge` abstract class** with `search_native(query, limit) -> list[SearchCandidate]` and `read_unit_window(ref) -> SourceUnitWindow` as its protocol. `GmailBridge` implements it. This satisfies D-03.
4. **Add error classification and retry strategy** for Gmail API HTTP responses.
5. **Clarify `SourceDocument`/`SourceUnit` mapping** for federated-search-only sources — are they virtual/on-the-fly, or is a no-op stub acceptable?

---

### Plan 37-03: Gmail Source Descriptor, Lifecycle Config, and Registry Wiring

#### Summary

Cleanly follows the filesystem/Telegram pattern for registry registration and lifecycle wiring. The credential flow through `SourceCredentialRef` → `DefaultSourceCredentialProvider` → `GmailOAuthTokenProvider` is architecturally correct.

#### Strengths

- **Correct capability set: FEDERATED_SEARCH + READ_UNIT_WINDOW, no LOCAL_SYNC.** Accurately reflects that Gmail is a read-only query source with no indexing/trickle involvement.
- **Credential provider boundary is respected.** OAuth tokens don't leak into the registry or search layer — they stay behind the `CredentialProviderProtocol` abstraction.
- **Env var activation is low-friction.** `DOTMD_GMAIL_*` vars follow the existing convention (similar to `DOTMD_TELEGRAM_*`).

#### Concerns

- **MEDIUM — Credential storage location mismatch.** User decision D-05 says credentials live in `~/.secrets/dotmd-gmail.env`, but the plan wires env vars directly. These are not the same thing — the plan should specify how the `.env` file is loaded (via `source_lifecycle.py`? via `start.sh`? via `SourceRuntimeFactory._load_secrets()`?). If the container doesn't have `~/.secrets/` bind-mounted, the credentials will be missing.
- **MEDIUM — No credential validation at registration time.** If `DOTMD_GMAIL_*` vars are set but the refresh token is expired or invalid, the descriptor should still register (degraded mode) but log a warning. Currently, the plan doesn't specify what happens on invalid credentials — does `build("gmail")` fail loudly, or does it succeed with a broken provider?
- **LOW — Plan depends only on 37-01, but references test removal from 37-02.** If 37-03 runs before 37-02, the skip markers don't exist yet. The dependency graph should show `Depends on: 37-01, 37-02` or the test skip-marker removal should move to Plan 37-04.
- **LOW — Search result limit env var.** `DOTMD_GMAIL_SEARCH_RESULT_LIMIT` is a hard cap on `maxResults`. Gmail API has its own cap (500). The plan should specify a sane default (e.g., 20) and validate it stays within the API bound (1–500).

#### Suggestions

1. Specify how `~/.secrets/dotmd-gmail.env` is loaded into env vars (or update D-05 if the decision changed). If the file approach is preferred, implement `SourceRuntimeFactory._load_dotenv(path)` or similar.
2. Add graceful degradation: if credentials are invalid, register the descriptor but mark it as `status=SourceLifecycleStatus.CREDENTIALS_UNAVAILABLE`.
3. Set `DOTMD_GMAIL_SEARCH_RESULT_LIMIT` default to 20, validate 1 ≤ value ≤ 500.
4. Fix dependency declaration to include 37-02, or move test skip-marker removal to 37-04.
5. Add a `health_check()` method (or reuse the lifecycle's existing check pattern) that validates the Gmail OAuth token with a lightweight API call (e.g., `GET /profile` with `fields=emailAddress`).

---

### Plan 37-04: AIR-02 Compatibility Report and End-to-End Verification

#### Summary

Good quality gate — the report structure is comprehensive and the verification grep checks are precise. The main risk is that the report is described as "pre-written," which suggests it may be aspirational rather than evidence-based.

#### Strengths

- **Report structure answers all three AIR-02 categories.** Reusable, shim, avoid — clear triage.
- **Verification checks are automatable.** The grep for `^from airweave|^import airweave` and the three-descriptor count are CI-checkable.
- **Attribution of `GmailSource.search()` being unimplemented.** The key research finding is correctly surfaced as a report section.

#### Concerns

- **MEDIUM — "Pre-written in the plan" is a smell.** If the report content is predetermined before the spike executes, it may miss actual findings. The report should be a template with placeholders, filled in after Plans 37-01 through 37-03 complete. At minimum, the report must cite specific file paths, class names, and tested behaviors from the implemented code.
- **MEDIUM — GmailAttachmentEntity deferred but not detailed.** D-11 says "SourceAsset is deferred" and AIR-02 should document the mapping. The report template mentions it, but doesn't specify what the mapping would look like — e.g., which `GmailAttachmentEntity` fields map to `SourceAsset` fields, and what blockers exist.
- **LOW — No mention of updating AGENTS.md.** Phase completions should update the project's AGENTS.md with architecture decisions (why we vendored, why direct API calls, token handling strategy).
- **LOW — "Generic bridge extensibility assessment" is vague.** The report section should assess: if we added a Slack connector tomorrow, what % of the bridge code is reusable vs. connector-specific?

#### Suggestions

1. Write the report as a template with `[TBD: filled after 37-01–37-03]` markers, not pre-written prose.
2. Include a concrete `SourceAsset` mapping table even if deferred — "this is what it would look like."
3. Add an "Extensibility Assessment" table: for each bridge component, classify as `generic` or `connector-specific` with % estimates.
4. Include an AGENTS.md update task in the plan (or a follow-up note to update it post-merge).

---

### Cross-Cutting Concerns

#### 1. `source_native_score = None` and RRF Fusion (CRITICAL)

This is the highest-risk item across all plans. The RRF formula is `score = ∑ 1/(k + rank_i)` summed across participating engines. If Gmail results have `source_native_score = None` and the fusion layer either skips them or assigns an arbitrary value, the fused ranking will be wrong. Audit `backend/src/dotmd/search/fusion.py` immediately.

**Recommendation:** Write a quick integration test that feeds a `SearchResult` with `score=None` into the fusion layer and verify it doesn't crash, exclude, or misrank the result.

#### 2. Generic Bridge Abstraction (D-03) Not Designed (HIGH)

User decision D-03 states: "Bridge must be generic across all BaseSource subclasses, not Gmail-specific." None of the plans define a generic bridge abstraction. The plans collectively describe a Gmail-specific integration. For the phase to satisfy AIR-01 and AIR-03, there must be a generic bridge class that Gmail instantiates, not a Gmail-specific class pretending to be generic.

**Recommendation:** Add a task to Plan 37-02: define `BaseConnectorBridge(ABC)` with:
- `search_native(query: str, limit: int) -> list[SearchCandidate]`
- `read_unit_window(ref: str) -> SourceUnitWindow`
- `to_search_candidate(entity: BaseEntity, rank: int) -> SearchCandidate`

GmailBridge implements this. The abstraction satisfies D-03 with minimal overhead.

#### 3. OAuth Token Lifecycle (MEDIUM)

Token refresh is mentioned across plans but never designed as a coherent lifecycle:
- Plan 37-01: caches for 5 minutes (too short)
- Plan 37-01: no refresh race condition guard
- Plan 37-03: no credential validation at registration
- No plan for refresh token rotation (Google may issue new refresh tokens on refresh)

**Recommendation:** Consolidate token handling into a single `TokenCache` class in the DI shims layer with thread-safe refresh serialization and margin-based expiry (`expires_in - 300`).

#### 4. MIME Body Decoding (MEDIUM)

Plan 37-02 underspecifies MIME decoding. Must address:
- Part selection: prefer `text/plain` > stripped `text/html` > any text part
- Charset handling: decode per part's `Content-Type` charset, fallback to UTF-8
- Size limits: cap body at configurable limit (e.g., 1MB), truncate with marker
- Encoding variants: Gmail returns both standard base64 and URL-safe base64url

#### 5. Error Boundary Design (MEDIUM)

No plan specifies error boundaries between the bridge and the caller (search service). Each HTTP error type needs a defined handling path: empty results (return `[]`), 401 (token expired → raise `SourceAuthError`), 429/5xx (rate limited/transient → raise `SourceTemporaryUnavailable`).

#### 6. Scope Creep Risk (LOW)

The plans are well-scoped to the spike goal. The only scope concern is whether the "generic bridge" requirement (D-03) pulls the spike into designing infrastructure it wasn't meant to. The spike should *demonstrate* that a generic bridge is feasible, not *build* a production-ready generic bridge.

### Risk Assessment

| Plan | Risk | Justification |
|------|------|---------------|
| 37-01 | **MEDIUM** | Token caching design needs revision. Otherwise well-scoped. |
| 37-02 | **HIGH** | `source_native_score = None` RRF risk unmitigated. MIME edge cases unaddressed. Generic bridge abstraction missing despite D-03 requirement. |
| 37-03 | **MEDIUM** | Credential source mismatch. Graceful degradation unspecified. |
| 37-04 | **LOW** | Pre-written report risk is real but easily corrected. |

**Overall Phase Risk: MEDIUM-HIGH**

Two blockers must be resolved before execution:
1. **BLOCKER:** Audit RRF fusion for `None` score handling — fix or add bridge fallback.
2. **BLOCKER:** Design and insert the generic `BaseConnectorBridge` abstraction into Plan 37-02 to satisfy D-03.

---

## Consensus Summary

Both reviewers converged on the same three primary risk areas with strong agreement.

### Agreed Strengths

- **Correct isolation of Airweave runtime.** Both reviewers praised the vendoring strategy — no Temporal, Vespa, Celery, Redis, or heavy transitive deps survive in the vendored tree.
- **Correct federated-only scope.** Gmail as a query-time federated provider (no trickle, no embedding, no FTS5 ingestion) is the right call for a spike.
- **Existing lifecycle contracts reused correctly.** Source registry, `SourceDescriptor`, `SourceRuntimeFactory`, credential provider boundary — all followed. AIR-03 is well-served.
- **Metadata whitelist discipline.** `GMAIL_PROVIDER_METADATA_KEYS` whitelist prevents raw API payload leakage into search results.
- **SourceAsset deferred cleanly.** Both reviewers agreed that deferring `GmailAttachmentEntity` → `SourceAsset` is the right call for a spike.

### Agreed Concerns

1. **HIGH — `source_native_score = None` in RRF fusion.** Both reviewers independently flagged this as the top risk. Gmail API returns no relevance score; setting `source_native_score = None` may crash or silently corrupt the fusion layer. `backend/src/dotmd/search/fusion.py` must be audited before plan acceptance. If the fusion layer does not handle `None`, either add `source_native_score = 1.0 / (rank + 1)` positional decay in the bridge, or patch the fusion layer.

2. **HIGH — Generic bridge abstraction absent (D-03 unsatisfied).** Both reviewers flagged that D-03 ("bridge must be generic across all BaseSource subclasses") has no design artifact in any plan. The plans describe a Gmail-specific integration, not a generic bridge. A `BaseConnectorBridge(ABC)` abstract class (or Protocol) defining `search_native`, `read_unit_window`, and `to_search_candidate` must be added to Plan 37-02, with `GmailBridge` as its first implementation.

3. **MEDIUM — OAuth token caching design is fragile.** Both reviewers identified: (a) 5-minute hard TTL is too short — should use `expires_in - 300` margin from the token response, and (b) no `threading.Lock` guard against concurrent refresh races. For a single-user server this is low severity in practice, but structurally wrong.

4. **MEDIUM — MIME body decoding is underspecified.** Both reviewers flagged that Plan 37-02's `_decode_gmail_body` helper has no documented handling for HTML-only emails, charset detection, multipart/mixed nesting, or body size limits.

5. **MEDIUM — Error boundaries between bridge and search service unspecified.** Neither plan defines what exception types the bridge raises for 401, 429, or 5xx responses, or how the fusion/search layer should degrade when Gmail is unavailable.

### Divergent Views

- **Vendor version anchoring:** OpenCode raised this as a MEDIUM concern (missing commit SHA in vendored files); Codex did not mention it. Recommend adding a `VENDOR_VERSION` file — low cost, high future value.
- **Pre-written report in 37-04:** OpenCode flagged this as a MEDIUM risk ("aspirational rather than evidence-based"). Codex did not flag it explicitly. The concern is valid: the report should be a template filled after implementation, not predetermined prose.
- **Dependency graph fix for 37-03:** OpenCode noted that 37-03 references test skip-marker removal from 37-02 but only declares dependency on 37-01 — a minor dependency graph inconsistency. Codex did not raise this.
- **`access.delegated_to` semantic mismatch:** Codex raised that storing a refresh token in `delegated_to` is semantically misleading. OpenCode addressed the credential storage gap from a different angle (D-05 `.env` file not wired). Both are valid; the credential flow design has two distinct gaps.
