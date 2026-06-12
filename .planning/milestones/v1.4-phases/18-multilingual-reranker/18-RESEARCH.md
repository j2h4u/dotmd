# Phase 18: Multilingual Reranker - Research

**Researched:** 2026-05-01  
**Mode:** External benchmark and deployment-fit research. No local quality eval set.  
**Backlog source:** 999.20  
**Confidence:** MEDIUM-HIGH for model shortlist and production fit; MEDIUM for exact latency until technical smoke.

## Executive Decision

Do **not** build a local dotMD benchmark harness or curated eval set in this phase. The user explicitly wants to rely on public benchmark work available by May 2026.

Recommended implementation path for dotMD:

1. **Selected first implementation target:** `Qwen/Qwen3-Reranker-0.6B`, with a technical serving/latency spike before production default.
2. **Fresh secondary candidate:** `Qwen/Qwen3-VL-Reranker-2B`, only if we accept a heavier multimodal stack for text search.
3. **Rejected-for-default ops fallback:** `Alibaba-NLP/gte-multilingual-reranker-base` through TEI `/rerank`.

Reason: low integration risk does not compensate for stale reranker quality. GTE remains useful evidence and possibly an emergency fallback because it is TEI-friendly, but by May 2026 it is too old to be the recommended direction. Among the fresh leaders, Qwen3-Reranker-0.6B, Jina v3, and ContextualAI rerank-v2 appear close enough in expected quality for dotMD that operational fit decides the first attempt. Qwen3-Reranker-0.6B wins because it is text-only, 0.6B, fresh enough, has strong multilingual public benchmark numbers, and is documented through `SentenceTransformers` `CrossEncoder`. Its serving risk must be handled as an implementation spike, not used as a reason to default to an older model.

Freshness rule: publication age is a hard gate for default selection. For Phase 18, models older than roughly 12-15 months can be retained only as fallback or comparison evidence, not as the primary recommendation, unless there is no viable fresher self-hosted candidate.

Qwen 3.6 check: I found Qwen3.6 base/chat model releases in April 2026, but no official Qwen3.6 reranker series as of May 1, 2026. The fresh Qwen reranker family that does exist is `Qwen3-VL-Reranker-2B/8B`, published January 2026. It is Apache-2.0 and supports text reranking, but it is built on Qwen3-VL, starts at 2B parameters, and brings multimodal dependencies; that makes it a serious candidate for research, not an automatic CPU-first default.

## Scoring Criteria For dotMD

| Criterion | Weight | Why it matters here |
|---|---:|---|
| Publication recency / maintenance | HARD GATE | Reranker quality moves quickly; old models cannot win default selection just because they are easy to run. |
| Russian / multilingual quality evidence | 40% | Main failure is Russian/mixed-language degradation. |
| Operational fit | 25% | Existing production shape is external TEI + CPU-only, but this cannot override the freshness gate. |
| Implementation risk | 25% | A fresh model may need a spike; implementation risk changes the rollout shape, not the model-quality decision. |
| Score semantics | 5% | Current `score >= 0` floor and empty-rerank behavior must be fixed or made explicit. |
| License | 0% / metadata only | This is a personal-use project; license must be shown in the table, but it does not affect scoring or default selection. |

Adjustment rules for dotMD-specific fit:

- **Multimodality bonus:** 0. dotMD currently reranks markdown text chunks, so image/video/screenshot support should not increase attractiveness.
- **Unneeded VL stack penalty:** mild negative. A VL stack is extra dependency/runtime surface for no current product benefit, but it should not fully disqualify a fresh Apache candidate if the text-reranking signal is strong.
- **Text-only simplicity bonus:** small positive when quality and recency are otherwise comparable.

## Ranked Candidate Matrix

