# Testing Patterns

**Analysis Date:** 2026-03-23

## Test Framework

**Status:** No automated test suite currently implemented.

**Runner:**
- Not detected. No `pytest.ini`, `pyproject.toml` test configuration, or `conftest.py` found.

**Assertion Library:**
- Not applicable (no tests present)

**Run Commands:**
- Testing infrastructure not yet set up

## Test File Organization

**Current State:**
- No `test_*.py` or `*_test.py` files found in codebase
- Evaluation code exists in `backend/eval/` for external benchmarking (HotpotQA dataset), separate from unit tests
- Evaluation is ad-hoc, not integrated into testing framework

**Recommended Pattern (when tests are added):**
- Location: Co-located with source code
  - Example: `src/dotmd/search/test_semantic.py` for `src/dotmd/search/semantic.py`
  - Or: `tests/unit/search/test_semantic.py` for cleaner separation
- Naming: `test_<module>.py` convention
- Structure: One test file per module or logical group

## Manual Testing Patterns (Current Approach)

**CLI-Based:**
The project uses manual CLI testing during development:
```bash
# Index sample data
dotmd index ./data/

# Perform searches
dotmd search "your query"

# Check index stats
dotmd status

# Test with options
dotmd search "query" --mode hybrid --no-rerank --no-expand
```

**Evaluation Scripts (`backend/eval/`):**
External evaluation harness for benchmarking against HotpotQA dataset:
- `eval/run_hotpotqa.py` — Main evaluation runner
- `eval/data_prep.py` — Dataset preparation
- `eval/metrics.py` — Metrics computation (MRR, NDCG, etc.)
- `eval/models.py` — Evaluation data structures

Usage pattern (inferred from codebase):
```bash
cd backend
python -m eval --dataset hotpotqa --top-k 10
```

**Visualization:**
- `visualize_graph.py` — Ad-hoc script to inspect knowledge graph structure

## Mock/Stub Patterns

**No mocking framework currently used** (no pytest-mock, unittest.mock imports found)

**Recommended approach when adding tests:**

**Protocol-based mocking:**
Use Protocols to create test doubles. Example pattern for `VectorStoreProtocol`:

```python
from dotmd.storage.base import VectorStoreProtocol
from dotmd.core.models import Chunk

class MockVectorStore:
    """Test double for VectorStoreProtocol."""

    def __init__(self, return_hits: list[tuple[str, float]] | None = None):
        self.return_hits = return_hits or []
        self.calls: list[tuple[list[float], int]] = []

    def add_chunks(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        self.stored_chunks = chunks
        self.stored_embeddings = embeddings

    def search(self, query_embedding: list[float], top_k: int = 10) -> list[tuple[str, float]]:
        self.calls.append((query_embedding, top_k))
        return self.return_hits[:top_k]

    def delete_all(self) -> None:
        self.stored_chunks = []

    def count(self) -> int:
        return len(self.stored_chunks)
```

Similarly for `SearchEngineProtocol`, `ExtractorProtocol`, etc.

## Testing Architecture Implications

**Dependency Injection enables testing:**
- `DotMDService` accepts `Settings` parameter; can pass test settings with temp directories
- `IndexingPipeline` accepts `Settings`; can be instantiated with mock stores
- Storage backends injected; can pass test doubles

**Example test structure:**

```python
import tempfile
from pathlib import Path
from dotmd.core.config import Settings
from dotmd.api.service import DotMDService

def test_search_with_mock_store():
    """Test search without hitting real vector store."""
    with tempfile.TemporaryDirectory() as tmpdir:
        settings = Settings(index_dir=Path(tmpdir))
        service = DotMDService(settings=settings)
        # ... arrange, act, assert
```

## Integration Testing Opportunities

**Areas suitable for integration testing:**
- Full indexing pipeline: file discovery → chunking → vector embedding → graph population
- Search fusion: multiple engines → RRF → reranking
- End-to-end CLI workflows: `dotmd index` → `dotmd search`
- Storage layer: metadata persistence to SQLite, vector search across backends

**Not yet implemented** but architecture supports it via:
- Sample markdown files in `backend/data/` directory
- Settings configured for test paths
- CLI commands fully functional

## Coverage

**Status:** No coverage requirements enforced.

**Recommendation:** When tests added, target:
- Core logic: `search/`, `ingestion/`, `extraction/` (>80% coverage)
- Storage backends: Each `VectorStoreProtocol` implementation (>75%)
- CLI: Happy-path commands (>70%)
- Error handling: Exception paths in `ingestion/reader.py`, `storage/` modules

