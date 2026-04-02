"""Structural extraction from markdown syntax.

Extracts entities and relations from wikilinks, tags, markdown links,
and heading hierarchy.  Frontmatter extraction moved to pipeline-level
``_frontmatter_to_graph()`` which injects typed entities directly from
parsed FileInfo metadata.
"""

from __future__ import annotations

import logging
import re

from dotmd.core.models import Chunk, Entity, ExtractDepth, ExtractionResult, Relation, RelationType

logger = logging.getLogger(__name__)

# --- Regex patterns -----------------------------------------------------------

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
_INLINE_TAG_RE = re.compile(r"(?:^|(?<=\s))#([A-Za-z_][\w/-]*)", re.MULTILINE)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+\.md(?:#[^)]*)?)\)")
class StructuralExtractor:
    """Extract entities and relations from markdown structural elements.

    Recognised patterns:
    - ``[[wikilinks]]`` — creates a *link* entity and a ``LINKS_TO`` relation.
    - Inline ``#tags`` (not heading lines) — creates a *tag* entity and a
      ``HAS_TAG`` relation.
    - Markdown links to ``.md`` files — creates a *link* entity and a
      ``LINKS_TO`` relation.
    - Heading hierarchy — creates ``PARENT_OF`` relations between parent and
      child chunks.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, chunks: list[Chunk]) -> ExtractionResult:
        """Extract entities and relations from *chunks*.

        Args:
            chunks: Ordered list of document chunks.

        Returns:
            Aggregated ``ExtractionResult``.
        """
        entities: list[Entity] = []
        relations: list[Relation] = []

        # Build a lookup from heading hierarchy tuple → chunk_id for parent
        # resolution.  The parent of a chunk is the chunk whose hierarchy is
        # the immediate prefix of the current one.
        hierarchy_map: dict[tuple[str, ...], str] = {}
        for chunk in chunks:
            key = tuple(chunk.heading_hierarchy)
            hierarchy_map[key] = chunk.chunk_id

        for chunk in chunks:
            text = chunk.text
            cid = chunk.chunk_id

            # --- Wikilinks ---------------------------------------------------
            for match in _WIKILINK_RE.finditer(text):
                target = match.group(1).strip()
                entity = Entity(
                    name=target,
                    type="link",
                    source=ExtractDepth.STRUCTURAL,
                    chunk_ids=[cid],
                )
                entities.append(entity)
                relations.append(
                    Relation(
                        source_id=cid,
                        target_id=target,
                        relation_type="LINKS_TO",
                    )
                )

            # --- Inline tags --------------------------------------------------
            for match in _INLINE_TAG_RE.finditer(text):
                # Exclude lines that start with '#' as a heading (e.g. "# Title").
                line_start = text.rfind("\n", 0, match.start()) + 1
                line = text[line_start : match.end()]
                if line.lstrip().startswith("# ") or line.lstrip().startswith("## ") or line.lstrip().startswith("### "):
                    continue
                tag = match.group(1)
                entity = Entity(
                    name=tag,
                    type="tag",
                    source=ExtractDepth.STRUCTURAL,
                    chunk_ids=[cid],
                )
                entities.append(entity)
                relations.append(
                    Relation(
                        source_id=cid,
                        target_id=tag,
                        relation_type=RelationType.HAS_TAG,
                    )
                )

            # --- Markdown links to .md files ----------------------------------
            for match in _MD_LINK_RE.finditer(text):
                link_text = match.group(1)
                href = match.group(2).split("#")[0]  # strip anchor
                entity = Entity(
                    name=href,
                    type="link",
                    source=ExtractDepth.STRUCTURAL,
                    chunk_ids=[cid],
                )
                entities.append(entity)
                relations.append(
                    Relation(
                        source_id=cid,
                        target_id=href,
                        relation_type="LINKS_TO",
                        properties={"link_text": link_text},
                    )
                )

            # --- Heading hierarchy → PARENT_OF --------------------------------
            hier = tuple(chunk.heading_hierarchy)
            if len(hier) > 1:
                parent_key = hier[:-1]
                parent_id = hierarchy_map.get(parent_key)
                if parent_id is not None:
                    relations.append(
                        Relation(
                            source_id=parent_id,
                            target_id=cid,
                            relation_type="PARENT_OF",
                        )
                    )

        return ExtractionResult(entities=entities, relations=relations)

