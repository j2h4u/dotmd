# Phase 10: Background Trickle Indexer - Research

**Researched:** 2026-03-28
**Domain:** Background processing, SQLite FTS5, filesystem watching, TOML configuration
**Confidence:** HIGH

## Summary

Phase 10 transforms dotMD from a batch-indexer into a continuously-running service that processes unindexed files one at a time in the background while the API serves search queries. The phase has four major workstreams: (1) replace `rank_bm25` + pickle with SQLite FTS5 for incremental BM25 search, (2) introduce `config.toml` with glob-based paths/exclude via `pydantic-settings[toml]`, (3) build a background indexer loop using `asyncio.create_task` within FastAPI's lifespan, and (4) add filesystem watching via `watchdog` for instant detection of new files.

All required technologies are well-supported. FTS5 is built into Python's bundled SQLite (verified: SQLite 3.46.1 with `unicode61` tokenizer available). The `watchdog` library (v6.0.0) is the de facto Python inotify wrapper. `pydantic-settings` v2.13+ has native TOML support via `TomlConfigSettingsSource`. FastAPI's `asynccontextmanager` lifespan pattern cleanly supports background task lifecycle with graceful shutdown.

**Primary recommendation:** Use `asyncio.Event` for shutdown signaling within a background `asyncio.Task` started in FastAPI's lifespan. FTS5 with a standalone table (not external content) co-located in `metadata.db` eliminates the entire BM25 rebuild problem. The `watchdog` Observer runs in its own thread and feeds events into the asyncio loop via `loop.call_soon_threadsafe`.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Background indexer is built into `dotmd serve` -- starts automatically when the server starts. No separate command or flag needed.
- **D-02:** Runs as a continuous loop: processes backlog of unindexed files, then watches for new files. Never stops until SIGTERM.
- **D-03:** Hybrid detection -- inotify (via watchdog library) as primary mechanism for instant reaction to new files, plus rare polling (e.g., once per hour) as fallback for cases where inotify misses events (Docker bind mounts, NFS).
- **D-04:** Initial backlog: on startup, discover all unindexed files via FileTracker diff and process them before switching to watch mode.
- **D-05:** Replace `rank_bm25` (BM25Okapi + pickle) with SQLite FTS5. Incremental INSERT per file -- no batch rebuilds, no pickle, no atomic swap needed. Each file becomes BM25-searchable immediately after indexing.
- **D-06:** FTS5 tokenizer: `unicode61` -- handles Cyrillic and other Unicode correctly. Parity with current tokenizer behavior (no stemming). Stemming deferred.
- **D-07:** This change makes BGIDX-04 (batched BM25 rebuild with atomic swap) obsolete -- satisfied by design since FTS5 is inherently incremental.
- **D-08:** Glob-based `paths` + `exclude` pattern -- same mental model as `.gitignore`/`tsconfig.json`. One `[indexing]` section in config.toml.
- **D-09:** `paths` entries can be directories (full recursive scan for .md) or glob patterns. `exclude` patterns filter out matches from both.
- **D-10:** Replaces single `data_dir` setting. `DOTMD_DATA_DIR` env var becomes comma-separated list fallback for Docker.
- **D-11:** Introduce `~/.dotmd/config.toml` as primary configuration source.
- **D-12:** Priority: env var overrides config.toml, config.toml overrides code defaults.
- **D-13:** `pydantic-settings` v2 supports TOML natively (`TomlConfigSettingsSource`).
- **D-14:** Sort unindexed files by mtime descending -- newest files first.
- **D-15:** `GET /status` and `dotmd status` return background indexer state.
- **D-16:** Logs: INFO-level log line per processed file with progress counter.
- **D-17:** On SIGTERM, finish processing the current file, then shut down cleanly.
- **D-18:** Configurable pause interval via config.toml + env var override.

### Claude's Discretion
- Threading/asyncio implementation for background loop (whatever fits FastAPI lifespan best)
- inotify event filtering (which events to watch, debouncing)
- Exact FTS5 table schema and migration from rank_bm25
- Polling interval for fallback (suggested: 1 hour)
- How to handle errors on individual files (skip and continue vs retry)
- Whether to keep rank_bm25 as a fallback or remove entirely

