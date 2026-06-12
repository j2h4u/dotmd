---
phase: "34"
plan: "02"
type: tdd
wave: 2
depends_on: ["34-01"]
files_modified:
  - backend/src/dotmd/core/config.py
  - backend/src/dotmd/search/federated.py
  - backend/src/dotmd/ingestion/source_provider.py
  - backend/src/dotmd/ingestion/source_lifecycle.py
  - backend/src/dotmd/api/service.py
  - backend/src/dotmd/mcp_server.py
  - backend/tests/search/test_federated.py
  - backend/tests/api/test_service_search.py
  - backend/tests/mcp/test_mcp_search_envelope.py
  - backend/tests/search/conftest.py
autonomous: true
requirements: ["SEARCH-01", "SEARCH-03"]
requirements_addressed: ["SEARCH-01", "SEARCH-03"]
must_haves:
  truths:
    - "D-06: Federated providers participate in the same RRF as local engines. Engine names are namespaced (e.g. tg:fts). Per-engine weights remain. Fusion stays rank-only."
    - "D-07: Cross-encoder reranker is unchanged. Federated candidates (`chunk_id is None`) skip reranking and keep their RRF score. The `chunk_id is None` predicate is a Phase 34 simplification — it currently coincides with the only federated source (Telegram, short snippet text). When a future phase adds a federated provider that returns long-form text (e.g. Notion pages), the skip predicate must switch to a snippet-length test (`not snippet or len(snippet) < min_rerank_chars`). This phase pins the simpler predicate; the snippet-length variant is owned by the phase that introduces the second federated provider. (cycle-5 opencode LOW: predicate aligned across D-07 + threat model + Stage 6 prose.)"
    - "D-08: Federated fan-out is always-on by default. Every service.search() queries all local engines plus all sources whose descriptor declares FEDERATED_SEARCH and whose lifecycle bundle is currently constructible. Lifecycle build failures per-source are caught and recorded as persistent SourceStatus(status='error') entries — they never crash service init. (cycle-2 HIGH-6 fix)"
    - "D-09: Per-source soft timeout (3-5s default, config-tunable) applies to FEDERATED engines only. Local engines do not share this timeout — they execute on the established sequential path with no soft-skip. Failure detection only — not throughput shaping. (cycle-2 MEDIUM fold-in: separate timeouts)"
    - "D-10: MCP-level source filter parameters are deferred. Always-on fan-out at the MCP surface."
    - "D-11: Soft-skip per source on error/timeout. service.search() returns SearchResponse{candidates, source_status}. Local engines report through the same status surface."
    - "D-12: No fail-fast."
    - "D-18: Adding a second federated provider in a later phase requires no Phase 34 contract edits."
    - "D-OUTCOME-SPLIT: EngineOutcome is split by kind. LocalEngineOutcome.ranked_chunks is list[tuple[chunk_id, score]]; FederatedEngineOutcome.candidates is list[SearchCandidate]. The two shapes are NEVER conflated; orchestrator stage-3/4/5 handles them with explicit branches. (cycle-2 HIGH-3 fix)"
    - "D-LOCAL-SEQUENTIAL: Local search engines (semantic, fts5, graph_direct) execute SEQUENTIALLY in ONE worker thread; only federated providers fan out in parallel on the event loop. Phase 34 explicitly does NOT pursue concurrent local engines — shared SQLite/metadata/graph clients are not proven thread-safe. A test pins that local engines never run concurrently during a single service.search() call. (cycle-2 HIGH-4 fix)"
    - "D-LOCAL-SERIALIZED: Local search sequences are serialized ACROSS concurrent search_async() calls by a dedicated single-worker executor `self._local_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='dotmd-local-search')` constructed once in DotMDService.__init__. search_async dispatches the local sequence via `loop.run_in_executor(self._local_executor, self._run_local_search_sequence, ...)` instead of asyncio.to_thread (which uses the default executor and would let two concurrent requests overlap). Because max_workers=1, it is structurally impossible for two _run_local_search_sequence invocations to overlap — invariant by construction. Federated fan-out is unaffected and proceeds in parallel on the event loop. Two regression tests pin: (a) the executor's max_workers value (`test_local_executor_has_max_workers_one`), and (b) cross-request mutual exclusion (`test_concurrent_search_async_calls_do_not_overlap_local_sequences`). (cycle-4 HIGH fix)"
    - "D-LOOP-SAFE: search_async never blocks the FastMCP/FastAPI event loop. The full local engine sequence runs in ONE worker thread via `await loop.run_in_executor(self._local_executor, self._run_local_search_sequence, ...)` (preserving D-LOCAL-SEQUENTIAL within a request and D-LOCAL-SERIALIZED across requests — all three engines share the same single worker thread, never overlap with each other or with another request's local sequence), composed with federated fan-out via asyncio.gather so federated tasks progress concurrently with local work. A regression test pins that an unrelated `await asyncio.sleep(0)` interleaved into the test loop completes BEFORE search_async returns even when local engines are slow, capturing interleave_count via a `finally` block immediately after search_async finishes (so a post-return tick burst cannot mask a pre-return block). (cycle-3 HIGH fix; cycle-4 MEDIUM timing fix)"
    - "D-ASYNC-CANONICAL: search_async(query, ...) -> SearchResponse is the canonical async public method. The sync search() wrapper calls asyncio.run(search_async(...)) and fails LOUD with RuntimeError if invoked from inside a running event loop. MCP and FastAPI surfaces call search_async directly. CLI and unit tests use the sync wrapper. (cycle-2 HIGH-5 fix)"
    - "D-MCP-CANDIDATE-DIRECT: MCP search tool returns SearchResponse containing full SearchCandidate records (no SearchHit narrowing). Every public SearchCandidate field is exposed (descriptor_key, can_read, can_materialize, source_native_score, source_native_rank, engine_scores, provider_metadata). (cycle-2 HIGH-2 fix carried into Plan 02)"
---

# Phase 34 Plan 02: Federated Fan-out, Soft Timeout, And SearchResponse Envelope

