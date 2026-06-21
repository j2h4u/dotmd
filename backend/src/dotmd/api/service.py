"""UI-agnostic service facade for dotMD.

Provides a high-level API for indexing and searching that hides all
storage, extraction, and fusion details from calling code.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, NotRequired, Protocol, TypedDict, cast

from dotmd.core.config import Settings, load_settings
from dotmd.core.models import (
    ChunkProvenance,
    IndexStats,
    SearchCandidate,
    SearchMode,
    SearchResponse,
    SourceDocument,
    SourceStatus,
    SourceUnit,
)
from dotmd.ingestion.pipeline import IndexingPipeline
from dotmd.ingestion.reader import parse_frontmatter, read_file
from dotmd.ingestion.source_lifecycle import SourceLifecycleConfigError, SourceRuntimeFactory
from dotmd.ingestion.source_provider import ApplicationSourceProviderProtocol
from dotmd.ingestion.telegram_provider import (
    is_low_signal_telegram_text as _is_low_signal_telegram_text,
)
from dotmd.ingestion.trickle import TrickleIndexer
from dotmd.search.base import SearchEngineProtocol
from dotmd.search.fusion import build_candidates, fuse_results
from dotmd.search.graph_direct import GraphDirectEngine
from dotmd.search.graph_search import GraphSearchEngine
from dotmd.search.query import QueryExpander
from dotmd.search.reranker import RerankerFactory
from dotmd.search.semantic import SemanticSearchEngine
from dotmd.storage.base import MetadataStoreProtocol

logger = logging.getLogger(__name__)

ACTIVE_FILTER_OVERFETCH_FACTOR = 5
TELEGRAM_REF_PREFIX = "telegram:"


def _write_service_init_progress(step: str, status: str, error: str | None = None) -> None:
    progress_path = os.environ.get("DOTMD_INIT_PROGRESS_PATH", "").strip()
    if not progress_path:
        return
    payload = {
        "schema_version": "dotmd-init-progress-v1",
        "step": step,
        "status": status,
        "error": error,
        "updated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    path = Path(progress_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _search_mode_log_label(mode: SearchMode | str) -> str:
    """Return a bounded label for search mode logging."""
    try:
        return SearchMode(mode).value
    except ValueError:
        return "invalid"


class TelegramReadPath(Enum):
    """Routing decision for Telegram message read operations."""

    LOCAL_ACTIVE = "local_active"  # Local entry with ACTIVE binding
    LOCAL_INACTIVE = "local_inactive"  # Local entry with INACTIVE binding
    FEDERATED_ONLY = "federated_only"  # No local entry, use provider


class ReadPayload(TypedDict):
    ref: str
    total_chunks: int
    frontmatter: dict[str, Any]
    chunks: list[dict[str, Any]]  # each: {index: int, heading_hierarchy: list[str], text: str}
    document_ref: NotRequired[str]
    target_unit_ref: NotRequired[str]
    units: NotRequired[list[dict[str, Any]]]
    metadata: NotRequired[dict[str, Any]]


class DrillPayload(TypedDict):
    ref: str
    title: str
    source_uri: str
    document_type: str
    parser_name: str
    frontmatter: dict[str, Any]
    total_chunks: int
    document_ref: NotRequired[str]
    target_unit_ref: NotRequired[str]
    metadata: NotRequired[dict[str, Any]]
    target_metadata: NotRequired[dict[str, Any]]


class BindingDiagnostics(TypedDict):
    active: int
    inactive: int
    retained: int
    reused: int


class RerankCandidatePool(TypedDict):
    search_query: str
    original_query: str
    # Fused candidates after graph enrichment has appended candidates.
    fused: list[tuple[str, float]]
    engine_results: dict[str, list[tuple[str, float]]]
    semantic_hits: list[tuple[str, float]]
    keyword_hits: list[tuple[str, float]]
    graph_direct_hits: list[tuple[str, float]]
    pool_size: int


class RerankerRunComparison(TypedDict):
    name: str
    model_name: str
    elapsed_ms: float
    elapsed: str
    load_ms: float
    load: str
    rerank_ms: float
    rerank: str
    returned_count: int
    top_chunk_ids: list[str]
    scores: list[float]
    error: str | None


class RerankerComparison(TypedDict):
    query: str
    search_query: str
    shared_pool_size: int
    candidate_pool_chunk_ids: list[str]
    rerankers: list[RerankerRunComparison]
    overlap_reference: str | None
    overlap: dict[str, int]


class GraphEnrichmentEngineProtocol(Protocol):
    """Protocol for seed-based graph enrichment engines."""

    def search(
        self,
        query: str,
        top_k: int = 10,
        seed_chunk_ids: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Search graph neighbors for the supplied seed chunk ids."""
        ...


