"""Tests for VecComponentStore (Phase 999.12)."""

import sqlite3

import pytest

from dotmd.storage.vec_components import VecComponentStore


@pytest.fixture
def store(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    return VecComponentStore(conn=conn, table_name="vec_components_test")


def test_store_and_get_roundtrip(store):
    """store() then get() returns the same vector."""
    vec = [0.1, 0.2, 0.3, 0.4]
    store.store("chunk_abc", "text", vec)
    conn = store._conn
    conn.commit()
    result = store.get("chunk_abc", "text")
    assert result is not None
    assert len(result) == 4
    assert all(abs(a - b) < 1e-6 for a, b in zip(result, vec, strict=False))


def test_get_missing_returns_none(store):
    """get() returns None for unknown entity_id/component."""
    assert store.get("nonexistent", "text") is None


def test_store_is_idempotent_replace(store):
    """store() with same entity_id+component replaces previous value (INSERT OR REPLACE)."""
    store.store("chunk_abc", "text", [0.1, 0.2])
    store.store("chunk_abc", "text", [0.9, 0.8])
    store._conn.commit()
    result = store.get("chunk_abc", "text")
    assert result is not None
    assert abs(result[0] - 0.9) < 1e-6


def test_different_components_independent(store):
    """text and meta components for same entity_id are stored independently."""
    store.store("file.md", "text", [0.1, 0.2])
    store.store("file.md", "meta", [0.5, 0.6])
    store._conn.commit()
    text_vec = store.get("file.md", "text")
    meta_vec = store.get("file.md", "meta")
    assert text_vec is not None and abs(text_vec[0] - 0.1) < 1e-6
    assert meta_vec is not None and abs(meta_vec[0] - 0.5) < 1e-6


def test_get_batch(store):
    """get_batch() returns all found entity_ids for a component."""
    store.store("chunk_a", "text", [0.1, 0.2])
    store.store("chunk_b", "text", [0.3, 0.4])
    store.store("chunk_c", "meta", [0.9, 0.8])  # different component
    store._conn.commit()
    result = store.get_batch(["chunk_a", "chunk_b", "chunk_c"], "text")
    assert set(result.keys()) == {"chunk_a", "chunk_b"}
    assert "chunk_c" not in result  # different component, not returned


def test_delete_by_entity_ids(store):
    """delete_by_entity_ids() removes all components for specified entity_ids."""
    store.store("chunk_a", "text", [0.1, 0.2])
    store.store("chunk_b", "text", [0.3, 0.4])
    store.store("chunk_a", "meta", [0.5, 0.6])
    store._conn.commit()
    store.delete_by_entity_ids(["chunk_a"])
    store._conn.commit()
    # Both text and meta for chunk_a deleted
    assert store.get("chunk_a", "text") is None
    assert store.get("chunk_a", "meta") is None
    # chunk_b unaffected
    assert store.get("chunk_b", "text") is not None


def test_delete_all(store):
    """delete_all() removes every row."""
    store.store("chunk_a", "text", [0.1])
    store.store("chunk_b", "meta", [0.2])
    store.delete_all()
    assert store.get("chunk_a", "text") is None
    assert store.get("chunk_b", "meta") is None
    assert store.count() == 0


def test_count(store):
    """count() returns number of rows."""
    assert store.count() == 0
    store.store("chunk_a", "text", [0.1])
    store.store("chunk_a", "meta", [0.2])
    store._conn.commit()
    assert store.count() == 2
