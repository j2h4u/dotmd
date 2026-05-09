"""Federated fan-out infrastructure and source-status tests.

Tests the federated search protocol, soft timeout behavior, source status
collection, and integration with local search engines. These tests establish
the contract for Plan 34 federated support.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from dotmd.core.models import SearchCandidate, SearchResponse, SourceStatus
from dotmd.search.federated import (
    LocalEngineOutcome,
    FederatedEngineOutcome,
    _run_local_engine,
    _run_federated_engine,
    fanout_federated,
    outcomes_to_source_status,
)
from tests.search.conftest import (
    StubFederatedProvider,
    make_federated_bundle,
    make_misconfigured_federated_factory,
)


# ============================================================================
# LocalEngineOutcome and FederatedEngineOutcome tests
# ============================================================================


class TestEngineOutcomes:
    """Tests for the split outcome shapes (cycle-2 HIGH-3)."""

    def test_engine_outcome_ok_carries_candidates_and_elapsed(self) -> None:
        """FederatedEngineOutcome carries candidates, not ranked_chunks."""
        candidates = [
            SearchCandidate(
                ref="stub:result:0",
                namespace="stub",
                descriptor_key="stub",
                source_kind="test",
                retrieval_kind="stub:fts",
                snippet="first",
                fused_score=1.0,
                can_read=False,
            ),
            SearchCandidate(
                ref="stub:result:1",
                namespace="stub",
                descriptor_key="stub",
                source_kind="test",
                retrieval_kind="stub:fts",
                snippet="second",
                fused_score=0.5,
                can_read=False,
            ),
        ]

        outcome = FederatedEngineOutcome(
            name="stub",
            status="ok",
            candidates=candidates,
            reason=None,
            elapsed_ms=42.0,
        )

        assert outcome.status == "ok"
        assert len(outcome.candidates) == 2
        assert outcome.elapsed_ms == 42.0
        assert not hasattr(outcome, "ranked_chunks")

    def test_engine_outcome_timeout_yields_skipped_with_reason_timeout(self) -> None:
        """Timeout results in skipped status."""
        outcome = FederatedEngineOutcome(
            name="stub",
            status="skipped",
            candidates=[],
            reason="timeout",
            elapsed_ms=100.0,
        )

        assert outcome.status == "skipped"
        assert outcome.reason == "timeout"
        assert outcome.candidates == []
        assert outcome.elapsed_ms < 1000

    def test_engine_outcome_exception_yields_error_with_reason_message(self) -> None:
        """Exception results in error status with message."""
        outcome = FederatedEngineOutcome(
            name="stub",
            status="error",
            candidates=[],
            reason="daemon down",
            elapsed_ms=10.0,
        )

        assert outcome.status == "error"
        assert outcome.reason is not None
        assert "daemon down" in outcome.reason
        assert outcome.candidates == []

    def test_local_engine_outcome_carries_ranked_chunks_not_candidates(self) -> None:
        """LocalEngineOutcome carries ranked_chunks, not candidates (cycle-2 HIGH-3)."""
        ranked = [("chunk_a", 1.0), ("chunk_b", 0.8)]
        outcome = LocalEngineOutcome(
            name="semantic",
            status="ok",
            ranked_chunks=ranked,
            reason=None,
            elapsed_ms=50.0,
        )

        assert outcome.status == "ok"
        assert outcome.ranked_chunks == ranked
        assert not hasattr(outcome, "candidates")
        assert outcome.elapsed_ms == 50.0

    def test_federated_engine_outcome_carries_candidates_not_ranked_chunks(self) -> None:
        """FederatedEngineOutcome carries candidates, not ranked_chunks (cycle-2 HIGH-3)."""
        candidates = [
            SearchCandidate(
                ref="stub:result:0",
                namespace="stub",
                descriptor_key="stub",
                source_kind="test",
                retrieval_kind="stub:fts",
                snippet="test",
                fused_score=1.0,
                can_read=False,
            ),
        ]
        outcome = FederatedEngineOutcome(
            name="stub:fts",
            status="ok",
            candidates=candidates,
            reason=None,
            elapsed_ms=30.0,
        )

        assert outcome.status == "ok"
        assert outcome.candidates == candidates
        assert not hasattr(outcome, "ranked_chunks")


# ============================================================================
# Runner tests for _run_local_engine and _run_federated_engine
# ============================================================================


class TestRunLocalEngine:
    """Tests for the sync local engine runner."""

    def test_run_local_engine_ok(self) -> None:
        """Successful local engine call returns ok outcome."""
        def _search() -> list[tuple[str, float]]:
            return [("chunk_a", 0.9), ("chunk_b", 0.7)]

        outcome = _run_local_engine("semantic", _search)

        assert outcome.name == "semantic"
        assert outcome.status == "ok"
        assert outcome.ranked_chunks == [("chunk_a", 0.9), ("chunk_b", 0.7)]
        assert outcome.reason is None
        assert outcome.elapsed_ms > 0

    def test_run_local_engine_error(self) -> None:
        """Exception in local engine returns error outcome."""
        def _search() -> list[tuple[str, float]]:
            raise RuntimeError("search failed")

        outcome = _run_local_engine("keyword", _search)

        assert outcome.name == "keyword"
        assert outcome.status == "error"
        assert outcome.ranked_chunks == []
        assert outcome.reason is not None
        assert "search failed" in outcome.reason


class TestRunFederatedEngine:
    """Tests for the async federated engine runner (cycle-2 HIGH-4)."""

    @pytest.mark.asyncio
    async def test_run_federated_engine_ok(self) -> None:
        """Successful federated call returns ok outcome."""
        provider = StubFederatedProvider(
            candidates=[
                SearchCandidate(
                    ref="stub:result:0",
                    namespace="stub",
                    descriptor_key="stub",
                    source_kind="test",
                    retrieval_kind="stub:fts",
                    snippet="test",
                    fused_score=1.0,
                    can_read=False,
                )
            ]
        )

        outcome = await _run_federated_engine(
            "stub:fts",
            lambda: provider.search_native("query", 10),
            timeout=5.0,
        )

        assert outcome.name == "stub:fts"
        assert outcome.status == "ok"
        assert len(outcome.candidates) == 1
        assert outcome.reason is None

    @pytest.mark.asyncio
    async def test_run_federated_engine_timeout(self) -> None:
        """Timeout yields skipped status (cycle-2 MEDIUM timeout-scope)."""
        provider = StubFederatedProvider(sleep_seconds=10.0)

        outcome = await _run_federated_engine(
            "stub:fts",
            lambda: provider.search_native("query", 10),
            timeout=0.1,
        )

        assert outcome.name == "stub:fts"
        assert outcome.status == "skipped"
        assert outcome.reason == "timeout"
        assert outcome.candidates == []

    @pytest.mark.asyncio
    async def test_run_federated_engine_exception(self) -> None:
        """Exception in provider returns error outcome."""
        provider = StubFederatedProvider(
            raises=RuntimeError("provider down")
        )

        outcome = await _run_federated_engine(
            "stub:fts",
            lambda: provider.search_native("query", 10),
            timeout=5.0,
        )

        assert outcome.name == "stub:fts"
        assert outcome.status == "error"
        assert outcome.reason is not None
        assert "provider down" in outcome.reason
        assert outcome.candidates == []


# ============================================================================
# Fan-out tests
# ============================================================================


class TestFanout:
    """Tests for federated fan-out behavior."""

    @pytest.mark.asyncio
    async def test_fanout_runs_in_parallel(self) -> None:
        """Multiple providers execute in parallel, not sequentially."""
        providers = {
            "stub1": StubFederatedProvider(sleep_seconds=1.0),
            "stub2": StubFederatedProvider(sleep_seconds=1.0),
            "stub3": StubFederatedProvider(sleep_seconds=1.0),
        }

        start = time.time()
        results = await fanout_federated(
            {
                name: (lambda p=p: p.search_native("query", 10))
                for name, p in providers.items()
            },
            timeout=5.0,
        )
        elapsed = time.time() - start

        # Parallel execution: 1s, not 3s
        assert elapsed < 1.5
        assert len(results) == 3
        assert all(r.status == "ok" for r in results)

    @pytest.mark.asyncio
    async def test_fanout_collects_source_status_for_every_engine_including_local(
        self,
    ) -> None:
        """Source status includes entries for every engine."""
        providers = {
            "stub1": StubFederatedProvider(),
            "stub2": StubFederatedProvider(raises=RuntimeError("down")),
        }

        results = await fanout_federated(
            {
                name: (lambda p=p: p.search_native("query", 10))
                for name, p in providers.items()
            },
            timeout=5.0,
        )

        assert len(results) == 2
        statuses = outcomes_to_source_status(results)
        assert len(statuses) == 2
        assert {s.name for s in statuses} == {"stub1", "stub2"}

    @pytest.mark.asyncio
    async def test_soft_timeout_does_not_block_response(self) -> None:
        """Fast local engine + slow federated within timeout window."""
        provider = StubFederatedProvider(sleep_seconds=0.5)

        start = time.time()
        outcome = await _run_federated_engine(
            "stub",
            lambda: provider.search_native("query", 10),
            timeout=2.0,
        )
        elapsed = time.time() - start

        assert outcome.status == "ok"
        assert elapsed < 1.0


# ============================================================================
# Source status tests
# ============================================================================


class TestSourceStatus:
    """Tests for source status reporting."""

    def test_source_error_soft_skip_does_not_break_query(self) -> None:
        """One failing source does not propagate error."""
        local_outcome = LocalEngineOutcome(
            name="semantic",
            status="ok",
            ranked_chunks=[("chunk_a", 0.9)],
            reason=None,
            elapsed_ms=50.0,
        )
        federated_outcome = FederatedEngineOutcome(
            name="stub:fts",
            status="error",
            candidates=[],
            reason="daemon down",
            elapsed_ms=10.0,
        )

        statuses = outcomes_to_source_status([local_outcome, federated_outcome])

        assert len(statuses) == 2
        assert statuses[1].name == "stub:fts"
        assert statuses[1].status == "error"

    def test_source_status_attributes_each_engine(self) -> None:
        """Every engine gets exactly one status entry."""
        outcomes = [
            LocalEngineOutcome(
                name="semantic",
                status="ok",
                ranked_chunks=[("a", 1.0)],
                reason=None,
                elapsed_ms=10.0,
            ),
            LocalEngineOutcome(
                name="keyword",
                status="ok",
                ranked_chunks=[],
                reason=None,
                elapsed_ms=5.0,
            ),
            FederatedEngineOutcome(
                name="stub:fts",
                status="ok",
                candidates=[],
                reason=None,
                elapsed_ms=20.0,
            ),
        ]

        statuses = outcomes_to_source_status(outcomes)

        assert len(statuses) == 3
        assert len({s.name for s in statuses}) == 3

    def test_outcomes_to_source_status_includes_candidate_count(self) -> None:
        """Candidate count is populated from outcome."""
        candidates = [
            SearchCandidate(
                ref="stub:0",
                namespace="stub",
                descriptor_key="stub",
                source_kind="test",
                retrieval_kind="stub:fts",
                snippet="test",
                fused_score=1.0,
                can_read=False,
            ),
            SearchCandidate(
                ref="stub:1",
                namespace="stub",
                descriptor_key="stub",
                source_kind="test",
                retrieval_kind="stub:fts",
                snippet="test",
                fused_score=0.9,
                can_read=False,
            ),
        ]
        outcome = FederatedEngineOutcome(
            name="stub:fts",
            status="ok",
            candidates=candidates,
            reason=None,
            elapsed_ms=30.0,
        )

        statuses = outcomes_to_source_status([outcome])

        assert statuses[0].candidate_count == 2


# ============================================================================
# Service integration tests (placeholders for Task 3)
# ============================================================================


class TestLocalEnginesNotConcurrent:
    """Tests for D-LOCAL-SEQUENTIAL (cycle-2 HIGH-4)."""

    @pytest.mark.skip(reason="Deferred to Task 3 - service integration")
    def test_local_engines_not_called_concurrently(self) -> None:
        """Local engines run sequentially, never concurrently."""
        pass


class TestAsyncSearchEventLoop:
    """Tests for D-LOOP-SAFE and D-LOCAL-SERIALIZED (cycle-3/4 HIGH)."""

    @pytest.mark.skip(reason="Deferred to Task 3 - service integration")
    def test_sync_search_in_running_loop_raises_runtime_error(self) -> None:
        """Sync search from inside event loop raises loudly."""
        pass

    @pytest.mark.skip(reason="Deferred to Task 3 - service integration")
    def test_async_search_in_running_loop_succeeds(self) -> None:
        """Async search from inside event loop works correctly."""
        pass

    @pytest.mark.skip(reason="Deferred to Task 3 - service integration")
    def test_search_async_does_not_block_event_loop(self) -> None:
        """Local search runs off-loop; event loop unblocked (cycle-3 HIGH)."""
        pass

    @pytest.mark.skip(reason="Deferred to Task 3 - service integration")
    def test_search_async_local_engines_share_one_worker_thread(self) -> None:
        """All three local engines run on the same worker thread."""
        pass

    @pytest.mark.skip(reason="Deferred to Task 3 - service integration")
    def test_federated_fanout_overlaps_with_local_search_sequence(self) -> None:
        """Federated and local proceed in parallel via asyncio.gather."""
        pass

    @pytest.mark.skip(reason="Deferred to Task 3 - service integration")
    def test_local_executor_has_max_workers_one(self) -> None:
        """Service._local_executor has max_workers=1 (cycle-4 HIGH structural pin)."""
        pass

    @pytest.mark.skip(reason="Deferred to Task 3 - service integration")
    def test_concurrent_search_async_calls_do_not_overlap_local_sequences(self) -> None:
        """Two concurrent search_async calls serialize their local sequences."""
        pass

    @pytest.mark.skip(reason="Deferred to Task 3 - service integration")
    def test_sqlite_connection_supports_cross_thread_access(self) -> None:
        """SQLite connection opened with check_same_thread=False."""
        pass


class TestLifecycleInitFailure:
    """Tests for D-LIFECYCLE-GRACEFUL (cycle-2 HIGH-6)."""

    @pytest.mark.skip(reason="Deferred to Task 3 - service integration")
    def test_misconfigured_federated_source_does_not_crash_service_init(self) -> None:
        """Service init survives per-source build failures."""
        pass

    @pytest.mark.skip(reason="Deferred to Task 3 - service integration")
    def test_misconfigured_federated_source_appears_as_error_status_in_search(self) -> None:
        """Build failure surfaces as persistent SourceStatus error entry."""
        pass


class TestFederatedTimeoutScope:
    """Tests for D-09 separate timeout scope (cycle-2 MEDIUM)."""

    @pytest.mark.skip(reason="Deferred to Task 3 - service integration")
    def test_federated_timeout_does_not_apply_to_local_engines(self) -> None:
        """Local engines have no soft timeout; federated timeout applies only to federated."""
        pass


class TestFederatedEngineScoresNone:
    """Tests for D-02 federated engine_scores (cycle-2 MEDIUM)."""

    @pytest.mark.skip(reason="Deferred to Task 3 - service integration")
    def test_federated_candidates_leave_engine_scores_none(self) -> None:
        """Federated candidates have engine_scores=None after fan-out."""
        pass