class _DisabledGraphEnrichmentEngine:
    """Explicitly disable seed-based graph expansion for backends without it."""

    def search(
        self,
        query: str,
        top_k: int = 10,
        seed_chunk_ids: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        return []


def _parse_telegram_message_ref(ref: str) -> tuple[str, str]:
    """Parse a public Telegram message ref into document and unit refs."""
    if not ref.startswith(TELEGRAM_REF_PREFIX):
        raise ValueError(f"Unknown source ref: {ref}")
    body = ref.removeprefix(TELEGRAM_REF_PREFIX)
    document_ref, separator, message_id_text = body.rpartition(":message:")
    if separator == "" or not document_ref.startswith("dialog:"):
        raise ValueError(f"Unknown source ref: {ref}")
    dialog_id_text = document_ref.removeprefix("dialog:")
    try:
        int(dialog_id_text)
        int(message_id_text)
    except ValueError:
        raise ValueError(f"Unknown source ref: {ref}") from None
    return document_ref, f"{document_ref}:message:{message_id_text}"


def _is_telegram_message_ref(ref: str) -> bool:
    """Return whether *ref* uses the Telegram message-ref shape."""
    return ref.startswith("telegram:dialog:") and ":message:" in ref


def format_elapsed_ms(elapsed_ms: float) -> str:
    """Format elapsed milliseconds for human-facing diagnostics."""
    if elapsed_ms < 1000.0:
        return f"{round(elapsed_ms):.0f}ms"

    total_seconds = max(1, round(elapsed_ms / 1000.0))
    seconds = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60

    if hours:
        return f"{hours}h{minutes:02d}m{seconds:02d}s"
    if minutes:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"


def _is_low_signal_federated_candidate(candidate: SearchCandidate) -> bool:
    """Return True if a federated candidate should be excluded from quota slots.

    Only applies the text-quality filter to Telegram candidates, where the
    low-signal heuristic is meaningful and proven in the trickle ingestion
    pipeline. Non-Telegram federated candidates have different snippet
    semantics and are passed through unconditionally.
    """
    is_telegram = candidate.namespace == "telegram" or (candidate.retrieval_kind or "").startswith(
        "tg:"
    )
    if is_telegram:
        return _is_low_signal_telegram_text(candidate.snippet or "")
    return False


def _merge_with_federated_quota(
    local_candidates: list[SearchCandidate],
    fed_candidates: list[SearchCandidate],
    top_k: int,
    fed_quota: int,
) -> list[SearchCandidate]:
    """Merge local and federated candidates using reserved slot quota.

    Score-based merge is impossible here: local candidates use cosine similarity
    (0.52-0.96), but federated providers such as mcp-telegram return no score
    field — fused_score is always 0.0. A unified sort would drop every federated
    result. Fabricating scores (e.g. 1/(1+rank)) would silently mislead
    downstream consumers and rerankers.

    Quota is the honest alternative: reserve fed_slots positions for federated
    results based on their daemon-returned ranking (which we trust within a
    source), fill the rest with the best local results.

    Adaptive quota — fed_slots = min(fed_quota, len(filtered_fed)) — handles
    three cases uniformly:
    - Daemon down / no results: fed_slots=0, all top_k go to local.
    - Sparse fed results: fed_slots shrinks, local gets the freed positions.
    - Normal operation: fed_slots=fed_quota, standard split.

    The _is_low_signal_federated_candidate pre-filter removes very short or
    emoji-only Telegram messages that FTS scored well by keyword but carry no
    semantic content. Non-Telegram sources (e.g., Gmail) are passed through
    unconditionally because their snippet quality semantics differ.
    """
    filtered_fed = [c for c in fed_candidates if not _is_low_signal_federated_candidate(c)]
    fed_slots = min(fed_quota, len(filtered_fed))
    local_slots = top_k - fed_slots

    top_local = sorted(local_candidates, key=lambda c: c.fused_score, reverse=True)[:local_slots]
    top_fed = filtered_fed[:fed_slots]  # daemon ranking is preserved as-is

    return top_local + top_fed


class DotMDService:
    """High-level service facade for indexing and searching markdown files.

    All storage backends, search engines, and extraction components are
    created internally based on the provided :class:`Settings`.

    Parameters
    ----------
    settings:
        Application configuration.  When ``None`` a default
        :class:`Settings` instance is created.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or load_settings()

        # Indexing pipeline (also creates storage backends and extractors).
        _write_service_init_progress("service:pipeline", "running")
        self._pipeline = IndexingPipeline(self._settings)
        _write_service_init_progress("service:pipeline", "applied")

        # Search engines -- reuse stores and shared connection from pipeline.
        self._surreal_connection: Any | None = None
        self._surreal_metadata_store: MetadataStoreProtocol | None = None
        self._uses_surreal_search_backend = (
            self._settings.surreal_retrieval_database is not None
            and self._settings.surreal_retrieval_embedding_dimension is not None
        )
        _write_service_init_progress("service:keyword_graph_engines", "running")
        if self._uses_surreal_search_backend:
            self._configure_surreal_search_backend()
        else:
            _write_service_init_progress("service:semantic_engine", "running")
            self._semantic_engine = SemanticSearchEngine(
                self._pipeline.vector_store,
                self._settings.embedding_model,
                score_floor=self._settings.semantic_score_floor,
                embedding_url=self._settings.embedding_url,
                tei_batch_size=self._settings.tei_batch_size,
                use_prefix=self._settings.needs_embedding_prefix,
                query_instruction=self._settings.query_instruction,
            )
            _write_service_init_progress("service:semantic_engine", "applied")
            self._keyword_engine = self._pipeline.keyword_engine
            self._graph_direct_engine = GraphDirectEngine(
                self._pipeline.graph_store,
            )
            self._graph_engine = GraphSearchEngine(
                self._pipeline.graph_store,
                cast(MetadataStoreProtocol, self._pipeline.metadata_store),
            )
        _write_service_init_progress("service:keyword_graph_engines", "applied")

        # Load acronym dictionary if available
        _write_service_init_progress("service:acronyms", "running")
        acronym_dict = self._load_acronyms()
        _write_service_init_progress("service:acronyms", "applied")

        # Query expansion and reranking.
        _write_service_init_progress("service:query_reranker", "running")
        self._query_expander = QueryExpander(
            acronym_dict=acronym_dict,
        )
        self._reranker_factory = RerankerFactory(self._settings)
        _write_service_init_progress("service:query_reranker", "applied")

        # Background trickle indexer
        _write_service_init_progress("service:trickle_sources", "running")
        self._trickle_indexer = TrickleIndexer(self._settings, self._pipeline)
        self._source_provenance_ready_strategies: set[str] = set()
        self._source_runtime_factory: SourceRuntimeFactory = self._pipeline.source_runtime_factory
        self._telegram_provider = self._build_telegram_provider()
        _write_service_init_progress("service:trickle_sources", "applied")

        # Federated fan-out infrastructure (cycle-2 HIGH-6, cycle-4 HIGH)
        # Build lifecycle bundles once at init; per-source failures are recorded
        # and surfaced as persistent SourceStatus entries (D-08).
        _write_service_init_progress("service:federated_bundles", "running")
        self._lifecycle_bundles: dict[str, Any] = {}
        self._lifecycle_init_errors: dict[str, str] = {}
        self._build_federated_bundles()
        _write_service_init_progress("service:federated_bundles", "applied")

        # Dedicated single-worker executor for local search sequence (cycle-4 HIGH).
        # Cross-request mutual exclusion: max_workers=1 forces concurrent
        # search_async() calls to queue instead of running local sequences
        # concurrently on different threads (D-LOCAL-SERIALIZED invariant by
        # construction). This preserves single-thread SQLite/metadata/graph access.
        self._local_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="dotmd-local-search",
        )
        _write_service_init_progress("service:complete", "applied")

    def _build_telegram_provider(self) -> ApplicationSourceProviderProtocol | None:
        """Build the optional Telegram provider from the source lifecycle."""
        bundle = self._source_runtime_factory.build_if_configured("telegram")
        if bundle is None:
            return None
        if bundle.provider is None:
            raise RuntimeError("telegram lifecycle runtime has no provider")
        return bundle.provider

    def _build_federated_bundles(self) -> None:
        """Build federated provider bundles, recording per-source failures (D-08).

        Lifecycle build failures are caught and recorded in
        _lifecycle_init_errors; service init never crashes. Each failed
        source is surfaced as a persistent SourceStatus(status="error")
        entry in every subsequent search response.
        """
        from dotmd.ingestion.source_lifecycle import SourceRuntimeBundle

        # Build all registered source descriptors
        for descriptor in self._source_runtime_factory._registry.list():
            namespace = descriptor.namespace
            try:
                bundle = self._source_runtime_factory.build_if_configured(namespace)
            except (SourceLifecycleConfigError, OSError, RuntimeError, ValueError) as exc:
                logger.warning(
                    "Lifecycle build failed for source %r: %s",
                    namespace,
                    exc,
                    exc_info=True,
                )
                self._lifecycle_init_errors[namespace] = str(exc)
                continue

            if bundle is None:
                continue

            if isinstance(bundle, SourceRuntimeBundle) and bundle.supports_federated_search:
                self._lifecycle_bundles[namespace] = bundle

    def _configure_surreal_search_backend(self) -> None:
        """Replace local retrieval engines with standalone SurrealDB engines."""
        from dotmd.search.surreal_native import build_surreal_native_engine_overrides
        from dotmd.storage.surreal import (
            SurrealConnection,
            SurrealMetadataStore,
            SurrealStoreConfig,
        )

        if not self._settings.surreal_retrieval_database:
            raise ValueError("surreal_retrieval_database must be set for Surreal retrieval")
        if self._settings.surreal_retrieval_embedding_dimension is None:
            raise ValueError(
                "surreal_retrieval_embedding_dimension must be set for Surreal retrieval"
            )

        connection = SurrealConnection(
            SurrealStoreConfig(
                url=self._settings.surreal_retrieval_url,
                namespace=self._settings.surreal_retrieval_namespace,
                database=self._settings.surreal_retrieval_database,
                username=self._settings.surreal_retrieval_username,
                password=self._settings.surreal_retrieval_password,
                access_token=self._settings.surreal_retrieval_access_token,
            )
        )

        overrides = build_surreal_native_engine_overrides(
            connection,
            self._settings,
            embedding_dimension=self._settings.surreal_retrieval_embedding_dimension,
            hnsw_ef=self._settings.surreal_retrieval_hnsw_ef,
            embedding_shard_count=self._settings.surreal_retrieval_embedding_shard_count,
        )
        self._surreal_connection = connection
        self._surreal_metadata_store = cast(MetadataStoreProtocol, SurrealMetadataStore(connection))
        self._semantic_engine = overrides["semantic"]
        self._keyword_engine = overrides["keyword"]
        self._graph_direct_engine = overrides["graph_direct"]
        self._graph_engine = _DisabledGraphEnrichmentEngine()

    def _active_metadata_store(self) -> MetadataStoreProtocol:
        if self._surreal_metadata_store is not None:
            return self._surreal_metadata_store
        return cast(MetadataStoreProtocol, self._pipeline.metadata_store)

    def close(self) -> None:
        """Shut down service resources cleanly.

        Closes the dedicated local-search executor to reap the worker
        thread before process exit (cycle-4 HIGH housekeeping).
        """
        try:
            self._local_executor.shutdown(wait=True)
        except (RuntimeError, OSError):
            logger.warning("local_executor shutdown failed", exc_info=True)
        pipeline_close = getattr(self._pipeline, "close", None)
        if callable(pipeline_close):
            try:
                pipeline_close()
            except (RuntimeError, OSError):
                logger.warning("pipeline close failed", exc_info=True)
        if self._surreal_connection is not None:
            try:
                self._surreal_connection.close()
            except (RuntimeError, OSError):
                logger.warning("surreal connection close failed", exc_info=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def trickle_indexer(self) -> TrickleIndexer:
        return self._trickle_indexer

    def warmup(self) -> None:
        """Eagerly load ML models so first query is fast."""
        logger.info("Warming up models...")
        self._semantic_engine.warmup()
        try:
            self._reranker_factory.get().warmup()
        except (RuntimeError, OSError, ValueError):
            logger.warning(
                "reranker warmup failed; search will fall back to fused ranking",
                exc_info=True,
            )
        if hasattr(self._keyword_engine, "load_index"):
            self._keyword_engine.load_index()
        if hasattr(self._graph_direct_engine, "load_catalog"):
            self._graph_direct_engine.load_catalog()
        self._check_embedding_model()
        logger.info("Models ready")

    def _check_embedding_model(self) -> None:
        """Warn if the active embedding model differs from what built the index.

        Compares the model name stored in vec_config (written during indexing)
        against the model actually served by TEI (queried via /info).
        This catches silent search degradation when someone swaps the TEI
        model without re-encoding vectors.
        """
        vs = cast(Any, self._pipeline.vector_store)
        if not hasattr(vs, "get_model_name"):
            return
        stored = vs.get_model_name()
        if not stored:
            return
        active = self._semantic_engine.get_tei_model_id()
        if active and stored != active:
            logger.warning(
                "Embedding model mismatch: index was built with %r, "
                "but TEI is serving %r. Re-run indexing to refresh embeddings.",
                stored,
                active,
            )
        if hasattr(vs, "get_distance_metric"):
            metric = vs.get_distance_metric()
            if metric and metric != "cosine":
                logger.warning(
                    "Distance metric mismatch: index uses %r, but code expects 'cosine'. "
                    "Rebuild the index to refresh embeddings.",
                    metric,
                )

    def index(self, directory: Path, *, force: bool = False) -> IndexStats:
        """Index all markdown files under *directory*.

        Delegates entirely to :class:`IndexingPipeline`.

        Parameters
        ----------
        directory:
            Root directory to scan.
        force:
            When ``True``, bypass incremental change detection and
            re-index all files from scratch.  When ``False`` (default),
            only new and modified files are processed.

        Returns
        -------
        IndexStats
            Summary statistics for the completed index.
        """
        return self._pipeline.index(directory, force=force)

    def search(
        self,
        query: str,
        top_k: int = 10,
        mode: SearchMode | str = SearchMode.HYBRID,
        rerank: bool = True,
        expand: bool = True,
        reranker_name: str | None = None,
        include_federated: bool = False,
    ) -> SearchResponse:
        """Search the index and return ranked results.

        Per D-ASYNC-CANONICAL: this is a sync wrapper that calls
        search_async() via asyncio.run(). Raises RuntimeError if called from
        inside an existing event loop (e.g., from an async function or MCP/FastAPI
        handler). Use search_async() directly in those contexts.

        Parameters
        ----------
        query:
            Natural-language search query.
        top_k:
            Maximum number of results to return.
        mode:
            Search strategy.  One of ``"semantic"``, ``"keyword"``,
            ``"graph"``, or ``"hybrid"`` (default).
        rerank:
            If ``True`` the top candidates are re-scored with a
            cross-encoder model before final ranking.
        expand:
            If ``True`` the query is expanded via :class:`QueryExpander`
            before being sent to the search engines.
        reranker_name:
            Optional stable reranker name to use for this request. When
            omitted, the configured default is used.
        include_federated:
            If True, federated provider bundles are queried in addition to the
            local index. Defaults to False for local-only search.

        Returns
        -------
        SearchResponse
            Envelope containing ranked search candidates (at most *top_k* items)
            and per-source SourceStatus records. Local sources report ok/error,
            federated sources report ok/error/skipped states.

        Raises
        ------
        RuntimeError
            If called from inside a running event loop.

        Side effect: appends one row to ``search_log`` in ``index.db`` on every call.
        """
        # Check for unsafe nesting inside a running event loop (cycle-2 HIGH-5)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No loop running — safe to bridge with asyncio.run
            return asyncio.run(
                self.search_async(
                    query,
                    top_k=top_k,
                    mode=mode,
                    rerank=rerank,
                    expand=expand,
                    reranker_name=reranker_name,
                    include_federated=include_federated,
                )
            )

        # Loop is running — must use search_async directly
        raise RuntimeError(
            "DotMDService.search() called from a running event loop; use search_async() instead",
        )

    async def search_async(
        self,
        query: str,
        top_k: int = 10,
        mode: SearchMode | str = SearchMode.HYBRID,
        rerank: bool = True,
        expand: bool = True,
        reranker_name: str | None = None,
        include_federated: bool = False,
    ) -> SearchResponse:
        """Async search with optional federated fan-out support (Phase 34 Plan 02).

        Per D-ASYNC-CANONICAL: This is the canonical async entry point.
        The sync search() method raises if called inside a running event loop.

        Parameters
        ----------
        query:
            Natural-language search query.
        top_k:
            Maximum number of results to return.
        mode:
            Search strategy. One of "semantic", "keyword", "graph", or "hybrid".
        rerank:
            If True, top candidates are re-scored with cross-encoder before final ranking.
        expand:
            If True, query is expanded via QueryExpander before engine calls.
        reranker_name:
            Optional stable reranker name. Omitted uses configured default.
        include_federated:
            If True, federated provider bundles are queried alongside the local
            engines. Defaults to False for local-only search.

        Returns
        -------
        SearchResponse
            Envelope containing candidates list and per-source SourceStatus records.
            Per D-12: errors don't fail the search; they're recorded in SourceStatus
            as error records with reason text.

        Notes
        -----
        - Per D-LOCAL-SEQUENTIAL: Local engines run sequentially on max_workers=1.
        - Per D-LOCAL-SERIALIZED: Concurrent search_async calls queue on executor.
        - Per D-09: Federated providers get per-source soft timeout (3-5s).
        - Per D-LOOP-SAFE: search_async doesn't block the event loop.
        """
        try:
            # Stage 0: Persistent lifecycle init errors (D-08, HIGH-6)
            persistent_status: list[SourceStatus] = [
                SourceStatus(
                    name=ns,
                    status="error",
                    reason=msg,
                    candidate_count=0,
                    elapsed_ms=0.0,
                )
                for ns, msg in self._lifecycle_init_errors.items()
            ]

            pool_size = self._settings.rerank_pool_size if rerank else top_k
            active_pool_size = self._active_filter_pool_size(top_k, pool_size)

            expanded_query = (
                self._query_expander.expand(query).expanded_text or query if expand else query
            )

            loop = asyncio.get_running_loop()

            local_coro = loop.run_in_executor(
                self._local_executor,
                lambda: self._execute_search(
                    search_query=expanded_query,
                    original_query=query,
                    top_k=top_k,
                    mode=mode,
                    rerank=rerank,
                    reranker_name=reranker_name,
                    pool_size=active_pool_size,
                ),
            )

            if include_federated:
                from dotmd.search.federated import fanout_federated, outcomes_to_source_status

                engine_calls: dict[str, Any] = {
                    self._federated_engine_name(bundle): (
                        lambda b=bundle: b.provider.search_native(expanded_query, limit=top_k)
                    )
                    for bundle in self._lifecycle_bundles.values()
                    if bundle.supports_federated_search
                }

                if engine_calls:
                    local_candidates, fed_outcomes = await asyncio.gather(
                        local_coro,
                        fanout_federated(
                            engine_calls,
                            timeout=self._settings.federated_timeout_seconds,
                        ),
                    )
                    fed_candidates = [c for outcome in fed_outcomes for c in outcome.candidates]
                    all_candidates = _merge_with_federated_quota(
                        local_candidates,
                        fed_candidates,
                        top_k,
                        self._settings.federated_result_quota,
                    )
                    fed_status = outcomes_to_source_status(fed_outcomes)
                else:
                    local_candidates = await local_coro
                    all_candidates = sorted(
                        local_candidates, key=lambda c: c.fused_score, reverse=True
                    )[:top_k]
                    fed_status = []
            else:
                local_candidates = await local_coro
                all_candidates = sorted(
                    local_candidates, key=lambda c: c.fused_score, reverse=True
                )[:top_k]
                fed_status = []

            return SearchResponse(
                candidates=all_candidates,
                source_status=persistent_status + fed_status,
            )

        except Exception:
            logger.exception(
                "search_async failed: query_len=%d mode=%s",
                len(query),
                _search_mode_log_label(mode),
            )
            raise

    def _execute_search(
        self,
        search_query: str,
        original_query: str,
        top_k: int,
        mode: SearchMode | str,
        rerank: bool,
        reranker_name: str | None,
        pool_size: int,
    ) -> list[SearchCandidate]:
        """Core retrieval + fusion + reranking pipeline.

        Separated from :meth:`search` so tests can patch this method to inject
        stub results without running the full engine stack.

        Parameters
        ----------
        search_query:
            Possibly-expanded query string for engine calls.
        original_query:
            The original (unexpanded) query used for snippet extraction.
        top_k, mode, rerank, reranker_name, pool_size:
        Same as :meth:`search`.
        """
        self._ensure_source_provenance_ready()
        active_pool_size = self._active_filter_pool_size(top_k, pool_size)
        pool, filtered_fused, active_provenance_map, inactive_count = (
            self._collect_active_candidate_pool(
                search_query=search_query,
                original_query=original_query,
                mode=mode,
                top_k=top_k,
                pool_size=active_pool_size,
            )
        )
        fused = pool["fused"]
        if not fused:
            return []
        engine_results = pool["engine_results"]
        semantic_hits = pool["semantic_hits"]
        keyword_hits = pool["keyword_hits"]
        if len(filtered_fused) < top_k:
            logger.warning(
                "active filter underfilled: requested=%d active=%d inactive=%d candidates=%d",
                top_k,
                len(filtered_fused),
                inactive_count,
                len(fused),
            )
        fused = filtered_fused
        if not fused:
            return []

        # -- Optional reranking -----------------------------------------------
        reranked_applied = False
        if rerank and fused:
            rerank_limit = min(pool_size, len(fused))
            rerank_candidates = fused[:rerank_limit]
            chunk_ids = [cid for cid, _ in rerank_candidates]
            fused_scores = dict(fused)  # ALL fused, not just pool_size
            reranker = self._reranker_factory.get(reranker_name)
            reranked = reranker.rerank(
                search_query,
                chunk_ids,
                self._active_metadata_store(),
                top_k=rerank_limit,
            )
            if not reranked:
                logger.info("reranker returned no candidates; falling back to fused ranking")
                reranked = []
            # Blend reranker scores with fusion scores via min-max normalization
            if reranked:
                reranked_applied = True
                re_scores = [s for _, s in reranked]
                re_min, re_max = min(re_scores), max(re_scores)
                re_range = re_max - re_min if re_max > re_min else 1.0

                fused_vals = [fused_scores[cid] for cid, _ in reranked if cid in fused_scores]
                fused_min = min(fused_vals) if fused_vals else 0.0
                fused_max = max(fused_vals) if fused_vals else 1.0
                fused_range = fused_max - fused_min if fused_max > fused_min else 1.0

                blended = []
                for cid, re_score in reranked:
                    norm_re = (re_score - re_min) / re_range
                    raw_fused = fused_scores.get(cid, fused_min)
                    norm_fused = (raw_fused - fused_min) / fused_range
                    blended.append((cid, 0.4 * norm_fused + 0.6 * norm_re))

                # Merge back fusion candidates not scored by reranker
                reranked_ids = {cid for cid, _ in blended}
                for cid, fused_score in fused:
                    if cid not in reranked_ids:
                        blended.append((cid, fused_score))

                blended.sort(key=lambda x: x[1], reverse=True)
                fused = blended

                # Diagnostic: how many keyword-only matches survived reranking
                kw_ids = {cid for cid, _ in keyword_hits}
                semantic_ids = {cid for cid, _ in semantic_hits}
                kw_only_ids = kw_ids - semantic_ids
                kw_in_final = sum(1 for cid, _ in fused if cid in kw_only_ids)
                logger.debug(
                    "Reranked %d candidates (pool_size=%d, fused=%d); "
                    "%d keyword-only matches in final list",
                    len(reranked),
                    pool_size,
                    len(fused),
                    kw_in_final,
                )

        # -- Build final SearchCandidate list ------------------------------------
        # Note: fused contains (chunk_id, score) pairs at this point.
        # build_candidates will hydrate these into full SearchCandidate objects
        # using the metadata_store and provenance map.
        candidates = build_candidates(
            fused[:top_k],
            per_engine=engine_results,
            metadata_store=self._active_metadata_store(),
            query=original_query,
            active_provenance_map=active_provenance_map,
            top_k=top_k,
            snippet_length=self._settings.snippet_length,
        )

        # Log search for observability and future auto-calibration (Phase 999.12)
        try:
            self._pipeline.log_search(
                query=original_query,
                weights_used=self._settings.parsed_embedding_weights,
                top_results=[
                    {
                        "chunk_id": c.chunk_id or c.ref,
                        "score": float(c.fused_score),
                        "engine": c.matched_engines[0] if c.matched_engines else "unknown",
                    }
                    for c in candidates[:top_k]
                ],
                mode=mode if isinstance(mode, str) else str(mode),
                reranked=reranked_applied,
            )
        except (sqlite3.Error, RuntimeError):
            logger.warning("search log failed — non-fatal", exc_info=True)

        return candidates

    def _run_local_search_sequence(
        self,
        query: str,
        pool_size: int,
    ) -> list[Any]:
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

        Parameters
        ----------
        query:
            Search query string (possibly expanded).
        pool_size:
            Number of results to request per engine.

        Returns
        -------
        list[LocalEngineOutcome]
            Outcomes from semantic, keyword, and graph_direct engines
            in that order.
        """
        from dotmd.search.federated import _run_local_engine

        outcomes: list[Any] = []
        outcomes.append(
            _run_local_engine(
                "semantic",
                lambda: self._semantic_engine.search(query, top_k=pool_size),
            )
        )
        outcomes.append(
            _run_local_engine(
                "keyword",
                lambda: self._keyword_engine.search(query, top_k=pool_size),
            )
        )
        outcomes.append(
            _run_local_engine(
                "graph_direct",
                lambda: self._graph_direct_engine.search(query, top_k=pool_size),
            )
        )
        return outcomes

    def _federated_engine_name(self, bundle: Any) -> str:
        """Return namespaced engine name for a federated bundle.

        Parameters
        ----------
        bundle:
            SourceRuntimeBundle with supports_federated_search=True.

        Returns
        -------
        str
            Namespaced engine name (e.g., "tg:fts" for Telegram).
        """
        namespace = bundle.descriptor.namespace
        if namespace == "telegram":
            return "tg:fts"
        return f"{namespace}:fts"

    def _filter_active_fused_candidates_by_ref(
        self,
        fused: list[tuple[str, float]],
    ) -> tuple[list[tuple[str, float]], dict[str, ChunkProvenance], int]:
        """Filter fused candidates by active bindings (ref-keyed version).

        Parameters
        ----------
        fused:
            List of (ref, score) tuples from fusion.

        Returns
        -------
        tuple
            (filtered_fused, active_provenance_map, inactive_count)
        """
        # For local refs, check active bindings
        active_provenance_map: dict[str, ChunkProvenance] = {}
        filtered_fused: list[tuple[str, float]] = []
        inactive_count = 0

        for ref, score in fused:
            # Federated refs (telegram:*) bypass active filter
            if isinstance(ref, str) and ref.startswith("telegram:"):
                filtered_fused.append((ref, score))
                continue

            # Local refs: For Phase 34, just include all local refs
            # (active binding filtering would require metadata store integration
            # which is deferred to later phases)
            filtered_fused.append((ref, score))

        return filtered_fused, active_provenance_map, inactive_count

    def _batch_load_provenance(
        self,
        chunk_ids: set[str],
    ) -> dict[str, ChunkProvenance]:
        """Load provenance records for a set of chunk IDs.

        Parameters
        ----------
        chunk_ids:
            Set of chunk_id strings.

        Returns
        -------
        dict[str, ChunkProvenance]
            Map from chunk_id to ChunkProvenance record.
        """
        from dotmd.storage.base import MetadataStoreProtocol

        store = cast(MetadataStoreProtocol, self._pipeline.metadata_store)
        provenance_map: dict[str, ChunkProvenance] = {}

        chunks = store.get_chunks(list(chunk_ids))
        for chunk in chunks:
            if chunk.provenance:
                provenance_map[chunk.chunk_id] = chunk.provenance

        return provenance_map

    def _build_candidates_with_federated(
        self,
        fused: list[tuple[str, float]],
        per_engine_ref: dict[str, list[tuple[str, float]]],
        active_provenance_map: dict[str, Any],
        federated_candidates_by_ref: dict[str, SearchCandidate],
        query: str,
        top_k: int,
        mode: SearchMode | str,
        rerank: bool,
        reranker_name: str | None,
    ) -> list[SearchCandidate]:
        """Build final SearchCandidate list with federated integration.

        Orchestrates Stage 5 (build candidates) and Stage 6 (optional rerank).
        Federated candidates (chunk_id is None) skip reranking per D-07.

        Parameters
        ----------
        fused:
            Fused (ref, score) tuples from Stage 3-4.
        per_engine_ref:
            Per-engine ref→score mappings for engine_scores attribution.
        active_provenance_map:
            Active local provenance records (ref→Provenance).
        federated_candidates_by_ref:
            Pre-built SearchCandidate objects from federated providers.
        query:
            Original query for snippet context.
        top_k, mode, rerank, reranker_name:
            Search parameters.

        Returns
        -------
        list[SearchCandidate]
            Top-K ranked candidates with engine attribution and optional reranking.
        """
        from dotmd.storage.base import MetadataStoreProtocol

        # Stage 5: Build candidates, distinguishing local from federated refs
        candidates: list[SearchCandidate] = []

        for ref, score in fused[:top_k]:
            if ref in federated_candidates_by_ref:
                # Federated ref: use prebuilt candidate, enforce engine_scores=None
                fed_cand = federated_candidates_by_ref[ref]
                # Override engine_scores to enforce D-02 invariant
                # Only include engines that actually scored this ref
                matched_engines = tuple(
                    engine_name
                    for engine_name, refs in per_engine_ref.items()
                    if any(eng_ref == ref for eng_ref, _ in refs)
                )
                candidates.append(
                    SearchCandidate(
                        ref=fed_cand.ref,
                        namespace=fed_cand.namespace,
                        descriptor_key=fed_cand.descriptor_key,
                        source_kind=fed_cand.source_kind,
                        retrieval_kind=fed_cand.retrieval_kind,
                        title=fed_cand.title,
                        snippet=fed_cand.snippet,
                        fused_score=score,
                        can_read=fed_cand.can_read,
                        can_materialize=fed_cand.can_materialize,
                        chunk_id=None,  # Federated only
                        heading_path=None,
                        provenance=None,
                        matched_engines=matched_engines,
                        source_native_score=fed_cand.source_native_score,
                        source_native_rank=fed_cand.source_native_rank,
                        engine_scores=None,  # Enforce D-02 (cycle-2 MEDIUM fold-in)
                        provider_metadata=fed_cand.provider_metadata,
                    )
                )
            else:
                # Local ref: build from provenance
                if ref not in active_provenance_map:
                    continue

                prov = active_provenance_map[ref]
                store = cast(MetadataStoreProtocol, self._pipeline.metadata_store)

                # Extract snippet from metadata
                snippet = ""
                try:
                    chunk = store.get_chunk(prov.chunk_id)
                    if chunk and hasattr(chunk, "text"):
                        snippet = chunk.text[: self._settings.snippet_length]
                except (sqlite3.Error, RuntimeError):
                    pass

                # Attribute engines that scored this ref
                engine_scores: dict[str, float] = {}
                for engine_name, refs in per_engine_ref.items():
                    for eng_ref, eng_score in refs:
                        if eng_ref == ref:
                            engine_scores[engine_name] = eng_score
                            break

                candidates.append(
                    SearchCandidate(
                        ref=prov.ref,
                        namespace=prov.namespace,
                        descriptor_key=prov.descriptor_key,
                        source_kind=prov.source_kind,
                        retrieval_kind=prov.retrieval_kind,
                        title=prov.title,
                        snippet=snippet,
                        fused_score=score,
                        can_read=True,
                        can_materialize=False,
                        chunk_id=prov.chunk_id,
                        heading_path=prov.heading_path,
                        provenance=prov,
                        matched_engines=tuple(engine_scores.keys()),
                        source_native_score=None,
                        source_native_rank=None,
                        engine_scores=engine_scores or None,
                        provider_metadata=None,
                    )
                )

        # Stage 6: Optional reranking (skip federated candidates: chunk_id is None)
        if rerank and candidates:
            rerank_limit = min(self._settings.rerank_pool_size, len(candidates))
            # Only rerank candidates with chunk_id set (local only)
            rerank_candidates = [c for c in candidates[:rerank_limit] if c.chunk_id is not None]

            if rerank_candidates:
                reranker = self._reranker_factory.get(reranker_name)
                chunk_ids = [c.chunk_id for c in rerank_candidates if c.chunk_id is not None]
                fused_scores_dict = {c.ref: c.fused_score for c in candidates}

                reranked = reranker.rerank(
                    query,
                    chunk_ids,
                    cast(MetadataStoreProtocol, self._pipeline.metadata_store),
                    top_k=rerank_limit,
                )

                if reranked:
                    # Blend reranker scores with fusion scores
                    re_scores = [s for _, s in reranked]
                    re_min, re_max = min(re_scores), max(re_scores)
                    re_range = re_max - re_min if re_max > re_min else 1.0

                    fused_vals = [
                        fused_scores_dict.get(cid, 0.0)
                        for cid, _ in reranked
                        if cid in fused_scores_dict
                    ]
                    fused_min = min(fused_vals) if fused_vals else 0.0
                    fused_max = max(fused_vals) if fused_vals else 1.0
                    fused_range = fused_max - fused_min if fused_max > fused_min else 1.0

                    # Update fused_score for reranked candidates
                    reranked_refs = {cid for cid, _ in reranked}
                    for i, cand in enumerate(candidates):
                        if cand.chunk_id in reranked_refs:
                            # Find reranked score
                            for chunk_id, re_score in reranked:
                                if chunk_id == cand.chunk_id:
                                    norm_re = (re_score - re_min) / re_range
                                    raw_fused = fused_scores_dict.get(cand.ref, fused_min)
                                    norm_fused = (raw_fused - fused_min) / fused_range
                                    blended_score = 0.4 * norm_fused + 0.6 * norm_re
                                    # Update candidate with blended score
                                    candidates[i] = SearchCandidate(
                                        ref=cand.ref,
                                        namespace=cand.namespace,
                                        descriptor_key=cand.descriptor_key,
                                        source_kind=cand.source_kind,
                                        retrieval_kind=cand.retrieval_kind,
                                        title=cand.title,
                                        snippet=cand.snippet,
                                        fused_score=blended_score,
                                        can_read=cand.can_read,
                                        can_materialize=cand.can_materialize,
                                        chunk_id=cand.chunk_id,
                                        heading_path=cand.heading_path,
                                        provenance=cand.provenance,
                                        matched_engines=cand.matched_engines,
                                        source_native_score=cand.source_native_score,
                                        source_native_rank=cand.source_native_rank,
                                        engine_scores=cand.engine_scores,
                                        provider_metadata=cand.provider_metadata,
                                    )
                                    break

                    # Re-sort candidates by blended score
                    candidates.sort(key=lambda c: c.fused_score, reverse=True)

        return candidates[:top_k]

    def _active_filter_pool_size(self, top_k: int, pool_size: int) -> int:
        """Return candidate pool size used before active-binding filtering."""
        return max(
            pool_size,
            top_k * ACTIVE_FILTER_OVERFETCH_FACTOR,
            top_k + 50,
        )

    def _collect_active_candidate_pool(
        self,
        *,
        search_query: str,
        original_query: str,
        mode: SearchMode | str,
        top_k: int,
        pool_size: int,
    ) -> tuple[
        RerankCandidatePool,
        list[tuple[str, float]],
        dict[str, ChunkProvenance],
        int,
    ]:
        """Expand retrieval until active candidates are filled or engines exhaust."""
        active_pool_size = self._active_filter_pool_size(top_k, pool_size)
        previous_count = -1
        inactive_count = 0
        active_provenance_map: dict[str, ChunkProvenance] = {}
        filtered_fused: list[tuple[str, float]] = []

        while True:
            pool = self._collect_candidate_pool(
                search_query=search_query,
                original_query=original_query,
                mode=mode,
                pool_size=active_pool_size,
            )
            fused = pool["fused"]
            if not fused:
                return pool, [], {}, 0

            filtered_fused, active_provenance_map, inactive_count = (
                self._filter_active_fused_candidates(fused)
            )
            if len(filtered_fused) >= top_k:
                return pool, filtered_fused, active_provenance_map, inactive_count
            if len(fused) < active_pool_size:
                return pool, filtered_fused, active_provenance_map, inactive_count
            if len(fused) <= previous_count:
                return pool, filtered_fused, active_provenance_map, inactive_count

            previous_count = len(fused)
            active_pool_size *= 2

    def _filter_active_fused_candidates(
        self,
        fused: list[tuple[str, float]],
    ) -> tuple[list[tuple[str, float]], dict[str, ChunkProvenance], int]:
        """Drop inactive public candidates while preserving missing-provenance errors."""
        strategy = self._settings.chunk_strategy
        chunk_ids = [chunk_id for chunk_id, _score in fused]
        store = self._active_metadata_store()
        all_provenance = store.get_chunk_provenance_for_chunk_ids(strategy, chunk_ids)
        active_provenance = store.get_active_chunk_provenance_for_chunk_ids(
            strategy,
            chunk_ids,
        )

        filtered: list[tuple[str, float]] = []
        inactive_count = 0
        for chunk_id, score in fused:
            if chunk_id in active_provenance:
                filtered.append((chunk_id, score))
                continue
            if chunk_id in all_provenance:
                inactive_count += 1
                continue
            raise ValueError(f"missing source provenance for chunk_id={chunk_id}")

        return filtered, active_provenance, inactive_count

    def compare_rerankers(
        self,
        query: str,
        reranker_names: list[str] | None = None,
        top_k: int = 10,
        mode: SearchMode | str = SearchMode.HYBRID,
        expand: bool = True,
    ) -> RerankerComparison:
        """Compare configured rerankers over one shared candidate pool.

        This is a developer diagnostic path. It intentionally returns raw
        reranker ordering and scores instead of building user search results.
        """
        search_query = query
        if expand:
            expanded = self._query_expander.expand(query)
            search_query = expanded.expanded_text or query

        pool_size = self._settings.rerank_pool_size
        pool = self._collect_candidate_pool(
            search_query=search_query,
            original_query=query,
            mode=mode,
            pool_size=pool_size,
        )
        chunk_ids = [cid for cid, _score in pool["fused"][:pool_size]]
        names = reranker_names or self._settings.parsed_reranker_compare_names

        runs: list[RerankerRunComparison] = []
        for name in names:
            reranker = self._reranker_factory.get(name)
            started_total = time.perf_counter()
            load_ms = 0.0
            rerank_ms = 0.0
            load_finished = False
            try:
                reranker.warmup()
                load_finished_at = time.perf_counter()
                load_ms = (load_finished_at - started_total) * 1000.0
                load_finished = True

                reranked = reranker.rerank(
                    search_query,
                    chunk_ids,
                    cast(MetadataStoreProtocol, self._pipeline.metadata_store),
                    top_k=top_k,
                    raise_on_provider_error=True,
                )
                finished_at = time.perf_counter()
                rerank_ms = (finished_at - load_finished_at) * 1000.0
                elapsed_ms = (finished_at - started_total) * 1000.0
                runs.append(
                    {
                        "name": name,
                        "model_name": reranker.model_name,
                        "elapsed_ms": elapsed_ms,
                        "elapsed": format_elapsed_ms(elapsed_ms),
                        "load_ms": load_ms,
                        "load": format_elapsed_ms(load_ms),
                        "rerank_ms": rerank_ms,
                        "rerank": format_elapsed_ms(rerank_ms),
                        "returned_count": len(reranked),
                        "top_chunk_ids": [cid for cid, _score in reranked],
                        "scores": [float(score) for _cid, score in reranked],
                        "error": None,
                    }
                )
            except (RuntimeError, ValueError) as exc:
                elapsed_ms = (time.perf_counter() - started_total) * 1000.0
                if load_finished:
                    rerank_ms = max(0.0, elapsed_ms - load_ms)
                else:
                    load_ms = elapsed_ms
                runs.append(
                    {
                        "name": name,
                        "model_name": reranker.model_name,
                        "elapsed_ms": elapsed_ms,
                        "elapsed": format_elapsed_ms(elapsed_ms),
                        "load_ms": load_ms,
                        "load": format_elapsed_ms(load_ms),
                        "rerank_ms": rerank_ms,
                        "rerank": format_elapsed_ms(rerank_ms),
                        "returned_count": 0,
                        "top_chunk_ids": [],
                        "scores": [],
                        "error": str(exc),
                    }
                )

        runs.sort(key=lambda run: (run["error"] is not None, run["rerank_ms"]))
        successful = [run for run in runs if run["error"] is None]
        overlap_reference = successful[0]["name"] if successful else None
        overlap: dict[str, int] = {}
        if successful:
            reference_ids = set(successful[0]["top_chunk_ids"])
            overlap = {
                run["name"]: len(reference_ids & set(run["top_chunk_ids"])) for run in successful
            }

        return {
            "query": query,
            "search_query": search_query,
            "shared_pool_size": len(chunk_ids),
            "candidate_pool_chunk_ids": chunk_ids,
            "rerankers": runs,
            "overlap_reference": overlap_reference,
            "overlap": overlap,
        }

    def _collect_candidate_pool(
        self,
        *,
        search_query: str,
        original_query: str,
        mode: SearchMode | str,
        pool_size: int,
        engine_overrides: dict[str, SearchEngineProtocol | GraphEnrichmentEngineProtocol]
        | None = None,
    ) -> RerankCandidatePool:
        """Collect fused candidates after graph enrichment for reuse by rerankers."""
        overrides = engine_overrides or {}
        semantic_engine = cast(
            SearchEngineProtocol,
            overrides.get("semantic", self._semantic_engine),
        )
        keyword_engine = cast(
            SearchEngineProtocol,
            overrides.get("keyword", self._keyword_engine),
        )
        graph_direct_engine = cast(
            SearchEngineProtocol,
            overrides.get("graph_direct", self._graph_direct_engine),
        )
        graph_engine = cast(
            GraphEnrichmentEngineProtocol,
            overrides.get("graph", self._graph_engine),
        )

        # -- Stage 1: Primary retrieval ----------------------------------------
        semantic_hits: list[tuple[str, float]] = []
        keyword_hits: list[tuple[str, float]] = []
        graph_direct_hits: list[tuple[str, float]] = []

        if mode in (SearchMode.SEMANTIC, SearchMode.HYBRID, SearchMode.GRAPH):
            semantic_hits = semantic_engine.search(search_query, top_k=pool_size)

        if mode in (SearchMode.KEYWORD, SearchMode.HYBRID, SearchMode.GRAPH):
            keyword_hits = keyword_engine.search(search_query, top_k=pool_size)

        # Graph-direct: entity matching (pre-fusion peer, not seed-based)
        if mode in (SearchMode.GRAPH, SearchMode.HYBRID):
            graph_direct_hits = graph_direct_engine.search(
                original_query,
                top_k=pool_size,
            )

        if not semantic_hits and not keyword_hits and not graph_direct_hits:
            return {
                "search_query": search_query,
                "original_query": original_query,
                "fused": [],
                "engine_results": {},
                "semantic_hits": semantic_hits,
                "keyword_hits": keyword_hits,
                "graph_direct_hits": graph_direct_hits,
                "pool_size": pool_size,
            }

        # -- Stage 2: RRF fusion (all primary engines) -------------------------
        engine_results: dict[str, list[tuple[str, float]]] = {}
        if semantic_hits:
            engine_results["semantic"] = semantic_hits
        if keyword_hits:
            engine_results["keyword"] = keyword_hits
        if graph_direct_hits:
            engine_results["graph_direct"] = graph_direct_hits

        fused = fuse_results(
            engine_results,
            k=self._settings.fusion_k,
        )

        # -- Stage 3: Graph enrichment (post-fusion, not a peer) ---------------
        if mode in (SearchMode.GRAPH, SearchMode.HYBRID) and fused:
            seed_ids = [cid for cid, _ in fused[:pool_size]]
            try:
                graph_hits = graph_engine.search(
                    search_query,
                    top_k=pool_size,
                    seed_chunk_ids=seed_ids,
                )
            except Exception:  # noqa: BLE001 - graph enrichment is best-effort.
                logger.warning(
                    "graph enrichment failed; continuing with primary fused results",
                    exc_info=True,
                )
                graph_hits = []
            if graph_hits:
                # Graph-discovered chunks get appended below primary results.
                # Score: fraction of the lowest fused score so they never
                # outrank direct hits.
                fused_floor = fused[-1][1] if fused else 0.0
                fused_ids = {cid for cid, _ in fused}
                for cid, _gscore in graph_hits:
                    if cid not in fused_ids:
                        fused.append((cid, fused_floor * 0.5))
                        fused_ids.add(cid)
                engine_results["graph"] = graph_hits

        return {
            "search_query": search_query,
            "original_query": original_query,
            "fused": fused,
            "engine_results": engine_results,
            "semantic_hits": semantic_hits,
            "keyword_hits": keyword_hits,
            "graph_direct_hits": graph_direct_hits,
            "pool_size": pool_size,
        }

    def _ensure_source_provenance_ready(self) -> None:
        """Ensure the active strategy can hydrate public source refs before search."""
        strategy = self._settings.chunk_strategy
        if strategy in self._source_provenance_ready_strategies:
            return

        store = self._pipeline.metadata_store
        try:
            missing = store.count_missing_source_provenance(strategy)
        except AttributeError:
            logger.debug("metadata store has no source provenance safety helpers")
            self._source_provenance_ready_strategies.add(strategy)
            return

        if not isinstance(missing, int):
            logger.debug("metadata store returned non-integer provenance count: %r", missing)
            self._source_provenance_ready_strategies.add(strategy)
            return

        if missing > 0:
            inserted = store.backfill_missing_source_provenance_from_file_paths(
                strategy,
                dry_run=False,
            )
            remaining = store.count_missing_source_provenance(strategy)
            if remaining > 0:
                raise ValueError(
                    "source provenance backfill incomplete: "
                    f"missing={missing} inserted={inserted} remaining={remaining}"
                )
            logger.info(
                "source provenance backfilled: strategy=%s missing=%d inserted=%d",
                strategy,
                missing,
                inserted,
            )

        # Migration guard, not a steady-state search dependency.
        #
        # Phase 27 made active resource bindings the public visibility gate:
        # chunks/provenance may be retained for reuse, but ordinary search must
        # only return resources with active source_documents/resource_bindings.
        # Phase 33 then routed filesystem construction through lifecycle, which
        # correctly writes those rows for newly indexed files. The problem this
        # guard covers is older live indexes: they can already have chunks,
        # FTS/vector rows, and chunk_source_provenance, while unchanged files
        # never re-enter the indexing path that now creates source_documents and
        # active bindings. Without this repair, the active filter would hide
        # valid indexed content even though the expensive artifacts are intact.
        #
        # Keep this path additive: it may create missing filesystem
        # source_documents and active resource_bindings from existing provenance,
        # but it must not rebuild chunks, embeddings, FTS, graph data, or
        # fingerprints. Once all supported deployments have migrated cleanly
        # and new indexing has proven it maintains the invariant by itself, this
        # guard should be removed and replaced with a hard integrity failure.
        try:
            source_doc_diagnostic = (
                self._pipeline.backfill_filesystem_source_documents_from_provenance(
                    strategy,
                    dry_run=False,
                )
            )
        except AttributeError:
            logger.debug("pipeline has no filesystem source-document backfill helper")
        else:
            inserted_docs = int(source_doc_diagnostic.get("inserted_source_documents", 0))
            inserted_bindings = int(source_doc_diagnostic.get("inserted_bindings", 0))
            if inserted_docs or inserted_bindings:
                logger.info(
                    "filesystem source bindings backfilled: strategy=%s docs=%d "
                    "bindings=%d missing_files=%d skipped_files=%d",
                    strategy,
                    inserted_docs,
                    inserted_bindings,
                    int(source_doc_diagnostic.get("missing_files", 0)),
                    int(source_doc_diagnostic.get("skipped_files", 0)),
                )

        self._source_provenance_ready_strategies.add(strategy)

    def _parse_ref(self, ref: str) -> tuple[str, str]:
        """Split a public source ref into namespace and document_ref."""
        namespace, separator, document_ref = ref.partition(":")
        if not separator or not namespace or not document_ref:
            raise ValueError(f"Unknown source ref: {ref}")
        return namespace, document_ref

    def _resolve_source_document(self, ref: str) -> SourceDocument:
        """Resolve a public ref to its source document row."""
        namespace, document_ref = self._parse_ref(ref)
        document = self._pipeline.metadata_store.get_source_document(
            namespace,
            document_ref,
        )
        if document is not None:
            return document
        if namespace == "filesystem":
            resolved = Path(document_ref).resolve()
            active_chunk_count = self._pipeline.metadata_store.get_chunk_count_for_file(
                self._settings.chunk_strategy,
                str(resolved),
            )
            if not isinstance(active_chunk_count, int) or active_chunk_count <= 0:
                raise ValueError(f"Unknown source ref: {ref}")
            if not resolved.exists():
                raise ValueError(f"Unknown source ref: {ref}")
            return SourceDocument(
                namespace="filesystem",
                document_ref=str(resolved),
                ref=f"filesystem:{resolved}",
                source_uri=resolved.as_uri(),
                file_path=resolved,
                media_type="text/markdown",
                parser_name="markdown",
                document_type="document",
                title=resolved.stem,
                updated_at=datetime.fromtimestamp(resolved.stat().st_mtime, tz=UTC),
                content_fingerprint="",
                metadata_fingerprint="",
                metadata_json={},
            )
        raise ValueError(f"Unknown source ref: {ref}")

    def _require_active_source_document(self, ref: str) -> SourceDocument:
        """Resolve a public ref only when its resource binding is active."""
        namespace, document_ref = self._parse_ref(ref)
        if not self._pipeline.metadata_store.is_resource_binding_active(
            namespace,
            document_ref,
        ):
            raise ValueError(f"Unknown source ref: {ref}")
        return self._resolve_source_document(ref)

    def _resolve_telegram_read_path(self, ref: str) -> TelegramReadPath:
        """Determine routing decision for Telegram message read operations.

        Returns the routing decision:
        - LOCAL_ACTIVE: local entry with ACTIVE binding → use local chunks
        - LOCAL_INACTIVE: local entry with INACTIVE binding → raise PermissionError
        - FEDERATED_ONLY: no local entry → use provider
        """
        try:
            document_ref, _unit_ref = _parse_telegram_message_ref(ref)
        except ValueError:
            return TelegramReadPath.FEDERATED_ONLY

        # Check if local entry exists
        document = self._pipeline.metadata_store.get_source_document(
            "telegram",
            document_ref,
        )

        if document is None:
            return TelegramReadPath.FEDERATED_ONLY

        # Check binding status
        if self._pipeline.metadata_store.is_resource_binding_active(
            "telegram",
            document_ref,
        ):
            return TelegramReadPath.LOCAL_ACTIVE
        return TelegramReadPath.LOCAL_INACTIVE

    def _require_active_telegram_message_ref(self, ref: str) -> tuple[SourceDocument, str]:
        """Resolve a Telegram message ref through its active dialog binding."""
        document_ref, unit_ref = _parse_telegram_message_ref(ref)
        if not self._pipeline.metadata_store.is_resource_binding_active(
            "telegram",
            document_ref,
        ):
            raise ValueError(f"Unknown source ref: {ref}")
        document = self._pipeline.metadata_store.get_source_document(
            "telegram",
            document_ref,
        )
        if document is None or document.namespace != "telegram":
            raise ValueError(f"Unknown source ref: {ref}")
        return document, unit_ref

    def _filesystem_path_for_source(
        self,
        document: SourceDocument,
        ref: str,
    ) -> str:
        if document.namespace != "filesystem":
            raise ValueError(f"Unsupported source namespace: {document.namespace}")
        if document.file_path is None:
            raise ValueError(f"Unknown source ref: {ref}")
        path = document.file_path
        if not path.exists():
            raise ValueError(f"Unknown source ref: {ref}")
        return str(path)

    def _read_frontmatter(self, path: Path) -> dict[str, Any]:
        try:
            frontmatter, _ = parse_frontmatter(read_file(path))
        except (OSError, ValueError):
            logger.warning("frontmatter parse failed: %s", path, exc_info=True)
            return {}
        return frontmatter

    def _telegram_window_sizes(
        self,
        start: int,
        end: int | None,
    ) -> tuple[int, int]:
        before = max(0, min(start, 50))
        after = 5 if end is None else max(0, min(end, 50))
        return before, after

    def _telegram_unit_payload(
        self,
        unit: SourceUnit,
        target_unit_ref: str,
    ) -> dict[str, Any]:
        metadata = dict(unit.metadata_json)
        message_id = metadata.get("message_id")
        if message_id is None:
            try:
                message_id = int(unit.unit_ref.rsplit(":message:", 1)[1])
            except (IndexError, ValueError):
                message_id = None
        return {
            "unit_ref": unit.unit_ref,
            "message_id": message_id,
            "text": unit.text,
            "sender_id": metadata.get("sender_id"),
            "sender_name": metadata.get("sender_name"),
            "sent_at": metadata.get("sent_at") or unit.updated_at.isoformat(),
            "topic_id": metadata.get("topic_id"),
            "topic_title": metadata.get("topic_title"),
            "reply_to_msg_id": metadata.get("reply_to_msg_id"),
            "edit_date": metadata.get("edit_date"),
            "target": unit.unit_ref == target_unit_ref,
        }

    def _read_telegram_message(
        self,
        ref: str,
        start: int,
        end: int | None,
    ) -> ReadPayload:
        # Determine routing path
        path = self._resolve_telegram_read_path(ref)

        # Handle INACTIVE binding gate (Phase 27)
        if path == TelegramReadPath.LOCAL_INACTIVE:
            raise PermissionError(f"Telegram ref has INACTIVE binding: {ref}")

        # Handle FEDERATED_ONLY refs
        if path == TelegramReadPath.FEDERATED_ONLY:
            if self._telegram_provider is None:
                raise ValueError(f"Unknown source ref: {ref}")
            try:
                _document_ref, unit_ref = _parse_telegram_message_ref(ref)
            except ValueError:
                raise ValueError(f"Unknown source ref: {ref}") from None
            before, after = self._telegram_window_sizes(start, end)
            try:
                window = self._telegram_provider.read_unit_window(
                    unit_ref,
                    before=before,
                    after=after,
                )
            except Exception as e:
                raise RuntimeError(f"Telegram provider error: {e}") from e
            units = [self._telegram_unit_payload(unit, unit_ref) for unit in window.units]
            return cast(
                ReadPayload,
                {
                    "ref": ref,
                    "total_chunks": len(units),
                    "frontmatter": {},
                    "units": units,
                    "chunks": [],
                    "metadata": getattr(window, "metadata_json", {}),
                },
            )

        # Handle LOCAL_ACTIVE refs (existing path)
        # LOCAL_ACTIVE means we must use local chunks only, never fall through to provider
        document, unit_ref = self._require_active_telegram_message_ref(ref)

        # Get local chunks (ACTIVE binding uses local path only)
        chunks = self._pipeline.metadata_store.get_chunks_by_source_unit_ref(
            "telegram",
            document.document_ref,
            unit_ref,
            self._settings.chunk_strategy,
        )

        if not chunks:
            raise ValueError(f"Unknown source ref: {ref}")

        chunk_payloads: list[dict[str, Any]] = []
        for index, chunk in enumerate(chunks):
            source_unit_refs = (
                chunk.provenance.source_unit_refs if chunk.provenance is not None else []
            )
            chunk_payloads.append(
                {
                    "index": index,
                    "heading_hierarchy": chunk.heading_hierarchy,
                    "text": chunk.text,
                    "target": unit_ref in source_unit_refs,
                    "source_unit_refs": source_unit_refs,
                }
            )
        return cast(
            ReadPayload,
            {
                "ref": ref,
                "document_ref": document.document_ref,
                "target_unit_ref": unit_ref,
                "total_chunks": len(chunk_payloads),
                "frontmatter": {},
                "chunks": chunk_payloads,
                "units": [],
                "metadata": document.metadata_json,
            },
        )

    def _drill_telegram_message(self, ref: str) -> DrillPayload:
        # Determine routing path
        path = self._resolve_telegram_read_path(ref)
        target_metadata: dict[str, Any] = {}

        # Handle INACTIVE binding gate (Phase 27)
        if path == TelegramReadPath.LOCAL_INACTIVE:
            raise PermissionError(f"Telegram ref has INACTIVE binding: {ref}")

        # Handle FEDERATED_ONLY refs
        if path == TelegramReadPath.FEDERATED_ONLY:
            if self._telegram_provider is None:
                raise ValueError(f"Unknown source ref: {ref}")
            try:
                _document_ref, unit_ref = _parse_telegram_message_ref(ref)
            except ValueError:
                raise ValueError(f"Unknown source ref: {ref}") from None
            try:
                window = self._telegram_provider.read_unit_window(
                    unit_ref,
                    before=0,
                    after=0,
                )
            except Exception as e:
                raise RuntimeError(f"Telegram provider error: {e}") from e
            else:
                for unit in window.units:
                    if unit.unit_ref == unit_ref:
                        target_metadata = self._telegram_unit_payload(unit, unit_ref)
                        break
            return cast(
                DrillPayload,
                {
                    "ref": ref,
                    "title": f"Telegram message {unit_ref}",
                    "source_uri": "",
                    "document_type": "telegram_message",
                    "parser_name": "telegram",
                    "frontmatter": {},
                    "total_chunks": 1,
                    "target_metadata": target_metadata,
                },
            )

        # Handle LOCAL_ACTIVE refs (existing path)
        document, unit_ref = self._require_active_telegram_message_ref(ref)
        if self._telegram_provider is not None:
            try:
                window = self._telegram_provider.read_unit_window(
                    unit_ref,
                    before=0,
                    after=0,
                )
            except (RuntimeError, ValueError):
                logger.warning("telegram target metadata lookup failed", exc_info=True)
            else:
                for unit in window.units:
                    if unit.unit_ref == unit_ref:
                        target_metadata = self._telegram_unit_payload(unit, unit_ref)
                        break
        return cast(
            DrillPayload,
            {
                "ref": ref,
                "document_ref": document.document_ref,
                "target_unit_ref": unit_ref,
                "title": document.title,
                "source_uri": document.source_uri,
                "document_type": document.document_type,
                "parser_name": document.parser_name,
                "frontmatter": {},
                "metadata": document.metadata_json,
                "target_metadata": target_metadata,
                "total_chunks": 0,
            },
        )

    def read(self, ref: str, start: int = 0, end: int | None = None) -> ReadPayload:
        """Return frontmatter and optionally a chunk range for a source ref.

        When end is None, returns only frontmatter and total_chunks (metadata
        mode — cheap, useful for planning a subsequent ranged call).
        When end is provided, also returns chunks[start:end], capped at 50.
        """
        if _is_telegram_message_ref(ref):
            return self._read_telegram_message(ref, start, end)

        document = self._require_active_source_document(ref)
        file_path = self._filesystem_path_for_source(document, ref)
        path = Path(file_path)
        frontmatter = self._read_frontmatter(path)

        # Phase 26 read(ref) is active-strategy-only; future source adapters may add explicit strategy discovery.
        strategy = self._settings.chunk_strategy
        total_chunks = self._pipeline.metadata_store.get_chunk_count_for_file(
            strategy,
            file_path,
        )
        if total_chunks == 0:
            raise ValueError("No chunks for source ref in active strategy")

        chunks: list[dict] = []
        if end is not None:
            end = min(end, start + 50)
            chunks = self._pipeline.metadata_store.get_chunks_for_file_range(
                strategy,
                file_path,
                start,
                end,
            )

        return {
            "ref": document.ref,
            "total_chunks": total_chunks,
            "frontmatter": frontmatter,
            "chunks": chunks,
        }

    def drill(self, ref: str) -> DrillPayload:
        """Return structured source metadata for a source ref."""
        if _is_telegram_message_ref(ref):
            return self._drill_telegram_message(ref)

        document = self._require_active_source_document(ref)
        file_path = self._filesystem_path_for_source(document, ref)
        frontmatter = self._read_frontmatter(Path(file_path))
        total_chunks = self._pipeline.metadata_store.get_chunk_count_for_file(
            self._settings.chunk_strategy,
            file_path,
        )
        return {
            "ref": document.ref,
            "title": document.title,
            "source_uri": document.source_uri,
            "document_type": document.document_type,
            "parser_name": document.parser_name,
            "frontmatter": frontmatter,
            "total_chunks": total_chunks,
        }

    def binding_diagnostics(self) -> BindingDiagnostics:
        """Return binding/artifact count diagnostics without exposing inactive content."""
        binding_counts = self._pipeline.metadata_store.count_resource_bindings()
        rebind_diagnostic = getattr(self._pipeline, "_last_rebind_diagnostic", {})
        reused = self._pipeline.metadata_store.count_reused_chunks_from_bindings()
        if isinstance(rebind_diagnostic, dict):
            reused = max(reused, int(rebind_diagnostic.get("reused_chunks", 0) or 0))
        return {
            "active": int(binding_counts.get("active", 0)),
            "inactive": int(binding_counts.get("inactive", 0)),
            "retained": self._pipeline.metadata_store.count_retained_inactive_chunks(
                self._settings.chunk_strategy,
            ),
            "reused": reused,
        }

    def status(self, live_diff: bool = True) -> IndexStats:
        """Return the current index statistics.

        Always returns an ``IndexStats`` instance (never ``None``) so that
        trickle indexer progress is available even before any explicit
        ``dotmd index`` command has been run.

        When a previous data_dir is known and the directory still exists,
        runs a live file diff to populate pending change counts.
        Pass ``live_diff=False`` to skip the scan (e.g. from MCP tools).

        Returns
        -------
        IndexStats
            The most recent index statistics enriched with trickle state.
        """
        stats = self._pipeline.metadata_store.get_stats()
        if stats is None:
            stats = IndexStats()
        # Live counts from actual tables (stats table may be stale/empty)
        try:
            conn = self._pipeline.conn
            chunks_table = self._pipeline._chunks_table
            stats.total_chunks = conn.execute(f"SELECT COUNT(*) FROM {chunks_table}").fetchone()[0]
            # Phase 16 P5: file count from M2M table (chunks_* has no file_path column)
            strategy = chunks_table.removeprefix("chunks_")
            m2m_table = f"chunk_file_paths_{strategy}"
            stats.total_files = conn.execute(
                f"SELECT COUNT(DISTINCT file_path) FROM {m2m_table}"
            ).fetchone()[0]
        except (AttributeError, sqlite3.Error):
            logger.debug("live chunk/file count failed", exc_info=True)
        # Live graph counts (stats table is only updated by batch run(), not trickle)
        try:
            stats.total_entities = self._pipeline.graph_store.node_count()
            stats.total_edges = self._pipeline.graph_store.edge_count()
        except (RuntimeError, ValueError):
            logger.debug("live graph count failed", exc_info=True)
        # Change detection: run live diff against all known paths (skip for MCP)
        if live_diff:
            try:
                if self._settings.indexing_paths:
                    from dotmd.ingestion.reader import discover_files_multi

                    files = discover_files_multi(
                        self._settings.indexing_paths,
                        self._settings.effective_indexing_exclude,
                    )
                elif stats.data_dir:
                    data_path = Path(stats.data_dir)
                    if data_path.is_dir():
                        from dotmd.ingestion.reader import discover_files

                        files = discover_files(data_path)
                    else:
                        files = []
                else:
                    files = []

                if files:
                    diff = self._pipeline.chunk_tracker.diff(files)
                    stats.new_files = len(diff.new)
                    stats.modified_files = len(diff.modified)
                    stats.deleted_files = len(diff.deleted)
                    stats.unchanged_files = len(diff.unchanged)
            except (OSError, sqlite3.Error) as e:
                logger.warning("Change detection failed: %s", e, exc_info=True)

        # Trickle indexer progress
        trickle_state = self._trickle_indexer.state
        stats.trickle_status = trickle_state.status
        stats.trickle_indexed = trickle_state.indexed_count
        stats.trickle_total = trickle_state.total_files
        stats.trickle_current_file = trickle_state.current_file
        stats.trickle_chunks_per_hour = (
            round(trickle_state.chunks_per_hour, 1) if trickle_state.chunks_per_hour > 0 else None
        )
        stats.trickle_files_per_hour = (
            round(trickle_state.files_per_hour, 1) if trickle_state.files_per_hour > 0 else None
        )
        stats.trickle_eta_minutes = (
            round(trickle_state.eta_minutes, 1) if trickle_state.eta_minutes is not None else None
        )

        return stats

    def graph_data(self) -> dict:
        """Return all graph nodes and edges for visualization."""
        return self._pipeline.graph_store.get_graph_data()

    def drop_vectors(self) -> None:
        """Drop local embedding-cache artifacts for current (strategy, model)."""
        self._pipeline.drop_vectors()

    def drop_chunks(self) -> None:
        """Drop local chunk/cache artifacts for current strategy.

        CASCADE operation: everything derived from chunks under the
        current strategy is removed.
        """
        self._pipeline.drop_chunks()

    def clear(self) -> None:
        """Remove all indexed data from every backing store.

        .. deprecated::
            Use :meth:`drop_vectors` or :meth:`drop_chunks` for granular
            cleanup.  Retained temporarily for backward compatibility.
        """
        self._pipeline.clear()

    def _load_acronyms(self) -> dict[str, list[str]] | None:
        """Load acronym dictionary from disk if available.

        Returns
        -------
        dict[str, list[str]] | None
            Acronym dictionary, or None if file doesn't exist.
        """
        if not self._settings.acronyms_path.exists():
            return None

        try:
            with self._settings.acronyms_path.open() as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load acronyms: %s", e, exc_info=True)
            return None
