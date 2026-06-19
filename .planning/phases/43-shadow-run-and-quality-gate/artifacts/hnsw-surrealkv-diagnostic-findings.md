# SurrealKV HNSW Diagnostic Findings

Date: 2026-06-17

## Summary

Embedded SurrealDB `surrealdb==2.0.0` / SurrealKV can build HNSW indexes on
small and medium `F32` vector tables, but fails at 100k rows x 1024 dimensions
with:

```text
The query was not executed due to a failed transaction. There was a problem with
a datastore transaction: Log error: Record is too large to fit in a segment.
Increase max segment size
```

The failure reproduces with synthetic vectors, so it is not caused by private
dotMD embeddings or malformed source data.

## Passing Cases

- synthetic 10k x 1024, `TYPE F32`, `M 12`, `EFC 32`: passed
- synthetic 50k x 1024, `TYPE F32`, `M 12`, `EFC 32`: passed
- actual source embeddings 25k x 1024, `TYPE F32`, `M 12`, `EFC 32`: passed
- actual source embeddings 50k x 1024, `TYPE F32`, `M 12`, `EFC 32`: passed

## Failing Cases

- actual source embeddings 100k x 1024, `TYPE F32`, `M 4`, `EFC 32`: failed
  after `682.069s` in `DEFINE INDEX`.
- synthetic embeddings 100k x 1024, `TYPE F32`, `M 4`, `EFC 32`: failed
  after `445.406s` in `DEFINE INDEX`.

Failing DDL:

```sql
DEFINE INDEX embeddings_hnsw_idx ON TABLE embeddings COLUMNS embedding
HNSW DIMENSION 1024 TYPE F32 DIST COSINE M 4 EFC 32;
```

## Storage Observations

- Synthetic 100k pre/post failure target size stayed at `1256156763` bytes.
- Largest SurrealKV clog file was `527604174` bytes.
- No target file growth occurred during the opaque `DEFINE INDEX` period before
  the transaction failed.

## Interpretation

The current evidence points to the HNSW index build producing a single internal
transaction/log record that exceeds SurrealKV's per-segment record limit at this
scale. It is not explained by individual embedding records, because inserts and
HNSW builds pass at 50k rows and the 100k failure reproduces with synthetic
vectors.

## Upstream Report Candidate

Use `backend/devtools/surreal_hnsw_diagnostics.py` to reproduce without dotMD
data:

```bash
cd backend
uv run python devtools/surreal_hnsw_diagnostics.py \
  --output-dir ../.planning/phases/43-shadow-run-and-quality-gate/artifacts/hnsw-diagnostics-synthetic-100k-m4 \
  --counts 100000 \
  --dimensions 1024 \
  --source-kind synthetic \
  --m-values 4 \
  --efc-values 32 \
  --segment-sizes default \
  --insert-batch-size 1000 \
  --heartbeat-seconds 30 \
  --timeout-seconds 1800 \
  --stop-on-failure
```

## Project Remediation

The practical embedded-SurrealKV path is sharded HNSW:

- Copy `149796` valid embeddings into three shard tables:
  `embeddings_0=49971`, `embeddings_1=49941`, `embeddings_2=49884`.
- Build one HNSW index per shard:
  `embeddings_0_hnsw_idx`, `embeddings_1_hnsw_idx`, `embeddings_2_hnsw_idx`.
- Query all shard tables and merge top-k by score.

Evidence:

- `artifacts/embedding-shard-copy-3/embedding-shard-results.json`
  -> `status=verified`, `copied_rows=149796`.
- `artifacts/index-build-hnsw-sharded-3-m4-efc32/index-build-results.json`
  -> `status=verified`, `present_indexes=3/3`.

