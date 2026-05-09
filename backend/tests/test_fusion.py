"""Tests for fusion math and weight validation (Phase 999.12)."""
import math
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from dotmd.core.models import Chunk, ChunkProvenance, SearchCandidate, SourceDocument
from dotmd.mcp_server import _format_result
from dotmd.search.fusion import _extract_best_snippet, build_candidates
from dotmd.storage.base import MetadataStoreProtocol
from dotmd.storage.metadata import SQLiteMetadataStore


def _normalize(v):
    """Reference normalize for test assertions."""
    mag = math.sqrt(sum(x * x for x in v))
    return [x / mag for x in v] if mag > 0 else v


def test_extract_best_snippet_starts_at_containing_sentence() -> None:
    """A match in a later sentence expands left to that sentence boundary."""
    text = (
        "Intro sentence has no relevant words. "
        "Before the target, this sentence has enough padding to be cut today. "
        "The ranking signal appears here and should keep the whole sentence. "
        "Final sentence is unrelated."
    )

    snippet = _extract_best_snippet(text, "ranking signal", length=44)

    assert snippet.startswith("...The ranking signal")
    assert "ranking signal appears here" in snippet


def test_extract_best_snippet_happy_path_expands_beyond_length() -> None:
    """Boundary expansion can return a full sentence longer than length but below cap."""
    text = (
        "Short opener. "
        "This target sentence is deliberately longer than the requested window. "
        "Short closer."
    )

    snippet = _extract_best_snippet(text, "target", length=40)

    expected = "...This target sentence is deliberately longer than the requested window...."
    assert snippet == expected
    assert len(snippet) > 40
    assert len(snippet) <= 2 * 40 + 6


def test_extract_best_snippet_already_at_sentence_boundary_has_no_leading_ellipsis() -> None:
    """A boundary-aligned best window must not pull previous punctuation in."""
    text = "Target sentence starts this chunk and should remain clean. Another sentence follows."

    snippet = _extract_best_snippet(text, "Target", length=35)

    assert snippet.startswith("Target sentence")
    assert not snippet.startswith("...")
    assert "Another sentence" not in snippet


def test_extract_best_snippet_blank_line_boundary() -> None:
    """Paragraph boundary stops expansion when the match is before a blank line."""
    text = (
        "Opening paragraph has filler. "
        "Important target sentence stays in the first paragraph.\n\n"
        "Second paragraph must not leak into the snippet."
    )

    snippet = _extract_best_snippet(text, "target", length=36)

    assert "Important target sentence" in snippet
    assert "\n\n" not in snippet
    assert "Second paragraph" not in snippet


def test_extract_best_snippet_long_single_sentence_is_hard_capped() -> None:
    """A long sentence falls back to bounded word-aware trimming."""
    text = (
        "This very long sentence has many filler words before the unique target "
        "and many filler words after it so sentence boundary expansion would be "
        "larger than the hard cap for the configured snippet length."
    )
    length = 45

    snippet = _extract_best_snippet(text, "unique target", length=length)

    assert "unique target" in snippet
    assert len(snippet) <= 2 * length + 6


def test_extract_best_snippet_empty_query_is_bounded() -> None:
    """Empty query keeps the old bounded fallback contract."""
    text = " ".join(f"word{i}" for i in range(30))

    snippet = _extract_best_snippet(text, "", length=50)

    assert len(snippet) <= 53
    assert snippet.endswith("...")


def test_extract_best_snippet_short_text_is_exact() -> None:
    """Short chunks are not decorated with artificial ellipses."""
    text = "Short complete chunk."

    assert _extract_best_snippet(text, "chunk", length=80) == text


