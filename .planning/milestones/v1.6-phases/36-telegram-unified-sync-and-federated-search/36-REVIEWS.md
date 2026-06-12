---
phase: 36
reviewers: [codex, opencode]
reviewed_at: 2026-05-10T10:22:51Z
plans_reviewed: [36-01-PLAN.md, 36-02-PLAN.md]
---

# Cross-AI Plan Review — Phase 36

## Codex Review

## Summary

Plan 01 has a correctness blocker: it acknowledges TG-04 but does not implement the researched fix. Current code validates `ResourceBinding.ref` as `namespace:document_ref`, while Telegram public identity is message-shaped. A test alone will either test the wrong invariant or fail without an implementation path. Plan 02 is directionally solid and matches the lifecycle decision, but it needs sharper shutdown and single-worker-executor semantics.

## Plan 01 Review

### Strengths

- Correctly adds the missing `rebound_units` surface for TG-03.
- Puts rebound reporting near the existing binding refresh path, which is the right place.
- Adds CLI output for the new counter, reducing "hidden success" risk.
- Recognizes that skipped units still pass through the second loop, which matches the current pipeline behavior.

### Concerns

- **HIGH:** TG-04 is not fixed. The plan says local results are "satisfied by construction," but the confirmed bug is specifically `resource_bindings.ref` storing dialog-level refs while native search returns message-level refs. This contradicts the research.
- **HIGH:** Rebound lookup uses `change.document.document_ref`, which is dialog-level. If the intended binding is message-level, this will look up the wrong binding and either undercount or collapse multiple messages under one dialog.
- **HIGH:** The proposed `binding_ref` research fix is absent. Adding only a regression test risks pinning the wrong behavior.
- **MEDIUM:** Current `ResourceBinding` validation appears incompatible with message-level binding refs unless the model invariant changes. It currently expects `ref == f"{namespace}:{document_ref}"`; for Telegram that produces `telegram:dialog:<id>`, not `telegram:dialog:<id>:message:<id>`.
- **MEDIUM:** The plan does not specify whether `resource_ref` should become message-level for Telegram. That decision determines the correct rebound lookup key, uniqueness, and TG-04 behavior.
- **LOW:** `reused_units` CLI output is mentioned, but the plan should verify existing result metadata/checkpoint serialization still includes the new field consistently.

### Suggestions

- Add `binding_ref: str | None = None` to `ApplicationSourceChange`, and have Telegram set it to `public_ref_for_unit(unit)`.
- Use a single helper in the pipeline to derive the binding identity: `binding_resource_ref = change.binding_ref without namespace prefix` or equivalent, depending on the model decision.
- Update `ResourceBinding` validation deliberately. Prefer validating `ref == f"{namespace}:{resource_ref}"`, while preserving filesystem behavior because filesystem has `resource_ref == document_ref`.
- Rebound detection must call `get_resource_binding(namespace, resource_ref=<same key used for upsert>)`.
- Add a storage/pipeline regression test that ingests a Telegram message and asserts the persisted `resource_bindings.ref` equals `telegram:dialog:<id>:message:<id>`.
- Add a second test with two messages in one dialog to ensure bindings do not collapse at dialog level.

### Risk Assessment

**HIGH.** The plan touches the right files, but it does not actually resolve the TG-04 defect and may encode dialog-level behavior more deeply. Fix the binding identity model before executing the plan.

## Plan 02 Review

### Strengths

- Correctly keeps Telegram polling outside `TrickleIndexer`.
- Correctly uses `SourceRuntimeFactory.build_if_configured("telegram")` rather than direct provider construction.
- Correctly routes ingestion through the single-worker local executor.
- Configurable interval with a sane default matches the phase decision.
- Error-and-continue behavior is appropriate for a background sync loop.

### Concerns

- **MEDIUM:** The plan says `asyncio.sleep` with early wakeup. Plain `asyncio.sleep(interval)` is not early-wakeable; the better pattern is `await asyncio.wait_for(shutdown_event.wait(), timeout=interval)` and treat `TimeoutError` as "run next cycle."
- **MEDIUM:** A 30s shutdown timeout may be too short if ingestion is already running in the single-worker executor. Cancelling the asyncio task will not stop the underlying thread work.
- **MEDIUM:** The poller must not checkpoint unless local persistence succeeds. The plan depends on `ingest_application_source_runtime` preserving D-12; tests should cover that failure path or at least avoid adding checkpoint logic in the poller.
- **LOW:** Accessing `svc._local_executor` from `mcp_server.py` is pragmatic but couples lifespan code to a private service field. A small public service method would be cleaner if one already exists or can be added narrowly.
- **LOW:** The plan should define first-run behavior: sync immediately on startup, then wait, or wait first. For a server sync task, immediate first run is usually preferable.

