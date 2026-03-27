# Phase 8: Smoke Tests - Research

**Researched:** 2026-03-27
**Domain:** Python smoke testing against a live HTTP API (pytest + httpx)
**Confidence:** HIGH

## Summary

Phase 8 adds a smoke test suite that validates all three search engines (semantic, BM25, graph), hybrid fusion, and the HTTP API against a **running** dotMD stack. The tests are external -- they hit the API over HTTP, not internal Python imports. This is the right approach because: (1) dotmd requires TEI and FalkorDB which run as separate containers, (2) the production stack is already deployed and healthy on localhost:8321, (3) external tests validate the full stack including serialization and Docker networking.

The implementation is straightforward: a `tests/smoke/` directory with pytest tests using `httpx` (already a project dependency) as the HTTP client. A conftest fixture probes the API health endpoint at startup and skips the entire suite if the stack is unreachable. The tests run **outside** the container, on the host, against the production URL.

**Primary recommendation:** Use httpx synchronous client in pytest tests hitting `http://localhost:8321` by default, with `DOTMD_SMOKE_URL` env var override. Skip-on-unavailable via a session-scoped fixture that checks `/health`.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TEST-01 | Smoke test verifies semantic search returns results for a known-indexed query | Single test: GET `/search?mode=semantic&q=<query>`, assert `count > 0` and all `matched_engines` contain `"semantic"` |
| TEST-02 | Smoke test verifies BM25 search returns results for a known-indexed query | Single test: GET `/search?mode=bm25&q=<query>`, assert `count > 0` and all `matched_engines` contain `"bm25"` |
| TEST-03 | Smoke test verifies graph search returns results for a known-indexed query | Single test: GET `/search?mode=graph&q=<query>`, assert `count > 0` and all `matched_engines` contain `"graph"` |
| TEST-04 | Smoke test verifies hybrid fusion combines results from multiple engines | Test: GET `/search?mode=hybrid&q=<query>`, collect all unique values from `matched_engines` across results, assert at least 2 different engines present |
| TEST-05 | Smoke test verifies API returns HTTP 200 with valid JSON on search endpoint | Test: GET `/search?q=test`, assert status 200, assert response parses as JSON matching `SearchResponse` schema (has `query`, `results`, `count` fields) |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Never run dotmd on host** -- always Docker or API (from memory/feedback_containers_first.md)
- **Tests run outside container** -- pytest runs on host, hits the containerized API over HTTP
- **pytest >= 8.0** already in dev dependencies (`pyproject.toml`)
- **httpx >= 0.27** already in main dependencies (version 0.28.1 installed)
- **No CI/CD** -- tests must work in manual dev workflow, skip gracefully when stack is down
- **Production port**: 8321 (localhost only)
- **CPU**: Xeon E3 V2 with AVX but NOT AVX2 -- PyTorch <2.5 only (not relevant for smoke tests, but context)

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | 8.3.5 | Test framework | Already in dev deps, industry standard |
| httpx | 0.28.1 | HTTP client for API calls | Already a project dependency, sync + async support |

### Supporting

No additional libraries needed. Everything required is already installed.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| httpx | requests | requests is not a project dependency; httpx already is |
| httpx | FastAPI TestClient | TestClient runs in-process -- would need TEI/FalkorDB mocking, defeats smoke test purpose |
| pytest | bare script | pytest gives skip logic, fixtures, markers, reporting for free |

**Installation:**
```bash
# Nothing new needed -- pytest is in dev deps, httpx in main deps
cd backend && pip install -e ".[dev]"
```

## Architecture Patterns

### Recommended Project Structure

```
backend/
├── tests/
│   ├── conftest.py          # Existing -- unit test fixtures (unchanged)
│   ├── test_*.py            # Existing unit tests (unchanged)
│   └── smoke/
│       ├── __init__.py      # Empty
│       ├── conftest.py      # Smoke-specific: API client fixture, skip logic
│       ├── test_search_engines.py   # TEST-01, TEST-02, TEST-03
│       ├── test_hybrid_fusion.py    # TEST-04
│       └── test_api.py              # TEST-05
└── pyproject.toml           # Add [tool.pytest.ini_options] markers
```

### Pattern 1: Skip-on-Unavailable via Session Fixture

**What:** A session-scoped conftest fixture probes `/health` once at collection time. If unreachable, all smoke tests are skipped (not failed).

**When to use:** Always -- this is the core mechanism for the "CI-less dev workflow" requirement.

