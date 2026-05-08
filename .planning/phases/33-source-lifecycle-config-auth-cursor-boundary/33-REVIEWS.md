---
phase: 33
reviewers: [opencode, claude]
reviewed_at: 2026-05-08T19:47:49+05:00
plans_reviewed:
  - .planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-01-lifecycle-runtime-bundle-PLAN.md
  - .planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-02-filesystem-lifecycle-migration-PLAN.md
  - .planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-03-telegram-lifecycle-and-cursor-boundary-PLAN.md
context_reviewed:
  - .planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-CONTEXT.md
  - .planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-RESEARCH.md
  - .planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-PATTERNS.md
  - .planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-VALIDATION.md
  - .planning/ROADMAP.md
  - .planning/REQUIREMENTS.md
  - .planning/PROJECT.md
  - .planning/STATE.md
source_architecture_reviewed:
  - backend/src/dotmd/core/models.py
  - backend/src/dotmd/core/source_registry.py
  - backend/src/dotmd/ingestion/source_registry.py
  - backend/src/dotmd/ingestion/source_provider.py
  - backend/src/dotmd/ingestion/source.py
  - backend/src/dotmd/ingestion/telegram_provider.py
  - backend/src/dotmd/ingestion/pipeline.py
  - backend/src/dotmd/storage/metadata.py
  - backend/src/dotmd/core/config.py
graphify_used: true
current_high: 1
---

# Cross-AI Plan Review - Phase 33

Phase 33 was reviewed with exactly the requested reviewer set: OpenCode and Claude. The shared prompt included the Phase 33 plans, context, research, pattern map, validation plan, ROADMAP, REQUIREMENTS, PROJECT, STATE, Graphify navigation notes, and live source excerpts for the current source architecture.

Graphify was used as a navigation aid for the source architecture cluster; review claims below were checked against live files before synthesis.

## OpenCode Review

Let me examine the live source files to verify the plans against actual code.
Now I have enough information from the live code. Here's my structured review:

---

## Plan 01: Lifecycle Runtime Bundle Contract

### Summary
Solid Wave 1 contract. Defines types, protocols, and factory before integration. Test-first approach correctly targets the boundary invariants (no raw secrets, transaction-owned cursor commits, fail-fast on missing config). The contract is self-contained and doesn't overreach into call-site migration.

### Strengths
- TDD task ordering (tests first, implementation second) is correct.
- `SourceConfigRecord` separates `credential_ref` from typed config, satisfying D-07/D-08.
- `SourceCursorStore.commit_checkpoint()` requiring `conn=` parameter preserves the existing caller-transaction invariant from `SQLiteMetadataStore.commit_source_checkpoint()`.
- `build_if_configured("telegram")` returning `None` is the right pattern for optional service startup.
- Static guards (no airweave, no Telethon, no password/secret) are enforceable.

### Concerns
- **MEDIUM**: `SourceConfigRecord` uses a union `FilesystemSourceConfig | TelegramSourceConfig`. When a third source kind arrives (Phase 37 Airweave spike), this union needs extending. A discriminated-union pattern or a `namespace` discriminator would be more forward-compatible. Not blocking for Phase 33, but the plan should acknowledge this is a closed union.
- **LOW**: The test `test_source_config_store_keeps_credential_refs_separate_from_config` checks for absence of `secret`/`token`/`password` field names. This is a lexical check, not a structural guarantee. A future contributor could add a `key` or `value` field that leaks secrets. Acceptable for now.

### Suggestions
- Consider making `SourceConfigRecord` a generic or namespace-discriminated model so Phase 34+ sources don't require union expansion.

### Risk Assessment: **LOW**
Self-contained contract module with no call-site changes. Tests assert all invariants. The only risk is a design that's slightly hard to extend, not one that breaks existing behavior.

---

## Plan 02: Filesystem Lifecycle Migration

### Summary
Routes all three `FilesystemMarkdownSourceAdapter()` direct constructions in `pipeline.py` (lines 1260, 1268, 1321) through the lifecycle factory. The approach is sound, but the plan references a **non-existent** Settings property that would cause the execution agent to either fail or create an unplanned property.

### Strengths
- Correctly identifies all three construction sites: `_discover_documents()`, `_discover_documents_multi()`, `_source_document_for_file_info()`.
- `source_runtime_factory_from_settings()` helper keeps factory construction co-located with lifecycle code.
- Static acceptance criterion `rg FilesystemMarkdownSourceAdapter\(\) pipeline.py` catches any missed direct construction.
- Explicitly preserves filesystem ref semantics and does not add provider cursor commits.