### Deferred Ideas (OUT OF SCOPE)
- Russian/English stemming for BM25 -- FTS5 supports custom tokenizers and ICU. Separate phase.
- FTS5 trigram tokenizer -- enables substring matching. Evaluate after FTS5 baseline works.
- Concurrent TEI requests -- Phase 9 benchmarks may show throughput gains.
- GLiNER batch NER -- Phase 9 benchmarks may show batching gains.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| BGIDX-01 | Background indexer discovers and processes unindexed files one at a time while API serves queries | asyncio.Task in FastAPI lifespan + FileTracker.diff() for discovery + SQLite WAL for concurrent access |
| BGIDX-02 | `dotmd status` reports background indexing progress | Extend IndexStats model with trickle fields; expose via GET /status and CLI |
| BGIDX-03 | Background indexer shuts down gracefully on SIGTERM (finishes current file, no corrupt state) | asyncio.Event shutdown flag checked between files; SQLite WAL ensures no corruption mid-write |
| BGIDX-04 | BM25 index rebuilds batched with atomic swap (OBSOLETED by D-07) | FTS5 incremental INSERT makes this requirement satisfied by design -- no batch rebuilds needed |
| BGIDX-05 | Configurable pause interval between files to control CPU pressure | `trickle_pause_seconds` in config.toml `[indexing]` section + `DOTMD_TRICKLE_PAUSE_SECONDS` env var |
| BGIDX-06 | Background indexer runs at low CPU priority via docker cpu-shares | Documentation only -- `docker update --cpu-shares 256` applied externally, not in code |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLite FTS5 | bundled (SQLite 3.46.1) | Incremental full-text search | Built into Python's sqlite3, zero dependencies, WAL-compatible, replaces rank_bm25 + pickle |
| watchdog | >=6.0 | Filesystem event monitoring (inotify) | De facto Python inotify wrapper, 120M+ downloads/month, pure Python with C extensions |
| pydantic-settings[toml] | >=2.0 (currently 2.13.1) | TOML config file loading | Already a dependency; `[toml]` extra adds tomli/tomllib support natively |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tomli | (auto via pydantic-settings[toml]) | TOML parsing on Python <3.11 | Automatically selected; Python 3.11+ uses stdlib tomllib |
| asyncio (stdlib) | builtin | Background task orchestration | Event loop for trickle indexer, shutdown signaling |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| FTS5 (standalone table) | FTS5 external content table | External content saves disk but requires triggers for sync and has consistency risks under concurrent writes |
| FTS5 | Tantivy/Whoosh | External dependency, more complex, no advantage for this use case |
| watchdog | inotifyx/pyinotify | watchdog is higher-level, cross-platform, better maintained |
| asyncio.Task | threading.Thread | asyncio integrates naturally with FastAPI/uvicorn; threading adds complexity with no benefit |

### Removal
| Library | Reason |
|---------|--------|
| rank-bm25 | Replaced by FTS5. Remove from pyproject.toml dependencies. |
| numpy (indirect) | rank-bm25's only consumer of numpy for BM25 scoring. Verify no other usage before removing. |

**Installation (pyproject.toml changes):**
```toml
# ADD:
"watchdog>=6.0",
"pydantic-settings[toml]>=2.0",  # was "pydantic-settings>=2.0"

# REMOVE:
"rank-bm25>=0.2",
```

## Architecture Patterns

### Recommended Project Structure Changes
```
src/dotmd/
├── core/
│   ├── config.py           # MODIFY: add TomlConfigSettingsSource, indexing paths/exclude, trickle settings
│   └── models.py           # MODIFY: extend IndexStats with trickle progress fields
├── ingestion/
│   ├── reader.py           # MODIFY: multi-path discovery with glob + exclude filtering
│   ├── trickle.py          # NEW: TrickleIndexer class (background loop + watchdog integration)
│   └── ...
├── search/
│   ├── bm25.py             # REWRITE: FTS5SearchEngine replacing BM25SearchEngine
│   └── ...
├── api/
│   ├── server.py           # MODIFY: start/stop TrickleIndexer in lifespan
│   └── service.py          # MODIFY: status() returns trickle progress
└── cli.py                  # MODIFY: status command shows trickle progress
```

