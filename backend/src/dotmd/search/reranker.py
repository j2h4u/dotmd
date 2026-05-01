"""Cross-encoder reranking for search results.

Provides a thin wrapper around a ``sentence_transformers.CrossEncoder``
model that rescores ``(query, chunk_text)`` pairs and returns the top-k
results sorted by descending relevance.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from dotmd.core.config import Settings
    from dotmd.storage.base import MetadataStoreProtocol

logger = logging.getLogger(__name__)


class RerankerProtocol(Protocol):
    """Protocol implemented by reranker adapters."""

    name: str
    model_name: str

    def warmup(self) -> None:
        """Load or prepare the underlying reranker provider."""
        ...

    def rerank(
        self,
        query: str,
        chunk_ids: list[str],
        metadata_store: MetadataStoreProtocol,
        top_k: int = 5,
    ) -> list[tuple[str, float]]:
        """Return reranked ``(chunk_id, score)`` pairs."""
        ...


@dataclass(frozen=True)
class RerankerSpec:
    """Registry metadata for a built-in reranker adapter."""

    name: str
    model_name: str
    backend: str = "cross_encoder"
    description: str = ""


BUILTIN_RERANKERS: dict[str, RerankerSpec] = {
    "qwen3-0.6b": RerankerSpec(
        name="qwen3-0.6b",
        model_name="Qwen/Qwen3-Reranker-0.6B",
        description="Qwen3 0.6B reranker selected as the Phase 18 default.",
    ),
    "msmarco-minilm": RerankerSpec(
        name="msmarco-minilm",
        model_name="cross-encoder/ms-marco-MiniLM-L-6-v2",
        description="Legacy English MiniLM baseline.",
    ),
    "mmarco-minilm": RerankerSpec(
        name="mmarco-minilm",
        model_name="cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
        description="Multilingual MiniLM baseline.",
    ),
    "gte-multilingual": RerankerSpec(
        name="gte-multilingual",
        model_name="Alibaba-NLP/gte-multilingual-reranker-base",
        description="GTE multilingual reranker candidate.",
    ),
    "bge-v2-m3": RerankerSpec(
        name="bge-v2-m3",
        model_name="BAAI/bge-reranker-v2-m3",
        description="BGE multilingual reranker candidate.",
    ),
}


def available_rerankers() -> list[str]:
    """Return stable names for built-in rerankers."""
    return sorted(BUILTIN_RERANKERS)


class CrossEncoderReranker:
    """Cross-encoder reranker with lazy model loading and length penalty.

    The underlying ``CrossEncoder`` is instantiated on the first call to
    :meth:`rerank` so that import time stays fast and GPU/CPU resources
    are only consumed when actually needed.

    The reranker reorders candidates by cross-encoder score. Raw-score
    filtering is disabled by default; callers may pass *relevance_floor*
    to keep only candidates at or above that score.

    Optionally applies a length penalty to downrank very short chunks
    (e.g., navigation tables) that may be keyword-dense but lack content.

    Parameters
    ----------
    model_name:
        HuggingFace model identifier for the cross-encoder.
    length_penalty:
        If True, apply a penalty to chunks shorter than *min_length*.
    min_length:
        Minimum character length below which the penalty is applied.
    """

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        *,
        name: str | None = None,
        length_penalty: bool = True,
        min_length: int = 100,
        relevance_floor: float | None = None,
    ) -> None:
        self.name = name or model_name
        self.model_name = model_name
        self._model_name = model_name
        self._model: Any | None = None
        self._length_penalty = length_penalty
        self._min_length = min_length
        # None means no raw-score filtering. Qwen3 scores are useful for
        # ordering, but a universal default floor is not portable across models.
        self._relevance_floor = relevance_floor

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _load_model(self) -> Any:
        """Load the cross-encoder model on first use."""
        if self._model is None:
            from sentence_transformers import CrossEncoder  # type: ignore[import-untyped]

            logger.info("Loading cross-encoder model: %s", self._model_name)
            self._model = CrossEncoder(self._model_name)
        return self._model

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def warmup(self) -> None:
        """Load the cross-encoder provider without scoring candidates."""
        self._load_model()

    def rerank(
        self,
        query: str,
        chunk_ids: list[str],
        metadata_store: MetadataStoreProtocol,
        top_k: int = 5,
    ) -> list[tuple[str, float]]:
        """Rerank *chunk_ids* against *query* using a cross-encoder.

        Each chunk's text is retrieved from *metadata_store*, paired with
        the query, and scored by the cross-encoder.  The results are
        returned in descending score order, truncated to *top_k*.

        Parameters
        ----------
        query:
            The user query string.
        chunk_ids:
            Chunk identifiers to rerank.
        metadata_store:
            A store satisfying :class:`MetadataStoreProtocol` used to
            look up chunk text.
        top_k:
            Maximum number of results to return.

        Returns
        -------
        list[tuple[str, float]]
            Up to *top_k* ``(chunk_id, score)`` pairs sorted by
            descending cross-encoder score.
        """
        if not chunk_ids:
            return []

        chunks = metadata_store.get_chunks(chunk_ids)
        if not chunks:
            return []

        # Preserve ordering alignment between ids and texts.
        chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
        id_text_pairs: list[tuple[str, str]] = [
            (cid, chunks_by_id[cid].text)
            for cid in chunk_ids
            if cid in chunks_by_id
        ]
        if not id_text_pairs:
            return []

        try:
            model = self._load_model()
            pairs = [(query, text) for _, text in id_text_pairs]
            raw_scores = model.predict(pairs)
            scores: list[float] = (
                raw_scores.tolist()
                if hasattr(raw_scores, "tolist")
                else list(raw_scores)
            )
        except Exception:
            logger.warning(
                "Reranker provider failed for model %s; returning no reranked candidates",
                self._model_name,
                exc_info=True,
            )
            return []

        # Apply length penalty to short chunks if enabled
        if self._length_penalty:
            adjusted_scores = []
            for score, (_cid, text) in zip(scores, id_text_pairs, strict=False):
                text_length = len(text)
                if text_length < self._min_length:
                    # Subtract so the penalty lowers rank for both positive and
                    # negative score scales.
                    penalty = 0.2 * (1.0 - (text_length / self._min_length))
                    score = score - penalty
                adjusted_scores.append(score)
            scores = adjusted_scores

        scored = [
            (cid, float(score))
            for (cid, _text), score in zip(id_text_pairs, scores, strict=False)
            if self._relevance_floor is None or score >= self._relevance_floor
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        if scored:
            logger.debug(
                "Reranker: %d/%d passed relevance floor (%s), top=%.2f, min=%.2f",
                len(scored), len(id_text_pairs), self._relevance_floor,
                scored[0][1], scored[-1][1],
            )
        else:
            logger.debug(
                "Reranker: all %d candidates below relevance floor (%s)",
                len(id_text_pairs),
                self._relevance_floor,
            )
        return scored[:top_k]


def create_reranker(name: str, settings: Settings) -> RerankerProtocol:
    """Create a reranker adapter by stable registry name."""
    try:
        spec = BUILTIN_RERANKERS[name]
    except KeyError:
        available = ", ".join(available_rerankers())
        raise ValueError(
            f"Unknown reranker {name!r}; available: {available}"
        ) from None

    if spec.backend != "cross_encoder":
        raise ValueError(
            f"Unsupported reranker backend {spec.backend!r} for {name!r}"
        )

    model_name = spec.model_name
    if name == "qwen3-0.6b" and settings.reranker_name == "qwen3-0.6b":
        model_name = settings.reranker_model

    return CrossEncoderReranker(
        model_name=model_name,
        name=spec.name,
        length_penalty=settings.reranker_length_penalty,
        min_length=settings.reranker_min_length,
        relevance_floor=settings.reranker_relevance_floor,
    )


class RerankerFactory:
    """Cache reranker adapters by stable registry name."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._instances: dict[str, RerankerProtocol] = {}

    def get(self, name: str | None = None) -> RerankerProtocol:
        """Return a cached reranker, using the configured default when omitted."""
        resolved = name or self._settings.reranker_name
        if resolved not in self._instances:
            self._instances[resolved] = create_reranker(resolved, self._settings)
        return self._instances[resolved]


Reranker = CrossEncoderReranker
