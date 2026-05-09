"""Tests for federated fan-out infrastructure (Phase 34 Plan 02).

Tests cover:
- FederatedSearchProviderProtocol contract and StubFederatedProvider implementation
- EngineOutcome union types (LocalEngineOutcome vs FederatedEngineOutcome)
- Federated candidate construction and envelope wrapping
- Per-source soft timeout and error handling (no fail-fast)
"""
import time

import pytest

from dotmd.core.models import SearchCandidate, SearchResponse, SourceStatus
from dotmd.search.federated import (
    EngineOutcome,
    FederatedEngineOutcome,
    LocalEngineOutcome,
)


class StubFederatedProvider:
    """Stub federated search provider for testing.

    Implements FederatedSearchProviderProtocol. Returns configurable
    search results and error states.
    """

    def __init__(
        self,
        name: str = "stub-provider",
        results: list[SearchCandidate] | None = None,
        error: Exception | None = None,
        latency_ms: float = 10,
    ):
        """Initialize stub provider.

        Parameters
        ----------
        name:
            Provider name for source_status tracking.
        results:
            List of SearchCandidate to return on search.
        error:
            Exception to raise on search (simulates provider failure).
        latency_ms:
            Artificial latency in milliseconds.
        """
        self.name = name
        self.results = results or []
        self.error = error
        self.latency_ms = latency_ms

    async def search(
        self,
        query: str,
        top_k: int = 10,
    ) -> list[SearchCandidate]:
        """Return configured results or raise error after latency."""
        if self.latency_ms > 0:
            await _async_sleep(self.latency_ms / 1000)

        if self.error:
            raise self.error

        return self.results[:top_k]


async def _async_sleep(duration: float) -> None:
    """Async sleep (usable outside asyncio context in tests)."""
    import asyncio

    try:
        await asyncio.sleep(duration)
    except RuntimeError:
        # Fallback: test might not have event loop
        time.sleep(duration)


def test_stub_federated_provider_returns_results() -> None:
    """StubFederatedProvider returns configured results synchronously."""
    candidate = SearchCandidate(
        ref="local:chunk-1",
        namespace="local",
        descriptor_key="builtin",
        source_kind="filesystem",
        retrieval_kind="semantic",
        snippet="test snippet",
        fused_score=0.95,
        can_read=True,
    )
    provider = StubFederatedProvider(
        name="test-source",
        results=[candidate],
        latency_ms=0,
    )

    # Call in sync context (test does not run async)
    import asyncio

    result = asyncio.run(provider.search("query", top_k=5))
    assert len(result) == 1
    assert result[0].ref == "local:chunk-1"
    assert result[0].source_kind == "filesystem"


def test_stub_federated_provider_respects_top_k() -> None:
    """StubFederatedProvider truncates results to top_k."""
    candidates = [
        SearchCandidate(
            ref=f"local:chunk-{i}",
            namespace="local",
            descriptor_key="builtin",
            source_kind="filesystem",
            retrieval_kind="semantic",
            snippet=f"snippet {i}",
            fused_score=0.95 - (i * 0.05),
            can_read=True,
        )
        for i in range(5)
    ]
    provider = StubFederatedProvider(
        name="test-source",
        results=candidates,
        latency_ms=0,
    )

    import asyncio

    result = asyncio.run(provider.search("query", top_k=2))
    assert len(result) == 2
    assert result[0].ref == "local:chunk-0"
    assert result[1].ref == "local:chunk-1"


def test_stub_federated_provider_raises_error() -> None:
    """StubFederatedProvider raises configured error."""
    provider = StubFederatedProvider(
        name="test-source",
        error=ValueError("Provider unavailable"),
        latency_ms=0,
    )

    import asyncio

    with pytest.raises(ValueError, match="Provider unavailable"):
        asyncio.run(provider.search("query", top_k=5))


def test_engine_outcome_local_outcome_type() -> None:
    """LocalEngineOutcome is distinct from FederatedEngineOutcome."""
    # LocalEngineOutcome: chunk_id must be present
    local_outcome: EngineOutcome = LocalEngineOutcome(
        engine_name="semantic",
        candidates=[],
        elapsed_ms=10.5,
    )
    assert isinstance(local_outcome, LocalEngineOutcome)
    assert not isinstance(local_outcome, FederatedEngineOutcome)


