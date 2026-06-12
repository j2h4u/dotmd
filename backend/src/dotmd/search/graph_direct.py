"""Entity-direct graph retrieval for dotMD.

Unlike :class:`GraphSearchEngine` which traverses from seed chunks,
this engine matches entity names in the query against the graph's
entity catalog and retrieves directly connected chunks.

Participates in RRF fusion as a peer engine alongside semantic and BM25.
"""

from __future__ import annotations

import logging
import re

from dotmd.storage.base import GraphStoreProtocol

logger = logging.getLogger(__name__)


class GraphDirectEngine:
    """Entity-direct retrieval: query → entity match → chunk_ids.

    At startup, loads all entity names from the graph store into an
    in-memory catalog for fast substring matching at query time.

    Parameters
    ----------
    graph_store:
        A graph store satisfying :class:`GraphStoreProtocol`.
    """

    def __init__(self, graph_store: GraphStoreProtocol) -> None:
        self._graph_store = graph_store
        self._entity_catalog: dict[str, str] = {}  # {lowercase_name: original_name}
        self._loaded = False

    def load_catalog(self) -> None:
        """Load all entity names from graph store into memory."""
        try:
            entities = self._graph_store.get_all_entity_names()
            self._entity_catalog = {name.lower(): name for name in entities}
            self._loaded = True
            logger.info(
                "Graph entity catalog loaded: %d entities",
                len(self._entity_catalog),
            )
        except (RuntimeError, ValueError):
            logger.warning("Failed to load entity catalog", exc_info=True)
            self._entity_catalog = {}
            self._loaded = True

    def search(
        self,
        query: str,
        top_k: int = 10,
    ) -> list[tuple[str, float]]:
        """Find chunks connected to entities mentioned in the query.

        Matching strategy:
        1. Tokenize query into words and multi-word phrases
        2. Match against entity catalog (case-insensitive substring)
        3. For matched entities: Cypher query for connected Section nodes
        4. Score by number of entity connections (more entities → higher score)

        Returns
        -------
        list[tuple[str, float]]
            ``(chunk_id, score)`` pairs, descending by score.
        """
        if not self._loaded:
            self.load_catalog()

        if not self._entity_catalog:
            return []

        # Match entities in query
        matched = self._match_entities(query)
        if not matched:
            return []

        logger.debug("Graph-direct: matched_entities=%d", len(matched))

        # Retrieve connected chunks for all matched entities
        chunk_scores: dict[str, float] = {}
        for entity_name in matched:
            chunk_ids = self._graph_store.get_chunks_by_entity(entity_name)
            for cid in chunk_ids:
                chunk_scores[cid] = chunk_scores.get(cid, 0.0) + 1.0

        # Normalize scores to [0, 1]
        if chunk_scores:
            max_score = max(chunk_scores.values())
            if max_score > 0:
                chunk_scores = {cid: score / max_score for cid, score in chunk_scores.items()}

        sorted_results = sorted(
            chunk_scores.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        return sorted_results[:top_k]

    def _match_entities(self, query: str) -> list[str]:
        """Match query tokens against entity catalog.

        Uses multi-word matching: tries progressively shorter n-grams
        (3-word, 2-word, 1-word) to catch entities like "Николай Сенин"
        or "Сергей Хабаров".
        """
        query_lower = query.lower()
        words = re.findall(r"\w+", query_lower)
        matched: list[str] = []
        used_positions: set[int] = set()

        # Try n-grams from longest to shortest
        for n in range(min(4, len(words)), 0, -1):
            for i in range(len(words) - n + 1):
                if any(pos in used_positions for pos in range(i, i + n)):
                    continue
                phrase = " ".join(words[i : i + n])
                if phrase in self._entity_catalog:
                    matched.append(self._entity_catalog[phrase])
                    used_positions.update(range(i, i + n))

        return matched
