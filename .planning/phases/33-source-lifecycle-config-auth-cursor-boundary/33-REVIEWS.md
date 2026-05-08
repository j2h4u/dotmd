---
phase: 33
reviewers: [opencode, claude]
reviewed_at: 2026-05-08T20:01:17+05:00
plans_reviewed:
  - .planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-01-lifecycle-runtime-bundle-PLAN.md
  - .planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-02-filesystem-lifecycle-migration-PLAN.md
  - .planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-03-telegram-lifecycle-and-cursor-boundary-PLAN.md
cycle: 2
current_high: 0
---

# Cross-AI Plan Review - Phase 33

Cycle 2 review after replanning from Cycle 1 feedback. Reviewers were restricted to OpenCode and Claude only.

## OpenCode Review

# Phase 33 Plan Review - Cycle 2

## Summary

All three Phase 33 plans are well-structured with clear TDD cycles, correct wave dependencies, and explicit guardrails. The previous Cycle 1 HIGH concern (`settings.resolved_indexing_paths`) is **fully resolved** in the current plans - all references now use `settings.indexing_paths` and `settings.effective_indexing_exclude`, with explicit negative static checks against the phantom attribute. Remaining concerns are at MEDIUM severity and below.

## Strengths

1. **Previous HIGH resolved cleanly.** Plans 02 and 03 now reference the live `Settings` API correctly (`settings.indexing_paths`, `settings.effective_indexing_exclude`), include explicit `rg` negative checks for `resolved_indexing_paths`, and the Plan 02 task action contains a direct instruction: *"Do not add or reference a resolved-indexing-paths alias; live `Settings` exposes `indexing_paths`."*

2. **Threat models are specific and actionable.** Each plan maps threats to concrete mitigations and acceptance criteria. For example, Plan 01 ties "Cursor commits escape the local transaction" directly to the `conn=` requirement on `commit_checkpoint()`.

3. **Wave structure is sound.** Plan 01 establishes the contract without touching call sites, Plan 02 proves it with filesystem (lower risk, no external deps), Plan 03 extends to Telegram (higher risk, delegated auth, cursor commits). Dependencies are declared correctly.

4. **Transaction safety is a structural invariant, not an afterthought.** The cursor store protocol preserves the `conn=` parameter, and the acceptance criteria in Plan 03 require `self._conn.execute("BEGIN")` to remain before checkpoint commit.

5. **Credential/Auth boundary is minimal but correct.** `SourceAccess(kind="none" | "delegated")` with no raw token/password/secret fields, plus static scans rejecting Telethon/direct Telegram API clients.

6. **Plan scope discipline.** No federated search, no connector marketplace, no full reindex requirement. The phase stays inside its boundary.

## Concerns

### MEDIUM: Pipeline ingest API shape has two alternatives but is not pinned (Plan 03, Task 2)

Plan 03 Task 2 offers two shapes for the lifecycle-mediated ingest entry point: `ingest_application_source_runtime(bundle, limit=limit)` *or* modifying `ingest_application_source()` to accept an optional `cursor_store`. These have different implications - the first adds a parallel entry point, the second modifies an existing method's signature. The agent has discretion here, but the two options produce meaningfully different integration surfaces. Pinning one would reduce ambiguity for execution.

**Recommendation:** Pick one shape in the plan. Adding a new `ingest_application_source_runtime()` that delegates to the existing `ingest_application_source()` with lifecycle-provided cursor store is cleaner than modifying the existing method's signature, because it keeps backward compatibility for any caller that constructs providers directly.

### MEDIUM: Factory ownership between pipeline and service is advisory, not pinned (Plan 03, Task 2)

Plan 03 says: *"In `DotMDService.__init__`, reuse the pipeline/source lifecycle factory or create an equivalent factory from settings and metadata store. Prefer one factory owned by the pipeline if that keeps dependency flow simpler."* This is reasonable guidance but "prefer" leaves the execution agent room to create a second factory in service, which would risk the Cycle 1 concern about multiple equivalent factory builders drifting.

**Recommendation:** Make it explicit: `DotMDService` accesses the factory through `self._pipeline._source_runtime_factory` or through a public property/method on the pipeline. One factory, one owner.

