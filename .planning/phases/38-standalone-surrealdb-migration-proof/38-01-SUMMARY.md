# Phase 38-01 Summary: Standalone Runtime and Smoke Gate

## Completed

- Created clean worktree from `main`:
  `/home/j2h4u/repos/j2h4u/dotmd-standalone-surrealdb`.
- Deployed shared standalone SurrealDB:
  - image `surrealdb/surrealdb:v3.1.4`;
  - compose `/opt/docker/surrealdb/docker-compose.yml`;
  - data `/srv/surrealdb/data`;
  - network `surrealdb`;
  - RocksDB storage.
- Connected live `dotmd` container to the `surrealdb` Docker network.
- Added `devtools/surreal_standalone_smoke.py`.
- Added standalone SurrealDB connection/schema foundation:
  - `storage/surreal.py`;
  - `storage/surreal_schema.py`;
  - schema apply CLI.
- Added SQLite source probe and small subset migration proof tooling:
  - `devtools/surreal_sqlite_source_probe.py`;
  - `devtools/surreal_sqlite_subset_export.py`;
  - `devtools/surreal_standalone_migration_proof.py`.

## Verification

Focused unit test:

```bash
PYTHONPATH=/home/j2h4u/repos/j2h4u/dotmd-standalone-surrealdb/backend:/home/j2h4u/repos/j2h4u/dotmd-standalone-surrealdb/backend/src \
  /home/j2h4u/repos/j2h4u/dotmd/backend/.venv/bin/python \
  -m pytest /home/j2h4u/repos/j2h4u/dotmd-standalone-surrealdb/backend/tests/devtools/test_surreal_standalone_smoke.py -q
```

Result: `3 passed`.

Live smoke:

```bash
surreal standalone smoke ok: url=ws://127.0.0.1:8000/rpc ns=dotmd db=phase43 version=surrealdb-3.1.4 write_probe=True elapsed=0.389s
```

Focused standalone test suite:

```bash
PYTHONPATH=/home/j2h4u/repos/j2h4u/dotmd-standalone-surrealdb/backend:/home/j2h4u/repos/j2h4u/dotmd-standalone-surrealdb/backend/src \
  /home/j2h4u/repos/j2h4u/dotmd/backend/.venv/bin/python \
  -m pytest \
  backend/tests/devtools/test_surreal_standalone_smoke.py \
  backend/tests/devtools/test_surreal_sqlite_source_probe.py \
  backend/tests/devtools/test_surreal_standalone_schema_apply.py \
  backend/tests/devtools/test_surreal_standalone_migration_proof.py \
  backend/tests/storage/test_surreal_standalone_connection.py \
  backend/tests/storage/test_surreal_schema_definition.py \
  -q
```

Result: `19 passed`.

Ruff focused check: `All checks passed`.

Live source probe:

```text
chunks=149839
vec_meta=149839
vec_chunks=149839
chunk_source_provenance=149975
chunk_file_paths=24357
dim=1024
```

Live schema apply:

```text
surreal standalone schema apply ok: url=ws://127.0.0.1:8000/rpc ns=dotmd db=phase43 dimension=1024 vector_index=none statements=114 elapsed=1.197s
```

Live migration proof:

```text
surreal migration proof ok: records=401 counts={"chunk": 100, "chunk_file_binding": 100, "chunk_source_provenance": 100, "document": 1, "embedding": 100} elapsed=3.883s
```

After changing the proof loader to batch SurrealQL `UPSERT`, live proof improved:

```text
surreal migration proof ok: records=401 counts={"chunk": 100, "chunk_file_binding": 100, "chunk_source_provenance": 100, "document": 1, "embedding": 100} elapsed=0.727s
```

Idempotency check:

- repeated the same proof import with `UPSERT`;
- target counts stayed `documents=1`, `chunks=100`, `chunk_file_bindings=100`,
  `chunk_source_provenance=100`, `embeddings=100`.

Native HNSW check:

```text
DEFINE INDEX IF NOT EXISTS embeddings_vector_hnsw ON TABLE embeddings FIELDS vector HNSW DIMENSION 1024 TYPE F32 DIST COSINE EFC 150 M 12;
[115/115] done in 0.296s
```

Full SQLite runner:

- added `devtools/surreal_sqlite_migration_runner.py`;
- reads SQLite by `vec_meta.rowid`;
- writes batch SurrealQL `UPSERT`;
- persists checkpoint after every successful batch;
- supports resume through `last_vector_rowid`;
- prints chunks done, records done, last rowid, batch timing, rate, and ETA.

Record ID fix:

- changed `SurrealRecordIdCodec` from URL-safe base64 to base32 without padding;
- reason: `type::record(...)` can truncate record IDs containing `-`, which caused
  collisions for Cyrillic graph entity names;
- all migrated data written with the old codec must be cleared and rerun.

FalkorDB graph runner:

- added `devtools/surreal_falkor_migration_runner.py`;
- uses paginated `SKIP`/`LIMIT` reads because unpaginated FalkorDB results capped
  at 10,000 rows;
- exports to `graph_nodes` and `graph_edges`, not the narrower
  `entities`/`relations` tables;
- source graph counts: `File=1099`, `Section=23954`, `Entity=29002`,
  `Tag=279`, `REL edges=355239`;
- live target counts after base32 fix: `graph_nodes=54334`,
  `graph_edges=355239`;
- final graph import: `nodes=54334 edges=355239 elapsed=192.050s`.

## Notes

SurrealDB v3 uses `type::record`, not the old `type::thing` helper in write
probe SQL. The smoke gate caught this before any migration code was ported.

`TYPE object` is too strict under `SCHEMAFULL` for real dotMD metadata. JSON-like
fields must use `TYPE object FLEXIBLE`; the 100-chunk migration proof caught this
with nested `metadata.date`.

The live filesystem source has empty `source_unit_refs`, so the 100-chunk proof
does not populate `source_units` or `source_unit_fingerprints`. The schema still
models them for connector/federated sources and idempotent replay.
