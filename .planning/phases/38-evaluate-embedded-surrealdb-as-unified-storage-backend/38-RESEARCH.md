# Phase 38: evaluate-embedded-surrealdb-as-unified-storage-backend - Research

**Researched:** 2026-06-12 [VERIFIED: live system date]
**Domain:** Embedded multi-model database evaluation for dotMD storage unification [VERIFIED: codebase grep]
**Confidence:** MEDIUM [CITED:https://surrealdb.com/docs/languages/python] [VERIFIED: codebase grep]

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
**Goal**

Decide whether embedded SurrealDB can replace the current SQLite/sqlite-vec/FTS5
plus FalkorDB storage split with one embedded database. [VERIFIED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-CONTEXT.md]

**Key Constraint**

Prefer migration over recomputation wherever technically safe. The spike must
measure how much existing production state can be moved into SurrealDB without
CPU-heavy rechunking, reembedding, or NER/entity re-extraction. [VERIFIED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-CONTEXT.md]

Current data to evaluate:
- SQLite `index.db`: chunks, metadata, FTS/source state, fingerprints, source
  documents, bindings, cursors/checkpoints, sqlite-vec vector rows. [VERIFIED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-CONTEXT.md]
- FalkorDB graph: File, Section, Entity, Tag nodes and relations. [VERIFIED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-CONTEXT.md]
- SQLite `feedback.db`: agent feedback. [VERIFIED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-CONTEXT.md]

**Decision Output**

The phase should end with one explicit recommendation: migrate, defer, or reject
SurrealDB. If migration is recommended, include a migration path and fallback
plan. [VERIFIED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-CONTEXT.md]

### the agent's Discretion
None provided in `38-CONTEXT.md`. [VERIFIED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-CONTEXT.md]

### Deferred Ideas (OUT OF SCOPE)
None provided in `38-CONTEXT.md`. [VERIFIED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-CONTEXT.md]
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| STOR-01 | dotMD can model its current persistent data in embedded SurrealDB: documents, source units, chunks, embeddings, entities, relations, feedback, cursors, and checkpoints. [VERIFIED: .planning/REQUIREMENTS.md] | Runtime inventory, target schema guidance, and migration matrix below identify which current stores map directly, which require transform-only import, and which stay separate during the spike. [VERIFIED: codebase grep] [CITED:https://surrealdb.com/docs/languages/python/concepts/connecting-to-surrealdb] |
| STOR-02 | The SurrealDB prototype can execute the retrieval paths dotMD depends on: full-text, vector, graph-direct entity retrieval, and hybrid/RRF fusion. [VERIFIED: .planning/REQUIREMENTS.md] | Standard stack, architecture patterns, and pitfalls sections map SurrealDB FTS/vector/graph features against dotMD’s exact retrieval contracts and call out the parity gaps that must be measured. [CITED:https://surrealdb.com/docs/reference/query-language/statements/define/indexes] [CITED:https://surrealdb.com/docs/learn/data-models/vector-search/hybrid-search] [VERIFIED: codebase grep] |
| STOR-03 | The spike measures how much current production data can be migrated from SQLite/sqlite-vec/FalkorDB without CPU-heavy rechunking, reembedding, or re-extraction. [VERIFIED: .planning/REQUIREMENTS.md] | Runtime inventory, live counts, and migration feasibility tables identify transform-only paths for chunks, provenance, bindings, vectors, graph edges, and feedback, and isolate the cases that may still require rebuilds. [VERIFIED: live sqlite inventory] [VERIFIED: docker inspect] [VERIFIED: codebase grep] |
| STOR-04 | The spike produces a recommendation to migrate, defer, or reject SurrealDB, including operational notes for backup/restore, locking/concurrency, and rollback. [VERIFIED: .planning/REQUIREMENTS.md] | Summary, operational notes, environment availability, security domain, and open questions define the evidence gates needed before a migrate recommendation is acceptable. [CITED:https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery] [CITED:https://surrealdb.com/docs/languages/python/concepts/embedded-databases] |
</phase_requirements>

## Project Constraints (from AGENTS.md)

- Work on `main`; this repo’s default and active branch is `main`. [VERIFIED: AGENTS.md]
- Treat dotMD as a standalone product, not as an upstream-fork compatibility surface. [VERIFIED: AGENTS.md]
- Preserve the current source-registry/lifecycle/search contracts; new storage must fit those boundaries instead of bypassing `api/service.py`. [VERIFIED: AGENTS.md]
- New storage backends must implement the protocol from `storage/base.py`. [VERIFIED: AGENTS.md]
- Never reload indexes per request; startup-loaded state must be reused. [VERIFIED: AGENTS.md]
- Never run `dotmd index --force` while the container is running because trickle holds the `fcntl.flock` lock. [VERIFIED: AGENTS.md]
- Never restart production on small changes; batch changes and deploy once. [VERIFIED: AGENTS.md]
- Production `DOTMD_DATA_DIR` is locked to `/mnt`; plans must not narrow it. [VERIFIED: AGENTS.md]
- Feedback storage must be accessed via `dotmd feedback ...`, not by querying `feedback.db` directly. [VERIFIED: AGENTS.md]

## Summary

Plan Phase 38 as a **decision spike with a default posture of `defer unless parity is proven`**, not as a migration implementation phase. SurrealDB’s current official Python docs do confirm embedded on-disk operation through `file://` and `surrealkv://`, built-in full-text search, vector indexes, graph relations, and hybrid search helpers, so the unification idea is technically plausible. The same docs also show important caveats for dotMD: embedded Python connections do not support sessions, client-side transactions, or live queries, SurrealDB full-text indexes are single-field per index, and HNSW assumes enough RAM for its in-memory graph. [CITED:https://surrealdb.com/docs/languages/python/concepts/connecting-to-surrealdb] [CITED:https://surrealdb.com/docs/languages/python/concepts/embedded-databases] [CITED:https://surrealdb.com/docs/learn/data-models/full-text-search/search-indexes] [CITED:https://surrealdb.com/docs/learn/data-models/vector-search/vector-indexes]

dotMD’s current production state is materially richer than “SQLite plus a graph DB” shorthand suggests. Live inspection shows a 2.4 GB `index.db`, separate `feedback.db`, an active `indexing.lock`, current contextual chunk state, dormant heading-strategy tables, embedding and extraction caches, provenance and binding state, and a live FalkorDB graph with about 28.7k `Entity` nodes, 23.9k `Section` nodes, 1.1k `File` nodes, 274 `Tag` nodes, and 353.7k edges. That means the spike must be designed around **copied production snapshots and transform-only imports**, not greenfield schemas or toy fixtures. [VERIFIED: live sqlite inventory] [VERIFIED: docker inspect] [VERIFIED: live FalkorDB inventory]

The highest-value plan is therefore: keep SQLite/FalkorDB as read-only source-of-truth inputs, build a thin Surreal-backed prototype that reuses current chunk IDs, provenance, fingerprints, vectors, and graph entities wherever possible, and gate any “migrate” recommendation behind parity checks for FTS behavior, vector recall, bounded graph-direct retrieval, backup/restore, and single-writer safety. If those gates fail or require meaningful CPU recomputation, the correct recommendation is `defer` or `reject`, not “migrate anyway and reindex later.” [VERIFIED: codebase grep] [CITED:https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery] [CITED:https://surrealdb.com/docs/reference/query-language/language-primitives/transactions]

**Primary recommendation:** Plan this phase as a transform-first prototype on a copied production snapshot, with success defined as retrieval parity plus rollback-safe operations; otherwise end the phase with `defer`. [VERIFIED: live sqlite inventory] [CITED:https://surrealdb.com/docs/languages/python/concepts/embedded-databases]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Production snapshot extraction from `index.db`, `feedback.db`, and FalkorDB | Database / Storage [VERIFIED: codebase grep] | API / Backend [VERIFIED: codebase grep] | The source-of-truth artifacts live in SQLite volumes and FalkorDB, while Python migration code only orchestrates reads and transforms. [VERIFIED: live sqlite inventory] [VERIFIED: live FalkorDB inventory] |
| Surreal target schema for documents, chunks, relations, and state | Database / Storage [CITED:https://surrealdb.com/docs/reference/query-language/statements/define/indexes] | API / Backend [VERIFIED: codebase grep] | The core design problem is data modeling and indexing, with backend code adapting protocol implementations to that model. [CITED:https://surrealdb.com/docs/learn/data-models/graph/knowledge-graph-patterns] |
| Transform-only migration of existing rows and vectors | API / Backend [VERIFIED: codebase grep] | Database / Storage [VERIFIED: live sqlite inventory] | The planner needs Python-side ETL tasks that preserve existing identifiers and embeddings while writing into Surreal records and indexes. [VERIFIED: codebase grep] |
| Retrieval parity testing for FTS, vector, graph-direct, and fusion | API / Backend [VERIFIED: codebase grep] | Database / Storage [CITED:https://surrealdb.com/docs/learn/data-models/vector-search/hybrid-search] | dotMD’s public search contracts live in the backend service, but the parity question depends on storage/index behavior under SurrealQL. [VERIFIED: codebase grep] |
| Backup, restore, rollback rehearsal, and single-writer safety | Database / Storage [CITED:https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery] | API / Backend [VERIFIED: AGENTS.md] | The operational risk is at datastore level, while backend code only supplies migration and smoke-check entry points. [VERIFIED: docker inspect] |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `surrealdb` [WARNING: flagged as suspicious — verify before using.] | `2.0.0` [CITED:https://surrealdb.com/docs/languages/python] | Official Python SDK for embedded (`mem://`, `file://`, `surrealkv://`) and remote SurrealDB access. [CITED:https://surrealdb.com/docs/languages/python/concepts/connecting-to-surrealdb] | This is the documented Python entry point for the exact repo language and supports the embedded URL schemes the phase is evaluating. [CITED:https://surrealdb.com/docs/languages/python/concepts/connecting-to-surrealdb] |
| Embedded SurrealDB datastore via `surrealkv://` | SDK-documented compatibility window `v2.0.0` to `v3.1.4` [CITED:https://surrealdb.com/docs/languages/python] | Primary spike target for an on-disk embedded single-store prototype. [CITED:https://surrealdb.com/docs/languages/python/concepts/connecting-to-surrealdb] | Official Python docs document `surrealkv://` as the on-disk embedded path, which aligns with the “no extra server process” question of this phase. [CITED:https://surrealdb.com/docs/languages/python/concepts/connecting-to-surrealdb] |
| Existing dotMD SQLite + FalkorDB readers | Current repo implementation [VERIFIED: codebase grep] | Read-only source adapters for transform-first migration tests. [VERIFIED: codebase grep] | The spike must measure migration of existing production state, so the current readers remain part of the standard stack even if Surreal is the target. [VERIFIED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-CONTEXT.md] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `surreal` CLI | Pin to the engine version under test [ASSUMED] | Logical export/import, backup rehearsal, and non-embedded operational checks. [CITED:https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery] | Use for backup/restore drills or if the spike needs a WebSocket/HTTP fallback to test features not available on embedded Python connections. [CITED:https://surrealdb.com/docs/reference/cli/surrealdb-cli/commands/start] |
| SurrealQL `search::rrf()` / `search::linear()` | Built-in database functions [CITED:https://surrealdb.com/docs/reference/query-language/functions/database-functions/search] | Native hybrid fusion experiments. [CITED:https://surrealdb.com/docs/learn/data-models/vector-search/hybrid-search] | Use only after measuring parity against dotMD’s current app-side fusion; do not assume native fusion is equivalent without tests. [VERIFIED: codebase grep] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Embedded `surrealkv://` as the primary prototype path [CITED:https://surrealdb.com/docs/languages/python/concepts/connecting-to-surrealdb] | WebSocket-backed single-node SurrealDB started with `surreal start` [CITED:https://surrealdb.com/docs/reference/cli/surrealdb-cli/commands/start] | WebSocket mode gives session and client-side transaction APIs, but it stops being an “embedded backend” evaluation and adds an operational layer the phase is explicitly trying to eliminate. [CITED:https://surrealdb.com/docs/languages/python/api/core/surreal-transaction] |
| Native Surreal hybrid fusion [CITED:https://surrealdb.com/docs/learn/data-models/vector-search/hybrid-search] | Keep current application-side RRF during the spike [VERIFIED: codebase grep] | Reusing current fusion logic reduces parity noise; native Surreal fusion is worth testing only after FTS and vector lists individually match expectations. [VERIFIED: codebase grep] |
| Surreal-only FTS weighting [CITED:https://surrealdb.com/docs/learn/data-models/full-text-search/search-indexes] | Denormalized `search_text` field or multiple field-specific indexes plus app-side weighting [ASSUMED] | dotMD’s current title/tags/body weighting does not map 1:1 because Surreal full-text indexes are single-field per index. [CITED:https://surrealdb.com/docs/learn/data-models/full-text-search/search-indexes] |

**Installation:**
```bash
cd backend
uv add surrealdb
```

**Version verification:** Official docs list `pip install surrealdb`, and the current docs identify SDK `2.0.0`; local host `pip` is absent, so this research verified the package version via PyPI metadata plus official docs instead of `pip index versions`. [CITED:https://surrealdb.com/docs/languages/python/installation] [CITED:https://surrealdb.com/docs/languages/python] [VERIFIED: PyPI JSON metadata] [VERIFIED: local env probe]

## Package Legitimacy Audit

> Required because this phase is likely to install at least one new Python dependency during the spike. [VERIFIED: codebase grep]

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `surrealdb` | PyPI [VERIFIED: PyPI JSON metadata] | ~50 days as current `2.0.0` release on 2026-04-23 [VERIFIED: PyPI JSON metadata] | unknown [VERIFIED: package-legitimacy check] | `github.com/surrealdb/surrealdb.py` [VERIFIED: PyPI JSON metadata] | `SUS` [VERIFIED: package-legitimacy check] | Flagged — planner must add `checkpoint:human-verify` before install. [VERIFIED: package-legitimacy check] |

**Packages removed due to [SLOP] verdict:** none [VERIFIED: package-legitimacy check]
**Packages flagged as suspicious [SUS]:** `surrealdb` [VERIFIED: package-legitimacy check]

*Packages discovered via official docs but failing the legitimacy gate are still treated as install-time risks; this one is not slop, but the planner should require explicit human verification before adding it to the repo environment.* [CITED:https://surrealdb.com/docs/languages/python/installation] [VERIFIED: package-legitimacy check]

## Architecture Patterns

### System Architecture Diagram

```text
Current production snapshot
  ├─ index.db (chunks, M2M holders, FTS5, vec_meta/vec0, caches, bindings, checkpoints)
  ├─ FalkorDB graph (File/Section/Entity/Tag + REL edges)
  └─ feedback surface (via `dotmd feedback ...`)
            │
            ▼
Snapshot copier / read-only extractors
  ├─ SQLite readers decode rows and sqlite-vec metadata
  ├─ Vector transformer decodes stored embeddings without TEI
  ├─ Graph exporter maps Falkor nodes/edges to target records
  └─ Feedback exporter reads via CLI-supported interface
            │
            ▼
Surreal prototype writer
  ├─ records: source docs, units, chunks, feedback, checkpoints
  ├─ relation tables: file↔section, section↔entity, section↔tag
  ├─ full-text indexes on chosen searchable fields
  └─ vector indexes on imported embedding arrays
            │
            ├─ parity path A: app-side dotMD search adapters
            ├─ parity path B: Surreal-native FTS/vector/hybrid helpers
            └─ ops path: backup/export/import/rollback rehearsal
            ▼
Decision gate
  ├─ migrate only if parity + transform-only migration + rollback safety pass
  └─ otherwise defer or reject
```

### Recommended Project Structure

```text
backend/
├── src/dotmd/storage/                 # Existing storage protocols and current backends
├── src/dotmd/storage/surreal_*.py     # New Surreal-backed protocol implementations
├── src/dotmd/ingestion/migrate_surreal.py
│                                       # Snapshot readers + transform-only import helpers
├── tests/storage/test_surreal_*.py    # Storage contract and parity tests
├── tests/ingestion/test_surreal_*.py  # Migration + rollback tests
└── tests/search/test_surreal_*.py     # Retrieval parity tests
```

### Pattern 1: Treat Surreal as a Target Backend Behind Existing Protocols
**What:** Implement a Surreal-backed `MetadataStoreProtocol`, `VectorStoreProtocol`, and `GraphStoreProtocol` without changing `api/service.py` contracts first. [VERIFIED: AGENTS.md] [VERIFIED: codebase grep]
**When to use:** Immediately for the spike’s first plan wave. [VERIFIED: .planning/ROADMAP.md]
**Example:**
```python
# Source: official SurrealDB Python docs + dotMD storage protocol
from surrealdb import Surreal

db = Surreal("surrealkv://./surreal-spike")
db.connect()
db.use("dotmd", "phase38")

# The spike should wrap this behind dotMD protocol adapters,
# not call it directly from api/service.py.
```

### Pattern 2: Import Existing Vectors as Data, Not as New Embedding Jobs
**What:** Read existing chunk IDs and embedding state from current SQLite/sqlite-vec storage, transform them into Surreal numeric arrays, and index them without TEI calls. [VERIFIED: codebase grep]
**When to use:** For every migration-feasibility measurement tied to STOR-03. [VERIFIED: .planning/REQUIREMENTS.md]
**Example:**
```python
# Source: dotMD sqlite-vec serializer + Surreal vector index docs
chunk_id = "..."
embedding = decode_existing_sqlite_vec_blob(blob)  # transform-only, no TEI
db.create(f"chunk:{chunk_id}", {"embedding": embedding})
db.query(
    "DEFINE INDEX chunk_embedding ON TABLE chunk FIELDS embedding HNSW DIMENSION $dim DIST COSINE",
    {"dim": len(embedding)},
)
```

### Pattern 3: Keep Graph-Direct Semantics Bounded
**What:** Reproduce dotMD’s current “entity catalog + bounded Section→Entity/Tag→Section traversal” behavior instead of switching to generic recursive graph search. [VERIFIED: codebase grep]
**When to use:** Before interpreting any graph-direct parity result. [VERIFIED: backend/tests/storage/test_falkordb_graph.py]
**Example:**
```surql
-- Source: official RELATE / knowledge-graph docs, adapted to dotMD semantics
DEFINE TABLE mentions TYPE RELATION IN section OUT entity;
DEFINE TABLE has_tag TYPE RELATION IN section OUT tag;

SELECT <-mentions<-section AS hit_sections
FROM ONLY entity:some_name;
```

### Anti-Patterns to Avoid

- **Reindexing as a shortcut:** The phase goal explicitly prioritizes migration over CPU-heavy rechunking, reembedding, or re-extraction; a plan that defaults to TEI or GLiNER recomputation has already missed the core invariant. [VERIFIED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-CONTEXT.md]
- **Collapsing FTS parity into “it has full-text search”:** Surreal full-text is real, but the single-field index rule makes current title/tags/body weighting a design problem, not a check-box. [CITED:https://surrealdb.com/docs/learn/data-models/full-text-search/search-indexes]
- **Assuming embedded operational parity from remote docs:** Embedded Python lacks sessions and client-side transaction handles, so plans must explicitly test the remaining atomicity and backup workflows they rely on. [CITED:https://surrealdb.com/docs/languages/python/concepts/embedded-databases]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Full-text tokenization and ranking | Custom Python tokenizer + BM25 layer inside dotMD [ASSUMED] | Surreal `DEFINE ANALYZER` + `FULLTEXT ANALYZER` + `BM25` + `search::score()` [CITED:https://surrealdb.com/docs/reference/query-language/statements/define/analyzer] [CITED:https://surrealdb.com/docs/reference/query-language/statements/define/indexes] | Surreal already ships analyzers, tokenizers, stemming, scoring, and highlighting; hand-rolling would add parity bugs the spike is supposed to measure away. [CITED:https://surrealdb.com/docs/reference/query-language/functions/database-functions/search] |
| ANN index maintenance | Custom HNSW bookkeeping in Python [ASSUMED] | Surreal HNSW or DISKANN indexes [CITED:https://surrealdb.com/docs/learn/data-models/vector-search/vector-indexes] | ANN correctness and tuning edge cases are already hard; the spike should evaluate Surreal’s built-ins, not replace them. [CITED:https://surrealdb.com/docs/learn/data-models/vector-search/vector-indexes] |
| Graph edge storage | JSON adjacency lists inside document rows [ASSUMED] | First-class Surreal relation tables via `RELATE` [CITED:https://surrealdb.com/docs/reference/query-language/statements/relate] | dotMD’s current graph uses queryable typed edges; collapsing that into inline arrays would lose traversal semantics and metadata-on-edge support. [VERIFIED: codebase grep] |
| Backup format | Ad-hoc JSON dumps [ASSUMED] | `surreal export` / `surreal import` SurrealQL backups [CITED:https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery] | Backup, diff, and restore are already defined operationally by Surreal’s tooling. [CITED:https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery] |

**Key insight:** The spike’s job is to evaluate whether Surreal’s built-ins are good enough to replace the current split stack while preserving existing data, not to design a new bespoke search engine inside Surreal. [CITED:https://surrealdb.com/docs/what-is-surrealdb] [VERIFIED: .planning/ROADMAP.md]

## Runtime State Inventory

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | Live `index.db` at `/var/lib/docker/volumes/dotmd_dotmd-index/_data/index.db` is about 2.4 GB and contains `chunks_contextual_512_50` (149,739 rows), `vec_meta_contextual_512_50_multilingual_e5_large` (149,739 rows), `vec_components_contextual_512_50_multilingual_e5_large` (156,842 rows), `chunks_fts_contextual_512_50` (150,396 rows), `source_documents` (1,421 rows), `resource_bindings` (1,523 rows; 1,519 active / 4 inactive), `source_unit_fingerprints` (143,975 rows), caches, and legacy `migration_v16_*` tables. `feedback` is a separate CLI-managed surface with 5 rows, all `done`. FalkorDB graph `dotmd` currently holds about 53,929 nodes and 353,700 edges. [VERIFIED: live sqlite inventory] [VERIFIED: dotmd feedback CLI] [VERIFIED: live FalkorDB inventory] | Plan separate tasks for snapshot copy, transform-only import, and post-import parity counts. Do **not** treat this as a single file swap. Data migration is required; code edits alone are insufficient. [VERIFIED: live sqlite inventory] |
| Live service config | Running production container `dotmd` is healthy and mounts `/dotmd-index` from the `dotmd_dotmd-index` volume, `/mnt` from host binds, and `/app/src/dotmd` from the repo bind mount. Live env keys confirm current storage-related config includes `DOTMD_INDEX_DIR`, `DOTMD_GRAPH_BACKEND=falkordb`, `DOTMD_FALKORDB_URL`, `DOTMD_DATA_DIR=/mnt`, and TEI settings. [VERIFIED: docker ps] [VERIFIED: docker inspect] | If the spike graduates to migration, production config will need a coordinated backend switch and likely new SurrealDB path/connection settings. That is live-service config work, not just repo code edits. [VERIFIED: docker inspect] |
| OS-registered state | `indexing.lock` exists inside the live index volume, and AGENTS documents `fcntl.flock` as the single-writer protection for the current trickle/index flow. No systemd/launchd-specific registrations were found in-repo for dotMD itself. [VERIFIED: live sqlite inventory] [VERIFIED: AGENTS.md] | The plan must include a single-writer/concurrency proof for embedded SurrealDB and a stop-the-writer or snapshot discipline during migration rehearsals. If no equivalent lock story is proven, recommend `defer`. [CITED:https://surrealdb.com/docs/languages/python/concepts/embedded-databases] [VERIFIED: AGENTS.md] |
| Secrets/env vars | The running container carries storage and connector env vars, including Surreal-relevant future config points (`DOTMD_GRAPH_BACKEND`, `DOTMD_INDEX_DIR`) and existing secrets for Gmail/OAuth. Values should be treated as sensitive and redacted in planning artifacts. [VERIFIED: docker inspect] | Code edits alone will not rotate or rename secret material. If Surreal adds new credentials or endpoints, plan an env/config rollout task and secret-handling review. [VERIFIED: docker inspect] |
| Build artifacts | The live volume also contains `oauth_state.json`, logs, current WAL/SHM sidecars, and cached model volumes. The repo bind-mount means Python source changes affect the running container on restart without rebuilding the image, while `pyproject.toml` or `start.sh` changes still require rebuild/restart per AGENTS. [VERIFIED: live sqlite inventory] [VERIFIED: AGENTS.md] | Plan snapshot/rehearsal work so build artifacts and WAL files are copied consistently. If the spike adds dependencies, the container image/runtime environment must be updated in a batched deployment step. [VERIFIED: live sqlite inventory] [VERIFIED: AGENTS.md] |

## Common Pitfalls

### Pitfall 1: Assuming Embedded Python Gives Full Remote Feature Parity
**What goes wrong:** The planner assumes transaction handles, sessions, and other remote behaviors are equally available on an embedded `surrealkv://` connection. [CITED:https://surrealdb.com/docs/languages/python/concepts/embedded-databases]
**Why it happens:** The SDK supports embedded URLs, but the feature matrix is narrower than WebSocket connections. [CITED:https://surrealdb.com/docs/languages/python/api/core/surreal-transaction] [CITED:https://surrealdb.com/docs/languages/python/api/core/surreal-session]
**How to avoid:** Make “embedded transaction/atomicity proof” an explicit spike task and allow a WebSocket fallback only as a comparison/control path, not as silent scope creep. [CITED:https://surrealdb.com/docs/languages/python/concepts/embedded-databases]
**Warning signs:** Early spike tasks start depending on `.new_session()` or `.begin_transaction()` helpers, or the team quietly shifts to a server-backed prototype. [CITED:https://surrealdb.com/docs/languages/python/api/core/surreal-session]

### Pitfall 2: Treating FTS Feature Presence as FTS Parity
**What goes wrong:** The team marks STOR-02 complete because Surreal can do full-text search, then later discovers title/tag/body weighting or query behavior changed materially. [CITED:https://surrealdb.com/docs/learn/data-models/full-text-search/search-indexes]
**Why it happens:** dotMD currently indexes text, title, and tags together inside one FTS5 surface with fixed column weights, while Surreal full-text indexes are single-field per index. [VERIFIED: codebase grep] [CITED:https://surrealdb.com/docs/learn/data-models/full-text-search/search-indexes]
**How to avoid:** Define parity fixtures that compare the current result set against Surreal using the exact same corpus and queries before deciding on final schema shape. [VERIFIED: codebase grep]
**Warning signs:** The prototype uses a denormalized text blob without measuring loss of title/tag weighting, or it skips Russian/compound-word test cases entirely. [VERIFIED: codebase grep] [CITED:https://surrealdb.com/docs/reference/query-language/statements/define/analyzer]

### Pitfall 3: Re-Embedding Because the Import Path Was Under-Specified
**What goes wrong:** The spike falls back to TEI and turns into a multi-day CPU job, violating the core invariant. [VERIFIED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-CONTEXT.md]
**Why it happens:** sqlite-vec rows are not stored as human-readable arrays; they need a deliberate transform path from current metadata/blob structures into Surreal numeric arrays. [VERIFIED: codebase grep]
**How to avoid:** Start from the current serializer, row IDs, `chunk_id`, `text_hash`, and model metadata, and require a transform-only proof before any TEI fallback is allowed. [VERIFIED: codebase grep]
**Warning signs:** The plan proposes `dotmd reindex vectors`, TEI calls, or “temporary” re-embedding to simplify the prototype. [VERIFIED: codebase grep] [VERIFIED: AGENTS.md]

### Pitfall 4: Losing Graph-Direct Semantics While “Simplifying” the Graph Model
**What goes wrong:** Surreal relation tables are created, but graph-direct retrieval quality drops because the current bounded entity/section logic was not recreated. [VERIFIED: codebase grep]
**Why it happens:** dotMD does not use arbitrary graph traversal for ranking; it uses a loaded entity catalog and bounded queries/tests aimed at Section↔Entity/Tag behavior. [VERIFIED: codebase grep] [VERIFIED: backend/tests/storage/test_falkordb_graph.py]
**How to avoid:** Preserve entity catalog loading and bounded relation traversal as explicit parity tasks, not optional polish. [VERIFIED: codebase grep]
**Warning signs:** Prototype queries switch to generic multi-hop traversal or skip current entity-catalog behavior because “Surreal is already graph-native.” [CITED:https://surrealdb.com/docs/learn/data-models/graph/knowledge-graph-patterns]

### Pitfall 5: Underplanning Rollback and Writer Coordination
**What goes wrong:** A spike proves happy-path inserts, but no safe return path exists if production parity or performance fails. [CITED:https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery]
**Why it happens:** Current production state spans two stores, a CLI-managed feedback surface, lock files, and live bind-mounted code. [VERIFIED: docker inspect] [VERIFIED: AGENTS.md]
**How to avoid:** Make copied snapshot creation, Surreal export/import rehearsal, and back-to-current rollback drills first-class tasks before any production switch recommendation. [CITED:https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery]
**Warning signs:** The plan says “rollback = keep the old volume” without proving export integrity, record counts, or application smoke queries. [CITED:https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery]

## Code Examples

Verified patterns from official sources:

### Embedded Python Connection
```python
# Source: https://surrealdb.com/docs/languages/python/concepts/connecting-to-surrealdb
from surrealdb import Surreal

db = Surreal("surrealkv://./surreal-spike")
db.connect()
db.use("dotmd", "phase38")
```

### Full-Text Analyzer and Single-Field Index
```surql
-- Source: https://surrealdb.com/docs/reference/query-language/statements/define/analyzer
-- Source: https://surrealdb.com/docs/learn/data-models/full-text-search/search-indexes
DEFINE ANALYZER dotmd_text TOKENIZERS class, punct FILTERS lowercase, ascii;

DEFINE INDEX chunk_search
  ON TABLE chunk
  FIELDS search_text
  FULLTEXT ANALYZER dotmd_text
  BM25
  HIGHLIGHTS;
```

### Vector Index and Hybrid Fusion
```surql
-- Source: https://surrealdb.com/docs/reference/query-language/functions/database-functions/search
DEFINE INDEX chunk_embedding
  ON TABLE chunk
  FIELDS embedding
  HNSW DIMENSION 1024 DIST COSINE;

LET $vec = [/* imported embedding */];
LET $vs = SELECT id FROM chunk WHERE embedding <|10,100|> $vec;
LET $ft = SELECT id, search::score(1) AS score
          FROM chunk
          WHERE search_text @1@ 'graph'
          ORDER BY score DESC
          LIMIT 10;

RETURN search::rrf([$vs, $ft], 10, 60);
```

### Graph Relation Tables
```surql
-- Source: https://surrealdb.com/docs/reference/query-language/statements/relate
DEFINE TABLE mentions TYPE RELATION IN section OUT entity;
DEFINE TABLE has_tag TYPE RELATION IN section OUT tag;

RELATE section:chunk_a->mentions->entity:alice SET weight = 1.0;
RELATE section:chunk_a->has_tag->tag:release_notes;
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `SEARCH ANALYZER` syntax for full-text indexes [CITED:https://surrealdb.com/docs/reference/query-language/statements/define/indexes] | `FULLTEXT ANALYZER` syntax [CITED:https://surrealdb.com/docs/reference/query-language/statements/define/indexes] | Since SurrealDB `3.0.0-beta` docs [CITED:https://surrealdb.com/docs/reference/query-language/statements/define/indexes] | Any prototype must use current `FULLTEXT` syntax and not copy older examples blindly. [CITED:https://surrealdb.com/docs/reference/query-language/statements/define/indexes] |
| MTREE vector indexes [CITED:https://surrealdb.com/docs/build/migrating/from-old-surrealdb-versions/2x-to-3x] | HNSW, with docs also covering DISKANN in `3.1+` [CITED:https://surrealdb.com/docs/learn/data-models/vector-search/vector-indexes] | 2.x to 3.x migration docs [CITED:https://surrealdb.com/docs/build/migrating/from-old-surrealdb-versions/2x-to-3x] | The spike should benchmark on HNSW or DISKANN, not plan around MTREE-era examples. [CITED:https://surrealdb.com/docs/build/migrating/from-old-surrealdb-versions/2x-to-3x] |
| dotMD current split storage: SQLite metadata/FTS5 + sqlite-vec + FalkorDB [VERIFIED: AGENTS.md] | SurrealDB positions unified document, graph, vector, and hybrid search in one engine. [CITED:https://surrealdb.com/docs/what-is-surrealdb] | Current official docs [CITED:https://surrealdb.com/docs/what-is-surrealdb] | This is the core upside being evaluated, but current dotMD parity still has to be demonstrated empirically. [VERIFIED: .planning/ROADMAP.md] |

**Deprecated/outdated:**
- `SEARCH ANALYZER` examples are outdated for current Surreal docs; use `FULLTEXT ANALYZER`. [CITED:https://surrealdb.com/docs/reference/query-language/statements/define/indexes]
- MTREE-based planning is outdated for current Surreal 3.x docs; use HNSW or DISKANN. [CITED:https://surrealdb.com/docs/build/migrating/from-old-surrealdb-versions/2x-to-3x]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Raw `BEGIN` / `COMMIT` SurrealQL queries will be usable enough on embedded Python connections to validate atomic migration behavior, even though client-side transaction handles are unavailable. [ASSUMED] | Summary, Common Pitfalls, Open Questions | If false, the embedded path loses a major operational safety property and the spike may need a server-backed fallback or a `defer` outcome. |
| A2 | dotMD’s current title/tag/body relevance can be approximated acceptably with denormalized `search_text` or multiple Surreal indexes plus app-side weighting. [ASSUMED] | Standard Stack, Common Pitfalls | If false, FTS parity fails even if Surreal “has full-text search,” which could force `reject` or partial retention of SQLite FTS5. |
| A3 | Surreal relation-table queries can meet acceptable latency for dotMD’s current graph-direct workload at about 28.7k entities and 353.7k edges. [ASSUMED] | Summary, Architecture Patterns | If false, the graph half of the unification case breaks and the phase should not recommend migration. |
| A4 | Embedded SurrealKV operational safety for single-writer production use can be proven without a lock mechanism equivalent to the current `fcntl.flock` discipline. [ASSUMED] | Runtime State Inventory, Open Questions | If false, production rollout needs a new locking design or must stay on the current stack. |

## Open Questions (RESOLVED)

1. **Can embedded Python connections support the atomicity dotMD actually needs?**
   - What we know: Embedded Python connections support query/CRUD/auth and explicit embedded URLs, but documented sessions and client-side transactions require WebSocket. [CITED:https://surrealdb.com/docs/languages/python/concepts/connecting-to-surrealdb] [CITED:https://surrealdb.com/docs/languages/python/api/core/surreal-transaction]
   - What's unclear: Whether raw multi-statement `BEGIN` / `COMMIT` via `.query()` is operationally sufficient on embedded `surrealkv://` for migration and purge-style writes. [ASSUMED]
   - Planning resolution: Plan `38-05` is a Wave 2 blocking gate after snapshot inventory and before Surreal schema/import/parity work. It verifies package legitimacy, installs the SDK only after the package checkpoint, probes raw embedded `surrealkv://` commit/rollback behavior, and proves local writer-guard behavior on copied stores. If embedded atomicity or writer safety cannot be proven, downstream schema/import/parity plans are blocked from producing a migrate-ready result. A WebSocket/server-backed run may be recorded only as a control experiment, not as the primary embedded answer. [CITED:https://surrealdb.com/docs/reference/query-language/language-primitives/transactions]

2. **How should current FTS5 weighting map into Surreal’s single-field full-text model?**
   - What we know: Surreal full-text indexes are single-field, while current dotMD FTS5 stores text/title/tags together with weighting logic. [CITED:https://surrealdb.com/docs/learn/data-models/full-text-search/search-indexes] [VERIFIED: codebase grep]
   - What's unclear: Whether denormalized `search_text`, separate indexes, or mixed app-side ranking gives the closest parity on real dotMD queries. [ASSUMED]
   - Planning resolution: Plan `38-03` measures FTS weighting parity as a blocking retrieval gate. The schema/import plan may create candidate searchable fields, but no Surreal search model is considered acceptable until the parity harness compares title/tag/body cases against current FTS5 behavior on the same corpus. FTS top-result or visibility regressions block a migrate recommendation and must be recorded in `38-03-RETRIEVAL-PARITY.md`. [VERIFIED: codebase grep]

3. **Can current sqlite-vec and graph data be imported without CPU recomputation?**
   - What we know: dotMD stores chunk IDs, text hashes, and vector blobs in SQLite, and current graph semantics are explicit File/Section/Entity/Tag nodes with relation metadata. [VERIFIED: codebase grep] [VERIFIED: live sqlite inventory] [VERIFIED: live FalkorDB inventory]
   - What's unclear: The exact Surreal import shape and whether imported vectors/relations preserve recall and latency without hidden rebuilds. [ASSUMED]
   - Planning resolution: Plan `38-02` depends on both the inventory/migration map and the early embedded safety gate. It must prove the import shape from existing SQLite/sqlite-vec/FalkorDB/feedback rows as transform-only data movement before any parity result or recommendation can count as migration evidence. TEI, chunking, and GLiNER/entity-extraction call sites are negative-grep gated out of the import modules; any need for CPU recomputation is recorded as a failed or deferred D-01 category, not silently folded into the migration path. [VERIFIED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-CONTEXT.md]

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Surreal Python SDK spike path | ✓ [VERIFIED: local env probe] | `3.13.5` [VERIFIED: local env probe] | — |
| `uv` | Installing/testing Python deps without system `pip` | ✓ [VERIFIED: local env probe] | `0.11.19` [VERIFIED: local env probe] | — |
| `pip` | Official Surreal install path in docs | ✗ [VERIFIED: local env probe] | — | Use `uv add` / `uv run`; keep docs examples mentally translated. [VERIFIED: local env probe] |
| Docker | Live volume snapshotting and current-store parity tests | ✓ [VERIFIED: local env probe] | `29.5.3` [VERIFIED: local env probe] | — |
| `sqlite3` CLI | Inspecting current `index.db` during the spike | ✓ [VERIFIED: local env probe] | `3.46.1` [VERIFIED: local env probe] | Python stdlib `sqlite3` also works. [VERIFIED: codebase grep] |
| `surreal` CLI | Backup/restore rehearsal and `surreal start` fallback | ✗ [VERIFIED: local env probe] | — | No local fallback for CLI-only flows; planner must add install/provisioning if those tasks are chosen. [CITED:https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery] |
| Rust toolchain | Rust-embedded fallback or direct engine experimentation | ✗ [VERIFIED: local env probe] | — | None on this host; stay on the Python SDK path unless the phase explicitly adds Rust tooling. [VERIFIED: local env probe] |

**Missing dependencies with no fallback:**
- `surreal` CLI for backup/export/import rehearsal on this host. [VERIFIED: local env probe]
- Rust toolchain if the phase pivots away from Python and into direct Rust embedding. [VERIFIED: local env probe]

**Missing dependencies with fallback:**
- System `pip`; `uv` is available and adequate for the Python spike path. [VERIFIED: local env probe]

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `pytest 9.0.3` [VERIFIED: local env probe] |
| Config file | `backend/pyproject.toml` for default suite, plus `backend/tests/e2e/pytest.ini` for e2e. [VERIFIED: codebase grep] |
| Quick run command | `cd backend && uv run pytest tests/storage/test_falkordb_graph.py tests/storage/test_metadata_m2m.py tests/test_hybrid_bm25.py tests/test_vector_delete.py -x` [VERIFIED: codebase grep] |
| Full suite command | `cd backend && uv run pytest` [VERIFIED: codebase grep] |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| STOR-01 | Surreal-backed prototype stores documents, units, chunks, vectors, relations, feedback, and checkpoints with preserved IDs/fingerprints. [VERIFIED: .planning/REQUIREMENTS.md] | integration | `cd backend && uv run pytest tests/storage/test_surreal_storage_contract.py -x` | ❌ Wave 0 |
| STOR-02 | Surreal prototype reproduces dotMD retrieval paths for FTS, vector, graph-direct, and hybrid fusion on the same corpus. [VERIFIED: .planning/REQUIREMENTS.md] | integration/parity | `cd backend && uv run pytest tests/search/test_surreal_retrieval_parity.py -x` | ❌ Wave 0 |
| STOR-03 | Migration path imports current SQLite/sqlite-vec/FalkorDB state without rechunk/reembed/re-extract by default. [VERIFIED: .planning/REQUIREMENTS.md] | integration/migration | `cd backend && uv run pytest tests/ingestion/test_surreal_transform_only_migration.py -x` | ❌ Wave 0 |
| STOR-04 | Backup/restore, rollback, and single-writer safety are rehearsed before any migrate recommendation. [VERIFIED: .planning/REQUIREMENTS.md] | integration/manual-smoke | `cd backend && uv run pytest tests/storage/test_surreal_ops_safety.py -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** run the most local new Surreal-focused test file plus the nearest existing invariant test (`test_hybrid_bm25.py`, `test_vector_delete.py`, or `test_falkordb_graph.py`) affected by that change. [VERIFIED: codebase grep]
- **Per wave merge:** `cd backend && uv run pytest` plus a copied-snapshot smoke on the prototype dataset. [VERIFIED: codebase grep] [ASSUMED]
- **Phase gate:** full suite green plus explicit parity and rollback rehearsal before `$gsd-verify-work`. [VERIFIED: .planning/REQUIREMENTS.md] [ASSUMED]

### Wave 0 Gaps

- [ ] `backend/tests/storage/test_surreal_storage_contract.py` — storage protocol conformance for a Surreal backend. [VERIFIED: codebase grep]
- [ ] `backend/tests/search/test_surreal_retrieval_parity.py` — side-by-side parity checks against current FTS/vector/graph outputs. [VERIFIED: codebase grep]
- [ ] `backend/tests/ingestion/test_surreal_transform_only_migration.py` — prove imported chunks/vectors/graph state do not trigger TEI/GLiNER recomputation. [VERIFIED: codebase grep]
- [ ] `backend/tests/storage/test_surreal_ops_safety.py` — backup/import/rollback and single-writer safety checks. [VERIFIED: codebase grep]

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes [CITED:https://surrealdb.com/docs/languages/python/concepts/authentication] | Use existing secret/env handling for any remote fallback and avoid hardcoding root/database credentials in the prototype. [VERIFIED: docker inspect] |
| V3 Session Management | no for the primary embedded path; yes only for a WebSocket fallback. [CITED:https://surrealdb.com/docs/languages/python/concepts/embedded-databases] | Keep the default spike path session-free; only test session features in explicit fallback tasks. [CITED:https://surrealdb.com/docs/languages/python/api/core/surreal-session] |
| V4 Access Control | yes [CITED:https://surrealdb.com/docs/languages/python/concepts/authentication] | Restrict backup/import and admin operations to controlled local rehearsal environments and explicit credentials. [CITED:https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery] |
| V5 Input Validation | yes [VERIFIED: codebase grep] | Keep migration manifests and configuration shapes behind Pydantic validation and parameterized queries. [VERIFIED: codebase grep] [CITED:https://surrealdb.com/docs/languages/python/concepts/connecting-to-surrealdb] |
| V6 Cryptography | no custom cryptography planned [VERIFIED: codebase grep] | Use built-in auth/token mechanisms only if the phase needs remote Surreal access; never hand-roll token or export encryption logic. [CITED:https://surrealdb.com/docs/languages/python/concepts/authentication] |

### Known Threat Patterns for This Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SurrealQL injection through dynamic string building | Tampering | Use parameter binding and avoid interpolating record IDs, vectors, or search text directly into raw query strings. [CITED:https://surrealdb.com/docs/languages/python/start] |
| Snapshot drift while live writers continue updating SQLite/FalkorDB | Tampering | Copy from a consistent snapshot and keep current writer coordination explicit; do not test migration against a moving target. [VERIFIED: AGENTS.md] [VERIFIED: live sqlite inventory] |
| Secret leakage from container/env inspection | Information Disclosure | Redact env values in docs, logs, and test fixtures; only reference key names and required scopes. [VERIFIED: docker inspect] |
| Partial import or unsafe restore | Tampering / Availability | Rehearse `surreal export` / `surreal import`, then run record counts and application smoke queries before any traffic switch. [CITED:https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery] |
| ANN or FTS parity regressions accepted as “close enough” | Integrity | Require side-by-side parity fixtures on current production-derived corpora before recommending migration. [VERIFIED: codebase grep] |

## Sources

### Primary (HIGH confidence)
- None in this run. Context7 was not available, and official docs fetched via web were classified `MEDIUM` by the research seam. [VERIFIED: classify-confidence output]

### Secondary (MEDIUM confidence)
- https://surrealdb.com/docs/languages/python/concepts/connecting-to-surrealdb - embedded URL schemes, Python connection modes, protocol matrix.
- https://surrealdb.com/docs/languages/python/concepts/embedded-databases - embedded feature limitations.
- https://surrealdb.com/docs/languages/python - SDK version and compatibility window.
- https://surrealdb.com/docs/languages/python/installation - install path for the official Python SDK.
- https://surrealdb.com/docs/reference/query-language/statements/define/analyzer - analyzers, tokenizers, filters, stemming.
- https://surrealdb.com/docs/reference/query-language/statements/define/indexes - index syntax, FULLTEXT, HNSW.
- https://surrealdb.com/docs/learn/data-models/full-text-search/search-indexes - single-field FTS index constraint.
- https://surrealdb.com/docs/learn/data-models/vector-search/vector-indexes - HNSW/DISKANN characteristics and query patterns.
- https://surrealdb.com/docs/reference/query-language/functions/database-functions/search - `search::score`, `search::rrf`, `search::linear`, hybrid examples.
- https://surrealdb.com/docs/reference/query-language/language-primitives/transactions - transaction semantics.
- https://surrealdb.com/docs/reference/query-language/statements/relate - graph relations as separate tables.
- https://surrealdb.com/docs/learn/data-models/graph/knowledge-graph-patterns - records-as-nodes, relations-as-edges.
- https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery - logical backup/restore guidance.

### Tertiary (LOW confidence)
- https://github.com/surrealdb/surrealdb.py - repository/README snippets confirming Python client-side sessions and transactions are WebSocket-only.
- https://github.com/surrealdb/surrealdb/issues/4000 - vector-query edge-case signal for filtered KNN.
- https://github.com/surrealdb/surrealdb/issues/4898 - analyzer parallelization issue signal.
- https://github.com/surrealdb/surrealdb/issues/5841 - FTS index utilization signal.

## Metadata

**Confidence breakdown:**
- Standard stack: MEDIUM - official/current docs are strong, but the package gate flagged `surrealdb` as `SUS` and no live prototype was executed. [CITED:https://surrealdb.com/docs/languages/python] [VERIFIED: package-legitimacy check]
- Architecture: MEDIUM - current dotMD state is well verified from live stores and code, but Surreal mapping parity remains unproven. [VERIFIED: live sqlite inventory] [VERIFIED: codebase grep]
- Pitfalls: MEDIUM - most are directly supported by docs or current code, while a few operational-performance risks still rely on issue history and assumptions. [CITED:https://surrealdb.com/docs/languages/python/concepts/embedded-databases] [ASSUMED]

**Research date:** 2026-06-12 [VERIFIED: live system date]
**Valid until:** 2026-06-19 for SurrealDB feature/release specifics, 2026-07-12 for current dotMD codebase inventory. [ASSUMED]
