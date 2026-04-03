# Indexing Pipeline Profiling Data — 2026-04-02/03

## Hardware
- CPU: Xeon E3 V2 (8 threads, AVX but NO AVX2)
- RAM: 16GB
- Containers: dotmd-api (pipeline + GLiNER) + embeddings (TEI, intfloat/multilingual-e5-large)

## Baseline Run (pre-optimization)

**Config:** per-chunk `predict_entities()`, default PyTorch threading, default max_len
**Period:** 19:53–01:49 UTC, 2026-04-02/03 (175 files)

### Per-file timings
Note: file paths unavailable in baseline (logged as "transcript.md" only). Identified by chunk count.

| # | Chunks | Total(s) | sec/chunk |
|---|--------|----------|-----------|
| 1 | 53 | 382.3 | 7.21 |
| 2 | 29 | 123.7 | 4.26 |
| 3 | 44 | 309.0 | 7.02 |
| 4 | 29 | 121.4 | 4.19 |
| 5 | 20 | 84.4 | 4.22 |
| 6 | 54 | 225.1 | 4.17 |
| 7 | 92 | 476.4 | 5.18 |
| 8 | 63 | 354.6 | 5.63 |
| 9 | 48 | 293.5 | 6.11 |
| 10 | 49 | 295.3 | 6.03 |
| **AVG** | | | **5.61** |

### Detailed phase breakdown (4 files with full extraction+embed data)

| File | Chunks | Extraction(s) | Embed(s) | Other(s) | Total(s) |
|------|--------|--------------|----------|----------|----------|
| #1 | 100 | 269.2 (46.7%) | 292.2 (50.6%) | 15.4 (2.7%) | 576.7 |
| #2 | 37 | 87.0 (40.0%) | 128.5 (59.1%) | 2.1 (1.0%) | 217.6 |
| #3 | 50 | 115.6 (41.3%) | 159.1 (56.8%) | 5.5 (2.0%) | 280.2 |
| #4 | 58 | 105.6 (39.7%) | 145.3 (54.7%) | 14.9 (5.6%) | 265.8 |

### CPU utilization by phase (beacon-correlated, 187 samples, 20min window)

| Phase | Samples | dotmd CPU% | TEI CPU% | Combined | Utilization% |
|-------|---------|-----------|---------|----------|--------------|
| embed | 98 | 1% | 675% | 676% | 84.5% |
| extraction | 85 | 356% | 7% | 363% | 45.3% |
| purge | 2 | 213% | 2% | 214% | 26.8% |
| graph | 2 | 3% | 663% | 665% | 83.2% |
| **OVERALL** | **187** | **172%** | **350%** | **522%** | **65.2%** |

**Key finding:** 34.8% CPU capacity lost. GLiNER uses only ~4.5 of 8 cores (356%). TEI uses ~6.7 cores (675%). They alternate — when one works, the other idles.

---

## Optimized Run (post-optimization)

**Config:** `batch_predict_entities()`, `torch.set_num_threads(8)`, `model.config.max_len=512`
**Period:** 09:55–10:15 UTC, 2026-04-03 (8 benchmark files)

### Per-file timings (full paths available)

| File Path | Chunks | Purge(s) | Save(s) | Extract(s) | Graph(s) | Embed(s) | TOTAL(s) | s/chunk |
|-----------|--------|---------|---------|-----------|---------|---------|---------|---------|
| 20260313-0907-qAsDs3xj/transcript.md | 46 | 1.1 | 0.07 | 156.3 | 13.4 | 134.3 | 305.3 | 6.64 |
| 20260305-1031-6IknNHdd/transcript.md | 31 | 0.7 | 0.02 | 61.0 | 5.3 | 72.5 | 139.7 | 4.50 |
| 20260116-0931-204Lwhi4/transcript.md | 22 | 0.6 | 0.02 | 39.8 | 5.2 | 52.6 | 98.3 | 4.47 |
| 20251217-0900-wuLRtnHS/transcript.md | 3 | 0.6 | 0.11 | 14.0 | 0.5 | 11.9 | 27.0 | 9.00 |
| 20251113-0949-b6Xx6TvT/transcript.md | 22 | 0.5 | 0.01 | 63.1 | 2.0 | 67.1 | 132.8 | 6.04 |
| 20251105-1116-390Dro4y/transcript.md | 46 | 1.2 | 0.03 | 85.1 | 10.1 | 103.8 | 200.3 | 4.35 |
| 20251029-1350-9FPGgzQz/transcript.md | 1 | 0.6 | 0.09 | 5.2 | 0.3 | 4.0 | 10.2 | 10.23 |
| /mnt/home/docs/GIT.md | 48 | 0.6 | 0.14 | 41.0 | 5.9 | 30.2 | 77.9 | 1.62 |

