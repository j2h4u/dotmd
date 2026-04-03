"""Named-entity recognition extraction using GLiNER (zero-shot NER)."""

from __future__ import annotations

import logging
import os
from collections import Counter
from itertools import combinations
from typing import TYPE_CHECKING, Any

import torch

from dotmd.core.models import Chunk, Entity, ExtractDepth, ExtractionResult, Relation

if TYPE_CHECKING:
    from gliner import GLiNER  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# ADR: Maximize CPU utilization for GLiNER inference.
# Without this, PyTorch defaults to a heuristic that often underutilizes
# available cores (observed: 4.5/8 cores on Xeon E3 V2).
# OMP_NUM_THREADS env var takes precedence if set.
_cpu_count = os.cpu_count() or 4
if not os.environ.get("OMP_NUM_THREADS"):
    torch.set_num_threads(_cpu_count)
    torch.set_num_interop_threads(max(1, _cpu_count // 2))

_DEFAULT_ENTITY_TYPES: list[str] = [
    "person",
    "organization",
    "technology",
    "concept",
    "location",
]

_DEFAULT_MODEL_NAME = "urchade/gliner_multi-v2.1"


class NERExtractor:
    """Zero-shot named-entity recognition extractor backed by GLiNER.

    The GLiNER model is loaded lazily on the first call to :meth:`extract` so
    that import-time cost is zero and the model is only downloaded when
    actually needed.

    Args:
        entity_types: Entity type labels passed to GLiNER for zero-shot
            prediction.  Defaults to ``["person", "organization",
            "technology", "concept", "location"]``.
        model_name: HuggingFace model identifier.  Defaults to
            ``urchade/gliner_multi-v2.1``.
        threshold: Minimum confidence score for GLiNER predictions.
    """

    def __init__(
        self,
        entity_types: list[str] | None = None,
        model_name: str = _DEFAULT_MODEL_NAME,
        threshold: float = 0.5,
    ) -> None:
        self._entity_types: list[str] = entity_types or list(_DEFAULT_ENTITY_TYPES)
        self._model_name: str = model_name
        self._threshold: float = threshold
        self._model: GLiNER | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, chunks: list[Chunk]) -> ExtractionResult:
        """Run GLiNER NER over *chunks* and return entities and relations.

        ADR: Uses batch_predict_entities() with pre-computed label embeddings
        for ~2.5x speedup over per-chunk predict_entities() calls (sequence
        packing in GLiNER 0.2.23+). Label embeddings are computed once and
        reused across all chunks in the batch.

        For each chunk the extractor:

        1. Predicts entities using GLiNER zero-shot NER (batched).
        2. Creates ``Entity`` objects for each unique entity found.
        3. Creates ``CO_OCCURS`` relations between every pair of entities
           found within the same chunk (weight = 1.0).
        4. Creates ``MENTIONS`` relations from the chunk to each entity
           (weight = frequency count of the entity span in the chunk text).
        """
        if not chunks:
            return ExtractionResult()

        model = self._get_model()

        # Batch inference: all chunks at once with pre-computed label embeddings.
        texts = [chunk.text for chunk in chunks]
        batch_predictions: list[list[dict[str, Any]]] = model.batch_predict_entities(
            texts,
            self._entity_types,
            threshold=self._threshold,
        )

        entities: list[Entity] = []
        relations: list[Relation] = []
        seen_entities: dict[tuple[str, str], Entity] = {}

        for chunk, predictions in zip(chunks, batch_predictions):
            if not predictions:
                continue

            span_counter: Counter[str] = Counter()
            chunk_entity_keys: list[tuple[str, str]] = []

            for pred in predictions:
                name: str = pred["text"].strip()
                etype: str = pred["label"]
                if not name:
                    continue

                span_counter[name] += 1
                key = (name.lower(), etype.lower())
                chunk_entity_keys.append(key)

                if key not in seen_entities:
                    entity = Entity(
                        name=name,
                        type=etype,
                        source=ExtractDepth.NER,
                        chunk_ids=[chunk.chunk_id],
                    )
                    seen_entities[key] = entity
                    entities.append(entity)
                else:
                    existing = seen_entities[key]
                    if chunk.chunk_id not in existing.chunk_ids:
                        existing.chunk_ids.append(chunk.chunk_id)

            unique_keys = list(dict.fromkeys(chunk_entity_keys))

            for key_a, key_b in combinations(unique_keys, 2):
                relations.append(
                    Relation(
                        source_id=seen_entities[key_a].name,
                        target_id=seen_entities[key_b].name,
                        relation_type="CO_OCCURS",
                        weight=1.0,
                    )
                )

            for key in unique_keys:
                entity = seen_entities[key]
                freq = span_counter[entity.name]
                relations.append(
                    Relation(
                        source_id=chunk.chunk_id,
                        target_id=entity.name,
                        relation_type="MENTIONS",
                        weight=float(freq),
                    )
                )

        return ExtractionResult(entities=entities, relations=relations)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_model(self) -> GLiNER:
        """Lazily load and cache the GLiNER model."""
        if self._model is None:
            logger.info("Loading GLiNER model '%s' …", self._model_name)
            from gliner import GLiNER  # type: ignore[import-untyped]

            self._model = GLiNER.from_pretrained(self._model_name)
            # ADR: Cap max sequence length to match our chunk token budget.
            # GLiNER attention is O(n^2) — shorter max_len = faster inference.
            # 512 matches our chunk_max_tokens setting.
            if hasattr(self._model, "config") and hasattr(self._model.config, "max_len"):
                self._model.config.max_len = 512
            logger.info(
                "GLiNER model loaded (threads=%d, max_len=%s).",
                torch.get_num_threads(),
                getattr(getattr(self._model, "config", None), "max_len", "?"),
            )
        return self._model
