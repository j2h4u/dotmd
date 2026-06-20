"""SurrealDB-native HNSW vector search."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from surrealdb import SurrealError

from dotmd.search.semantic import SemanticSearchEngine
from dotmd.storage.surreal_schema import (
    DEFAULT_EMBEDDING_SHARD_COUNT,
    DEFAULT_HNSW_EF,
    MAX_TOP_K,
    MIN_TOP_K,
    surreal_embedding_shard_tables,
    validate_surreal_native_retrieval_contract,
)

if TYPE_CHECKING:
    from dotmd.core.models import Chunk

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_MAX_HNSW_RESULTS_PER_SHARD = 20
_PRECONDITION_STATEMENT = """
SELECT embedding_model, array::len(vector) AS embedding_dimension
FROM {table_name}
WHERE chunk_strategy = $chunk_strategy
  AND embedding_model = $embedding_model
LIMIT 25;
""".strip()


def _write_vector_progress(suffix: str, status: str, error: str | None = None) -> None:
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
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class _SurrealQueryConnection(Protocol):
    def query(
        self,
        statement: str,
        variables: dict[str, Any] | None = None,
    ) -> list[Any]: ...


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

    def lookup_embeddings_by_text_hash(self, text_hashes: list[str]) -> dict[str, list[float]]:
        raise NotImplementedError

    def count(self) -> int:
        raise NotImplementedError


class SurrealVectorSearchEngine(SemanticSearchEngine):
    """HNSW-backed vector retrieval over Surreal embeddings."""

    def __init__(
        self,
        connection: _SurrealQueryConnection,
        *,
        model_name: str = _DEFAULT_MODEL,
        chunk_strategy: str = "contextual_512_50",
        embedding_dimension: int,
        score_floor: float = 0.0,
        embedding_url: str | None = None,
        tei_batch_size: int = 32,
        use_prefix: bool = True,
        query_instruction: str = "",
        hnsw_ef: int = DEFAULT_HNSW_EF,
        embedding_shard_count: int = DEFAULT_EMBEDDING_SHARD_COUNT,
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
        self._chunk_strategy = chunk_strategy
        self._embedding_dimension = embedding_dimension
        self._hnsw_ef = hnsw_ef
        self._embedding_tables = surreal_embedding_shard_tables(embedding_shard_count)
        self._preconditions_valid: bool | None = None

    def _placeholder_validation_rows(self) -> list[dict[str, object]]:
        return [
            {
                "embedding_model": self._model_name,
                "vector": [0.0] * self._embedding_dimension,
            }
        ]

    def _validate_request_bounds(self, top_k: int) -> None:
        if top_k < MIN_TOP_K or top_k > MAX_TOP_K:
            raise ValueError(f"top_k must be between {MIN_TOP_K} and {MAX_TOP_K}, inclusive")
        validate_surreal_native_retrieval_contract(
            embedding_dimension=self._embedding_dimension,
            embedding_rows=self._placeholder_validation_rows(),
            top_k=min(top_k, _MAX_HNSW_RESULTS_PER_SHARD),
            hnsw_ef=self._hnsw_ef,
        )

    def _load_precondition_rows(self) -> list[dict[str, object]]:
        rows: list[Any] = []
        for table_name in self._embedding_tables:
            rows.extend(
                self._connection.query(
                    _PRECONDITION_STATEMENT.format(table_name=table_name),
                    {
                        "chunk_strategy": self._chunk_strategy,
                        "embedding_model": self._model_name,
                    },
                )
            )
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
                    "vector": vector,
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
        except (RuntimeError, SurrealError) as exc:
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

    def _build_search_statement(self, *, table_name: str, top_k: int) -> str:
        shard_top_k = min(top_k, _MAX_HNSW_RESULTS_PER_SHARD)
        return f"""
SELECT chunk_id, score
FROM (
    SELECT chunk_id,
        chunk_strategy,
        embedding_model,
        vector::similarity::cosine(vector, $qvec) AS score
    FROM {table_name}
    WHERE vector <|{shard_top_k},{self._hnsw_ef}|> $qvec
)
WHERE embedding_model = $embedding_model
  AND chunk_strategy = $chunk_strategy
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

        _write_vector_progress("bounds", "running")
        self._validate_request_bounds(top_k)
        _write_vector_progress("bounds", "applied")
        _write_vector_progress("preconditions", "running")
        if not self._ensure_retrieval_preconditions():
            _write_vector_progress("preconditions", "failed", "retrieval preconditions failed")
            return []
        _write_vector_progress("preconditions", "applied")

        encoded_query = self._normalize_query_text(query)
        _write_vector_progress("encode", "running")
        query_embedding = self.encode(encoded_query)
        _write_vector_progress("encode", "applied")

        try:
            rows = []
            for table_name in self._embedding_tables:
                _write_vector_progress(f"query:{table_name}", "running")
                rows.extend(
                    self._connection.query(
                        self._build_search_statement(table_name=table_name, top_k=top_k),
                        {
                            "embedding_model": self._model_name,
                            "chunk_strategy": self._chunk_strategy,
                            "qvec": query_embedding,
                            "limit": top_k,
                        },
                    )
                )
                _write_vector_progress(f"query:{table_name}", "applied")
        except (RuntimeError, SurrealError) as exc:
            _write_vector_progress("query", "failed", str(exc))
            logger.warning(
                "Surreal vector search failed: query_len=%d error_type=%s",
                len(query),
                type(exc).__name__,
            )
            return []

        results = sorted(
            self._normalize_results(rows),
            key=lambda item: (-item[1], item[0]),
        )[:top_k]
        if not results:
            return []
        if self._score_floor > 0.0:
            top_score = results[0][1]
            threshold = top_score * self._score_floor
            results = [(chunk_id, score) for chunk_id, score in results if score >= threshold]
        return results
