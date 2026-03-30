# Phase 11: Embedding Model Swap - Research

**Researched:** 2026-03-30
**Domain:** Embedding model integration (pplx-embed), Docker serving, A/B evaluation
**Confidence:** MEDIUM

## Summary

Phase 11 replaces the current multilingual-e5-large embedding model with Perplexity's pplx-embed model family on a feature branch. The pplx-embed architecture uses TWO models: `pplx-embed-context-v1-0.6B` for document indexing (context-aware, grouped chunks per document) and `pplx-embed-v1-0.6B` for query encoding (standard single-text). Both produce 1024-dim embeddings in the same vector space, use cosine similarity, and require no instruction prefixes -- eliminating the current E5 "query: " / "passage: " prefix logic.

The critical architectural challenge is that pplx-embed-context requires grouped input (chunks organized by document, concatenated with SEP tokens) which TEI's standard `/embed` endpoint does not natively support. For indexing, the context model must run through Python's `transformers`/`AutoModel` with `trust_remote_code=True`, not through TEI. For query-time encoding, standard `pplx-embed-v1` CAN be served via TEI v1.9.2+ using the `/embed` endpoint. This means the phase needs a hybrid serving approach: TEI for queries, in-process Python for document indexing.

The server's 16GB RAM with ~8GB in use, no GPU, and Xeon E3 V2 (AVX but not AVX2) creates tight resource constraints. The 0.6B model (~1.2GB weights, ~2-3GB runtime) is comparable to the current E5-large (2.4GB in TEI). Running both models simultaneously during the A/B comparison period will require careful memory management.

**Primary recommendation:** Use a hybrid approach -- TEI v1.9.3 for pplx-embed-v1 query encoding, and an in-process Python embedding wrapper (using `transformers.AutoModel`) for pplx-embed-context document indexing. The in-process context model only runs during indexing (not kept resident), keeping memory manageable.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EVAL-01 | Reproducible test query set (5+ queries) with expected result annotations | Baseline already saved in SEARCH-BASELINE.md with 5 queries. Implement as a script that runs queries and captures results |
| EVAL-02 | A/B comparison script that runs same queries on two branches and reports score/rank differences | Script reads baseline file, runs queries via DotMDService, compares rank positions and scores |
| EMBED-01 | pplx-embed-context-v1-0.6B integration for document indexing (grouped chunks per document) | Requires in-process Python model loading with trust_remote_code=True, grouped chunks by file_path, SEP-token concatenation. See Architecture Patterns |
| EMBED-02 | pplx-embed-v1-0.6B integration for query encoding (standard single-text) | Served via TEI v1.9.3 with --model-id and --dtype float32. No prefix needed -- remove E5 prefix logic |
| EMBED-03 | Self-hosted deployment in Docker (no external API dependency) | TEI cpu-1.9 container for query model. In-process Python for context model during indexing only |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| text-embeddings-inference | cpu-1.9.3 | Serve pplx-embed-v1 for query encoding | Official HF serving infra, Qwen3 CPU support fixed in 1.9+ |
| transformers | >=4.45 | Load pplx-embed-context-v1 for indexing | Required for trust_remote_code=True, custom AutoModel.encode() |
| torch | <2.5 | Backend for transformers model | CPU-only, must be <2.5 due to AVX2 requirement in 2.5+ |
| perplexity-ai/pplx-embed-v1-0.6B | latest | Query embedding model (1024-dim, no prefix) | TEI-compatible, standard flat input |
| perplexity-ai/pplx-embed-context-v1-0.6B | latest | Document embedding model (1024-dim, context-aware) | Grouped chunks per document, SEP-token concatenation |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| httpx | >=0.27 | HTTP client for TEI /embed calls | Already in deps, used for query encoding |
| sqlite-vec | >=0.1.6 | Vector store (1024-dim cosine) | Already in use, same dimension as E5-large |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| In-process context model | TEI for both models | TEI /embed doesn't support grouped input for context model |
| transformers AutoModel | sentence-transformers SentenceTransformer | Both work, but AutoModel gives more control over the context grouping logic |
| pplx-embed-v1-4B | pplx-embed-v1-0.6B | 4B is 2560-dim, too large for 16GB RAM server |

## Architecture Patterns

### Two-Model Serving Architecture

```
INDEXING (batch, offline):
  Chunks grouped by document
    -> In-process Python (transformers.AutoModel)
    -> pplx-embed-context-v1-0.6B
    -> Per-chunk embeddings (1024-dim)
    -> sqlite-vec store

QUERY (online, per-request):
  Query text
    -> HTTP POST to TEI /embed
    -> pplx-embed-v1-0.6B
    -> Query embedding (1024-dim)
    -> sqlite-vec cosine search
```

