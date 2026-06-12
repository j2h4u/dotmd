# Testing Patterns

**Analysis Date:** 2026-05-10

## Test Framework

**Runner:**
- pytest 8.x (declared `pytest>=8.0` in `backend/pyproject.toml`)
- Config: `backend/pyproject.toml` `[tool.pytest.ini_options]`

**Async support:**
- pytest-asyncio 0.24+ with `asyncio_mode = "auto"` — all `async def` test functions run automatically without `@pytest.mark.asyncio`

**Assertion Library:**
- pytest's built-in `assert` (no third-party assertion library)

**Run Commands:**
```bash
cd backend
# Run all tests (stops on first failure by default — addopts = "-x --tb=short")
python -m pytest

# Run a specific subdir
python -m pytest tests/ingestion/

# Run a specific file
python -m pytest tests/ingestion/test_pipeline_metadata.py

# Run with verbose output
python -m pytest -v

# Disable fail-fast for full run
python -m pytest --no-header -p no:cacheprovider

# E2E inside container (must run as docker exec)
docker exec dotmd sh -c "cd /mnt/home/repos/j2h4u/dotmd/backend && python -m pytest tests/e2e/ -v -p no:cacheprovider"
```

## Test File Organization

**Location:** Separate `backend/tests/` tree, NOT co-located with source.

**Structure mirrors `src/dotmd/`:**
```
backend/tests/
├── conftest.py               # Global autouse fixtures (env, mock semantic, mock schema check)
├── ingestion/                # Mirrors src/dotmd/ingestion/
│   ├── conftest.py           # (not present — uses root conftest)
│   ├── test_pipeline_metadata.py
│   ├── test_incremental_pipeline.py
│   ├── test_telegram_provider.py
│   └── application_source_fixtures.py  # Shared helper module (not a conftest)
├── search/
│   ├── conftest.py           # search-specific fixtures (StubFederatedProvider, bundles)
│   └── test_federated.py
├── storage/
│   └── test_metadata_m2m.py
├── api/
│   └── test_service_search.py
├── mcp/
│   └── test_search_tool.py
├── cli/
│   └── test_search_output.py
├── core/
│   └── test_search_candidate.py
├── e2e/
│   ├── conftest.py           # MCP transport fixtures (http + stdio parametrize)
│   └── test_mcp_smoke.py
└── devtools/
    └── test_reranker_latency_bench.py
```

**Naming:**
- Test files: `test_<module_or_feature>.py`
- Test classes: `Test<FeatureName>` (e.g., `TestFirstIndex`, `TestToolSurface`)
- Test functions: `test_<what_it_asserts>` — descriptive, full sentence style
  (e.g., `test_metadata_only_change_calls_encode_batch_once`, `test_no_change_skips_encode_batch`)

## Test Structure

**Suite organization:**
```python
# File-level: module docstring states what it covers
"""Integration tests for Plan 02 pipeline branching logic (Phase 999.12).

Covers:
- Fast path detection: metadata-only vs body change vs no change
...
"""

# Class grouping (used when multiple related scenarios):
class TestFirstIndex:
    """First index (no fingerprints) treats all files as new."""

    @patch("dotmd.ingestion.source.discover_files")
    def test_first_index_ingests_all_files(self, mock_discover, ...):
        ...

# Module-level functions (no class) for standalone tests:
def test_no_change_skips_encode_batch(minimal_settings, tmp_path):
    ...
```

**Section separators** used within long test files to group related tests:
```python
# ── Fast path detection ──────────────────────────────────────────────────────
```

**Setup pattern:**
- Fixtures provide temp dirs, stores, settings
- Helper functions (prefixed with `_`) build test data inline: `_write_md(...)`, `_make_file_info(...)`, `_make_chunk(...)`
- `tmp_path` (pytest built-in) used universally for filesystem isolation; `tmp_dir` is a legacy alias defined in root conftest

**Teardown:** No explicit teardown — temp fixtures clean themselves up via pytest's `tmp_path` scoping.

## Autouse Fixtures (Global — `backend/tests/conftest.py`)

Three `autouse=True` fixtures apply to every test by default:

**`_dotmd_test_env`** — sets minimal env vars via `monkeypatch.setenv`:
- `DOTMD_EMBEDDING_URL=http://test-tei:8088` (non-routable stub)
- `DOTMD_EXTRACT_DEPTH=structural` (prevents NER model load)
- `DOTMD_FALKORDB_URL=redis://127.0.0.1:1` (unreachable fallback)