### LOW: `SourceConfigRecord.credential_ref` default_factory is a placeholder (Plan 01, Task 2)

The action specifies `credential_ref: SourceCredentialRef = Field(default_factory=...)` with literal `...`. The execution agent will need to fill this in (likely `lambda: SourceCredentialRef(namespace="")` or similar). Minor but could cause a type error if not caught.

### LOW: Private `_from_file_info` method access (Plan 02, Task 2, Cycle 1 carryover)

Plan 02 says: *"If the exact adapter method remains `_from_file_info`, keep it private to the adapter but obtain the adapter from lifecycle first."* This is acceptable - the pipeline gets the adapter from the lifecycle bundle and calls public `discover`/`discover_multi`, while `_source_document_for_file_info` can call the adapter's private method since both are in the same package boundary. Not a real issue but worth noting.

## Suggestions

1. **Pin the ingest API shape** in Plan 03 to `ingest_application_source_runtime(bundle, limit)` that internally delegates to the existing method with the lifecycle cursor store, rather than leaving two alternatives.

2. **Pin factory ownership** to the pipeline, with service accessing it through a pipeline property/method. This prevents factory drift.

3. Consider adding a static acceptance criterion in Plan 03 that `DotMDService` does not construct its own `SourceRuntimeFactory` - it reuses the pipeline's. This would be a stronger guardrail than the current advisory language.

## Risk Assessment

| Risk | Likelihood | Impact | Mitigated |
|------|-----------|--------|-----------|
| Previous HIGH (`resolved_indexing_paths`) recurs | Very Low | HIGH | Yes - explicit negative checks in all plans |
| Pipeline ingest API shape ambiguity | Medium | MEDIUM | Partially - agent discretion, but two alternatives given |
| Factory drift between pipeline and service | Low-Medium | MEDIUM | Partially - advisory preference, not pinned |
| Dead lifecycle layer (unused by real paths) | Very Low | HIGH | Yes - acceptance criteria reject direct construction |
| Cursor commits escape transaction | Very Low | HIGH | Yes - `conn=` required, `BEGIN`/`COMMIT` preserved |
| Telegram auth moves into dotMD | Very Low | HIGH | Yes - static scans, `SourceAccess(kind="delegated")` |
| Full reindex required | Very Low | MEDIUM | Yes - plans explicitly avoid this |

## Final Assessment

The previous HIGH is resolved. The plans are ready for execution with two MEDIUM items that are advisory improvements, not blockers. The core architecture (lifecycle factory, typed config, credential delegation, cursor store) is sound and correctly mapped to live source surfaces.

CYCLE_SUMMARY: current_high=0

---

## Claude Review

# Phase 33 Plan Review - Cycle 2

## Summary

Cycle 2 plans correctly resolve the previous HIGH about `settings.resolved_indexing_paths`. Plan 02 and Plan 03 now reference `settings.indexing_paths` and `settings.effective_indexing_exclude` directly (verified live at `backend/src/dotmd/core/config.py:200,287`), and both plans add explicit negative-grep guards to prevent the phantom property from re-appearing. The remaining `resolved_indexing_paths` matches in the phase directory are confined to `33-REVIEWS.md` (historical Cycle 1 text), not the current PLAN files. The wave order, threat-model coverage, and TDD-first task structure remain coherent. Several MEDIUM/LOW issues from the Cycle 1 consensus persist but none rises to a HIGH blocker.

## Strengths

