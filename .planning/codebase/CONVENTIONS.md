# Coding Conventions

**Analysis Date:** 2026-03-23

## Naming Patterns

**Files:**
- Lowercase with underscores: `semantic.py`, `metadata.py`, `ner.py`
- Protocol definitions use `_protocol` suffix or no suffix (e.g., `base.py` contains protocols)
- Module grouping: `storage/base.py`, `search/base.py`, `extraction/base.py` hold protocol definitions
- Package-level exports in `__init__.py` (minimal re-exports for public API)

**Functions:**
- Lowercase with underscores: `discover_files()`, `read_file()`, `chunk_file()`
- Private/internal functions prefixed with single underscore: `_extract_title()`, `_get_model()`, `_load_model()`
- Public methods no prefix: `index()`, `search()`, `extract()`
- Boolean returns named with verb phrases: `is_file()`, `exists()` (stdlib patterns)

**Variables:**
- Lowercase with underscores: `chunk_id`, `vector_store`, `embedding_url`, `query_tokens`
- Type-hinted collections use plural: `results: list[Chunk]`, `embeddings: list[list[float]]`
- Abbreviations for common objects: `conn` (connection), `ctx` (context), `r` (result in loops)
- Class instance variables private with underscore: `self._model`, `self._settings`, `self._vector_store`

**Types:**
- Pydantic models use PascalCase: `FileInfo`, `Chunk`, `SearchResult`, `IndexStats`, `Entity`, `Relation`
- Protocol classes PascalCase with `Protocol` suffix: `VectorStoreProtocol`, `SearchEngineProtocol`, `ExtractorProtocol`
- Literal types lowercase: `Literal["structural", "ner"]`, `Literal["semantic", "bm25", "graph", "hybrid"]`

## Code Style

**Formatting:**
- No explicit linter configured (pyproject.toml has no linting tools listed)
- Style follows PEP 8 implicitly
- Line length not enforced but generally short (most lines <100 characters)
- Docstrings use double quotes: `"""Triple-quoted docstrings"""`

**Linting:**
- No linting configuration detected in `pyproject.toml`
- Uses `from __future__ import annotations` at file start for forward compatibility

## Import Organization

**Order:**
1. `from __future__ import annotations` (always first)
2. Standard library (`logging`, `json`, `sqlite3`, `pathlib`, `datetime`, `re`)
3. Third-party packages (`pydantic`, `click`, `sentence_transformers`, `fastapi`, `pyyaml`)
4. Local imports (`from dotmd.core.models import ...`)
5. TYPE_CHECKING conditional imports (for type hints only):
   ```python
   from typing import TYPE_CHECKING
   if TYPE_CHECKING:
       from gliner import GLiNER
   ```

**Path Aliases:**
- No aliases configured; uses absolute imports: `from dotmd.core.models import ...`
- Package root is `src/dotmd/` (importable as `dotmd`)

## Error Handling

**Patterns:**
- Custom exception hierarchy defined in `dotmd.core.exceptions`:
  - Base: `DotMDError(Exception)`
  - Specific: `IndexError`, `IndexNotFoundError`, `ChunkingError`, `StorageError`, `SearchError`, `ExtractionError`, `ConfigError`
- Exceptions are specific but not heavily used in current code
- OSError caught at ingestion layer with warning log:
  ```python
  except OSError:
      logger.warning("Skipping unreadable file: %s", md_path, exc_info=True)
  ```
- Early validation: `discover_files()` raises `FileNotFoundError` and `NotADirectoryError` for invalid input
- HTTP errors explicitly raised: `response.raise_for_status()` in TEI embedding code
- No try-except in core logic; errors propagate to caller or CLI

## Logging

**Framework:** Python standard `logging` module

**Setup:** Centralized in `utils/logging.py`:
```python
def setup_logging(verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("dotmd")
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
```

