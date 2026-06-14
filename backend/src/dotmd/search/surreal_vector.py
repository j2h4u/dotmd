"""SurrealDB-native HNSW vector search."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from dotmd.search.semantic import SemanticSearchEngine
from dotmd.storage.surreal_schema import (
    DEFAULT_HNSW_EF,
    validate_surreal_native_retrieval_contract,
)

if TYPE_CHECKING:
    from dotmd.core.models import Chunk
    from dotmd.storage.surreal import SurrealConnection

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_PRECONDITION_STATEMENT = """
SELECT embedding_model, array::len(embedding) AS embedding_dimension
FROM embeddings;
""".strip()


class _UnusedVectorStore:
    def add_chunks(
        self,
        chunks: list[Chunk],
        embeddings: list[list[float]],
        *,
        overwrite: bool = True,
        text_hashes: dict[str, str] | None = None,
    ) -> None:
        raise NotImplementedError("SurrealVectorSearchEngine does not write through VectorStore")

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
    ) -> list[tuple[str, float]]:
        raise AssertionError("SurrealVectorSearchEngine overrides search()")

    def delete_all(self) -> None:
        raise NotImplementedError

    def delete_vectors_by_chunk_ids(self, chunk_ids: list[str]) -> int:
        raise NotImplementedError

    def count(self) -> int:
        raise NotImplementedError


class SurrealVectorSearchEngine(SemanticSearchEngine):
    """HNSW-backed vector retrieval over Surreal embeddings."""

    def __init__(
        self,
        connection: SurrealConnection,
        *,
        model_name: str = _DEFAULT_MODEL,
        embedding_dimension: int,
        score_floor: float = 0.0,
        embedding_url: str | None = None,
        tei_batch_size: int = 32,
        use_prefix: bool = True,
        query_instruction: str = "",
        hnsw_ef: int = DEFAULT_HNSW_EF,
    ) -> None:
        super().__init__(
            _UnusedVectorStore(),
            model_name=model_name,
            score_floor=score_floor,
            embedding_url=embedding_url,
            tei_batch_size=tei_batch_size,
            use_prefix=use_prefix,
            query_instruction=query_instruction,
        )
        self._connection = connection
        self._embedding_dimension = embedding_dimension
        self._hnsw_ef = hnsw_ef
        self._preconditions_valid: bool | None = None

    def _placeholder_validation_rows(self) -> list[dict[str, object]]:
        return [
            {
                "embedding_model": self._model_name,
                "embedding": [0.0] * self._embedding_dimension,
            }
        ]

    def _validate_request_bounds(self, top_k: int) -> None:
        validate_surreal_native_retrieval_contract(
            embedding_dimension=self._embedding_dimension,
            embedding_rows=self._placeholder_validation_rows(),
            top_k=top_k,
            hnsw_ef=self._hnsw_ef,
        )

    def _load_precondition_rows(self) -> list[dict[str, object]]:
        rows = self._connection.query(_PRECONDITION_STATEMENT)
        validation_rows: list[dict[str, object]] = []
        for row in rows:
            embedding_model = row.get("embedding_model")
            if embedding_model in (None, ""):
                continue
            raw_dimension = row.get("embedding_dimension")
            if raw_dimension in (None, 0):
                vector: list[float] = []
            else:
                vector = [0.0] * int(raw_dimension)
            validation_rows.append(
                {
                    "embedding_model": str(embedding_model),
                    "embedding": vector,
                }
            )
        return validation_rows

    def _ensure_retrieval_preconditions(self) -> bool:
        if self._preconditions_valid is not None:
            return self._preconditions_valid

        try:
            validate_surreal_native_retrieval_contract(
                embedding_dimension=self._embedding_dimension,
                embedding_rows=self._load_precondition_rows(),
                top_k=1,
                hnsw_ef=self._hnsw_ef,
            )
        except ValueError as exc:
            logger.warning(
                "Surreal vector retrieval precondition failed: error_type=%s detail=%s",
                type(exc).__name__,
                exc,
            )
            self._preconditions_valid = False
            return False
        except Exception as exc:
            logger.warning(
                "Surreal vector retrieval precondition query failed: error_type=%s",
                type(exc).__name__,
            )
            self._preconditions_valid = False
            return False

        self._preconditions_valid = True
        return True

    def _normalize_query_text(self, query: str) -> str:
        if self._query_instruction:
            return f"{self._query_instruction}\nQuery: {query}"
        if self._use_prefix:
            return f"query: {query}"
        return query

    def _build_search_statement(self, top_k: int) -> str:
        return f"""
SELECT chunk_id,
    vector::similarity::cosine(embedding, $qvec) AS score
FROM embeddings
WHERE embedding_model = $embedding_model
  AND embedding <|{top_k},{self._hnsw_ef}|> $qvec
ORDER BY score DESC, chunk_id ASC
LIMIT $limit;
""".strip()

    @staticmethod
    def _normalize_results(rows: list[dict[str, Any]]) -> list[tuple[str, float]]:
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

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        if not query.strip():
            return []

        self._validate_request_bounds(top_k)
        if not self._ensure_retrieval_preconditions():
            return []

        encoded_query = self._normalize_query_text(query)
        query_embedding = self.encode(encoded_query)

        try:
            rows = self._connection.query(
                self._build_search_statement(top_k),
                {
                    "embedding_model": self._model_name,
                    "qvec": query_embedding,
                    "limit": top_k,
                },
            )
        except Exception as exc:
            logger.warning(
                "Surreal vector search failed: query_len=%d error_type=%s",
                len(query),
                type(exc).__name__,
            )
            return []

        results = self._normalize_results(rows)
        if not results:
            return []
        if self._score_floor > 0.0:
            top_score = results[0][1]
            threshold = top_score * self._score_floor
            results = [(chunk_id, score) for chunk_id, score in results if score >= threshold]
        return results
