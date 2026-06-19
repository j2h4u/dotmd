---
phase: 46-surrealdb-write-path-and-trickle-cutover
plan: 01
status: in_progress
last_updated: 2026-06-19
---

# Phase 46 Plan 01 Summary

## What is done

Phase 46 now has the core idempotent SurrealDB delta-apply machinery plus
focused direct-write and service-level visibility smokes on the Surreal sink:

- delta manifest contract for changed old-stack rows only;
- deterministic sync runner with resume state and progress/ETA snapshots;
- row-builder that filters transformed old-stack rows down to changed document refs;
- `SurrealDeltaStoreWriter` that uses point upserts and exact deletes only;
- writer-side table alias normalization for old-stack table names;
- stable record-id selection aligned with the bootstrap migration IDs;
- tombstone deletion by stable IDs from `previous_row`;
- fake-connection unit tests and real temporary `surrealkv://` smoke tests;
- changed-file delta smoke from an old-stack SQLite fixture through
  `load_sqlite_rows_for_surreal()` and `build_surreal_delta_manifest_from_rows()`;
- schema-derived payload pruning in the writer, so old-stack row shapes do not
  need test-side field stripping before Surreal upsert;
- `vector_components` are accepted by the writer rather than excluded.
- temporary-markdown direct-write smoke to SurrealKV through
  `IndexingPipeline(search_backend='surreal')`, proving the direct pipeline ->
  Surreal writer path without Falkor dependency and with native relation
  inserts.
- direct Surreal write -> Surreal FTS visibility smoke through
  `SurrealFTSSearchEngine`.
- direct Surreal write -> `DotMDService.search(... mode=SearchMode.KEYWORD,
  rerank=False, expand=False)` visibility smoke against a temporary SurrealKV
  DB.
- safe local temporary `surrealkv://` public-entrypoint smokes for API, CLI,
  and MCP direct-written visibility are done.
- orchestrator validation also passed with focused devtools and shadow-run
  checks:
  - `67 passed in 1.08s` for the devtools runner gate
  - phase 43 shadow bundle verify-only passed with explicit required args
  - artifact summary still reports `passed=true`, `regression=0`, and no
    unresolved blockers or unclear items
- live read-only state remains on the old stack, with `dotmd` healthy,
  `surrealdb/surrealdb:v3.1.4` running, and `dotmd status --verbose` reporting
  1098 files, 149880 chunks, 233348 entities, 592448 edges, graph=`falkordb`
  and `/health` returning `ok`.
- keyword smoke still finds the same SurrealDB document in both the old-stack
  live child and the Surreal child-process override path without requiring a
  container restart.
- the hybrid old-stack smoke path is still too slow for rerank-on production
  use: semantic/graph smoke took about 100s, TEI one-query encode logged
  `93.7s`, and Falkor graph enrichment timed out before results returned.
  Phase 46 therefore proceeds with rerank off / no-rerank cutover smoke, while
  rerank-on optimization remains follow-up work rather than a blocker.
- commit `fb15e14` fixes the Surreal FTS adapter shape: the first one-query
  attempt (`c22f6de`) collapsed title/text predicates into one `OR` query and
  timed out live against standalone SurrealDB, so the final adapter uses one
  `query_raw()` HTTP roundtrip containing two independent indexed SELECTs and
  fuses the title/text scores in Python.
- commit `a098ae9` fixes graph enrichment query shape by de-duplicating and
  capping seed chunk IDs and using one batched Falkor query when available
  instead of issuing an unbounded per-seed loop.
- live Surreal child-process keyword smoke after `fb15e14` passed in `2.139s`
  against database `phase43_refresh_20260618g` and returned the expected
  SurrealDB document without requiring a production container restart.
- normal cutover smoke stays local-only by default; federated search is an
  explicit opt-in via `include_federated`, `--federated`, the API `federated`
  query param, and the MCP `federated` argument.
- Gmail federated search still logs OAuth 400 in both old-stack and Surreal
  child-process search; treat that as a separate federated-source issue, not a
  SurrealDB cutover blocker unless Gmail is made part of the acceptance scope.
- commit `06e8179` guards manual reindex paths in Surreal mode:
  `IndexingPipeline.reindex_vectors()`, `reindex_fts5()`, and
  `DotMDService.reindex('all')` now return `0`/skip without mutating the local
  sqlite-vec or FTS5 stores.
