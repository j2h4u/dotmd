"""Abstract protocol definitions for dotMD storage backends.

This module defines the three storage protocols that all concrete
implementations must satisfy:

- **VectorStoreProtocol** – similarity search over chunk embeddings.
- **GraphStoreProtocol** – knowledge-graph persistence and traversal.
- **MetadataStoreProtocol** – chunk and index-statistics persistence.

Each protocol is marked ``@runtime_checkable`` so that ``isinstance``
checks work at runtime, but the primary enforcement mechanism is
static type-checking (mypy / pyright).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from dotmd.core.models import Chunk, IndexStats

# ---------------------------------------------------------------------------
# Vector store
# ---------------------------------------------------------------------------


@runtime_checkable
class VectorStoreProtocol(Protocol):
    """Protocol for vector similarity-search backends."""

    def add_chunks(
        self,
        chunks: list[Chunk],
        embeddings: list[list[float]],
        *,
        overwrite: bool = True,
        text_hashes: dict[str, str] | None = None,
    ) -> None:
        """Upsert *chunks* with their corresponding *embeddings*.

        Parameters
        ----------
        chunks:
            The chunk objects to store.
        embeddings:
            A parallel list of embedding vectors, one per chunk.
        overwrite:
            When ``True`` (default), all existing vectors are deleted
            before inserting.  When ``False``, new vectors are appended
            to existing ones.
        """
        ...

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
    ) -> list[tuple[str, float]]:
        """Return the *top_k* most similar chunks.

        Parameters
        ----------
        query_embedding:
            The embedding vector to search against.
        top_k:
            Maximum number of results to return.

        Returns
        -------
        list[tuple[str, float]]
            A list of ``(chunk_id, score)`` pairs ordered by
            descending similarity.
        """
        ...

    def delete_all(self) -> None:
        """Remove **all** vectors from the store."""
        ...

    def delete_vectors_by_chunk_ids(self, chunk_ids: list[str]) -> int:
        """Delete vectors for the given chunk IDs.

        Parameters
        ----------
        chunk_ids:
            The chunk identifiers whose vectors should be removed.

        Returns
        -------
        int
            The number of vectors actually deleted.
        """
        ...

    def count(self) -> int:
        """Return the total number of stored vectors."""
        ...

    def lookup_embeddings_by_text_hash(
        self,
        text_hashes: list[str],
    ) -> dict[str, list[float]]:
        """Find existing embeddings by text content hash.

        Returns ``{text_hash: embedding}`` for hashes found in the store.
        Used for embedding reuse when switching chunk strategy — identical
        text encoded with the same model yields the same vector.

        This is an **optional** capability.  Backends that do not support
        it return an empty dict (the default), and the pipeline falls back
        to re-encoding.

        Parameters
        ----------
        text_hashes:
            Content hashes to look up.

        Returns
        -------
        dict[str, list[float]]
            Mapping of ``{text_hash: embedding}`` for hashes found.
        """
        return {}


# ---------------------------------------------------------------------------
# Graph store
# ---------------------------------------------------------------------------


@runtime_checkable
class GraphStoreProtocol(Protocol):
    """Protocol for knowledge-graph storage backends."""

    def add_file_node(
        self,
        file_path: str,
        title: str,
    ) -> None:
        """Create or update a node representing a source file.

        Parameters
        ----------
        file_path:
            Absolute or workspace-relative path to the file.
        title:
            Human-readable title for the file.
        """
        ...

    def add_section_node(
        self,
        chunk_id: str,
        heading: str,
        level: int,
        file_path: str,
        text_preview: str,
    ) -> None:
        """Create or update a node representing a document section.

        Parameters
        ----------
        chunk_id:
            Unique identifier for the corresponding chunk.
        heading:
            Section heading text.
        level:
            Heading depth (1 = top-level).
        file_path:
            Path of the source file this section belongs to.
        text_preview:
            Short preview of the section body.
        """
        ...

    def add_entity_node(
        self,
        name: str,
        entity_type: str,
        source: str,
    ) -> None:
        """Create or update a named-entity node.

        Parameters
        ----------
        name:
            The canonical entity name.
        entity_type:
            Category of the entity (e.g. ``"PERSON"``, ``"ORG"``).
        source:
            Provenance information (e.g. chunk id or file path).
        """
        ...

    def add_tag_node(self, name: str) -> None:
        """Create or update a tag node.

        Parameters
        ----------
        name:
            The tag label.
        """
        ...

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        weight: float = 1.0,
    ) -> None:
        """Create or update a directed edge between two nodes.

        Parameters
        ----------
        source_id:
            Identifier of the source node.
        target_id:
            Identifier of the target node.
        relation_type:
            Semantic label for the relationship.
        weight:
            Edge weight (default ``1.0``).
        """
        ...

    def get_neighbors(
        self,
        node_id: str,
        max_hops: int = 2,
    ) -> list[tuple[str, str, float]]:
        """Retrieve neighbours reachable within *max_hops*.

        Parameters
        ----------
        node_id:
            Starting node identifier.
        max_hops:
            Maximum traversal depth.

        Returns
        -------
        list[tuple[str, str, float]]
            A list of ``(node_id, relation_type, weight)`` tuples.
        """
        ...

    def get_all_entity_names(self) -> list[str]:
        """Return all entity names in the graph."""
        return []

    def get_chunks_by_entity(self, entity_name: str) -> list[str]:
        """Return chunk_ids for sections connected to an entity."""
        return []

    def get_entities_by_file(self, file_path: str) -> list[str]:
        """Return sorted entity names mentioned in sections belonging to file_path."""
        return []

    # -- batch write helpers -----------------------------------------------
    # Default implementations loop over the individual methods.
    # Backends with native batch support (e.g. FalkorDB UNWIND) override these.

    def batch_add_section_nodes(self, sections: list[dict]) -> None:
        """Upsert Section nodes in bulk.

        Parameters
        ----------
        sections:
            List of dicts with keys ``chunk_id``, ``heading``, ``level``,
            ``file_path``, ``text_preview``.
        """
        for s in sections:
            self.add_section_node(
                chunk_id=s["chunk_id"],
                heading=s["heading"],
                level=s["level"],
                file_path=s["file_path"],
                text_preview=s["text_preview"],
            )

    def batch_add_entity_nodes(self, entities: list[dict]) -> None:
        """Upsert Entity nodes in bulk.

        Parameters
        ----------
        entities:
            List of dicts with keys ``name``, ``entity_type``, ``source``.
        """
        for e in entities:
            self.add_entity_node(
                name=e["name"],
                entity_type=e["entity_type"],
                source=e["source"],
            )

    def batch_add_tag_nodes(self, tags: list[str]) -> None:
        """Upsert Tag nodes in bulk.

        Parameters
        ----------
        tags:
            List of tag name strings.
        """
        for tag in tags:
            self.add_tag_node(tag)

    def batch_add_file_nodes(self, files: list[dict]) -> None:
        """Upsert File nodes in bulk.

        Parameters
        ----------
        files:
            List of dicts with keys ``file_path``, ``title``.
        """
        for f in files:
            self.add_file_node(file_path=f["file_path"], title=f["title"])

    def batch_add_edges(self, edges: list[dict]) -> None:
        """Upsert directed edges in bulk.

        Parameters
        ----------
        edges:
            List of dicts with keys ``source_id``, ``target_id``,
            ``relation_type``, and optional ``weight`` (default ``1.0``).
        """
        for e in edges:
            self.add_edge(
                source_id=e["source_id"],
                target_id=e["target_id"],
                relation_type=e["relation_type"],
                weight=e.get("weight", 1.0),
            )

    def delete_all(self) -> None:
        """Remove **all** nodes and edges from the graph."""
        ...

    def delete_file_subgraph(self, file_path: str) -> None:
        """Delete File and Section nodes for a file path.

        Entity and Tag nodes are preserved because they may be
        referenced by other files.

        Parameters
        ----------
        file_path:
            The path of the file whose subgraph should be removed.
        """
        ...

    def node_count(self) -> int:
        """Return the total number of nodes in the graph."""
        ...

    def edge_count(self) -> int:
        """Return the total number of edges in the graph."""
        ...

    def delete_isolated_nodes(self) -> int:
        """Delete nodes with no edges. Returns the number of nodes removed."""
        ...

    def get_graph_data(self) -> dict:
        """Return all nodes and edges for visualization.

        Returns
        -------
        dict
            A dictionary with ``'nodes'`` and ``'edges'`` keys.
            Each node: ``{'id': str, 'label': str, 'properties': dict}``.
            Each edge: ``{'source': str, 'target': str, 'relation_type': str, 'weight': float}``.
        """
        ...


# ---------------------------------------------------------------------------
# Metadata store
# ---------------------------------------------------------------------------


@runtime_checkable
class MetadataStoreProtocol(Protocol):
    """Protocol for chunk metadata and index-statistics persistence."""

    def save_chunks(self, chunks: list[Chunk]) -> None:
        """Persist a batch of chunks (insert or update).

        Parameters
        ----------
        chunks:
            The chunk objects to save.
        """
        ...

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        """Retrieve a single chunk by its identifier.

        Parameters
        ----------
        chunk_id:
            The unique chunk identifier.

        Returns
        -------
        Chunk | None
            The chunk if found, otherwise ``None``.
        """
        ...

    def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]:
        """Retrieve multiple chunks by their identifiers.

        Parameters
        ----------
        chunk_ids:
            A list of chunk identifiers.

        Returns
        -------
        list[Chunk]
            The chunks that were found.  Missing ids are silently
            skipped.
        """
        ...

    def get_all_chunks(self) -> list[Chunk]:
        """Return every chunk currently stored."""
        ...

    def save_stats(self, stats: IndexStats) -> None:
        """Persist index statistics (overwrites previous stats).

        Parameters
        ----------
        stats:
            The statistics snapshot to save.
        """
        ...

    def get_stats(self) -> IndexStats | None:
        """Retrieve the most recent index statistics.

        Returns
        -------
        IndexStats | None
            The statistics if available, otherwise ``None``.
        """
        ...

    def get_chunk_ids_by_file(self, file_path: str) -> list[str]:
        """Return all chunk_ids for a given file path.

        Parameters
        ----------
        file_path:
            The file path to look up.

        Returns
        -------
        list[str]
            Chunk identifiers belonging to the file.
        """
        ...

    def delete_chunks_by_file(self, file_path: str) -> int:
        """Delete all chunks belonging to a file.

        Parameters
        ----------
        file_path:
            The file path whose chunks should be removed.

        Returns
        -------
        int
            The number of chunks deleted.
        """
        ...

    def delete_all(self) -> None:
        """Remove **all** chunks and statistics from the store."""
        ...
