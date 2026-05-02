---
phase: 21
slug: reranker-quality-benchmark
status: verified
threats_open: 0
asvs_level: 1
created: 2026-05-02
---

# Phase 21 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Live dotMD index -> benchmark runner | Developer-only benchmark reads the current production-like index through `DotMDService`; it must not mutate or reindex data. | Markdown-derived chunks, file paths, chunk ids, retrieval metadata |
| Human-approved labels -> benchmark metrics | Label JSONL controls what is treated as relevant evidence for quality scoring. | Query text, label selectors, relevance grades |
| Reranker outputs -> model recommendation | Model-specific rankings and timings are converted into durable benchmark conclusions. | Ranked chunk ids, rank metrics, hot rerank timing |
| Benchmark artifacts -> production registry decision | Documentation guides which reranker remains available in production. | Model names, recommendation, cleanup record |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-21-01 | Tampering / Integrity | Shared candidate pool | mitigate | Runner calls `DotMDService.compare_rerankers()` once per query and records `candidate_pool_chunk_ids` / `shared_pool_size`; `compare_rerankers()` builds one fused pool before per-model reranking. Tests verify model-order restoration and pool-miss handling. | closed |
| T-21-02 | Tampering / Integrity | Label resolution | mitigate | Label resolver fails when `file_path + contains` resolves to zero or multiple chunks; label coverage and approval are recorded before canonical scoring. | closed |
| T-21-03 | Repudiation / Integrity | Russian quality conclusion | mitigate | Benchmark ledger and summary explicitly treat `msmarco-minilm` as a negative historical control and lead with local Russian/mixed-corpus metrics. | closed |
| T-21-04 | Tampering / Availability | Live index | mitigate | Plan forbids `dotmd index --force`; executed commands only used the running `dotmd` container and current `/dotmd-index/index.db`. | closed |
| T-21-05 | Integrity | Cross-model score comparison | mitigate | Summary ranks models by `nDCG@10`, `MRR@10`, `Hit@3`, and p95 hot rerank time; raw cross-encoder scores are documented as diagnostics only. | closed |
| T-21-06 | Availability / Operational risk | Slow reranking | mitigate | Runner records `rerank_ms` and human-readable `rerank`; summaries include p50/p95 hot rerank time beside quality metrics. | closed |
| T-21-07 | Integrity | Relevance labels | mitigate | Canonical scoring required `21-LABELS-REVIEW.md` with `Status: APPROVED`; approval exists for 30 queries before the canonical run. | closed |
| T-21-08 | Integrity | Retrieval misses | mitigate | Runner marks `pool_miss` from the shared candidate pool, excludes pool misses from per-model quality averages, and reports retrieval-gap query ids separately. | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Evidence

| Threat ID | Evidence |
|-----------|----------|
| T-21-01 | `backend/src/dotmd/api/service.py` returns `candidate_pool_chunk_ids` and `shared_pool_size`; `backend/devtools/reranker_quality_bench.py` calls `compare_rerankers()` once per query and restores configured model order for output rows. |
| T-21-02 | `resolve_labels()` and `_resolve_label_object()` raise on unsupported labels or non-unique `file_path + contains` resolution. |
| T-21-03 | `21-BENCHMARKS.md` and `results/2026-05-02-rerank-quality-summary.md` record `msmarco-minilm` as the negative historical control and show local metrics from 30 Russian/mixed queries. |
| T-21-04 | `21-01-quality-benchmark-SUMMARY.md` command list contains no reindex command; canonical run used `docker exec dotmd python /tmp/reranker_quality_bench.py ...`. |
| T-21-05 | `21-BENCHMARKS.md` states raw cross-encoder scores are diagnostics only; `summarize_rows()` sorts by rank metrics and p95 rerank time, not raw model scores. |
| T-21-06 | `make_result_row()` records `rerank_ms` and `rerank`; canonical summary includes p50 and p95 hot rerank columns. |
| T-21-07 | `21-LABELS-REVIEW.md` contains `Status: APPROVED`, `Reviewed by`, and `Query count: 30`; `21-BENCHMARKS.md` records this approval in the canonical run. |
| T-21-08 | `make_result_row()` derives `pool_miss` from `candidate_pool_ids`; `summarize_rows()` excludes pool misses from quality averages; canonical summary lists nine retrieval-gap query ids. |

---

## Accepted Risks Log

No accepted risks.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-05-02 | 8 | 8 | 0 | Codex security auditor |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-05-02