### Concerns
- **HIGH**: The plan references `settings.resolved_indexing_paths` in Task 2 action and acceptance criteria. **This property does not exist** in `Settings`. The actual field is `settings.indexing_paths` (a `list[str]`, `config.py:200`). An execution agent following the plan literally would either (a) create a new `resolved_indexing_paths` property with unclear semantics, or (b) fail pyright because the attribute doesn't exist. The plan must commit to either using `settings.indexing_paths` directly or specifying what `resolved_indexing_paths` resolves (e.g., data_dir fallback). Currently `indexing_paths` defaults to `[]` and is validated as non-empty and absolute at runtime startup (`config.py:310-313`), so it's already "resolved" — the plan just needs to use the real name.
- **MEDIUM**: `_source_document_for_file_info` calls `FilesystemMarkdownSourceAdapter()._from_file_info(file_info)` — a private method on a freshly constructed adapter. After migration, the plan says "obtain the adapter from lifecycle first" then calls the private `_from_file_info`. The adapter should expose this as a public method (e.g., `source_document_from_file_info`), or the plan should acknowledge the smell and leave it for later cleanup. Calling `bundle.source._from_file_info()` undermines the "inspectable bundle" goal.
- **LOW**: The `source_runtime_factory_from_settings` helper creates an `InMemorySourceConfigStore` from settings values. The pipeline `__init__` already takes `Settings` and stores `self._settings`. The factory would be constructed once at pipeline init, but if settings change at runtime (unlikely but possible), the factory would be stale. Not a real risk for current architecture.

### Suggestions
- Fix `settings.resolved_indexing_paths` → `settings.indexing_paths` in Task 2 action and acceptance criteria.
- Add a public `build_source_document(file_info: FileInfo) -> SourceDocument` method to `FilesystemMarkdownSourceAdapter` to replace the `_from_file_info` private call, or document that this smell is accepted.

### Risk Assessment: **MEDIUM**
The `resolved_indexing_paths` bug will cause an execution agent to either fail or diverge from the plan. Fixing it is trivial but the plan as written is not correctly grounded.

---

## Plan 03: Telegram Lifecycle And Cursor Boundary

### Summary
Routes Telegram construction in `service.py` (lines 206-211), `cli.py` (lines 465-466), and checkpoint access in `pipeline.py` through lifecycle. The plan correctly preserves transaction safety and delegated auth. However, the `ingest_application_source()` signature change is underspecified.

### Strengths
- Correctly identifies both construction sites: `DotMDService._build_telegram_provider()` and `cli.py telegram_ingest`.
- Service startup uses `build_if_configured("telegram")` — matches the non-breaking optional behavior.
- CLI keeps `is_socket()` checks before lifecycle construction — preserves existing UX error messages.
- Transaction boundary preservation: checkpoint commit remains inside `BEGIN`/`COMMIT`, rollback test proves checkpoint is absent after rollback.
- Static guards reject `TelegramApplicationSourceProvider(` in service.py and cli.py.
- Task 3 docs + static guards provide a clean phase-close bookend.

### Concerns
- **MEDIUM**: Task 2 says "Add a lifecycle-mediated ingest entry point, for example `ingest_application_source_runtime(bundle, limit=limit)`, or change `ingest_application_source()` to accept an optional `cursor_store`." This is two different approaches with different implications:
  - Option A (new method): Callers that currently pass a raw `provider` would need to switch to passing a `bundle`. This changes the `cli.py` `telegram_ingest` call at line 480: `service._pipeline.ingest_application_source(provider, limit=limit)`.
  - Option B (optional param): The existing signature stays but the cursor store is injected. The pipeline still needs the metadata store for non-checkpoint operations, so the cursor store is an additional dependency.
  
  The plan should commit to one approach. Option B is lower-risk since it doesn't change the `provider` parameter and keeps backward compatibility for direct callers.

- **MEDIUM**: The same `settings.resolved_indexing_paths` issue from Plan 02 propagates here since Plan 03 extends `source_runtime_factory_from_settings()`.

- **LOW**: Plan 03 Task 2 acceptance criteria checks `pipeline.py` still contains `self._conn.execute("BEGIN")`. This is a good guard but doesn't verify that the cursor store's `conn=` parameter receives `self._conn`. A future refactor could introduce a different connection. The rollback test in Task 1 covers this implicitly.

### Suggestions
- Commit to Option B (optional `cursor_store` parameter) for `ingest_application_source()` to minimize signature disruption.
- Fix `resolved_indexing_paths` → `indexing_paths` (same as Plan 02).

### Risk Assessment: **MEDIUM**
The underspecified `ingest_application_source` migration path could lead to two different implementations across execution agents. The transaction safety is well-guarded.

