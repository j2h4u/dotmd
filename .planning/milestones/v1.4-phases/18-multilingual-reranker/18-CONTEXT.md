# Phase 18: Multilingual Reranker - Context

**Created:** 2026-05-01
**Workflow:** `$gsd-discuss-phase 18`
**Backlog source:** 999.20

## Phase Goal

Replace or rework the English-oriented reranker so Russian and multilingual searches are not degraded by noisy cross-encoder scores.

## Why This Phase Exists

The current default reranker is `cross-encoder/ms-marco-MiniLM-L-6-v2`, an English-oriented MS MARCO cross-encoder. dotMD then blends normalized reranker scores at 60% weight:

```text
0.4 * norm_fused + 0.6 * norm_re
```

For Russian queries, noisy reranker scores can dominate otherwise good semantic, FTS5, and graph retrieval.

## Locked Decisions

1. **Do not implement a blind model string swap.**
   The phase must compare current reranker options before changing production defaults.

2. **Benchmark before selecting the default.**
   Candidate choice must be based on realistic dotMD search cases: Russian notes, mixed Russian/English technical notes, and exact keyword-heavy queries.

3. **Treat inference architecture as part of the decision.**
   Acceptable tracks are:
   - current in-process `sentence_transformers.CrossEncoder` wrapper;
   - a custom local `transformers`/model-specific wrapper;
   - separate TEI `/rerank` service.

4. **Treat score-floor behavior as in scope.**
   The existing hard floor (`score >= 0`) is tied to the current MS MARCO binary-logit model. Any new model must define whether raw-score filtering is disabled, calibrated, or opt-in.

5. **Production deploy remains batched.**
   Do not restart production for exploratory changes. Benchmark and code work can happen locally/container-side; production restart comes after a final decision and batched deploy.

## Candidate Set To Research

Must include:
- `Qwen/Qwen3-Reranker-0.6B`
- `BAAI/bge-reranker-v2-m3`
- `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`
- `Alibaba-NLP/gte-multilingual-reranker-base`

Should consider but may reject early:
- `jinaai/jina-reranker-v3`
- `jinaai/jina-reranker-v2-base-multilingual`

## Evaluation Criteria

- Russian query quality on local knowledgebase content.
- Mixed-language query quality.
- Keyword-only result survival.
- CPU latency and memory footprint in the current container constraints.
- License suitability.
- Integration risk with current dependency pins (`sentence-transformers`, `transformers<5`, `torch<2.5`).
- Operational fit: no unnecessary new service if a local wrapper is good enough; accept a TEI rerank service only if quality/ops tradeoff is worth it.

## Gray Areas Still Open

1. **Quality vs architecture simplicity.**
   We need benchmark evidence to decide whether a simple CrossEncoder replacement is enough.

2. **Local model vs TEI rerank service.**
   TEI gives a clean service boundary but adds a container and HTTP path.

3. **Reranker floor semantics.**
   The current floor may be harmful for multilingual models; the phase should decide default behavior explicitly.

4. **Benchmark source.**
   Prefer production-like search_log queries if available; otherwise create a small hand-curated Russian/mixed-language fixture.

## Deferred Ideas

- Automatic fusion-weight calibration through the reranker remains backlog 999.15 and is not part of this phase.
- Upgrading `transformers` to 5.x remains backlog 999.19 unless a chosen model makes it unavoidable.