- **Phantom-property regression fixed structurally, not just textually.** Plans now bake the correct attribute names into acceptance criteria, and Plan 02 + Plan 03 each carry an `rg -n "resolved[_]indexing[_]paths" ... returns no matches` verify line. This makes recurrence detectable mechanically.
- **Cursor transaction invariant treated as structural.** Plan 03 acceptance asserts `pipeline.py` still contains `self._conn.execute("BEGIN")` before checkpoint commit, and the rollback regression test (`test_lifecycle_cursor_checkpoint_rolls_back_when_index_transaction_fails`) verifies durable-cursor semantics from Phase 28 are preserved through the lifecycle wrapper.
- **Real-call-site integration mandated.** Plan 02 forbids `FilesystemMarkdownSourceAdapter()` in `pipeline.py`; Plan 03 forbids `TelegramApplicationSourceProvider(` and `UnixSocketTelegramSourceClient(` in `service.py`/`cli.py`. Together these prevent a "lifecycle module that tests use but call sites bypass" outcome - the top risk in `33-PATTERNS.md`.
- **Boundary discipline preserved.** Static `rg` scans for `airweave`, `Telethon`, `telegram.client`, and Telegram private-SQLite access protect the D-15 invariant that Telegram auth stays delegated to `mcp-telegram`.
- **Optional-Telegram startup remains intact.** Plan 03 routes `_build_telegram_provider()` through `build_if_configured("telegram")`, preserving the current behavior of returning `None` when `telegram_daemon_socket` is unset.

## Concerns

### HIGH

None. The previous Cycle 1 HIGH (`settings.resolved_indexing_paths`) is verified resolved across all current PLAN files.

### MEDIUM

- **MEDIUM - Plan 02 still calls into `FilesystemMarkdownSourceAdapter._from_file_info()` (private method) via the lifecycle bundle.** Live `pipeline.py:1321` does `FilesystemMarkdownSourceAdapter()._from_file_info(file_info)`. Plan 02 task 2 explicitly accepts: *"If the exact adapter method remains `_from_file_info`, keep it private to the adapter but obtain the adapter from lifecycle first."* This was the Cycle 1 consensus MEDIUM and remains unresolved. Calling a private method through a public bundle is a smell that future phases will inherit. Recommend Plan 02 promote `_from_file_info` to a public adapter method (e.g., `source_document_from_file_info`) or add a small public helper on `SourceAdapterProtocol`.
- **MEDIUM - Plan 01 acceptance criterion "`source_lifecycle.py` does not contain `password` or `secret`" is overly broad.** A natural docstring such as *"this store must not become a raw secret store"* would fail this static check. The intent is "no raw secret field names." Recommend scoping to specific patterns (e.g., `rg -n "(?i)\b(password|token|api_key|access_token|secret_key|client_secret)\s*:" backend/src/dotmd/ingestion/source_lifecycle.py`) so the assertion catches structural violations without forbidding the word "secret" in prose.
- **MEDIUM - Factory ownership remains underspecified across pipeline/service.** Plan 03 task 2 says: *"reuse the pipeline/source lifecycle factory or create an equivalent factory from settings and metadata store. Prefer one factory owned by the pipeline if that keeps dependency flow simpler."* This was the Cycle 1 consensus MEDIUM (factory drift risk). Two construction sites with the same logic but separate instances will diverge in the next milestone (config store seeding, credential provider wiring). Recommend pinning ownership: pipeline owns the factory, service consumes `pipeline.source_runtime_factory` (or vice versa) - pick one.
- **MEDIUM - `tests/storage/test_metadata_m2m.py` is listed in `files_modified` for Plans 01 and 03 but no concrete additions are specified.** The verify commands run that file, but the action sections do not describe what tests are added there. Either remove from `files_modified` (if only running for regression coverage) or specify which assertions the cursor-store wrapper introduces in that file.

### LOW

- **LOW - Plan 03 leaves the lifecycle ingest entry-point shape open.** Action says *"Add a lifecycle-mediated ingest entry point in `IndexingPipeline`, for example `ingest_application_source_runtime(bundle, limit=limit)`, or change `ingest_application_source()` to accept an optional `cursor_store`."* Either is workable; pinning one shape removes a planning decision the executor would otherwise re-litigate.
- **LOW - Filesystem cursor-schema metadata is not exercised.** Filesystem descriptor declares `cursor_kind="fingerprint"`. Plan 02 does not assert that the filesystem bundle exposes any fingerprint metadata via `bundle.metadata_json` or equivalent. Not blocking - D-13 requires only that filesystem does not *claim* provider cursor commits, which the plan does enforce.
- **LOW - The negative `rg` for `Telethon|telegram\.client|sqlite.*telegram|telegram.*sqlite` over `backend/src backend/tests` may produce historical matches in test fixtures or comments.** Plan 03 acknowledges this with "no new direct Telegram API or private SQLite access," but the acceptance criterion as written ("returns no matches") could be tightened to a baseline diff or a regex anchored to import lines.

