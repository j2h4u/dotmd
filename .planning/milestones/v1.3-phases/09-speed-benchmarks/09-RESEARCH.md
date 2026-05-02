# Phase 9: Speed Benchmarks - Research

**Researched:** 2026-03-27
**Domain:** Python benchmarking / TEI HTTP concurrency / GLiNER batch NER
**Confidence:** HIGH

## Summary

This phase produces **benchmark scripts** -- not production optimizations. The goal is empirical data answering two questions: (1) does sending concurrent HTTP requests to TEI improve embedding throughput, and (2) does GLiNER's batch inference outperform sequential per-chunk prediction on this hardware.

The benchmark scripts are standalone (not part of the production pipeline), run inside the dotMD container against the live TEI instance, and output a human-readable report with a clear conclusion for each question. Results inform Phase 10 (background indexer) and future SPEED-03/SPEED-04 implementation decisions.

**Primary recommendation:** Two standalone benchmark scripts in `backend/benchmarks/` -- one for TEI concurrency, one for GLiNER batching. Each generates synthetic test data, measures throughput, and prints a comparison table with a conclusion line.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SPEED-01 | Benchmark measures end-to-end texts/sec for concurrent TEI requests (1, 2, 3 parallel) and reports whether concurrency improves throughput | TEI supports max_concurrent_requests=512, max_batch_requests=8. Use `concurrent.futures.ThreadPoolExecutor` with httpx sync client to send parallel batched requests. Measure wall-clock texts/sec for each concurrency level. |
| SPEED-02 | Benchmark measures GLiNER batch vs sequential NER throughput and reports whether batching improves speed | GLiNER 0.2.26 `inference()` method accepts `batch_size` parameter (default 8). Sequence packing available since v0.2.23 (~2.5x speedup claimed). Compare sequential `predict_entities()` vs `inference(texts, batch_size=N)` for N=1,4,8. |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **TEI mandatory**: `DOTMD_EMBEDDING_URL` is required, no local model fallback
- **Never reload indexes per-request**: Benchmark scripts must NOT touch production indexes
- **All public APIs go through api/service.py**: Benchmarks bypass service layer -- they directly test TEI HTTP and GLiNER model, not the full pipeline
- **Docker-first**: Benchmarks run inside the dotMD container (access to TEI network, GLiNER model)
- **CPU-only**: Xeon E3-1245 V2 (Ivy Bridge), no AVX2, PyTorch <2.5

## Standard Stack

### Core (already installed -- no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| httpx | 0.28.1 | HTTP client for TEI requests | Already in deps, supports sync and async |
| concurrent.futures | stdlib | Thread-based parallelism for concurrent TEI requests | I/O-bound HTTP calls benefit from threading |
| time (perf_counter) | stdlib | High-resolution timing | Already used throughout pipeline.py |
| gliner | 0.2.26 | NER model with batch inference | Already installed, has `inference()` with batch_size |
| torch | <2.5 | GLiNER backend | Already installed, CPU-only |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| ThreadPoolExecutor | asyncio + httpx.AsyncClient | Async is faster for high concurrency but adds complexity; 1-3 workers is too few to matter |
| time.perf_counter | timeit module | perf_counter is simpler for wall-clock measurement; timeit better for micro-benchmarks |
| Custom script | pytest-benchmark | Over-engineered for 2 simple benchmarks with manual analysis |

**Installation:** None needed -- all libraries already available.

## Architecture Patterns

### Recommended Project Structure
```
backend/
├── benchmarks/
│   ├── bench_tei_concurrency.py    # SPEED-01
│   └── bench_gliner_batching.py    # SPEED-02
└── ...
```

