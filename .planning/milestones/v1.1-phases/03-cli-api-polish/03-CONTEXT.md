# Phase 3: CLI & API Polish - Context

**Gathered:** 2026-03-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Clean user-facing interface with progress reporting for incremental indexing. CA-01 (`dotmd index` defaults to incremental) and CA-02 (`--force` flag) are already done from Phase 2. Remaining work: diff summary output (CA-03), API response, status command enhancements.

</domain>

<decisions>
## Implementation Decisions

### Progress output (CA-03)
- **D-01:** After `dotmd index`, show one-line diff summary: "3 new, 1 modified, 0 deleted, 222 unchanged" — matches the requirement verbatim
- **D-02:** Keep existing totals line after the diff summary (files, chunks, entities, edges) for full picture
- **D-03:** In verbose mode (`-v`), list individual changed file paths before the summary

### IndexStats model
- **D-04:** Extend `IndexStats` with diff fields: `new_files`, `modified_files`, `deleted_files`, `unchanged_files` (all `int`, default 0)
- **D-05:** Pipeline passes diff counts into IndexStats before returning, so CLI and API both get the data

### Status command
- **D-06:** `dotmd status` keeps current output (files, chunks, entities, edges, last_indexed) — already covers "last index time, file count"
- **D-07:** Add change detection: run `FileTracker.diff()` against current directory and show pending changes ("2 new, 1 modified since last index") — this is what "change detection" in the roadmap means

### API response
- **D-08:** `POST /index` returns IndexStats as JSON (including diff fields) — standard REST response
- **D-09:** No new endpoints needed — existing `/index` just returns richer payload

### Claude's Discretion
- Exact formatting of CLI output (alignment, colors, separators)
- Status command dry-run implementation detail (how to discover data_dir without re-indexing)
- Error messages and edge cases (no index exists, empty directory, etc.)

</decisions>

<canonical_refs>
## Canonical References

No external specs — requirements fully captured in decisions above and in:

### Project requirements
- `.planning/REQUIREMENTS.md` — CA-01, CA-02, CA-03 definitions
- `.planning/ROADMAP.md` §Phase 3 — scope and done-when criteria

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `IndexingPipeline.index()` already has diff data (`diff.new`, `diff.modified`, `diff.deleted`, `diff.unchanged`) — just not returned
- `IndexStats` model exists in `core/models.py` — needs diff fields added
- `FileTracker.diff()` in `storage/file_tracker.py` — can be called from status command for change detection
- `cli.py` index command already prints mode label and totals — extend, not rewrite

### Established Patterns
- CLI uses Click with `@click.pass_context` for verbose flag
- Service facade pattern: CLI → DotMDService → IndexingPipeline
- Pydantic v2 models with `Field(default_factory=...)` and `computed_field`

### Integration Points
- `IndexStats` returned by `pipeline.index()` → `service.index()` → CLI/API
- `FileTracker` owned by pipeline — status command needs access via service
- REST API in `api/server.py` — `/index` endpoint returns IndexStats

</code_context>

<specifics>
## Specific Ideas

No specific requirements — user said "common sense, no special requirements beyond the obvious." Standard CLI tool patterns apply.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 03-cli-api-polish*
*Context gathered: 2026-03-23*