---

## Cross-Cutting Assessment

### Dependency Ordering
- Wave ordering is correct: Plan 01 (contract) → Plan 02 (filesystem) → Plan 03 (Telegram). Plan 03 depends on Plan 02 because both share `source_runtime_factory_from_settings()`.

### Scope Creep
- Plans correctly stay within Phase 33 boundary. No federated search, no Airweave connector, no filesystem unification.

### Second Source Plane Risk
- The plans explicitly prevent a second source plane by routing both filesystem and Telegram through the same factory. Static guards reject direct construction in call sites.

### Full Reindex Risk
- Plans explicitly state "Do not run or require a full reindex." The migration is construction-path only.

### Cursor Transaction Safety
- `SourceCursorStore.commit_checkpoint()` requires `conn=`, preserving the existing invariant. Rollback tests in Plan 01 and Plan 03 verify this.

---

## Unresolved HIGH Concerns

1. **Plan 02 references `settings.resolved_indexing_paths` which does not exist in the codebase.** The actual property is `settings.indexing_paths` (`core/config.py:200`). Plan 02 Task 2 action, acceptance criteria, and the Plan 03 extension all reference this phantom property. The plan must be corrected to use `settings.indexing_paths` before execution.


---

## Claude Review

<sef-eval phase="USER-PROMPT">
<task>cross-AI plan review for Phase 33 source lifecycle plans</task>
<skills>none — plan review request, output is the deliverable</skills>
<decision>proceed</decision>
</sef-eval>

# Phase 33 Cross-AI Plan Review

## 1. Summary

The three plans deliver an Airweave-lite source lifecycle/factory boundary in TDD style, with real integration into `IndexingPipeline`, `DotMDService`, and the CLI rather than a test-only shim. The wave ordering (contract → filesystem → Telegram + cursor) is sound, dependencies are explicit, and the design preserves the most important Phase 28/29 invariant: cursor commits happen inside the same caller-owned transaction as local persistence. Config and credential separation is enforced through types (`SourceConfigRecord`, `SourceCredentialRef`, `SourceAccess`) and static guards. I see no HIGH blockers — the plans satisfy LIFE-01 through LIFE-04 with reasonable scope discipline. A handful of MEDIUM items below could tighten the plan, but none require gate-stopping rework.

## 2. Strengths

- **Real integration, not a dead layer.** Plan 02 swaps the three direct `FilesystemMarkdownSourceAdapter()` call sites in `pipeline.py`, and Plan 03 swaps both `_build_telegram_provider()` in `service.py` and `dotmd telegram ingest` in `cli.py`. Static guards (`rg ... pipeline.py`, `rg ... service.py cli.py`) verify the migration actually landed.
- **Cursor transaction safety is structural, not procedural.** `SourceCursorStoreProtocol.commit_checkpoint(..., *, conn: Any, ...)` makes `conn` keyword-only, the wrapper delegates to `commit_source_checkpoint(..., conn=conn)` without calling `commit()`, and the pipeline preserves the existing `BEGIN`/`COMMIT` envelope. The `test_lifecycle_cursor_checkpoint_rolls_back_when_index_transaction_fails` test pins this end-to-end.
- **Config/credential separation is typed.** `SourceConfigRecord.config` holds typed config; `credential_ref: SourceCredentialRef` lives alongside it; `SourceAccess` only has `kind: Literal["none", "delegated"]` with no raw token/password fields. The `test_telegram_lifecycle_does_not_accept_raw_secret_fields` test makes this auditable.
- **Optional service startup is preserved.** `build_if_configured("telegram")` returns `None` when no socket is configured, so the existing optional Telegram startup path (no socket = no Telegram provider) keeps working.
- **No-full-reindex guardrail is explicit.** Plan 02 task 2 says "Do not run or require a full reindex." Filesystem refs and document_ref shapes are pinned by tests (`filesystem:<resolved_path>`).
- **Static guards block the second-plane risks.** `from airweave|import airweave`, `Telethon|telegram\.client`, `sqlite.*telegram`, and direct provider construction are all scanned. Plan 03 task 3 also updates `docs/source-adapter-architecture.md` and `docs/source-registry-airweave-mapping.md` so the lifecycle boundary is documented.
- **TDD ordering is honest.** Each plan has a fail-first test task before the implementation task; acceptance criteria require the test file to exist with named tests *before* the implementation lands.

## 3. Concerns

### MEDIUM