**`_mock_semantic_engine`** — patches `SemanticSearchEngine.encode_batch` to return zero-vectors (dimension 8) and `get_tei_model_id` to return `"stub-model"`. Opt out with:
```python
@pytest.mark.real_semantic_encode_batch
def test_my_test(...):
    ...
```

**`_mock_schema_version_check`** — patches `IndexingPipeline._check_schema_version` to no-op. Prevents schema wipe when tests construct a pipeline against a pre-populated fixture DB. Opt out with:
```python
@pytest.mark.real_schema_check
def test_schema_version_wipe_clears_all_state(...):
    ...
```

## Mocking

**Framework:** `unittest.mock` (`MagicMock`, `patch`, `monkeypatch`)

**Patch via decorator** for module-level functions:
```python
@patch("dotmd.ingestion.source.discover_files")
@patch("dotmd.ingestion.pipeline.read_file")
@patch("dotmd.ingestion.chunker.chunk_file")
def test_first_index_ingests_all_files(self, mock_chunk_file, mock_read_file, mock_discover, ...):
    mock_discover.return_value = [file_a, file_b]
    mock_chunk_file.side_effect = [[chunk_a], [chunk_b]]
```

**Patch via `monkeypatch.setattr`** for instance methods (preferred in fixture-heavy tests):
```python
monkeypatch.setattr(pipeline._semantic_engine, "_encode_via_tei", record_tei_boundary)
```

**Direct attribute injection** on pipeline internals:
```python
pipeline._semantic_engine = mock_engine
mock_engine.encode_batch = mock_encode
mock_engine.get_tei_model_id = MagicMock(return_value="test-model")
```

**Stub classes** (hand-written fakes, not MagicMock) for complex collaborators:
```python
class _TelegramSourceClientFixture:
    """Minimal stub matching the real TelegramSourceClient interface."""
    def describe_source(self) -> dict: ...
    def export_source_changes(self, cursor, limit, ...) -> dict: ...
    def search_messages(self, query, limit, ...) -> dict: ...
```

```python
class StubFederatedProvider:
    """Minimal stub federated provider for testing fan-out."""
    def __init__(self, candidates, sleep_seconds, raises): ...
    def search_native(self, query, limit) -> list[SearchCandidate]: ...
```

**What to mock:**
- External HTTP calls (TEI embedding server) — always mocked in unit/integration tests
- `discover_files` / `read_file` / `chunk_file` when testing pipeline orchestration logic
- `encode_batch` — replaced by zero-vector stub globally via autouse fixture
- FalkorDB — avoided in unit tests by patching graph-store construction to an in-memory test double
- Settings — constructed either as real `Settings(...)` with temp dirs or as `MagicMock()` with explicit attributes

**What NOT to mock:**
- SQLite / sqlite-vec storage — real in-memory or temp-file databases used directly
- FalkorDB connectivity — only in explicit live/integration tests
- Chunker logic — real chunker runs in most integration tests
- Pydantic model construction and validation — always real

## Fixtures and Factories

**Root conftest shared fixtures:**
```python
@pytest.fixture
def metadata_store(tmp_path: Path):
    """SQLiteMetadataStore with M2M table for the default strategy."""
    from dotmd.storage.metadata import SQLiteMetadataStore
    store = SQLiteMetadataStore(db_path=tmp_path / "metadata.db", table_name="chunks_heading_512_50")
    store.ensure_m2m_table("heading_512_50")
    return store

@pytest.fixture
def vector_store(tmp_path: Path):
    """SQLiteVecVectorStore backed by a temp file DB."""
    ...

@pytest.fixture
def graph_store():
    """InMemoryGraphStore test double."""
    ...
```

**Local fixtures defined per-file** for test-specific settings:
```python
@pytest.fixture
def minimal_settings(tmp_path):
    """Minimal settings for pipeline construction without live TEI."""
    from dotmd.core.config import Settings
    return Settings(data_dir=..., index_dir=..., embedding_url="http://localhost:18088", ...)
```

**Factory helpers** (module-level `_`-prefixed functions, not fixtures):
```python
def _write_md(path: Path, title: str, tags: list, body: str) -> None: ...
def _make_file_info(path: str, title: str = "Test") -> FileInfo: ...
def _make_chunk(chunk_id: str, file_path: str) -> Chunk: ...
def _make_pipeline_with_mock_encode(settings) -> tuple[IndexingPipeline, list]: ...
def _dummy_embeddings(n: int) -> list[list[float]]: ...
```

