---
created: 2026-03-30T16:19:44.589Z
title: Evaluate pplx-embed-context as E5-large replacement
area: api
files:
  - backend/src/dotmd/search/semantic.py
  - backend/src/dotmd/ingestion/pipeline.py
  - backend/src/dotmd/core/config.py
---

## Problem

Current E5-large (560M) has fundamental limitations for our voicenote corpus:
- Cosine scores compress into 0.78-0.80 for everything (anisotropy, documented behavior)
- No context awareness: chunk embedding doesn't know what "he" or "as I mentioned" refers to
- Requires "query: "/"passage: " prefixes (brittle, easy to forget)
- Can't distinguish "35 на 65" in a meeting transcript from random technical content

pplx-embed-context-v1-0.6B (Perplexity, Feb 2026) solves these structurally:
- Context-aware: all chunks from a document processed in one forward pass, each chunk embedding sees full document context
- No prefix needed (deliberately avoids instruction tuning)
- SOTA on ConTEB benchmark (81.96% nDCG@10 vs Voyage 79.45%, Anthropic 72.4%)
- MIT license, open weights, 596M params, 1024-dim (same as current E5)
- Self-hosted: transformers, ONNX, or TEI (for query model)
- HuggingFace: https://huggingface.co/perplexity-ai/pplx-embed-context-v1-0.6b

## Solution

Implement in a **separate git branch** for A/B comparison:

1. **Branch setup**: create `feature/pplx-embed` from `dev`
2. **Query model**: replace TEI E5-large with `pplx-embed-v1-0.6B` (standard TEI, drop-in)
3. **Indexing model**: add `pplx-embed-context-v1-0.6B` for document embedding
   - Requires grouped input: all chunks from one document in single forward pass
   - Chunks joined with sep_token, per-chunk mean pooling extracts individual embeddings
   - Can use transformers/ONNX directly (TEI may not support contextual mode)
4. **Remove E5 prefix logic** (pplx-embed doesn't need prefixes)
5. **Reindex**: `dotmd reindex vectors`
6. **A/B test queries**:
   - "распределение прибыли" (semantic concept matching)
   - "hiveon" (exact brand name)
   - "Николай Сенин делить деньги" (entity + topic)
   - "35 на 65" (specific fact in transcript)
   - "trickle indexer" (negative test, should return 0)
7. **Compare** with main branch on same queries
8. **Decision**: merge if significantly better, delete branch if marginal

### Integration changes needed
- `SemanticSearchEngine`: add contextual encoding path (group chunks by file)
- `IndexingPipeline.reindex_vectors()`: batch chunks by source document
- Docker: new container for pplx-embed-context (or Python-based indexer)
- Config: `embedding_model` → detect from TEI /info (already implemented)
