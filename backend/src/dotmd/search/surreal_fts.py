"""Read-only SurrealDB full-text keyword search for dotMD standalone."""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Protocol

from surrealdb import SurrealError

logger = logging.getLogger(__name__)

_CHUNK_TABLE = "chunks"
_TITLE_INDEX = "chunks_title_fts"
_TEXT_INDEX = "chunks_text_fts"
_TITLE_REF = 0
_TEXT_REF = 1

_QUERY_CLEAN_RE = re.compile(r"[^\w\s'\-]+", re.UNICODE)
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")


def _sanitize_keyword_query(query: str) -> str:
    """Normalize a keyword query for safe SurrealQL full-text use."""
    normalized = unicodedata.normalize("NFKC", query)
    normalized = _CONTROL_RE.sub(" ", normalized)
    normalized = _QUERY_CLEAN_RE.sub(" ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


@dataclass(frozen=True, slots=True)
class SurrealFTSConfig:
    """Configuration for the standalone SurrealDB keyword search adapter."""

    query_timeout_seconds: int = 5
    max_query_timeout_seconds: int = 30
    title_boost: float = 5.0
    text_boost: float = 1.0
    explain: bool = False

    def __post_init__(self) -> None:
        if self.query_timeout_seconds <= 0:
            raise ValueError("query_timeout_seconds must be positive")
        if self.max_query_timeout_seconds <= 0:
            raise ValueError("max_query_timeout_seconds must be positive")
        if self.title_boost <= 0:
            raise ValueError("title_boost must be positive")
        if self.text_boost <= 0:
            raise ValueError("text_boost must be positive")

    def bounded_timeout_seconds(self) -> int:
        return max(1, min(self.query_timeout_seconds, self.max_query_timeout_seconds))


class _SurrealQueryConnection(Protocol):
    def query(
        self,
        statement: str,
        variables: dict[str, Any] | None = None,
    ) -> list[Any]: ...

    def query_raw(
        self,
        statement: str,
        variables: dict[str, Any] | None = None,
    ) -> Any: ...


class SurrealFTSSearchEngine:
    """Read-only SurrealDB keyword engine using title and text full-text indexes."""

    def __init__(
        self,
        connection: _SurrealQueryConnection,
        *,
        chunk_strategy: str = "contextual_512_50",
        search_config: SurrealFTSConfig | None = None,
    ) -> None:
        self._connection = connection
        self._chunk_strategy = chunk_strategy
        self._search_config = search_config or SurrealFTSConfig()

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        if top_k <= 0:
            return []

        sanitized = _sanitize_keyword_query(query)
        if not sanitized:
            return []

        try:
            rows = self._run_query(query=sanitized, top_k=top_k)
        except (RuntimeError, SurrealError, TypeError, ValueError) as exc:
            logger.warning(
                "Surreal keyword search failed: query_len=%d error_type=%s",
                len(query),
                type(exc).__name__,
            )
            return []

        return _rows_to_ranked_pairs(
            rows,
            title_boost=self._search_config.title_boost,
            text_boost=self._search_config.text_boost,
        )[:top_k]

    def _run_query(
        self,
        *,
        query: str,
        top_k: int,
    ) -> Any:
        statement = _build_fulltext_statement(
            timeout_seconds=self._search_config.bounded_timeout_seconds(),
        )
        variables = {"query": query, "limit": top_k, "chunk_strategy": self._chunk_strategy}

        if self._search_config.explain:
            self._connection.query(f"EXPLAIN FULL {statement}", variables)

        return self._connection.query_raw(statement, variables)


def _build_fulltext_statement(
    *,
    timeout_seconds: int,
) -> str:
    return (
        "SELECT chunk_id, search::score(0) AS score "
        f"FROM {_CHUNK_TABLE} WITH INDEX {_TITLE_INDEX} "
        f"WHERE chunk_strategy = $chunk_strategy "
        f"AND title @{_TITLE_REF}@ $query "
        f"ORDER BY score DESC LIMIT $limit TIMEOUT {timeout_seconds}s; "
        "SELECT chunk_id, search::score(1) AS score "
        f"FROM {_CHUNK_TABLE} WITH INDEX {_TEXT_INDEX} "
        f"WHERE chunk_strategy = $chunk_strategy "
        f"AND text @{_TEXT_REF}@ $query "
        f"ORDER BY score DESC LIMIT $limit TIMEOUT {timeout_seconds}s;"
    )


def _rows_to_ranked_pairs(
    rows: Any,
    *,
    title_boost: float,
    text_boost: float,
) -> list[tuple[str, float]]:
    ranked_scores: dict[str, float] = {}
    result_sets = _iter_result_sets(rows)
    weighted_boosts = (title_boost, text_boost)
    for result_index, result_rows in enumerate(result_sets):
        boost = weighted_boosts[result_index] if result_index < len(weighted_boosts) else 1.0
        for row in result_rows:
            if not isinstance(row, dict):
                continue
            chunk_id = row.get("chunk_id")
            score = row.get("score", row.get("ft_score"))
            if not isinstance(chunk_id, str) or not isinstance(score, (int, float)):
                continue
            ranked_scores[chunk_id] = ranked_scores.get(chunk_id, 0.0) + (float(score) * boost)
    ranked = list(ranked_scores.items())
    ranked.sort(key=lambda item: (-item[1], item[0]))
    return ranked


def _iter_result_sets(rows: Any) -> list[list[Any]]:
    if isinstance(rows, dict):
        if "result" in rows:
            return _iter_result_sets(rows["result"])
        return [[rows]]
    if not isinstance(rows, list):
        return []

    if not rows:
        return []

    if all(not isinstance(row, dict) or "result" not in row for row in rows):
        return [rows]

    result_sets: list[list[Any]] = []
    for row in rows:
        if isinstance(row, dict) and "result" in row:
            nested_rows = row["result"]
            if isinstance(nested_rows, list):
                result_sets.append(nested_rows)
            elif nested_rows is None:
                result_sets.append([])
            else:
                result_sets.append([nested_rows])
        elif isinstance(row, list):
            result_sets.append(row)
    return result_sets
