"""Federated fan-out search infrastructure (Phase 34 Plan 02).

Provides outcome types, runner functions, and orchestration for multi-source
search with local-sequential + federated-parallel execution.

Key architectural decisions:
- D-06: Per-engine weights remain; fusion is rank-only
- D-07: Federated candidates (chunk_id is None) skip reranking
- D-08: Optional explicit fan-out; lifecycle build failures → persistent SourceStatus
- D-09: Per-source soft timeout (3-5s) for federated only; local engines sequential
- D-12: No fail-fast; errors are soft-skips
- D-OUTCOME-SPLIT: LocalEngineOutcome vs FederatedEngineOutcome (cycle-2 HIGH-3)
- D-LOCAL-SEQUENTIAL: Local engines run sequentially on ONE worker thread
- D-LOCAL-SERIALIZED: Concurrent search_async() calls serialize on max_workers=1 executor
- D-LOOP-SAFE: search_async doesn't block event loop
- D-ASYNC-CANONICAL: search_async is canonical; sync search() raises if inside running loop
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

import httpx

from dotmd.core.models import SearchCandidate, SourceStatus

logger = logging.getLogger(__name__)


# ============================================================================
# Split Outcome Shapes (cycle-2 HIGH-3)
# ============================================================================


@dataclass(frozen=True)
class LocalEngineOutcome:
    """Outcome from a local search engine (semantic, FTS5, graph_direct).

    Local engines run SEQUENTIALLY on one worker thread and run to completion
    with no soft timeout (D-LOCAL-SEQUENTIAL, D-09).

    All candidates have chunk_id set (local-specific).
    """

    name: str
    """Name of the local engine (e.g., "semantic", "keyword", "graph_direct")."""

    status: Literal["ok", "skipped", "error"]
    """Outcome status: ok, skipped (not used for local in Phase 34), or error."""

    ranked_chunks: list[tuple[str, float]]
    """List of (chunk_id, score) tuples from this engine. Empty if status != ok."""

    reason: str | None
    """Brief reason if status is not ok. None if status is ok."""

    elapsed_ms: float
    """Execution time in milliseconds."""


@dataclass(frozen=True)
class FederatedEngineOutcome:
    """Outcome from a federated search provider (Telegram, Slack, etc.).

    Federated outcomes execute in parallel on the event loop via asyncio.gather.
    Each provider call has a soft per-source timeout (D-09).

    All candidates have chunk_id=None (federated-specific).
    Errors are recorded but not re-raised (D-12: no fail-fast).
    """

    name: str
    """Namespaced engine name (e.g., "tg:fts", "gmail:native")."""

    status: Literal["ok", "skipped", "error"]
    """Status: ok, skipped (timeout), or error (exception)."""

    candidates: list[SearchCandidate]
    """Pre-built candidates from the provider. Empty if status != ok."""

    reason: str | None
    """Brief reason if status is not ok (e.g., "timeout", "daemon down"). None if ok."""

    elapsed_ms: float
    """Execution time in milliseconds, including timeout wait if error occurred."""


# Type alias for dispatch in orchestrator
EngineOutcome = LocalEngineOutcome | FederatedEngineOutcome
"""Union of local and federated outcome types.