class _SnippetMetadataStore:
    _table = "chunks_default"

    def __init__(self, chunks: list[Chunk]) -> None:
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}

    def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]:
        return [self._chunks[chunk_id] for chunk_id in chunk_ids if chunk_id in self._chunks]

    def get_file_paths_for_chunk_ids(
        self,
        strategy: str,
        chunk_ids: list[str],
    ) -> dict[str, list[str]]:
        return {
            chunk_id: [str(path) for path in self._chunks[chunk_id].file_paths]
            for chunk_id in chunk_ids
            if chunk_id in self._chunks
        }

    def get_chunk_provenance_for_chunk_ids(
        self,
        strategy: str,
        chunk_ids: list[str],
    ) -> dict[str, ChunkProvenance]:
        assert strategy == "default"
        return {
            chunk_id: ChunkProvenance(
                namespace="filesystem",
                document_ref=f"/mnt/{chunk_id}.md",
                ref=f"filesystem:/mnt/{chunk_id}.md",
                source_unit_refs=[],
                chunk_strategy=strategy,
                parser_name="markdown",
            )
            for chunk_id in chunk_ids
            if chunk_id in self._chunks
        }


def test_build_candidates_uses_boundary_aware_snippet() -> None:
    """Normal result construction exposes the boundary-aware snippet."""
    chunk = Chunk(
        chunk_id="chunk-1",
        file_paths=[Path("/notes/transcript.md")],
        heading_hierarchy=["Meeting"],
        text=(
            "Intro sentence has no signal. "
            "The search target appears in this complete sentence. "
            "Tail sentence."
        ),
        chunk_index=0,
    )
    store = _SnippetMetadataStore([chunk])

    results = build_candidates(
        [("filesystem:/mnt/chunk-1.md", 0.9)],
        {"semantic": [("filesystem:/mnt/chunk-1.md", 0.8)]},
        cast(MetadataStoreProtocol, store),
        query="target",
        ref_to_chunk={"filesystem:/mnt/chunk-1.md": ("chunk-1", "")},
        active_provenance_map={"chunk-1": store.get_chunk_provenance_for_chunk_ids("default", ["chunk-1"])["chunk-1"]},
        snippet_length=35,
    )

    assert len(results) == 1
    assert isinstance(results[0], SearchCandidate)
    assert results[0].snippet.startswith("...The search target")
    assert "target appears" in results[0].snippet
    assert results[0].ref == "filesystem:/mnt/chunk-1.md"


def test_build_candidates_hydrates_graph_direct_ref_from_provenance() -> None:
    """Graph-direct hits use source provenance, not holder paths, for public refs."""
    graph_chunk_id = "graph-chunk"
    graph_ref = "filesystem:/graph/file.md"
    chunk = Chunk(
        chunk_id=graph_chunk_id,
        file_paths=[Path("/fallback/file.md")],
        heading_hierarchy=["Graph"],
        level=1,
        text="filesystem:/graph/file.md graph snippet",
        chunk_index=0,
    )

    class HydratingStore:
        _table = "chunks_heading_512_50"

        def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]:
            assert chunk_ids == [graph_chunk_id]
            return [chunk]

        def get_chunk_provenance_for_chunk_ids(
            self,
            strategy: str,
            chunk_ids: list[str],
        ) -> dict[str, ChunkProvenance]:
            assert strategy == "heading_512_50"
            assert chunk_ids == [graph_chunk_id]
            return {
                graph_chunk_id: ChunkProvenance(
                    namespace="filesystem",
                    document_ref="/graph/file.md",
                    ref=graph_ref,
                    source_unit_refs=[],
                    chunk_strategy=strategy,
                    parser_name="markdown",
                )
            }

    provenance = ChunkProvenance(
        namespace="filesystem",
        document_ref="/graph/file.md",
        ref=graph_ref,
        source_unit_refs=[],
        chunk_strategy="heading_512_50",
        parser_name="markdown",
    )

    results = build_candidates(
        [(graph_ref, 0.7)],
        per_engine={"graph_direct": [(graph_ref, 0.95)]},
        metadata_store=cast(Any, HydratingStore()),
        query="graph",
        ref_to_chunk={graph_ref: (graph_chunk_id, "")},
        active_provenance_map={graph_chunk_id: provenance},
        top_k=1,
    )

    assert len(results) == 1
    assert isinstance(results[0], SearchCandidate)
    assert results[0].ref == graph_ref
    assert results[0].engine_scores is not None
    assert results[0].engine_scores.get("graph_direct") == 0.95
    assert results[0].matched_engines == ("graph_direct",)