### Suggestions

- Implement sleep as:
  ```python
  try:
      await asyncio.wait_for(shutdown_event.wait(), timeout=interval_seconds)
      break
  except TimeoutError:
      continue
  ```
  Or run once immediately, then use that pattern between runs.
- Use a shutdown timeout closer to the existing indexer timeout (120s), or document why Telegram gets only 30s. Recommended: 60s minimum.
- On timeout, log clearly that the asyncio task is cancelled but executor work may still finish.
- Test that shutdown during the interval exits promptly, not after 300s.
- Test that an exception from one sync iteration logs and the next iteration still runs.
- Keep all ingestion calls inside the existing lifecycle ingestion function; the poller should not manually manage cursors.

### Risk Assessment

**MEDIUM.** The architecture is right, but shutdown behavior and executor cancellation semantics need tightening. The biggest functional risk is not the polling loop itself; it is accidentally weakening the serialized write and checkpoint guarantees.

## Overall Codex Recommendation

Do not execute Plan 01 as written. Revise it so TG-04 is an implementation task, not just a regression test. The key invariant should be: local indexed Telegram results and native federated Telegram results expose the same message-level public ref, and persisted resource bindings use the same identity key that rebound detection uses.

Plan 02 can proceed after Plan 01 fixes binding identity, but include interruptible sleep and a realistic shutdown timeout. The correct sleep primitive is `wait_for(shutdown_event.wait(), timeout=interval)`, not plain `asyncio.sleep(interval)` plus a later flag check.

---

## OpenCode Review

*Note: OpenCode performed live code inspection of the codebase (fusion.py, pipeline.py, cli.py) before producing this review.*

## Plan 01: TG-03 rebound_units counter + TG-04 ref consistency regression test

### Summary

Adds the missing `rebound_units` counter to `ApplicationSourceIngestResult`, adds rebound detection via a pre-upsert `get_resource_binding` check, updates CLI output with both `rebound_units` and `reused_units`, and pins TG-04 with a regression test. The plan correctly identifies that TG-04 is satisfied by construction at the user-facing level (`_public_ref_for_provenance` in `fusion.py:184` already maps Telegram chunk refs to message-level, matching `search_native` output).

### Strengths

- **Correct PK for rebound lookup:** Using `(namespace, resource_ref = document.document_ref)` matches the `(namespace, resource_ref)` primary key of `resource_bindings` — same values used by `upsert_resource_binding` at `pipeline.py:587`.
- **Rebound detection placement is right:** Pre-upsert check in the second loop (line 583+) catches reactivation before the upsert flips `active=True`.
- **CLI fix piggybacking:** Plan adds `reused_units` to CLI output, which was already on `ApplicationSourceIngestResult` but never printed (confirmed at `cli.py:480-489`).
- **TG-04 test approach is practical:** Testing `ChunkProvenance.ref` / `_public_ref_for_provenance` output against expected `telegram:dialog:<id>:message:<id>` format covers the actual user-visible invariant without over-engineering.
- **TDD structure:** RED → GREEN → REFACTOR sequence is clear.

### Concerns

- **[MEDIUM] TG-04 research contradiction is papered over, not resolved:** The RESEARCH phase explicitly found: *"resource_bindings.ref is currently stored as the dialog-level ref (telegram:dialog:<id>) via change.document.ref, but search_native and public_ref_for_unit both return telegram:dialog:<id>:message:<id>."* The research proposed a fix (add `binding_ref` field to `ApplicationSourceChange`). Plan 01 acknowledges that `ChunkProvenance.ref` is message-level but says nothing about whether the `resource_bindings.ref` mismatch matters. Code inspection confirms it does NOT currently cause a user-visible TG-04 violation because `_public_ref_for_provenance` (line 184) uses `source_unit_refs[0]`, not `resource_bindings.ref`, for Telegram. However, the plan should **explicitly state** why the research's recommended fix is being deferred, or at least note the difference between "search result refs" (which are correct) and "resource binding refs" (which are dialog-level but not user-facing in search).

- **[LOW] Rebound detection does not check fingerprint mismatch:** The detection only checks `active=False`. If a dialog was previously bound with different metadata (e.g., dialog name changed), that's still a "changed" unit, not a "rebound" unit. The plan could clarify that "active=False" alone is the intended signal.

- **[LOW] `reused_units` already exists but was hidden:** CLI output never showed `reused_units` despite it being on the result dataclass since introduction. The plan correctly fixes this, but it's worth noting the research/context didn't flag this pre-existing gap.

### Suggestions

