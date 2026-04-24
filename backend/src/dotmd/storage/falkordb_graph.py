"""FalkorDB-backed knowledge-graph store.

Implements :class:`~dotmd.storage.base.GraphStoreProtocol` using
FalkorDB (Redis-protocol graph database) for network-accessible,
concurrent-safe graph storage.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from falkordb import FalkorDB

logger = logging.getLogger(__name__)


class FalkorDBGraphStore:
    """FalkorDB implementation of :class:`GraphStoreProtocol`.

    Connects to a running FalkorDB instance via the Redis protocol and
    stores knowledge-graph data in a named graph.  The connection is
    established once at initialization and reused for every operation.

    Parameters
    ----------
    url:
        Redis-protocol URL for the FalkorDB instance
        (e.g. ``"redis://localhost:6379"``).
    graph_name:
        Name of the FalkorDB graph to use.  Must differ from other
        graphs on the same instance (e.g. Graphiti's ``"knowledgebase"``).
    """

    def __init__(
        self,
        url: str = "redis://localhost:6379",
        graph_name: str = "dotmd",
    ) -> None:
        parsed = urlparse(url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379

        try:
            self._db = FalkorDB(host=host, port=port)
            self._graph = self._db.select_graph(graph_name)
        except Exception as exc:
            logger.error("Cannot connect to FalkorDB at %s:%d", host, port, exc_info=True)
            raise ConnectionError(
                f"Cannot connect to FalkorDB at {url}. "
                "Is the container running?"
            ) from exc

        self._graph_name = graph_name

        # Create range indexes for performance (idempotent).
        for label in ("File", "Section", "Entity", "Tag"):
            try:
                self._graph.query(f"CREATE INDEX FOR (n:{label}) ON (n.id)")
            except Exception:  # noqa: BLE001
                logger.debug("Index for %s already exists or creation skipped", label)

    # -- node creation ------------------------------------------------------

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
        self._graph.query(
            "MERGE (f:File {id: $id}) SET f.title = $title",
            params={"id": file_path, "title": title},
        )

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
        self._graph.query(
            "MERGE (s:Section {id: $id}) "
            "SET s.heading = $heading, s.level = $level, "
            "s.file_path = $file_path, s.text_preview = $text_preview",
            params={
                "id": chunk_id,
                "heading": heading,
                "level": level,
                "file_path": file_path,
                "text_preview": text_preview,
            },
        )

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
        self._graph.query(
            "MERGE (e:Entity {id: $id}) "
            "SET e.type = $type, e.source = $source",
            params={"id": name, "type": entity_type, "source": source},
        )

    def add_tag_node(self, name: str) -> None:
        """Create or update a tag node.

        Parameters
        ----------
        name:
            The tag label.
        """
        self._graph.query(
            "MERGE (t:Tag {id: $id})",
            params={"id": name},
        )

    # -- edge creation ------------------------------------------------------

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        weight: float = 1.0,
    ) -> None:
        """Create or update a directed edge between two nodes.

        Uses label-agnostic MATCH which is acceptable for the current
        graph size (~3.5K nodes).  Range indexes on each label's ``id``
        property keep scans fast.

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
        self._graph.query(
            "MATCH (a {id: $src}), (b {id: $tgt}) "
            "MERGE (a)-[r:REL]->(b) "
            "SET r.rel_type = $rel_type, r.weight = $weight",
            params={
                "src": source_id,
                "tgt": target_id,
                "rel_type": relation_type,
                "weight": weight,
            },
        )

    # -- queries ------------------------------------------------------------

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
        result = self._graph.ro_query(
            f"MATCH (a {{id: $id}})-[*1..{int(max_hops)}]-(b) "
            "RETURN DISTINCT b.id, labels(b)[0]",
            params={"id": node_id},
        )
        neighbors: list[tuple[str, str, float]] = []
        for row in result.result_set:
            nid = str(row[0])
            if nid != node_id:
                neighbors.append((nid, "", 1.0))
        return neighbors

    # -- housekeeping -------------------------------------------------------

    def delete_file_subgraph(self, file_path: str) -> None:
        """Delete File and Section nodes for a file path.

        Entity and Tag nodes are preserved because they may be
        referenced by other files.  ``DETACH DELETE`` removes the
        node and all its connected edges.

        Parameters
        ----------
        file_path:
            The path of the file whose subgraph should be removed.
        """
        self._graph.query(
            "MATCH (s:Section {file_path: $fp}) DETACH DELETE s",
            params={"fp": file_path},
        )
        self._graph.query(
            "MATCH (f:File {id: $fp}) DETACH DELETE f",
            params={"fp": file_path},
        )

    def get_all_entity_names(self) -> list[str]:
        """Return all entity names in the graph."""
        result = self._graph.ro_query(
            "MATCH (e:Entity) RETURN e.id"
        )
        return [str(row[0]) for row in result.result_set]

    def get_chunks_by_entity(self, entity_name: str) -> list[str]:
        """Return chunk_ids for sections connected to an entity."""
        result = self._graph.ro_query(
            "MATCH (e:Entity {id: $name})--(s:Section) RETURN s.id",
            params={"name": entity_name},
        )
        return [str(row[0]) for row in result.result_set]

    def delete_all(self) -> None:
        """Remove all nodes and edges from the graph."""
        self._graph.query("MATCH (n) DETACH DELETE n")

    def node_count(self) -> int:
        """Return the total number of nodes in the graph."""
        result = self._graph.ro_query("MATCH (n) RETURN count(n)")
        return int(result.result_set[0][0]) if result.result_set else 0

    def edge_count(self) -> int:
        """Return the total number of edges in the graph."""
        result = self._graph.ro_query("MATCH ()-[r]->() RETURN count(r)")
        return int(result.result_set[0][0]) if result.result_set else 0

    def get_graph_data(self) -> dict:
        """Return all nodes and edges for visualization.

        Returns
        -------
        dict
            A dictionary with ``'nodes'`` and ``'edges'`` keys.
            Each node: ``{'id': str, 'label': str, 'properties': dict}``.
            Each edge: ``{'source': str, 'target': str, 'relation_type': str, 'weight': float}``.
        """
        nodes: list[dict] = []
        for label in ("File", "Section", "Entity", "Tag"):
            try:
                result = self._graph.ro_query(f"MATCH (n:{label}) RETURN n")
                for row in result.result_set:
                    node = row[0]
                    node_id = node.properties.get("id", "")
                    props = {
                        k: v for k, v in node.properties.items() if k != "id"
                    }
                    # Enrich Section nodes with NER entity names
                    if label == "Section":
                        try:
                            ent_result = self._graph.ro_query(
                                "MATCH (s:Section {id: $sid})-[:REL]->(e:Entity) "
                                "WHERE e.source = 'ner' "
                                "RETURN e.id",
                                params={"sid": str(node_id)},
                            )
                            if ent_result.result_set:
                                props["ner_entities"] = [
                                    str(r[0]) for r in ent_result.result_set
                                ]
                        except Exception:  # noqa: BLE001
                            logger.debug("Failed to enrich Section %s with NER entities", node_id, exc_info=True)
                    nodes.append({
                        "id": str(node_id),
                        "label": label,
                        "properties": props,
                    })
            except Exception:
                logger.debug(
                    "Failed to query %s nodes", label, exc_info=True
                )

        edges: list[dict] = []
        try:
            result = self._graph.ro_query(
                "MATCH (a)-[r]->(b) "
                "RETURN a.id, b.id, r.rel_type, r.weight"
            )
            for row in result.result_set:
                edges.append({
                    "source": str(row[0]),
                    "target": str(row[1]),
                    "relation_type": str(row[2]),
                    "weight": float(row[3]) if row[3] is not None else 1.0,
                })
        except Exception:
            logger.debug("Failed to query edges", exc_info=True)

        return {"nodes": nodes, "edges": edges}