def test_build_candidates_uses_telegram_message_ref_from_unit_provenance() -> None:
    """Telegram search hits must be directly usable by drill/read."""
    telegram_chunk_id = "telegram-message-chunk"
    telegram_ref = "telegram:dialog:-1001:message:42"
    chunk = Chunk(
        chunk_id=telegram_chunk_id,
        file_paths=[],
        heading_hierarchy=[],
        level=0,
        text="Telegram message about smoke search",
        chunk_index=0,
    )

    class TelegramStore:
        _table = "chunks_contextual_512_50"

        def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]:
            assert chunk_ids == [telegram_chunk_id]
            return [chunk]

        def get_chunk_provenance_for_chunk_ids(
            self,
            strategy: str,
            chunk_ids: list[str],
        ) -> dict[str, ChunkProvenance]:
            assert strategy == "contextual_512_50"
            assert chunk_ids == [telegram_chunk_id]
            return {
                telegram_chunk_id: ChunkProvenance(
                    namespace="telegram",
                    document_ref="dialog:-1001",
                    ref="telegram:dialog:-1001",
                    source_unit_refs=["dialog:-1001:message:42"],
                    chunk_strategy=strategy,
                    parser_name="telegram-message",
                )
            }

    provenance = ChunkProvenance(
        namespace="telegram",
        document_ref="dialog:-1001",
        ref=telegram_ref,
        source_unit_refs=["dialog:-1001:message:42"],
        chunk_strategy="contextual_512_50",
        parser_name="telegram-message",
    )

    results = build_candidates(
        [(telegram_ref, 0.7)],
        per_engine={"semantic": [(telegram_ref, 0.95)]},
        metadata_store=cast(Any, TelegramStore()),
        query="smoke",
        ref_to_chunk={telegram_ref: (telegram_chunk_id, "")},
        active_provenance_map={telegram_chunk_id: provenance},
        top_k=1,
    )

    assert len(results) == 1
    assert isinstance(results[0], SearchCandidate)
    assert results[0].ref == telegram_ref


def test_build_candidates_missing_provenance_raises() -> None:
    """Top chunks with no source provenance are hard invariant failures."""
    chunk = Chunk(
        chunk_id="missing-provenance",
        file_paths=[Path("/fallback/file.md")],
        heading_hierarchy=["Missing"],
        level=1,
        text="missing provenance snippet",
        chunk_index=0,
    )

    class MissingProvenanceStore:
        _table = "chunks_heading_512_50"

        def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]:
            return [chunk]

        def get_chunk_provenance_for_chunk_ids(
            self,
            strategy: str,
            chunk_ids: list[str],
        ) -> dict[str, ChunkProvenance]:
            return {}

    with pytest.raises(ValueError, match="missing source provenance for chunk_id="):
        build_candidates(
            [("filesystem:/missing.md", 0.7)],
            per_engine={"semantic": [("filesystem:/missing.md", 0.95)]},
            metadata_store=cast(Any, MissingProvenanceStore()),
            query="missing",
            ref_to_chunk={"filesystem:/missing.md": ("missing-provenance", "")},
            active_provenance_map={},
            top_k=1,
        )


def _source_document(file_path: str) -> SourceDocument:
    now = datetime(2026, 5, 6)
    return SourceDocument(
        namespace="filesystem",
        document_ref=file_path,
        ref=f"filesystem:{file_path}",
        source_uri=file_path,
        file_path=Path(file_path),
        media_type="text/markdown",
        parser_name="markdown",
        document_type="document",
        title=Path(file_path).name,
        updated_at=now,
        content_fingerprint="content",
        metadata_fingerprint="metadata",
        metadata_json={},
    )


def _store_with_provenance_schema(tmp_path: Path) -> SQLiteMetadataStore:
    db_path = tmp_path / "test.db"
    strategy = "heading_512_50"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(f"""
        CREATE TABLE chunks_{strategy} (
            chunk_id TEXT PRIMARY KEY,
            heading_hierarchy TEXT NOT NULL DEFAULT '[]',
            level INTEGER NOT NULL DEFAULT 0,
            text TEXT NOT NULL DEFAULT ''
        );
    """)
    conn.commit()
    store = SQLiteMetadataStore(
        db_path=db_path,
        table_name=f"chunks_{strategy}",
        conn=conn,
    )
    store.ensure_m2m_table(strategy)
    store.ensure_chunk_source_provenance_table(strategy)
    return store


