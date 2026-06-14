"""SurrealDB-native graph/entity retrieval."""

from __future__ import annotations

import logging
import math
import re
from typing import Any, Protocol

from surrealdb import SurrealError

logger = logging.getLogger(__name__)

_ENTITY_CATALOG_STATEMENT = """
SELECT name
FROM entities
ORDER BY name ASC
LIMIT $limit;
""".strip()

_DEFAULT_ALLOWED_REL_TYPES = ("MENTIONS", "HAS_TAG")
_DEFAULT_CATALOG_LIMIT = 100_000


class _SurrealQueryConnection(Protocol):
    def query(
        self,
        statement: str,
        variables: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...


class SurrealGraphDirectEngine:
    """Entity-direct graph retrieval backed by Surreal relation records."""

    def __init__(
        self,
        connection: _SurrealQueryConnection,
        *,
        allowed_rel_types: tuple[str, ...] = _DEFAULT_ALLOWED_REL_TYPES,
        catalog_limit: int = _DEFAULT_CATALOG_LIMIT,
    ) -> None:
        self._connection = connection
        self._allowed_rel_types = tuple(allowed_rel_types)
        self._catalog_limit = catalog_limit
        self._entity_catalog: dict[str, str] = {}
        self._loaded = False
        self._relation_statement = self._build_relation_statement()

    @staticmethod
    def _build_relation_statement() -> str:
        return """
SELECT source_id, target_id, rel_type, weight, properties, metadata, `in`, out
FROM relations
WHERE source_table = 'sections'
  AND target_id IN $entity_names
  AND rel_type IN $allowed_rel_types
ORDER BY weight DESC, source_id ASC, target_id ASC
LIMIT $limit;
""".strip()

    def load_catalog(self) -> None:
        try:
            rows = self._connection.query(
                _ENTITY_CATALOG_STATEMENT,
                {"limit": self._catalog_limit},
            )
        except (RuntimeError, SurrealError) as exc:
            logger.warning(
                "Surreal graph entity catalog load failed: error_type=%s",
                type(exc).__name__,
            )
            self._entity_catalog = {}
            self._loaded = True
            return

        catalog: dict[str, str] = {}
        for row in rows:
            name = row.get("name")
            if name in (None, ""):
                continue
            catalog[str(name).lower()] = str(name)

        self._entity_catalog = catalog
        self._loaded = True
        logger.info("Graph entity catalog loaded: %d entities", len(self._entity_catalog))

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        if top_k <= 0:
            return []

        if not self._loaded:
            self.load_catalog()
        if not self._entity_catalog:
            return []

        matched_entities = self._match_entities(query)
        if not matched_entities:
            return []

        logger.debug("Surreal graph-direct: matched_entities=%d", len(matched_entities))

        try:
            rows = self._connection.query(
                self._relation_statement,
                {
                    "entity_names": matched_entities,
                    "allowed_rel_types": list(self._allowed_rel_types),
                    "limit": top_k,
                },
            )
        except (RuntimeError, SurrealError) as exc:
            logger.warning(
                "Surreal graph search failed: query_len=%d matched_entities=%d error_type=%s",
                len(query),
                len(matched_entities),
                type(exc).__name__,
            )
            return []

        chunk_scores: dict[str, float] = {}
        for row in rows:
            chunk_id = row.get("source_id")
            rel_type = row.get("rel_type")
            weight = row.get("weight")
            if chunk_id in (None, "") or rel_type not in self._allowed_rel_types or weight is None:
                continue
            try:
                numeric_weight = float(weight)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(numeric_weight):
                continue
            chunk_scores[str(chunk_id)] = chunk_scores.get(str(chunk_id), 0.0) + numeric_weight

        if not chunk_scores:
            return []

        max_score = max(chunk_scores.values())
        if max_score <= 0.0:
            return []

        normalized = [(chunk_id, score / max_score) for chunk_id, score in chunk_scores.items()]
        normalized.sort(key=lambda item: (-item[1], item[0]))
        return normalized[:top_k]

    def _match_entities(self, query: str) -> list[str]:
        query_lower = query.lower()
        words = re.findall(r"\w+", query_lower)
        matched: list[str] = []
        used_positions: set[int] = set()

        for n in range(min(4, len(words)), 0, -1):
            for i in range(len(words) - n + 1):
                if any(position in used_positions for position in range(i, i + n)):
                    continue
                phrase = " ".join(words[i : i + n])
                if phrase in self._entity_catalog:
                    matched.append(self._entity_catalog[phrase])
                    used_positions.update(range(i, i + n))

        return matched