**Example:**
```python
# tests/smoke/conftest.py
import os
import pytest
import httpx

DOTMD_URL = os.environ.get("DOTMD_SMOKE_URL", "http://localhost:8321")


def pytest_collection_modifyitems(config, items):
    """Skip all smoke tests if the stack is unreachable."""
    try:
        r = httpx.get(f"{DOTMD_URL}/health", timeout=5.0)
        if r.status_code == 200:
            return  # Stack is up -- run tests
    except httpx.ConnectError:
        pass
    except Exception:
        pass

    skip_marker = pytest.mark.skip(reason=f"dotMD stack not reachable at {DOTMD_URL}")
    for item in items:
        item.add_marker(skip_marker)


@pytest.fixture(scope="session")
def api_url() -> str:
    """Base URL for the dotMD API."""
    return DOTMD_URL


@pytest.fixture(scope="session")
def client() -> httpx.Client:
    """Reusable HTTP client for the test session."""
    with httpx.Client(base_url=DOTMD_URL, timeout=30.0) as c:
        yield c
```

**Why `pytest_collection_modifyitems` instead of `skipif`:** The hook runs once before any test, so the health check happens exactly once. A fixture-based `pytest.skip` would need to be called in each test or module. The hook approach means zero boilerplate in test files.

**Why 30s timeout on client:** Model warmup can cause slow first responses. 30s is conservative but safe.

### Pattern 2: Test Against Known-Indexed Data

**What:** The production stack has 229 voicenotes / 532 chunks indexed. Tests use queries that are known to return results from this corpus.

**When to use:** Every search engine test.

**Critical detail:** The corpus is Russian-language voicenotes. Test queries should match content actually in the index. The word "test" did return results from all three engines (verified empirically above). The query "smoke" also works for BM25 since that exact word appears in the corpus.

**Query strategy:**
- Use a generic query like `"test"` which returns results from all engines (verified)
- For BM25 specifically, keyword matches are strong -- `"test"` returned BM25 results with score 5.9
- For graph, seed expansion from semantic/BM25 hits propagates -- `"test"` in graph mode returned results
- Alternative: use the `/status` endpoint first to confirm `total_chunks > 0`, skip if empty

### Pattern 3: Response Schema Validation

**What:** Validate the JSON response structure matches the expected `SearchResponse` model without importing internal dotmd code.

**Example:**
```python
def test_api_search_returns_valid_json(client: httpx.Client):
    r = client.get("/search", params={"q": "test", "top_k": 3})
    assert r.status_code == 200

    data = r.json()
    assert "query" in data
    assert "results" in data
    assert "count" in data
    assert isinstance(data["results"], list)
    assert data["count"] == len(data["results"])

    if data["results"]:
        result = data["results"][0]
        assert "chunk_id" in result
        assert "file_path" in result
        assert "snippet" in result
        assert "fused_score" in result
        assert "matched_engines" in result
        assert isinstance(result["matched_engines"], list)
```

### Anti-Patterns to Avoid

- **Importing dotmd inside smoke tests:** Smoke tests must NOT `import dotmd`. They are external HTTP tests. Importing dotmd would require the full dependency tree (torch, sentence-transformers, etc.) on the host, which contradicts the "containers first" principle.
- **Hardcoding chunk_ids or file paths:** The index content may change when more files are indexed. Test for `count > 0` and structural validity, not specific chunk IDs.
- **Using FastAPI TestClient:** This creates an in-process app instance requiring TEI and FalkorDB connections from the test process. Defeats the purpose of smoke testing the deployed stack.
- **Failing instead of skipping when stack is down:** The success criteria explicitly require graceful skip.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP client | urllib/socket code | httpx | Already a dependency, handles timeouts, connection errors cleanly |
| Test skip logic | Custom decorator on each test | `pytest_collection_modifyitems` hook | One check per session, zero boilerplate in tests |
| JSON validation | Manual dict traversal | Simple assert checks on known fields | Full Pydantic validation would require importing dotmd models |

**Key insight:** These smoke tests are intentionally thin. They validate "is the system working?" not "is the business logic correct?" -- that's what the existing unit tests in `tests/test_*.py` do.

## Common Pitfalls

### Pitfall 1: Slow First Request After Container Start

