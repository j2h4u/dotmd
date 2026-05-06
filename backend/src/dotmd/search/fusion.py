"""Reciprocal Rank Fusion and search-result construction.

This module provides two functions:

- :func:`fuse_results` -- merge ranked lists from multiple search engines
  using Reciprocal Rank Fusion (RRF).
- :func:`build_search_results` -- hydrate fused scores into full
  :class:`SearchResult` objects by looking up chunk metadata.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol, cast

from dotmd.core.models import ChunkProvenance, SearchResult

if TYPE_CHECKING:
    from dotmd.storage.base import MetadataStoreProtocol

logger = logging.getLogger(__name__)


class _ChunkProvenanceBatchStore(Protocol):
    """Optional metadata-store extension for batch source-provenance hydration."""

    def get_chunk_provenance_for_chunk_ids(
        self,
        strategy: str,
        chunk_ids: Sequence[str],
    ) -> dict[str, ChunkProvenance]:
        """Return canonical provenance for chunk IDs under the given strategy."""
        ...


def _extract_best_snippet(text: str, query: str, length: int = 300) -> str:
    """Find the window of *length* chars in *text* with the most query term overlap."""
    if len(text) <= length:
        return text

    query_tokens = set(re.findall(r"\w+", query.lower()))
    if not query_tokens:
        # Fallback to start of text
        return _truncate(text, length)

    # Score each window position (slide by sentences/words for speed)
    words = text.split()
    best_score = -1
    best_start = 0

    # Build character position index for word boundaries
    char_pos = 0
    word_starts: list[int] = []
    for w in words:
        idx = text.index(w, char_pos)
        word_starts.append(idx)
        char_pos = idx + len(w)

    for _i, start in enumerate(word_starts):
        end = start + length
        if end > len(text):
            start = max(0, len(text) - length)
            end = len(text)

        window = text[start:end].lower()
        score = sum(1 for t in query_tokens if t in window)

        if score > best_score:
            best_score = score
            best_start = start

        if end >= len(text):
            break

    focus_start = _find_query_focus_start(text, best_start, length, query_tokens)
    return _expand_snippet_to_boundaries(text, best_start, focus_start, length)


def _find_query_focus_start(
    text: str,
    best_start: int,
    length: int,
    query_tokens: set[str],
) -> int:
    """Find the first query token inside the selected relevance window."""
    window_end = min(len(text), best_start + length)
    for match in re.finditer(r"\w+", text[best_start:window_end]):
        if match.group(0).lower() in query_tokens:
            return best_start + match.start()
    return best_start


def _expand_snippet_to_boundaries(
    text: str,
    best_start: int,
    focus_start: int,
    length: int,
) -> str:
    """Expand the selected relevance window to simple sentence boundaries."""
    hard_cap = length * 2
    window_end = min(len(text), best_start + length)
    left = _find_left_boundary(text, focus_start)
    right = _find_right_boundary(text, window_end)
    body = text[left:right].strip()

    if len(body) > hard_cap:
        return _bounded_window_snippet(text, best_start, length)

    prefix = "..." if left > 0 else ""
    suffix = "..." if right < len(text) else ""
    return prefix + body + suffix


def _find_left_boundary(text: str, start: int) -> int:
    """Return the nearest simple boundary at or before *start*."""
    if start <= 0:
        return 0

    candidates = [0]
    paragraph = text.rfind("\n\n", 0, start + 1)
    if paragraph != -1:
        candidates.append(_skip_boundary_space(text, paragraph + 2))

    for match in re.finditer(r"[.?!]", text[:start]):
        candidates.append(_skip_boundary_space(text, match.end()))

    return max(candidate for candidate in candidates if candidate <= start)


def _find_right_boundary(text: str, end: int) -> int:
    """Return the nearest simple boundary at or after *end*."""
    if end >= len(text):
        return len(text)

    candidates = [len(text)]
    paragraph = text.find("\n\n", end)
    if paragraph != -1:
        candidates.append(paragraph)

    match = re.search(r"[.?!]", text[end:])
    if match is not None:
        candidates.append(end + match.end())

    return min(candidates)


def _skip_boundary_space(text: str, index: int) -> int:
    """Move from a boundary marker to the next non-whitespace sentence char."""
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _bounded_window_snippet(text: str, best_start: int, length: int) -> str:
    """Bounded fallback around the already selected relevance window."""
    snippet_text = text[best_start : best_start + length]

    prefix = "..." if best_start > 0 else ""
    suffix = "..." if best_start + length < len(text) else ""

    if suffix:
        last_space = snippet_text.rfind(" ")
        if last_space > len(snippet_text) * 0.8:
            snippet_text = snippet_text[:last_space]

    return prefix + snippet_text + suffix


def _truncate(text: str, length: int) -> str:
    """Word-aware truncation fallback."""
    truncated = text[:length]
    last_space = truncated.rfind(" ")
    if last_space > length * 0.8:
        return truncated[:last_space] + "..."
    return truncated + "..."


# Score field names on SearchResult keyed by canonical engine name.
_ENGINE_SCORE_FIELDS: dict[str, str] = {
    "semantic": "semantic_score",
    "keyword": "keyword_score",
    "graph": "graph_score",
    "graph_direct": "graph_direct_score",
}


def fuse_results(
    ranked_lists: dict[str, list[tuple[str, float]]],
    k: int = 60,
    engine_weights: dict[str, float] | None = None,
) -> list[tuple[str, float]]:
    """Merge multiple ranked lists using Reciprocal Rank Fusion.

    For every chunk that appears in at least one list the fused score is
    computed as::

        score = sum(weight_i / (k + rank_i))

    where *rank_i* is the **1-based** position of the chunk in each
    engine's result list and *weight_i* is the engine weight (default 1.0).

    Parameters
    ----------
    ranked_lists:
        A mapping of ``engine_name`` to a list of ``(chunk_id, score)``
        pairs, ordered by descending relevance.
    k:
        The RRF constant (default ``60``).  Higher values dampen the
        influence of top-ranked results.
    engine_weights:
        Optional per-engine weights.  Engines not listed default to 1.0.
        Use higher weights for engines that discover unique content
        (e.g. ``{"graph": 1.5}``).

    Returns
    -------
    list[tuple[str, float]]
        A list of ``(chunk_id, fused_score)`` pairs sorted by
        descending fused score.
    """
    weights = engine_weights or {}
    rrf_scores: dict[str, float] = {}

    for engine, results in ranked_lists.items():
        w = weights.get(engine, 1.0)
        for rank_0, (chunk_id, _score) in enumerate(results):
            rank = rank_0 + 1  # 1-based
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + w / (k + rank)

    return sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)


def build_search_results(
    fused: list[tuple[str, float]],
    per_engine: dict[str, list[tuple[str, float]]],
    metadata_store: MetadataStoreProtocol,
    query: str = "",
    top_k: int = 10,
    snippet_length: int = 300,
) -> list[SearchResult]:
    """Convert fused scores into fully hydrated :class:`SearchResult` objects.

    For each of the *top_k* fused results the corresponding chunk is
    looked up in *metadata_store* to populate the heading path, snippet,
    and per-engine scores.

    Parameters
    ----------
    fused:
        Output of :func:`fuse_results`.
    per_engine:
        The same ``ranked_lists`` dict passed to :func:`fuse_results`,
        used to attribute per-engine scores.
    metadata_store:
        A store satisfying :class:`MetadataStoreProtocol`.
    top_k:
        Maximum number of results to return.
    snippet_length:
        Maximum length for the text snippet (default 300 characters).
        Truncation is word-aware to avoid cutting mid-word.

    Returns
    -------
    list[SearchResult]
        Up to *top_k* search results, ordered by descending fused score.
    """
    # Pre-index per-engine scores for O(1) lookup.
    engine_scores: dict[str, dict[str, float]] = {}
    for engine, engine_results in per_engine.items():
        engine_scores[engine] = dict(engine_results)

    top_ids = [cid for cid, _ in fused[:top_k]]
    chunks_by_id = {c.chunk_id: c for c in metadata_store.get_chunks(top_ids)}

    strategy = getattr(metadata_store, "_table", "").removeprefix("chunks_")
    provenance_map: dict[str, ChunkProvenance] = {}
    if strategy and hasattr(metadata_store, "get_chunk_provenance_for_chunk_ids"):
        batch_store = cast(_ChunkProvenanceBatchStore, metadata_store)
        provenance_map = batch_store.get_chunk_provenance_for_chunk_ids(
            strategy,
            top_ids,
        )

    results: list[SearchResult] = []
    for chunk_id, fused_score in fused[:top_k]:
        chunk = chunks_by_id.get(chunk_id)
        if chunk is None:
            continue

        heading_path = " > ".join(chunk.heading_hierarchy) if chunk.heading_hierarchy else ""

        snippet = _extract_best_snippet(chunk.text, query, snippet_length)

        provenance = provenance_map.get(chunk_id)
        if provenance is None:
            raise ValueError(f"missing source provenance for chunk_id={chunk_id}")

        # Determine which engines matched and their individual scores.
        matched_engines: list[str] = []
        per_engine_kwargs: dict[str, float | None] = {}
        for engine_name, field_name in _ENGINE_SCORE_FIELDS.items():
            score = engine_scores.get(engine_name, {}).get(chunk_id)
            per_engine_kwargs[field_name] = score
            if score is not None:
                matched_engines.append(engine_name)

        results.append(
            SearchResult(
                chunk_id=chunk_id,
                ref=provenance.ref,
                heading_path=heading_path,
                snippet=snippet,
                fused_score=fused_score,
                matched_engines=sorted(matched_engines),
                **per_engine_kwargs,  # type: ignore[arg-type]
            )
        )

    return results
