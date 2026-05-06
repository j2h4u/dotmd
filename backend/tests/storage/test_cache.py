"""Regression coverage for Phase 15 content-addressed caches."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from dotmd.core.models import Chunk, Entity, Relation
from dotmd.extraction.ner import NERExtractor
from dotmd.ingestion.chunker import chunk_file
from dotmd.storage.cache import EmbeddingCache, ExtractionCache


def _chunk(chunk_id: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        file_paths=[Path(f"/tmp/{chunk_id[:8]}.md")],
        heading_hierarchy=[],
        level=0,
        text=text,
        chunk_index=0,
    )


def test_embedding_cache_is_model_scoped_and_invalidates_on_model_change() -> None:
    conn = sqlite3.connect(":memory:")
    cache = EmbeddingCache(conn, "model-a")

    assert cache.should_invalidate() is False

    cache.store("hash-1", [0.1, 0.2, 0.3])
    conn.commit()
    cache.update_model_sentinel()

    assert cache.lookup(["hash-1"]) == {
        "hash-1": [0.10000000149011612, 0.20000000298023224, 0.30000001192092896]
    }
    assert EmbeddingCache(conn, "model-b").lookup(["hash-1"]) == {}
    assert EmbeddingCache(conn, "model-b").should_invalidate() is True

    EmbeddingCache(conn, "model-b").clear()
    assert cache.lookup(["hash-1"]) == {}
    assert EmbeddingCache(conn, "model-b").should_invalidate() is False


def test_extraction_cache_is_signature_scoped_and_stores_chunk_id_independent_payload() -> None:
    conn = sqlite3.connect(":memory:")
    cache = ExtractionCache(conn, "ner-a", ["person"], 0.5)
    chunk = _chunk("a" * 64, "Alice met Bob.")

    assert cache.should_invalidate() is False
    cache.store_batch(
        [chunk],
        {
            chunk.chunk_id: (
                [{"name": "Alice", "type": "person", "source": "ner"}],
                [],
            )
        },
    )
    conn.commit()
    cache.update_model_sig()

    hits, misses = cache.lookup_batch([chunk])
    assert misses == []
    assert hits == {chunk.chunk_id: ([{"name": "Alice", "type": "person", "source": "ner"}], [])}

    columns = {row[1] for row in conn.execute("PRAGMA table_info(extraction_cache)").fetchall()}
    assert "entities_json" in columns
    assert "co_occurs_json" in columns
    assert "relations_json" not in columns

    assert ExtractionCache(conn, "ner-a", ["person"], 0.7).should_invalidate() is True
    assert ExtractionCache(conn, "ner-a", ["organization"], 0.5).should_invalidate() is True
    assert ExtractionCache(conn, "ner-b", ["person"], 0.5).should_invalidate() is True


def test_ner_extractor_rebuilds_mentions_with_current_chunk_id_from_cache() -> None:
    conn = sqlite3.connect(":memory:")
    cache = ExtractionCache(conn, "ner-a", ["person"], 0.5)
    old_chunk = _chunk("a" * 64, "Alice met Bob.")
    current_chunk = _chunk("b" * 64, "Alice met Bob.")
    cache.store_batch(
        [old_chunk],
        {
            old_chunk.chunk_id: (
                [{"name": "Alice", "type": "person", "source": "ner"}],
                [],
            )
        },
    )
    conn.commit()

    extractor = NERExtractor(["person"], model_name="ner-a", threshold=0.5, extraction_cache=cache)
    result = extractor.extract_with_cache([current_chunk])

    assert result.entities == [
        Entity(name="Alice", type="person", source="ner", chunk_ids=[current_chunk.chunk_id])
    ]
    assert (
        Relation(
            source_id=current_chunk.chunk_id,
            target_id="Alice",
            relation_type="MENTIONS",
            weight=1.0,
        )
        in result.relations
    )


def test_ner_extractor_runs_model_only_for_cache_misses(monkeypatch) -> None:
    conn = sqlite3.connect(":memory:")
    cache = ExtractionCache(conn, "ner-a", ["person"], 0.5)
    cached = _chunk("a" * 64, "Alice met Bob.")
    missed = _chunk("c" * 64, "Carol met Dave.")
    cache.store_batch(
        [cached],
        {
            cached.chunk_id: (
                [{"name": "Alice", "type": "person", "source": "ner"}],
                [],
            )
        },
    )
    conn.commit()

    extractor = NERExtractor(["person"], model_name="ner-a", threshold=0.5, extraction_cache=cache)
    seen: list[list[str]] = []

    def fake_extract_per_chunk(
        chunks: list[Chunk],
    ) -> dict[str, tuple[list[Entity], list[Relation]]]:
        seen.append([chunk.chunk_id for chunk in chunks])
        return {
            missed.chunk_id: (
                [Entity(name="Carol", type="person", source="ner", chunk_ids=[missed.chunk_id])],
                [
                    Relation(
                        source_id=missed.chunk_id,
                        target_id="Carol",
                        relation_type="MENTIONS",
                        weight=1.0,
                    )
                ],
            )
        }

    monkeypatch.setattr(extractor, "_extract_per_chunk", fake_extract_per_chunk)

    result = extractor.extract_with_cache([cached, missed])

    assert seen == [[missed.chunk_id]]
    assert {entity.name for entity in result.entities} == {"Alice", "Carol"}


def test_chunk_ids_are_path_independent_and_strategy_scoped(tmp_path: Path) -> None:
    content = "# Heading\n\nSame body.\n"
    first = tmp_path / "first.md"
    second = tmp_path / "nested" / "second.md"
    first.write_text(content, encoding="utf-8")
    second.parent.mkdir()
    second.write_text(content, encoding="utf-8")

    first_chunks = chunk_file(first, content, chunk_strategy="heading_512_50")
    second_chunks = chunk_file(second, content, chunk_strategy="heading_512_50")
    other_strategy_chunks = chunk_file(first, content, chunk_strategy="contextual_512_50")

    assert [chunk.chunk_id for chunk in first_chunks] == [chunk.chunk_id for chunk in second_chunks]
    assert all(len(chunk.chunk_id) == 64 for chunk in first_chunks)
    assert [chunk.chunk_id for chunk in first_chunks] != [
        chunk.chunk_id for chunk in other_strategy_chunks
    ]