**Fixture location:**
- `backend/tests/conftest.py` — global (metadata_store, vector_store, graph_store, tmp_dir, sqlite_conn)
- `backend/tests/search/conftest.py` — federated search fixtures (StubFederatedProvider, bundles)
- `backend/tests/e2e/conftest.py` — MCP transport fixtures
- `backend/tests/ingestion/application_source_fixtures.py` — shared data builders (not a conftest; imported explicitly)
- `backend/tests/fixtures/__init__.py` — placeholder (currently empty)

## Markers

Custom markers declared in `pyproject.toml`:

| Marker | Meaning |
|--------|---------|
| `smoke` | Requires a running dotMD stack |
| `e2e` | Against live MCP HTTP server inside container |
| `real_semantic_encode_batch` | Opt out of `_mock_semantic_engine` autouse |
| `real_schema_check` | Opt out of `_mock_schema_version_check` autouse |
| `asyncio` | Marks async test (usually automatic with `asyncio_mode = "auto"`) |

**Applying markers:**
```python
@pytest.mark.real_semantic_encode_batch
def test_embed_chunks_sends_context_prefixed_text(minimal_settings, monkeypatch): ...

@pytest.mark.real_schema_check
def test_schema_version_wipe_clears_all_state(minimal_settings, tmp_path): ...

pytestmark = pytest.mark.e2e  # module-level, applies to all tests in file
```

## Coverage

**Requirements:** No enforced minimum — no `--cov` flag in `addopts`.

**View Coverage:**
```bash
cd backend
python -m pytest --cov=src/dotmd --cov-report=term-missing
```

## Test Types

**Unit tests** (majority):
- Scope: single function or class method in isolation
- Location: `backend/tests/` root and subdirs
- Use real SQLite/sqlite-vec; mock TEI, external HTTP, and graph-store construction unless the test is explicitly live

**Integration tests:**
- Scope: full pipeline end-to-end with real storage backends and mocked embeddings
- Key files: `test_pipeline_metadata.py`, `test_incremental_pipeline.py`, `test_migration_v16.py`
- Construct `IndexingPipeline` against temp dirs; exercise `pipeline.index(data_dir)` calls

**E2E / smoke tests:**
- Location: `backend/tests/e2e/` — marked `@pytest.mark.e2e`
- Require live dotMD stack inside container; not run in default `pytest` invocation
- Parametrized over `http` and `stdio` transports
- Pin the MCP tool surface with `EXPECTED_TOOLS` frozenset and fail on drift

**Benchmark/devtools tests:**
- Location: `backend/tests/devtools/`
- Not part of regular CI; run manually for latency and quality benchmarking

## Common Patterns

**Call-count assertion (encode_batch call tracking):**
```python
call_log = []
def mock_encode(texts):
    call_log.append(list(texts))
    return [dummy_vec[:] for _ in texts]

pipeline._semantic_engine.encode_batch = mock_encode
pipeline.index(data_dir)

assert len(call_log) == 1, f"Metadata-only change must trigger exactly 1 encode_batch call, got {len(call_log)}: {call_log}"
assert len(call_log[0]) == 1
```

**Assertion messages:** All non-trivial `assert` statements include a descriptive f-string message explaining what invariant was violated and what was actually observed.

**DB state inspection** (integration tests access pipeline internals directly):
```python
chunk_count = pipeline._conn.execute(
    f"SELECT COUNT(*) FROM chunks_{pipeline._strategy}"
).fetchone()[0]
```

**Error testing:**
```python
with pytest.raises(ValueError, match="ref must be formatted as"):
    SearchCandidate(ref="bad-ref", ...)
```

**Async testing:**
```python
# asyncio_mode = "auto" means no decorator needed:
async def test_federated_fan_out_timeout(bundles):
    result = await service.search_async(query="test", ...)
    assert result.source_status[0].status == "error"
```

**Surface contract pinning** (e2e tests):
```python
EXPECTED_TOOLS: frozenset[str] = frozenset({"search", "read", "drill", "feedback"})

def test_tool_list_matches_pinned(self, mcp_call):
    data = mcp_call("tools/list")
    actual = frozenset(t["name"] for t in data["result"]["tools"])
    assert actual == EXPECTED_TOOLS, f"Tool surface drift: {actual ^ EXPECTED_TOOLS}"
```

---

*Testing analysis: 2026-05-10*