### Pattern 1: Background Task via FastAPI Lifespan
**What:** Start an asyncio.Task during FastAPI startup, cancel it during shutdown.
**When to use:** Any long-running background work that must coordinate with the server lifecycle.
**Example:**
```python
# Source: FastAPI docs + verified pattern
import asyncio
from contextlib import asynccontextmanager

@asynccontextmanager
async def _lifespan(app: FastAPI):
    global _service
    _service = DotMDService(Settings())
    _service.warmup()

    # Start background indexer
    shutdown_event = asyncio.Event()
    indexer_task = asyncio.create_task(
        _service.trickle_indexer.run(shutdown_event)
    )

    yield

    # Signal shutdown, wait for current file to finish
    shutdown_event.set()
    await asyncio.wait_for(indexer_task, timeout=120)
    _service = None
```

### Pattern 2: Trickle Indexer Loop
**What:** Background loop that processes one file at a time with pause between files.
**When to use:** Continuous background work with controllable throughput.
**Example:**
```python
class TrickleIndexer:
    async def run(self, shutdown: asyncio.Event) -> None:
        """Main loop: process backlog, then watch for new files."""
        # Phase 1: Process existing backlog (newest first)
        unindexed = self._discover_unindexed()
        unindexed.sort(key=lambda fi: fi.last_modified, reverse=True)

        for i, file_info in enumerate(unindexed):
            if shutdown.is_set():
                return
            self._process_one_file(file_info)
            self._state.indexed_count = i + 1
            logger.info("Indexed %d/%d: %s", i + 1, len(unindexed), file_info.path)
            # Configurable pause for CPU pressure control
            await asyncio.sleep(self._pause_seconds)

        # Phase 2: Watch mode (inotify + polling fallback)
        self._start_watcher()
        while not shutdown.is_set():
            # Process any queued files from watchdog events
            while not self._file_queue.empty():
                file_info = self._file_queue.get_nowait()
                self._process_one_file(file_info)
            # Wait for shutdown or new file event
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=self._poll_interval)
                return  # shutdown was set
            except asyncio.TimeoutError:
                # Polling fallback: re-scan for files inotify may have missed
                self._queue_new_files()
```

### Pattern 3: Watchdog-to-Asyncio Bridge
**What:** watchdog Observer runs in its own thread; events are forwarded to the asyncio event loop.
**When to use:** Integrating threaded libraries with asyncio.
**Example:**
```python
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler

class _MarkdownEventHandler(PatternMatchingEventHandler):
    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue):
        super().__init__(patterns=["*.md"], ignore_directories=True)
        self._loop = loop
        self._queue = queue
        self._debounce: dict[str, float] = {}

    def on_created(self, event):
        self._enqueue(event.src_path)

    def on_modified(self, event):
        self._enqueue(event.src_path)

    def _enqueue(self, path: str):
        now = time.monotonic()
        # Debounce: ignore events within 2 seconds of each other for same file
        if path in self._debounce and now - self._debounce[path] < 2.0:
            return
        self._debounce[path] = now
        self._loop.call_soon_threadsafe(self._queue.put_nowait, path)
```