## Suggestions

1. **Promote `_from_file_info` to a public adapter API in Plan 02.** Add a one-line task: rename `FilesystemMarkdownSourceAdapter._from_file_info` to `source_document_from_file_info` (or add a thin public delegator) and route `pipeline._source_document_for_file_info` through it via the lifecycle bundle. Closes the Cycle 1 private-method MEDIUM.
2. **Pin factory ownership.** Replace Plan 03's "reuse or create" wording with: *"`IndexingPipeline` owns the `SourceRuntimeFactory`. `DotMDService` reads it via `self._pipeline.source_runtime_factory`."* This kills factory drift before it starts.
3. **Tighten the secret-field static guard.** Replace `does not contain password or secret` with a regex that targets schema field declarations (e.g., model field assignments) rather than whole-file substring presence.
4. **Either specify test additions in `test_metadata_m2m.py` or drop it from `files_modified`** in Plans 01 and 03. Files that run for regression should not be in `files_modified` unless edits are described.
5. **Pick one ingest entry-point shape in Plan 03.** Recommend extending `ingest_application_source(provider, *, limit, cursor_store=None)` with a default that resolves to the lifecycle store - this avoids a parallel public method.

## Risk Assessment

- **Execution risk: LOW.** With the `resolved_indexing_paths` issue gone, the plans are grounded in live attribute names. The negative-grep guards make the "phantom config" failure mode self-detecting.
- **Boundary-leak risk: LOW.** Static scans cover Airweave imports, Telethon imports, direct Telegram clients, private Telegram SQLite access, and direct adapter construction in pipeline/service/CLI.
- **Cursor-safety risk: LOW.** Transaction-owned `commit_checkpoint(conn=...)` is enforced both at the protocol level (TypeError on missing `conn`) and behaviorally (rollback regression test).
- **Drift risk: MEDIUM-LOW.** Two structural ambiguities remain - factory ownership across pipeline/service, and the public-vs-private adapter method choice. Neither blocks Phase 33; both will compound as Phase 34+ adds connectors.
- **Reindex risk: LOW.** Plans explicitly forbid full-reindex requirements, and the migration is a construction-site refactor not a schema change.

CYCLE_SUMMARY: current_high=0

---

## Consensus Summary

Both reviewers agree that the previous HIGH concern is fully resolved in the current Phase 33 plan files. The current plans reference the live `Settings` API through `settings.indexing_paths` and `settings.effective_indexing_exclude`, add negative checks against `resolved_indexing_paths`, and keep historical Cycle 1 mentions isolated to prior review text.

### Agreed Strengths

- The wave order is sound: lifecycle contract first, filesystem migration second, Telegram/cursor integration third.
- The lifecycle boundary is required to reach real call sites, not just tests.
- Cursor checkpoint safety is treated as a transaction-owned invariant.
- Credential/auth boundaries remain delegated and avoid raw secret handling.
- No full reindex, marketplace runtime, direct Telegram client, or Airweave dependency is introduced.

### Agreed Concerns

- MEDIUM: Plan 03 leaves factory ownership between pipeline and service too flexible; both reviewers recommend pinning one factory owner.
- MEDIUM/LOW: Plan 03 leaves the application-source ingest API shape open; both reviewers recommend choosing one shape before execution.
- MEDIUM/LOW: The filesystem adapter private `_from_file_info` path remains a design smell, though reviewers differ on severity.

### Divergent Views

- Claude classifies the private adapter method, broad secret-word static guard, factory ownership, and unspecified `test_metadata_m2m.py` edits as MEDIUM. OpenCode treats the private adapter method and placeholder default factory as LOW, and does not raise the secret-word/static-test issue.
- OpenCode recommends a new `ingest_application_source_runtime()` wrapper. Claude recommends extending `ingest_application_source(..., cursor_store=None)` with a lifecycle-backed default.

### Verified Unresolved HIGH Concerns

None.

CYCLE_SUMMARY: current_high=0