- **C1. Closed unions in `SourceConfigRecord.config` and `SourceAccess.kind` will need editing for every new source.** `config: FilesystemSourceConfig | TelegramSourceConfig` and `kind: Literal["none", "delegated"]` are fine for Phase 33 but become a friction point in Phase 34/35/37. Worth a one-line note in the architecture doc that this is intentional and the union widens per phase.

- **C2. Single source-of-truth for the lifecycle factory is left ambiguous.** Plan 03 says "reuse the pipeline/source lifecycle factory or create an equivalent factory from settings and metadata store. Prefer one factory owned by the pipeline if that keeps dependency flow simpler." Two factories (one in pipeline, one in service) would diverge on Telegram socket/exclude config drift. Recommend pinning this: `DotMDService` consumes `pipeline._source_runtime_factory` (or expose `pipeline.source_runtime_factory` as a public attribute). Otherwise both sides drift independently in Phase 36.

- **C3. The `_source_document_for_file_info()` migration path is underspecified.** Plan 02 says "use the filesystem source from the lifecycle bundle to build or bridge the source document. If the exact adapter method remains `_from_file_info`, keep it private to the adapter but obtain the adapter from lifecycle first." `_from_file_info` is currently private. Either promote it to a public adapter method or define a public bridge function in `source.py`. Calling `bundle.source._from_file_info(...)` from pipeline code would technically pass the static guard but reaches into a private member. Lock the chosen approach in the plan.

- **C4. Filesystem cursor store is reachable but unused — needs a negative test.** The filesystem bundle includes `cursor_store: SourceCursorStoreProtocol` (per the bundle contract), but D-13 says filesystem must not claim provider-owned cursor commits. Today nothing in pipeline calls `cursor_store.commit_checkpoint("filesystem", ...)`, but a future refactor could accidentally start. Add a simple test: after a filesystem index pass, `metadata_store.get_source_checkpoint("filesystem")` returns `None`.

- **C5. Static scan `Telethon|telegram\.client|sqlite.*telegram|telegram.*sqlite` may match existing fixtures or string literals.** The verify step says "returns no new direct Telegram API/private SQLite access" but doesn't capture a baseline. Either snapshot the current matches as the allowlist or tighten the pattern (e.g., scope to `backend/src/dotmd/` only; add `--type py` and exclude tests where a `telegram_socket_path` fixture variable could trip the regex). Otherwise CI flakes on harmless renames.

- **C6. CLI `is_socket()` ordering relative to lifecycle is implied but not pinned.** Plan 03 says "settings still performs the existing socket presence and `is_socket()` checks before non-dry-run/dry-run behavior." Ordering should be: (a) check `settings.telegram_daemon_socket is not None`, (b) check `is_socket()`, (c) call `factory.build_if_configured("telegram")`. If lifecycle is invoked first and the socket path exists but isn't actually a socket, the user gets a less helpful error from `UnixSocketTelegramSourceClient` later. A one-line acceptance criterion locking this order in `cli.py` would help.

- **C7. `record_error` semantics around concurrent writes during rollback.** Today `record_source_checkpoint_error(namespace, error)` does `write_conn.execute(...)` then `write_conn.commit()` when no `conn=` is passed. The pipeline calls this *after* `ROLLBACK`. The lifecycle wrapper preserves this, but if the underlying SQLite connection is in WAL mode and another writer is active during the same window, the existing behavior is already "best-effort." Not a regression — just worth noting that lifecycle doesn't change the existing semantics, so any race is pre-existing.

### LOW

- **C8. `does not contain "password" or "secret"` static check is fragile.** A stray comment or docstring containing "no passwords stored here" would trip it. Tighten to disallow only field/attribute definitions: `rg -n "password\s*[:=]|secret\s*[:=]|token\s*[:=]" backend/src/dotmd/ingestion/source_lifecycle.py` or scope to Pydantic field annotations.

- **C9. Settings attributes are referenced but not verified.** `settings.resolved_indexing_paths`, `settings.effective_indexing_exclude`, `settings.telegram_daemon_socket` must exist on `Settings`. Pyright will catch missing ones in task 2, but a quick read of `core/config.py` during planning would surface any rename. Likely already present (Phase 24 separated config), but worth a glance.

- **C10. No explicit assertion that `SourceCursorStoreProtocol.commit_checkpoint` does not call `conn.commit()` itself.** The plan describes the behavior in prose ("delegates to `commit_source_checkpoint(..., conn=conn)`; it must not call `commit()`") but doesn't add a test. Could add a `MagicMock` assertion that `conn.commit` is never called inside `commit_checkpoint`.

