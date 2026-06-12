"""Named-entity recognition extraction using GLiNER (zero-shot NER)."""

from __future__ import annotations

import logging
import os
from collections import Counter
from itertools import combinations
from typing import TYPE_CHECKING, Any, cast

from dotmd.core.models import Chunk, Entity, ExtractDepth, ExtractionResult, Relation

if TYPE_CHECKING:
    from gliner import GLiNER  # type: ignore[import-untyped]

    from dotmd.storage.cache import ExtractionCache

logger = logging.getLogger(__name__)

_DEFAULT_ENTITY_TYPES: list[str] = [
    "person",
    "organization",
    "technology",
    "concept",
    "location",
]

_DEFAULT_MODEL_NAME = "urchade/gliner_multi-v2.1"


def _configure_torch_threads() -> int | None:
    """Configure PyTorch thread counts only when NER is actually used."""
    if os.environ.get("OMP_NUM_THREADS"):
        return None
    import torch

    cpu_count = os.cpu_count() or 4
    torch.set_num_threads(cpu_count)
    torch.set_num_interop_threads(max(1, cpu_count // 2))
    return torch.get_num_threads()


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
        extraction_cache: ExtractionCache | None = None,
    ) -> None:
        self._entity_types: list[str] = entity_types or list(_DEFAULT_ENTITY_TYPES)
        self._model_name: str = model_name
        self._threshold: float = threshold
        self._model: object | None = None
        self._extraction_cache: ExtractionCache | None = extraction_cache

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_with_cache(self, chunks: list[Chunk]) -> ExtractionResult:
        """Run NER extraction with cache lookup. Falls back to extract() when cache is None.

        Cache stores only chunk-id-independent data:
        - entities: {name, type, source} — no chunk_ids in stored rows
        - co_occurs: CO_OCCURS relations keyed on entity names, scoped to ONE chunk

        MENTIONS relations are rebuilt here at read time using current chunk.chunk_id.
        This makes cached results safe to reuse after Plan 03 chunk_id migration.
        """
        if self._extraction_cache is None or not chunks:
            return self.extract(chunks)

        cached_hits, miss_chunks = self._extraction_cache.lookup_batch(chunks)
        chunk_by_id: dict[str, Chunk] = {c.chunk_id: c for c in chunks}

        entities: list[Entity] = []
        relations: list[Relation] = []
        seen_entities: dict[tuple[str, str], Entity] = {}

        # Restore cached results and rebuild MENTIONS at read time
        for chunk_id, (ents_data, co_occurs_data) in cached_hits.items():
            _ = chunk_by_id[chunk_id]  # validate chunk_id present in batch
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

            relations.extend(Relation(**d) for d in co_occurs_data)

            # Rebuild MENTIONS using current chunk_id
            for name, freq in span_counter.items():
                relations.append(
                    Relation(
                        source_id=chunk_id,
                        target_id=name,
                        relation_type="MENTIONS",
                        weight=float(freq),
                    )
                )

        # Run GLiNER only on cache misses, with per-chunk attribution preserved
        if miss_chunks:
            per_chunk_misses = self._extract_per_chunk(miss_chunks)
            new_results_per_chunk: dict[str, tuple[list, list]] = {}

            for chunk in miss_chunks:
                chunk_entities, chunk_relations = per_chunk_misses.get(chunk.chunk_id, ([], []))

                # Aggregate this chunk's entities into global result (dedup by key)
                for e in chunk_entities:
                    key = (e.name.lower(), e.type.lower())
                    if key not in seen_entities:
                        seen_entities[key] = e
                        entities.append(e)
                    else:
                        existing = seen_entities[key]
                        if chunk.chunk_id not in existing.chunk_ids:
                            existing.chunk_ids.append(chunk.chunk_id)

                relations.extend(chunk_relations)

                # Build per-chunk cache payload (entities + CO_OCCURS for THIS chunk only)
                chunk_co_occurs = [r for r in chunk_relations if r.relation_type == "CO_OCCURS"]
                entities_to_cache = [
                    {"name": e.name, "type": e.type, "source": e.source} for e in chunk_entities
                ]
                co_occurs_to_cache = [r.model_dump() for r in chunk_co_occurs]
                new_results_per_chunk[chunk.chunk_id] = (entities_to_cache, co_occurs_to_cache)

            if new_results_per_chunk:
                self._extraction_cache.store_batch(miss_chunks, new_results_per_chunk)

        return ExtractionResult(entities=entities, relations=relations)

    def extract(self, chunks: list[Chunk]) -> ExtractionResult:
        """Run GLiNER NER over *chunks* and return aggregated entities and relations.

        Aggregates per-chunk results: dedupes entities by ``(name.lower(), type.lower())``
        and accumulates ``chunk_ids`` on the kept Entity object. Order of first
        appearance (chunk-order) is preserved in the entities list.

        For each chunk the extractor:

        1. Predicts entities using GLiNER zero-shot NER (batched, see _extract_per_chunk).
        2. Creates ``Entity`` objects for each unique (name, type) found.
        3. Creates ``CO_OCCURS`` relations between every pair of entities
           found within the same chunk (weight = 1.0).
        4. Creates ``MENTIONS`` relations from the chunk to each entity
           (weight = frequency count of the entity span in the chunk text).
        """
        if not chunks:
            return ExtractionResult()

        per_chunk = self._extract_per_chunk(chunks)

        entities: list[Entity] = []
        relations: list[Relation] = []
        seen_entities: dict[tuple[str, str], Entity] = {}

        for chunk in chunks:
            chunk_entities, chunk_relations = per_chunk.get(chunk.chunk_id, ([], []))

            for e in chunk_entities:
                key = (e.name.lower(), e.type.lower())
                if key not in seen_entities:
                    seen_entities[key] = e
                    entities.append(e)
                else:
                    existing = seen_entities[key]
                    if chunk.chunk_id not in existing.chunk_ids:
                        existing.chunk_ids.append(chunk.chunk_id)

            relations.extend(chunk_relations)

        return ExtractionResult(entities=entities, relations=relations)

    def _extract_per_chunk(
        self, chunks: list[Chunk]
    ) -> dict[str, tuple[list[Entity], list[Relation]]]:
        """Run GLiNER and return per-chunk (entities, relations), without global dedup.

        Each chunk's Entity has ``chunk_ids = [chunk.chunk_id]`` (single-chunk).
        Each chunk's relations include only that chunk's MENTIONS and CO_OCCURS.

        ADR: Uses inference() with pre-computed label embeddings for ~2.5x speedup
        over per-chunk predict_entities() calls (sequence packing in GLiNER 0.2.23+).

        Per-chunk attribution lets ``extract_with_cache`` write the correct subset
        of relations to each chunk's cache row, avoiding the N×N batch-bloat bug
        where every chunk's row stored every other chunk's CO_OCCURS pairs.
        """
        if not chunks:
            return {}

        model = self._get_model()

        texts = [chunk.text for chunk in chunks]
        batch_predictions: list[list[dict[str, Any]]] = cast(Any, model).inference(
            texts,
            self._entity_types,
            threshold=self._threshold,
        )

        per_chunk: dict[str, tuple[list[Entity], list[Relation]]] = {}

        for chunk, predictions in zip(chunks, batch_predictions, strict=False):
            chunk_entities: list[Entity] = []
            chunk_relations: list[Relation] = []

            if not predictions:
                per_chunk[chunk.chunk_id] = (chunk_entities, chunk_relations)
                continue

            seen_in_chunk: dict[tuple[str, str], Entity] = {}
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

                if key not in seen_in_chunk:
                    entity = Entity(
                        name=name,
                        type=etype,
                        source=ExtractDepth.NER,
                        chunk_ids=[chunk.chunk_id],
                    )
                    seen_in_chunk[key] = entity
                    chunk_entities.append(entity)

            unique_keys = list(dict.fromkeys(chunk_entity_keys))

            for key_a, key_b in combinations(unique_keys, 2):
                chunk_relations.append(
                    Relation(
                        source_id=seen_in_chunk[key_a].name,
                        target_id=seen_in_chunk[key_b].name,
                        relation_type="CO_OCCURS",
                        weight=1.0,
                    )
                )

            for key in unique_keys:
                entity = seen_in_chunk[key]
                freq = span_counter[entity.name]
                chunk_relations.append(
                    Relation(
                        source_id=chunk.chunk_id,
                        target_id=entity.name,
                        relation_type="MENTIONS",
                        weight=float(freq),
                    )
                )

            per_chunk[chunk.chunk_id] = (chunk_entities, chunk_relations)

        return per_chunk

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_model(self) -> GLiNER:
        """Lazily load and cache the GLiNER model."""
        if self._model is None:
            logger.info("Loading GLiNER model '%s' …", self._model_name)
            torch_threads = _configure_torch_threads()
            from gliner import GLiNER  # type: ignore[import-untyped]

            model = cast("GLiNER", GLiNER.from_pretrained(self._model_name))
            # ADR: Cap max sequence length to match our chunk token budget.
            # GLiNER attention is O(n^2) — shorter max_len = faster inference.
            # 512 matches our chunk_max_tokens setting.
            model_config = getattr(cast(Any, model), "config", None)
            if model_config is not None and hasattr(model_config, "max_len"):
                model_config.max_len = 512
            logger.info(
                "GLiNER model loaded (threads=%d, max_len=%s).",
                torch_threads or 0,
                getattr(model_config, "max_len", "?"),
            )
            self._model = model
        return cast("GLiNER", self._model)
