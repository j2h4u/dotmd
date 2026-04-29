"""Tests for LadybugDBGraphStore.delete_file_subgraph() + DETACH DELETE spike.

Spike tests validate that LadybugDB DETACH DELETE cascade works correctly
across all 7 REL tables in the project schema. Functional tests verify
the delete_file_subgraph() method behavior.
"""

from __future__ import annotations

from dotmd.storage.graph import LadybugDBGraphStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_nodes(gs: LadybugDBGraphStore, label: str) -> int:
    """Count nodes of a given label."""
    with gs._connection() as conn:
        result = conn.execute(f"MATCH (n:{label}) RETURN count(n)")
        return int(result.get_as_df().iloc[0, 0])


def _count_edges(gs: LadybugDBGraphStore, rel_table: str) -> int:
    """Count edges in a given relationship table."""
    with gs._connection() as conn:
        result = conn.execute(f"MATCH ()-[r:{rel_table}]->() RETURN count(r)")
        return int(result.get_as_df().iloc[0, 0])


def _populate_graph(gs: LadybugDBGraphStore) -> None:
    """Create a small graph: 1 File -> 2 Sections, shared Entity + Tag.

    Nodes: File(doc/test.md), Section(chunk-1), Section(chunk-2),
           Entity(Python), Tag(programming)
    Edges: FILE_SECTION x2, SECTION_ENTITY x2, SECTION_TAG x1,
           SECTION_SECTION x1, FILE_ENTITY x1, FILE_TAG x1
    Total: 5 nodes, 8 edges
    """
    gs.add_file_node(file_path="doc/test.md", title="Test Doc")
    gs.add_section_node(
        chunk_id="chunk-1", heading="Intro", level=1,
        file_path="doc/test.md", text_preview="Introduction text",
    )
    gs.add_section_node(
        chunk_id="chunk-2", heading="Body", level=2,
        file_path="doc/test.md", text_preview="Body text",
    )
    gs.add_entity_node(name="Python", entity_type="technology", source="ner")
    gs.add_tag_node(name="programming")
    # File -> Sections
    gs.add_edge("doc/test.md", "chunk-1", "CONTAINS")
    gs.add_edge("doc/test.md", "chunk-2", "CONTAINS")
    # Sections -> Entity
    gs.add_edge("chunk-1", "Python", "MENTIONS")
    gs.add_edge("chunk-2", "Python", "MENTIONS")
    # Section -> Tag
    gs.add_edge("chunk-1", "programming", "TAGGED")
    # Section -> Section (sibling)
    gs.add_edge("chunk-1", "chunk-2", "NEXT")
    # File -> Entity, File -> Tag
    gs.add_edge("doc/test.md", "Python", "HAS_ENTITY")
    gs.add_edge("doc/test.md", "programming", "HAS_TAG")


def _populate_second_file(gs: LadybugDBGraphStore) -> None:
    """Add a second file that shares Entity 'Python' and Tag 'programming'."""
    gs.add_file_node(file_path="doc/other.md", title="Other Doc")
    gs.add_section_node(
        chunk_id="chunk-3", heading="Appendix", level=1,
        file_path="doc/other.md", text_preview="Appendix text",
    )
    gs.add_edge("doc/other.md", "chunk-3", "CONTAINS")
    gs.add_edge("chunk-3", "Python", "MENTIONS")


# ---------------------------------------------------------------------------
# Spike tests: DETACH DELETE cascade validation
# ---------------------------------------------------------------------------


