# Phase 3: CLI & API Polish - Research

**Researched:** 2026-03-23
**Domain:** CLI output formatting, Pydantic model extension, FastAPI response enrichment
**Confidence:** HIGH

## Summary

Phase 3 is a thin integration layer. All the hard work (incremental pipeline, file tracking, diff computation) was completed in Phases 1 and 2. The remaining work is threading diff counts from `FileDiff` through `IndexStats`, formatting CLI output, and adding change detection to `dotmd status`.

CA-01 and CA-02 are already implemented: `dotmd index` defaults to incremental, and `--force` triggers full re-index. The remaining requirement is CA-03 (progress reporting), plus status command enhancements and API response enrichment per the CONTEXT.md decisions.

**Primary recommendation:** Extend `IndexStats` with four integer diff fields, populate them in `_ingest_and_finalize` and `_incremental_index`, then format in CLI and return via API. No new libraries, no schema migrations, no new endpoints.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** After `dotmd index`, show one-line diff summary: "3 new, 1 modified, 0 deleted, 222 unchanged" -- matches the requirement verbatim
- **D-02:** Keep existing totals line after the diff summary (files, chunks, entities, edges) for full picture
- **D-03:** In verbose mode (`-v`), list individual changed file paths before the summary
- **D-04:** Extend `IndexStats` with diff fields: `new_files`, `modified_files`, `deleted_files`, `unchanged_files` (all `int`, default 0)
- **D-05:** Pipeline passes diff counts into IndexStats before returning, so CLI and API both get the data
- **D-06:** `dotmd status` keeps current output (files, chunks, entities, edges, last_indexed) -- already covers "last index time, file count"
- **D-07:** Add change detection: run `FileTracker.diff()` against current directory and show pending changes ("2 new, 1 modified since last index") -- this is what "change detection" in the roadmap means
- **D-08:** `POST /index` returns IndexStats as JSON (including diff fields) -- standard REST response
- **D-09:** No new endpoints needed -- existing `/index` just returns richer payload

### Claude's Discretion
- Exact formatting of CLI output (alignment, colors, separators)
- Status command dry-run implementation detail (how to discover data_dir without re-indexing)
- Error messages and edge cases (no index exists, empty directory, etc.)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CA-01 | `dotmd index` uses incremental by default | Already implemented in Phase 2 -- `force=False` default in pipeline.index() and service.index() |
| CA-02 | `dotmd index --force` does full re-index | Already implemented in Phase 2 -- `--force` CLI flag threads through service to pipeline |
| CA-03 | Progress reporting: "3 new, 1 modified, 0 deleted, 222 unchanged" | Requires: extend IndexStats model (D-04), populate diff counts in pipeline (D-05), format in CLI (D-01/D-02/D-03), return via API (D-08) |
</phase_requirements>

## Standard Stack

No new libraries needed. This phase uses only existing project dependencies.

### Core (already installed)
| Library | Purpose | Relevant to Phase 3 |
|---------|---------|---------------------|
| Click | CLI framework | Output formatting in `cli.py` |
| Pydantic v2 | Data models | `IndexStats` field extension |
| FastAPI | REST API | Response model already uses `IndexStats` |
| SQLite3 (stdlib) | Metadata storage | Stats table schema (may need column additions) |

### No New Dependencies
This phase is purely about data flow and formatting. Zero `pip install` needed.

## Architecture Patterns

### Data Flow: Diff Counts Through the Stack

```
FileTracker.diff()  -->  FileDiff(new=[], modified=[], deleted=[], unchanged=[])
        |
        v
IndexingPipeline.index()  -->  counts len() of each list
        |
        v
IndexStats(new_files=3, modified_files=1, ...)  -->  returned to caller
        |
        +----> CLI: click.echo("3 new, 1 modified, 0 deleted, 222 unchanged")
        +----> API: JSON response body (Pydantic serialization, automatic)
        +----> MCP: already returns stats dict (will get new fields for free)
```

### Where Diff Counts Are Already Available

The `IndexingPipeline.index()` method (line 137-148 in pipeline.py) already computes the diff:

```python
diff = self._file_tracker.diff(files)
logger.info(
    "File diff: %d new, %d modified, %d deleted, %d unchanged",
    len(diff.new), len(diff.modified), len(diff.deleted), len(diff.unchanged),
)
```

The counts exist but are logged and discarded. They need to be threaded into `IndexStats`.