### Aggregates

| Phase | Seconds | % of total |
|-------|---------|-----------|
| Extraction (GLiNER) | 465 | 47% |
| Embed (TEI) | 477 | 48% |
| Other (purge+chunk+save+fts5+graph+vec_store) | 49 | 5% |
| **TOTAL** | **992** | **100%** |
| **Avg sec/chunk** | **4.53** | (baseline: 5.61) |

### Speedup: 1.24x overall (5.61 → 4.53 sec/chunk)

| Category | Baseline s/c | Optimized s/c | Speedup |
|----------|-------------|--------------|---------|
| Markdown docs (GIT.md, 48 chunks) | 5.61 | 1.62 | 3.5x |
| Large voicenotes (46+ chunks) | 5.61 | 4.35-6.64 | 0.8-1.3x |
| Small files (1-3 chunks) | 5.61 | 9.0-10.2 | 0.6x (overhead) |

---

## Optimization Opportunity: Pipeline Parallelism

### The problem
Extraction (GLiNER) and Embed (TEI) run sequentially. Each is CPU-bound but uses different processes (dotmd container vs embeddings container). While one works, the other idles.

### What could run in parallel
During **embed phase** (TEI working, dotmd idle 99%):
- Chunk next file
- Save + FTS5 for next file
- Start extraction (GLiNER) for next file — BUT this competes for CPU with TEI

During **extraction phase** (GLiNER working at ~356%, TEI idle 99%):
- Send previous file's chunks to TEI for embedding — TEI runs in separate container, no CPU competition
- Purge next file's old data

### Estimated gain
If we overlap extraction(N) with embed(N-1):
- Currently: extraction_time + embed_time per file (sequential)
- Parallel: max(extraction_time, embed_time) per file
- For 46-chunk file: max(156, 134) = 156s vs 156+134 = 290s → **1.9x speedup**
- For the full corpus: depends on file size distribution

### Implementation considerations
- `index_file()` is called per-file by trickle in a loop. Parallelism requires restructuring to pipeline 2+ files.
- fcntl.flock exclusive lock prevents parallel indexing. The lock protects SQLite writes — may need finer-grained locking.
- Crash safety: fingerprints saved per-phase. If interrupted between files, no data loss.
- asyncio in trickle: already async. Could use asyncio.create_task for TEI HTTP calls.

### Benchmark files for regression testing
These 8 files can be used to measure any future optimization:
```
/mnt/voicenotes/20260313-0907-qAsDs3xj/transcript.md  (46 chunks)
/mnt/voicenotes/20260305-1031-6IknNHdd/transcript.md   (31 chunks)
/mnt/voicenotes/20260116-0931-204Lwhi4/transcript.md   (22 chunks)
/mnt/voicenotes/20251217-0900-wuLRtnHS/transcript.md   (3 chunks)
/mnt/voicenotes/20251113-0949-b6Xx6TvT/transcript.md   (22 chunks)
/mnt/voicenotes/20251105-1116-390Dro4y/transcript.md   (46 chunks)
/mnt/voicenotes/20251029-1350-9FPGgzQz/transcript.md   (1 chunk)
/mnt/home/docs/GIT.md                                  (48 chunks)
```

To re-benchmark: delete fingerprints for these files → restart → collect [prof] data.
