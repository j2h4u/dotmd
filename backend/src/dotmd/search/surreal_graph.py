"""SurrealDB-native graph/entity retrieval."""

from __future__ import annotations

import json
import logging
import math
import os
import re
from datetime import UTC, datetime
from pathlib import Path
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
_RELATION_CANDIDATE_MULTIPLIER = 25

_VALID_CHUNKS_STATEMENT = """
SELECT chunk_id
FROM chunks
WHERE chunk_strategy = $chunk_strategy
  AND chunk_id IN $source_ids
LIMIT $limit;
""".strip()


def _write_graph_progress(suffix: str, status: str, error: str | None = None) -> None:
    progress_path = os.environ.get("DOTMD_SEARCH_PROGRESS_PATH", "").strip()
    progress_prefix = os.environ.get("DOTMD_SEARCH_PROGRESS_PREFIX", "").strip()
    if not progress_path or not progress_prefix:
        return
    payload = {
        "schema_version": "dotmd-search-progress-v1",
        "step": f"{progress_prefix}:{suffix}",
        "status": status,
        "error": error,
        "updated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    path = Path(progress_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


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
        chunk_strategy: str = "contextual_512_50",
        allowed_rel_types: tuple[str, ...] = _DEFAULT_ALLOWED_REL_TYPES,
        catalog_limit: int = _DEFAULT_CATALOG_LIMIT,
    ) -> None:
        self._connection = connection
        self._chunk_strategy = chunk_strategy
        self._allowed_rel_types = tuple(allowed_rel_types)
        self._catalog_limit = catalog_limit
        self._entity_catalog: dict[str, str] = {}
        self._loaded = False
        self._relation_statement = self._build_relation_statement()

    @staticmethod
    def _build_relation_statement() -> str:
        return """
SELECT source_id, math::sum(weight) AS total_weight
FROM relations
WHERE source_table = 'sections'
  AND target_id IN $entity_names
  AND rel_type IN $allowed_rel_types
GROUP BY source_id
ORDER BY total_weight DESC, source_id ASC
LIMIT $limit;
""".strip()

    def load_catalog(self) -> None:
        _write_graph_progress("catalog", "running")
        try:
            rows = self._connection.query(
                _ENTITY_CATALOG_STATEMENT,
                {"limit": self._catalog_limit},
            )
        except (RuntimeError, SurrealError) as exc:
            _write_graph_progress("catalog", "failed", str(exc))
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
        _write_graph_progress("catalog", "applied")
        logger.info("Graph entity catalog loaded: %d entities", len(self._entity_catalog))

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        if top_k <= 0:
            return []

        if not self._loaded:
            self.load_catalog()
        if not self._entity_catalog:
            return []

        _write_graph_progress("match_entities", "running")
        matched_entities = self._match_entities(query)
        _write_graph_progress("match_entities", "applied")
        if not matched_entities:
            return []

        logger.debug("Surreal graph-direct: matched_entities=%d", len(matched_entities))

        try:
            _write_graph_progress("relations", "running")
            rows = self._connection.query(
                self._relation_statement,
                {
                    "entity_names": matched_entities,
                    "allowed_rel_types": list(self._allowed_rel_types),
                    "limit": self._relation_candidate_limit(top_k),
                },
            )
            _write_graph_progress("relations", "applied")
        except (RuntimeError, SurrealError) as exc:
            _write_graph_progress("relations", "failed", str(exc))
            logger.warning(
                "Surreal graph search failed: query_len=%d matched_entities=%d error_type=%s",
                len(query),
                len(matched_entities),
                type(exc).__name__,
            )
            return []

        valid_source_ids = self._load_valid_source_ids(rows)
        if not valid_source_ids:
            return []

        chunk_scores: dict[str, float] = {}
        for row in rows:
            chunk_id = row.get("source_id")
            rel_type = row.get("rel_type")
            weight = row.get("total_weight", row.get("weight"))
            if chunk_id in (None, "") or weight is None:
                continue
            if str(chunk_id) not in valid_source_ids:
                continue
            if rel_type is not None and rel_type not in self._allowed_rel_types:
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

    @staticmethod
    def _relation_candidate_limit(top_k: int) -> int:
        return max(top_k, top_k * _RELATION_CANDIDATE_MULTIPLIER)

    def _load_valid_source_ids(self, relation_rows: list[dict[str, Any]]) -> set[str]:
        source_ids: list[str] = []
        seen: set[str] = set()
        for row in relation_rows:
            source_id = row.get("source_id")
            if source_id in (None, ""):
                continue
            source_id_text = str(source_id)
            if source_id_text in seen:
                continue
            seen.add(source_id_text)
            source_ids.append(source_id_text)
        if not source_ids:
            return set()

        try:
            _write_graph_progress("chunks", "running")
            rows = self._connection.query(
                _VALID_CHUNKS_STATEMENT,
                {
                    "chunk_strategy": self._chunk_strategy,
                    "source_ids": source_ids,
                    "limit": len(source_ids),
                },
            )
            _write_graph_progress("chunks", "applied")
        except (RuntimeError, SurrealError) as exc:
            _write_graph_progress("chunks", "failed", str(exc))
            logger.warning(
                "Surreal graph active chunk validation failed: source_ids=%d error_type=%s",
                len(source_ids),
                type(exc).__name__,
            )
            return set()

        valid_source_ids: set[str] = set()
        for row in rows:
            chunk_id = row.get("chunk_id")
            if chunk_id in (None, ""):
                continue
            valid_source_ids.add(str(chunk_id))
        return valid_source_ids

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