Decision D-OUTCOME-SPLIT (cycle-2 HIGH-3): Keep outcomes separate to enforce
that federated results never flow through reranking logic. Orchestrator stages
3-5 branch by isinstance(outcome, LocalEngineOutcome) vs isinstance(outcome, FederatedEngineOutcome).
"""


# ============================================================================
# Runner Functions
# ============================================================================


def _run_local_engine(
    name: str,
    fn: Callable[[], list[tuple[str, float]]],
) -> LocalEngineOutcome:
    """Run a local search engine synchronously.

    Local engines run SEQUENTIALLY in the caller's thread with no soft timeout.
    Exceptions are caught, logged, and returned as error outcomes (D-12: no fail-fast).

    This function is SYNCHRONOUS and intended to be wrapped by
    loop.run_in_executor(self._local_executor, _run_local_search_sequence, ...)
    to execute off the event loop while preserving D-LOCAL-SEQUENTIAL
    (all three engines on the same worker thread) and D-LOCAL-SERIALIZED
    (max_workers=1 executor serializes across concurrent search_async calls).

    Parameters
    ----------
    name:
        Engine name (e.g., "semantic", "keyword", "graph_direct").
    fn:
        Sync callable returning list of (chunk_id, score) tuples.

    Returns
    -------
    LocalEngineOutcome
        With status ok/error and elapsed_ms recorded.
    """
    start = time.time()
    try:
        ranked_chunks = fn()
        return LocalEngineOutcome(
            name=name,
            status="ok",
            ranked_chunks=ranked_chunks,
            reason=None,
            elapsed_ms=(time.time() - start) * 1000,
        )
    except (httpx.HTTPError, OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
        logger.warning(
            "Local engine %r failed: %s",
            name,
            exc,
            exc_info=True,
        )
        return LocalEngineOutcome(
            name=name,
            status="error",
            ranked_chunks=[],
            reason=str(exc),
            elapsed_ms=(time.time() - start) * 1000,
        )


async def _run_federated_engine(
    name: str,
    fn: Callable[[], list[SearchCandidate]],
    timeout: float,
) -> FederatedEngineOutcome:
    """Run a federated provider call with soft timeout.

    Wraps the sync provider call with asyncio.to_thread (runs in thread pool),
    then asyncio.wait_for (applies soft timeout). Per D-09, the timeout applies
    ONLY to federated providers, not to local engines.

    Timeout behavior (cycle-2 MEDIUM limitation):
    - asyncio.wait_for(asyncio.to_thread(...)) does NOT cancel the underlying
      thread on timeout. The thread continues to completion; the orchestrator
      ignores the late result. Logs may show "late completion after timeout".
      This is an accepted Phase 34 limitation; revisit only if operational pain.

    Errors (any exception, including TimeoutError) are caught, logged, and
    returned as error/skipped outcomes (D-12: no fail-fast).

    Parameters
    ----------
    name:
        Namespaced engine name (e.g., "tg:fts", "gmail:native").
    fn:
        Sync callable returning list of SearchCandidate.
    timeout:
        Per-source timeout in seconds (from config, e.g., 3.0-5.0 per D-09).

    Returns
    -------
    FederatedEngineOutcome
        With status ok/skipped (timeout)/error and elapsed_ms recorded.
    """
    start = time.time()
    try:
        coro = asyncio.to_thread(fn)
        candidates = await asyncio.wait_for(coro, timeout=timeout)
        return FederatedEngineOutcome(
            name=name,
            status="ok",
            candidates=candidates,
            reason=None,
            elapsed_ms=(time.time() - start) * 1000,
        )
    except TimeoutError:
        logger.debug(
            "Federated engine %r timed out after %.1f seconds",
            name,
            timeout,
        )
        return FederatedEngineOutcome(
            name=name,
            status="skipped",
            candidates=[],
            reason="timeout",
            elapsed_ms=(time.time() - start) * 1000,
        )
    except (httpx.HTTPError, OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
        logger.warning(
            "Federated engine %r failed: %s",
            name,
            exc,
            exc_info=True,
        )
        return FederatedEngineOutcome(
            name=name,
            status="error",
            candidates=[],
            reason=str(exc),
            elapsed_ms=(time.time() - start) * 1000,
        )


# ============================================================================
# Fan-out Orchestration
# ============================================================================


async def fanout_federated(
    engine_calls: dict[str, Callable[[], list[SearchCandidate]]],
    timeout: float,
) -> list[FederatedEngineOutcome]:
    """Run all federated providers in parallel with per-source timeout.

    Uses asyncio.gather to run all providers concurrently on the event loop
    (not blocking, unlike local engines which run on a worker thread).

    Returns outcomes in input dict iteration order (Python 3.12+ guarantees).

    Parameters
    ----------
    engine_calls:
        Dict mapping namespaced engine names to callables (e.g.,
        {"tg:fts": lambda: tg_provider.search_native(query, 10), ...}).
    timeout:
        Per-source timeout in seconds (from config).

    Returns
    -------
    list[FederatedEngineOutcome]
        One outcome per engine, in dict iteration order.
    """
    return await asyncio.gather(
        *[_run_federated_engine(name, fn, timeout) for name, fn in engine_calls.items()]
    )


# ============================================================================
# Status Reporting
# ============================================================================


def outcomes_to_source_status(
    outcomes: Sequence[EngineOutcome],
) -> list[SourceStatus]:
    """Convert engine outcomes to source status reports.

    One SourceStatus per outcome. Count comes from ranked_chunks length for
    local engines, candidates length for federated engines.

    Parameters
    ----------
    outcomes:
        Sequence of LocalEngineOutcome and/or FederatedEngineOutcome.

    Returns
    -------
    list[SourceStatus]
        Status reports for each engine, preserving input order.
    """
    statuses: list[SourceStatus] = []
    for outcome in outcomes:
        if isinstance(outcome, LocalEngineOutcome):
            count = len(outcome.ranked_chunks)
        else:  # FederatedEngineOutcome
            count = len(outcome.candidates)

        statuses.append(
            SourceStatus(
                name=outcome.name,
                status=outcome.status,
                reason=outcome.reason,
                candidate_count=count,
                elapsed_ms=outcome.elapsed_ms,
            )
        )
    return statuses