### Pattern 1: Context-Aware Document Embedding

The context model takes chunks grouped by document and returns per-chunk embeddings that incorporate surrounding context. Chunks are concatenated with SEP tokens internally.

**Input format:**
```python
# Grouped by document -- order matters!
doc_chunks = [
    ["chunk1_of_doc_A", "chunk2_of_doc_A", "chunk3_of_doc_A"],
    ["chunk1_of_doc_B", "chunk2_of_doc_B"],
]

# Returns list of numpy arrays, one per document
# embeddings[0].shape = (3, 1024)  -- 3 chunks from doc A
# embeddings[1].shape = (2, 1024)  -- 2 chunks from doc B
embeddings = model.encode(doc_chunks)
```

**Integration point:** In `IndexingPipeline._ingest_and_finalize()` and `IndexingPipeline.index_file()`, chunks are currently embedded in a flat batch. Must be restructured to group by `chunk.file_path` before calling the context model.

### Pattern 2: Query Encoding via TEI (No Prefix)

pplx-embed-v1 deliberately avoids instruction prefixes. The current E5 prefix logic in `SemanticSearchEngine` must be removed.

**Current (E5):**
```python
# encode_batch adds "passage: " prefix
prefixed = [f"passage: {t}" for t in texts]
# search adds "query: " prefix
query_embedding = self.encode(f"query: {query}")
```

**New (pplx-embed):**
```python
# encode_batch -- no prefix needed
# search -- no prefix needed
query_embedding = self.encode(query)
```

### Pattern 3: Feature Branch Isolation

The A/B comparison runs on a feature branch with a separate index directory. The production index on `dev` remains untouched.

```
~/.dotmd/             -- production E5-large index (untouched)
~/.dotmd-pplx/        -- pplx-embed index on feature branch
```

Override via `DOTMD_INDEX_DIR=~/.dotmd-pplx` during testing.

### Anti-Patterns to Avoid
- **Loading context model per-request:** The context model is for INDEXING only. Queries use pplx-embed-v1 via TEI. Never load the 0.6B context model into the serving hot path.
- **Running two TEI containers simultaneously:** Memory too tight. Context model runs in-process during indexing only, then is unloaded.
- **Using pplx-embed-v1 for document indexing:** Loses the context-awareness benefit. Documents must use the context model.
- **Sending individual chunks to context model:** Loses context. Chunks must be grouped by document to get context-aware embeddings.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SEP-token concatenation | Manual tokenizer + SEP insertion | `AutoModel.from_pretrained(trust_remote_code=True)` + `.encode()` | Model's custom code handles SEP insertion, pooling, and chunk extraction correctly |
| Embedding server | Custom Flask/FastAPI wrapper | TEI cpu-1.9.3 for query model | TEI handles batching, tokenization, OOM recovery |
| A/B comparison framework | Complex statistical testing | Simple rank comparison script | 5 queries, manual review -- don't over-engineer |

## Common Pitfalls

### Pitfall 1: TEI Version Too Old for pplx-embed
**What goes wrong:** TEI v1.6 (current) does not support Qwen3 architecture. pplx-embed models are based on Qwen3.
**Why it happens:** Server was set up with E5-large which only needs older TEI.
**How to avoid:** Upgrade TEI to cpu-1.9.3. The pplx-embed-v1 model card explicitly requires TEI v1.9.2+.
**Warning signs:** TEI fails to load model, architecture error in logs.

### Pitfall 2: E5 Prefix Logic Still Active After Model Swap
**What goes wrong:** "query: " and "passage: " prefixes are hard-coded in SemanticSearchEngine. If left active with pplx-embed, they contaminate the text and degrade results.
**Why it happens:** E5 family requires these prefixes; pplx-embed explicitly does not.
**How to avoid:** Make prefix behavior configurable or remove it when embedding model is not E5-family. The model requires NO prefixes at all.
**Warning signs:** Unexpectedly low similarity scores, "query: " appearing in encoded text.

### Pitfall 3: Context Model Runs Out of Memory on Full Corpus
**What goes wrong:** Loading transformers model + processing all chunks in-process exhausts 16GB RAM.
**Why it happens:** 0.6B model ~2-3GB in RAM + large batch of chunks with long context window (32K tokens).
**How to avoid:** Process documents one-at-a-time or in small batches. Unload model after indexing is complete. Set `--max-batch-tokens` conservatively.
**Warning signs:** OOM killer, swap thrashing, process killed.