### Two Code Paths to Handle

1. **Incremental path** (`_incremental_index`): diff is computed, counts are known
2. **Full re-index path** (`_full_index`): all files are "new", counts are: new=len(files), modified=0, deleted=0, unchanged=0
3. **No-changes short-circuit** (line 143-146): when `not diff.new and not diff.modified and not diff.deleted`, returns early with stored stats. Diff counts here are: new=0, modified=0, deleted=0, unchanged=len(diff.unchanged)

### Status Command: Change Detection (D-07)

The `dotmd status` command needs to run `FileTracker.diff()` to show pending changes. Challenge: it needs to know which directory to scan.

**The data_dir problem:** Currently, `data_dir` is not persisted after indexing. The stats table stores counts but not the source directory path. The service `status()` method doesn't know which directory was indexed.

**Recommended approach:** Store `data_dir` in the stats table (add a column). When `dotmd status` is called:
1. Read `data_dir` from stored stats
2. If exists and is a valid directory, run `FileTracker.diff()` against it
3. Show pending changes: "2 new, 1 modified since last index"
4. If `data_dir` not stored (old index), skip change detection gracefully

**Alternative (simpler):** Accept an optional directory argument in `dotmd status [DIRECTORY]`. If provided, run diff against it. If not, show stats without change detection. This avoids schema changes but requires the user to remember the directory.

**Recommendation:** Store `data_dir` in stats. It is one column addition and makes the tool self-contained. The status command should work without arguments for daily cron use.

### Verbose Mode (D-03)

The CLI already has `--verbose` / `-v` as a group-level option stored in `ctx.obj["verbose"]`. The `index` command needs `@click.pass_context` to access it, then list changed paths before the summary.

Current `index` command signature does NOT use `@click.pass_context`. It needs to be added.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON serialization of new fields | Custom dict building | Pydantic `model_dump()` / FastAPI auto-serialization | IndexStats is already a Pydantic model; adding fields makes them appear in API responses automatically |
| Schema migration | Manual ALTER TABLE | Add columns with defaults + handle missing columns | SQLite ALTER TABLE ADD COLUMN is safe; old rows get defaults |
| CLI output alignment | printf-style formatting | Simple f-strings with consistent format | Keep it simple -- this is a personal tool, not a TUI |

## Common Pitfalls

### Pitfall 1: Stats Table Schema Drift
**What goes wrong:** Adding `new_files`, `modified_files`, `deleted_files`, `unchanged_files`, `data_dir` columns to the `stats` table breaks existing indexes (old schema lacks these columns).
**Why it happens:** SQLite does not auto-add columns. `get_stats()` SELECT query will fail if it references columns that don't exist.
**How to avoid:** Use `ALTER TABLE stats ADD COLUMN ... DEFAULT 0` in the store's `__init__`. SQLite supports this safely. OR keep the SELECT query column-list in sync and handle `None` for old rows.
**Warning signs:** `OperationalError: no such column` after upgrading code against an existing index.

### Pitfall 2: Force Mode Diff Counts
**What goes wrong:** `_full_index` doesn't compute a `FileDiff` -- it goes straight to `_ingest_and_finalize`. If diff fields on `IndexStats` aren't set, they default to 0, which is misleading (suggests nothing happened).
**Why it happens:** Force mode clears everything and re-ingests all files -- there's no "diff" in the traditional sense.
**How to avoid:** In `_full_index`, explicitly set `new_files=len(files)` on the returned stats. All files are effectively "new" after a full clear.

### Pitfall 3: No-Changes Short Circuit Returns Stale Stats
**What goes wrong:** When no changes are detected, `pipeline.index()` returns `self._metadata_store.get_stats()` (stored stats from last run). These stored stats may have stale diff counts from the previous run.
**Why it happens:** Diff counts are ephemeral per-run data, but stats are persisted. Returning stored stats means showing old diff counts.
**How to avoid:** When returning early on no-changes, create a new `IndexStats` with the stored totals but zeroed diff counts (or with unchanged=len(diff.unchanged)). Do NOT return raw stored stats for diff fields.

### Pitfall 4: Status Command data_dir Discovery
**What goes wrong:** `dotmd status` tries to show pending changes but doesn't know which directory was indexed.
**Why it happens:** `data_dir` is passed to `index()` as an argument but never persisted.
**How to avoid:** Persist `data_dir` in the stats table during indexing. Read it back in `status()`. Handle the case where it's `None` (old index or never indexed).

