"""Federated fan-out search infrastructure (Phase 34 Plan 02).

Provides protocols and outcome types for multi-source search orchestration.

Key architectural decisions:
- D-06: Per-engine weights remain; fusion is rank-only
- D-07: Federated candidates (chunk_id is None) skip reranking
- D-08: Always-on fan-out; lifecycle build failures → persistent SourceStatus
- D-09: Per-source soft timeout (3-5s) for federated only; local engines sequential
- D-12: No fail-fast; errors are soft-skips
- D-OUTCOME-SPLIT: LocalEngineOutcome vs FederatedEngineOutcome (never conflate)
- D-LOCAL-SEQUENTIAL: Local engines run sequentially on ONE worker thread
- D-LOCAL-SERIALIZED: Concurrent search_async() calls serialize on max_workers=1 executor
- D-LOOP-SAFE: search_async doesn't block event loop
- D-ASYNC-CANONICAL: search_async is canonical; sync search() raises if inside running loop
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from dotmd.core.models import SearchCandidate


class FederatedSearchProviderProtocol(ABC):
    """Protocol for federated search providers.

    Implemented by integrations (Telegram, Slack, etc.) to surface
    external search results into the local search response.

    Methods run in the federated executor context (threadpool or async).
    Errors are soft-skipped per D-12; they propagate to SourceStatus as
    error records but do not fail the overall search.
    """

    @abstractmethod
    async def search(
        self,
        query: str,
        top_k: int = 10,
    ) -> list[SearchCandidate]:
        """Search the external source and return ranked candidates.

        All candidates returned MUST have:
        - chunk_id=None (federated identifier)
        - namespace matching the source (e.g., "telegram", "slack")
        - descriptor_key identifying the source instance/account
        - can_read=True (federated sources are assumed readable)

        Parameters
        ----------
        query:
            Natural-language search query.
        top_k:
            Maximum number of results to return.

        Returns
        -------
        list[SearchCandidate]
            Ranked candidates from the source. Empty list if no results.
            Each candidate must have chunk_id=None and valid namespace.

        Raises
        ------
        Exception
            Any exception indicates provider failure. Per D-12, the error
            is caught and recorded in SourceStatus; the overall search
            continues. Errors are not re-raised.
        """
        ...


@dataclass(frozen=True)
class LocalEngineOutcome:
    """Outcome from a local search engine (semantic, FTS5, graph).

    Local outcomes ALWAYS have chunk_id in all candidates.
    These outcomes feed into reranking (D-07: federated skips reranking).
    """

    engine_name: str
    """Name of the local engine (e.g., "semantic", "fts5", "graph")."""

    candidates: list[SearchCandidate]
    """Candidates from this engine. ALL have chunk_id set."""

    elapsed_ms: float
    """Execution time in milliseconds."""


@dataclass(frozen=True)
class FederatedEngineOutcome:
    """Outcome from a federated search provider.

    Federated outcomes represent results from external sources (Telegram, Slack, etc.).
    All candidates have chunk_id=None (they are not materialized from local index).

    Errors are recorded but not re-raised (D-12: no fail-fast).
    """

    provider_name: str
    """Name of the provider (e.g., "telegram", "slack")."""

    candidates: list[SearchCandidate]
    """Pre-materialized candidates from the provider. ALL have chunk_id=None."""

    elapsed_ms: float
    """Execution time in milliseconds (includes soft timeout if error occurred)."""

    error: Exception | None = None
    """If non-None, provider failed. Per D-12, error is recorded but search continues."""


# Union type for outcome results
EngineOutcome = LocalEngineOutcome | FederatedEngineOutcome
"""Union of local and federated outcome types.

Decision D-OUTCOME-SPLIT: Keep outcomes separate throughout the search pipeline
to enforce that federated results never flow through reranking logic.
"""
