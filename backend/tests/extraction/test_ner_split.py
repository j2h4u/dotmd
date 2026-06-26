"""GLiNER input splitting behavior."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dotmd.core.models import Chunk
from dotmd.extraction.ner import NERExtractor, _split_for_gliner


def _chunk(chunk_id: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        file_paths=[Path(f"/tmp/{chunk_id[:8]}.md")],
        heading_hierarchy=[],
        level=0,
        text=text,
        chunk_index=0,
    )


class _FakeGliner:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def inference(
        self,
        texts: list[str],
        entity_types: list[str],
        *,
        threshold: float,
    ) -> list[list[dict[str, Any]]]:
        self.texts = texts
        return [
            [{"text": f"Entity {index}", "label": entity_types[0]}] for index, _ in enumerate(texts)
        ]


def test_short_gliner_input_is_not_split() -> None:
    text = "Alice works with Bob."

    assert _split_for_gliner(text) == [text]


def test_long_gliner_input_is_split_before_inference_and_merged_by_chunk() -> None:
    long_sentence = " ".join(f"token{i}" for i in range(530))
    chunk = _chunk("a" * 64, long_sentence)
    extractor = NERExtractor(["person"], model_name="ner-a", threshold=0.5)
    fake_model = _FakeGliner()
    extractor._model = fake_model

    result = extractor.extract([chunk])

    assert len(fake_model.texts) == 2
    assert all(len(text.split()) <= 320 for text in fake_model.texts)
    assert [entity.name for entity in result.entities] == ["Entity 0", "Entity 1"]
    assert all(entity.chunk_ids == [chunk.chunk_id] for entity in result.entities)
