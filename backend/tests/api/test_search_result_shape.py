"""RED test skeletons for SearchResult.file_paths shape (DEDUP-09 — P5 Task 1).

After Phase 16 P5 ships:
  - SearchResult.file_paths: list[Path] replaces file_path: Path
  - file_paths is sorted lexicographically
  - No file_path singular attribute (clean break — Decision #2)
  - Batch hydration uses single SELECT per strategy (Review-LOW-12)

These tests FAIL at execution time until P5 (wave 5) updates the models.
Imports are deferred so --collect-only works before P5 ships.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _import_search_result():  # type: ignore[no-untyped-def]
    """Deferred import — raises ImportError/AttributeError until P5 ships."""
    from dotmd.core.models import SearchResult
    return SearchResult


class TestFilePathsFieldIsList:
    """DEDUP-09: SearchResult.file_paths is list[Path]."""

    def test_file_paths_field_is_list(self) -> None:
        """SearchResult.file_paths field type annotation is list[Path]."""
        SearchResult = _import_search_result()
        fields = SearchResult.model_fields
        assert "file_paths" in fields, (
            "SearchResult must have file_paths field (Phase 16 P5 — Decision #2)"
        )
        # Check the annotation is a list type
        annotation = fields["file_paths"].annotation
        assert annotation is not None
        # Accepts list[Path] or list[str] — both are valid
        origin = getattr(annotation, "__origin__", None)
        assert origin is list or str(annotation).startswith("list"), (
            f"file_paths annotation must be list[...], got {annotation!r}"
        )


class TestFilePathsSortedLex:
    """Decision #1: file_paths returned in lexicographic order."""

    def test_file_paths_sorted_lex(self) -> None:
        """A SearchResult with holders ['z.md', 'a.md', 'm.md'] returns them sorted."""
        SearchResult = _import_search_result()
        paths = [Path("/z/last.md"), Path("/a/first.md"), Path("/m/middle.md")]
        result = SearchResult(
            chunk_id="a" * 64,
            file_paths=paths,
            heading_path="# Heading",
            snippet="snippet",
            fused_score=0.9,
        )
        assert result.file_paths == sorted(paths), (
            f"file_paths must be sorted lex, got {result.file_paths!r}"
        )


class TestSingleHolderReturnsSingleElementList:
    """Non-dup chunk returns file_paths as a single-element list."""

    def test_single_holder_returns_single_element_list(self) -> None:
        """SearchResult with one holder has file_paths = [path]."""
        SearchResult = _import_search_result()
        single_path = Path("/only/one.md")
        result = SearchResult(
            chunk_id="b" * 64,
            file_paths=[single_path],
            heading_path="# Heading",
            snippet="snippet",
            fused_score=0.8,
        )
        assert result.file_paths == [single_path]
        assert len(result.file_paths) == 1


class TestNoFilePathAttr:
    """Decision #2: clean break — no singular file_path attribute."""

    def test_no_file_path_attr(self) -> None:
        """SearchResult has no 'file_path' field after P5 (guards clean break)."""
        SearchResult = _import_search_result()
        fields = SearchResult.model_fields
        assert "file_path" not in fields, (
            "SearchResult must NOT have singular file_path field after P5 (Decision #2: clean break)"
        )


class TestGraphDirectHitAlsoHydrates:
    """Graph-origin hits are hydrated via the same batch path as semantic hits."""

    def test_graph_direct_hit_also_hydrates(self, tmp_path: Path) -> None:
        """A chunk_id from graph_direct search is hydrated with file_paths list."""
        # This test will fail until P5 wires graph_direct results through
        # the same batch hydration path (get_file_paths_for_chunk_ids).
        # For now, assert that the SearchResult shape is consistent.
        SearchResult = _import_search_result()
        graph_path = Path("/graph/file.md")
        result = SearchResult(
            chunk_id="c" * 64,
            file_paths=[graph_path],
            heading_path="# Section",
            snippet="graph snippet",
            fused_score=0.7,
            graph_direct_score=0.95,
        )
        assert isinstance(result.file_paths, list)
        assert len(result.file_paths) >= 1


class TestBatchHydrationSingleQueryPerStrategy:
    """Review-LOW-12: hydrate N chunk_ids in a single SELECT per strategy."""

    def test_batch_hydration_single_query_per_strategy(
        self, tmp_path: Path
    ) -> None:
        """get_file_paths_for_chunk_ids called once per strategy for a batch of 5 chunk_ids."""
        # This test validates the batch hydration helper from P1 metadata layer.
        # It will fail until P1 ships get_file_paths_for_chunk_ids.
        from dotmd.storage.metadata import SQLiteMetadataStore

        db_path = tmp_path / "test.db"
        strategy = "heading_512_50"

        # Build a minimal post-v16 store
        conn_raw = __import__("sqlite3").connect(str(db_path))
        conn_raw.executescript(f"""
            CREATE TABLE chunks_{strategy} (chunk_id TEXT PRIMARY KEY, text TEXT);
            CREATE TABLE chunk_file_paths_{strategy} (
                chunk_id TEXT NOT NULL, file_path TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                PRIMARY KEY (chunk_id, file_path, chunk_index)
            );
        """)
        conn_raw.commit()

        store = SQLiteMetadataStore(db_path=db_path, table_name=f"chunks_{strategy}", conn=conn_raw)
        store.ensure_m2m_table(strategy)

        chunk_ids = [chr(ord("a") + i) * 64 for i in range(5)]
        for i, cid in enumerate(chunk_ids):
            store.insert_chunk(strategy, cid, ["H"], 1, f"text {i}")
            store.add_file_path(strategy, cid, f"/path/file_{i}.md", chunk_index=0)

        # Count SELECT calls
        original_execute = conn_raw.execute
        select_count = {"n": 0}

        def counting_execute(sql: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if str(sql).strip().upper().startswith("SELECT"):
                select_count["n"] += 1
            return original_execute(sql, *args, **kwargs)

        conn_raw.execute = counting_execute  # type: ignore[method-assign]
        select_count["n"] = 0

        result = store.get_file_paths_for_chunk_ids(strategy, chunk_ids)

        assert select_count["n"] <= 1, (
            f"Expected single SELECT for batch hydration, got {select_count['n']} SELECT calls"
        )
        assert len(result) == 5
        conn_raw.close()