- commit `41409a3` now skips local sqlite-vec and FTS5 writes for the normal
  `search_backend='surreal'` ingest and metadata-only refresh path while still
  keeping SQLite source metadata, bindings, fingerprints, and
  `VecComponentStore` in place for metadata-only reuse and change detection.
- commits `c9fa512`, `5542938`, and `231f531` fence legacy purge paths in
  Surreal mode so destructive admin/public methods fail fast, `_purge_file`
  and `purge_orphaned_files` stay tombstone-only, and trickle delete/orphan
  handling uses those safe paths.

## Evidence

Commits:

- `d706e93` `feat(46): define surreal delta manifest`
- `fb534d4` `feat(46): add surreal delta sync runner`
- `172d2ab` `feat(46): build surreal delta manifests from rows`
- `ef09f60` `feat(46): add incremental surreal delta writer`
- `15d4cd0` `fix(46): normalize surreal delta table aliases`
- `f1ca595` `fix(46): resolve surreal tombstones by stable ids`
- `da3be6e` `test(46): smoke incremental surreal delta writer`
- `779c55f` `test(46): verify fresh surreal delta reruns`
- `f775c05` `test(46): smoke changed-file surreal delta`
- `527fda0` `fix(46): sanitize surreal delta payloads by schema`
- `06e8179` `fix(46): guard manual reindex paths in surreal mode`
- `53f6e18` `test(46): add public-entrypoint surreal visibility smokes`
- `c9fa512` `fix(46): fence purge application source in surreal mode`
- `5542938` `fix(46): fence legacy drop paths in surreal mode`
- `231f531` `fix(46): route trickle orphan handling through tombstones`
- `c22f6de` `Collapse Surreal FTS to one query`
- `a098ae9` `Bound Falkor graph enrichment`
- `fb15e14` `Fix Surreal FTS query_raw fusion`

Verification run on 2026-06-19:

```bash
cd backend
UV_LINK_MODE=hardlink uv run pytest tests/ingestion/test_surreal_delta_sync.py tests/ingestion/test_surreal_delta_sync_live.py -q
UV_LINK_MODE=hardlink uv run ruff check src/dotmd/ingestion/surreal_delta_sync.py tests/ingestion/test_surreal_delta_sync.py tests/ingestion/test_surreal_delta_sync_live.py
UV_LINK_MODE=hardlink uv run pytest tests/ingestion/test_application_source_ingestion.py tests/ingestion/test_surreal_direct_sink.py tests/ingestion/test_surreal_delta_sync.py tests/ingestion/test_surreal_delta_sync_live.py tests/ingestion/test_bulk_fusion_pairing.py tests/ingestion/test_metadata_only_reindex.py tests/ingestion/test_pipeline_purge.py tests/ingestion/test_pipeline_orphan_sweep.py -q
UV_LINK_MODE=hardlink uv run pytest tests/ingestion/test_application_source_ingestion.py tests/ingestion/test_surreal_direct_sink.py tests/ingestion/test_surreal_delta_sync.py tests/ingestion/test_surreal_delta_sync_live.py tests/ingestion/test_bulk_fusion_pairing.py tests/ingestion/test_metadata_only_reindex.py tests/ingestion/test_pipeline_purge.py tests/ingestion/test_pipeline_orphan_sweep.py tests/search/test_surreal_direct_visibility.py tests/search/test_surreal_native_fts.py tests/api/test_service_reindex_surreal.py -q
UV_LINK_MODE=hardlink uv run pytest tests/ingestion/test_application_source_ingestion.py tests/ingestion/test_surreal_direct_sink.py tests/ingestion/test_surreal_delta_sync.py tests/ingestion/test_surreal_delta_sync_live.py tests/ingestion/test_bulk_fusion_pairing.py tests/ingestion/test_metadata_only_reindex.py tests/ingestion/test_pipeline_purge.py tests/ingestion/test_pipeline_orphan_sweep.py tests/ingestion/test_pipeline_surreal_guards.py tests/search/test_surreal_direct_visibility.py tests/search/test_surreal_native_fts.py tests/api/test_service_reindex_surreal.py -q
UV_LINK_MODE=hardlink uv run ruff check src/dotmd/ingestion/pipeline.py src/dotmd/api/service.py tests/ingestion/test_metadata_only_reindex.py tests/api/test_service_reindex_surreal.py tests/search/test_surreal_direct_visibility.py tests/search/test_surreal_native_fts.py
UV_LINK_MODE=hardlink uv run pytest tests/ingestion/test_application_source_ingestion.py tests/ingestion/test_surreal_direct_sink.py tests/ingestion/test_surreal_delta_sync.py tests/ingestion/test_surreal_delta_sync_live.py tests/ingestion/test_bulk_fusion_pairing.py tests/ingestion/test_metadata_only_reindex.py tests/ingestion/test_pipeline_purge.py tests/ingestion/test_pipeline_orphan_sweep.py tests/ingestion/test_pipeline_surreal_guards.py tests/search/test_surreal_fts.py tests/search/test_surreal_native_fts.py tests/search/test_surreal_direct_visibility.py tests/search/test_surreal_retrieval_parity.py tests/search/test_surreal_native_vector.py tests/search/test_surreal_native_graph.py tests/test_graph_search.py tests/storage/test_falkordb_graph.py tests/api/test_service_reindex_surreal.py -q
UV_LINK_MODE=hardlink uv run ruff check src/dotmd/search/surreal_fts.py src/dotmd/search/graph_search.py src/dotmd/storage/falkordb_graph.py tests/search/test_surreal_fts.py tests/search/test_surreal_native_fts.py tests/search/test_surreal_direct_visibility.py tests/search/test_surreal_retrieval_parity.py tests/test_graph_search.py tests/storage/test_falkordb_graph.py
```