**Patterns:**
- Module-level loggers: `logger = logging.getLogger(__name__)`
- Info level for major operations: `logger.info("Discovered %d files", count)`
- Debug level for details: `logger.debug("Expanded query: %r -> %r", old, new)`
- Warning level for recoverable issues: `logger.warning("Skipping unreadable file: %s", path, exc_info=True)`
- Exception info logged: `exc_info=True` passed to include stack traces
- Log messages use printf-style formatting: `logger.info("Value: %s", value)` not f-strings
- All log calls are at module level (not in methods of classes with state)

## Comments

**When to Comment:**
- Module docstrings: Every file has a `"""..."""` docstring explaining purpose
- Function/method docstrings: All public methods documented with NumPy-style sections (Parameters, Returns, Raises)
- Complex algorithms: `_extract_best_snippet()` has comments explaining windowing logic
- Inline comments for non-obvious code: e.g., "Word-aware truncation at the end"
- **NOT** commented: obvious code, self-explanatory variable names

**JSDoc/TSDoc:**
- Not applicable (Python project)
- Uses NumPy-style docstrings with sections:
  ```python
  def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
      """Search and return ``(chunk_id, score)`` pairs.

      Parameters
      ----------
      query:
          The natural-language search query.
      top_k:
          Maximum number of results to return.

      Returns
      -------
      list[tuple[str, float]]
          A list of ``(chunk_id, score)`` pairs ordered by descending relevance.
      """
  ```

## Function Design

**Size:** Functions are short and focused:
- Utility functions: 10-40 lines (e.g., `_extract_title()`, `_truncate()`)
- Search methods: 30-80 lines with clear subsections (e.g., `DotMDService.search()`)
- Pipeline orchestration: 40-120 lines with numbered steps in docstring

**Parameters:**
- Named parameters preferred over positional; most functions use keyword args
- Defaults for common values: `top_k: int = 10`, `threshold: float = 0.5`
- Type hints required (enforced by `from __future__ import annotations`)
- Protocols used for abstraction: `vector_store: VectorStoreProtocol`

**Return Values:**
- Single return type or `None`: `list[SearchResult]`, `IndexStats | None`
- Tuples for pairs: `list[tuple[str, float]]` for (chunk_id, score) pairs
- Domain models (Pydantic) for complex data: returns `SearchResult` not dict
- Early returns for guards:
  ```python
  if not directory.exists():
      raise FileNotFoundError(...)
  ```

## Module Design

**Exports:**
- Public classes/functions at module level; no `__all__` defined
- Protocols imported into `storage/base.py`, `search/base.py`, `extraction/base.py` for discoverability
- Private modules (eval, visualize_graph) not part of public API
- Service facade `DotMDService` is the only public entry point for integration

**Barrel Files:**
- Minimal use; `__init__.py` files mostly empty or contain just imports of protocols
- Example: `storage/__init__.py` may import `VectorStoreProtocol` for convenience

## Architecture Principles

**Dependency Injection:**
- Settings object passed to pipeline and service
- Storage backends created by pipeline, passed to search engines
- Extractors created by pipeline, not in search layer
- No global singletons; stateless functions preferred

**Protocol-Based Abstraction:**
- All storage implementations satisfy `VectorStoreProtocol`, `GraphStoreProtocol`, `MetadataStoreProtocol`
- All search engines satisfy `SearchEngineProtocol`
- All extractors satisfy `ExtractorProtocol`
- Enables swapping backends without API changes

**Lazy Loading:**
- Models (SentenceTransformer, GLiNER, cross-encoder) loaded on first use via `_load_model()` methods
- BM25 index loaded when first search occurs, cached in instance
- Warmup method available: `DotMDService.warmup()` for eager loading

**No Per-Request Reloading:**
- Indexes (BM25, vector, graph) loaded once at startup and reused
- Critical performance principle: calling `load_index()` inside search methods would cause disk I/O per query

---

*Convention analysis: 2026-03-23*
