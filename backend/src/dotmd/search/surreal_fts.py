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
        except (RuntimeError, SurrealError, TypeError, ValueError, AttributeError) as exc:
            logger.warning(
                "Surreal keyword search failed: query_len=%d error_type=%s",
                len(query),
                type(exc).__name__,
            )
            return []

        return _rows_to_ranked_pairs(rows)[:top_k]

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
        variables["title_boost"] = self._search_config.title_boost
        variables["text_boost"] = self._search_config.text_boost

        if self._search_config.explain:
            self._connection.query(f"EXPLAIN FULL {statement}", variables)

        return self._connection.query(statement, variables)


def _build_fulltext_statement(
    *,
    timeout_seconds: int,
) -> str:
    return (
        "SELECT chunk_id, "
        f"(search::score({_TITLE_REF}) * $title_boost) + "
        f"(search::score({_TEXT_REF}) * $text_boost) AS score "
        f"FROM {_CHUNK_TABLE} WITH INDEX {_TITLE_INDEX}, {_TEXT_INDEX} "
        f"WHERE chunk_strategy = $chunk_strategy "
        f"AND (title @{_TITLE_REF}@ $query OR text @{_TEXT_REF}@ $query) "
        f"ORDER BY score DESC, chunk_id ASC LIMIT $limit TIMEOUT {timeout_seconds}s;"
    )


def _rows_to_ranked_pairs(rows: Any) -> list[tuple[str, float]]:
    ranked: list[tuple[str, float]] = []
    for row in _iter_result_rows(rows):
        if not isinstance(row, dict):
            continue
        chunk_id = row.get("chunk_id")
        score = row.get("score", row.get("ft_score"))
        if not isinstance(chunk_id, str) or not isinstance(score, (int, float)):
            continue
        ranked.append((chunk_id, float(score)))
    ranked.sort(key=lambda item: (-item[1], item[0]))
    return ranked


def _iter_result_rows(rows: Any) -> list[Any]:
    if isinstance(rows, dict):
        return [rows]
    if not isinstance(rows, list):
        return []

    flattened: list[Any] = []
    for row in rows:
        if isinstance(row, list):
            flattened.extend(row)
        else:
            flattened.append(row)
    return flattened
