# SurrealDB Standalone Cutover

dotMD is moving SurrealDB work from the failed embedded SurrealKV experiment to
a standalone SurrealDB server.

## Host Layout

- Compose: `/opt/docker/surrealdb/docker-compose.yml`
- Data: `/srv/surrealdb/data`
- Docker network: `surrealdb`
- Host URL: `ws://127.0.0.1:8000/rpc`
- Container URL: `ws://surrealdb:8000/rpc`
- Initial dotMD namespace/database: `dotmd` / `phase43`

The standalone server is shared infrastructure. Future services should use their
own namespaces/databases instead of creating service-specific SurrealDB
containers.

## Migration Direction

Start clean from `main`; do not port the embedded SurrealKV target or the
sharded embedding workaround by default.

Initial target:

- standalone SurrealDB `3.1.x`;
- RocksDB storage;
- monolithic `embeddings` table;
- one native vector index;
- instrumentation for every operation that can run longer than 120 seconds.

Only reintroduce sharded embeddings if a standalone monolithic vector index
fails measurable build/search gates.

## Gates Run

### Standalone Smoke

Before porting the migration runner, verify basic standalone connectivity:

```bash
cd backend
set -a
. /opt/docker/surrealdb/.env
set +a
uv run python devtools/surreal_standalone_smoke.py --write-probe
```

The smoke must authenticate, select `dotmd/phase43`, report server version, and
create/read/delete a temporary record.

Observed on this branch:

```text
surreal standalone smoke ok: url=ws://127.0.0.1:8000/rpc ns=dotmd db=phase43 version=surrealdb-3.1.4 write_probe=True elapsed=0.417s
```

### Source SQLite Probe

Current production source dataset:

- chunk strategy: `contextual_512_50`
- embedding model: `intfloat/multilingual-e5-large`
- `chunks`: 149,839
- `vec_meta`: 149,839
- `vec_chunks`: 149,839
- `chunk_source_provenance`: 149,975
- `chunk_file_paths`: 24,357
- vector dimension: 1024

The production WAL is large, so full migration tooling must use SQLite backup
API or an equivalent consistent snapshot path. Small proof exports can read
inside the running `dotmd` container without copying the full DB.

The full migration uses the joined corpus, not raw `vec_meta` count. The live
source has 5 `vec_meta` rows without matching vector payloads, so the migratable
chunk/vector total is 149,834.

### Schema Apply

Schema application is idempotent and instrumented per statement:

```text
surreal standalone schema apply ok: url=ws://127.0.0.1:8000/rpc ns=dotmd db=phase43 dimension=1024 vector_index=none statements=114 elapsed=1.197s
```

JSON-like fields use `TYPE object FLEXIBLE`. Plain `TYPE object` under
`SCHEMAFULL` rejects real metadata such as nested `metadata.date`.

### Migration Proof

A 100-chunk proof export from live SQLite produced 401 records:

- `document`: 1
- `chunk`: 100
- `chunk_file_binding`: 100
- `chunk_source_provenance`: 100
- `embedding`: 100

The proof loader writes deterministic record IDs with `UPSERT` and prints batch
progress, rate, percentage, and ETA.

Observed run:

```text
surreal migration proof ok: records=401 counts={"chunk": 100, "chunk_file_binding": 100, "chunk_source_provenance": 100, "document": 1, "embedding": 100} elapsed=3.883s
```

After switching the loader from one query per record to SurrealQL batch upsert:

```text
surreal migration proof ok: records=401 counts={"chunk": 100, "chunk_file_binding": 100, "chunk_source_provenance": 100, "document": 1, "embedding": 100} elapsed=0.727s
```

Repeating the same proof did not duplicate rows. Target counts stayed:

- `documents`: 1
- `chunks`: 100
- `chunk_file_bindings`: 100
- `chunk_source_provenance`: 100
- `embeddings`: 100

### Full SQLite Runner

`devtools/surreal_sqlite_migration_runner.py` is the direct full-migration path.
It reads SQLite in batches ordered by `vec_meta.rowid`, writes SurrealDB through
batch `UPSERT`, and stores a checkpoint after each successful batch.

Checkpoint fields include:

- `last_vector_rowid`
- `chunks_done`
- `records_done`
- per-record-type `counts`
- `complete`

If the process dies, rerun with the same checkpoint path. Already committed
batches are skipped; a partially failed batch is safe to replay because target
record IDs are deterministic.

Record IDs must use the `SurrealRecordIdCodec` base32 encoding. URL-safe base64
is not safe enough for `type::record(...)`: encoded `-` can truncate parsed
record IDs and cause collisions.

Live full SQLite migration completed with checkpoint resume semantics:

- `documents`: 1,736
- `chunks`: 149,834
- `embeddings`: 149,834
- `chunk_file_bindings`: 24,352
- `chunk_source_provenance`: 149,970

Observed completion:

```text
surreal sqlite migration ok: chunks=149834 records=475726 last_rowid=188336 complete=True counts={"chunk": 149834, "chunk_file_binding": 24352, "chunk_source_provenance": 149970, "document": 1736, "embedding": 149834}
```

### FalkorDB Graph Runner

`devtools/surreal_falkor_migration_runner.py` exports FalkorDB into dedicated
SurrealDB graph tables:

- `graph_nodes`: one record per exported `(primary_label, node_id)`;
- `graph_edges`: one record per exported FalkorDB edge, keyed by export ordinal.

The runner paginates FalkorDB reads with `SKIP`/`LIMIT`. This is required:
unpaginated reads silently cap at 10,000 rows in this environment.

Live source graph counts:

- `File`: 1,099
- `Section`: 23,954
- `Entity`: 29,002
- `Tag`: 279
- `REL` edges: 355,239

Live SurrealDB target counts after base32 ID fix:

- `graph_nodes`: 54,334
- `graph_edges`: 355,239

Observed final graph import:

```text
surreal falkor migration ok: nodes=54334 edges=355239 elapsed=192.050s counts={"graph_edge": 355239, "graph_node": 54334}
```

### HNSW Gate

Native HNSW index creation on the 100 migrated embeddings succeeded:

```text
DEFINE INDEX IF NOT EXISTS embeddings_vector_hnsw ON TABLE embeddings FIELDS vector HNSW DIMENSION 1024 TYPE F32 DIST COSINE EFC 150 M 12;
[115/115] done in 0.296s
```

On the full 149,834-vector corpus, blocking HNSW creation failed once with a
RocksDB transaction-conflict error while building the index. A follow-up
`CONCURRENTLY` HNSW build reached `ready` with `initial=149834`, `pending=0`,
and `updated=0`.

The first live KNN query against the full HNSW index timed out after 40 seconds
while the container was still under high memory pressure after index build.
Treat the 100-row HNSW gate as syntax/runtime proof only. Treat the full-corpus
HNSW build as passed for construction, but not yet passed for query latency.
