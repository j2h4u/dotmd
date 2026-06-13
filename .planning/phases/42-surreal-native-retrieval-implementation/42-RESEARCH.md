# Phase 42: Surreal-native retrieval implementation - Research

**Researched:** 2026-06-14
**Domain:** SurrealDB-native retrieval implementation for dotMD search surfaces. [CITED: .planning/ROADMAP.md] [CITED: .planning/REQUIREMENTS.md]
**Confidence:** MEDIUM

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SURR-SEARCH-01 | SurrealDB full-text search uses real BM25/full-text indexes with weighted title, tags, and body/text contributions. [CITED: .planning/REQUIREMENTS.md] | Use one Surreal full-text index per searchable field, bind each predicate with its own match number, and compose weighted scores in query or application code; do not plan a single multi-column FTS index. [CITED: https://surrealdb.com/docs/learn/data-models/full-text-search/search-indexes] [CITED: https://surrealdb.com/docs/learn/data-models/full-text-search/scoring-and-ranking] [VERIFIED: local embedded Surreal probe] |
| SURR-SEARCH-02 | SurrealDB vector search uses the selected HNSW or DISKANN strategy with production-like build-time and latency evidence. [CITED: .planning/REQUIREMENTS.md] | Plan HNSW as the default implementation path in the current checkout because embedded `surrealdb-2.0.0` accepts HNSW and rejects DISKANN syntax; keep DISKANN behind an explicit runtime-upgrade decision. [CITED: https://surrealdb.com/docs/reference/query-language/statements/define/indexes] [VERIFIED: local embedded Surreal probe] |
| SURR-SEARCH-03 | Graph/entity retrieval runs through Surreal relation records and preserves relation labels, weights, and metadata needed by dotMD search. [CITED: .planning/REQUIREMENTS.md] | Query `TYPE RELATION` rows and arrow traversals directly; do not keep Python-side `scan_table("relations")` loops as the retrieval path. [CITED: https://surrealdb.com/docs/learn/data-models/graph/creating-relations] [CITED: https://surrealdb.com/docs/reference/query-language/statements/relate] [VERIFIED: local embedded Surreal probe] |
| SURR-SEARCH-04 | Hybrid fusion runs over Surreal result sets and produces explainable engine attribution for returned candidates. [CITED: .planning/REQUIREMENTS.md] | Keep fusion in Python over Surreal result sets in Phase 42 because current embedded runtime rejects built-in `search::rrf()` and `search::linear()` even though current docs describe them. [CITED: https://surrealdb.com/docs/reference/query-language/functions/database-functions/search] [CITED: https://surrealdb.com/docs/learn/data-models/vector-search/hybrid-search] [VERIFIED: local embedded Surreal probe] |

## Summary

Phase 42 should replace the Phase 38 prototype retrieval path, not the whole search service. The stable seam is already in the repo: `DotMDService` orchestrates retrieval, each engine implements `SearchEngineProtocol`, fusion already lives in `search/fusion.py`, and Phase 40 already defines the evaluation output shape that later shadow runs will consume. [CITED: backend/src/dotmd/api/service.py] [CITED: backend/src/dotmd/search/base.py] [CITED: backend/src/dotmd/search/fusion.py] [CITED: backend/src/dotmd/search/surreal_eval.py]

The most important planning fact is version skew. Current SurrealDB docs describe `FULLTEXT ANALYZER`, built-in `search::rrf()` / `search::linear()`, and DISKANN with `Available since: v3.1.0`, but the local embedded runtime in this checkout reports `surrealdb-2.0.0`, accepts HNSW and `TYPE RELATION`, accepts old `SEARCH ANALYZER ... BM25` syntax, and rejects `FULLTEXT ANALYZER`, DISKANN, and built-in hybrid helper functions. [CITED: https://surrealdb.com/docs/reference/query-language/statements/define/indexes] [CITED: https://surrealdb.com/docs/reference/query-language/functions/database-functions/search] [VERIFIED: local embedded Surreal probe]

That means the safe plan is: implement real Surreal BM25 with separate field indexes and weighted score composition, implement HNSW-backed vector retrieval, implement graph retrieval via relation queries and traversals, and keep explainable hybrid fusion in Python over Surreal result sets. Do not let Phase 42 silently expand into runtime upgrade, shadow-run, cutover, or legacy removal work. [CITED: .planning/ROADMAP.md] [CITED: .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md] [CITED: docs/surrealdb-production-migration.md]

**Primary recommendation:** Plan Phase 42 around the current embedded runtime: HNSW, old-style `SEARCH ANALYZER` BM25 indexes, relation-backed graph traversal, and Python-side fusion with existing `fuse_results()` attribution. [CITED: backend/src/dotmd/search/fusion.py] [VERIFIED: local embedded Surreal probe]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Weighted full-text retrieval | Database / Storage | API / Backend | Index definition and BM25 scoring belong in SurrealDB; score composition and candidate shaping belong in the backend engine adapter. [CITED: https://surrealdb.com/docs/learn/data-models/full-text-search/search-indexes] [CITED: https://surrealdb.com/docs/learn/data-models/full-text-search/scoring-and-ranking] |
| Vector ANN retrieval | Database / Storage | API / Backend | HNSW query execution belongs in SurrealDB; query embedding generation and result normalization stay in the backend search engine. [CITED: https://surrealdb.com/docs/learn/data-models/vector-search/similarity-search] [CITED: backend/src/dotmd/search/semantic.py] |
| Graph/entity traversal | Database / Storage | API / Backend | Relation records and arrow traversal belong in SurrealDB; entity matching policy and top-k shaping stay in the backend adapter. [CITED: https://surrealdb.com/docs/learn/data-models/graph/creating-relations] [CITED: backend/src/dotmd/search/graph_direct.py] |
| Hybrid fusion and engine attribution | API / Backend | Database / Storage | The current local runtime does not expose verified built-in hybrid helpers, and dotMD already has explainable per-engine attribution in Python. [CITED: backend/src/dotmd/search/fusion.py] [VERIFIED: local embedded Surreal probe] |
| Reranker input shaping | API / Backend | Database / Storage | Candidate refs, snippets, and matched-engine metadata are assembled in Python after retrieval. [CITED: backend/src/dotmd/api/service.py] [CITED: backend/src/dotmd/search/fusion.py] |

## Project Constraints (from AGENTS.md)

- Work in the repository’s established search architecture instead of inventing a parallel runtime surface. Public APIs go through `backend/src/dotmd/api/service.py`. [CITED: AGENTS.md]
- New search behavior should preserve the existing search pipeline shape: query expansion, three peer engines, fusion, then reranking. [CITED: AGENTS.md]
- New search engines should fit behind `SearchEngineProtocol`. [CITED: AGENTS.md] [CITED: backend/src/dotmd/search/base.py]
- Never reload indexes per request; startup-loaded or connection-owned Surreal structures must be reused. [CITED: AGENTS.md]
- Do not plan `dotmd index --force` while the container is running. [CITED: AGENTS.md]
- Do not plan production restart or cutover work inside Phase 42; batch deployment changes later. [CITED: AGENTS.md] [CITED: .planning/ROADMAP.md]
- Treat the old stack as baseline evidence only, not as a compatibility target. [CITED: .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md]
- Keep the production data root assumption unchanged at `/mnt`; do not narrow corpus scope in this phase. [CITED: AGENTS.md]

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `surrealdb` Python SDK / embedded SurrealKV runtime | installed `2.0.0` in repo venv; local embedded runtime reports `surrealdb-2.0.0` [VERIFIED: local env] [VERIFIED: local embedded Surreal probe] | Execute SurrealQL, manage embedded connections, define indexes, and run retrieval queries. | It is already the repo dependency and the only verified local path for real Surreal retrieval in this checkout. It supports HNSW and relation traversal now, but not the newer DISKANN / built-in hybrid surfaces described in current docs. [CITED: backend/pyproject.toml] [VERIFIED: local embedded Surreal probe] |
| `dotmd.search.base.SearchEngineProtocol` | current checkout [CITED: backend/src/dotmd/search/base.py] | Stable interface for full-text, vector, and graph engines. | Phase 42 should swap implementations behind this protocol instead of reshaping `DotMDService`. [CITED: backend/src/dotmd/search/base.py] [CITED: backend/src/dotmd/api/service.py] |
| `dotmd.search.fusion.fuse_results` + `build_candidates` | current checkout [CITED: backend/src/dotmd/search/fusion.py] | Explainable hybrid fusion and candidate hydration. | Existing code already carries engine attribution and public result shaping; keeping it avoids depending on unverified embedded-runtime hybrid helpers. [CITED: backend/src/dotmd/search/fusion.py] [VERIFIED: local embedded Surreal probe] |
| `dotmd.storage.surreal` + `dotmd.storage.surreal_schema` | current checkout [CITED: backend/src/dotmd/storage/surreal.py] [CITED: backend/src/dotmd/storage/surreal_schema.py] | Connection management, record-ID safety, and the Phase 41 schema catalog. | Phase 42 should build on the Phase 41 schema instead of inventing a second Surreal shape. [CITED: .planning/phases/41-production-grade-surreal-schema-and-import/41-01-SUMMARY.md] [CITED: .planning/phases/41-production-grade-surreal-schema-and-import/41-02-SUMMARY.md] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `dotmd.search.surreal_contract` | current checkout [CITED: backend/src/dotmd/search/surreal_contract.py] | Canonical retrieval surfaces and difference vocabulary. | Use for naming, acceptance semantics, and test coverage alignment. [CITED: .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md] |
| `dotmd.search.surreal_eval` | current checkout [CITED: backend/src/dotmd/search/surreal_eval.py] | Phase 40 diff-row and gate shape. | Use when designing Phase 42 result capture for later Phase 43 evaluation. [CITED: .planning/phases/40-evaluation-harness-and-golden-queries/40-01-SUMMARY.md] |
| `pytest` | local `9.0.3` [VERIFIED: local env] | Contract and integration testing for new engines. | Use for focused unit/integration gates before Phase 43 shadow runs exist. [CITED: backend/pyproject.toml] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| HNSW on current runtime | DISKANN | Current docs describe DISKANN as available since `v3.1.0`, but the local embedded runtime rejects DISKANN syntax today. [CITED: https://surrealdb.com/docs/reference/query-language/statements/define/indexes] [VERIFIED: local embedded Surreal probe] |
| Python-side fusion over Surreal result sets | Built-in `search::rrf()` / `search::linear()` | Current docs document these helpers, but the local embedded runtime rejects them; existing Python fusion already preserves matched-engine attribution. [CITED: https://surrealdb.com/docs/reference/query-language/functions/database-functions/search] [CITED: backend/src/dotmd/search/fusion.py] [VERIFIED: local embedded Surreal probe] |
| Real indexed Surreal queries | Prototype `scan_table()` loops and in-Python cosine / edge scans | The prototype path is Phase 38 evidence only and does not satisfy the Phase 42 requirement for real Surreal capabilities. [CITED: backend/src/dotmd/storage/surreal.py] [CITED: .planning/ROADMAP.md] |

**Installation:**
```bash
cd /home/j2h4u/repos/j2h4u/dotmd/backend
uv sync --extra dev
```

**Version verification:** The repo venv currently provides `Python 3.12.12`, `surrealdb 2.0.0`, `pytest 9.0.3`, `pydantic 2.13.4`, and `httpx 0.28.1`. The embedded Surreal runtime reports `surrealdb-2.0.0`. [VERIFIED: local env] [VERIFIED: local embedded Surreal probe]

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `surrealdb` | PyPI [VERIFIED: package-legitimacy check] | ~52 days as of 2026-06-14 [VERIFIED: package-legitimacy check] | unknown [VERIFIED: package-legitimacy check] | none signalled by seam [VERIFIED: package-legitimacy check] | `SUS` [VERIFIED: package-legitimacy check] | Existing dependency is already installed locally; if Phase 42 upgrades or reinstalls it, the planner must add `checkpoint:human-verify` first. [VERIFIED: package-legitimacy check] |

**Packages removed due to [SLOP] verdict:** none. [VERIFIED: package-legitimacy check]
**Packages flagged as suspicious [SUS]:** `surrealdb` if the plan introduces an upgrade or fresh install step. [VERIFIED: package-legitimacy check]

## Architecture Patterns

### System Architecture Diagram

```text
user query
   |
   v
DotMDService._collect_candidate_pool()
   |
   +--> Surreal FTS engine --------> Surreal BM25 result rows
   |
   +--> Surreal vector engine -----> Surreal HNSW result rows
   |
   +--> Surreal graph engine ------> Surreal relation/traversal result rows
   |
   v
Python fusion (existing fuse_results + engine attribution)
   |
   v
build_candidates() -> SearchCandidate refs/snippets/matched_engines
   |
   v
optional reranker
```

The service boundary stays in `api/service.py`; Phase 42 should replace engine internals, not the orchestration contract. [CITED: backend/src/dotmd/api/service.py] [CITED: backend/src/dotmd/search/fusion.py]

### Recommended Project Structure

```text
backend/src/dotmd/search/
├── surreal_fts.py        # weighted BM25 query adapter over Surreal
├── surreal_vector.py     # HNSW-backed vector query adapter
├── surreal_graph.py      # relation / traversal-backed graph retrieval
├── fusion.py             # existing explainable RRF stays here
└── surreal_contract.py   # existing phase contract vocabulary
```

This keeps one engine module per retrieval surface and leaves `api/service.py` focused on orchestration. [CITED: backend/src/dotmd/search/base.py] [CITED: backend/src/dotmd/api/service.py]

### Pattern 1: Replace Prototype Table Scans With Surface-Specific Surreal Engines

**What:** Implement one Surreal-backed engine per retrieval surface and keep each one conforming to `SearchEngineProtocol`. [CITED: backend/src/dotmd/search/base.py]

**When to use:** For Phase 42 full-text, vector, and graph surfaces. [CITED: .planning/ROADMAP.md]

**Example:**
```python
# Source: backend/src/dotmd/search/base.py
class SearchEngineProtocol(Protocol):
    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]: ...
```

### Pattern 2: Compose Weighted BM25 From Separate Single-Field Indexes

**What:** Define one full-text index per searchable string field and compose field weights from numbered `search::score(n)` predicates. Separate-field indexes are required because Surreal full-text indexes are single-field only. [CITED: https://surrealdb.com/docs/learn/data-models/full-text-search/search-indexes] [CITED: https://surrealdb.com/docs/learn/data-models/full-text-search/scoring-and-ranking]

**When to use:** For title, tags, and body weighting. [CITED: .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md]

**Example:**
```sql
-- Source pattern: https://surrealdb.com/docs/learn/data-models/full-text-search/scoring-and-ranking
-- dotMD weighting formula is inferred from the official numbered-score pattern. [ASSUMED]
SELECT id,
  (5 * search::score(1)) +
  (3 * search::score(2)) +
  (1 * search::score(3)) AS weighted_score
FROM chunks
WHERE title @1@ $query
   OR tags_text @2@ $query
   OR text @3@ $query
ORDER BY weighted_score DESC
LIMIT $limit;
```

### Pattern 3: Use HNSW Now, Keep DISKANN Upgrade-Gated

**What:** Build the vector engine against HNSW because it is both documented and locally accepted in the embedded runtime. DISKANN should stay behind an explicit upgrade decision because docs mark it `Available since: v3.1.0` and the current embedded runtime rejects its syntax. [CITED: https://surrealdb.com/docs/reference/query-language/statements/define/indexes] [VERIFIED: local embedded Surreal probe]

**When to use:** For the initial Phase 42 implementation path in this checkout. [VERIFIED: local embedded Surreal probe]

**Example:**
```sql
-- Source: https://surrealdb.com/docs/reference/query-language/statements/define/indexes
DEFINE INDEX idx_embedding
  ON TABLE test
  FIELDS embedding
  HNSW DIMENSION 3 DIST COSINE;

SELECT id FROM test WHERE embedding <|10,40|> $qvec;
```

### Pattern 4: Query Graph Relations Directly, Preserve Edge Metadata

**What:** Drive graph/entity retrieval from Surreal relation rows and traversals so `rel_type`, `weight`, and endpoint metadata stay first-class. [CITED: https://surrealdb.com/docs/learn/data-models/graph/creating-relations] [CITED: https://surrealdb.com/docs/reference/query-language/statements/relate]

**When to use:** For both entity-direct retrieval and graph enrichment over sections, entities, and tags. [CITED: .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md]

**Example:**
```sql
-- Source: https://surrealdb.com/docs/learn/data-models/graph/creating-relations
RELATE section:a->mentions->entity:surreal SET weight = 0.7, rel_type = "MENTIONS";
SELECT ->mentions->entity FROM section:a;
```

### Anti-Patterns to Avoid

- **Prototype cosine scan:** Do not keep `SurrealVectorStore.search()` as a Python loop over `scan_table("embeddings")` plus `_cosine_similarity`. That is spike code, not indexed retrieval. [CITED: backend/src/dotmd/storage/surreal.py]
- **Prototype relation scan:** Do not keep `get_chunks_by_entity()` and related graph reads as full-table scans over `relations`. [CITED: backend/src/dotmd/storage/surreal.py]
- **One giant multi-field FTS index:** Surreal full-text indexes are single-field only. [CITED: https://surrealdb.com/docs/learn/data-models/full-text-search/search-indexes]
- **Silent syntax drift:** Do not write `FULLTEXT ANALYZER`, DISKANN, or built-in hybrid helpers into Phase 42 tasks unless the runtime upgrade is an explicit earlier task. [CITED: https://surrealdb.com/docs/reference/query-language/statements/define/indexes] [CITED: https://surrealdb.com/docs/reference/query-language/functions/database-functions/search] [VERIFIED: local embedded Surreal probe]
- **Service rewrite:** Do not collapse Phase 42 into `DotMDService` contract changes; the stable seam is engine replacement. [CITED: backend/src/dotmd/api/service.py]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Lexical scoring | Python token matching or manual BM25 math over chunk text | Surreal full-text indexes plus `search::score(n)` composition | Surreal already provides the index and score primitives, and docs show numbered score binding. [CITED: https://surrealdb.com/docs/learn/data-models/full-text-search/scoring-and-ranking] |
| ANN vector retrieval | `scan_table("embeddings")` with Python cosine similarity | Surreal HNSW index and KNN operator | The local runtime already accepts HNSW; the prototype scan is O(n) and not Phase 42-native. [CITED: https://surrealdb.com/docs/reference/query-language/statements/define/indexes] [VERIFIED: local embedded Surreal probe] |
| Graph edge traversal | Python loops over relation rows | `TYPE RELATION`, `RELATE`, and arrow traversal | Surreal relations are first-class and preserve edge metadata. [CITED: https://surrealdb.com/docs/reference/query-language/statements/relate] |
| Hybrid score normalization | New bespoke hybrid engine format | Existing `fuse_results()` and `build_candidates()` | dotMD already has explainable engine attribution and stable public candidate shaping there. [CITED: backend/src/dotmd/search/fusion.py] |
| Record-ID escaping | Ad hoc string concatenation into Surreal IDs | `SurrealRecordIdCodec` | The repo already centralizes safe record-ID encoding. [CITED: backend/src/dotmd/storage/surreal.py] |

**Key insight:** “Surreal-native” in this phase should mean Surreal-native retrieval surfaces, not “all fusion and orchestration must move into SurrealQL.” Keeping Python-side fusion is the most defensible path under the currently verified runtime. [CITED: .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md] [VERIFIED: local embedded Surreal probe]

## Common Pitfalls

### Pitfall 1: Planning Against Current Docs Instead of Current Runtime

**What goes wrong:** The plan assumes `FULLTEXT ANALYZER`, DISKANN, or built-in hybrid helpers are available immediately. [CITED: https://surrealdb.com/docs/reference/query-language/statements/define/indexes] [CITED: https://surrealdb.com/docs/reference/query-language/functions/database-functions/search]
**Why it happens:** Current docs describe newer 3.x features while the repo’s embedded runtime is still `surrealdb-2.0.0`. [VERIFIED: local embedded Surreal probe]
**How to avoid:** Make runtime compatibility a Wave 0 gate and default the implementation to the locally verified feature set. [VERIFIED: local embedded Surreal probe]
**Warning signs:** Plan tasks mention DISKANN or `search::rrf()` without an earlier upgrade/probe task. [VERIFIED: local embedded Surreal probe]

### Pitfall 2: Trying To Use One FTS Index Across Title, Tags, and Body

**What goes wrong:** The DDL attempts a single multi-column full-text index. [CITED: https://surrealdb.com/docs/learn/data-models/full-text-search/search-indexes]
**Why it happens:** SQLite FTS5 supports multi-column weighting, so it is easy to project that shape onto Surreal. [CITED: backend/src/dotmd/search/fts5.py]
**How to avoid:** Define one searchable field per index and weight scores in query/application code. [CITED: https://surrealdb.com/docs/learn/data-models/full-text-search/scoring-and-ranking]
**Warning signs:** `DEFINE INDEX ... FIELDS title, tags, text ... FULLTEXT ...` appears in the plan. [CITED: https://surrealdb.com/docs/learn/data-models/full-text-search/search-indexes]

### Pitfall 3: Leaving Prototype Full-Table Scans In Place

**What goes wrong:** Phase 42 lands “Surreal” code that still scans all embeddings or all relations in Python. [CITED: backend/src/dotmd/storage/surreal.py]
**Why it happens:** The Phase 38 prototype optimized for proof of import, not native retrieval. [CITED: .planning/ROADMAP.md]
**How to avoid:** Require every engine plan task to include the actual SurrealQL query and the index/traversal it depends on. [CITED: https://surrealdb.com/docs/reference/query-language/statements/define/indexes] [CITED: https://surrealdb.com/docs/reference/query-language/statements/relate]
**Warning signs:** Retrieval methods call `scan_table()` in hot search paths. [CITED: backend/src/dotmd/storage/surreal.py]

### Pitfall 4: Expanding Phase 42 Into Cutover Work

**What goes wrong:** The plan starts adding shadow runs, runtime switching, or legacy deletion. [CITED: .planning/ROADMAP.md]
**Why it happens:** Phase 42 sits in the middle of the cutover milestone and touches retrieval internals. [CITED: .planning/STATE.md]
**How to avoid:** Keep Phase 42 limited to engine implementation plus tests and candidate-output capture needed by later phases. [CITED: .planning/ROADMAP.md] [CITED: .planning/phases/40-evaluation-harness-and-golden-queries/40-01-SUMMARY.md]
**Warning signs:** Tasks mention production container restart, shadow-run ledgers, or deleting SQLite/Falkor code. [CITED: .planning/ROADMAP.md]

## Code Examples

Verified patterns from official sources:

### HNSW Index Definition And Query
```sql
-- Source: https://surrealdb.com/docs/reference/query-language/statements/define/indexes
DEFINE INDEX idx_embedding
  ON TABLE test
  FIELDS embedding
  HNSW DIMENSION 3 DIST COSINE;

SELECT id FROM test WHERE embedding <|10,40|> $qvec;
```

### Relation Row With Edge Metadata
```sql
-- Source: https://surrealdb.com/docs/learn/data-models/graph/creating-relations
RELATE $new_user->wrote->$new_comment SET
  location = "Arizona",
  os = "Windows 11",
  mood = "happy";
```

### Numbered Full-Text Scores
```sql
-- Source: https://surrealdb.com/docs/learn/data-models/full-text-search/scoring-and-ranking
SELECT
  search::score(0) AS text_score,
  search::score(1) AS title_score
FROM article
WHERE text @0@ "night" OR title @1@ "hound";
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `SEARCH ANALYZER` text-index syntax in embedded runtime | `FULLTEXT ANALYZER` documented in current docs, with note “Before SurrealDB version 3.0.0-beta...” | 3.0.0-beta syntax boundary in docs [CITED: https://surrealdb.com/docs/reference/query-language/statements/define/indexes] | Current local runtime still needs the old syntax, so Phase 42 must either target old syntax or explicitly upgrade first. [VERIFIED: local embedded Surreal probe] |
| HNSW only in current local runtime | DISKANN documented as available since `v3.1.0` | 3.1.0 docs boundary [CITED: https://surrealdb.com/docs/reference/query-language/statements/define/indexes] | DISKANN is not a safe default in this checkout. [VERIFIED: local embedded Surreal probe] |
| Python-side hybrid fusion only | Built-in `search::rrf()` / `search::linear()` documented in current docs | current docs [CITED: https://surrealdb.com/docs/reference/query-language/functions/database-functions/search] | Keep Python fusion unless runtime capability changes. [VERIFIED: local embedded Surreal probe] |
| Prototype Python scans over Surreal rows | Indexed FTS/HNSW/traversal retrieval | Phase 42 target [CITED: .planning/ROADMAP.md] | This is the actual implementation delta the planner should decompose. [CITED: backend/src/dotmd/storage/surreal.py] |

**Deprecated/outdated:**
- Phase 38 proxy retrieval in `backend/src/dotmd/storage/surreal.py` is baseline evidence only and should not be treated as the implementation target. [CITED: .planning/ROADMAP.md] [CITED: backend/src/dotmd/storage/surreal.py]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | dotMD will likely need a derived single-string lexical field for tags if the canonical schema keeps tags as structured metadata instead of a directly searchable string field. [ASSUMED] | Architecture Patterns | Weighted tag retrieval may stall on schema shape rather than engine code. |
| A2 | Query-side weighted composition of multiple `search::score(n)` outputs is the intended way to preserve title/tags/body weighting in dotMD. Official docs show numbered scores but do not prescribe this exact formula. [ASSUMED] | Architecture Patterns | The planner may need an early spike if the exact score-composition approach behaves differently than expected. |

## Open Questions

1. **Is a Surreal runtime / SDK upgrade in scope before implementation starts?**
   - What we know: current docs describe 3.x-only surfaces such as DISKANN and newer full-text syntax, while the local embedded runtime is `surrealdb-2.0.0`. [CITED: https://surrealdb.com/docs/reference/query-language/statements/define/indexes] [VERIFIED: local embedded Surreal probe]
   - What's unclear: whether Phase 42 is allowed to upgrade the runtime or must implement on the existing embedded stack. [CITED: .planning/ROADMAP.md]
   - Recommendation: make this the first planner checkpoint; branch the plan into “implement on 2.0 now” vs “upgrade first, then implement.” [VERIFIED: local embedded Surreal probe]

2. **What exact Surreal field should carry tag text for BM25?**
   - What we know: Surreal full-text indexes are single-field, and Phase 42 must preserve weighted tag contribution. [CITED: https://surrealdb.com/docs/learn/data-models/full-text-search/search-indexes] [CITED: .planning/REQUIREMENTS.md]
   - What's unclear: whether tags already land in a searchable string field after Phase 41 import or need a new derived field. [CITED: backend/src/dotmd/storage/surreal_schema.py] [ASSUMED]
   - Recommendation: add a first-wave schema/query-shape task that resolves tag materialization before coding the engine. [ASSUMED]

3. **Should graph entity matching stay Python-side or move fully into Surreal queries?**
   - What we know: current `GraphDirectEngine` loads entity names into memory and matches n-grams in Python before fetching chunk IDs from the graph store. [CITED: backend/src/dotmd/search/graph_direct.py]
   - What's unclear: whether “Surreal-native retrieval” requires moving entity catalog matching itself into Surreal, or only the downstream traversal/result retrieval. [CITED: .planning/ROADMAP.md]
   - Recommendation: keep entity phrase matching policy stable in Python first, then move traversal/result fetch into Surreal; treat full query-side entity matching as optional follow-up unless the planner finds a clear upside. [ASSUMED]

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `uv` | backend dev/test workflow | ✓ [VERIFIED: local env] | `0.11.19` [VERIFIED: local env] | — |
| backend Python runtime | implementation/tests | ✓ [VERIFIED: local env] | `Python 3.12.12` in repo venv [VERIFIED: local env] | — |
| `surrealdb` Python SDK | embedded Surreal queries and local probes | ✓ [VERIFIED: local env] | `2.0.0` [VERIFIED: local env] | — |
| embedded Surreal runtime via SDK | local Phase 42 development path | ✓ [VERIFIED: local embedded Surreal probe] | `surrealdb-2.0.0` [VERIFIED: local embedded Surreal probe] | — |
| Docker | optional container-adjacent verification | ✓ [VERIFIED: local env] | `29.5.3` [VERIFIED: local env] | — |
| `surreal` CLI | export/import or CLI-based capability checks | ✗ [VERIFIED: local env] | — | Use repo-local SDK probes and existing Phase 41 runner surfaces. [CITED: docs/surrealdb-production-migration.md] |
| `ctx7` CLI | context7 docs fallback | ✗ [VERIFIED: local env] | — | Use official SurrealDB docs via web lookup. [CITED: /home/j2h4u/.codex/gsd-core/references/research-documentation-lookup.md] |

**Missing dependencies with no fallback:**
- none identified for planning or local implementation. [VERIFIED: local env]

**Missing dependencies with fallback:**
- `surreal` CLI. Phase 42 can proceed with SDK-backed local probes and query execution. [VERIFIED: local env] [CITED: docs/surrealdb-production-migration.md]
- `ctx7` CLI. Official docs lookup is sufficient for research. [VERIFIED: local env] [CITED: /home/j2h4u/.codex/gsd-core/references/research-documentation-lookup.md]

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `pytest 9.0.3` [VERIFIED: local env] |
| Config file | `backend/pyproject.toml` [CITED: backend/pyproject.toml] |
| Quick run command | `cd backend && uv run pytest tests/search/test_surreal_native_fts.py tests/search/test_surreal_native_vector.py tests/search/test_surreal_native_graph.py tests/search/test_surreal_native_hybrid.py -q` [ASSUMED] |
| Full suite command | `cd backend && just verify` [CITED: justfile] |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SURR-SEARCH-01 | Weighted title/tags/body BM25 query returns expected chunk IDs and score ordering. [CITED: .planning/REQUIREMENTS.md] | unit | `cd backend && uv run pytest tests/search/test_surreal_native_fts.py -q` [ASSUMED] | ❌ Wave 0 |
| SURR-SEARCH-02 | HNSW query path returns top-k chunk IDs from real Surreal index queries, not Python cosine scans. [CITED: .planning/REQUIREMENTS.md] | unit | `cd backend && uv run pytest tests/search/test_surreal_native_vector.py -q` [ASSUMED] | ❌ Wave 0 |
| SURR-SEARCH-03 | Relation-backed graph/entity retrieval preserves `rel_type`, `weight`, and bounded traversal semantics. [CITED: .planning/REQUIREMENTS.md] | unit/integration | `cd backend && uv run pytest tests/search/test_surreal_native_graph.py -q` [ASSUMED] | ❌ Wave 0 |
| SURR-SEARCH-04 | Hybrid fusion over Surreal result sets preserves matched-engine attribution and feeds Phase 40 eval capture shape. [CITED: .planning/REQUIREMENTS.md] | integration | `cd backend && uv run pytest tests/search/test_surreal_native_hybrid.py -q` [ASSUMED] | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `cd backend && uv run pytest <targeted Phase 42 tests> -q` [CITED: justfile] [ASSUMED]
- **Per wave merge:** `cd backend && just unit` [CITED: justfile]
- **Phase gate:** `cd backend && just verify` before `$gsd-verify-work`. [CITED: justfile]

### Wave 0 Gaps

- [ ] `backend/tests/search/test_surreal_native_fts.py` — covers SURR-SEARCH-01. [ASSUMED]
- [ ] `backend/tests/search/test_surreal_native_vector.py` — covers SURR-SEARCH-02. [ASSUMED]
- [ ] `backend/tests/search/test_surreal_native_graph.py` — covers SURR-SEARCH-03. [ASSUMED]
- [ ] `backend/tests/search/test_surreal_native_hybrid.py` — covers SURR-SEARCH-04. [ASSUMED]
- [ ] Shared embedded Surreal fixture for per-test isolated `surrealkv://` databases and query helpers. [ASSUMED]

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no [CITED: .planning/ROADMAP.md] | Phase 42 does not change auth flows. [CITED: .planning/ROADMAP.md] |
| V3 Session Management | no [CITED: .planning/ROADMAP.md] | Phase 42 does not change session handling. [CITED: .planning/ROADMAP.md] |
| V4 Access Control | yes [CITED: backend/src/dotmd/api/service.py] | Preserve active-binding and readable-ref filtering at the service boundary when swapping retrieval engines. [CITED: backend/src/dotmd/api/service.py] |
| V5 Input Validation | yes [CITED: backend/src/dotmd/storage/surreal.py] | Parameterize SurrealQL inputs and keep record shaping behind `SurrealRecordIdCodec`; never let user text shape identifiers. [CITED: backend/src/dotmd/storage/surreal.py] |
| V6 Cryptography | no [CITED: .planning/ROADMAP.md] | No crypto primitives are introduced in this phase. [CITED: .planning/ROADMAP.md] |

### Known Threat Patterns for Surreal-native retrieval

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SurrealQL injection through interpolated query text or identifiers | Tampering | Use query variables for user strings and `SurrealRecordIdCodec` for record IDs; keep schema/table names fixed in code. [CITED: backend/src/dotmd/storage/surreal.py] |
| Leakage of inactive or unreadable refs through new retrieval paths | Information Disclosure | Preserve service-side provenance and active-binding filtering after Surreal engines return chunk IDs. [CITED: backend/src/dotmd/api/service.py] |
| Unbounded graph or ANN queries causing resource spikes | Denial of Service | Keep explicit `top_k`, bounded traversal shape, and HNSW query parameters in each engine. [CITED: backend/src/dotmd/search/graph_direct.py] [CITED: https://surrealdb.com/docs/reference/query-language/language-primitives/operators] |
| Runtime-syntax drift causing accidental fallback to prototype scans | Elevation of Privilege / Tampering | Add explicit startup or Wave 0 capability probes and fail closed when required Surreal features are missing. [VERIFIED: local embedded Surreal probe] |

## Sources

### Primary (HIGH confidence)

- Local embedded Surreal probe run on 2026-06-14 — verified runtime version, accepted HNSW and relation syntax, rejected DISKANN, built-in hybrid helpers, and new full-text syntax. [VERIFIED: local embedded Surreal probe]
- Repo code in `backend/src/dotmd/api/service.py`, `backend/src/dotmd/search/base.py`, `backend/src/dotmd/search/fusion.py`, `backend/src/dotmd/storage/surreal.py`, and `backend/src/dotmd/storage/surreal_schema.py` — verified current architecture seams and prototype limitations. [CITED: backend/src/dotmd/api/service.py] [CITED: backend/src/dotmd/search/base.py] [CITED: backend/src/dotmd/search/fusion.py] [CITED: backend/src/dotmd/storage/surreal.py] [CITED: backend/src/dotmd/storage/surreal_schema.py]

### Secondary (MEDIUM confidence)

- https://surrealdb.com/docs/learn/data-models/full-text-search/search-indexes
- https://surrealdb.com/docs/learn/data-models/full-text-search/scoring-and-ranking
- https://surrealdb.com/docs/reference/query-language/statements/define/indexes
- https://surrealdb.com/docs/reference/query-language/functions/database-functions/search
- https://surrealdb.com/docs/learn/data-models/vector-search/hybrid-search
- https://surrealdb.com/docs/learn/data-models/vector-search/similarity-search
- https://surrealdb.com/docs/learn/data-models/graph/creating-relations
- https://surrealdb.com/docs/reference/query-language/statements/relate

### Tertiary (LOW confidence)

- none. All unverified inferences are listed in the Assumptions Log. [CITED: .planning/REQUIREMENTS.md]

## Metadata

**Confidence breakdown:**
- Standard stack: MEDIUM - repo wiring and local runtime are verified, but docs/runtime version skew leaves upgrade-sensitive features unresolved. [VERIFIED: local embedded Surreal probe]
- Architecture: HIGH - current service/engine/fusion seams are explicit in repo code and prior phase artifacts. [CITED: backend/src/dotmd/api/service.py] [CITED: .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md]
- Pitfalls: HIGH - the major failure modes are directly supported by docs/runtime mismatch and current prototype code. [VERIFIED: local embedded Surreal probe] [CITED: backend/src/dotmd/storage/surreal.py]

**Research date:** 2026-06-14
**Valid until:** 2026-06-21 for runtime-feature assumptions; refresh earlier if the repo upgrades `surrealdb`. [VERIFIED: local env]