| Rank | Candidate | Published | Age at May 2026 | Attractiveness | Pros | Cons / risks | Verdict |
|---:|---|---|---:|---:|---|---|---|
| 1 | `Qwen/Qwen3-Reranker-0.6B` | Jun 2025 | ~11 months | 7.8/10 | License: Apache-2.0; 0.6B; 32K context; 100+ languages; official Qwen table: MTEB-R 65.80, MMTEB-R 66.36, MLDR 67.28, MTEB-Code 73.42, ahead of GTE/BGE in most listed columns; model card now shows SentenceTransformers `CrossEncoder` usage. | Not TEI-native in the same straightforward sequence-classification way; TEI issue history says Qwen3 rerank support required core changes; MTEB PR discussion noted reproducibility/implementation difficulty; Qwen docs require newer transformers; CPU latency/memory risk. | **Best age-aware text reranker candidate**, but needs a serving/latency spike before production default. |
| 2 | `ContextualAI/ctxl-rerank-v2-instruct-multilingual-*` | Aug 2025 | ~8 months | 7.5/10 | License: CC-BY-NC-SA-4.0; strong current benchmark claims; instruction-following reranker; 100+ languages; claims to match Qwen3 on MIRACL hard negatives and sit on cost/performance Pareto frontier; HF card includes `text-embeddings-inference` tag. | 1B/2B/6B family is heavier than Qwen3 0.6B; less straightforward as a minimal CPU-first integration; license is noted but not scored for personal use. | **Serious alternate leader** now that license is metadata-only. |
| 3 | `jinaai/jina-reranker-v3` | Oct 2025 | ~7 months | 7.2/10 | License: CC-BY-NC-4.0; strong claimed benchmark table: BEIR 61.94, MIRACL 66.83, MKQA 67.92, CoIR 70.64; listwise architecture; 0.6B; multilingual; fresh serious candidate. | Custom/listwise serving path may be more work than Qwen CrossEncoder; license is noted but not scored for personal use. | **Strong quality alternate**, especially if Qwen integration is poor. |
| 4 | `Qwen/Qwen3-VL-Reranker-2B` / `8B` | Jan 2026 | ~4 months | 7.1/10 | License: Apache-2.0; fresh Qwen reranker family; supports text reranking; 32K context; 30+ languages; model card reports MMTEB retrieval 70.0 for 2B and 74.9 for 8B; SentenceTransformers usage documented. | Minimum official size is 2B, much heavier than Qwen3 0.6B/GTE; Qwen3-VL dependencies (`transformers>=4.57`, `qwen-vl-utils`, newer torch) are intrusive for dotMD; multimodality adds no current value for markdown text reranking and receives no score bonus. | **Fresh but overkill** for current text-only dotMD reranking. |
| 5 | `mixedbread-ai/mxbai-rerank-base-v2` / `large-v2` | Mar 2025 family; Jun 2025 model card | ~11-14 months | 7.0/10 | License: Apache-2.0; 100+ languages; long context; claims fast inference; base-v2 0.5B, large-v2 1.5B; code/search relevance focus; standalone Python package. | Public multilingual score in Mixedbread table is not compelling for our Russian-first need; not TEI-native; adds a new library/inference path; large-v2 too heavy for CPU-first production. | Practical fallback, but weaker public multilingual/Russian signal than Qwen/Contextual/Jina. |
| 6 | `naver/xprovence-reranker-bgem3-v2` | Jan 2026 | ~3 months | 5.6/10 | License: CC-BY-NC-ND-4.0; fresh ECIR 2026 multilingual context pruning model; 0.6B; based on BGE-M3; native Russian among 16 training languages and 100+ cross-lingual transfer; provides relevance score plus context pruning. | Optimized for QA context pruning, not plain top-K search reranking; requires `trust_remote_code` and `spacy`; not a general default reranker. | Useful idea/source, but task mismatch keeps it below the main leaders. |
| 7 | `Alibaba-NLP/gte-multilingual-reranker-base` | Jul 2024 | ~22 months | 4.9/10 | Apache-2.0; 306M; 8192 tokens; 70+ languages including Russian; official Hugging Face card documents TEI CPU/GPU `/rerank`; strong GTE table: Avg 67.4, MLDR 78.7, MIRACL 68.5, MKQA 67.2, BEIR 55.4. Fits dotMD's existing TEI-service pattern. | Too old for default selection; low integration risk does not compensate for stale ranking quality; local Python path uses `trust_remote_code`; Qwen table ranks Qwen3-0.6B higher on several retrieval columns. | **Fallback only** if fresh candidates fail technically. |
| 8 | `BAAI/bge-reranker-v2-m3` | Mar 2024 model; Feb 2024 paper family | ~26 months | 4.7/10 | Apache-2.0; strong established multilingual reranker; Russian-specific RusBEIR uses it and shows large gains when added to BM25/mE5/BGE pipelines; direct `AutoModelForSequenceClassification` and FlagEmbedding docs; scores are sigmoid-normalizable. | Too old for default selection; 568M, heavier than GTE; Qwen and GTE tables both show cases where BGE is not top. | Russian-evidence fallback only. |
| 9 | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | Jun 2022 | ~47 months | 3.5/10 | Apache-2.0; multilingual MS MARCO; smaller and likely easiest drop-in CrossEncoder; supports Russian among 15 languages; low implementation risk. | Very old; weaker evidence versus modern GTE/BGE/Qwen/Jina; 512-token family constraints; does not use existing TEI service. | Emergency low-risk fallback only. |
| 10 | `jinaai/jina-reranker-v2-base-multilingual` | Jun 2024 | ~23 months | 3.3/10 | License: CC-BY-NC-4.0; 0.3B; multilingual; historically strong and included in several comparison tables. | Old relative to v3/Qwen/Mixedbread; custom code concerns. | Reject for default due to age. |
| 11 | API-only rerankers: Cohere, Voyage, ZeroEntropy | Various; e.g. Cohere Rerank 3.5 Dec 2024 | varies | 3.0/10 | Good quality/latency possible; some have calibrated scores. | dotMD is self-hosted/private; recurring API dependency and data egress are not aligned with current architecture. | Out of scope unless user changes hosting/privacy constraints. |

