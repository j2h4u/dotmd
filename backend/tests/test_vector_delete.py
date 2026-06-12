"""Tests for SQLiteVecVectorStore delete and overwrite behavior."""

from pathlib import Path

from dotmd.core.models import Chunk
from dotmd.storage.sqlite_vec import SQLiteVecVectorStore


def _make_chunk(chunk_id: str, file_path: str = "test.md") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        file_paths=[Path(file_path)],
        heading_hierarchy=["Test"],
        level=1,
        text=f"Content of {chunk_id}",
        chunk_index=0,
    )


def _make_embedding(dim: int = 4) -> list[float]:
    return [0.1] * dim


def _add_three_chunks(vs: SQLiteVecVectorStore) -> None:
    """Helper: add 3 chunks with 4-dim embeddings."""
    chunks = [_make_chunk("c1"), _make_chunk("c2"), _make_chunk("c3")]
    embeddings = [_make_embedding() for _ in chunks]
    vs.add_chunks(chunks, embeddings)


class TestDeleteVectorsByChunkIds:
    """Tests for delete_vectors_by_chunk_ids method."""

    def test_delete_valid_chunk_ids_returns_count(self, vector_store: SQLiteVecVectorStore) -> None:
        """Deleting existing chunk_ids removes them and returns correct count."""
        _add_three_chunks(vector_store)
        assert vector_store.count() == 3

        deleted = vector_store.delete_vectors_by_chunk_ids(["c1", "c2"])
        assert deleted == 2
        assert vector_store.count() == 1

    def test_delete_empty_list_returns_zero(self, vector_store: SQLiteVecVectorStore) -> None:
        """Deleting with empty list is a no-op returning 0."""
        _add_three_chunks(vector_store)
        deleted = vector_store.delete_vectors_by_chunk_ids([])
        assert deleted == 0
        assert vector_store.count() == 3

    def test_delete_unknown_chunk_ids_returns_zero(
        self, vector_store: SQLiteVecVectorStore
    ) -> None:
        """Deleting non-existent chunk_ids returns 0, no errors."""
        _add_three_chunks(vector_store)
        deleted = vector_store.delete_vectors_by_chunk_ids(["nonexistent1", "nonexistent2"])
        assert deleted == 0
        assert vector_store.count() == 3

    def test_deleted_vectors_not_in_search_results(
        self, vector_store: SQLiteVecVectorStore
    ) -> None:
        """After deletion, search does not return deleted chunk_ids."""
        _add_three_chunks(vector_store)
        vector_store.delete_vectors_by_chunk_ids(["c1"])

        results = vector_store.search(_make_embedding(), top_k=10)
        result_ids = [chunk_id for chunk_id, _score in results]
        assert "c1" not in result_ids
        assert "c2" in result_ids
        assert "c3" in result_ids

    def test_delete_partial_match_returns_actual_count(
        self, vector_store: SQLiteVecVectorStore
    ) -> None:
        """Mix of existing and non-existing chunk_ids returns count of actually deleted."""
        _add_three_chunks(vector_store)
        deleted = vector_store.delete_vectors_by_chunk_ids(["c1", "nonexistent"])
        assert deleted == 1
        assert vector_store.count() == 2


class TestAddChunksOverwrite:
    """Tests for add_chunks overwrite parameter."""

    def test_add_chunks_overwrite_true_replaces_all(
        self, vector_store: SQLiteVecVectorStore
    ) -> None:
        """add_chunks with overwrite=True (default) wipes existing vectors before insert."""
        _add_three_chunks(vector_store)
        assert vector_store.count() == 3

        # Add 2 new chunks with overwrite=True
        new_chunks = [_make_chunk("c4"), _make_chunk("c5")]
        new_embeddings = [_make_embedding() for _ in new_chunks]
        vector_store.add_chunks(new_chunks, new_embeddings, overwrite=True)

        assert vector_store.count() == 2

    def test_add_chunks_overwrite_false_appends(self, vector_store: SQLiteVecVectorStore) -> None:
        """add_chunks with overwrite=False appends without wiping — count goes from N to N+M."""
        _add_three_chunks(vector_store)
        assert vector_store.count() == 3

        # Add 2 new chunks with overwrite=False
        new_chunks = [_make_chunk("c4"), _make_chunk("c5")]
        new_embeddings = [_make_embedding() for _ in new_chunks]
        vector_store.add_chunks(new_chunks, new_embeddings, overwrite=False)

        assert vector_store.count() == 5

        # Verify all 5 chunk_ids are searchable
        results = vector_store.search(_make_embedding(), top_k=10)
        result_ids = {chunk_id for chunk_id, _score in results}
        assert result_ids == {"c1", "c2", "c3", "c4", "c5"}

    def test_add_chunks_overwrite_false_default_is_true(
        self, vector_store: SQLiteVecVectorStore
    ) -> None:
        """Default behavior (no overwrite kwarg) still wipes existing data."""
        _add_three_chunks(vector_store)
        assert vector_store.count() == 3

        # Add 2 new chunks without specifying overwrite
        new_chunks = [_make_chunk("c4"), _make_chunk("c5")]
        new_embeddings = [_make_embedding() for _ in new_chunks]
        vector_store.add_chunks(new_chunks, new_embeddings)

        assert vector_store.count() == 2