### Pitfall 5: IndexStats Pydantic Serialization of New Fields
**What goes wrong:** New integer fields with `default=0` serialize fine, but `data_dir` (a `Path` or `str | None`) needs care in JSON serialization.
**Why it happens:** Pydantic v2 serializes `Path` as strings by default, which is fine. But `None` values for optional fields need explicit handling in the stats table read/write.
**How to avoid:** Use `str | None = None` for `data_dir` in `IndexStats`. In `save_stats`, write it. In `get_stats`, read it (or `None` if column missing).

### Pitfall 6: API IndexRequest Missing force Parameter
**What goes wrong:** `POST /index` in `server.py` creates a new `DotMDService` per request and calls `service.index(Path(req.directory))` without passing `force`. The `--force` flag from CLI works, but API callers cannot request a full re-index.
**Why it happens:** `IndexRequest` model doesn't have a `force` field.
**How to avoid:** Add `force: bool = False` to `IndexRequest` and pass it through to `service.index()`. This is adjacent to CA-02 scope and should be addressed.

## Code Examples

### Extending IndexStats (D-04)

```python
# core/models.py
class IndexStats(BaseModel):
    """Summary statistics about the current index."""
    total_files: int = 0
    total_chunks: int = 0
    total_entities: int = 0
    total_edges: int = 0
    last_indexed: datetime | None = None
    # Diff counts from last index run (CA-03)
    new_files: int = 0
    modified_files: int = 0
    deleted_files: int = 0
    unchanged_files: int = 0
    # Source directory for change detection (D-07)
    data_dir: str | None = None
```

### Populating Diff Counts in Pipeline (D-05)

In `_ingest_and_finalize`, the stats construction (line 274-280) gains diff fields:

```python
stats = IndexStats(
    total_files=len(all_files),
    total_chunks=len(all_chunks),
    total_entities=all_entities_count,
    total_edges=all_edges_count,
    last_indexed=datetime.now(tz=timezone.utc),
    new_files=diff_counts.get("new", 0),
    modified_files=diff_counts.get("modified", 0),
    deleted_files=diff_counts.get("deleted", 0),
    unchanged_files=diff_counts.get("unchanged", 0),
    data_dir=str(directory),
)
```

The diff counts need to be threaded from `index()` through to `_ingest_and_finalize`. Options:
- Pass `FileDiff` (or a counts dict) as parameter to `_ingest_and_finalize`
- Simpler: pass individual counts as kwargs

### CLI Output (D-01, D-02, D-03)

```python
# cli.py index command
stats = service.index(directory, force=force)
# D-01: diff summary
click.echo(
    f"{stats.new_files} new, {stats.modified_files} modified, "
    f"{stats.deleted_files} deleted, {stats.unchanged_files} unchanged"
)
# D-02: existing totals line (kept)
click.echo(
    f"Done. {stats.total_files} files, {stats.total_chunks} chunks, "
    f"{stats.total_entities} entities, {stats.total_edges} edges."
)
```

### Verbose File Listing (D-03)

```python
# Requires @click.pass_context on the index command
@main.command()
@click.pass_context
def index(ctx, directory, extract_depth, entity_types, force):
    verbose = ctx.obj.get("verbose", False)
    # ... service.index() ...
    # In verbose mode, we need the actual file paths from the diff.
    # Problem: IndexStats only has counts, not paths.
    # Solution: return paths via a separate mechanism or log them.
```

**Verbose detail:** For D-03, the CLI needs actual file paths, not just counts. Two approaches:
1. **Add path lists to IndexStats** -- wasteful for API (large payloads), complicates serialization
2. **Log paths at INFO level, let verbose mode show them** -- the pipeline already logs individual purge/ingest operations. With `setup_logging(verbose=True)`, these logs already appear. This may be sufficient.

**Recommendation:** Use approach 2 (logging). The pipeline already logs `"Purged deleted file: %s"` and `"Purged modified file: %s"`. For new files, it logs chunk counts. With `-v` these appear naturally. If explicit path listing is desired beyond logging, add a lightweight callback or collect paths in the service layer.

### Status with Change Detection (D-07)