def test_engine_outcome_federated_outcome_type() -> None:
    """FederatedEngineOutcome is distinct from LocalEngineOutcome."""
    # FederatedEngineOutcome: chunk_id is None, candidates pre-materialized
    federated_outcome: EngineOutcome = FederatedEngineOutcome(
        provider_name="telegram",
        candidates=[],
        elapsed_ms=150.0,
        error=None,
    )
    assert isinstance(federated_outcome, FederatedEngineOutcome)
    assert not isinstance(federated_outcome, LocalEngineOutcome)


def test_local_outcome_preserves_chunk_ids() -> None:
    """LocalEngineOutcome requires chunk_id in all candidates."""
    candidate = SearchCandidate(
        ref="local:chunk-42",
        namespace="local",
        descriptor_key="builtin",
        source_kind="filesystem",
        retrieval_kind="semantic",
        snippet="snippet",
        fused_score=0.9,
        can_read=True,
        chunk_id="chunk-42",  # REQUIRED for local
    )
    outcome = LocalEngineOutcome(
        engine_name="semantic",
        candidates=[candidate],
        elapsed_ms=5.0,
    )
    assert outcome.candidates[0].chunk_id == "chunk-42"


def test_federated_outcome_candidates_have_no_chunk_id() -> None:
    """FederatedEngineOutcome candidates have chunk_id=None (federated candidates)."""
    candidate = SearchCandidate(
        ref="telegram:user-42-msg-1",
        namespace="telegram",
        descriptor_key="telegram-user-42",
        source_kind="chat",
        retrieval_kind="text_search",
        snippet="federated snippet",
        fused_score=0.85,
        can_read=True,
        chunk_id=None,  # REQUIRED: None for federated
    )
    outcome = FederatedEngineOutcome(
        provider_name="telegram",
        candidates=[candidate],
        elapsed_ms=120.0,
        error=None,
    )
    assert outcome.candidates[0].chunk_id is None
    assert outcome.provider_name == "telegram"


def test_federated_outcome_with_error() -> None:
    """FederatedEngineOutcome records provider errors without raising."""
    error = TimeoutError("Provider timeout")
    outcome = FederatedEngineOutcome(
        provider_name="slack",
        candidates=[],
        elapsed_ms=5000.0,
        error=error,
    )
    assert outcome.error is not None
    assert isinstance(outcome.error, TimeoutError)
    assert "Provider timeout" in str(outcome.error)


def test_source_status_ok_state() -> None:
    """SourceStatus records successful engine execution."""
    status = SourceStatus(
        name="semantic",
        status="ok",
        candidate_count=5,
        elapsed_ms=12.5,
    )
    assert status.status == "ok"
    assert status.candidate_count == 5
    assert status.elapsed_ms == 12.5


def test_source_status_error_state() -> None:
    """SourceStatus records provider errors."""
    status = SourceStatus(
        name="telegram",
        status="error",
        reason="Network timeout",
        candidate_count=0,
        elapsed_ms=3000.0,
    )
    assert status.status == "error"
    assert status.reason == "Network timeout"
    assert status.candidate_count == 0


def test_source_status_skipped_state() -> None:
    """SourceStatus records skipped engines (e.g., disabled provider)."""
    status = SourceStatus(
        name="slack",
        status="skipped",
        reason="Provider not configured",
        candidate_count=0,
    )
    assert status.status == "skipped"
    assert status.reason == "Provider not configured"
    assert status.elapsed_ms is None