### Pattern 4: FTS5 Table Co-located in metadata.db
**What:** Create FTS5 virtual table in the same SQLite database as chunks/stats.
**When to use:** When FTS5 content mirrors existing table data and both need WAL-mode concurrent access.
**Rationale:** Putting FTS5 in `metadata.db` means it shares the same WAL-mode connection, same transaction boundaries, and same backup/clear lifecycle as chunk metadata. No separate file to manage.
**Example:**
```python
# In SQLiteMetadataStore.__init__() or a new FTS5SearchEngine
CREATE_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    chunk_id UNINDEXED,
    text,
    tokenize = 'unicode61'
)
"""

# Per-file insert (called during trickle indexing)
def add_to_fts(self, chunks: list[Chunk]) -> None:
    rows = [(c.chunk_id, c.text) for c in chunks]
    self._conn.executemany(
        "INSERT INTO chunks_fts(chunk_id, text) VALUES (?, ?)", rows
    )
    self._conn.commit()

# Per-file delete (called during file purge)
def remove_from_fts(self, chunk_ids: list[str]) -> None:
    for cid in chunk_ids:
        self._conn.execute(
            "DELETE FROM chunks_fts WHERE chunk_id = ?", (cid,)
        )
    self._conn.commit()

# Search
def search_fts(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
    # FTS5 rank is negative (lower = better match), negate for our convention
    cur = self._conn.execute(
        "SELECT chunk_id, rank FROM chunks_fts WHERE chunks_fts MATCH ? "
        "ORDER BY rank LIMIT ?",
        (query, top_k),
    )
    return [(row[0], -row[1]) for row in cur.fetchall()]
```

### Pattern 5: TOML Config with pydantic-settings
**What:** Add `config.toml` as a settings source with lower priority than env vars.
**When to use:** Structured settings (lists, nested objects) that are awkward as flat env vars.
**Example:**
```python
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, TomlConfigSettingsSource

class Settings(BaseSettings):
    model_config = {"env_prefix": "DOTMD_"}

    # New fields
    indexing_paths: list[str] = []
    indexing_exclude: list[str] = ["**/node_modules", "**/.git", "**/__pycache__"]
    trickle_pause_seconds: float = 1.0
    poll_interval_seconds: float = 3600.0  # 1 hour

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
            TomlConfigSettingsSource(settings_cls),
        )
```

```toml
# ~/.dotmd/config.toml
[indexing]
paths = [
    "/srv/knowledgebase/voicenotes",
    "/home/j2h4u/docs",
    "/home/j2h4u/**/README.md",
    "/home/j2h4u/**/AGENTS.md",
    "/home/j2h4u/**/CLAUDE.md",
]
exclude = ["**/node_modules", "**/.git", "**/__pycache__"]
trickle_pause_seconds = 1.0
```

### Anti-Patterns to Avoid
- **BM25 full rebuild per file:** O(N^2) at scale -- the whole point of FTS5 migration is to avoid this.
- **Blocking the event loop:** Never call synchronous I/O (file reads, embedding requests) directly in an async function. Use `asyncio.to_thread()` or `loop.run_in_executor()` for CPU/IO-bound per-file processing.
- **Per-request index reload:** CLAUDE.md explicitly forbids this. FTS5 queries go through the same long-lived SQLite connection.
- **Global mutable state without locks:** The trickle indexer's progress state (`indexed_count`, `total_files`, `state`) must be thread-safe since watchdog runs in a separate thread.
- **Ignoring watchdog debouncing:** File editors write temp files and rename -- a single "save" can trigger 3-4 events. Always debounce.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Full-text search index | Custom inverted index with pickle | SQLite FTS5 | FTS5 handles tokenization, ranking (BM25), incremental updates, concurrent reads, Unicode -- battle-tested in SQLite for 10+ years |
| Filesystem watching | Custom polling loop with os.stat | watchdog Observer | inotify integration, cross-platform, event debouncing, recursive watching -- handles edge cases (symlinks, permissions, rapid events) |
| TOML config parsing | Custom tomli + Pydantic wiring | pydantic-settings TomlConfigSettingsSource | Handles type coercion, nested models, priority ordering, env var override -- already built |
| Graceful shutdown signaling | Custom signal handlers + global flags | asyncio.Event + FastAPI lifespan | Clean cancellation semantics, integrates with uvicorn's own SIGTERM handling |
| FTS5 query escaping | Manual string escaping | FTS5 parameterized queries | SQLite handles escaping; manual escaping is error-prone and insecure |