- Add a one-sentence rationale in the plan explaining: *"The `resource_bindings.ref` stores dialog-level refs which is an internal-only field not exposed in the TG-04 search-result path. Fixing it is out of scope for this plan — the regression test covers the user-facing invariant."*
- Make the TG-04 test explicit about lifecycle: test that a chunk produced by the pipeline (or a `ChunkProvenance` constructed the same way) has a `ref` matching `public_ref_for_unit(unit)`, which in turn equals `search_native` output format.
- Consider testing `_public_ref_for_provenance` directly: it's the actual TG-04 bridge — a unit test for it would be the strongest TG-04 anchor.

### Risk Assessment: **LOW**

The core additions (one `int` field, one `get_resource_binding` call, one conditional increment, two new CLI print arguments) are minimal and non-invasive. The only risk is the TG-04 test being too weak (testing the wrong thing) but the plan says the test will be hand-written — as long as the test author understands the actual invariant, this risk is small.

---

## Plan 02: Telegram auto-sync polling task in _server_lifespan (TG-01, TG-02)

### Summary

Wires the existing `ingest_application_source_runtime` call into a background `asyncio` polling task inside `_server_lifespan`, mirroring the `indexer_task` pattern. Adds one config field (`telegram_sync_interval_seconds`, default 300), creates `_run_telegram_poller` coroutine, and handles clean shutdown with a timeout. When `build_if_configured("telegram")` returns `None`, no task is created.

### Strengths

- **Architectural correctness:** Separate asyncio task (not inside TrickleIndexer) per D-02. Uses `loop.run_in_executor(_local_executor, ...)` for all SQLite writes per D-LOCAL-SERIALIZED. No `asyncio.to_thread()`.
- **Mirrors existing pattern:** `indexer_task` lifecycle at `mcp_server.py:509-526` provides a proven template — `asyncio.create_task`, `shutdown_event.set()`, `asyncio.wait_for(timeout)`, `cancel()` on timeout.
- **Delegated auth:** Uses `build_if_configured("telegram")` which already routes through `SourceRuntimeFactory` — no direct provider construction.
- **Configurable interval:** `DOTMD_TELEGRAM_SYNC_INTERVAL_SECONDS` env var override follows existing Settings conventions.

### Concerns

- **[MEDIUM] 30-second shutdown timeout is asymmetric:** `indexer_task` gets 120 seconds. The Telegram poller gets 30 seconds. But the poller may be mid-sync when shutdown arrives — `ingest_application_source_runtime` runs synchronously on the executor and cannot be preempted by cancellation (cancellation only affects `await` points). A single sync batch could legitimately take >30s. Consider 60s or matching the 120s given to `indexer_task`.

- **[LOW] Sleep pattern left ambiguous:** The plan says "Waits `interval_seconds` between runs using `asyncio.sleep` with early wakeup on `shutdown_event`." Two implementations are possible:
  - **Good:** `await asyncio.wait_for(shutdown_event.wait(), timeout=interval_seconds)` — early-wakeup pattern.
  - **Bad:** `await asyncio.sleep(interval_seconds)` without shutdown event — shutdown delayed up to 300s.
  The implementation section should be explicit about the code shape.

- **[LOW] Unnecessary dependency on Plan 01:** Plan 02 depends on Plan 01 only because it references `ApplicationSourceIngestResult` which gains `rebound_units`. But `rebound_units` has a default value `0` — Plan 02 works fine without Plan 01. Could be parallel.

- **[LOW] No backoff on consecutive failures:** If the Telegram daemon is down, the poller will spam ERROR logs every 300 seconds. No exponential backoff or circuit-breaker pattern is mentioned. Acceptable for v1 but worth noting.

- **[LOW] `CancelledError` during shutdown not explicitly handled:** The "On exception: logs ERROR and continues" clause should specifically exclude `CancelledError` which is expected during shutdown. Fix:
  ```python
  except asyncio.CancelledError:
      raise
  except Exception:
      logger.exception("Telegram sync failed")
  ```

### Suggestions

- Specify sleep pattern explicitly in implementation steps:
  ```python
  while not shutdown_event.is_set():
      result = await loop.run_in_executor(svc._local_executor, ...)
      logger.info(...)
      try:
          await asyncio.wait_for(shutdown_event.wait(), timeout=interval_seconds)
      except TimeoutError:
          pass  # interval expired, loop again
  ```
- Increase shutdown timeout to 60s to provide safety margin for in-flight sync operations.
- Distinguish `CancelledError` from real errors in the exception handler.
- Drop Plan 01 dependency or make it a soft dependency (note in PLAN.md that ordering is cosmetic, not structural).
- Add cleanup note: if `shutdown_event.wait_for()` times out and we cancel, suppress `CancelledError` — same as the existing pattern for `indexer_task`.