## Evidence Notes

### GTE multilingual reranker

The official model card says `gte-multilingual-reranker-base` is encoder-only, 306M params, 8192 max input tokens, supports 70+ languages, and documents TEI CPU/GPU deployment with `/rerank`. The model has `text-embeddings-inference` tagging and Apache-2.0 license.

The GTE reranker PDF/table reports:

| Model | Params | Seq len | Avg | MLDR | MIRACL | MKQA | BEIR |
|---|---:|---:|---:|---:|---:|---:|---:|
| Dense only | 304M | 8192 | 58.9 | 56.6 | 62.1 | 65.8 | 50.9 |
| Jina v2 multilingual | 278M | 8192 | 59.4 | 53.2 | 65.8 | 68.8 | 49.7 |
| BGE v2 M3 | 568M | 8192 | 65.7 | 66.8 | 72.6 | 68.7 | 54.6 |
| GTE multilingual reranker | 304M | 8192 | 67.4 | 78.7 | 68.5 | 67.2 | 55.4 |

This is vendor evidence, and it directly compares the most relevant original backlog candidates. It supports GTE as a fallback with good historical evidence, but not as the primary May 2026 direction because it fails the freshness gate.

### BGE reranker v2 M3

The BGE docs describe `bge-reranker-v2-m3` as a multilingual reranker with fast inference and provide `FlagReranker` and transformers usage. RusBEIR specifically uses BGE reranker as the reranker and shows large Russian IR gains:

- BM25 average NDCG@10: 52.16
- BM25 + BGE reranker: 59.87
- mE5-large: 60.12
- mE5-large + BGE reranker: 65.71
- BGE-M3: 61.13
- BGE-M3 + BGE reranker: 65.85

This is the strongest Russian-specific evidence among the older candidates found. It keeps BGE as fallback/comparison evidence, but its age prevents it from being a default recommendation.

### Qwen3 reranker

Qwen's official table is strong:

| Model | Params | MTEB-R | CMTEB-R | MMTEB-R | MLDR | MTEB-Code | FollowIR |
|---|---:|---:|---:|---:|---:|---:|---:|
| GTE multilingual reranker | 0.3B | 59.51 | 74.08 | 59.44 | 66.33 | 54.18 | -1.64 |
| BGE reranker v2 M3 | 0.6B | 57.03 | 72.16 | 58.36 | 59.51 | 41.38 | -0.01 |
| Qwen3-Reranker-0.6B | 0.6B | 65.80 | 71.31 | 66.36 | 67.28 | 73.42 | 5.41 |

But this evidence is not enough to make Qwen the first production default in dotMD:

