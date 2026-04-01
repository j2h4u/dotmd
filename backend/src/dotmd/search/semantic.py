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
        tei_batch_size: int = 32,
        use_prefix: bool = True,
        query_instruction: str = "",
    ) -> None:
        self._vector_store = vector_store
        self._model_name = model_name
        self._model: SentenceTransformer | None = None
        self._score_floor = score_floor
        self._embedding_url = embedding_url.rstrip("/") if embedding_url else None
        self._tei_batch_size = tei_batch_size
        self._tei_bs_probed = False
        self._tei_model_id: str | None = None
        self._use_prefix = use_prefix
        self._query_instruction = query_instruction

    def get_tei_model_id(self) -> str | None:
        """Return the actual embedding model name.

        When TEI is configured, queries /info for the real model_id
        (the config value is irrelevant — TEI decides which model to load).
        When running locally, returns the configured model_name.
        """
        if self._tei_model_id:
            return self._tei_model_id
        if not self._embedding_url:
            return self._model_name  # local model, trust config
        try:
            resp = httpx.get(f"{self._embedding_url}/info", timeout=5.0)
            resp.raise_for_status()
            self._tei_model_id = resp.json().get("model_id")
            return self._tei_model_id
        except Exception:
            logger.debug("Could not query TEI /info", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_model(self) -> SentenceTransformer:
        if self._model is None:
            logger.info("Loading SentenceTransformer model: %s", self._model_name)
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        return self._model

    def _probe_tei_batch_size(self, sample_text: str) -> int:
        """Find the largest batch size TEI accepts without 413."""
        import httpx

        bs = self._tei_batch_size
        while bs > 1:
            try:
                resp = httpx.post(
                    f"{self._embedding_url}/embed",
                    json={"inputs": [sample_text] * bs, "truncate": True},
                    timeout=120.0,
                )
                resp.raise_for_status()
                logger.info("TEI batch size probe: bs=%d OK", bs)
                return bs
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 413:
                    bs //= 2
                    logger.info("TEI batch size probe: 413, trying bs=%d", bs)
                    continue
                raise
        return 1

    def _encode_via_tei(self, inputs: str | list[str]) -> list[list[float]]:
        """Call a TEI-compatible ``/embed`` endpoint.

        Probes the max batch size on first call, then uses it for all
        subsequent batches.
        """
        import httpx

        if isinstance(inputs, str):
            inputs = [inputs]

        if not self._tei_bs_probed:
            self._tei_batch_size = self._probe_tei_batch_size(inputs[0])
            self._tei_bs_probed = True

        results: list[list[float]] = []
        bs = self._tei_batch_size
        total_batches = (len(inputs) + bs - 1) // bs
        for batch_idx, i in enumerate(range(0, len(inputs), bs)):
            batch = inputs[i : i + bs]
            if batch_idx % 200 == 0 or batch_idx == total_batches - 1:
                logger.info("TEI batch %d/%d (%d texts, bs=%d)", batch_idx + 1, total_batches, len(batch), bs)
            response = httpx.post(
                f"{self._embedding_url}/embed",
                json={"inputs": batch, "truncate": True},
                timeout=600.0,
            )
            response.raise_for_status()
            results.extend(response.json())
        logger.info("TEI embedding complete: %d vectors (bs=%d)", len(results), bs)
        return results

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
        """Encode a batch of document passages into dense vectors.

        Adds the ``"passage: "`` prefix required by E5-family models
        when ``use_prefix`` is True.  pplx-embed models need no prefix.
        """
        if not texts:
            return []
        if self._use_prefix:
            texts = [f"passage: {t}" for t in texts]
        if self._embedding_url:
            return self._encode_via_tei(texts)
        model = self._load_model()
        embeddings = model.encode(texts, show_progress_bar=False)
        return [e.tolist() for e in embeddings]  # type: ignore[union-attr]

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Encode *query* and return the most similar chunks."""
        if self._query_instruction:
            encoded_query = f"{self._query_instruction}\nQuery: {query}"
        elif self._use_prefix:
            encoded_query = f"query: {query}"
        else:
            encoded_query = query
        query_embedding = self.encode(encoded_query)
        results = self._vector_store.search(query_embedding, top_k=top_k)
        if not results:
            return results
        # Relative threshold: keep results within score_floor ratio of the
        # best hit. Adapts automatically to any model's score distribution
        # (e.g., E5 scores cluster in 0.7–1.0, other models may differ).
        if self._score_floor > 0.0:
            top_score = results[0][1]  # results are sorted by descending score
            threshold = top_score * self._score_floor
            results = [(cid, s) for cid, s in results if s >= threshold]
        return results