**Key insight:** Every "simple" background indexer eventually needs: shutdown coordination, error recovery, progress tracking, file deduplication, event debouncing, and concurrent read safety. Using FTS5 + watchdog + asyncio.Event eliminates most custom code for these concerns.

## Common Pitfalls

### Pitfall 1: FTS5 Query Syntax Mismatch
**What goes wrong:** User queries containing FTS5 special characters (`*`, `"`, `AND`, `OR`, `NOT`, `NEAR`, parentheses) cause sqlite3.OperationalError.
**Why it happens:** FTS5 MATCH syntax is not plain text -- it's a query language. A query like `"hello world"` is interpreted as a phrase query; `foo AND bar` uses the AND operator.
**How to avoid:** Wrap user queries in double quotes to force phrase matching, or escape special characters. For single-word queries, no escaping needed. For multi-word, either quote the entire query or tokenize and join with spaces (implicit AND).
**Warning signs:** Crash on queries containing parentheses, asterisks, or the word "AND"/"OR"/"NOT".

### Pitfall 2: Watchdog Events in Docker Bind Mounts
**What goes wrong:** inotify does not work across filesystem boundaries. Docker bind mounts (`-v /host:/container`) may not propagate inotify events reliably, especially on overlayfs.
**Why it happens:** inotify watches are kernel-level and tied to the specific filesystem where the watch was created. Bind mounts cross filesystem boundaries.
**How to avoid:** D-03 already addresses this -- polling fallback at 1-hour intervals catches anything inotify misses. The `watchdog` library's `PollingObserver` class can be used as fallback, but the hourly diff approach is simpler and sufficient.
**Warning signs:** New files in bind-mounted directories not detected by inotify.

### Pitfall 3: Blocking the asyncio Event Loop
**What goes wrong:** Per-file processing (read file, chunk, embed via HTTP, extract NER, write to SQLite) is synchronous and can take 1-10 seconds per file. Running this in an async function blocks all API request handling.
**Why it happens:** `asyncio.create_task()` runs on the event loop; if the coroutine calls synchronous code without `await`, it blocks.
**How to avoid:** Wrap the synchronous `_process_one_file()` call in `await asyncio.to_thread(self._process_one_file, file_info)` to run it in a thread pool, keeping the event loop responsive for API requests.
**Warning signs:** API latency spikes during background indexing; health checks timing out.

### Pitfall 4: FTS5 and Existing BM25 Data Migration
**What goes wrong:** After switching to FTS5, the existing `bm25_index.pkl` file is orphaned, and if the FTS5 table is empty, BM25 search returns nothing until a full reindex.
**Why it happens:** FTS5 is a new table; existing chunk data in `metadata.db` needs to be bulk-inserted into `chunks_fts`.
**How to avoid:** On first startup with FTS5, check if `chunks_fts` is empty but `chunks` table has data. If so, run a one-time migration: `INSERT INTO chunks_fts(chunk_id, text) SELECT chunk_id, text FROM chunks`. Log the migration prominently.
**Warning signs:** BM25 search returns empty results after upgrade.

### Pitfall 5: Config.toml Path Resolution in Docker
**What goes wrong:** `~/.dotmd/config.toml` resolves to `/root/.dotmd/config.toml` in Docker, which doesn't exist since config lives on the host.
**Why it happens:** Docker containers have a different filesystem. The config.toml file is on the host at `~/.dotmd/config.toml`.
**How to avoid:** Allow config path override via env var (`DOTMD_CONFIG_PATH`) or make `config.toml` path relative to `index_dir` (which is already a named volume mount). Since `DOTMD_INDEX_DIR=/dotmd-index` in Docker, config.toml would be at `/dotmd-index/config.toml` -- mountable via the existing `dotmd-index` volume. Alternative: bind-mount the config file explicitly.
**Warning signs:** Config.toml settings ignored in Docker; only env vars take effect.