### Pattern 1: Benchmark Script Structure
**What:** Each benchmark script is self-contained, generates its own test data, runs measurements, and prints a human-readable report.
**When to use:** Always for these benchmarks.
**Example:**
```python
"""TEI concurrency benchmark for SPEED-01."""
import time
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx


def generate_test_texts(n: int, avg_words: int = 150) -> list[str]:
    """Generate n synthetic texts of ~avg_words length.

    Uses realistic-ish content so tokenization is representative.
    """
    # Use a fixed seed paragraph repeated/sliced to target length
    base = (
        "The server infrastructure runs on a dedicated machine with Docker containers. "
        "Each service communicates through internal networks using REST APIs. "
        "The knowledge base contains transcribed voice notes and documentation files. "
        "Search combines semantic embeddings, keyword matching, and graph traversal. "
    )
    words = base.split()
    texts = []
    for i in range(n):
        # Vary length slightly per text
        target = avg_words + (i % 20) - 10
        repeated = (words * ((target // len(words)) + 1))[:target]
        texts.append(" ".join(repeated))
    return texts


def embed_batch(client: httpx.Client, url: str, texts: list[str]) -> int:
    """Send a batch to TEI /embed, return count of texts embedded."""
    resp = client.post(
        f"{url}/embed",
        json={"inputs": texts, "truncate": True},
        timeout=120.0,
    )
    resp.raise_for_status()
    return len(texts)


def benchmark_concurrency(
    url: str,
    texts: list[str],
    batch_size: int,
    max_workers: int,
    warmup_batches: int = 2,
) -> float:
    """Return texts/sec for given concurrency level."""
    batches = [texts[i:i + batch_size] for i in range(0, len(texts), batch_size)]

    with httpx.Client() as client:
        # Warmup
        for b in batches[:warmup_batches]:
            embed_batch(client, url, b)

        # Timed run
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(embed_batch, client, url, b) for b in batches]
            total = sum(f.result() for f in as_completed(futures))
        elapsed = time.perf_counter() - t0

    return total / elapsed


def main():
    url = os.environ.get("DOTMD_EMBEDDING_URL", "http://embeddings:80")
    # ... run benchmarks, print table
```

### Pattern 2: GLiNER Batch vs Sequential
**What:** Compare `predict_entities` (one-at-a-time, batch_size=1 internally) vs `inference` (batch processing with configurable batch_size).
**When to use:** For SPEED-02.
**Example:**
```python
"""GLiNER batching benchmark for SPEED-02."""
import time
from gliner import GLiNER

ENTITY_TYPES = ["person", "organization", "technology", "concept", "location"]
MODEL_NAME = "urchade/gliner_multi-v2.1"


def benchmark_sequential(model, texts: list[str]) -> float:
    """Process texts one at a time. Return texts/sec."""
    t0 = time.perf_counter()
    for text in texts:
        model.predict_entities(text, ENTITY_TYPES, threshold=0.5)
    elapsed = time.perf_counter() - t0
    return len(texts) / elapsed


def benchmark_batch(model, texts: list[str], batch_size: int) -> float:
    """Process texts in batches. Return texts/sec."""
    t0 = time.perf_counter()
    model.inference(texts, ENTITY_TYPES, threshold=0.5, batch_size=batch_size)
    elapsed = time.perf_counter() - t0
    return len(texts) / elapsed
```

### Anti-Patterns to Avoid
- **Measuring cold start**: Always run warmup iterations before timing. GLiNER model load is ~5-10s and TEI has JIT compilation.
- **Using production indexes**: Benchmarks must create their own test data, never touch `~/.dotmd/` or production volumes.
- **Averaging without variance**: Report min/max/stddev, not just mean. Single runs can be noisy on a shared server.
- **Forgetting TEI batch size limits**: TEI server reports `max_client_batch_size: 32` and `max_batch_requests: 8`. Sending batches > 32 texts per request will get 413 errors.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP connection pooling | Manual socket reuse | httpx.Client context manager | Handles keep-alive, connection reuse automatically |
| Thread pool management | Manual Thread creation | concurrent.futures.ThreadPoolExecutor | Handles worker lifecycle, exception propagation |
| Batch splitting | Custom loop logic | List slicing `texts[i:i+bs]` | Simple, readable, correct |

## Common Pitfalls

### Pitfall 1: TEI Server Contention
**What goes wrong:** TEI is shared infrastructure (used by other services on the server). Benchmark results vary wildly depending on other load.
**Why it happens:** TEI has `max_concurrent_requests: 512` but only 8 CPU threads.
**How to avoid:** Run benchmarks during low-activity periods. Run multiple iterations and report variance. Note whether other services were using TEI during the run.
**Warning signs:** High stddev across runs, texts/sec varying by >20%.

### Pitfall 2: TEI Batch Size vs Concurrency Confusion
**What goes wrong:** Confusing "batch size per request" (how many texts in one POST) with "concurrency" (how many simultaneous POST requests).
**Why it happens:** SPEED-01 asks about concurrent requests, not batch size. The current code already batches (bs=4). The question is whether sending N batches in parallel beats sending N batches sequentially.
**How to avoid:** Fix batch_size constant (e.g., bs=4 matching production), vary only max_workers (1, 2, 3).
**Warning signs:** Benchmark accidentally tests batch_size variation instead of concurrency.

### Pitfall 3: GLiNER Memory Spikes with Large Batches
**What goes wrong:** GLiNER batch inference allocates tensors proportional to batch_size * max_seq_len. Large batches can OOM on 16GB server.
**Why it happens:** Each text is tokenized and padded to the longest sequence in the batch.
**How to avoid:** Keep batch_size <= 16. Monitor memory during benchmarks. The benchmark text lengths should match production (~150 words = ~200 tokens per chunk).
**Warning signs:** Process killed by OOM killer, swap usage spikes.

