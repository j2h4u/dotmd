---
phase: 09-speed-benchmarks
verified: 2026-03-27T18:30:00Z
status: passed
score: 6/6 must-haves verified
re_verification: false
---

# Phase 9: Speed Benchmarks Verification Report

**Phase Goal:** Create TEI concurrency and GLiNER batching benchmarks that produce empirical throughput data for optimizing the trickle indexer.
**Verified:** 2026-03-27T18:30:00Z
**Status:** passed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | TEI concurrency benchmark reports texts/sec for 1, 2, and 3 concurrent workers with mean/stddev/min/max | VERIFIED | `worker_counts = [1, 2, 3]` at line 78; stats table prints mean/stdev/min/max at lines 111-131; 3 iterations per worker count at line 79 |
| 2 | TEI benchmark prints a CONCLUSION line stating whether concurrency helps and which worker count is best | VERIFIED | Lines 144-147: `CONCLUSION: Concurrency {verdict}. Best throughput at workers={best_workers}.` + `Speedup vs sequential: {speedup:.2f}x`; 5% threshold at line 141 |
| 3 | GLiNER benchmark reports texts/sec for sequential (predict_entities) vs batch (inference) at batch_size 1, 4, 8 | VERIFIED | Sequential via `predict_entities` at line 46; batch via `model.inference()` at line 54; configs list at lines 102-106 tests bs=1,4,8 plus packed bs=8 |
| 4 | GLiNER benchmark prints a CONCLUSION line stating whether batching helps and which batch_size is best | VERIFIED | Lines 186-189: `CONCLUSION: Batching {verdict}. Best throughput at {best_label}.` + `Speedup vs sequential: {speedup:.2f}x`; 5% threshold at line 185 |
| 5 | Both benchmarks generate synthetic test data and never touch production indexes | VERIFIED | Both scripts have `generate_test_texts()` using fixed seed paragraph; no imports from dotmd package; no references to `~/.dotmd/`, `lancedb`, `graphdb`, `metadata.db`, or `index_dir` in either file |
| 6 | Both benchmarks include warmup iterations before timed runs | VERIFIED | TEI: `warmup_batches=2` parameter, warmup loop at lines 62-63; GLiNER: `warmup_count=5` texts at lines 94-98 |

**Score:** 6/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/benchmarks/bench_tei_concurrency.py` | TEI concurrency benchmark script, contains ThreadPoolExecutor, min 80 lines | VERIFIED | 151 lines, contains ThreadPoolExecutor, httpx.Client, valid Python syntax |
| `backend/benchmarks/bench_gliner_batching.py` | GLiNER batching benchmark script, contains model.inference, min 80 lines | VERIFIED | 200 lines, contains model.inference(), GLiNER.from_pretrained, valid Python syntax |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `bench_tei_concurrency.py` | TEI /embed endpoint | httpx.Client POST to DOTMD_EMBEDDING_URL/embed | VERIFIED | `httpx.Client()` at line 60, `client.post(f"{url}/embed", ...)` at lines 41-44, URL from `DOTMD_EMBEDDING_URL` env var at line 76 |
| `bench_gliner_batching.py` | GLiNER model | GLiNER.from_pretrained loading urchade/gliner_multi-v2.1 | VERIFIED | `GLiNER.from_pretrained(MODEL_NAME)` at line 84, `MODEL_NAME = "urchade/gliner_multi-v2.1"` at line 17 |

Note: gsd-tools key-link check reported false negatives due to multiline regex matching limitations. Manual grep confirmed both links are present and correctly wired.

### Data-Flow Trace (Level 4)

Not applicable -- these are standalone benchmark scripts that generate their own synthetic data and print results to stdout. They do not render dynamic data from a data source.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| TEI script valid Python | `python3 -c "import ast; ast.parse(open('backend/benchmarks/bench_tei_concurrency.py').read())"` | syntax OK | PASS |
| GLiNER script valid Python | `python3 -c "import ast; ast.parse(open('backend/benchmarks/bench_gliner_batching.py').read())"` | syntax OK | PASS |
| TEI script has all required functions | AST parse: functions list | `generate_test_texts, embed_batch, benchmark_concurrency, main` | PASS |
| GLiNER script has all required functions | AST parse: functions list | `generate_test_texts, benchmark_sequential, benchmark_batch, benchmark_batch_packed, main, _extract_batch_size` | PASS |
| Neither script imports dotmd | grep for `import dotmd` | No actual imports found (docstring mention is not an import) | PASS |
| Neither script uses deprecated API | grep for `batch_predict_entities` | Not found in GLiNER script | PASS |
| Commits exist | `git log --oneline` | `d6465aa` and `2a344a8` both verified | PASS |
| Live execution | Requires running TEI server + GLiNER model in Docker | N/A | SKIP (needs live services) |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| SPEED-01 | 09-01-PLAN | Benchmark measures end-to-end texts/sec for concurrent TEI requests (1, 2, 3 parallel) and reports whether concurrency improves throughput | SATISFIED | `bench_tei_concurrency.py` tests workers=[1,2,3], reports texts/sec table with stats, prints CONCLUSION with helps/does-not-help verdict and speedup ratio |
| SPEED-02 | 09-01-PLAN | Benchmark measures GLiNER batch vs sequential NER throughput and reports whether batching improves speed | SATISFIED | `bench_gliner_batching.py` tests sequential vs batch (bs=1,4,8) vs packed (bs=8), reports texts/sec table with stats, prints CONCLUSION with helps/does-not-help verdict and speedup ratio |

No orphaned requirements found -- REQUIREMENTS.md maps exactly SPEED-01 and SPEED-02 to Phase 9, matching the PLAN frontmatter.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `bench_gliner_batching.py` | 62, 132 | "not available" string | Info | Intentional -- graceful fallback message when GLiNER InferencePackingConfig is not installed; returns -1.0 sentinel and prints "N/A" |

No blockers or warnings. The "not available" match is by design -- it handles the case where the packing feature is absent from the installed GLiNER version.

### Human Verification Required

### 1. TEI Concurrency Benchmark Execution

**Test:** Run `docker exec dotmd-app-1 python benchmarks/bench_tei_concurrency.py` inside the dotMD container
**Expected:** Prints a table with texts/sec for workers=1,2,3 and a CONCLUSION line stating whether concurrency helps
**Why human:** Requires a running TEI service on the Docker network; results depend on live hardware performance

### 2. GLiNER Batching Benchmark Execution

**Test:** Run `docker exec dotmd-app-1 python benchmarks/bench_gliner_batching.py` inside the dotMD container
**Expected:** Prints a table with texts/sec for sequential, batch (bs=1,4,8), and packed (bs=8), plus a CONCLUSION line stating whether batching helps
**Why human:** Requires GLiNER model download and ~3-5 minutes of CPU-intensive inference; may need memory monitoring on the 16GB server

### Gaps Summary

No gaps found. All 6 must-have truths verified, both artifacts pass all 3 levels (exist, substantive, wired), all acceptance criteria met, both requirements (SPEED-01, SPEED-02) satisfied. The only remaining step is human execution of the benchmarks against live services to collect actual throughput numbers.

---

_Verified: 2026-03-27T18:30:00Z_
_Verifier: Claude (gsd-verifier)_