- **C11. Trickle indexer is not in the test set.** `trickle.py` triggers indexing via the pipeline; if it calls `pipeline._discover_documents_multi()` (which Plan 02 routes through lifecycle), it inherits the migration. Worth a one-line confirmation in the plan that trickle's call path is `pipeline → lifecycle`, not `trickle → FilesystemMarkdownSourceAdapter()` directly. Quick `rg -n "FilesystemMarkdownSourceAdapter" backend/src/dotmd/ingestion/trickle.py` would settle it.

## 4. Suggestions

1. **Pin the factory ownership in Plan 03 task 2.** Choose: `DotMDService` consumes `pipeline.source_runtime_factory`; remove the "or create an equivalent factory" alternative.
2. **Decide and lock the `_from_file_info` exposure** in Plan 02 task 2 acceptance criteria — promote to public `from_file_info()` on the adapter, or add a `source_document_from_file_info(file_info, adapter)` helper in `source.py`. Either is fine; pick one.
3. **Add the filesystem-checkpoint-absent negative test** described in C4 — cheap, structural guarantee against D-13 violation.
4. **Add a test or assertion** for C10: `conn.commit` is never called by `SourceCursorStore.commit_checkpoint`.
5. **Tighten the `Telethon|telegram\.client|sqlite.*telegram` regex** (C5) — scope to `backend/src/dotmd/` and exclude `tests/` to reduce false positives, or snapshot a baseline of allowed matches.
6. **Add a one-line acceptance criterion** in Plan 03 task 2 pinning the ordering: `is_socket()` check before `factory.build_if_configured("telegram")` in `cli.py`.
7. **Run `rg -n "FilesystemMarkdownSourceAdapter" backend/src/dotmd/ingestion/trickle.py`** during planning to confirm trickle is downstream of pipeline.
8. **Add a brief note in `docs/source-adapter-architecture.md`** that the closed `Literal["none", "delegated"]` and the `FilesystemSourceConfig | TelegramSourceConfig` union widen per phase as new sources land. Future-reader signal.

## 5. Risk Assessment

**MEDIUM-LOW.**

Justification: The plans preserve the most invariant-critical behavior (caller-owned cursor commits inside the local persistence transaction) by structural means, not by procedure. The lifecycle layer is integrated into real call sites in this phase, not deferred to a later milestone. TDD ordering and static guards make regressions visible. The MEDIUM concerns are about clarity of ownership (which factory the service uses) and minor private-API exposure decisions, not architectural soundness. No HIGH risk to executing. Phase 34/35/37 will need to widen the closed union types, which is expected scope, not a fault of Phase 33.

## Unresolved HIGH Concerns

None.


---

## Consensus Summary

### Agreed Strengths

- The wave order is sound: lifecycle contract first, filesystem migration second, Telegram/cursor integration third.
- The phase stays inside the Phase 33 boundary and does not pull in federated search, broad connector marketplace work, or full Telegram/filesystem unification.
- Cursor transaction safety is treated as a structural invariant: checkpoint commits remain inside caller-owned local persistence transactions.
- Config and credential separation is explicit, with descriptors remaining declarative and credentials accessed through a provider/delegation boundary.
- The plans aim to integrate real filesystem and Telegram construction paths, not create a dead lifecycle layer.

### Agreed Concerns

- MEDIUM: The closed config/access unions are acceptable for Phase 33 but should be documented as intentionally widened by future source phases.
- MEDIUM: The filesystem `_source_document_for_file_info()` migration should avoid reaching through a lifecycle bundle into a private `_from_file_info()` method; the plan should pick a public adapter/helper shape.
- MEDIUM: Telegram/service/pipeline lifecycle factory ownership should be pinned to avoid multiple equivalent factory builders drifting.

### Divergent Views

- OpenCode raised one HIGH blocker: Plan 02 references `settings.resolved_indexing_paths`, which does not exist in the live `Settings` model. Claude mentioned this as LOW, likely assuming the attribute existed or would be caught by pyright. Live verification confirms the attribute is absent; the HIGH remains unresolved.
- Claude raised additional MEDIUM/LOW hardening suggestions around filesystem negative cursor tests, static scan baselines, CLI socket-check ordering, and `conn.commit()` assertions. OpenCode did not classify those as blockers.

### Verified Unresolved HIGH Concerns

- HIGH: `33-02-filesystem-lifecycle-migration-PLAN.md` references `settings.resolved_indexing_paths` in the risk table, task action, and acceptance criteria, but live `backend/src/dotmd/core/config.py` exposes `settings.indexing_paths` and `settings.effective_indexing_exclude`; no `resolved_indexing_paths` attribute exists. Plan 03 inherits the same factory-builder issue. This should be corrected before execution so agents do not implement against a phantom setting or add an unplanned config alias.

### Current HIGH Count

1