<objective>
Add federated fan-out infrastructure: optional `search_native` protocol on
the lifecycle bundle, parallel `asyncio.gather` with per-source soft
timeout, `SourceStatus` collection for every fanned-out engine, the
`SearchResponse` envelope return shape on `DotMDService.search`, and the
MCP `search` tool envelope. Drives the contract end-to-end with a stub
federated provider — Telegram wiring is owned by Plan 03.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| One stuck federated source blocks the entire response | HIGH | Per-source `asyncio.wait_for(coro, timeout=N)` with config-driven timeout; total wall-time test pins behavior. |
| Federated source error breaks the query (fail-fast regression) | HIGH | Test stub raises; assert local results survive; `source_status` reports the error. |
| Provider-native scores leak into RRF as direct comparisons | HIGH | Federated stubs return absurd `source_native_score`; assert RRF rank-only — local hit at rank 1 still beats federated hit at rank 5 regardless of raw scores. |
| Lifecycle bundle rebuilt per request | HIGH | Service builds bundles once at init; mock asserts `factory.build_if_configured` called only at init. |
| Reranker called on candidates without rerank-eligible text → CrossEncoder error | MEDIUM | In Phase 34, skip reranker when `chunk_id is None` (i.e. federated). Assertion test pins federated candidates retain their RRF score after the rerank stage. The `chunk_id is None` predicate matches D-07 — it is the Phase 34 simplification documented there; future federated providers returning long-form text will switch to a snippet-length predicate. (cycle-5 opencode LOW: predicate now aligned across D-07 + threat model + Stage 6.) |
| MCP envelope schema regression breaks Claude Code | MEDIUM | Integration test through `mcp.server.fastmcp` test harness; pins schema keys. |
| Source filter params slip in early | MEDIUM | MCP search tool keeps signature `(query, top_k)`; test pins absence of `sources`/`exclude_sources` params. |
| `tg:fts` namespacing collides with engine names ("semantic", "keyword", "graph_direct") | MEDIUM | Engine name registry prevents collisions; test asserts federated engines use namespace prefix. |
| EngineOutcome shape conflates local chunk-keyed and federated SearchCandidate-keyed outputs (cycle-2 HIGH-3) | HIGH | Two outcome shapes: `LocalEngineOutcome(name, status, ranked_chunks: list[tuple[str, float]], reason, elapsed_ms)` and `FederatedEngineOutcome(name, status, candidates: list[SearchCandidate], reason, elapsed_ms)`. Type alias `EngineOutcome = LocalEngineOutcome | FederatedEngineOutcome`. Orchestrator stage 3 dispatches by isinstance. |
| Concurrent local engines corrupt shared SQLite/graph state (cycle-2 HIGH-4) | HIGH | Local engines run SEQUENTIALLY on the existing sync path; ONLY federated providers fan out in parallel. Test `test_local_engines_not_called_concurrently` wraps local engines with a contention-detector and asserts no overlap during a single `service.search()` call. |
| Sync search() inside running event loop deadlocks (cycle-2 HIGH-5) | HIGH | `search_async` is canonical; sync `search()` is a wrapper that calls `asyncio.get_running_loop()` to detect the unsafe condition and raises `RuntimeError("DotMDService.search() called from a running event loop; use search_async() instead")`. MCP and FastAPI surfaces call `search_async` directly. Test pins both the success path (await search_async inside loop) and the loud-fail path (sync search inside loop). |
| `search_async` blocks the FastMCP/FastAPI event loop during local search, stalling unrelated MCP requests (cycle-3 HIGH) | HIGH | Local engines run sequentially inside ONE worker thread via `await loop.run_in_executor(self._local_executor, self._run_local_search_sequence, query, pool_size)` instead of executing on the event-loop thread. This preserves D-LOCAL-SEQUENTIAL (all three engines share the same worker thread → no concurrent SQLite access) AND unblocks the loop. Federated fan-out tasks are CREATED before the local executor task is awaited and composed via `asyncio.gather(local_task, federated_task)` so federated and local work overlap from the loop's perspective. Regression test `test_search_async_does_not_block_event_loop` interleaves `await asyncio.sleep(0)` at multiple checkpoints during a slow local search and asserts each checkpoint resumes before search_async returns — pins "loop is not blocked" as load-bearing behavior. The interleaver coroutine captures its tick count via a `finally` block at the moment `search_async` completes (cycle-4 MEDIUM fix) so a post-return tick burst cannot mask a pre-return block. |
| Two concurrent `search_async()` requests run two `_run_local_search_sequence` invocations on different default-executor worker threads, breaking the cross-request single-thread SQLite/metadata/graph invariant (cycle-4 HIGH) | HIGH | Service constructs a dedicated single-worker `ThreadPoolExecutor(max_workers=1, thread_name_prefix="dotmd-local-search")` once in `__init__` and stores it as `self._local_executor`. `search_async` calls `loop.run_in_executor(self._local_executor, self._run_local_search_sequence, ...)` instead of `asyncio.to_thread(...)` (which uses the default global executor with N workers). Because the executor has a hard cap of one worker, two concurrent `search_async` calls SERIALIZE on the executor's queue — invariant by construction, no shared lock or barrier needed. Federated fan-out is unaffected (event-loop-bound, allowed to overlap between requests). Two regression tests pin the choice: `test_local_executor_has_max_workers_one` (asserts `service._local_executor._max_workers == 1` — structural pin) and `test_concurrent_search_async_calls_do_not_overlap_local_sequences` (records `(threading.get_ident(), enter_time, exit_time)` per call, asserts overlapping requests either share the same thread ident OR have disjoint [enter, exit] intervals — behavioral pin). Service shutdown calls `self._local_executor.shutdown(wait=True)` from `DotMDService.close()` to avoid leaked daemon threads. |
| Stage-2 `_batch_load_provenance` runs on the event-loop thread while another request's `_run_local_search_sequence` runs on the executor thread → same-process cross-thread SQLite reads (cycle-5 opencode MEDIUM) | MEDIUM | Pre-existing pattern (the legacy sync search path already crossed threads); replan-3's executor reifies it but does not introduce it. The search-path SQLite connection is opened with `check_same_thread=False` (already required project-wide for WAL mode) so concurrent reads from the loop thread (Stage-2 provenance load) and the `dotmd-local-search` executor thread (next request's local sequence) are safe per SQLite's threading model. New regression test `test_sqlite_connection_supports_cross_thread_access` exercises one read from the loop thread and one read from a separate worker thread on the same `DotMDService` connection and asserts no `sqlite3.ProgrammingError`. Documentation-and-pin only — no code change. |
| One misconfigured federated source crashes service init (cycle-2 HIGH-6) | HIGH | Service init catches per-source lifecycle build failures, records them in `self._lifecycle_init_errors: dict[str, str]`, and includes them as persistent `SourceStatus(status="error")` entries in every `SearchResponse`. Test `test_misconfigured_federated_source_does_not_crash_service_init` and `test_misconfigured_federated_source_appears_as_error_status_in_search`. |
| Federated timeout accidentally soft-skips slow local engines (cycle-2 MEDIUM) | MEDIUM | Local engines have NO soft timeout in Phase 34 (sequential, run to completion). The `federated_timeout_seconds` setting applies ONLY to federated provider calls. Test pins that a 5-second cold semantic call is not soft-skipped when `federated_timeout_seconds=1`. |
| asyncio.wait_for(asyncio.to_thread(...)) leaves zombie threads after timeout (cycle-2 MEDIUM) | LOW | Documented limitation: a timed-out provider thread keeps running until natural completion; logs may show late completion. No code mitigation in Phase 34 (Python's threading model does not support cooperative cancellation of `to_thread`-wrapped sync code). Comment near `wait_for` references this threat row. |
| Federated candidates accidentally populate engine_scores (D-02 violation) | MEDIUM | Test `test_federated_candidates_leave_engine_scores_none` asserts every federated candidate emerging from `_search_async` has `engine_scores is None`. |
</threat_model>

<tasks>
<task id="1" type="tdd">
<name>Add federated fan-out and source-status tests first</name>
<title>Add federated fan-out and source-status tests first</title>
<read_first>
- `.planning/phases/34-federated-searchcandidate-contract/34-CONTEXT.md`
- `.planning/phases/34-federated-searchcandidate-contract/34-RESEARCH.md`
- `.planning/phases/34-federated-searchcandidate-contract/34-PATTERNS.md`
- `.planning/phases/34-federated-searchcandidate-contract/34-01-searchcandidate-contract-and-ref-keyed-fusion-PLAN.md`
- `backend/src/dotmd/search/fusion.py`
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/ingestion/source_lifecycle.py`
- `backend/src/dotmd/ingestion/source_provider.py`
</read_first>
<files>
- `backend/tests/search/test_federated.py`
- `backend/tests/search/conftest.py`
</files>
<action>
Create `backend/tests/search/conftest.py` (or extend if it exists) with
fixtures:

- `StubFederatedProvider` — minimal class implementing
  `FederatedSearchProviderProtocol` (will be added in task 2). Methods:
  - `search_native(query: str, limit: int) -> list[SearchCandidate]` — sync
    method (the executor wraps it via `asyncio.to_thread`).
  - Configurable behavior via constructor: `(candidates, sleep_seconds=0,
    raises=None)`. When `sleep_seconds > 0`, the call sleeps before
    returning. When `raises` is set, the call raises the given exception.
- `slow_federated_provider(seconds)` factory.
- `failing_federated_provider(exc)` factory.
- `make_federated_bundle(name="stub", capabilities=None, provider=None)`
  factory that returns a fake `SourceRuntimeBundle` whose
  `supports_federated_search` is True (set
  `descriptor.capabilities=[SourceCapability.FEDERATED_SEARCH]` and attach
  the stub provider).

Create `backend/tests/search/test_federated.py` with failing tests:

- `test_engine_outcome_ok_carries_candidates_and_elapsed` — runs
  `_run_one("stub", coro_returning(2 candidates), timeout=5.0)` and asserts
  `outcome.status == "ok"`, `len(outcome.candidates) == 2`,
  `outcome.elapsed_ms is not None`.
- `test_engine_outcome_timeout_yields_skipped_with_reason_timeout` — uses
  `slow_federated_provider(seconds=10)` with `timeout=0.1`. Asserts
  `outcome.status == "skipped"`, `outcome.reason == "timeout"`,
  `outcome.candidates == []`, `outcome.elapsed_ms < 1000`.
- `test_engine_outcome_exception_yields_error_with_reason_message` — uses
  `failing_federated_provider(RuntimeError("daemon down"))`. Asserts
  `outcome.status == "error"`, `"daemon down" in outcome.reason`,
  `outcome.candidates == []`.
- `test_fanout_runs_in_parallel` — three federated providers each sleep 1s
  with timeout 5s; total fan-out wall time < 1.5s (parallel proof).
- `test_fanout_collects_source_status_for_every_engine_including_local` —
  given two local outcomes (`semantic` ok, `keyword` ok) and one federated
  outcome (`stub:fts` error), assert returned `list[SourceStatus]` has
  three entries with names `semantic`, `keyword`, `stub:fts`.
- `test_soft_timeout_does_not_block_response` — combines a fast local
  semantic outcome with a slow federated provider exceeding timeout;
  assert total wall time < `local_engine_time + timeout + 200ms slack`.
- `test_source_error_soft_skip_does_not_break_query` — federated provider
  raises, semantic returns 5 candidates; `service.search("foo")` returns
  `SearchResponse` with the 5 local candidates and a
  `SourceStatus(status="error")` for the federated source. No exception
  propagates.
- `test_source_status_attributes_each_engine` — every fanned-out engine
  produces exactly one `SourceStatus`. No duplicate entries even when an
  engine returns 0 candidates.
- `test_local_engine_outcome_carries_ranked_chunks_not_candidates`
  (**cycle-2 HIGH-3 fix**) — assert that running a local-engine call
  through the local outcome runner returns `LocalEngineOutcome` whose
  `ranked_chunks` field is `list[tuple[str, float]]` (chunk_id, score).
  Assert `not hasattr(outcome, "candidates")` (federated-only attribute).
- `test_federated_engine_outcome_carries_candidates_not_ranked_chunks`
  (**cycle-2 HIGH-3 fix**) — assert running a federated-engine call
  returns `FederatedEngineOutcome` whose `candidates` field is
  `list[SearchCandidate]`. Assert `not hasattr(outcome, "ranked_chunks")`.
- `test_local_engines_not_called_concurrently` (**cycle-2 HIGH-4 fix**) —
  wrap each local engine's `search` method with a contention detector
  decorator that records "running" state and raises if a second call
  starts while the first is in flight. Run `service.search("foo")`. Assert
  no concurrent invocation occurs across `semantic`, `keyword`,
  `graph_direct` engines. Federated stub providers are allowed to overlap
  with local execution and with each other.
- `test_federated_engines_run_in_parallel` (**cycle-2 HIGH-4 fix
  positive case**) — three federated stubs each sleep 1s with timeout 5s;
  total federated wall time < 1.5s (parallel proof). Sequential local
  engines + parallel federated still fits the response budget.
- `test_sync_search_in_running_loop_raises_runtime_error` (**cycle-2 HIGH-5
  fix**) — call `service.search("foo")` from inside `asyncio.run(...)`;
  assert `RuntimeError` whose message contains the substring
  `"running event loop"` and `"search_async"`.
- `test_async_search_in_running_loop_succeeds` (**cycle-2 HIGH-5 fix**) —
  call `await service.search_async("foo")` from inside `asyncio.run(...)`;
  assert it returns a `SearchResponse` without raising.
- `test_misconfigured_federated_source_does_not_crash_service_init`
  (**cycle-2 HIGH-6 fix**) — register a stub federated descriptor whose
  lifecycle factory raises `RuntimeError("missing config")`. Assert
  `DotMDService(...)` constructs successfully (no exception). Assert
  `len(service._lifecycle_bundles)` excludes the failed namespace. Assert
  `service._lifecycle_init_errors[failed_namespace]` is the failure message.
- `test_misconfigured_federated_source_appears_as_error_status_in_search`
  (**cycle-2 HIGH-6 fix**) — same setup; `service.search("foo")` returns
  `SearchResponse` whose `source_status` includes one entry with
  `name=failed_namespace`, `status="error"`, `reason` containing
  `"missing config"`, `candidate_count=0`.
- `test_federated_timeout_does_not_apply_to_local_engines` (**cycle-2
  MEDIUM fold-in**) — local semantic engine sleeps 5 seconds; service
  configured with `federated_timeout_seconds=1.0`; assert local results
  STILL appear in `response.candidates` (no soft-skip on local). The
  federated timeout applies only to federated providers.
- `test_federated_candidates_leave_engine_scores_none` (**cycle-2 MEDIUM
  fold-in**) — federated stub returns 3 candidates with arbitrary
  `source_native_score` values; after fanout + fusion, every federated
  candidate in `response.candidates` has `engine_scores is None`. Local
  candidates have `engine_scores` populated for engines that scored them.
- `test_search_async_does_not_block_event_loop` (**cycle-3 HIGH fix —
  load-bearing regression test; cycle-4 MEDIUM timing fix**) — patch
  `service._run_local_search_sequence` with a sync helper that
  `time.sleep(2.0)`s before returning empty results (simulating slow local
  I/O). Capture the interleaver count VIA A `finally` BLOCK INSIDE THE
  SEARCH CALL so the recorded value is frozen at the moment `search_async`
  completes — NOT after both coroutines drain (which is the cycle-4 MEDIUM
  trap: post-return ticks could mask pre-return blockage):
  ```python
  interleave_count = 0
  search_finished_count: int | None = None

  async def interleaver() -> None:
      nonlocal interleave_count
      for _ in range(20):
          await asyncio.sleep(0.05)
          interleave_count += 1

  async def search_wrapper() -> SearchResponse:
      nonlocal search_finished_count
      try:
          return await service.search_async("foo")
      finally:
          search_finished_count = interleave_count
  ```
  Run `await asyncio.gather(search_wrapper(), interleaver())`. Assert that
  `search_finished_count is not None` and `search_finished_count >= 15`
  (i.e. at least 15 of the 20 interleaver ticks fired BEFORE
  `search_async` completed). Crucially, do NOT assert on the post-gather
  `interleave_count` — that value would still be 20 even if the event
  loop was blocked, because once `search_async` returns the interleaver
  finishes its remaining iterations freely. This pins "loop unblocked
  DURING the search call", not "loop unblocked at any point". If
  `_run_local_search_sequence` were called directly inside the awaited
  coroutine instead of through `loop.run_in_executor(self._local_executor, ...)`,
  the interleaver would starve and `search_finished_count` would be ≤ 1.
- `test_search_async_local_engines_share_one_worker_thread` (**cycle-3
  HIGH fix — preserves D-LOCAL-SEQUENTIAL**) — patch each local engine's
  `search` method with a wrapper that records the current thread ID via
  `threading.get_ident()`. Run `await service.search_async("foo")`. Assert
  every recorded local-engine thread ID is identical (one shared worker
  thread, not three different threads from per-engine wraps) AND none of
  those thread IDs equals the event-loop thread ID. Also assert the
  recorded thread name starts with `"dotmd-local-search"` (the
  `thread_name_prefix` configured on `self._local_executor` —
  cycle-4 marker). This pins the exact wrap structure: ONE
  `loop.run_in_executor(self._local_executor, self._run_local_search_sequence)`
  call wrapping all three engines, NOT three separate executor submissions
  per engine (which would re-introduce concurrent local access).
- `test_federated_fanout_overlaps_with_local_search_sequence` (**cycle-3
  MEDIUM fold-in — overlap, not additive timeouts**) — federated stub
  sleeps 1.0s; patched `_run_local_search_sequence` sleeps 1.0s. Run
  `await service.search_async("foo")`. Assert total wall time is
  `< 1.5s` (proving overlap), NOT `>= 2.0s` (which would prove sequential
  local-then-federated). Documents the overlap budget: response time =
  `max(local_duration, federated_timeout)` rather than
  `local_duration + federated_timeout`.
- `test_local_executor_has_max_workers_one` (**cycle-4 HIGH fix —
  STRUCTURAL pin**) — construct a `DotMDService` with default
  configuration and assert
  `service._local_executor._max_workers == 1`. Also assert
  `isinstance(service._local_executor, ThreadPoolExecutor)` and
  `service._local_executor._thread_name_prefix == "dotmd-local-search"`.
  This is the load-bearing structural pin for D-LOCAL-SERIALIZED — if a
  future change swaps `ThreadPoolExecutor(max_workers=1)` back to the
  default executor (or raises `max_workers`), this test fails before any
  behavioral test even runs. Comment in the test must reference the
  cycle-4 HIGH so future readers know why the count is structural. Note
  that `_max_workers` is a CPython implementation detail (private
  attribute, not part of the `concurrent.futures` public API). The
  behavioral test below is the primary guarantee — if `_max_workers` is
  ever renamed in CPython, only this structural pin breaks; cross-request
  non-overlap is still enforced. Trade-off accepted as defense-in-depth.
  (cycle-5 opencode LOW: private-attribute trade-off documented.)
- `test_concurrent_search_async_calls_do_not_overlap_local_sequences`
  (**cycle-4 HIGH fix — BEHAVIORAL pin for cross-request mutual
  exclusion**) — patch `service._run_local_search_sequence` with a
  recorder that captures `(threading.get_ident(), enter_time, exit_time)`
  per invocation, sleeps 0.5 seconds while inside, then returns an empty
  outcome list. Launch two concurrent search calls:
  ```python
  results = await asyncio.gather(
      service.search_async("query_a"),
      service.search_async("query_b"),
  )
  ```
  Sort the two recorder entries by `enter_time` and assert ONE of the
  following two equivalent invariants holds (either is sufficient — both
  prove cross-request mutual exclusion):
  - **Invariant A — same-thread serialization:** both recorder entries
    have the same `threading.get_ident()` value, AND the second entry's
    `enter_time` is `>=` the first entry's `exit_time`. (This is the
    expected behavior with `max_workers=1` — the second submission waits
    for the first to release the single worker.)
  - **Invariant B — disjoint intervals:** the two intervals
    `[enter_time, exit_time]` are non-overlapping (entry-2.enter_time
    `>=` entry-1.exit_time). This is a stronger statement of A and works
    even if a future implementation switches to a different mechanism
    (e.g. an `asyncio.Lock`).
  Implementation note: prefer Invariant A as the primary assertion (it
  doubly pins both serialization AND single-thread identity); use B as
  a fallback comment for readers. With `max_workers=1` the two
  invocations land on the same worker by construction. If a regression
  removes the executor and re-introduces `asyncio.to_thread(...)` on the
  default executor (or replaces the executor with `max_workers >= 2`),
  this test fails because the two intervals overlap on different
  threads. Comment must reference the cycle-4 HIGH.
- `test_sqlite_connection_supports_cross_thread_access` (**cycle-5
  opencode MEDIUM** — Stage-2 `_batch_load_provenance` runs on the
  event-loop thread while the next request's `_run_local_search_sequence`
  may already be running on the `dotmd-local-search` executor thread,
  exercising the search-path SQLite connection from two different threads
  in the same process). Instantiate `DotMDService` against the test
  fixture index. Issue one read from the event-loop thread (call
  `service._batch_load_provenance({...some_chunk_id...})` directly) and,
  on the same `DotMDService` instance, issue another read driven from a
  different thread via `await asyncio.to_thread(lambda: service._batch_load_provenance({...}))`.
  Assert no `sqlite3.ProgrammingError` ("SQLite objects created in a
  thread can only be used in that same thread") is raised. This pins
  that the search-path SQLite connection was opened with
  `check_same_thread=False` — an existing project-wide WAL-mode
  requirement. Documentation-and-pin only; no code change is expected
  in task 3 to make this pass (it should already pass once the WAL
  connection is wired up). Comment must reference the cycle-5 opencode
  MEDIUM.

Tests must fail before task 2.
</action>
<acceptance_criteria>
- `backend/tests/search/conftest.py` contains `StubFederatedProvider`,
  `slow_federated_provider`, `failing_federated_provider`,
  `make_federated_bundle`, plus a `make_misconfigured_federated_factory`
  helper for the lifecycle init failure tests (cycle-2 HIGH-6).
- `backend/tests/search/test_federated.py` contains all 22+ tests named
  above (8 foundational + 8 cycle-2 review additions for outcome split,
  local sequential, async/sync bridge, lifecycle init failure, separate
  timeouts, federated engine_scores=None + 3 cycle-3 review additions:
  `test_search_async_does_not_block_event_loop`,
  `test_search_async_local_engines_share_one_worker_thread`,
  `test_federated_fanout_overlaps_with_local_search_sequence` + 2
  cycle-4 review additions:
  `test_local_executor_has_max_workers_one` (structural pin),
  `test_concurrent_search_async_calls_do_not_overlap_local_sequences`
  (behavioral pin for cross-request mutual exclusion) + 1 cycle-5
  opencode MEDIUM addition:
  `test_sqlite_connection_supports_cross_thread_access`).
- `rg -n 'test_search_async_does_not_block_event_loop|test_search_async_local_engines_share_one_worker_thread|test_federated_fanout_overlaps_with_local_search_sequence|test_local_executor_has_max_workers_one|test_concurrent_search_async_calls_do_not_overlap_local_sequences|test_sqlite_connection_supports_cross_thread_access' backend/tests/search/test_federated.py`
  returns one match per test name above (cycle-3 HIGH/MEDIUM markers + cycle-4 cross-request mutex pins + cycle-5 cross-thread pin).
- `cd backend && uv run pytest tests/search/test_federated.py -q` exits
  non-zero before task 2 (federated module/protocol does not exist).
- Tests reference `_run_local_engine`, `_run_federated_engine`,
  `LocalEngineOutcome`, `FederatedEngineOutcome`, `SearchResponse`,
  `SourceStatus`, `FederatedSearchProviderProtocol`, `search_async`.
</acceptance_criteria>
<verify>
`cd backend && uv run pytest tests/search/test_federated.py -q` fails
before task 2 because the federated module symbols do not exist yet.
</verify>
<done>
Federated fan-out tests exist and fail only for missing implementation.
</done>
</task>

<task id="2" type="tdd">
<name>Implement federated fan-out helper, protocol, and lifecycle bundle capability</name>
<title>Implement federated fan-out helper, protocol, and lifecycle bundle capability</title>
<read_first>
- `backend/tests/search/test_federated.py`
- `backend/tests/search/conftest.py`
- `backend/src/dotmd/search/fusion.py`
- `backend/src/dotmd/ingestion/source_provider.py`
- `backend/src/dotmd/ingestion/source_lifecycle.py`
- `backend/src/dotmd/api/service.py`
</read_first>
<files>
- `backend/src/dotmd/search/federated.py`
- `backend/src/dotmd/ingestion/source_provider.py`
- `backend/src/dotmd/ingestion/source_lifecycle.py`
- `backend/src/dotmd/core/config.py`
</files>
<action>
Create `backend/src/dotmd/search/federated.py` (cycle-2 HIGH-3 split outcome
shapes; HIGH-4 split runners; documents the wait_for-thread-cancellation
limitation per cycle-2 MEDIUM):

- Define two outcome shapes (split per cycle-2 HIGH-3):
  ```python
  @dataclass(frozen=True)
  class LocalEngineOutcome:
      name: str
      status: Literal["ok", "skipped", "error"]
      ranked_chunks: list[tuple[str, float]]  # (chunk_id, score)
      reason: str | None
      elapsed_ms: float

  @dataclass(frozen=True)
  class FederatedEngineOutcome:
      name: str
      status: Literal["ok", "skipped", "error"]
      candidates: list[SearchCandidate]  # provider-built
      reason: str | None
      elapsed_ms: float

  EngineOutcome = LocalEngineOutcome | FederatedEngineOutcome
  ```
- Define `def _run_local_engine(name: str, fn: Callable[[], list[tuple[str, float]]]) -> LocalEngineOutcome`:
  - **Synchronous; no timeout.** Local engines run sequentially in the
    caller's thread and run to completion. (cycle-2 HIGH-4 + MEDIUM
    timeout-scope fixes.) On `Exception`: log warning, return
    `LocalEngineOutcome(name, "error", [], str(exc), elapsed_ms)`.
    On success: return `LocalEngineOutcome(name, "ok", result, None,
    elapsed_ms)`.
  - Used by `_search_async` for `semantic`, `keyword`, `graph_direct`.
- Define `async def _run_federated_engine(name: str, fn: Callable[[], list[SearchCandidate]], timeout: float) -> FederatedEngineOutcome`:
  - Wraps the sync provider call with `asyncio.to_thread(fn)`, then
    `asyncio.wait_for(coro, timeout=timeout)`.
  - On `asyncio.TimeoutError`:
    `FederatedEngineOutcome(name, "skipped", [], "timeout", elapsed_ms)`.
  - On any other `Exception`: log warning with `exc_info=True`, return
    `FederatedEngineOutcome(name, "error", [], str(exc), elapsed_ms)`.
  - On success: return
    `FederatedEngineOutcome(name, "ok", candidates, None, elapsed_ms)`.
  - **Note (cycle-2 MEDIUM doc):** `asyncio.wait_for(asyncio.to_thread(...))`
    does NOT cancel the underlying thread on timeout. The thread runs to
    natural completion; the orchestrator simply ignores the late result.
    Logs may show "late completion after timeout" entries. This is an
    accepted Phase 34 limitation; revisit only if it produces operational
    pain.
- Define `async def fanout_federated(engine_calls: dict[str, Callable[[], list[SearchCandidate]]], timeout: float) -> list[FederatedEngineOutcome]`:
  - `outcomes = await asyncio.gather(*[_run_federated_engine(name, fn, timeout) for name, fn in engine_calls.items()])`.
  - Return outcomes in input dict iteration order (Python 3.12+ dicts
    preserve insertion order). Pin order with a test.
  - **Local engines are NOT passed through here** — they run sequentially
    via `_run_local_engine` BEFORE this function is awaited.
- Define `def outcomes_to_source_status(outcomes: Sequence[EngineOutcome]) -> list[SourceStatus]`:
  - Map each outcome to `SourceStatus(name, status, reason,
    candidate_count=count, elapsed_ms)`. For `LocalEngineOutcome`,
    `count = len(ranked_chunks)`; for `FederatedEngineOutcome`,
    `count = len(candidates)`.

Update `backend/src/dotmd/ingestion/source_provider.py`:

- Add `class FederatedSearchProviderProtocol(Protocol)`:
  ```python
  class FederatedSearchProviderProtocol(Protocol):
      def search_native(self, query: str, limit: int) -> list[SearchCandidate]: ...
  ```
- Do NOT extend `ApplicationSourceProviderProtocol` (Phase 28 surface
  stays untouched).

Update `backend/src/dotmd/ingestion/source_lifecycle.py`:

- Add a `supports_federated_search` `@property` to `SourceRuntimeBundle`:
  ```python
  @property
  def supports_federated_search(self) -> bool:
      if SourceCapability.FEDERATED_SEARCH not in self.descriptor.capabilities:
          return False
      provider = self.provider
      if provider is None:
          return False
      return callable(getattr(provider, "search_native", None))
  ```
- No constructor changes required.

Update `backend/src/dotmd/core/config.py`:

- Add a `federated_timeout_seconds: float = 4.0` setting (between 3.0 and
  5.0 per D-09 default range; pick 4.0). Mark as tunable through env var
  `DOTMD_FEDERATED_TIMEOUT_SECONDS`.
- Add a `federated_engine_weights: dict[str, float] = Field(default_factory=dict)`
  setting (parsed from env if convenient; no env wiring required if
  costly — leave config-only for Phase 34, env wiring is a deferred task).
</action>
<acceptance_criteria>
- `backend/src/dotmd/search/federated.py` contains
  `class LocalEngineOutcome`, `class FederatedEngineOutcome`,
  `def _run_local_engine` (sync), `async def _run_federated_engine`,
  `async def fanout_federated`, `def outcomes_to_source_status`.
  (cycle-2 HIGH-3 + HIGH-4 split markers)
- `backend/src/dotmd/search/federated.py` does NOT contain a generic
  `_run_one` or `fanout_search` that conflates local and federated calls
  (cycle-2 HIGH-3): `rg -n 'def _run_one\b|def fanout_search\b'
  backend/src/dotmd/search/federated.py` returns no matches.
- `backend/src/dotmd/ingestion/source_provider.py` contains
  `class FederatedSearchProviderProtocol(Protocol)` with `search_native`.
- `backend/src/dotmd/ingestion/source_lifecycle.py` `SourceRuntimeBundle`
  has a `supports_federated_search` property.
- `backend/src/dotmd/core/config.py` contains
  `federated_timeout_seconds: float = 4.0` (verify with `rg`).
- `backend/src/dotmd/core/config.py` does NOT contain a
  `local_engine_timeout` or any setting that applies the federated
  timeout to local engines (cycle-2 MEDIUM): `rg -n 'local_engine_timeout'
  backend/src/dotmd/core/config.py` returns no matches.
- `cd backend && uv run pytest tests/search/test_federated.py -q -k 'local_engine_outcome or federated_engine_outcome or run_federated_engine or fanout_federated or run_local_engine'` exits 0.
- `cd backend && uv run pyright src/dotmd/search/federated.py src/dotmd/ingestion/source_provider.py src/dotmd/ingestion/source_lifecycle.py src/dotmd/core/config.py tests/search/test_federated.py tests/search/conftest.py` exits 0.
</acceptance_criteria>
<verify>
`cd backend && uv run pytest tests/search/test_federated.py -q -k 'engine_outcome or fanout_federated or run_local_engine or run_federated_engine'`
`cd backend && uv run pyright src/dotmd/search/federated.py src/dotmd/ingestion/source_provider.py src/dotmd/ingestion/source_lifecycle.py src/dotmd/core/config.py tests/search/test_federated.py tests/search/conftest.py`
`rg -n 'def _run_one\b|def fanout_search\b' backend/src/dotmd/search/federated.py` (must return zero — cycle-2 HIGH-3 enforcement)
</verify>
<done>
Fan-out helper, federated protocol, and lifecycle capability discovery
exist and are typed/test-pinned at the helper level.
</done>
</task>

<task id="3" type="tdd">
<name>Wire federated fan-out into DotMDService.search and switch return shape to SearchResponse</name>
<title>Wire federated fan-out into DotMDService.search and switch return shape to SearchResponse</title>
<read_first>
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/search/federated.py`
- `backend/src/dotmd/search/fusion.py`
- `backend/src/dotmd/ingestion/source_lifecycle.py`
- `backend/tests/search/test_federated.py`
- `backend/tests/api/test_service_search.py`
</read_first>
<files>
- `backend/src/dotmd/api/service.py`
- `backend/tests/api/test_service_search.py`
</files>
<action>
Add lifecycle-bundle caching and fan-out orchestration to `DotMDService`.

In `DotMDService.__init__` (cycle-2 HIGH-6 graceful skip on lifecycle build
failure):

- Build a `SourceRuntimeFactory` and call `build_if_configured(namespace)`
  for every namespace registered in `self._registry` (from the existing
  Phase 32-33 plumbing) wrapped in try/except per-namespace:
  ```python
  self._lifecycle_bundles: dict[str, SourceRuntimeBundle] = {}
  self._lifecycle_init_errors: dict[str, str] = {}
  for namespace in self._registry.namespaces():
      try:
          bundle = factory.build_if_configured(namespace)
      except Exception as exc:
          logger.warning(
              "Lifecycle build failed for source %r: %s",
              namespace, exc, exc_info=True,
          )
          self._lifecycle_init_errors[namespace] = str(exc)
          continue
      if bundle is None:
          continue
      self._lifecycle_bundles[namespace] = bundle
  ```
  - **Service init MUST proceed even if every federated source fails to
    build.** This is the cycle-2 HIGH-6 fix: D-08 says fan-out queries
    sources whose lifecycle bundle is "currently constructible" — a build
    failure becomes a recorded error status, not a startup crash.
- Compute `self._federated_bundles: list[SourceRuntimeBundle]` once at
  init by filtering `bundle.supports_federated_search`.
- **Construct the dedicated single-worker local-search executor (cycle-4
  HIGH fix — D-LOCAL-SERIALIZED).** Add to `__init__`:
  ```python
  from concurrent.futures import ThreadPoolExecutor

  # Cross-request mutual exclusion for the local search sequence.
  # max_workers=1 makes it STRUCTURALLY IMPOSSIBLE for two concurrent
  # search_async() calls to overlap their _run_local_search_sequence
  # invocations — they queue on the executor instead. asyncio.to_thread
  # would use the default executor (multiple workers) and could overlap
  # two requests on different worker threads, breaking the cross-request
  # single-thread SQLite/metadata/graph invariant. (cycle-4 HIGH)
  self._local_executor = ThreadPoolExecutor(
      max_workers=1,
      thread_name_prefix="dotmd-local-search",
  )
  ```
  - The executor is constructed ONCE at service init and reused for the
    lifetime of the service — never re-created per request.
  - **Test pin:** `test_local_executor_has_max_workers_one` asserts
    `service._local_executor._max_workers == 1` and the
    `_thread_name_prefix == "dotmd-local-search"` so a future code change
    that reverts to `asyncio.to_thread` (default executor) or raises
    `max_workers` fails the test before any behavior runs.
- **Add `def close(self)` (or extend the existing one if present) to
  shut the executor down cleanly:**
  ```python
  def close(self) -> None:
      # Existing teardown (graph clients, sqlite handles, etc.) ...
      try:
          self._local_executor.shutdown(wait=True)
      except Exception:
          logger.warning("local_executor shutdown failed", exc_info=True)
  ```
  - `wait=True` blocks until any in-flight local search drains —
    important during process exit so we don't leave an active SQLite
    transaction half-open.
  - If `DotMDService.close` does not yet exist, add it AND register it
    via FastAPI/MCP shutdown hooks. **Plan 02 owns this wiring** — both
    the `close()` method body and its registration into the FastAPI
    lifespan and the FastMCP server's shutdown hook are in scope here.
    Plan 03 does not touch service lifecycle (its scope is the Telegram
    federated provider + read-routing), so the prior "out of scope:
    owned by Plan 03 if it touches the lifecycle layer" caveat is
    discarded — there is no overlap to defer. (cycle-5 opencode LOW:
    shutdown ownership made explicit; no overlap with Plan 03.)

Public sync/async surface (cycle-2 HIGH-5 fix — `search_async` is canonical):

- New `async def search_async(self, query: str, top_k: int = 10, mode: str =
  "auto", rerank: bool = True, expand: bool = True,
  reranker_name: str | None = None) -> SearchResponse` — the canonical
  public method. Runs the full fan-out pipeline. MCP and FastAPI surfaces
  call this directly.
- Public `def search(self, query, ...) -> SearchResponse` is a sync wrapper
  that LOUDLY refuses to run inside an existing event loop:
  ```python
  def search(self, query: str, **kwargs) -> SearchResponse:
      try:
          asyncio.get_running_loop()
      except RuntimeError:
          # No loop running — safe to bridge with asyncio.run.
          return asyncio.run(self.search_async(query, **kwargs))
      raise RuntimeError(
          "DotMDService.search() called from a running event loop; "
          "use search_async() instead",
      )
  ```
  - The sync wrapper is intended for CLI and unit-test contexts. MCP /
    FastAPI / any code already inside an event loop MUST call
    `await search_async(...)` directly.

Inside `async def search_async(self, ...)` (cycle-2 HIGH-3 outcome split,
HIGH-4 sequential local + parallel federated; **cycle-3 HIGH fix —
local sequence runs off-loop in one worker thread, overlapped with
federated fan-out via `asyncio.gather`**):

  - Stage 0 — record persistent lifecycle errors (cycle-2 HIGH-6 surface):
    ```python
    persistent_status: list[SourceStatus] = [
        SourceStatus(name=ns, status="error", reason=msg, candidate_count=0,
                     elapsed_ms=0.0)
        for ns, msg in self._lifecycle_init_errors.items()
    ]
    ```
  - Stage 1 — concurrent local-thread + federated fan-out (**cycle-3 HIGH
    fix; cycle-4 HIGH cross-request serialization**). Local engines run
    sequentially in ONE worker thread on the dedicated single-worker
    executor (`self._local_executor`, max_workers=1, constructed in
    `__init__`). This preserves D-LOCAL-SEQUENTIAL within a single request
    AND D-LOCAL-SERIALIZED across concurrent requests — two simultaneous
    `search_async` calls queue on the executor rather than running
    `_run_local_search_sequence` concurrently on different default-pool
    threads. Federated fan-out runs on the event loop. Both proceed in
    parallel, gathered:
    ```python
    # Build federated calls dict (cycle-2 HIGH-4 keeps federated parallelism)
    federated_calls: dict[str, Callable[[], list[SearchCandidate]]] = {}
    for bundle in self._federated_bundles:
        name = self._federated_engine_name(bundle)
        federated_calls[name] = lambda b=bundle: b.provider.search_native(
            query, limit=pool_size,
        )

    # Local sequence runs off the event loop in ONE worker thread on
    # the SHARED single-worker executor. `_run_local_search_sequence` is
    # a SYNC method that runs semantic → keyword → graph_direct in order.
    # All three engines share the SAME worker thread (NOT three separate
    # executor submissions) — preserving D-LOCAL-SEQUENTIAL within the
    # request — AND because the executor has max_workers=1, two
    # concurrent search_async() calls cannot overlap their local
    # sequences either, preserving D-LOCAL-SERIALIZED across requests.
    # (cycle-3 HIGH event-loop fix + cycle-4 HIGH cross-request fix.)
    #
    # IMPORTANT: do NOT use asyncio.to_thread(self._run_local_search_sequence, ...).
    # That dispatches to the default executor (typically max_workers =
    # min(32, os.cpu_count()+4)) and lets two concurrent requests run two
    # local sequences on two different worker threads — exactly the
    # cycle-4 HIGH defect. Always go through self._local_executor.
    loop = asyncio.get_running_loop()
    local_task = loop.run_in_executor(
        self._local_executor,
        self._run_local_search_sequence,
        query,
        pool_size,
    )
    federated_task = fanout_federated(
        federated_calls,
        timeout=self._settings.federated_timeout_seconds,
    )

    # asyncio.gather runs local thread + federated fan-out concurrently
    # from the loop's perspective. Response time = max(local_duration,
    # federated_timeout), NOT additive. (cycle-3 MEDIUM fold-in.)
    local_outcomes, federated_outcomes = await asyncio.gather(
        local_task, federated_task,
    )
    ```

    Define the new sync helper `_run_local_search_sequence` on
    `DotMDService`:
    ```python
    def _run_local_search_sequence(
        self, query: str, pool_size: int,
    ) -> list[LocalEngineOutcome]:
        """Run all three local engines sequentially in the calling thread.

        This is INTENTIONALLY synchronous and meant to be invoked via
        `loop.run_in_executor(self._local_executor,
        self._run_local_search_sequence, ...)`. All three engines share
        this thread within a single call → no concurrent SQLite/graph
        access within a request (D-LOCAL-SEQUENTIAL) → no event-loop
        blockage (D-LOOP-SAFE). Because `self._local_executor` has
        `max_workers=1`, two concurrent `search_async()` calls cannot
        overlap their local sequences either (D-LOCAL-SERIALIZED) —
        invariant by construction.

        DO NOT call this from inside an event loop directly — that
        re-introduces the cycle-3 HIGH (event-loop blockage).

        DO NOT call this via `asyncio.to_thread(...)` — that uses the
        default multi-worker executor and re-introduces the cycle-4 HIGH
        (cross-request concurrency on shared SQLite/metadata/graph
        clients). Always dispatch through `self._local_executor`.
        """
        outcomes: list[LocalEngineOutcome] = []
        outcomes.append(_run_local_engine(
            "semantic",
            lambda: self._semantic_engine.search(query, top_k=pool_size),
        ))
        outcomes.append(_run_local_engine(
            "keyword",
            lambda: self._keyword_engine.search(query, top_k=pool_size),
        ))
        outcomes.append(_run_local_engine(
            "graph_direct",
            lambda: self._graph_direct_engine.search(query, top_k=pool_size),
        ))
        return outcomes
    ```

    Local engines have NO per-engine soft timeout — they run to natural
    completion within the worker thread. (cycle-2 HIGH-4 + MEDIUM
    timeout-scope fixes preserved.) Federated `wait_for` timeout is
    unchanged and applies only to federated providers.

    **Why one executor submission, not three (cycle-3 HIGH-4 preserved):**
    wrapping each local engine in its own
    `loop.run_in_executor(self._local_executor, self._semantic_engine.search, ...)`
    submission would queue three jobs on the executor and run them one at
    a time on the same single worker — equivalent in safety, but worse:
    each job pays the queue handoff overhead and the federated `gather`
    only completes after all three sequential jobs drain. ONE submission
    that wraps the entire sync sequence keeps all three engines on the
    same thread within ONE atomic executor job by construction.
    `test_search_async_local_engines_share_one_worker_thread` pins this
    structural choice.

    **Why a dedicated single-worker executor, not `asyncio.to_thread`
    (cycle-4 HIGH fix):** `asyncio.to_thread(...)` uses the default
    `loop.run_in_executor(None, ...)` executor — typically a
    `ThreadPoolExecutor(max_workers=min(32, os.cpu_count()+4))`. With
    multiple workers, two concurrent `search_async()` requests would
    each get a different default-pool worker thread and run two
    `_run_local_search_sequence` invocations concurrently — exactly the
    cycle-4 defect. Hard-capping our private executor at `max_workers=1`
    forces concurrent requests to QUEUE on the executor instead, making
    cross-request mutual exclusion structurally impossible to violate.
    `test_local_executor_has_max_workers_one` pins the cap;
    `test_concurrent_search_async_calls_do_not_overlap_local_sequences`
    pins the resulting non-overlap invariant.

    **Why a dedicated executor and not an `asyncio.Lock`:** an
    `asyncio.Lock` would also serialize cross-request local sequences,
    but the lock object lives in user-space and a future maintainer
    could accidentally drop the lock acquire (e.g. when refactoring the
    `gather` shape) without any structural failure mode catching it.
    The single-worker executor is a structural primitive: any code path
    that submits work to it inherits the serialization guarantee. This
    aligns with the project motto "invariant by construction" (project
    memory: `feedback_invariant_by_construction.md`). The `asyncio.Lock`
    alternative was considered and rejected for this reason.
  - Stage 2 — assemble per-engine ranked-ref dict by branching on outcome
    kind:
    ```python
    per_engine_ref: dict[str, list[tuple[str, float]]] = {}
    federated_candidates_by_ref: dict[str, SearchCandidate] = {}

    chunk_ids: set[str] = set()
    for outcome in local_outcomes:
        if outcome.status != "ok":
            continue
        chunk_ids.update(cid for cid, _ in outcome.ranked_chunks)
    provenance_map = self._batch_load_provenance(chunk_ids)

    for outcome in local_outcomes:
        if outcome.status != "ok":
            continue
        per_engine_ref[outcome.name] = hydrate_local_engine_results(
            {outcome.name: outcome.ranked_chunks}, provenance_map,
        )[outcome.name]

    for outcome in federated_outcomes:
        if outcome.status != "ok":
            continue
        per_engine_ref[outcome.name] = [
            (c.ref, c.source_native_score or 1.0)
            for c in outcome.candidates
        ]
        for c in outcome.candidates:
            federated_candidates_by_ref[c.ref] = c
    ```
  - Stage 3 — `fuse_results(per_engine_ref, k=settings.fusion_k,
    engine_weights=settings.federated_engine_weights | local_weights)`.
  - Stage 4 — apply active-binding filter to fused results: federated-only
    refs (no entry in `provenance_map`) bypass the filter; local refs
    follow the existing inactive drop logic.
  - Stage 5 — build candidates: `build_candidates_with_federated(fused,
    per_engine_ref, ref_to_local_metadata, federated_candidates_by_ref,
    query, top_k)`. This extends `build_candidates` from Plan 01 to
    accept a `federated_candidates_by_ref: dict[str, SearchCandidate]`.
    The merge logic distinguishes LOCAL refs from FEDERATED refs by
    membership in `federated_candidates_by_ref`, and applies different
    `engine_scores` policies per branch (cycle-4 LOW prose fix —
    previously this paragraph implied a single merge that was contradicted
    by D-02; the two branches are now stated explicitly):
    - **LOCAL refs** (refs absent from `federated_candidates_by_ref`):
      populate `engine_scores` from the per-local-engine RRF
      contributions in `per_engine_ref` exactly as Plan 01 does. Local
      candidates get `engine_scores={"semantic": rrf_a, "keyword": rrf_b,
      "graph_direct": rrf_c}` (any subset, depending on which engines
      retrieved that ref).
    - **FEDERATED refs** (refs present in `federated_candidates_by_ref`):
      take the prebuilt `SearchCandidate` from the federated outcome AS-IS
      and OVERWRITE its `engine_scores` field with `None` regardless of
      what the federated provider sent. The D-02 invariant ("federated
      candidates have `engine_scores=None`") is enforced ONE-WAY at the
      builder level — the builder is the single point where
      `engine_scores=None` is stamped, so no upstream code path can leak
      a non-None value. `test_federated_candidates_leave_engine_scores_none`
      pins this invariant: every federated candidate emerging from
      `_search_async` has `engine_scores is None`, even if the stub
      provider returned a non-None value.

    Per-engine attribution for federated engines is NOT merged into
    `engine_scores` — it lives only in the upstream `per_engine_ref`
    table and the `SourceStatus` records. The D-02 invariant is the
    single source of truth for federated candidates' `engine_scores`.
  - Stage 6 — optional reranker: pass through candidates whose
    `chunk_id is None` AS-IS (skip rerank), keep their RRF score. The
    `chunk_id is None` predicate is the Phase 34 simplification documented
    in D-07 — it currently coincides with "federated candidate carrying
    only short Telegram-style snippet text". When a future phase adds a
    federated provider returning long-form text (e.g. Notion pages),
    this predicate must switch to a snippet-length test
    (`not snippet or len(snippet) < min_rerank_chars`); that change is
    owned by the phase that introduces the second federated provider.
    (cycle-5 opencode LOW: Phase 34 simplification documented at
    Stage 6 alongside D-07 and the threat model row.)
  - Stage 7 — assemble:
    ```python
    return SearchResponse(
        candidates=top_k_candidates,
        source_status=(
            persistent_status
            + outcomes_to_source_status(local_outcomes)
            + outcomes_to_source_status(federated_outcomes)
        ),
    )
    ```

- Helper `def _federated_engine_name(self, bundle: SourceRuntimeBundle) -> str`:
  - For `telegram` namespace: return `"tg:fts"`.
  - General fallback: `f"{bundle.descriptor.namespace}:fts"`.

In `backend/tests/api/test_service_search.py`:

- Update `test_local_only_search_returns_searchcandidate` (from Plan 01)
  to assert `service.search("foo")` returns a `SearchResponse`.
- Add `test_lifecycle_bundles_built_once` — mock `SourceRuntimeFactory`;
  assert `build_if_configured` is called only during `DotMDService.__init__`
  and not during search.
- Add `test_search_response_envelope_has_local_source_status` — service
  with no federated providers; assert `response.source_status` has at
  least entries for local engines (`semantic`, `keyword`, `graph_direct`).
- Add `test_search_response_includes_federated_source_status_when_bundle_present`
  — service with a stub federated bundle; assert `source_status` includes
  the bundle's engine name.
- Add `test_federated_only_ref_bypasses_active_binding_filter` — stub
  federated provider returns one ref unknown to local store; assert it
  appears in `response.candidates` (not dropped by inactive filter).
- Add `test_provider_native_score_does_not_outrank_local_via_raw_score`
  — stub federated provider returns a candidate with
  `source_native_score=1e6` at rank 5; semantic returns a hit at rank 1;
  assert local hit's RRF score > federated hit's RRF score.
</action>
<acceptance_criteria>
- `backend/src/dotmd/api/service.py` `DotMDService.__init__` builds and
  caches lifecycle bundles in `self._lifecycle_bundles`. (`rg -n
  'self\._lifecycle_bundles' backend/src/dotmd/api/service.py` returns
  matches.)
- `backend/src/dotmd/api/service.py` `DotMDService.__init__` records
  per-source build failures in `self._lifecycle_init_errors`. (cycle-2
  HIGH-6 marker — `rg -n '_lifecycle_init_errors'
  backend/src/dotmd/api/service.py` returns matches.)
- `backend/src/dotmd/api/service.py` defines `async def search_async`
  (canonical) and `def search` (sync wrapper). (cycle-2 HIGH-5)
- `backend/src/dotmd/api/service.py` `def search` raises `RuntimeError`
  when called from inside a running event loop — assertion verified by
  `test_sync_search_in_running_loop_raises_runtime_error`.
- `backend/src/dotmd/api/service.py` `_federated_engine_name` exists.
- `backend/src/dotmd/api/service.py` defines a sync helper
  `def _run_local_search_sequence(self, query: str, pool_size: int) -> list[LocalEngineOutcome]`
  that calls `_run_local_engine` for `semantic`, `keyword`, and
  `graph_direct` in order. (cycle-3 HIGH marker — `rg -n
  'def _run_local_search_sequence' backend/src/dotmd/api/service.py`
  returns at least one match.)
- `backend/src/dotmd/api/service.py` `DotMDService.__init__` constructs
  `self._local_executor = ThreadPoolExecutor(max_workers=1,
  thread_name_prefix="dotmd-local-search")` (cycle-4 HIGH marker —
  D-LOCAL-SERIALIZED). Verify with `rg`:
  - `rg -n 'self\._local_executor\s*=\s*ThreadPoolExecutor' backend/src/dotmd/api/service.py` returns at least one match.
  - `rg -n 'max_workers=1' backend/src/dotmd/api/service.py` returns at least one match for the local executor.
  - `rg -n 'thread_name_prefix=.dotmd-local-search.' backend/src/dotmd/api/service.py` returns at least one match.
  - `rg -n 'from concurrent\.futures import ThreadPoolExecutor' backend/src/dotmd/api/service.py` returns at least one match.
- `backend/src/dotmd/api/service.py` `search_async` invokes
  `loop.run_in_executor(self._local_executor, self._run_local_search_sequence, ...)`
  exactly ONCE (the whole local sequence in one worker thread on the
  dedicated single-worker executor, NOT three per-engine submissions or
  any `asyncio.to_thread` call on the default pool). Verify with `rg`:
  - `rg -n 'run_in_executor\(\s*self\._local_executor' backend/src/dotmd/api/service.py` returns at least one match (cycle-4 HIGH structural marker).
  - `rg -n 'self\._run_local_search_sequence' backend/src/dotmd/api/service.py` returns matches both at the executor dispatch site AND at the helper definition (cycle-3 HIGH preserved).
  - `rg -n 'asyncio\.to_thread\(' backend/src/dotmd/api/service.py` returns NO matches in `search_async` (cycle-4 HIGH — the default-executor path is the defect class).
  - `rg -n 'asyncio\.to_thread.*semantic|asyncio\.to_thread.*keyword|asyncio\.to_thread.*graph_direct' backend/src/dotmd/api/service.py` returns NO matches (cycle-2 HIGH-4 + cycle-3 + cycle-4 structural choice — per-engine wraps OR default-pool wraps would regress single-threaded local access).
- `backend/src/dotmd/api/service.py` `search_async` composes local + federated
  via `asyncio.gather(local_task, federated_task)` (cycle-3 MEDIUM fold-in
  — overlap, not additive). `rg -n 'asyncio\.gather' backend/src/dotmd/api/service.py`
  returns at least one match.
- `backend/src/dotmd/api/service.py` `DotMDService.close()` calls
  `self._local_executor.shutdown(wait=True)` so the dedicated worker
  thread is reaped at process exit (cycle-4 HIGH housekeeping). `rg -n
  'self\._local_executor\.shutdown' backend/src/dotmd/api/service.py`
  returns at least one match.
- `rg -n 'fanout_search\b' backend/src/dotmd/api/service.py` returns no
  matches (cycle-2 HIGH-3 — old conflated helper is gone).
- `DotMDService.search` and `DotMDService.search_async` both return
  `SearchResponse` (verified by type annotation and tests).
- `cd backend && uv run pytest tests/search/test_federated.py tests/api/test_service_search.py -q` exits 0.
- `cd backend && uv run pyright src/dotmd/api/service.py src/dotmd/search/federated.py tests/search/test_federated.py tests/api/test_service_search.py` exits 0.
</acceptance_criteria>
<verify>
`cd backend && uv run pytest tests/search/test_federated.py tests/api/test_service_search.py -q`
`cd backend && uv run pyright src/dotmd/api/service.py src/dotmd/search/federated.py tests/search/test_federated.py tests/api/test_service_search.py`
</verify>
<done>
`DotMDService.search` returns `SearchResponse`, fans out across local
engines plus stub federated providers, applies per-source soft timeout,
and reports per-engine status.
</done>
</task>

<task id="4" type="tdd">
<name>Update MCP search tool envelope</name>
<title>Update MCP search tool envelope</title>
<read_first>
- `backend/src/dotmd/mcp_server.py`
- `backend/tests/mcp/` (existing)
- `backend/src/dotmd/api/service.py`
</read_first>
<files>
- `backend/src/dotmd/mcp_server.py`
- `backend/tests/mcp/test_mcp_search_envelope.py`
</files>
<action>
Update the MCP `search` tool to return the new envelope (cycle-2 HIGH-2 +
HIGH-5 fixes — no SearchHit narrowing, calls `search_async` directly).

`backend/src/dotmd/mcp_server.py`:

- Confirm `SearchHit` was already removed in Plan 34-01 task 2 (cycle-2
  HIGH-2). If a `SearchHit` class still exists at this point, remove it
  and replace any usage with `SearchCandidate`.
- The MCP `search` tool returns `SearchResponse` directly (the same
  Pydantic model that `service.search_async` returns). FastMCP serializes
  it to JSON automatically:
  ```python
  @mcp.tool(name="search")
  async def search(query: str, top_k: int = 10) -> SearchResponse:
      """Search the personal markdown knowledgebase ...

      The response contains:
      - candidates: list[SearchCandidate] — full public contract,
        including descriptor_key, can_read, can_materialize,
        source_native_score, source_native_rank, engine_scores,
        provider_metadata.
      - source_status: list[SourceStatus] — per-engine status
        (`ok` / `skipped` / `error`) for each local and federated
        engine that participated in this query, plus persistent
        lifecycle init errors. Use it to understand why a query may
        have returned fewer results than expected.
      """
      return await service.search_async(query, top_k=top_k)  # cycle-2 HIGH-5: native async, no asyncio.to_thread bridge
  ```
- Do NOT define a `SearchEnvelope` BaseModel that narrows the public
  contract. Returning `SearchResponse` directly satisfies SEARCH-01's
  "single public type" intent (cycle-2 HIGH-2). If FastMCP's schema
  emission requires a typed-dict shim, the shim MUST round-trip equal to
  `SearchResponse` (lossless projection).
- Do NOT add `sources` or `exclude_sources` parameters (D-10).
- Do NOT call `asyncio.to_thread(service.search, ...)` from the MCP tool
  (cycle-2 HIGH-5 — the tool already runs inside FastMCP's event loop;
  use `search_async` directly).

`backend/tests/mcp/test_mcp_search_envelope.py`:

- Add an integration test that loads the MCP server, calls the `search`
  tool with `query="foo"` against a service whose lifecycle has a stub
  federated bundle, and asserts:
  - response shape is `{"candidates": [...], "source_status": [...]}`
    (the `SearchResponse` envelope; cycle-2 HIGH-2 — no `results` /
    `SearchHit` narrowing).
  - each item in `candidates` has the FULL `SearchCandidate` shape:
    `ref`, `namespace`, `descriptor_key`, `source_kind`, `retrieval_kind`,
    `title`, `snippet`, `fused_score`, `can_read`, `can_materialize`,
    plus optional `chunk_id`, `heading_path`, `matched_engines`,
    `source_native_score`, `source_native_rank`, `engine_scores`,
    `provider_metadata`. None of these public fields are stripped from
    the MCP response.
  - `source_status` contains entries for `semantic`, `keyword`,
    `graph_direct`, plus the stub federated engine name.
- Add `test_mcp_search_signature_does_not_include_source_filters` —
  asserts the tool's input schema does not include `sources` or
  `exclude_sources` parameters (defense against accidental D-10 violation).
- Add `test_mcp_search_does_not_use_asyncio_to_thread_bridge` (**cycle-2
  HIGH-5 fix**) — static-grep assertion. Run `rg -n
  'asyncio\.to_thread\(.*service\.search\b' backend/src/dotmd/mcp_server.py`
  and assert zero matches. The MCP tool MUST call `service.search_async`
  directly, not bridge through `asyncio.to_thread(service.search, ...)`.
- Add `test_mcp_response_round_trips_full_search_candidate_contract`
  (**cycle-2 HIGH-2 fix**) — construct a `SearchCandidate` with every
  optional field populated (including `descriptor_key`, `can_materialize`,
  `source_native_score`, `source_native_rank`, `engine_scores`,
  `provider_metadata`). Stub the service to return a `SearchResponse`
  containing this candidate. Call the MCP tool. Assert the JSON-serialized
  response includes EVERY public field. Re-parse the JSON into
  `SearchCandidate` and assert equality with the original (lossless
  round-trip).
</action>
<acceptance_criteria>
- `backend/src/dotmd/mcp_server.py` does NOT contain
  `class SearchHit(BaseModel)` or `class SearchEnvelope(BaseModel)` —
  cycle-2 HIGH-2 fix. (`rg -n 'class SearchHit\b|class SearchEnvelope\b'
  backend/src/dotmd/mcp_server.py` returns no matches.)
- `backend/src/dotmd/mcp_server.py` `search` tool returns `SearchResponse`
  (the same model `service.search_async` returns).
- `backend/src/dotmd/mcp_server.py` `search` tool calls
  `await service.search_async(query, top_k=top_k)` directly. (`rg -n
  'asyncio\.to_thread\(.*service\.search\b' backend/src/dotmd/mcp_server.py`
  returns zero matches — cycle-2 HIGH-5.)
- `backend/tests/mcp/test_mcp_search_envelope.py` contains the integration
  test, `test_mcp_search_signature_does_not_include_source_filters`,
  `test_mcp_search_does_not_use_asyncio_to_thread_bridge`, and
  `test_mcp_response_round_trips_full_search_candidate_contract`.
- `cd backend && uv run pytest tests/mcp/test_mcp_search_envelope.py -q` exits 0.
- `cd backend && uv run pyright src/dotmd/mcp_server.py tests/mcp/test_mcp_search_envelope.py` exits 0.
- `rg -n '"sources"' backend/src/dotmd/mcp_server.py` returns no matches in the `search` tool definition.
</acceptance_criteria>
<verify>
`cd backend && uv run pytest tests/mcp/test_mcp_search_envelope.py -q`
`cd backend && uv run pyright src/dotmd/mcp_server.py tests/mcp/test_mcp_search_envelope.py`
`rg -n 'sources\s*:.*Annotated' backend/src/dotmd/mcp_server.py`
`rg -n 'class SearchHit\b|class SearchEnvelope\b' backend/src/dotmd/mcp_server.py` (must return zero — cycle-2 HIGH-2 enforcement)
`rg -n 'asyncio\.to_thread\(.*service\.search\b' backend/src/dotmd/mcp_server.py` (must return zero — cycle-2 HIGH-5 enforcement)
</verify>
<done>
MCP `search` tool returns `SearchResponse` with full `SearchCandidate`
records and `source_status`; no source filter parameters present.
(cycle-3 LOW fix — was incorrectly written as `SearchEnvelope`.)
</done>
</task>
</tasks>

<verification>
- `cd backend && uv run pytest tests/search/test_federated.py tests/api/test_service_search.py tests/mcp/test_mcp_search_envelope.py tests/core/test_search_candidate.py tests/search/test_fusion.py -q`
- `cd backend && uv run pyright src/dotmd/core/models.py src/dotmd/core/config.py src/dotmd/search/fusion.py src/dotmd/search/federated.py src/dotmd/api/service.py src/dotmd/mcp_server.py src/dotmd/ingestion/source_provider.py src/dotmd/ingestion/source_lifecycle.py tests/core/test_search_candidate.py tests/search/test_fusion.py tests/search/test_federated.py tests/api/test_service_search.py tests/mcp/test_mcp_search_envelope.py`
- `rg -n 'FederatedSearchError' backend/src/dotmd/search backend/src/dotmd/api` returns no matches (fail-fast pattern explicitly rejected).
- `rg -n 'sources\s*:\s*Annotated' backend/src/dotmd/mcp_server.py` returns no matches in the `search` tool definition.
</verification>

<success_criteria>
- SEARCH-01 has a federated-aware service surface that emits one
  `SearchResponse` envelope, exposed identically at service and MCP
  surfaces (cycle-2 HIGH-2 — no narrowing).
- SEARCH-03 has rank-only RRF in which provider-native scores cannot
  outrank local hits via raw score.
- D-08, D-09, D-11, D-12 behaviors are pinned: always-on fan-out,
  configurable per-source timeout (federated only), soft-skip with reason
  attribution, no fail-fast.
- D-10 is preserved at the MCP surface (no source filter parameters).
- D-18 generic-enough check: adding a second federated provider in Plan 03
  requires NO Phase 34 contract or fan-out edits — only a new lifecycle
  bundle with `search_native`. (Plan 03 is the proof.)
- **D-OUTCOME-SPLIT** (cycle-2 HIGH-3): `LocalEngineOutcome` and
  `FederatedEngineOutcome` are distinct types; orchestrator branches by
  isinstance.
- **D-LOCAL-SEQUENTIAL** (cycle-2 HIGH-4): local engines run sequentially
  in one thread; only federated providers fan out in parallel. Test pins
  no concurrent local engine invocation.
- **D-ASYNC-CANONICAL** (cycle-2 HIGH-5): `search_async` is the canonical
  public async method; sync `search` raises `RuntimeError` from inside a
  running event loop. MCP and FastAPI call `search_async` directly.
- **D-LIFECYCLE-GRACEFUL** (cycle-2 HIGH-6): per-source lifecycle build
  failures are caught at service init and surfaced as persistent
  `SourceStatus(status="error")` entries; service init never crashes on
  one bad source.
- **D-LOOP-SAFE** (cycle-3 HIGH; cycle-4 MEDIUM timing fix): `search_async`
  never blocks the FastMCP/FastAPI event loop. The full local engine
  sequence runs in one worker thread on the dedicated single-worker
  executor via `loop.run_in_executor(self._local_executor,
  self._run_local_search_sequence, ...)`, composed with federated fan-out
  via `asyncio.gather`. Regression test
  `test_search_async_does_not_block_event_loop` (with `finally`-block
  capture of `interleave_count` at search completion — cycle-4 MEDIUM
  fix, not at gather completion) and
  `test_search_async_local_engines_share_one_worker_thread` pin both
  "loop is unblocked DURING the search call" and "all three local
  engines share the same worker thread". Overlap test
  `test_federated_fanout_overlaps_with_local_search_sequence` pins
  response time = `max(local_duration, federated_timeout)`, not
  additive (cycle-3 MEDIUM fold-in).
- **D-LOCAL-SERIALIZED** (cycle-4 HIGH): two concurrent `search_async()`
  calls cannot run two `_run_local_search_sequence` invocations
  simultaneously — the dedicated `self._local_executor` has
  `max_workers=1`, queueing concurrent submissions. Structural pin
  `test_local_executor_has_max_workers_one` asserts `_max_workers == 1`
  and `_thread_name_prefix == "dotmd-local-search"`. Behavioral pin
  `test_concurrent_search_async_calls_do_not_overlap_local_sequences`
  asserts two simultaneous searches either share the same worker thread
  (Invariant A — same-thread serialization, expected with
  `max_workers=1`) OR have disjoint `[enter, exit]` intervals (Invariant
  B — also passes if a future maintainer swaps in a different
  serialization mechanism). The single-worker executor was chosen over
  an `asyncio.Lock` for "invariant by construction" — any code path
  that submits to `self._local_executor` inherits the cross-request
  serialization guarantee, so accidental refactors that drop a lock
  acquire cannot regress this invariant.
</success_criteria>