```python
# service.py
def status(self) -> IndexStats | None:
    stats = self._pipeline.metadata_store.get_stats()
    if stats is None:
        return None
    # Change detection: if data_dir is known, run diff
    if stats.data_dir:
        data_path = Path(stats.data_dir)
        if data_path.is_dir():
            from dotmd.ingestion.reader import discover_files
            files = discover_files(data_path)
            diff = self._pipeline.file_tracker.diff(files)
            stats.new_files = len(diff.new)
            stats.modified_files = len(diff.modified)
            stats.deleted_files = len(diff.deleted)
            stats.unchanged_files = len(diff.unchanged)
    return stats
```

**Note:** This mutates the stats object returned from the store. Since `IndexStats` is a Pydantic model and we're creating a fresh instance from DB, this is safe.

### Stats Table Schema Update

```sql
-- Add columns with safe defaults (run in SQLiteMetadataStore.__init__)
ALTER TABLE stats ADD COLUMN new_files INTEGER NOT NULL DEFAULT 0;
ALTER TABLE stats ADD COLUMN modified_files INTEGER NOT NULL DEFAULT 0;
ALTER TABLE stats ADD COLUMN deleted_files INTEGER NOT NULL DEFAULT 0;
ALTER TABLE stats ADD COLUMN unchanged_files INTEGER NOT NULL DEFAULT 0;
ALTER TABLE stats ADD COLUMN data_dir TEXT;
```

SQLite `ALTER TABLE ADD COLUMN` is safe for existing tables -- old rows get the default value. Wrap in try/except to handle "duplicate column" errors on subsequent runs.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Diff counts logged and discarded | Thread through IndexStats | This phase | CLI and API consumers get diff data |
| Status shows static counts only | Status runs live diff | This phase | Users see pending changes before indexing |

## Open Questions

1. **Verbose mode file listing depth**
   - What we know: Pipeline logs individual file operations at INFO level. `-v` enables these logs.
   - What's unclear: Whether the user wants a structured list (bullet points) separate from log output, or if log output is sufficient.
   - Recommendation: Start with log-based output (`-v` shows INFO logs which include file paths). If insufficient, add explicit path collection later. This is in "Claude's Discretion" per CONTEXT.md.

2. **Stats table schema migration strategy**
   - What we know: SQLite `ALTER TABLE ADD COLUMN` is safe. Pydantic defaults handle missing values.
   - What's unclear: Whether to use try/except per column or a version check.
   - Recommendation: Try/except per `ALTER TABLE` -- simpler, idempotent, no version tracking needed. Each `ALTER TABLE ADD COLUMN` on an existing column raises `OperationalError: duplicate column name` which is safely caught.

3. **API `POST /index` force parameter**
   - What we know: CLI `--force` works. API `IndexRequest` doesn't have `force` field.
   - What's unclear: Whether this is in scope for Phase 3 or a separate concern.
   - Recommendation: Add it -- it's a one-line addition to `IndexRequest` and one parameter pass-through. Consistent with CA-02 intent.

## Project Constraints (from CLAUDE.md)

- All public APIs go through `api/service.py` -- never expose internals directly
- Never reload indexes per-request (BM25, vector, graph loaded once at startup)
- New storage backends implement Protocol from `storage/base.py`
- Click CLI is a thin wrapper over `api/service.py`
- Pydantic v2 for all models
- Python 3.12+
- Protocol-based abstractions, dependency injection

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection of all relevant files:
  - `backend/src/dotmd/core/models.py` -- IndexStats model (lines 91-98)
  - `backend/src/dotmd/ingestion/pipeline.py` -- diff computation (lines 137-148), stats construction (lines 274-283)
  - `backend/src/dotmd/ingestion/file_tracker.py` -- FileDiff dataclass, diff() method
  - `backend/src/dotmd/cli.py` -- current index/status command output
  - `backend/src/dotmd/api/server.py` -- POST /index endpoint, IndexRequest model
  - `backend/src/dotmd/api/service.py` -- DotMDService.index() and .status()
  - `backend/src/dotmd/storage/metadata.py` -- stats table schema, save_stats/get_stats

### Secondary (MEDIUM confidence)
- SQLite ALTER TABLE ADD COLUMN behavior -- well-documented, stable SQLite feature

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new libraries, pure internal refactoring
- Architecture: HIGH -- data flow path is fully understood from code inspection
- Pitfalls: HIGH -- identified from concrete code paths (short-circuit return, force mode, schema drift)

**Research date:** 2026-03-23
**Valid until:** 2026-04-23 (stable -- internal code changes only, no external dependencies)
