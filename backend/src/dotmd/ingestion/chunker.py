"""Markdown-aware chunking of document content."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path

import blake3 as _blake3

from dotmd.core.models import Chunk, ChunkProvenance, DocKind
from dotmd.ingestion.content_handlers import get_handler, split_default
from dotmd.ingestion.reader import parse_frontmatter
from dotmd.utils.text import estimate_tokens, split_sentences

logger = logging.getLogger(__name__)

# Matches ATX headings: one or more '#' characters followed by a space and text.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def _make_chunk_id(body_checksum: str, chunk_index: int, chunk_strategy: str) -> str:
    """Content-addressed chunk identifier — path-independent.

    body_checksum is blake3(kind + "\n" + body) from chunk_fingerprints_{strategy}.
    Equivalent to chunk_checksum() in reader.py.

    chunk_strategy prevents collisions between heading_512_50 and
    contextual_512_50 chunks with the same body content.

    Returns 64-char blake3 hexdigest (down from 128-char blake2b).
    """
    payload = f"{body_checksum}:{chunk_index}:{chunk_strategy}"
    return _blake3.blake3(payload.encode()).hexdigest()


def _split_with_overlap(
    text: str,
    max_tokens: int,
    overlap_tokens: int,
    pre_split: Callable[[str], list[str]] = split_default,
) -> list[str]:
    """Split *text* into pieces that each fit within *max_tokens*.

    First breaks text into natural segments using *pre_split*, then
    groups them into token-budget chunks with overlap.  Falls back
    to sentence splitting for segments that exceed the budget.
    """
    segments = pre_split(text)
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
            sentences.extend(sub or [seg])

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
    content: str | None = None,
    max_tokens: int = 512,
    overlap_tokens: int = 50,
    kind: str = DocKind.DOCUMENT,
    chunk_strategy: str = "heading_512_50",
    provenance: ChunkProvenance | None = None,
) -> list[Chunk]:
    """Split a markdown document into semantically meaningful chunks.

    The algorithm first strips YAML frontmatter, then splits on ATX
    headings (``#`` through ``######``), tracking the heading hierarchy
    so each chunk knows its context.  Sections that exceed *max_tokens*
    are further split using the kind-appropriate pre-split strategy,
    with *overlap_tokens* of shared context between consecutive sub-chunks.

    Parameters
    ----------
    file_path:
        Path to the source file (used for metadata, not read here).
    content:
        Full text content of the markdown file (frontmatter will be stripped).
    max_tokens:
        Soft upper bound on chunk size expressed as estimated tokens.
    overlap_tokens:
        Number of overlapping tokens between consecutive sub-chunks created
        by sentence splitting.
    kind:
        Document kind from frontmatter (e.g. ``"meeting_transcript"``).
        Selects the pre-split strategy for large sections.
    chunk_strategy:
        Strategy name used in chunk_id derivation — prevents ID collisions
        between heading_512_50 and contextual_512_50 chunks with identical body.
    provenance:
        Optional caller-owned source provenance to attach to each returned
        chunk. When omitted, chunks remain unannotated.

    Returns
    -------
    list[Chunk]
        Ordered list of chunks covering the entire document.
    """
    # If content is not supplied, read it from disk.
    if content is None:
        content = file_path.read_text(encoding="utf-8")

    # ADR: Strip YAML frontmatter before chunking so raw YAML never leaks
    # into chunk text. Frontmatter metadata reaches search engines through
    # structured channels (graph entities, keyword metadata, embedding prefix)
    # rather than as accidental text content that pollutes BM25/embeddings.
    _, body = parse_frontmatter(content)

    # Compute body_checksum for content-addressed chunk IDs.
    # Formula: blake2b(kind + "\n" + body) — matches chunk_fingerprints_{strategy}.checksum.
    body_checksum = _blake3.blake3(f"{kind}\n{body}".encode()).hexdigest()

    handler = get_handler(kind)
    sections = _parse_sections(body)
    chunks: list[Chunk] = []
    chunk_index = 0

    # Maintain a stack-like list mapping heading level -> heading text.
    # Index 0 is unused (level 0 = no heading); indices 1-6 correspond to
    # ``#`` through ``######``.
    hierarchy: list[str] = [""] * 7
    for level, heading, section_body, _char_offset in sections:
        if level > 0:
            hierarchy[level] = heading
            # Clear deeper headings when a higher-level heading appears.
            for i in range(level + 1, 7):
                hierarchy[i] = ""

        current_hierarchy = [h for h in hierarchy[1 : level + 1] if h] if level > 0 else []

        # Prepend the full heading path so search engines can match on
        # contextual terms (e.g. "principles" matches each principle chunk).
        body_stripped = section_body.strip()
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
                    chunk_id=_make_chunk_id(body_checksum, chunk_index, chunk_strategy),
                    file_paths=[file_path],
                    heading_hierarchy=list(current_hierarchy),
                    level=level,
                    text=section_text,
                    chunk_index=chunk_index,
                    kind=kind,
                    provenance=provenance,
                )
            )
            chunk_index += 1
        else:
            # Section too large – split using kind-appropriate strategy.
            sub_texts = _split_with_overlap(
                section_text,
                max_tokens,
                overlap_tokens,
                pre_split=handler.pre_split,
            )
            for sub_text in sub_texts:
                chunks.append(
                    Chunk(
                        chunk_id=_make_chunk_id(body_checksum, chunk_index, chunk_strategy),
                        file_paths=[file_path],
                        heading_hierarchy=list(current_hierarchy),
                        level=level,
                        text=sub_text,
                        chunk_index=chunk_index,
                        kind=kind,
                        provenance=provenance,
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