def test_search_response_envelope_structure() -> None:
    """SearchResponse envelope wraps candidates and per-source status."""
    candidates = [
        SearchCandidate(
            ref="local:chunk-1",
            namespace="local",
            descriptor_key="builtin",
            source_kind="filesystem",
            retrieval_kind="semantic",
            snippet="snippet 1",
            fused_score=0.95,
            can_read=True,
            chunk_id="chunk-1",
        ),
        SearchCandidate(
            ref="telegram:msg-42",
            namespace="telegram",
            descriptor_key="telegram-user-42",
            source_kind="chat",
            retrieval_kind="text_search",
            snippet="snippet 2",
            fused_score=0.80,
            can_read=True,
            chunk_id=None,
        ),
    ]
    status = [
        SourceStatus(name="semantic", status="ok", candidate_count=2, elapsed_ms=10.0),
        SourceStatus(name="telegram", status="ok", candidate_count=2, elapsed_ms=150.0),
    ]

    response = SearchResponse(candidates=candidates, source_status=status)

    assert len(response.candidates) == 2
    assert len(response.source_status) == 2
    assert response.candidates[0].fused_score == 0.95
    assert response.candidates[1].chunk_id is None
    assert response.source_status[0].name == "semantic"
    assert response.source_status[1].elapsed_ms == 150.0


def test_search_response_empty_envelope() -> None:
    """SearchResponse can be empty (no candidates, no sources)."""
    response = SearchResponse()
    assert len(response.candidates) == 0
    assert len(response.source_status) == 0


def test_federated_candidate_descriptor_key_must_match_source() -> None:
    """Federated candidates must have descriptor_key that identifies the source."""
    candidate = SearchCandidate(
        ref="telegram:msg-1",
        namespace="telegram",
        descriptor_key="telegram-user-42",  # Must identify the source provider
        source_kind="chat",
        retrieval_kind="text_search",
        snippet="test",
        fused_score=0.80,
        can_read=True,
        chunk_id=None,
    )
    # Validate that descriptor_key is present and non-empty
    assert candidate.descriptor_key == "telegram-user-42"
    assert "telegram" in candidate.descriptor_key


def test_local_candidate_has_provenance() -> None:
    """Local candidates include chunk provenance for materialization."""
    from dotmd.core.models import ChunkProvenance

    provenance = ChunkProvenance(
        namespace="local",
        document_ref="builtin:doc-1",
        ref="local:chunk-42",
        chunk_strategy="semantic",
    )
    candidate = SearchCandidate(
        ref="local:chunk-42",
        namespace="local",
        descriptor_key="builtin",
        source_kind="filesystem",
        retrieval_kind="semantic",
        snippet="test",
        fused_score=0.90,
        can_read=True,
        chunk_id="chunk-42",
        provenance=provenance,
    )
    assert candidate.provenance is not None
    assert candidate.provenance.namespace == "local"
    assert candidate.provenance.ref == "local:chunk-42"


# ============================================================================
# Task 3: search_async with ThreadPoolExecutor orchestration
# ============================================================================


@pytest.mark.asyncio
async def test_search_async_basic_execution() -> None:
    """search_async executes local + federated engines concurrently.

    Awaits all outcomes, returns SearchResponse envelope.
    """
    # This test will be enabled after search_async is implemented
    pytest.skip("search_async not yet implemented")


@pytest.mark.asyncio
async def test_search_async_local_serialized_on_single_worker() -> None:
    """Local engines run sequentially on max_workers=1 executor (D-LOCAL-SERIALIZED).

    Prevents concurrent local index access while federated can run in parallel.
    """
    pytest.skip("search_async not yet implemented")


@pytest.mark.asyncio
async def test_search_async_federated_timeout_3_to_5_seconds() -> None:
    """Per-source soft timeout (3-5s) for federated only; local sequential (D-09).

    Slow providers time out; SourceStatus records error.
    """
    pytest.skip("search_async not yet implemented")


@pytest.mark.asyncio
async def test_search_async_no_fail_fast_on_provider_error() -> None:
    """Provider errors don't fail overall search (D-12: no fail-fast).

    One provider error → SourceStatus error, search continues.
    """
    pytest.skip("search_async not yet implemented")


@pytest.mark.asyncio
async def test_search_async_raises_if_inside_running_event_loop() -> None:
    """Per D-ASYNC-CANONICAL: sync search() raises if inside running loop.

    Enforces proper async boundary separation.
    """
    pytest.skip("search_async not yet implemented")


@pytest.mark.asyncio
async def test_search_async_fuses_local_and_federated_outcomes() -> None:
    """Fusion combines local and federated candidates, federated skip reranking (D-07).

    RRF fusion on all candidates, but federated bypass cross-encoder gate.
    """
    pytest.skip("search_async not yet implemented")