### Pitfall 6: Watchdog Observer Thread Leak
**What goes wrong:** If the Observer is started but not stopped during FastAPI shutdown, the thread keeps running and prevents clean process exit.
**Why it happens:** Observer.start() spawns a daemon thread, but if join() is not called, the thread may hold resources.
**How to avoid:** Stop the Observer in the lifespan cleanup (after yield): `observer.stop(); observer.join()`.
**Warning signs:** Container takes 30+ seconds to shut down; Docker sends SIGKILL after timeout.

### Pitfall 7: Multi-path Discovery Performance
**What goes wrong:** With glob patterns like `/home/j2h4u/**/README.md`, `pathlib.glob()` traverses the entire directory tree including node_modules, .git, etc. before exclude patterns filter results.
**Why it happens:** Python's `pathlib.glob()` does full traversal; exclude filtering happens after discovery.
**How to avoid:** Apply exclude patterns during traversal, not after. Use `os.walk()` with directory pruning (skip excluded dirs entirely) for directory-type paths. For glob patterns, use `wcmatch.glob` which supports exclude patterns natively, or filter early.
**Warning signs:** Startup takes minutes scanning /home with 100k+ files in node_modules trees.

## Code Examples

### FTS5 Search Engine (replaces BM25SearchEngine)
```python
# Implements SearchEngineProtocol -- same interface as current BM25SearchEngine
import re
import sqlite3
import logging

logger = logging.getLogger(__name__)

# Characters that are FTS5 operators and must be escaped
_FTS5_SPECIAL = re.compile(r'["\(\)\*:]')

def _sanitize_fts5_query(query: str) -> str:
    """Escape FTS5 special characters in user query."""
    # Remove special chars, then wrap each word in quotes for safety
    cleaned = _FTS5_SPECIAL.sub(" ", query)
    words = cleaned.split()
    if not words:
        return ""
    # Join with spaces (implicit AND in FTS5)
    return " ".join(f'"{w}"' for w in words if w.strip())


class FTS5SearchEngine:
    """Full-text search engine using SQLite FTS5.

    Uses the same SQLite connection as metadata store (WAL mode).
    Implements SearchEngineProtocol.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                chunk_id UNINDEXED,
                text,
                tokenize = 'unicode61'
            )
        """)
        self._conn.commit()

    def add_chunks(self, chunks: list) -> None:
        """Insert chunks into FTS5 index (incremental)."""
        rows = [(c.chunk_id, c.text) for c in chunks]
        self._conn.executemany(
            "INSERT OR REPLACE INTO chunks_fts(chunk_id, text) VALUES (?, ?)",
            rows,
        )
        self._conn.commit()

    def remove_chunks(self, chunk_ids: list[str]) -> None:
        """Remove chunks from FTS5 index."""
        for cid in chunk_ids:
            self._conn.execute(
                "DELETE FROM chunks_fts WHERE chunk_id = ?", (cid,),
            )
        self._conn.commit()

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        """Search FTS5 index. Returns (chunk_id, score) pairs."""
        sanitized = _sanitize_fts5_query(query)
        if not sanitized:
            return []
        try:
            cur = self._conn.execute(
                "SELECT chunk_id, -rank AS score FROM chunks_fts "
                "WHERE chunks_fts MATCH ? ORDER BY rank LIMIT ?",
                (sanitized, top_k),
            )
            return [(row[0], row[1]) for row in cur.fetchall()]
        except sqlite3.OperationalError as e:
            logger.warning("FTS5 query failed: %s (query: %r)", e, sanitized)
            return []

    def rebuild_from_metadata(self, conn: sqlite3.Connection) -> None:
        """One-time migration: populate FTS5 from existing chunks table."""
        self._conn.execute("DELETE FROM chunks_fts")
        self._conn.execute(
            "INSERT INTO chunks_fts(chunk_id, text) "
            "SELECT chunk_id, text FROM chunks"
        )
        self._conn.commit()
```