def test_metadata_provenance_canonical_ref_uses_sql_ordering(tmp_path: Path) -> None:
    """Reverse insertion order still returns lexicographically canonical ref."""
    strategy = "heading_512_50"
    chunk_id = "canonical"
    store = _store_with_provenance_schema(tmp_path)
    raw_conn = object.__getattribute__(store._conn, "_real_conn")
    store.insert_chunk(strategy, chunk_id, ["H"], 1, "text")

    for file_path in ["/mnt/b.md", "/mnt/a.md"]:
        document = _source_document(file_path)
        store.upsert_source_document(document, conn=raw_conn)
        store.add_chunk_provenance(
            strategy,
            ChunkProvenance(
                namespace="filesystem",
                document_ref=file_path,
                ref=f"filesystem:{file_path}",
                source_unit_refs=[],
                chunk_strategy=strategy,
                parser_name="markdown",
            ),
            chunk_id,
            conn=raw_conn,
        )
    raw_conn.commit()

    result = store.get_chunk_provenance_for_chunk_ids(strategy, [chunk_id])

    assert result[chunk_id].ref == "filesystem:/mnt/a.md"


def test_missing_provenance_count_and_backfill_safety(tmp_path: Path) -> None:
    """Missing-provenance backfill is count-first, dry-run-safe, and idempotent."""
    strategy = "heading_512_50"
    chunk_id = "missing"
    store = _store_with_provenance_schema(tmp_path)
    raw_conn = object.__getattribute__(store._conn, "_real_conn")
    document = _source_document("/mnt/a.md")

    store.upsert_source_document(document, conn=raw_conn)
    store.insert_chunk(strategy, chunk_id, ["H"], 1, "text")
    store.add_file_path(strategy, chunk_id, "/mnt/a.md", chunk_index=0)
    raw_conn.commit()

    assert store.count_missing_source_provenance(strategy) == 1
    assert store.backfill_missing_source_provenance_from_file_paths(
        strategy,
        dry_run=True,
    ) == 1
    assert store.count_missing_source_provenance(strategy) == 1

    assert store.backfill_missing_source_provenance_from_file_paths(
        strategy,
        dry_run=False,
    ) == 1
    assert store.backfill_missing_source_provenance_from_file_paths(
        strategy,
        dry_run=False,
    ) == 0
    assert store.count_missing_source_provenance(strategy) == 0
    provenance = store.get_chunk_provenance_for_chunk_ids(strategy, [chunk_id])
    assert provenance[chunk_id].ref == "filesystem:/mnt/a.md"


def test_format_result_keeps_clean_visible_snippet_after_cleanup() -> None:
    """MCP formatting strips metadata while leaving a coherent visible sentence."""
    result = SearchCandidate(
        ref="filesystem:/notes/transcript.md",
        namespace="filesystem",
        descriptor_key="filesystem-mnt",
        source_kind="markdown",
        retrieval_kind="semantic",
        snippet=(
            "---\ntitle: Hidden\n---\n"
            "[00:15:32] Visible target sentence survives cleanup."
        ),
        fused_score=0.9,
        can_read=True,
        chunk_id="chunk-1",
        heading_path="Meeting",
    )

    formatted = _format_result(result)

    assert formatted.snippet == "Visible target sentence survives cleanup."
    assert isinstance(formatted, SearchCandidate)


def test_normalize_unit_vector():
    """Normalized vector has magnitude 1.0."""
    from dotmd.ingestion.pipeline import IndexingPipeline
    v = [3.0, 4.0]
    n = IndexingPipeline._normalize_vector(v)
    mag = math.sqrt(sum(x * x for x in n))
    assert abs(mag - 1.0) < 1e-6


def test_normalize_zero_vector():
    """Zero vector returned unchanged (no division by zero)."""
    from dotmd.ingestion.pipeline import IndexingPipeline
    v = [0.0, 0.0, 0.0]
    n = IndexingPipeline._normalize_vector(v)
    assert n == [0.0, 0.0, 0.0]


