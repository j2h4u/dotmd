"""Semantic (dense vector) search engine for dotMD.

Uses either a local ``SentenceTransformer`` model or a remote
TEI-compatible HTTP endpoint to encode queries into dense vectors,
then delegates similarity search to a
:class:`~dotmd.storage.base.VectorStoreProtocol` backend.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any, cast

import httpx

from dotmd.storage.base import VectorStoreProtocol

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class EmbeddingEncoder:
    """Shared dense embedding encoder for local and TEI-backed callers.

    Callers format queries separately and then use :meth:`encode` or
    :meth:`encode_batch` to obtain vectors.  The helper hides local
    SentenceTransformer loading and TEI batch-size probing.
    """

    def __init__(
        self,
        *,
        model_name: str = _DEFAULT_MODEL,
        embedding_url: str | None = None,
        tei_batch_size: int = 32,
        use_prefix: bool = True,
        query_instruction: str = "",
    ) -> None:
        self._model_name = model_name
        self._model: Any | None = None
        self._embedding_url = embedding_url.rstrip("/") if embedding_url else None
        self._tei_batch_size = tei_batch_size
        self._tei_bs_probed = False
        self._tei_model_id: str | None = None
        self._use_prefix = use_prefix
        self._query_instruction = query_instruction

    def get_tei_model_id(self) -> str | None:
        """Return the actual embedding model name."""
        if self._tei_model_id:
            return self._tei_model_id
        if not self._embedding_url:
            return self._model_name
        try:
            resp = httpx.get(f"{self._embedding_url}/info", timeout=5.0)
            resp.raise_for_status()
            self._tei_model_id = resp.json().get("model_id")
            return self._tei_model_id
        except (httpx.HTTPError, ValueError):
            logger.debug("Could not query TEI /info", exc_info=True)
            return None

    def warmup(self) -> None:
        """Pre-load the embedding model (no-op when using a remote server)."""
        if not self._embedding_url:
            self._load_model()

    @property
    def uses_remote_embeddings(self) -> bool:
        """Whether this encoder delegates to a remote embedding service."""
        return self._embedding_url is not None

    def format_query(self, query: str) -> str:
        """Apply the query instruction or prefix expected by this encoder."""
        if self._query_instruction:
            return f"{self._query_instruction}\nQuery: {query}"
        if self._use_prefix:
            return f"query: {query}"
        return query

    def format_passages(self, texts: list[str]) -> list[str]:
        """Apply the passage prefix expected by E5-family encoders."""
        if not self._use_prefix:
            return texts
        return [f"passage: {text}" for text in texts]

    def encode(self, text: str) -> list[float]:
        """Encode one text string into a dense vector."""
        if self._embedding_url:
            return self._encode_remote([text])[0]
        return self._encode_local(text)

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode a batch of passage texts into dense vectors."""
        if not texts:
            return []
        prepared = self.format_passages(texts)
        if self._embedding_url:
            return self._encode_remote(prepared)
        return self._encode_local_batch(prepared)

    def _load_model(self) -> Any:
        if self._model is None:
            logger.info("Loading SentenceTransformer model: %s", self._model_name)
            sentence_transformers = cast(Any, importlib.import_module("sentence_transformers"))
            self._model = sentence_transformers.SentenceTransformer(self._model_name)
        return self._model

    def _encode_local(self, text: str) -> list[float]:
        model = self._load_model()
        embedding = model.encode(text, show_progress_bar=False)
        return embedding.tolist()  # type: ignore[union-attr]

    def _encode_local_batch(self, texts: list[str]) -> list[list[float]]:
        model = self._load_model()
        embeddings = model.encode(texts, show_progress_bar=False)
        return [embedding.tolist() for embedding in embeddings]  # type: ignore[union-attr]

    def _probe_tei_batch_size(self, sample_text: str) -> int:
        """Find the largest batch size TEI accepts without 413."""

        batch_size = self._tei_batch_size
        while batch_size > 1:
            if self._probe_tei_batch_size_once(sample_text, batch_size):
                logger.info("TEI batch size probe: bs=%d OK", batch_size)
                return batch_size
            batch_size //= 2
            logger.info("TEI batch size probe: 413, trying bs=%d", batch_size)
        return 1

    def _probe_tei_batch_size_once(self, sample_text: str, batch_size: int) -> bool:
        import httpx

        try:
            resp = httpx.post(
                f"{self._embedding_url}/embed",
                json={"inputs": [sample_text] * batch_size, "truncate": True},
                timeout=120.0,
            )
            resp.raise_for_status()
            return True
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 413:
                return False
            raise

    def _encode_remote(self, inputs: list[str]) -> list[list[float]]:
        """Call a TEI-compatible ``/embed`` endpoint."""
        if not self._tei_bs_probed:
            self._tei_batch_size = self._probe_tei_batch_size(inputs[0])
            self._tei_bs_probed = True
        return self._encode_remote_batches(inputs, self._tei_batch_size)

    def _encode_remote_batches(self, inputs: list[str], batch_size: int) -> list[list[float]]:
        import time

        results: list[list[float]] = []
        total_batches = (len(inputs) + batch_size - 1) // batch_size
        t_start = time.perf_counter()

        logger.info(
            "TEI start: %d chunks (%d batches, bs=%d)", len(inputs), total_batches, batch_size
        )
        t_last_heartbeat = t_start

        for batch_index, start in enumerate(range(0, len(inputs), batch_size)):
            batch = inputs[start : start + batch_size]
            results.extend(self._encode_remote_batch(batch))
            t_last_heartbeat = self._log_tei_progress(
                batch_index=batch_index,
                total_batches=total_batches,
                start_time=t_start,
                last_heartbeat=t_last_heartbeat,
            )

        self._log_tei_completion(
            total_items=len(results),
            start_time=t_start,
            batch_size=batch_size,
        )
        return results

    def _encode_remote_batch(self, batch: list[str]) -> list[list[float]]:
        import httpx

        response = httpx.post(
            f"{self._embedding_url}/embed",
            json={"inputs": batch, "truncate": True},
            timeout=600.0,
        )
        response.raise_for_status()
        return cast(list[list[float]], response.json())

    def _log_tei_progress(
        self,
        *,
        batch_index: int,
        total_batches: int,
        start_time: float,
        last_heartbeat: float,
    ) -> float:
        import time

        now = time.perf_counter()
        if not self._should_log_tei_progress(
            batch_index=batch_index,
            total_batches=total_batches,
            last_heartbeat=last_heartbeat,
            now=now,
        ):
            return last_heartbeat

        self._log_tei_progress_line(
            batch_index=batch_index,
            total_batches=total_batches,
            start_time=start_time,
            now=now,
        )
        return now

    def _should_log_tei_progress(
        self,
        *,
        batch_index: int,
        total_batches: int,
        last_heartbeat: float,
        now: float,
    ) -> bool:
        return batch_index == total_batches - 1 or (now - last_heartbeat) >= 30.0

    def _format_tei_eta(self, remaining_seconds: float) -> str:
        if remaining_seconds < 60:
            return f"ETA ~{remaining_seconds:.0f}s"
        return f"ETA ~{remaining_seconds / 60:.1f}min"

    def _log_tei_progress_line(
        self,
        *,
        batch_index: int,
        total_batches: int,
        start_time: float,
        now: float,
    ) -> None:
        done = batch_index + 1
        elapsed = now - start_time
        rate = done / elapsed if elapsed > 0 else 0
        remaining = (total_batches - done) / rate if rate > 0 else 0
        eta = self._format_tei_eta(remaining)
        logger.info(
            "TEI %d/%d (%.0f%%) %.1f batches/s, %s",
            done,
            total_batches,
            done / total_batches * 100,
            rate,
            eta,
        )

    def _log_tei_completion(self, *, total_items: int, start_time: float, batch_size: int) -> None:
        import time

        elapsed = time.perf_counter() - start_time
        logger.info(
            "TEI complete: %d vectors in %.1fs (%.1f vectors/s, bs=%d)",
            total_items,
            elapsed,
            total_items / elapsed if elapsed > 0 else 0,
            batch_size,
        )


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
        Base URL of a TEI server (production: ``http://embeddings:80``).
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
        self._score_floor = score_floor
        self._encoder = EmbeddingEncoder(
            model_name=model_name,
            embedding_url=embedding_url,
            tei_batch_size=tei_batch_size,
            use_prefix=use_prefix,
            query_instruction=query_instruction,
        )

    def get_tei_model_id(self) -> str | None:
        return self._encoder.get_tei_model_id()

    @property
    def uses_remote_embeddings(self) -> bool:
        """Whether this engine delegates to a remote embedding service."""
        return self._encoder.uses_remote_embeddings

    def warmup(self) -> None:
        """Pre-load the embedding model (no-op when using a remote server)."""
        self._encoder.warmup()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def encode(self, text: str) -> list[float]:
        """Encode a single text string into a dense vector."""
        return self._encoder.encode(text)

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode a batch of document passages into dense vectors.

        Adds the ``"passage: "`` prefix required by E5-family models
        when ``use_prefix`` is True.  pplx-embed models need no prefix.
        """
        return self._encoder.encode_batch(texts)

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Encode *query* and return the most similar chunks."""
        encoded_query = self._encoder.format_query(query)
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
