"""Graph-based search engine for dotMD.

Expands seed chunk IDs (typically supplied by the semantic or keyword
engines via the fusion layer) by traversing the knowledge graph and
scoring neighbouring section nodes.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable, Iterable
from typing import cast

from dotmd.storage.base import GraphStoreProtocol, MetadataStoreProtocol

logger = logging.getLogger(__name__)


class GraphSearchEngine:
    """Search engine that exploits the knowledge graph for relevance signals.

    Unlike engines that operate directly on raw query text, this engine
    requires a set of *seed* chunk IDs (produced by another engine) and
    discovers related sections by walking the graph.

    Parameters
    ----------
    graph_store:
        A graph store satisfying :class:`GraphStoreProtocol`.
    metadata_store:
        A metadata store satisfying :class:`MetadataStoreProtocol`.
    """

    MAX_SEED_CHUNK_IDS = 8

    def __init__(
        self,
        graph_store: GraphStoreProtocol,
        metadata_store: MetadataStoreProtocol,
    ) -> None:
        self._graph_store = graph_store
        self._metadata_store = metadata_store

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 10,
        seed_chunk_ids: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Traverse the graph from *seed_chunk_ids* and score neighbours.

        The engine prefers a single batched graph lookup when the backend
        exposes one, otherwise it falls back to bounded per-seed lookups.
        Every discovered node is scored using:

        .. code-block:: text

            graph_score = sum(edge_weight / hop_distance ** 2)

        Scores are aggregated across all seeds so that nodes reachable
        from multiple seeds receive a boost.

        Parameters
        ----------
        query:
            The original query string.  Accepted for protocol
            compatibility but **not used** by this engine.
        top_k:
            Maximum number of results to return.
        seed_chunk_ids:
            Starting chunk IDs for graph traversal.  If ``None`` or
            empty, an empty list is returned immediately. Only a bounded,
            de-duplicated prefix of the seed list is used for enrichment.

        Returns
        -------
        list[tuple[str, float]]
            A list of ``(chunk_id, score)`` pairs ordered by
            descending graph score.
        """
        if not seed_chunk_ids:
            return []

        # Aggregate scores: chunk_id -> cumulative graph score
        aggregated_scores: dict[str, float] = defaultdict(float)
        seed_ids = self._bounded_seed_chunk_ids(seed_chunk_ids, top_k)
        seed_set = set(seed_ids)

        neighbors = self._collect_related_sections(seed_ids)
        for node_id, _rel, weight in neighbors:
            if node_id not in seed_set:
                aggregated_scores[node_id] += weight

        # Exclude the seed chunks themselves so the fusion layer does not
        # double-count results already present from another engine.
        for sid in seed_set:
            aggregated_scores.pop(sid, None)

        # Filter to only valid chunk IDs (Section nodes).  The traversal
        # also reaches Entity/Tag/File nodes which aren't searchable
        # results — discard them by checking the metadata store.
        candidate_ids = list(aggregated_scores.keys())
        if candidate_ids:
            valid_chunks = self._metadata_store.get_chunks(candidate_ids)
            valid_ids = {c.chunk_id for c in valid_chunks}
            aggregated_scores = {
                cid: score for cid, score in aggregated_scores.items() if cid in valid_ids
            }

        # Sort by descending score and return top-k.
        sorted_results = sorted(
            aggregated_scores.items(),
            key=lambda item: item[1],
            reverse=True,
        )

        return sorted_results[:top_k]

    def _bounded_seed_chunk_ids(
        self,
        seed_chunk_ids: list[str],
        top_k: int,
    ) -> list[str]:
        """Return a de-duplicated, bounded seed list for graph enrichment."""
        seed_limit = min(max(top_k, 0), self.MAX_SEED_CHUNK_IDS)
        if seed_limit <= 0:
            return []

        bounded: list[str] = []
        seen: set[str] = set()
        for seed_id in seed_chunk_ids:
            if seed_id in seen:
                continue
            seen.add(seed_id)
            bounded.append(seed_id)
            if len(bounded) >= seed_limit:
                break
        return bounded

    def _collect_related_sections(
        self,
        seed_chunk_ids: list[str],
    ) -> list[tuple[str, str, float]]:
        """Collect graph-enrichment neighbors using the best available path."""
        if not seed_chunk_ids:
            return []

        batch_getter = cast(
            Callable[[list[str]], Iterable[tuple[str, str, float]]],
            getattr(self._graph_store, "get_related_sections_for_seeds", None),
        )
        if callable(batch_getter):
            try:
                return list(batch_getter(seed_chunk_ids))
            except Exception:  # noqa: BLE001, RUF100 - graph enrichment is best-effort.
                logger.warning(
                    "graph enrichment batch query failed; continuing without enrichment",
                    exc_info=True,
                )
                return []

        related: list[tuple[str, str, float]] = []
        for seed_id in seed_chunk_ids:
            try:
                neighbors = self._graph_store.get_related_sections(seed_id)
            except Exception:  # noqa: BLE001, RUF100 - graph enrichment is best-effort.
                logger.warning(
                    "graph enrichment seed query failed; skipping seed",
                    exc_info=True,
                )
                continue
            related.extend(neighbors)
        return related