class TestDetachDeleteSpike:
    """Validate that LadybugDB DETACH DELETE cascades across all 7 REL tables."""

    def test_detach_delete_section_preserves_entity(
        self, graph_store: LadybugDBGraphStore
    ) -> None:
        """DETACH DELETE Section removes SECTION_ENTITY edges but preserves Entity node."""
        _populate_graph(graph_store)
        assert _count_nodes(graph_store, "Entity") == 1
        assert _count_edges(graph_store, "SECTION_ENTITY") == 2

        with graph_store._connection() as conn:
            conn.execute(
                "MATCH (s:Section {id: $id}) DETACH DELETE s",
                parameters={"id": "chunk-1"},
            )

        # Entity preserved, but one SECTION_ENTITY edge gone
        assert _count_nodes(graph_store, "Entity") == 1
        assert _count_edges(graph_store, "SECTION_ENTITY") == 1

    def test_detach_delete_section_preserves_tag(
        self, graph_store: LadybugDBGraphStore
    ) -> None:
        """DETACH DELETE Section removes SECTION_TAG edges but preserves Tag node."""
        _populate_graph(graph_store)
        assert _count_nodes(graph_store, "Tag") == 1
        assert _count_edges(graph_store, "SECTION_TAG") == 1

        with graph_store._connection() as conn:
            conn.execute(
                "MATCH (s:Section {id: $id}) DETACH DELETE s",
                parameters={"id": "chunk-1"},
            )

        assert _count_nodes(graph_store, "Tag") == 1
        assert _count_edges(graph_store, "SECTION_TAG") == 0

    def test_detach_delete_section_removes_sibling_edges(
        self, graph_store: LadybugDBGraphStore
    ) -> None:
        """DETACH DELETE Section removes SECTION_SECTION edges (sibling links)."""
        _populate_graph(graph_store)
        assert _count_edges(graph_store, "SECTION_SECTION") == 1

        with graph_store._connection() as conn:
            conn.execute(
                "MATCH (s:Section {id: $id}) DETACH DELETE s",
                parameters={"id": "chunk-1"},
            )

        assert _count_edges(graph_store, "SECTION_SECTION") == 0

    def test_detach_delete_section_removes_file_section_edge(
        self, graph_store: LadybugDBGraphStore
    ) -> None:
        """DETACH DELETE Section removes the FILE_SECTION edge from parent File."""
        _populate_graph(graph_store)
        assert _count_edges(graph_store, "FILE_SECTION") == 2

        with graph_store._connection() as conn:
            conn.execute(
                "MATCH (s:Section {id: $id}) DETACH DELETE s",
                parameters={"id": "chunk-1"},
            )

        assert _count_edges(graph_store, "FILE_SECTION") == 1

    def test_detach_delete_file_preserves_shared_nodes(
        self, graph_store: LadybugDBGraphStore
    ) -> None:
        """DETACH DELETE File removes FILE_TAG, FILE_ENTITY edges but preserves nodes."""
        _populate_graph(graph_store)
        assert _count_edges(graph_store, "FILE_TAG") == 1
        assert _count_edges(graph_store, "FILE_ENTITY") == 1

        # First delete sections to isolate File node edges
        with graph_store._connection() as conn:
            conn.execute(
                "MATCH (s:Section {file_path: $fp}) DETACH DELETE s",
                parameters={"fp": "doc/test.md"},
            )
            conn.execute(
                "MATCH (f:File {id: $fp}) DETACH DELETE f",
                parameters={"fp": "doc/test.md"},
            )

        # Shared nodes preserved
        assert _count_nodes(graph_store, "Entity") == 1
        assert _count_nodes(graph_store, "Tag") == 1
        # File edges gone
        assert _count_edges(graph_store, "FILE_TAG") == 0
        assert _count_edges(graph_store, "FILE_ENTITY") == 0


# ---------------------------------------------------------------------------
# Functional tests: delete_file_subgraph()
# ---------------------------------------------------------------------------


class TestDeleteFileSubgraph:
    """Tests for delete_file_subgraph method."""

    def test_removes_all_sections_for_file(
        self, graph_store: LadybugDBGraphStore
    ) -> None:
        """delete_file_subgraph removes all Section nodes with matching file_path."""
        _populate_graph(graph_store)
        assert _count_nodes(graph_store, "Section") == 2

        graph_store.delete_file_subgraph("doc/test.md")

        assert _count_nodes(graph_store, "Section") == 0

    def test_removes_file_node(
        self, graph_store: LadybugDBGraphStore
    ) -> None:
        """delete_file_subgraph removes the File node."""
        _populate_graph(graph_store)
        assert _count_nodes(graph_store, "File") == 1

        graph_store.delete_file_subgraph("doc/test.md")

        assert _count_nodes(graph_store, "File") == 0

    def test_preserves_entity_and_tag_nodes(
        self, graph_store: LadybugDBGraphStore
    ) -> None:
        """delete_file_subgraph preserves Entity and Tag nodes (shared across files)."""
        _populate_graph(graph_store)

        graph_store.delete_file_subgraph("doc/test.md")

        assert _count_nodes(graph_store, "Entity") == 1
        assert _count_nodes(graph_store, "Tag") == 1

    def test_preserves_other_file_sections(
        self, graph_store: LadybugDBGraphStore
    ) -> None:
        """delete_file_subgraph preserves Section nodes from OTHER files."""
        _populate_graph(graph_store)
        _populate_second_file(graph_store)
        assert _count_nodes(graph_store, "Section") == 3

        graph_store.delete_file_subgraph("doc/test.md")

        assert _count_nodes(graph_store, "Section") == 1
        assert _count_nodes(graph_store, "File") == 1

    def test_nonexistent_file_is_noop(
        self, graph_store: LadybugDBGraphStore
    ) -> None:
        """delete_file_subgraph on non-existent file_path is a no-op (no error)."""
        _populate_graph(graph_store)
        before_nodes = graph_store.node_count()
        before_edges = graph_store.edge_count()

        graph_store.delete_file_subgraph("nonexistent/path.md")

        assert graph_store.node_count() == before_nodes
        assert graph_store.edge_count() == before_edges

    def test_node_count_decreases_correctly(
        self, graph_store: LadybugDBGraphStore
    ) -> None:
        """After delete_file_subgraph, node_count decreases by expected amount."""
        _populate_graph(graph_store)
        _populate_second_file(graph_store)
        # 2 Files + 3 Sections + 1 Entity + 1 Tag = 7 nodes
        assert graph_store.node_count() == 7

        graph_store.delete_file_subgraph("doc/test.md")

        # Removed: 1 File + 2 Sections = 3 nodes. Remaining: 4
        assert graph_store.node_count() == 4