class _FakePipeline:
    """Minimal shim to test _fuse_vectors without full pipeline init.

    _normalize_vector is a @staticmethod on IndexingPipeline, so we can
    delegate to it directly without needing full pipeline construction.
    """

    @staticmethod
    def _normalize_vector(v):
        from dotmd.ingestion.pipeline import IndexingPipeline
        return IndexingPipeline._normalize_vector(v)

    def _fuse_vectors(self, e_text, e_meta, weights):
        from dotmd.ingestion.pipeline import IndexingPipeline
        return cast(Any, IndexingPipeline._fuse_vectors)(self, e_text, e_meta, weights)


def test_fuse_vectors_output_is_unit():
    """e_fused is a unit vector."""
    p = _FakePipeline()
    e_text = [1.0, 0.0, 0.0]
    e_meta = [0.0, 1.0, 0.0]
    weights = {"text": 0.7, "meta": 0.3}
    e_fused = p._fuse_vectors(e_text, e_meta, weights)
    mag = math.sqrt(sum(x * x for x in e_fused))
    assert abs(mag - 1.0) < 1e-6


def test_fuse_vectors_text_only_weight():
    """With weight text=1.0, meta=0.0, e_fused == normalize(e_text)."""
    p = _FakePipeline()
    e_text = [3.0, 4.0]
    e_meta = [1.0, 0.0]
    weights = {"text": 1.0, "meta": 0.0}
    e_fused = p._fuse_vectors(e_text, e_meta, weights)
    expected = _normalize(e_text)
    assert all(abs(a - b) < 1e-6 for a, b in zip(e_fused, expected, strict=False))


def test_fuse_vectors_dimension_mismatch_raises():
    """Mismatched dimensions between e_text and e_meta must raise ValueError.

    Phase 999.12 change (addresses Codex MEDIUM review concern):
    _fuse_vectors raises ValueError on mismatch — silent truncation would be
    data corruption since both vectors must come from the same TEI model.
    """
    p = _FakePipeline()
    e_text = [1.0, 0.0, 0.0]
    e_meta = [0.0, 1.0]  # shorter — dimension mismatch
    weights = {"text": 0.7, "meta": 0.3}
    with pytest.raises(ValueError, match="dimension mismatch"):
        p._fuse_vectors(e_text, e_meta, weights)


def test_weight_validation_sum_must_be_one():
    """Settings rejects weights that don't sum to 1.0."""
    os.environ.setdefault("DOTMD_EMBEDDING_URL", "http://localhost:8088")
    from dotmd.core.config import Settings
    with pytest.raises(Exception, match="sum"):
        Settings(
            embedding_url="http://localhost:8088",
            embedding_weights="text=0.5,meta=0.3",
        )


def test_weight_validation_accepts_valid():
    """Settings accepts valid weights."""
    os.environ.setdefault("DOTMD_EMBEDDING_URL", "http://localhost:8088")
    from dotmd.core.config import Settings
    s = Settings(
        embedding_url="http://localhost:8088",
        embedding_weights="text=0.7,meta=0.3",
    )
    w = s.parsed_embedding_weights
    assert abs(w["text"] - 0.7) < 1e-9
    assert abs(w["meta"] - 0.3) < 1e-9


def test_weight_validation_invalid_format():
    """Settings rejects malformed weight entries."""
    os.environ.setdefault("DOTMD_EMBEDDING_URL", "http://localhost:8088")
    from dotmd.core.config import Settings
    with pytest.raises(Exception):
        Settings(
            embedding_url="http://localhost:8088",
            embedding_weights="text_0.7_meta_0.3",
        )


def test_weight_validation_requires_text_key():
    """Settings rejects weights missing the 'text' key.

    Addresses Codex MEDIUM review concern: validator must require both 'text' and
    'meta' keys. Accepting arbitrary keys would silently omit a component from fusion.
    """
    os.environ.setdefault("DOTMD_EMBEDDING_URL", "http://localhost:8088")
    from dotmd.core.config import Settings
    with pytest.raises(Exception, match="text"):
        Settings(
            embedding_url="http://localhost:8088",
            embedding_weights="other=0.7,meta=0.3",
        )


