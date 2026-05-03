"""Shared test fixtures for dotMD."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Global env fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _dotmd_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set minimal env vars so Settings() and IndexingPipeline can be constructed.

    - DOTMD_EMBEDDING_URL: required field with no default (prevents misconfiguration
      in production). A non-routable stub is fine — tests that need real embeddings
      mock the HTTP call at a higher level.
    - DOTMD_EXTRACT_DEPTH: override to 'structural' so tests that construct a full
      IndexingPipeline do not accidentally load NER models or call TEI during ingest.
      Tests that specifically exercise NER must override this fixture or set the env
      var directly.
    """
    monkeypatch.setenv("DOTMD_EMBEDDING_URL", "http://test-tei:8088")
    monkeypatch.setenv("DOTMD_EXTRACT_DEPTH", "structural")
    # Force local embedded graph — never touch production FalkorDB.
    # Fallback guard: even if graph_backend slips to falkordb, the URL points nowhere.
    monkeypatch.setenv("DOTMD_GRAPH_BACKEND", "ladybugdb")
    monkeypatch.setenv("DOTMD_FALKORDB_URL", "redis://127.0.0.1:1")


@pytest.fixture(autouse=True)
def _mock_semantic_engine(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """Patch SemanticSearchEngine to avoid real HTTP/model calls in tests.

    Tests that exercise the actual embedding pipeline should override this
    fixture or un-patch locally. The stub returns zero-vectors (dimension 8)
    which is enough for schema/idempotency tests that only check row counts.
    """
    if request.node.get_closest_marker("real_semantic_encode_batch"):
        yield
        return

    def _stub_encode_batch(texts: list[str]) -> list[list[float]]:
        return [[0.0] * 8 for _ in texts]

    def _stub_get_tei_model_id(self) -> str | None:  # type: ignore[no-untyped-def]
        return "stub-model"

    with patch(
        "dotmd.search.semantic.SemanticSearchEngine.encode_batch",
        side_effect=_stub_encode_batch,
    ), patch(
        "dotmd.search.semantic.SemanticSearchEngine.get_tei_model_id",
        _stub_get_tei_model_id,
    ):
        yield


@pytest.fixture(autouse=True)
def _mock_schema_version_check(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """Patch _check_schema_version to no-op in all tests.

    Prevents the schema wipe from firing when tests construct an IndexingPipeline
    with a pre-populated fixture DB (which has chunk_fingerprints rows and therefore
    looks like a pre-999.12 DB to the real check).

    Tests that specifically exercise _check_schema_version must opt out with:
        @pytest.mark.real_schema_check
    """
    if request.node.get_closest_marker("real_schema_check"):
        yield
        return
    with patch("dotmd.ingestion.pipeline.IndexingPipeline._check_schema_version"):
        yield


# ---------------------------------------------------------------------------
# Shared convenience fixtures (used by pre-phase-16 test files)
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """Alias for tmp_path — used by test files that predate pytest's tmp_path name."""
    return tmp_path


@pytest.fixture
def sqlite_conn(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """In-memory SQLite connection for FileTracker tests."""
    conn = sqlite3.connect(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def metadata_store(tmp_path: Path):
    """SQLiteMetadataStore with M2M table for the default strategy."""
    from dotmd.storage.metadata import SQLiteMetadataStore

    strategy = "heading_512_50"
    db_path = tmp_path / "metadata.db"
    store = SQLiteMetadataStore(db_path=db_path, table_name=f"chunks_{strategy}")
    store.ensure_m2m_table(strategy)
    return store


@pytest.fixture
def vector_store(tmp_path: Path):
    """SQLiteVecVectorStore backed by a temp file DB."""
    import sqlite3 as _sqlite3

    import sqlite_vec  # type: ignore[import-untyped]

    from dotmd.storage.sqlite_vec import SQLiteVecVectorStore

    db_path = tmp_path / "vec.db"
    conn = _sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    store = SQLiteVecVectorStore(table_name="vec_chunks", conn=conn)
    return store


@pytest.fixture
def graph_store(tmp_path: Path):
    """LadybugDBGraphStore backed by a temp directory."""
    from dotmd.storage.graph import LadybugDBGraphStore

    db_path = tmp_path / "graphdb"
    store = LadybugDBGraphStore(db_path=db_path)
    return store
