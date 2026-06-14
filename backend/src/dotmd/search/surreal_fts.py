"""SurrealDB-native weighted full-text search."""

from __future__ import annotations

import logging
import re
from typing import Any, Protocol

from surrealdb import SurrealError

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"\w+", flags=re.UNICODE)


class _SurrealQueryConnection(Protocol):
    def query(
        self,
        statement: str,
        variables: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...


def _sanitize_surreal_fts_query(query: str) -> str:
    return " ".join(_WORD_RE.findall(query))


class SurrealFTSSearchEngine:
    """Weighted BM25 search backed by Surreal full-text indexes."""

    def __init__(
        self,
        connection: _SurrealQueryConnection,
        *,
        chunk_strategy: str = "contextual_512_50",
        title_weight: float = 5.0,
        tags_weight: float = 3.0,
        text_weight: float = 1.0,
    ) -> None:
        self._connection = connection
        self._chunk_strategy = chunk_strategy
        self._statement = self._build_statement(
            title_weight=title_weight,
            tags_weight=tags_weight,
            text_weight=text_weight,
        )

    @staticmethod
    def _build_statement(
        *,
        title_weight: float,
        tags_weight: float,
        text_weight: float,
    ) -> str:
        return f"""
SELECT chunk_id,
    -(
        ({title_weight:g} * search::score(1)) +
        ({tags_weight:g} * search::score(2)) +
        ({text_weight:g} * search::score(3))
    ) AS score
FROM chunks
WHERE chunk_strategy = $chunk_strategy
  AND (
      title @1@ $query
      OR tags_text @2@ $query
      OR text @3@ $query
  )
ORDER BY score DESC, chunk_id ASC
LIMIT $limit;
""".strip()

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        sanitized = _sanitize_surreal_fts_query(query)
        if not sanitized:
            return []

        try:
            rows = self._connection.query(
                self._statement,
                {
                    "query": sanitized,
                    "chunk_strategy": self._chunk_strategy,
                    "limit": top_k,
                },
            )
        except (RuntimeError, SurrealError) as exc:
            logger.warning(
                "Surreal FTS search failed: query_len=%d error_type=%s",
                len(query),
                type(exc).__name__,
            )
            return []

        results: list[tuple[str, float]] = []
        for row in rows:
            chunk_id = row.get("chunk_id")
            score = row.get("score")
            if chunk_id in (None, "") or score is None:
                continue
            try:
                results.append((str(chunk_id), float(score)))
            except (TypeError, ValueError):
                continue
        return results
