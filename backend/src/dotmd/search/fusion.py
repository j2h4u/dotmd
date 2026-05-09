"""Reciprocal Rank Fusion and search-result construction.

This module provides three functions:

- :func:`fuse_results` -- merge ranked lists from multiple search engines
  using Reciprocal Rank Fusion (RRF).
- :func:`hydrate_local_engine_results` -- convert chunk-keyed engine results
  to ref-keyed results using provenance mapping.
- :func:`build_candidates` -- hydrate fused scores into full
  :class:`SearchCandidate` objects by looking up chunk metadata.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

from dotmd.core.models import ChunkProvenance, SearchCandidate

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




def _public_ref_for_provenance(provenance: ChunkProvenance) -> str:
    if provenance.namespace == "telegram" and len(provenance.source_unit_refs) == 1:
        return f"telegram:{provenance.source_unit_refs[0]}"
    return provenance.ref


def fuse_results(
    ranked_lists: dict[str, list[tuple[str, float]]],
    k: int = 60,
    engine_weights: dict[str, float] | None = None,
) -> list[tuple[str, float]]:
    """Merge multiple ranked lists using Reciprocal Rank Fusion.

    For every ref that appears in at least one list the fused score is
    computed as::

        score = sum(weight_i / (k + rank_i))

    where *rank_i* is the **1-based** position of the ref in each
    engine's result list and *weight_i* is the engine weight (default 1.0).

    Parameters
    ----------
    ranked_lists:
        A mapping of ``engine_name`` to a list of ``(ref, score)``
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
        A list of ``(ref, fused_score)`` pairs sorted by
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


def hydrate_local_engine_results(
    per_engine_chunk: dict[str, list[tuple[str, float]]],
    provenance_map: dict[str, ChunkProvenance],
) -> dict[str, list[tuple[str, float]]]:
    """Convert per-engine chunk-keyed results to ref-keyed results.

    For each engine's ranked list of (chunk_id, score) pairs, resolve
    chunk_id to public ref using the provenance map. Drop entries without
    provenance.

    Parameters
    ----------
    per_engine_chunk:
        Dict mapping engine name to list of (chunk_id, score) pairs.
    provenance_map:
        Dict mapping chunk_id to ChunkProvenance.

    Returns
    -------
    dict[str, list[tuple[str, float]]]
        Same structure but with refs instead of chunk_ids; duplicates
        drop the lower-ranked occurrence (keep first).
    """
    result: dict[str, list[tuple[str, float]]] = {}
    for engine, chunk_results in per_engine_chunk.items():
        ref_results: list[tuple[str, float]] = []
        seen_refs: set[str] = set()
        for chunk_id, score in chunk_results:
            provenance = provenance_map.get(chunk_id)
            if provenance is None:
                continue
            ref = _public_ref_for_provenance(provenance)
            if ref not in seen_refs:
                ref_results.append((ref, score))
                seen_refs.add(ref)
        if ref_results:
            result[engine] = ref_results
    return result


def build_candidates(
    fused: list[tuple[str, float]],
    per_engine: dict[str, list[tuple[str, float]]],
    metadata_store: MetadataStoreProtocol,
    query: str = "",
    ref_to_chunk: dict[str, tuple[str, str]] | None = None,
    active_provenance_map: dict[str, ChunkProvenance] | None = None,
    top_k: int = 10,
    snippet_length: int = 300,
) -> list[SearchCandidate]:
    """Convert fused (chunk_id, score) tuples into fully hydrated SearchCandidate objects.

    For each of the *top_k* fused results the corresponding chunk is
    looked up in *metadata_store* to populate the heading path, snippet,
    and per-engine scores.

    Parameters
    ----------
    fused:
        Output of :func:`fuse_results` (list of (chunk_id, fused_score) tuples).
    per_engine:
        Dict mapping engine name to list of (chunk_id, score) pairs, after
        hydration via hydrate_local_engine_results.
    metadata_store:
        A store satisfying :class:`MetadataStoreProtocol`.
    query:
        Original query string for snippet extraction.
    ref_to_chunk:
        Pre-built mapping from chunk_id to (chunk_id, text). If None, looks up
        via metadata_store.
    active_provenance_map:
        Pre-built mapping from chunk_id to ChunkProvenance. If None, looks up
        via metadata_store.
    top_k:
        Maximum number of results to return.
    snippet_length:
        Maximum length for the text snippet (default 300 characters).

    Returns
    -------
    list[SearchCandidate]
        Up to *top_k* search candidates, ordered by descending fused score.
    """
    if ref_to_chunk is None:
        ref_to_chunk = {}
    if active_provenance_map is None:
        active_provenance_map = {}

    # Pre-index per-engine scores for O(1) ref lookup.
    engine_scores_by_ref: dict[str, dict[str, float]] = {}
    for engine, ref_results in per_engine.items():
        for ref, score in ref_results:
            if ref not in engine_scores_by_ref:
                engine_scores_by_ref[ref] = {}
            engine_scores_by_ref[ref][engine] = score

    candidates: list[SearchCandidate] = []
    for chunk_id, fused_score in fused[:top_k]:
        # Look up chunk for this chunk_id (might need multiple chunks in case of
        # multiple chunks mapping to same chunk_id; use highest fused_score winner).
        chunk_lookup_id: str | None = None
        chunk = None

        # If ref_to_chunk is provided, use it
        if chunk_id in ref_to_chunk:
            chunk_lookup_id, _text = ref_to_chunk[chunk_id]
            chunks = metadata_store.get_chunks([chunk_lookup_id])
            if chunks:
                chunk = chunks[0]
        else:
            # Fallback: search for a chunk with this chunk_id via provenance.
            # This handles looking up the chunk by checking active_provenance_map.
            if chunk_id in active_provenance_map:
                chunk_lookup_id = chunk_id
                chunks = metadata_store.get_chunks([chunk_lookup_id])
                if chunks:
                    chunk = chunks[0]

        if chunk is None:
            # Skip candidates we can't hydrate
            continue

        heading_path = " > ".join(chunk.heading_hierarchy) if chunk.heading_hierarchy else ""
        snippet = _extract_best_snippet(chunk.text, query, snippet_length)

        provenance = active_provenance_map.get(chunk_lookup_id) if chunk_lookup_id else None
        if provenance is None:
            raise ValueError(f"missing source provenance for chunk_id={chunk_lookup_id}")

        # Determine which engines matched this chunk_id
        matched_engines = tuple(sorted(engine_scores_by_ref.get(chunk_id, {}).keys()))
        engine_scores_dict = engine_scores_by_ref.get(chunk_id)

        candidates.append(
            SearchCandidate(
                ref=provenance.ref,  # Use actual ref from provenance
                namespace=provenance.namespace,
                descriptor_key="filesystem-mnt",  # Local chunks are always filesystem
                source_kind="markdown",
                retrieval_kind="semantic",  # Will be updated by service layer
                title=None,
                snippet=snippet,
                fused_score=fused_score,
                can_read=True,
                can_materialize=False,
                chunk_id=chunk_lookup_id,
                heading_path=heading_path,
                matched_engines=matched_engines,
                engine_scores=engine_scores_dict,
                provenance=provenance,
            )
        )

    return candidates
