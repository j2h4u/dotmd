"""Markdown-aware chunking of document content."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from dotmd.core.models import Chunk
from dotmd.utils.text import estimate_tokens, split_sentences

logger = logging.getLogger(__name__)

# Matches ATX headings: one or more '#' characters followed by a space and text.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def _make_chunk_id(file_path: Path, chunk_index: int) -> str:
    """Deterministic chunk identifier from file path and index."""
    payload = f"{file_path}:{chunk_index}"
    return hashlib.md5(payload.encode()).hexdigest()


# Matches transcript speaker turns: [00:12:34] **Speaker Name:**
_SPEAKER_TURN_RE = re.compile(r"\n(?=\[\d{2}:\d{2}:\d{2}\]\s*\*\*)")


def _pre_split_segments(text: str) -> list[str]:
    """Break text into natural segments before sentence splitting.

    Transcript speaker turns and paragraph breaks are stronger boundaries
    than sentence-level punctuation.  Returns segments that the existing
    ``_split_with_overlap`` groups into token-budget chunks.

    Detection order:
    1. Speaker turns (``[HH:MM:SS] **Name:**``) — meetings with diarization
    2. Double newlines — personal voicenotes, paragraph breaks
    3. Fallback — return text as-is (docs without structure)
    """
    # Meetings: split on speaker turn boundaries
    if len(_SPEAKER_TURN_RE.findall(text)) >= 3:
        segments = _SPEAKER_TURN_RE.split(text)
        return [s.strip() for s in segments if s.strip()]

    # Personal voicenotes / other: split on double newlines
    if text.count("\n\n") >= 3:
        segments = text.split("\n\n")
        return [s.strip() for s in segments if s.strip()]

    # Docs or short text: no pre-splitting needed
    return [text] if text.strip() else []


def _split_with_overlap(
    text: str,
    max_tokens: int,
    overlap_tokens: int,
) -> list[str]:
    """Split *text* into pieces that each fit within *max_tokens*.

    First breaks text into natural segments (speaker turns, paragraphs),
    then groups them into token-budget chunks with overlap.  Falls back
    to sentence splitting for segments that exceed the budget.
    """
    segments = _pre_split_segments(text)
    if not segments:
        return [text] if text.strip() else []

    # Flatten: if any segment is still too large, sentence-split it
    sentences: list[str] = []
    for seg in segments:
        if estimate_tokens(seg) <= max_tokens:
            sentences.append(seg)
        else:
            # Segment too large — break into sentences
            sub = split_sentences(seg)
            sentences.extend(sub if sub else [seg])

    pieces: list[str] = []
    current_sentences: list[str] = []
    current_tokens: int = 0

    for sentence in sentences:
        sent_tokens = estimate_tokens(sentence)

        if current_sentences and current_tokens + sent_tokens > max_tokens:
            pieces.append(" ".join(current_sentences))

            # Build overlap from the tail of current_sentences.
            overlap_sents: list[str] = []
            overlap_tok = 0
            for s in reversed(current_sentences):
                s_tok = estimate_tokens(s)
                if overlap_tok + s_tok > overlap_tokens and overlap_sents:
                    break
                overlap_sents.insert(0, s)
                overlap_tok += s_tok

            current_sentences = overlap_sents
            current_tokens = overlap_tok

        current_sentences.append(sentence)
        current_tokens += sent_tokens

    if current_sentences:
        pieces.append(" ".join(current_sentences))

    return pieces


def _parse_sections(content: str) -> list[tuple[int, str, str, int]]:
    """Parse markdown into sections delimited by headings.

    Returns a list of ``(level, heading_text, body, char_offset)`` tuples.
    Level ``0`` represents text that appears before the first heading.
    """
    sections: list[tuple[int, str, str, int]] = []
    last_end = 0
    last_level = 0
    last_heading = ""

    for match in _HEADING_RE.finditer(content):
        # Capture the text *before* this heading as the previous section body.
        body = content[last_end : match.start()]
        if last_end == 0 and body.strip():
            # Text before the first heading.
            sections.append((0, "", body, 0))
        elif last_end > 0:
            sections.append((last_level, last_heading, body, last_end))

        last_level = len(match.group(1))
        last_heading = match.group(2).strip()
        last_end = match.end()

    # Remaining text after the last heading (or the entire file if no headings).
    trailing = content[last_end:]
    if last_end == 0:
        # No headings found at all – treat the whole file as one section.
        sections.append((0, "", trailing, 0))
    else:
        sections.append((last_level, last_heading, trailing, last_end))

    return sections


def chunk_file(
    file_path: Path,
    content: str,
    max_tokens: int = 512,
    overlap_tokens: int = 50,
) -> list[Chunk]:
    """Split a markdown document into semantically meaningful chunks.

    The algorithm first splits on ATX headings (``#`` through ``######``),
    tracking the heading hierarchy so each chunk knows its context.
    Sections that exceed *max_tokens* are further split at sentence
    boundaries with *overlap_tokens* of shared context between consecutive
    sub-chunks.

    Parameters
    ----------
    file_path:
        Path to the source file (used for IDs and metadata, not read here).
    content:
        Full text content of the markdown file.
    max_tokens:
        Soft upper bound on chunk size expressed as estimated tokens.
    overlap_tokens:
        Number of overlapping tokens between consecutive sub-chunks created
        by sentence splitting.

    Returns
    -------
    list[Chunk]
        Ordered list of chunks covering the entire document.
    """
    sections = _parse_sections(content)
    chunks: list[Chunk] = []
    chunk_index = 0

    # Maintain a stack-like list mapping heading level -> heading text.
    # Index 0 is unused (level 0 = no heading); indices 1-6 correspond to
    # ``#`` through ``######``.
    hierarchy: list[str] = [""] * 7
    for level, heading, body, char_offset in sections:
        if level > 0:
            hierarchy[level] = heading
            # Clear deeper headings when a higher-level heading appears.
            for i in range(level + 1, 7):
                hierarchy[i] = ""

        current_hierarchy = [h for h in hierarchy[1 : level + 1] if h] if level > 0 else []

        # Prepend the full heading path so search engines can match on
        # contextual terms (e.g. "principles" matches each principle chunk).
        body_stripped = body.strip()
        if not body_stripped and not heading:
            continue

        parts: list[str] = []
        if current_hierarchy:
            parts.append(" > ".join(current_hierarchy))
        if body_stripped:
            parts.append(body_stripped)
        section_text = "\n\n".join(parts) if parts else ""
        if not section_text:
            continue

        token_count = estimate_tokens(section_text)

        if token_count <= max_tokens:
            chunks.append(
                Chunk(
                    chunk_id=_make_chunk_id(file_path, chunk_index),
                    file_path=file_path,
                    heading_hierarchy=list(current_hierarchy),
                    level=level,
                    text=section_text,
                    chunk_index=chunk_index,
                    char_offset=char_offset,
                )
            )
            chunk_index += 1
        else:
            # Section too large – sentence-split with overlap.
            sub_texts = _split_with_overlap(section_text, max_tokens, overlap_tokens)
            for sub_text in sub_texts:
                chunks.append(
                    Chunk(
                        chunk_id=_make_chunk_id(file_path, chunk_index),
                        file_path=file_path,
                        heading_hierarchy=list(current_hierarchy),
                        level=level,
                        text=sub_text,
                        chunk_index=chunk_index,
                        char_offset=char_offset,
                    )
                )
                chunk_index += 1

    logger.debug(
        "Chunked %s into %d chunks (max_tokens=%d, overlap=%d)",
        file_path,
        len(chunks),
        max_tokens,
        overlap_tokens,
    )
    return chunks
