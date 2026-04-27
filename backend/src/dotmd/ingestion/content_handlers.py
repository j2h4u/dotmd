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



def _enrich_passthrough(text: str, frontmatter: dict) -> str:
    """No-op enrichment — chunk text embedded as-is (Phase 999.12 dual-encoder).

    title+tags are now a separate e_meta vector component; not prepended to
    e_text. FTS5 path does not use this registry enrich function (verified
    999.12): keyword_engine.add_chunks() receives file_meta separately.
    """
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
    enrich=_enrich_passthrough,
)

HANDLERS: dict[str, ContentHandler] = {
    DocKind.MEETING_TRANSCRIPT: ContentHandler(
        pre_split=split_by_speaker_turns,
        enrich=_enrich_passthrough,
    ),
    DocKind.VOICENOTE: ContentHandler(
        pre_split=split_by_paragraphs,
        enrich=_enrich_passthrough,
    ),
}


def get_handler(kind: str) -> ContentHandler:
    """Look up the handler for *kind*, falling back to the default."""
    handler = HANDLERS.get(kind)
    if handler is None:
        logger.debug("No handler for kind=%r, using default", kind)
        return DEFAULT_HANDLER
    return handler