### Pitfall 4: GLiNER predict_entities vs inference API
**What goes wrong:** Using deprecated `batch_predict_entities` method which just forwards to `inference`.
**Why it happens:** Old examples and documentation reference the deprecated method.
**How to avoid:** Use `model.inference(texts, labels, batch_size=N)` directly -- this is the current API in GLiNER 0.2.26. `predict_entities` wraps inference for single texts.
**Warning signs:** Deprecation warnings in output.

### Pitfall 5: Sequential Baseline Uses batch_size=1 Internally
**What goes wrong:** Calling `predict_entities` per text actually calls `inference([text], ...)` with DataLoader batch_size=1. This is already "batch of 1" not "no batching". The comparison should be explicit about this.
**Why it happens:** GLiNER always uses DataLoader internally.
**How to avoid:** Sequential baseline = loop of `predict_entities()` calls. Batch baseline = single `inference(all_texts, batch_size=N)` call. Make the comparison clear in the report.

## Code Examples

### TEI Concurrency Benchmark Output Format
```
TEI Concurrency Benchmark
=========================
Model: intfloat/multilingual-e5-large (via TEI 1.6.1)
Hardware: Xeon E3-1245 V2, 4C/8T
Test corpus: 100 texts, ~150 words each
Batch size per request: 4 (matching production)
Warmup: 2 batches
Iterations: 3

| Workers | texts/sec (mean) | stddev | min    | max    |
|---------|------------------|--------|--------|--------|
| 1       | 12.3             | 0.4    | 11.8   | 12.7   |
| 2       | 15.1             | 0.6    | 14.3   | 15.6   |
| 3       | 14.8             | 0.9    | 13.7   | 15.5   |

CONCLUSION: Concurrency {helps/does not help}. Best throughput at N={1|2|3} workers.
Speedup vs sequential: {X.Xx}
```

### GLiNER Batching Benchmark Output Format
```
GLiNER Batching Benchmark
=========================
Model: urchade/gliner_multi-v2.1
Hardware: Xeon E3-1245 V2, 4C/8T (CPU-only, PyTorch <2.5)
Entity types: person, organization, technology, concept, location
Test corpus: 50 texts, ~150 words each
Warmup: 5 texts
Iterations: 3

| Mode            | batch_size | texts/sec (mean) | stddev | min  | max  |
|-----------------|------------|------------------|--------|------|------|
| Sequential      | 1          | 0.8              | 0.05   | 0.7  | 0.85 |
| Batch           | 4          | 1.2              | 0.08   | 1.1  | 1.3  |
| Batch           | 8          | 1.5              | 0.10   | 1.4  | 1.6  |
| Batch + packing | 8          | 2.1              | 0.12   | 2.0  | 2.2  |

CONCLUSION: Batching {helps/does not help}. Best throughput at batch_size={N}.
Speedup vs sequential: {X.Xx}
```

## Hardware Context

Critical context for interpreting benchmark results:

| Property | Value | Impact |
|----------|-------|--------|
| CPU | Xeon E3-1245 V2, 4 cores / 8 threads, 3.4 GHz | TEI uses all 8 threads for inference |
| RAM | 16GB total, ~7.7GB available | GLiNER + PyTorch need ~2GB, TEI uses ~2.6GB |
| AVX | Yes (AVX1 only, no AVX2) | PyTorch <2.5 constraint, limits SIMD throughput |
| TEI model | intfloat/multilingual-e5-large (1024-dim) | Large model = slower per-text but higher quality |
| TEI config | max_batch_requests=8, max_client_batch_size=32, max_batch_tokens=16384 | Hard limits on what TEI accepts |
| TEI batch_size | Production uses bs=4 | Starting point; benchmark should also test if higher bs helps |
| GLiNER model | urchade/gliner_multi-v2.1 | ~400MB model, CPU inference |
| GLiNER version | 0.2.26 | Has inference packing since 0.2.23 |

## TEI Server Configuration (live, verified)

From `curl http://localhost:8088/info`:

```json
{
  "model_id": "intfloat/multilingual-e5-large",
  "model_dtype": "float32",
  "max_concurrent_requests": 512,
  "max_input_length": 512,
  "max_batch_tokens": 16384,
  "max_batch_requests": 8,
  "max_client_batch_size": 32,
  "tokenization_workers": 8,
  "version": "1.6.1"
}
```