### Pitfall 4: Float32 vs INT8 Embedding Mismatch
**What goes wrong:** pplx-embed natively produces INT8 embeddings. sqlite-vec stores float32. Mixing formats or not normalizing consistently breaks cosine similarity.
**Why it happens:** TEI with `--dtype float32` produces float32 vectors. In-process model produces int8 by default.
**How to avoid:** Use `--dtype float32` in TEI for query model. For context model in-process, explicitly request float32 output or convert int8 to float32 before storing. Both sides MUST use the same dtype for cosine similarity to be meaningful.
**Warning signs:** Cosine similarities near 0 or nonsensical rankings.

### Pitfall 5: Dimension Change Breaks Existing Index
**What goes wrong:** E5-large produces 1024-dim vectors. pplx-embed also produces 1024-dim. NOT a problem in this case -- but sqlite-vec's _create_vec_table() detects dimension changes and drops/recreates the table.
**Why it happens:** Good defensive code, but worth noting.
**How to avoid:** Use a separate index directory for the feature branch. Do NOT mix E5 and pplx-embed vectors in the same index.
**Warning signs:** N/A -- same dimension, but different vector spaces.

### Pitfall 6: PyTorch AVX2 Requirement
**What goes wrong:** PyTorch >= 2.5 requires AVX2. Server CPU (Xeon E3 V2) only has AVX.
**Why it happens:** PyTorch dropped AVX-only support.
**How to avoid:** Pin `torch<2.5` in requirements. TEI handles its own PyTorch internally (Candle backend, not PyTorch), so only the in-process context model loading needs this constraint.
**Warning signs:** Illegal instruction crash, SIGILL.

## Code Examples

### Loading Context Model for Indexing
```python
# Source: HuggingFace model card for pplx-embed-context-v1-0.6B
from transformers import AutoModel

model = AutoModel.from_pretrained(
    "perplexity-ai/pplx-embed-context-v1-0.6B",
    trust_remote_code=True,
)

# Group chunks by document
doc_chunks = [
    ["chunk1_doc_A", "chunk2_doc_A"],
    ["chunk1_doc_B", "chunk2_doc_B", "chunk3_doc_B"],
]

# Returns list of numpy arrays
embeddings = model.encode(doc_chunks)
# embeddings[0].shape == (2, 1024)
# embeddings[1].shape == (3, 1024)
```

### TEI Docker for Query Model
```bash
# Source: pplx-embed-v1-0.6B model card
docker run -p 8080:80 \
  -v hf-cache:/data \
  ghcr.io/huggingface/text-embeddings-inference:cpu-1.9 \
  --model-id perplexity-ai/pplx-embed-v1-0.6B \
  --dtype float32
```

### Querying TEI /embed Endpoint (No Prefix)
```python
# Source: existing dotMD SemanticSearchEngine._encode_via_tei
import httpx

response = httpx.post(
    "http://embeddings:80/embed",
    json={"inputs": ["your search query"], "truncate": True},
    timeout=30.0,
)
embeddings = response.json()  # list of list[float], 1024-dim
```