Result:

- Earlier delta-sync smoke: `21 passed`, `74 passed in 1.99s`, `All checks passed!`
- Orchestrator validation: `85 passed in 2.30s`, `All checks passed!`
- Expanded orchestrator validation: `94 passed, 1 warning in 3.28s`.
- Surreal FTS + graph enrichment regression gate:
  `141 passed, 1 warning in 3.73s`.
- Ruff over changed code/tests: `All checks passed!`

The live smoke used real temporary `surrealkv://` storage, applied the dotMD
schema, seeded bootstrap-style records, applied a delta, reran with the same
state for resume-skip coverage, and reran with fresh state to prove no duplicate
record IDs or unrelated-row damage.

The changed-file smoke used the existing synthetic old-stack SQLite fixture,
loaded rows with `load_sqlite_rows_for_surreal()`, built a one-document delta,
applied it to temporary SurrealKV, and proved unrelated old-stack rows were not
applied by that delta.

The direct-write smoke used a temporary markdown file plus mocked embeddings,
wrote successfully through `IndexingPipeline(search_backend='surreal')` into
temporary SurrealKV, and observed counts of documents=1, chunks=1,
bindings=1, embeddings=1, files=1, sections=1, tags=1, relations=2. That
confirms the direct pipeline -> Surreal writer path, native relation inserts,
and deterministic int `vector_rowid`.

Commit `41409a3` narrows the normal Surreal ingest path further by quarantining
local sqlite-vec and FTS5 writes there, but it intentionally leaves the local
SQLite metadata/source lifecycle, bindings, fingerprints, and
`VecComponentStore` cache in place.

Commit `06e8179` closes the remaining manual-reindex gap in Surreal mode by
making the legacy reindex entry points return no-op/skip instead of mutating
sqlite-vec or FTS5.

Commits `c9fa512`, `5542938`, and `231f531` fence legacy purge and orphan
handling in Surreal mode so direct writes keep flowing through tombstone-safe
paths without mutating local legacy stores.

## Direction Change

The product decision is direct cutover to SurrealDB, not a bounded hybrid
runtime. The delta-sync work above remains useful as migration/retry safety and
as proof that Surreal writes are idempotent, schema-aware, and stable by record
ID. It is not the target steady-state architecture.

## Not done yet

Phase 46 is not complete. Remaining work:

- prove Surreal-backed search sees changed direct-written results through the
  production/live API/CLI/MCP smoke path at cutover scope;
- update production cutover criteria with the write-path evidence;
- remove or quarantine any remaining old-stack write dependencies outside the
  normal Surreal ingest path, or mark them explicitly non-authoritative, before
  production cutover;
- decide the production deploy/runbook for the Surreal-backed write path.

## Current Decision

Proceed with direct SurrealDB write path. Do not build a long-lived hybrid
old-stack-to-Surreal sync layer.