### Risk Assessment: **LOW**

The implementation is straightforward: one config field, one coroutine with ~20 lines, a few lines in `_server_lifespan`. The shutdown pattern is well-proven by `indexer_task`. The primary risk is the sleep pattern being implemented incorrectly (delaying shutdown), which can be caught in code review.

---

## Cross-Plan Issues (OpenCode)

- **[MEDIUM] Plan 01 defers the `resource_bindings.ref` fix without documenting why:** The research explicitly found a bug and proposed a fix (`binding_ref` field). Plan 01 neither fixes it nor explains the deferral. This creates ambiguity for the implementer: should they fix it or not? The plan should either include the fix or explicitly scope it out with a justification.

- **[LOW] No plan addresses `source_unit_refs=[]` (empty list) in resource bindings:** At `pipeline.py:597`, `source_unit_refs` is hardcoded to `[]` during application source ingestion. This means `resource_bindings` can't enumerate which messages belong to a dialog. Not in scope for Phase 36 but a latent issue if the `read` tool needs to map from a message ref to its dialog binding.

---

## Consensus Summary

Both Codex and OpenCode reviewed the same two plans. Key points of convergence and divergence:

### Agreed Strengths

- **Plan 02 architecture is sound:** Both reviewers confirm: separate asyncio task (not TrickleIndexer), `build_if_configured("telegram")` lifecycle, `loop.run_in_executor(_local_executor, ...)` for writes, configurable interval, error-and-continue. All decisions are correctly implemented.
- **Plan 01 rebound counter placement is correct:** Pre-upsert detection in the second loop correctly catches re-activation of inactive bindings. Lookup key `(namespace, document.document_ref)` matches the upsert PK.
- **CLI output improvement is unambiguously correct:** Adding `rebound_units` and `reused_units` to `telegram ingest` output fixes a known gap.
- **TDD RED→GREEN→REFACTOR structure:** Both reviewers find the task sequencing sound.

### Agreed Concerns

- **Sleep pattern must be interruptible (MEDIUM — Plan 02):** Both reviewers flag that plain `asyncio.sleep(interval)` would block shutdown for up to 300s. The correct pattern is `asyncio.wait_for(shutdown_event.wait(), timeout=interval_seconds)` catching `TimeoutError`.
- **30-second shutdown timeout is asymmetric (MEDIUM — Plan 02):** Both reviewers flag this; both recommend 60–120s to match the `indexer_task` timeout and account for in-flight executor work.
- **TG-04 / `resource_bindings.ref` contradiction needs explicit resolution (MEDIUM — Plan 01):** The research found a dialog-level ref stored in `resource_bindings.ref` but the plan claims TG-04 is satisfied by construction. Both reviewers agree the plan needs to either fix the bug or explicitly explain why it's not user-visible and is deferred.

### Divergent Views

- **Severity of Plan 01 TG-04 issue:** Codex rates Plan 01 as **HIGH risk** and says "do not execute as written" — it treats `resource_bindings.ref` storing the wrong level as a correctness blocker. OpenCode rates Plan 01 as **LOW risk** after live code inspection — it confirmed via `_public_ref_for_provenance` (fusion.py:184) that the user-facing search result path uses `source_unit_refs[0]` (message-level) and does not read `resource_bindings.ref`, so TG-04 is not violated at the API surface. The disagreement is about whether a data model inconsistency (internal storage mismatch) constitutes a TG-04 violation or is just latent technical debt.

- **Rebound lookup correctness:** Codex flags the dialog-level lookup key as a potential HIGH issue (may undercount or collapse messages); OpenCode confirms it's correct because `upsert_resource_binding` uses the same `(namespace, document_ref)` primary key — the lookup and the upsert use the same key, so detection is consistent.

### Resolution Guidance

1. **Plan 01 — TG-04:** The OpenCode live inspection resolves the Codex concern. `resource_bindings.ref` is not consumed by the user-facing search path; `_public_ref_for_provenance` correctly uses `source_unit_refs[0]`. However, **the plan must add an explicit note** explaining this so the implementer does not fix the wrong thing. The `resource_bindings.ref` data inconsistency should be tracked as technical debt (backlog item) separate from Phase 36.

2. **Plan 02 — sleep pattern:** Use `asyncio.wait_for(shutdown_event.wait(), timeout=interval_seconds)` + `except TimeoutError: pass`. This is now codified in the implementation section but should be verified in code review.

3. **Plan 02 — shutdown timeout:** Raise from 30s to 60s (or align with indexer_task's 120s). Add a `CancelledError` re-raise in the exception handler.

4. **Plan 01 — rebound lookup:** Confirmed correct by OpenCode. Codex concern is resolved.
