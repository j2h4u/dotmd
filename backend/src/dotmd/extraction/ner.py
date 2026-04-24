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
    from dotmd.storage.cache import ExtractionCache

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
        extraction_cache: "ExtractionCache | None" = None,
    ) -> None:
        self._entity_types: list[str] = entity_types or list(_DEFAULT_ENTITY_TYPES)
        self._model_name: str = model_name
        self._threshold: float = threshold
        self._model: GLiNER | None = None
        self._extraction_cache: ExtractionCache | None = extraction_cache

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_with_cache(self, chunks: list[Chunk]) -> ExtractionResult:
        """Run NER extraction with cache lookup. Falls back to extract() when cache is None.

        Cache stores only chunk-id-independent data:
        - entities: {name, type, source} — no chunk_ids in stored rows
        - co_occurs: CO_OCCURS relations keyed on entity names

        MENTIONS relations are rebuilt here at read time using current chunk.chunk_id.
        This makes cached results safe to reuse after Plan 03 chunk_id migration.
        """
        if self._extraction_cache is None or not chunks:
            return self.extract(chunks)

        cached_hits, miss_chunks = self._extraction_cache.lookup_batch(chunks)

        # Build a chunk_id lookup for MENTIONS reconstruction
        chunk_by_id: dict[str, Chunk] = {c.chunk_id: c for c in chunks}

        entities: list[Entity] = []
        relations: list[Relation] = []
        seen_entities: dict[tuple[str, str], Entity] = {}

        # Restore cached results and rebuild MENTIONS at read time
        for chunk_id, (ents_data, co_occurs_data) in cached_hits.items():
            chunk = chunk_by_id[chunk_id]
            span_counter: Counter[str] = Counter()

            for d in ents_data:
                key = (d["name"].lower(), d["type"].lower())
                if key not in seen_entities:
                    entity = Entity(
                        name=d["name"],
                        type=d["type"],
                        source=d["source"],
                        chunk_ids=[chunk_id],
                    )
                    seen_entities[key] = entity
                    entities.append(entity)
                else:
                    existing_entity = seen_entities[key]
                    if chunk_id not in existing_entity.chunk_ids:
                        existing_entity.chunk_ids.append(chunk_id)
                span_counter[d["name"]] += 1

            for d in co_occurs_data:
                relations.append(Relation(**d))

            # Rebuild MENTIONS using current chunk_id
            for name, freq in span_counter.items():
                relations.append(Relation(
                    source_id=chunk_id,
                    target_id=name,
                    relation_type="MENTIONS",
                    weight=float(freq),
                ))

        # Run GLiNER only on cache misses
        new_results_per_chunk: dict[str, tuple[list, list]] = {}
        if miss_chunks:
            miss_result = self.extract(miss_chunks)

            # Split miss_result into per-chunk data for cache storage.
            # extract() returns a combined ExtractionResult — we split it
            # back into per-chunk cache payloads for storage.
            entities.extend(miss_result.entities)

            # Separate MENTIONS from CO_OCCURS for per-chunk cache storage
            for chunk in miss_chunks:
                chunk_mentions = [
                    r for r in miss_result.relations
                    if r.relation_type == "MENTIONS" and r.source_id == chunk.chunk_id
                ]
                chunk_co_occurs = [
                    r for r in miss_result.relations
                    if r.relation_type == "CO_OCCURS"
                ]
                # Entities referenced by this chunk (those that mention this chunk_id)
                mentioned_names = {r.target_id for r in chunk_mentions}
                chunk_entities = [
                    e for e in miss_result.entities
                    if e.name in mentioned_names
                ]

                entities_to_cache = [
                    {"name": e.name, "type": e.type, "source": e.source}
                    for e in chunk_entities
                ]
                co_occurs_to_cache = [r.model_dump() for r in chunk_co_occurs]
                new_results_per_chunk[chunk.chunk_id] = (entities_to_cache, co_occurs_to_cache)

            relations.extend(miss_result.relations)

            if new_results_per_chunk:
                self._extraction_cache.store_batch(miss_chunks, new_results_per_chunk)

        return ExtractionResult(entities=entities, relations=relations)

    def extract(self, chunks: list[Chunk]) -> ExtractionResult:
        """Run GLiNER NER over *chunks* and return entities and relations.

        ADR: Uses inference() with pre-computed label embeddings
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
        batch_predictions: list[list[dict[str, Any]]] = model.inference(
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
