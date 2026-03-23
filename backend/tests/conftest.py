"""Shared test fixtures for dotmd."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from dotmd.ingestion.file_tracker import FileTracker
from dotmd.storage.metadata import SQLiteMetadataStore
from dotmd.storage.sqlite_vec import SQLiteVecVectorStore
from dotmd.storage.graph import LadybugDBGraphStore


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """Return a temporary directory for test artifacts."""
    return tmp_path


@pytest.fixture
def metadata_store(tmp_dir: Path) -> SQLiteMetadataStore:
    """Return a fresh SQLiteMetadataStore backed by a temp db."""
    return SQLiteMetadataStore(tmp_dir / "metadata.db")


@pytest.fixture
def sqlite_conn(tmp_dir: Path) -> sqlite3.Connection:
    """Return a raw sqlite3 connection to a temp database."""
    return sqlite3.connect(str(tmp_dir / "test.db"))


@pytest.fixture
def vector_store(tmp_dir: Path) -> SQLiteVecVectorStore:
    """Return a fresh SQLiteVecVectorStore backed by a temp db."""
    return SQLiteVecVectorStore(tmp_dir / "vec.db")


@pytest.fixture
def graph_store(tmp_dir: Path) -> LadybugDBGraphStore:
    """Return a fresh LadybugDBGraphStore backed by a temp directory."""
    return LadybugDBGraphStore(tmp_dir / "graphdb")


@pytest.fixture
def file_tracker(metadata_store: SQLiteMetadataStore) -> FileTracker:
    """Return a FileTracker sharing the metadata store's connection."""
    return FileTracker(metadata_store._conn)