### Multi-path File Discovery
```python
# Source: D-08, D-09 decisions
from pathlib import Path
from fnmatch import fnmatch

def discover_files_multi(
    paths: list[str],
    exclude: list[str],
) -> list[FileInfo]:
    """Discover .md files from multiple paths with exclude filtering."""
    results: list[FileInfo] = []
    seen: set[Path] = set()

    for path_spec in paths:
        if "*" in path_spec or "?" in path_spec:
            # Glob pattern: e.g., "/home/j2h4u/**/README.md"
            root = Path(path_spec.split("*")[0].rstrip("/"))
            pattern = path_spec[len(str(root)):].lstrip("/")
            for p in root.glob(pattern):
                if p.is_file() and _not_excluded(p, exclude) and p not in seen:
                    seen.add(p)
                    results.append(_file_info(p))
        else:
            # Directory: recursive .md scan
            directory = Path(path_spec)
            if directory.is_dir():
                for p in directory.rglob("*.md"):
                    if p.is_file() and _not_excluded(p, exclude) and p not in seen:
                        seen.add(p)
                        results.append(_file_info(p))

    return sorted(results, key=lambda fi: str(fi.path))

def _not_excluded(path: Path, exclude: list[str]) -> bool:
    """Check if path matches any exclude pattern."""
    path_str = str(path)
    for pattern in exclude:
        if fnmatch(path_str, pattern):
            return False
        # Also check each path component
        for part in path.parts:
            if fnmatch(part, pattern.replace("**/", "")):
                return False
    return True
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| rank_bm25 + pickle (full rebuild) | SQLite FTS5 (incremental) | SQLite 3.9.0 (2015) onwards | Eliminates O(N) rebuild per file; incremental INSERT; WAL-safe concurrent reads |
| Flat env vars for config | pydantic-settings TOML source | pydantic-settings 2.0 (2023) | Structured config (lists, nested objects) without env var gymnastics |
| Manual inotify bindings | watchdog 6.0 | 2024-11 | Higher-level API, PatternMatchingEventHandler, cross-platform |
| startup/shutdown events | FastAPI lifespan (asynccontextmanager) | FastAPI 0.93 (2023) | Clean async context for resource lifecycle; replaces deprecated on_event |

**Deprecated/outdated:**
- `rank_bm25` library: Last release 2023, limited maintenance. FTS5 is strictly superior for this use case.
- FastAPI `@app.on_event("startup"/"shutdown")`: Deprecated in favor of lifespan context manager.
- `bm25_index.pkl` file: Will be orphaned after FTS5 migration. Can be safely deleted.

## Open Questions

1. **numpy dependency after rank_bm25 removal**
   - What we know: rank_bm25 is the primary consumer of numpy in the BM25 scoring path.
   - What's unclear: Whether other parts of the codebase (embeddings, reranker) import numpy directly.
   - Recommendation: Grep for numpy imports before removing from dependencies. If only rank_bm25 uses it, remove.

2. **Config.toml location in Docker**
   - What we know: `index_dir` is `/dotmd-index` (named volume) in Docker. Host config at `~/.dotmd/config.toml` is not accessible.
   - What's unclear: Best way to expose config.toml to the container.
   - Recommendation: Default to `{index_dir}/config.toml`. In Docker, this becomes `/dotmd-index/config.toml` which lives in the named volume. Users can create/edit it via `docker exec` or bind-mount. Add `DOTMD_CONFIG_PATH` env var for explicit override.

3. **Watchdog paths inside Docker vs host paths**
   - What we know: Production mounts `/srv/knowledgebase/voicenotes` as `/mnt/voicenotes:ro` and `/home/j2h4u` as `/mnt/home:ro`. Config.toml `paths` must use container paths (`/mnt/voicenotes`, `/mnt/home`), not host paths.
   - What's unclear: Whether inotify works on read-only bind mounts (it watches for kernel notifications, not writes).
   - Recommendation: inotify should work for detecting changes made on the host that propagate through the bind mount. The `:ro` flag prevents the container from writing but does not prevent inotify from seeing host-side changes. Verify empirically; polling fallback covers the gap.

4. **FTS5 vs existing tokenize() function behavior parity**
   - What we know: Current BM25 uses `utils/text.py:tokenize()` which does stop-word removal and lowercasing. FTS5 `unicode61` does lowercasing and Unicode normalization but NO stop-word removal.
   - What's unclear: Whether the stop-word difference materially affects search quality.
   - Recommendation: Accept the difference. FTS5's BM25 scoring naturally downweights common words via IDF. Stop-word removal in the old tokenizer was a rough approximation of what BM25 IDF already does. If quality issues arise, add a custom FTS5 tokenizer later (deferred to search quality phase).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| SQLite FTS5 | BM25 replacement | Yes | 3.46.1 (bundled) | -- |
| unicode61 tokenizer | FTS5 Cyrillic support | Yes | verified via test | -- |
| Python 3.12+ | Project requirement | Yes | 3.13.5 (host), 3.12-slim (Docker) | -- |
| watchdog | Filesystem watching | No (not yet installed) | 6.0.0 available on PyPI | pip install in Docker build |
| pydantic-settings[toml] | TOML config loading | Partial (pydantic-settings installed, toml extra not) | 2.13.1 available | pip install extra in Docker build |
| Docker | Runtime environment | Yes | available on host | -- |
| TEI (external) | Embedding generation | Yes | deployed at embeddings:80 | -- |
| FalkorDB (external) | Graph store | Yes | deployed at falkordb:6379 | -- |

**Missing dependencies with no fallback:** None -- all are installable via pip.

**Missing dependencies with fallback:**
- watchdog and pydantic-settings[toml] are pip-installable; added to pyproject.toml, built into Docker image.

## Project Constraints (from CLAUDE.md)

- **Protocol-based abstractions:** FTS5SearchEngine must implement `SearchEngineProtocol` (same `search(query, top_k)` interface).
- **UI-agnostic API:** All trickle indexer state must be accessible via `DotMDService`, not directly from the background task.
- **Never reload indexes per-request:** FTS5 queries use the long-lived SQLite connection, not a per-request load. This is naturally satisfied.
- **All public APIs through api/service.py:** Trickle progress goes through `DotMDService.status()`, not a separate endpoint.
- **Module-level loggers:** `logger = logging.getLogger(__name__)` in every new file.
- **NumPy-style docstrings:** All public methods must have Parameters/Returns sections.
- **from __future__ import annotations:** Required at top of every new file.
- **Containers first (AGENTS.md):** dotMD always runs in Docker. Development and testing happen in-container.
- **Hatch build system:** pyproject.toml uses hatchling.

## Sources

### Primary (HIGH confidence)
- SQLite FTS5 official docs (https://www.sqlite.org/fts5.html) -- CREATE, INSERT, DELETE, MATCH, rank, unicode61 tokenizer, contentless vs standalone tables
- FastAPI lifespan docs (https://fastapi.tiangolo.com/advanced/events/) -- asynccontextmanager pattern, startup/shutdown lifecycle
- pydantic-settings docs (https://docs.pydantic.dev/latest/concepts/pydantic_settings/) -- TomlConfigSettingsSource, settings_customise_sources, priority ordering
- Verified: SQLite 3.46.1 FTS5 + unicode61 available on Python 3.13.5 via direct test

### Secondary (MEDIUM confidence)
- watchdog PyPI (https://pypi.org/project/watchdog/) -- v6.0.0, PatternMatchingEventHandler API, Observer threading model
- watchdog GitHub (https://github.com/gorakhargosh/watchdog) -- inotify backend, Docker bind mount limitations
- pydantic-settings PyPI -- v2.13.1 current, toml extra requires tomli
- Multiple sources on asyncio graceful shutdown patterns (asyncio.Event + loop.add_signal_handler)

### Tertiary (LOW confidence)
- inotify behavior on Docker bind mounts with `:ro` flag -- needs empirical verification in production setup

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries verified via docs and local testing; FTS5 tested on target Python/SQLite
- Architecture: HIGH -- patterns follow established FastAPI/asyncio conventions; FTS5 table design verified against official docs
- Pitfalls: HIGH -- based on known issues documented in official sources and production deployment context

**Research date:** 2026-03-28
**Valid until:** 2026-04-28 (stable technologies, 30-day validity)