**What goes wrong:** First search request after container restart can take 10-30s due to model warmup (cross-encoder, BM25 index loading).
**Why it happens:** The `warmup()` call in the lifespan handler loads models eagerly, but if the container just started, it may still be warming up when tests connect.
**How to avoid:** The 30s timeout on httpx client handles this. The `/health` endpoint returns 200 before warmup completes (it's a liveness probe), but the Docker HEALTHCHECK on the container (which checks `/health`) with `start_period: 60s` means `docker ps` shows healthy only after the container has been up for a while. In practice, since we check health in collection_modifyitems, the stack should already be warm.
**Warning signs:** First test takes 15+ seconds, subsequent tests are fast.

### Pitfall 2: Empty Index

**What goes wrong:** All search tests return 0 results because no data has been indexed.
**Why it happens:** Fresh stack deployment without running `dotmd index`.
**How to avoid:** Add a guard in conftest that checks `/status` and skips with a clear message if `total_chunks == 0`. This is separate from the "stack unavailable" skip.
**Warning signs:** All search tests fail with "expected count > 0, got 0".

### Pitfall 3: Graph Search Returning Empty in Isolation

**What goes wrong:** `mode=graph` returns 0 results even though graph data exists.
**Why it happens:** Graph search requires seed chunk IDs from semantic+BM25. If those engines return nothing for the query, graph search has no seeds to expand from.
**How to avoid:** Use a query that returns results from semantic and/or BM25 first (like `"test"`, which is verified to work). The service code already handles this -- when `mode=graph`, it internally runs semantic+BM25 to get seeds.
**Warning signs:** Graph-only test returns empty while hybrid test succeeds.

### Pitfall 4: Pytest Collects Smoke Tests in Regular Runs

**What goes wrong:** Running `pytest tests/` includes smoke tests, which fail when stack is unavailable.
**Why it happens:** Default pytest collection walks all subdirectories.
**How to avoid:** The `pytest_collection_modifyitems` hook handles this -- tests are skipped, not failed. Additionally, register a `smoke` marker in pyproject.toml so users can run `pytest -m smoke` or `pytest -m "not smoke"` explicitly.

### Pitfall 5: Test Isolation Between Modes

**What goes wrong:** Tests pass when run in sequence but one test's assertion relies on side effects of another.
**Why it happens:** Shared state or ordering assumptions.
**How to avoid:** Each test makes its own HTTP request with explicit `mode` parameter. No shared state between tests. The `client` fixture is session-scoped (connection reuse) but each test sends independent requests.

## Code Examples

### Complete conftest.py

```python
"""Smoke test configuration -- runs against a live dotMD stack."""

import os

import httpx
import pytest

DOTMD_URL = os.environ.get("DOTMD_SMOKE_URL", "http://localhost:8321")


def pytest_collection_modifyitems(config, items):
    """Skip all smoke tests if the stack is unreachable."""
    try:
        r = httpx.get(f"{DOTMD_URL}/health", timeout=5.0)
        if r.status_code == 200:
            return
    except (httpx.ConnectError, httpx.TimeoutException):
        pass

    skip_marker = pytest.mark.skip(
        reason=f"dotMD stack not reachable at {DOTMD_URL}"
    )
    for item in items:
        item.add_marker(skip_marker)


@pytest.fixture(scope="session")
def api_url() -> str:
    return DOTMD_URL


@pytest.fixture(scope="session")
def client():
    with httpx.Client(base_url=DOTMD_URL, timeout=30.0) as c:
        yield c
```

### Search Engine Test Pattern

```python
"""Smoke tests for individual search engines (TEST-01, TEST-02, TEST-03)."""

import pytest


@pytest.mark.smoke
class TestSearchEngines:
    """Each search engine returns results for a known query."""

    def test_semantic_returns_results(self, client):
        """TEST-01: Semantic search returns results."""
        r = client.get("/search", params={"q": "test", "top_k": 5, "mode": "semantic"})
        assert r.status_code == 200
        data = r.json()
        assert data["count"] > 0, "Semantic search returned no results"
        for result in data["results"]:
            assert "semantic" in result["matched_engines"]

    def test_bm25_returns_results(self, client):
        """TEST-02: BM25 search returns results."""
        r = client.get("/search", params={"q": "test", "top_k": 5, "mode": "bm25"})
        assert r.status_code == 200
        data = r.json()
        assert data["count"] > 0, "BM25 search returned no results"
        for result in data["results"]:
            assert "bm25" in result["matched_engines"]

    def test_graph_returns_results(self, client):
        """TEST-03: Graph search returns results."""
        r = client.get("/search", params={"q": "test", "top_k": 5, "mode": "graph"})
        assert r.status_code == 200
        data = r.json()
        assert data["count"] > 0, "Graph search returned no results"
        for result in data["results"]:
            assert "graph" in result["matched_engines"]
```

### Hybrid Fusion Test Pattern

```python
"""Smoke test for hybrid fusion (TEST-04)."""

import pytest


@pytest.mark.smoke
class TestHybridFusion:
    """Hybrid mode fuses results from multiple engines."""

    def test_hybrid_combines_multiple_engines(self, client):
        """TEST-04: Hybrid returns results from at least 2 engines."""
        r = client.get("/search", params={"q": "test", "top_k": 10, "mode": "hybrid"})
        assert r.status_code == 200
        data = r.json()
        assert data["count"] > 0, "Hybrid search returned no results"

        # Collect all engines that contributed to ANY result
        all_engines = set()
        for result in data["results"]:
            all_engines.update(result["matched_engines"])

        assert len(all_engines) >= 2, (
            f"Expected results from >= 2 engines, got only: {all_engines}"
        )
```

### pyproject.toml Addition

```toml
[tool.pytest.ini_options]
markers = [
    "smoke: smoke tests requiring a running dotMD stack",
]
```

## Verified API Response Structures

Verified against the running production stack (2026-03-27):

### GET /health
```json
{"status": "ok"}
```

### GET /status
```json
{
    "total_files": 229,
    "total_chunks": 532,
    "total_entities": 3520,
    "total_edges": 20269,
    "last_indexed": "2026-03-27T10:09:26.589000Z",
    "new_files": 0,
    "modified_files": 0,
    "deleted_files": 0,
    "unchanged_files": 229,
    "data_dir": "/mnt/voicenotes"
}
```

### GET /search?q=test&top_k=3&mode=semantic
```json
{
    "query": "test",
    "results": [
        {
            "chunk_id": "5ad85123...",
            "file_path": "/mnt/voicenotes/...",
            "heading_path": "",
            "snippet": "...",
            "fused_score": 0.86,
            "semantic_score": 0.59,
            "bm25_score": null,
            "graph_score": null,
            "matched_engines": ["semantic"]
        }
    ],
    "count": 3
}
```

**Key observations:**
- `matched_engines` is always a list of strings
- Score fields for non-participating engines are `null` (not 0 or absent)
- `fused_score` is always present and > 0 for returned results
- `heading_path` can be empty string
- `file_path` is an absolute path inside the container (starts with `/mnt/`)

## File Organization Decision

**5 test files in architecture research vs 3 in this plan:**

The architecture research (ARCHITECTURE.md) proposed 5 files: `test_search_engines.py`, `test_hybrid_fusion.py`, `test_api_endpoints.py`, `test_bm25_survival.py`, `test_status.py`. This phase only covers TEST-01 through TEST-05. The BM25 survival guard (TEST-07) and status endpoint tests are deferred to future requirements.

Recommended: **3 test files** to match the 5 requirements:
1. `test_search_engines.py` -- TEST-01, TEST-02, TEST-03 (one class, three methods)
2. `test_hybrid_fusion.py` -- TEST-04 (verifies multi-engine fusion)
3. `test_api.py` -- TEST-05 (HTTP 200 + JSON structure validation)

Plus `conftest.py` and `__init__.py`. Total: 5 files in `tests/smoke/`.

## Open Questions

1. **Query choice for reliable results**
   - What we know: `"test"` returns results from all 3 engines on current 229-file corpus (verified empirically)
   - What's unclear: Will this query still work after the full 13,500-file corpus is indexed? (Almost certainly yes -- more data means more matches, not fewer)
   - Recommendation: Use `"test"` as the default query. If the corpus changes significantly, query can be updated without structural changes

2. **Should tests validate score ranges?**
   - What we know: semantic_score ranges ~0.4-0.6, bm25_score ranges 1.5-6.0, graph_score is typically 22.0, fused_score ~0.5-0.9
   - What's unclear: Are these ranges stable across reindexes?
   - Recommendation: Do NOT assert score ranges. Only assert `count > 0`, correct `matched_engines`, and `fused_score > 0`. Score magnitudes can shift with model changes or corpus changes.

## Sources

### Primary (HIGH confidence)
- **Live production stack** -- all API response structures verified by curling localhost:8321 during research
- **Source code** -- `api/server.py`, `api/service.py`, `core/models.py` read directly to understand response schemas
- **Existing tests** -- `tests/conftest.py`, `tests/test_hybrid_bm25.py` examined for project test patterns

### Secondary (MEDIUM confidence)
- **Architecture research** -- `.planning/research/ARCHITECTURE.md` lines 510-590 had prior smoke test design (authored during v1.3 planning)
- **Todo** -- `.planning/todos/pending/2026-03-27-smoke-tests.md` captured original problem statement

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- pytest + httpx are already project dependencies, no new libraries
- Architecture: HIGH -- straightforward HTTP testing pattern, verified against live responses
- Pitfalls: HIGH -- all identified from direct experience with this specific codebase and deployment

**Research date:** 2026-03-27
**Valid until:** Indefinite -- smoke test patterns are stable; response structures would only change with API code changes