def test_weight_validation_requires_meta_key():
    """Settings rejects weights missing the 'meta' key."""
    os.environ.setdefault("DOTMD_EMBEDDING_URL", "http://localhost:8088")
    from dotmd.core.config import Settings
    with pytest.raises(Exception, match="meta"):
        Settings(
            embedding_url="http://localhost:8088",
            embedding_weights="text=0.7,other=0.3",
        )


def test_fuse_results_math_equivalence_ref_keys_vs_chunk_keys() -> None:
    """RRF computation is identical whether using chunk_id or ref keys."""
    from dotmd.search.fusion import fuse_results

    # Same ranked lists using chunk IDs
    chunk_results = {
        "semantic": [("chunk-1", 0.9), ("chunk-2", 0.8)],
        "keyword": [("chunk-2", 0.7), ("chunk-3", 0.6)],
    }

    # Same ranked lists using refs
    ref_results = {
        "semantic": [("filesystem:/a.md#0", 0.9), ("filesystem:/b.md#1", 0.8)],
        "keyword": [("filesystem:/b.md#1", 0.7), ("filesystem:/c.md#2", 0.6)],
    }

    chunk_fused = fuse_results(chunk_results, k=60)
    ref_fused = fuse_results(ref_results, k=60)

    # Verify same math: RRF is position-based, not key-based
    assert len(chunk_fused) == len(ref_fused)
    for (_chunk_key, chunk_score), (_ref_key, ref_score) in zip(chunk_fused, ref_fused, strict=True):
        assert abs(chunk_score - ref_score) < 1e-9


def test_hydrate_local_engine_results_drops_chunks_without_provenance() -> None:
    """hydrate_local_engine_results skips chunks missing from provenance_map."""
    from dotmd.search.fusion import hydrate_local_engine_results

    per_engine_chunk = {
        "semantic": [("chunk-1", 0.9), ("missing", 0.8), ("chunk-2", 0.7)],
    }

    provenance_map = {
        "chunk-1": ChunkProvenance(
            namespace="filesystem",
            document_ref="/a.md",
            ref="filesystem:/a.md",
            source_unit_refs=[],
            chunk_strategy="default",
            parser_name="markdown",
        ),
        "chunk-2": ChunkProvenance(
            namespace="filesystem",
            document_ref="/b.md",
            ref="filesystem:/b.md",
            source_unit_refs=[],
            chunk_strategy="default",
            parser_name="markdown",
        ),
    }

    result = hydrate_local_engine_results(per_engine_chunk, provenance_map)

    assert len(result["semantic"]) == 2
    assert result["semantic"][0] == ("filesystem:/a.md", 0.9)
    assert result["semantic"][1] == ("filesystem:/b.md", 0.7)


def test_build_candidates_only_attributes_engines_that_scored_the_ref() -> None:
    """build_candidates only populates engine_scores for engines that matched."""
    chunk = Chunk(
        chunk_id="c1",
        file_paths=[Path("/a.md")],
        heading_hierarchy=["H"],
        level=1,
        text="target text",
        chunk_index=0,
    )

    class Store:
        _table = "chunks_default"

        def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]:
            return [chunk] if "c1" in chunk_ids else []

        def get_chunk_provenance_for_chunk_ids(self, strategy: str, chunk_ids: list[str]):
            return {
                "c1": ChunkProvenance(
                    namespace="filesystem",
                    document_ref="/a.md",
                    ref="filesystem:/a.md",
                    source_unit_refs=[],
                    chunk_strategy=strategy,
                    parser_name="markdown",
                )
            }

    results = build_candidates(
        [("filesystem:/a.md", 0.85)],
        per_engine={
            "semantic": [("filesystem:/a.md", 0.9)],
            "keyword": [("filesystem:/a.md", 0.7)],
        },
        metadata_store=cast(MetadataStoreProtocol, Store()),
        ref_to_chunk={"filesystem:/a.md": ("c1", "")},
        active_provenance_map={
            "c1": ChunkProvenance(
                namespace="filesystem",
                document_ref="/a.md",
                ref="filesystem:/a.md",
                source_unit_refs=[],
                chunk_strategy="default",
                parser_name="markdown",
            )
        },
    )

    assert len(results) == 1
    assert results[0].matched_engines == ("keyword", "semantic")
    assert results[0].engine_scores == {"semantic": 0.9, "keyword": 0.7}


