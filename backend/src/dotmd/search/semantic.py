"""Semantic (dense vector) search engine for dotMD.

Uses either a local ``SentenceTransformer`` model or a remote
TEI-compatible HTTP endpoint to encode queries into dense vectors,
then delegates similarity search to a
:class:`~dotmd.storage.base.VectorStoreProtocol` backend.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

from dotmd.storage.base import VectorStoreProtocol

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class SemanticSearchEngine:
    """Dense-vector search engine backed by embeddings.

    Supports two backends selected at construction time:

    * **Local** (default) — loads a ``SentenceTransformer`` model in-process.
    * **Remote** — calls a `TEI-compatible
      <https://github.com/huggingface/text-embeddings-inference>`_ HTTP
      endpoint when *embedding_url* is provided.

    The underlying model / HTTP client is **lazy-initialised** on the
    first call to :meth:`encode`, :meth:`encode_batch`, or :meth:`search`.

    Parameters
    ----------
    vector_store:
        A vector store that satisfies :class:`VectorStoreProtocol`.
    model_name:
        HuggingFace model identifier (local backend only).
    embedding_url:
        Base URL of a TEI server (e.g. ``http://embeddings:8088``).
        When set, *model_name* is ignored and all encoding is done
        via HTTP POST to ``{embedding_url}/embed``.
    """

    def __init__(
        self,
        vector_store: VectorStoreProtocol,
        model_name: str = _DEFAULT_MODEL,
        score_floor: float = 0.0,
        embedding_url: str | None = None,
    ) -> None:
        self._vector_store = vector_store
        self._model_name = model_name
        self._model: SentenceTransformer | None = None
        self._score_floor = score_floor
        self._embedding_url = embedding_url.rstrip("/") if embedding_url else None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_model(self) -> SentenceTransformer:
        if self._model is None:
            logger.info("Loading SentenceTransformer model: %s", self._model_name)
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        return self._model

    def _encode_via_tei(self, inputs: str | list[str]) -> list[list[float]]:
        """Call a TEI-compatible ``/embed`` endpoint.

        Batches are sent in chunks of ``_TEI_BATCH_SIZE`` to avoid
        413 Payload Too Large errors from the embedding server.
        """
        import httpx

        if isinstance(inputs, str):
            inputs = [inputs]

        results: list[list[float]] = []
        total_batches = (len(inputs) + self._TEI_BATCH_SIZE - 1) // self._TEI_BATCH_SIZE
        for batch_idx, i in enumerate(range(0, len(inputs), self._TEI_BATCH_SIZE)):
            batch = inputs[i : i + self._TEI_BATCH_SIZE]
            logger.info("TEI batch %d/%d (%d texts)", batch_idx + 1, total_batches, len(batch))
            response = httpx.post(
                f"{self._embedding_url}/embed",
                json={"inputs": batch, "truncate": True},
                timeout=120.0,
            )
            response.raise_for_status()
            results.extend(response.json())
        logger.info("TEI embedding complete: %d vectors", len(results))
        return results

    _TEI_BATCH_SIZE = 4

    @property
    def uses_remote_embeddings(self) -> bool:
        """Whether this engine delegates to a remote embedding service."""
        return self._embedding_url is not None

    def warmup(self) -> None:
        """Pre-load the embedding model (no-op when using a remote server)."""
        if not self._embedding_url:
            self._load_model()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def encode(self, text: str) -> list[float]:
        """Encode a single text string into a dense vector."""
        if self._embedding_url:
            return self._encode_via_tei(text)[0]
        model = self._load_model()
        embedding = model.encode(text, show_progress_bar=False)
        return embedding.tolist()  # type: ignore[union-attr]

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode a batch of texts into dense vectors."""
        if not texts:
            return []
        if self._embedding_url:
            return self._encode_via_tei(texts)
        model = self._load_model()
        embeddings = model.encode(texts, show_progress_bar=False)
        return [e.tolist() for e in embeddings]  # type: ignore[union-attr]

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Encode *query* and return the most similar chunks."""
        query_embedding = self.encode(query)
        results = self._vector_store.search(query_embedding, top_k=top_k)
        if self._score_floor > 0.0:
            results = [(cid, s) for cid, s in results if s >= self._score_floor]
        return results