- The model is LLM-style reranking, not a classic sequence-classification reranker.
- TEI issue history indicates Qwen3 reranker support was non-trivial and still moving in 2026.
- MTEB PR discussion noted implementation/reproducibility problems and that Qwen's scores are tied to a specific retrieved top-100 setup.
- Our production is CPU-only, so Qwen has real serving and latency risk; that risk should trigger a spike, not push us back to a stale default.

Qwen is no longer just a vague later watchlist item after adding publication age. `Qwen3-Reranker-0.6B` is the best age-aware Apache text reranker candidate, while `Qwen3-VL-Reranker-2B/8B` is the freshest official Qwen reranker family found. The VL family should not be ignored, but it is heavier and more intrusive than the 0.6B text reranker for dotMD's CPU-first markdown search.

## Implementation Decision

The implementation plan should now target Qwen3 0.6B first:

1. Implement the least intrusive `Qwen/Qwen3-Reranker-0.6B` local `CrossEncoder` path first.
2. If Qwen integration or latency fails, try `jinaai/jina-reranker-v3`.
3. If instruction-following/recency-aware ranking becomes important, try `ContextualAI/ctxl-rerank-v2-instruct-multilingual-1b`.
4. Keep GTE/BGE as old fallback/comparison evidence only.

Shared implementation requirements either way:

1. Add config for reranker backend/model/url; do not bake old model assumptions into search code.
2. Preserve in-process CrossEncoder as fallback/legacy path if useful.
3. Fix score-floor behavior: no hard `score >= 0` should erase fused results. If reranker returns no surviving candidates, fall back to fused ranking.
4. Tests should mock HTTP/CrossEncoder boundaries; no model downloads or local quality eval harness.
5. Optional smoke: call the selected serving path with a tiny Russian pair after service is configured.

## Out Of Scope

- Local quality benchmark harness.
- Curated eval set.
- Model bake-off implementation.
- Local model bake-off between GTE/Qwen/Mixedbread.
- Jina v2 implementation; it is too old for default selection.

## Sources

- TEI repository and supported reranker docs: https://github.com/huggingface/text-embeddings-inference
- GTE model card: https://huggingface.co/Alibaba-NLP/gte-multilingual-reranker-base
- GTE/mGTE paper: https://arxiv.org/abs/2407.19669
- GTE reranker benchmark PDF: https://huggingface.co/Alibaba-NLP/gte-multilingual-base/resolve/087a024525fd6e2fe749cb4679d218d8bcc95bdd/images/mgte-reranker.pdf?download=true
- BGE model card: https://huggingface.co/BAAI/bge-reranker-v2-m3
- BGE docs: https://bge-model.com/bge/bge_reranker_v2.html
- BGE M3 paper: https://arxiv.org/abs/2402.03216
- RusBEIR paper: https://arxiv.org/abs/2504.12879
- RusBEIR repo: https://github.com/kaengreg/rusbeir
- Qwen model card: https://huggingface.co/Qwen/Qwen3-Reranker-0.6B
- Qwen blog: https://qwenlm.github.io/blog/qwen3-embedding
- Qwen MTEB integration discussion: https://github.com/embeddings-benchmark/mteb/issues/3958/linked_closing_reference?reference_location=REPO_ISSUES_INDEX
- Qwen TEI support issue: https://github.com/huggingface/text-embeddings-inference/issues/691
- Qwen3-VL reranker model card: https://huggingface.co/Qwen/Qwen3-VL-Reranker-8B
- Qwen3-VL reranker paper: https://arxiv.org/abs/2601.04720
- Mixedbread v2 release: https://www.mixedbread.com/blog/mxbai-rerank-v2
- Mixedbread reranker repo: https://github.com/mixedbread-ai/mxbai-rerank
- Contextual AI Reranker v2 release: https://contextual.ai/blog/rerank-v2
- Contextual AI Reranker v2 model card: https://huggingface.co/ContextualAI/ctxl-rerank-v2-instruct-multilingual-6b
- Jina v3 model card: https://huggingface.co/jinaai/jina-reranker-v3
- Jina v3 paper: https://arxiv.org/abs/2509.25085
- XProvence model card: https://huggingface.co/naver/xprovence-reranker-bgem3-v2
- XProvence paper: https://arxiv.org/abs/2601.18886
- Cohere Rerank 3.5 changelog: https://docs.cohere.com/v2/changelog/rerank-v3.5