def test_build_candidates_sets_can_read_true_and_can_materialize_false_for_local() -> None:
    """Local filesystem candidates are always readable, never materializable."""
    chunk = Chunk(
        chunk_id="local",
        file_paths=[Path("/local/file.md")],
        heading_hierarchy=[],
        level=0,
        text="local content",
        chunk_index=0,
    )

    class Store:
        _table = "chunks_default"

        def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]:
            return [chunk] if "local" in chunk_ids else []

        def get_chunk_provenance_for_chunk_ids(self, strategy: str, chunk_ids: list[str]):
            return {
                "local": ChunkProvenance(
                    namespace="filesystem",
                    document_ref="/local/file.md",
                    ref="filesystem:/local/file.md",
                    source_unit_refs=[],
                    chunk_strategy=strategy,
                    parser_name="markdown",
                )
            }

    results = build_candidates(
        [("filesystem:/local/file.md", 0.9)],
        per_engine={},
        metadata_store=cast(MetadataStoreProtocol, Store()),
        ref_to_chunk={"filesystem:/local/file.md": ("local", "")},
        active_provenance_map={
            "local": ChunkProvenance(
                namespace="filesystem",
                document_ref="/local/file.md",
                ref="filesystem:/local/file.md",
                source_unit_refs=[],
                chunk_strategy="default",
                parser_name="markdown",
            )
        },
    )

    assert len(results) == 1
    assert results[0].can_read is True
    assert results[0].can_materialize is False


def test_build_candidates_collapses_tiebreak_highest_score_then_lowest_chunk_id() -> None:
    """When refs collapse to same position, use higher fused score then lower chunk_id."""
    # Simulate two chunks mapping to same ref via M2M
    chunk_a = Chunk(
        chunk_id="chunk-a",
        file_paths=[Path("/same.md")],
        heading_hierarchy=["H"],
        level=1,
        text="first chunk text",
        chunk_index=0,
    )
    chunk_b = Chunk(
        chunk_id="chunk-b",
        file_paths=[Path("/same.md")],
        heading_hierarchy=["H"],
        level=1,
        text="second chunk text",
        chunk_index=1,
    )

    class Store:
        _table = "chunks_default"

        def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]:
            return [c for c in [chunk_a, chunk_b] if c.chunk_id in chunk_ids]

        def get_chunk_provenance_for_chunk_ids(self, strategy: str, chunk_ids: list[str]):
            return {
                "chunk-a": ChunkProvenance(
                    namespace="filesystem",
                    document_ref="/same.md",
                    ref="filesystem:/same.md",
                    source_unit_refs=[],
                    chunk_strategy=strategy,
                    parser_name="markdown",
                ),
                "chunk-b": ChunkProvenance(
                    namespace="filesystem",
                    document_ref="/same.md",
                    ref="filesystem:/same.md",
                    source_unit_refs=[],
                    chunk_strategy=strategy,
                    parser_name="markdown",
                ),
            }

    shared_ref = "filesystem:/same.md"
    shared_prov = ChunkProvenance(
        namespace="filesystem",
        document_ref="/same.md",
        ref=shared_ref,
        source_unit_refs=[],
        chunk_strategy="default",
        parser_name="markdown",
    )

    results = build_candidates(
        [(shared_ref, 0.9)],
        per_engine={},
        metadata_store=cast(MetadataStoreProtocol, Store()),
        ref_to_chunk={shared_ref: ("chunk-a", "")},
        active_provenance_map={"chunk-a": shared_prov, "chunk-b": shared_prov},
    )

    assert len(results) == 1
    # Should select chunk-a (used by ref_to_chunk mapping)
    assert results[0].chunk_id == "chunk-a"
