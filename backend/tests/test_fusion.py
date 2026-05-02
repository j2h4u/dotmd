"""Tests for fusion math and weight validation (Phase 999.12)."""
import math
import os
from pathlib import Path
from typing import Any, cast

import pytest

from dotmd.core.models import Chunk, SearchResult
from dotmd.mcp_server import _format_result
from dotmd.search.fusion import _extract_best_snippet, build_search_results
from dotmd.storage.base import MetadataStoreProtocol


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


def test_build_search_results_uses_boundary_aware_snippet() -> None:
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

    results = build_search_results(
        [("chunk-1", 0.9)],
        {"semantic": [("chunk-1", 0.8)]},
        cast(MetadataStoreProtocol, store),
        query="target",
        snippet_length=35,
    )

    assert len(results) == 1
    assert results[0].snippet.startswith("...The search target")
    assert "target appears" in results[0].snippet


def test_format_result_keeps_clean_visible_snippet_after_cleanup() -> None:
    """MCP formatting strips metadata while leaving a coherent visible sentence."""
    result = SearchResult(
        chunk_id="chunk-1",
        file_paths=[Path("/notes/transcript.md")],
        heading_path="Meeting",
        snippet=(
            "---\ntitle: Hidden\n---\n"
            "[00:15:32] Visible target sentence survives cleanup."
        ),
        fused_score=0.9,
    )

    formatted = _format_result(result)

    assert formatted.snippet == "Visible target sentence survives cleanup."


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