## Test Types

**Unit Tests (when added):**
- Scope: Single function or class method in isolation
- Approach: Mock all dependencies; use test doubles for protocols
- Examples:
  - `test_extract_best_snippet()` — text windowing logic with various query patterns
  - `test_chunk_file()` — chunking with different token lengths
  - `test_entity_deduplication()` — NER duplicate handling

**Integration Tests (when added):**
- Scope: Multiple components working together
- Approach: Use real storage (in-memory SQLite, temp LanceDB) but mock external services (TEI embeddings)
- Examples:
  - Test full indexing of sample markdown files
  - Test search across all three engines
  - Test query expansion + search pipeline

**E2E Tests:**
- Not implemented
- Would require Docker composition or local service startup
- Could test CLI commands against running API server

## Logging in Tests

Tests should suppress or capture logger output:

```python
import logging

def test_with_logging(caplog):
    """caplog is pytest fixture for capturing logs."""
    with caplog.at_level(logging.INFO):
        service.search("query")

    assert "query" in caplog.text or len(caplog.records) > 0
```

Alternatively, configure logger to be silent:

```python
logging.getLogger("dotmd").setLevel(logging.CRITICAL)
```

## Performance/Stress Testing

**Evaluation suite in `backend/eval/`** provides benchmarking:
- Runs searches against HotpotQA dataset (thousands of queries)
- Tracks metrics: MRR (Mean Reciprocal Rank), NDCG (Normalized Discounted Cumulative Gain)
- Identifies bottlenecks in search quality and speed

**Not load-testing yet** but architecture supports it:
- Vector store backends (LanceDB, SQLite-vec) can handle large indexes
- Graph store (LadybugDB) scales to thousands of nodes/edges
- BM25 index can be built incrementally

## Test Data and Fixtures

**Sample data location:** `backend/data/` directory contains markdown files for testing

**Fixture patterns (when tests added):**

```python
import pytest
from pathlib import Path
from dotmd.core.models import Chunk, FileInfo

@pytest.fixture
def sample_chunk() -> Chunk:
    """A test chunk."""
    return Chunk(
        chunk_id="test-001",
        file_path=Path("test.md"),
        heading_hierarchy=["Introduction", "Background"],
        level=2,
        text="Sample chunk text for testing.",
        chunk_index=0,
        char_offset=0,
    )

@pytest.fixture
def sample_file_info() -> FileInfo:
    """Metadata about a test markdown file."""
    return FileInfo(
        path=Path("test.md"),
        title="Test Document",
        last_modified=datetime.now(timezone.utc),
        size_bytes=1024,
    )
```

Factory patterns for generating test data:

```python
def make_chunks(count: int, text_prefix: str = "Chunk") -> list[Chunk]:
    """Factory for creating N test chunks."""
    return [
        Chunk(
            chunk_id=f"chunk-{i}",
            file_path=Path(f"file-{i}.md"),
            text=f"{text_prefix} {i}",
            chunk_index=i,
            char_offset=i * 100,
        )
        for i in range(count)
    ]
```

## What to Mock, What NOT to Mock

**MOCK (test doubles):**
- External services: TEI embedding servers, HuggingFace model hub (use local models instead)
- Storage backends in unit tests: Replace with protocol-compatible test doubles
- HTTP calls: Use `httpx` mock or responses library
- File system (in isolation): Use `tempfile` or `pathlib`

**DO NOT MOCK:**
- Core domain logic: `chunk_file()`, `fuse_results()`, `extract_title()`
- Pydantic model instantiation: Test with real model instances
- Actual storage backends in integration tests: Use real in-memory or temp instances
- CLI argument parsing: Test with Click's test runner

## Recommended Testing Strategy

**Phase 1 (Foundation):**
1. Add pytest to `pyproject.toml` under `[project.optional-dependencies]`
2. Create `tests/` directory with `conftest.py`
3. Write unit tests for pure functions: `test_extract_best_snippet()`, `test_truncate()`, `_extract_title()`
4. Write unit tests for models: ensure Pydantic validation works correctly

**Phase 2 (Integration):**
1. Test storage backends with real in-memory SQLite and temp LanceDB
2. Test search engines with mock stores
3. Test indexing pipeline end-to-end with sample data
4. Test RRF fusion logic with synthetic ranked lists

**Phase 3 (E2E):**
1. CLI command tests using Click's `CliRunner`
2. FastAPI endpoint tests using `TestClient`
3. Full workflow tests: index → search → verify results

---

*Testing analysis: 2026-03-23*