Key constraint: `max_batch_tokens=16384` means a batch of 32 texts x 512 tokens = 16384 tokens exactly at the limit. Shorter texts allow larger batches; longer texts may trigger 413.

## GLiNER API (verified from source, v0.2.26)

### Current API (use this)
```python
# Single text (wraps inference internally)
results = model.predict_entities(text, labels, threshold=0.5)

# Batch processing (the method to benchmark)
results = model.inference(
    texts,           # List[str] -- all texts at once
    labels,          # List[str] -- entity types
    batch_size=8,    # DataLoader batch size (default 8)
    threshold=0.5,
)
# Returns: List[List[Dict]] -- one list of entities per text
```

### Deprecated (do not use)
```python
# DEPRECATED -- forwards to inference()
results = model.batch_predict_entities(texts, labels)
```

### Sequence Packing (optional, may improve throughput)
```python
from gliner.infer_packing import InferencePackingConfig

# Pack short sequences into longer streams to reduce padding
packing = InferencePackingConfig(max_length=512, streams_per_batch=1)
results = model.inference(
    texts, labels, batch_size=8, packing_config=packing,
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| GLiNER batch_predict_entities | GLiNER inference() with batch_size | v0.2.x | Unified API, deprecated old method |
| No sequence packing | InferencePackingConfig | GLiNER v0.2.23 (2025) | ~2.5x speedup claimed for short sequences |
| httpx sync only | httpx sync + ThreadPoolExecutor | Always available | I/O-bound concurrency for TEI calls |

## Open Questions

1. **Does TEI internal batching saturate the CPU?**
   - What we know: TEI has internal dynamic batching (`max_batch_requests=8`). When 3 clients send requests simultaneously, TEI may batch them internally, which could either help (better GPU/CPU utilization) or hurt (contention on CPU inference).
   - What's unclear: Whether TEI's internal batching on CPU provides any benefit, or if the CPU is already fully utilized processing one batch at a time.
   - Recommendation: The benchmark will answer this empirically. If workers=1 is fastest, TEI is compute-bound and concurrent requests just add queueing overhead.

2. **Is GLiNER packing worth testing?**
   - What we know: InferencePackingConfig exists since 0.2.23, claimed ~2.5x for short sequences. Our chunks are ~150 words (~200 tokens), which is moderate-length.
   - What's unclear: Whether packing helps for texts that already fill most of the 512-token window.
   - Recommendation: Include packing as an optional test configuration (batch_size=8 with and without packing). Low effort, potentially valuable data.

3. **How many test texts are needed for stable measurements?**
   - What we know: Pipeline.py processes 532 chunks for the voicenotes corpus. Production will be ~13k chunks.
   - What's unclear: At what N do measurements stabilize.
   - Recommendation: Use 100 texts for TEI (25 batches at bs=4, takes ~30s per run at sequential speed). Use 50 texts for GLiNER (slower, ~60s per run sequential). Run 3 iterations each.

## Sources

### Primary (HIGH confidence)
- TEI server `/info` endpoint -- live configuration verified via `curl http://localhost:8088/info`
- GLiNER source code at `/home/j2h4u/repos/j2h4u/dotmd/backend/.venv/lib/python3.13/site-packages/gliner/model.py` -- `inference()` method signature, batch_size parameter, deprecated batch_predict_entities
- GLiNER `infer_packing.py` -- InferencePackingConfig dataclass verified from installed source
- Production .env at `/opt/docker/dotmd/.env` -- DOTMD_TEI_BATCH_SIZE=4 confirmed
- `backend/src/dotmd/search/semantic.py` -- current TEI integration code, _encode_via_tei method

### Secondary (MEDIUM confidence)
- [GLiNER batch processing discussion #73](https://github.com/urchade/GLiNER/discussions/73) -- community reports on batch vs sequential performance, sequence packing in v0.2.23
- [TEI GitHub repository](https://github.com/huggingface/text-embeddings-inference) -- concurrent request configuration, CPU inference patterns

### Tertiary (LOW confidence)
- Community claims of "~2.5x speedup with packing" -- needs empirical validation on this hardware

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all libraries already installed, versions verified from installed packages
- Architecture: HIGH - benchmark scripts are simple standalone Python, no complex patterns needed
- Pitfalls: HIGH - hardware verified, TEI config verified from live server, GLiNER API verified from source
- TEI concurrency benefit: LOW - must be determined empirically (that's the whole point of the phase)
- GLiNER batching benefit: MEDIUM - API supports it and packing exists, but community reports mixed results on CPU

**Research date:** 2026-03-27
**Valid until:** 2026-04-27 (stable -- benchmark methodology doesn't change, hardware is fixed)
