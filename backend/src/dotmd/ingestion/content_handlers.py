"""Content-type handlers for kind-aware chunking and enrichment.

Each document ``kind`` (from YAML frontmatter) maps to a handler that knows
how to pre-split the text into natural segments and how to enrich chunk text
for embedding.  Unknown or missing kinds fall back to the default handler.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import NamedTuple

from dotmd.core.models import DocKind

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pre-split functions
# ---------------------------------------------------------------------------

# Matches transcript speaker turns: [00:12:34] **Speaker Name:**
_SPEAKER_TURN_RE = re.compile(r"\n(?=\[\d{2}:\d{2}:\d{2}\]\s*\*\*)")


def split_by_speaker_turns(text: str) -> list[str]:
    """Split meeting transcript on ``[HH:MM:SS] **Speaker:**`` boundaries."""
    segments = _SPEAKER_TURN_RE.split(text)
    return [s.strip() for s in segments if s.strip()]


def split_by_paragraphs(text: str) -> list[str]:
    """Split on double newlines (voicenotes, plain text)."""
    if text.count("\n\n") >= 3:
        segments = text.split("\n\n")
        return [s.strip() for s in segments if s.strip()]
    return [text] if text.strip() else []


def split_default(text: str) -> list[str]:
    """No pre-splitting — return text as-is for heading-based chunking."""
    return [text] if text.strip() else []


# ---------------------------------------------------------------------------
# Enrich functions
# ---------------------------------------------------------------------------


def enrich_with_title_and_tags(text: str, frontmatter: dict) -> str:
    """Prepend document title and tags to chunk text for embedding context.

    ADR: Enriching embedding input with title + tags improves semantic search
    recall. The embedding model sees "Meeting Notes\\nperson:Alice, budget\\n\\n..."
    which places the chunk closer to queries about Alice or budgets in vector
    space. This is the semantic equivalent of FTS5 column weighting -- each
    search engine receives the same metadata through its native channel.
    """
    title = frontmatter.get("title", "")
    tags = frontmatter.get("tags", [])
    tags_str = ", ".join(str(t) for t in tags) if tags else ""
    parts: list[str] = []
    if title:
        parts.append(title)
    if tags_str:
        parts.append(tags_str)
    if parts:
        return "\n".join(parts) + "\n\n" + text
    return text


# ---------------------------------------------------------------------------
# Handler registry
# ---------------------------------------------------------------------------


class ContentHandler(NamedTuple):
    """Dispatch pair for a document kind."""

    pre_split: Callable[[str], list[str]]
    enrich: Callable[[str, dict], str]


DEFAULT_HANDLER = ContentHandler(
    pre_split=split_default,
    enrich=enrich_with_title_and_tags,
)

HANDLERS: dict[str, ContentHandler] = {
    DocKind.MEETING_TRANSCRIPT: ContentHandler(
        pre_split=split_by_speaker_turns,
        enrich=enrich_with_title_and_tags,
    ),
    DocKind.VOICENOTE: ContentHandler(
        pre_split=split_by_paragraphs,
        enrich=enrich_with_title_and_tags,
    ),
}


def get_handler(kind: str) -> ContentHandler:
    """Look up the handler for *kind*, falling back to the default."""
    handler = HANDLERS.get(kind)
    if handler is None:
        logger.debug("No handler for kind=%r, using default", kind)
        return DEFAULT_HANDLER
    return handler