### Grouping Chunks by Document in Pipeline
```python
# Integration pattern for IndexingPipeline
from collections import defaultdict

def group_chunks_by_file(chunks: list[Chunk]) -> list[list[str]]:
    """Group chunk texts by file_path, preserving order."""
    by_file: dict[str, list[str]] = defaultdict(list)
    for chunk in chunks:
        by_file[str(chunk.file_path)].append(chunk.text)
    return list(by_file.values())
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| E5 query/passage prefixes | No prefixes (pplx-embed) | Feb 2026 | Simpler pipeline, no prefix mismatch bugs |
| Single model for indexing+queries | Asymmetric: context model for docs, standard for queries | Feb 2026 | Better retrieval via document context awareness |
| TEI cpu-1.6 | TEI cpu-1.9.3 | Mar 2025 | Qwen3 support, pplx-embed compatibility, CPU fixes |
| sentence-transformers only | transformers AutoModel with trust_remote_code | Feb 2026 | Required for custom encode() in context model |

## Open Questions

1. **Cross-model vector space compatibility**
   - What we know: The paper says pplx-embed-v1 is created via SLERP (spherical linear interpolation) of the contextual and triplet checkpoints. Both produce 1024-dim. Perplexity's API docs show queries with the context model using `[[query]]` wrapper, but third-party sources describe asymmetric retrieval (context for docs, standard for queries).
   - What's unclear: Whether using pplx-embed-v1 for queries against pplx-embed-context-v1 document embeddings produces optimal results, or if both sides should use the context model.
   - Recommendation: Test BOTH approaches during A/B. Primary: asymmetric (context docs + standard queries). Fallback: context model for both (query as `[[query]]`). Compare results to determine which is better.

2. **In-process context model memory overhead**
   - What we know: 0.6B model ~1.2GB weights on disk, ~2-3GB in RAM during inference. Server has ~7.6GB available.
   - What's unclear: Exact peak RAM when processing a full document with many chunks through 32K token context window.
   - Recommendation: Monitor memory during first indexing run. Process documents one at a time. Kill model after indexing is done.

3. **INT8 vs float32 vector quality**
   - What we know: pplx-embed natively produces INT8. TEI with `--dtype float32` produces float32. sqlite-vec stores float32.
   - What's unclear: Whether float32 TEI output and in-process int8-to-float32 conversion produce identical vectors for the same input.
   - Recommendation: Use float32 everywhere (TEI `--dtype float32`, in-process convert to float32). Consistency matters more than storage savings at this scale.

4. **Multilingual (Russian) performance of 0.6B model**
   - What we know: pplx-embed-4B scored 68.2% on MIRACL Russian (vs E5-large no data). pplx-embed-0.6B scored 68.6% avg across 18 MIRACL languages. The corpus is primarily Russian voicenotes.
   - What's unclear: Exact Russian-specific score for the 0.6B variant.
   - Recommendation: This is exactly what the A/B comparison will determine empirically on the real corpus. Trust the data, not the benchmarks.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker | TEI container | Yes | 27.5.1 | -- |
| TEI | Query model serving | Yes (needs upgrade) | cpu-1.6 -> need cpu-1.9.3 | -- |
| Python 3.12 | In-process context model | Yes | 3.12+ (in dotmd container) | -- |
| transformers | AutoModel loading | Needs install | Not in current deps | Add to pyproject.toml |
| torch | transformers backend | Needs install | Must be <2.5 | Add to pyproject.toml |
| RAM (~4GB free during indexing) | Context model loading | Yes (~7.6GB available) | -- | Process docs one at a time |
| sqlite-vec | Vector storage (1024-dim) | Yes | >=0.1.6 | -- |

**Missing dependencies with no fallback:**
- TEI must be upgraded from cpu-1.6 to cpu-1.9.3 (Qwen3 support)
- `transformers` and `torch<2.5` must be added to backend dependencies

**Missing dependencies with fallback:**
- None

## Sources

### Primary (HIGH confidence)
- [HuggingFace pplx-embed-v1-0.6B model card](https://huggingface.co/perplexity-ai/pplx-embed-v1-0.6b) - architecture, TEI serving, code examples, no-prefix design
- [HuggingFace pplx-embed-context-v1-0.6B model card](https://huggingface.co/perplexity-ai/pplx-embed-context-v1-0.6b) - grouped input format, context-aware encoding, trust_remote_code
- [TEI GitHub releases](https://github.com/huggingface/text-embeddings-inference/releases) - v1.9.2 added pplx-embed support, v1.9.3 current stable
- [TEI GitHub issue #667](https://github.com/huggingface/text-embeddings-inference/issues/667) - Qwen3 CPU support confirmed in v1.7.4+
- [Perplexity contextualized embeddings docs](https://docs.perplexity.ai/docs/embeddings/contextualized-embeddings) - API format, query-as-single-element-list pattern
- Current codebase: `SemanticSearchEngine`, `IndexingPipeline`, `sqlite_vec.py` -- existing E5 integration points

### Secondary (MEDIUM confidence)
- [arxiv 2602.11151](https://arxiv.org/abs/2602.11151) - SLERP merge of context + triplet checkpoints, MIRACL benchmarks
- [Karan Prasad blog](https://karanprasad.com/blog/perplexity-pplx-embed-context-aware-embeddings-rag) - two-model RAG architecture, ~1.2GB model size
- [The Decoder](https://the-decoder.com/perplexity-open-sources-embedding-models-that-match-google-and-alibaba-at-a-fraction-of-the-memory-cost/) - memory cost comparison

### Tertiary (LOW confidence)
- Cross-model vector space compatibility (asymmetric retrieval) - multiple blog sources agree but official docs suggest using same model for both sides. Needs empirical validation.

## Metadata

**Confidence breakdown:**
- Standard stack: MEDIUM - TEI v1.9.3 for pplx-embed-v1 is well-documented. In-process context model is less battle-tested for CPU serving.
- Architecture: MEDIUM - Two-model hybrid approach is the only viable option given TEI's flat-input limitation. The cross-model compatibility question introduces uncertainty.
- Pitfalls: HIGH - Well-understood from E5 migration experience, TEI version requirements, and memory constraints.

**Research date:** 2026-03-30
**Valid until:** 2026-04-30 (stable models, unlikely to change rapidly)
