# Phase 41: Production-grade Surreal schema and import - Research

**Researched:** 2026-06-13
**Domain:** Transform-first SurrealDB migration tooling for dotMD's v1.8 cutover. [CITED: .planning/ROADMAP.md; .planning/REQUIREMENTS.md]
**Confidence:** MEDIUM

## User Constraints

- Stay on the current `milestone/v1.8-surrealdb-cutover` branch for this research run and do not switch branches. [CITED: user request]
- Skip discuss-phase and use existing evidence from Phases 38-40 plus the current prototype code. [CITED: user request]
- Keep the no-fallback, no-compat-shim posture: the old SQLite/sqlite-vec/FTS5 plus FalkorDB stack is migration source and evaluation evidence only. [CITED: user request; .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md]
- Preserve existing chunks, embeddings, refs, graph relations, feedback, cursors, and checkpoints where practical; avoid default rechunking, reembedding, and entity re-extraction. [CITED: user request; .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md; .planning/REQUIREMENTS.md]
- Phase 41 should produce production-grade schema/import planning only; real Surreal retrieval remains Phase 42, shadow-run quality evidence remains Phase 43, runtime cutover remains Phase 44, and legacy deletion remains Phase 45. [CITED: .planning/ROADMAP.md; .planning/REQUIREMENTS.md]

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SURR-MIG-01 | The production Surreal schema represents documents, source units, chunks, embeddings, source refs, file/resource bindings, fingerprints, graph entities/relations, feedback, cursors, and checkpoints. | Use one schema catalog with explicit table ownership, relation-table usage for graph edges, and import boundaries that keep caches and retrieval indexes out of the required success path. [CITED: .planning/REQUIREMENTS.md; .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-01-MIGRATION-MAP.md; https://surrealdb.com/docs/reference/query-language/statements/define/table; https://surrealdb.com/docs/learn/data-models/graph/creating-relations] |
| SURR-MIG-02 | Migration imports existing stored data transform-first wherever practical, avoiding default TEI reembedding, rechunking, and entity re-extraction. | Keep Phase 38's transform-only contract, retain the copied-snapshot plus exporter inputs, and forbid TEI/GLiNER/indexing-pipeline recomputation in the default path. [CITED: .planning/REQUIREMENTS.md; .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-02-IMPORT-PROOF.md; backend/src/dotmd/ingestion/migrate_surreal.py] |
| SURR-MIG-03 | Migration has explicit backup, restore, rollback, and partial-failure semantics before production cutover. | Add reportable dry-run/apply phases, restore-ready manifests, and partial-failure gates now; keep live cutover execution for later phases. [CITED: .planning/REQUIREMENTS.md; .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-04-OPERATIONS.md; https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery; https://surrealdb.com/docs/reference/cli/surrealdb-cli/commands/export; https://surrealdb.com/docs/reference/cli/surrealdb-cli/commands/import] |

## Summary

Phase 41 should harden the existing thin prototype into a migration toolchain, not into a retrieval backend and not into a production cutover. The current repo already has the right evidence chain for this split: Phase 38 proved transform-first coverage and embedded-writer safety, Phase 39 fixed the no-fallback migration posture, and Phase 40 created the evaluation gate that later phases will use against real retrieval behavior. [CITED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-02-IMPORT-PROOF.md; .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-05-EMBEDDED-SAFETY-GATE.md; .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md; .planning/phases/40-evaluation-harness-and-golden-queries/40-RESEARCH.md]

The planning target is a schema-versioned, report-first migration surface that can: snapshot and inventory the old stores, materialize a target schema, dry-run counts and diffs without writes, apply data in explicit phases, verify counts and sample invariants after each phase, and produce rollback/restore evidence without pretending retrieval parity or runtime cutover are solved. The current `run_surreal_import()` prototype is useful as a seed, but its `clear_phase38_tables()` plus replay behavior is still spike-only and must not become the production contract. [CITED: backend/src/dotmd/ingestion/migrate_surreal.py; backend/src/dotmd/storage/surreal.py; .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-RECOMMENDATION.md]

Official SurrealDB docs matter here in two narrow places. First, relation data that needs edge metadata belongs in relation tables, which matches dotMD's need to preserve `rel_type`, `weight`, and edge payloads from Falkor exports. Second, the official backup/restore story is logical `surreal export` and `surreal import` plus rehearsed sanity checks, while the Python SDK's higher-level transaction object is not available on embedded connections, so Phase 41 should prefer batch-scoped import phases and raw SurrealQL transaction blocks over any assumption of one giant embedded SDK transaction. [CITED: https://surrealdb.com/docs/learn/data-models/graph/creating-relations; https://surrealdb.com/docs/reference/query-language/statements/define/table; https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery; https://surrealdb.com/docs/reference/query-language/language-primitives/transactions; https://surrealdb.com/docs/languages/python/concepts/connecting-to-surrealdb; https://surrealdb.com/docs/languages/python/api/core/surreal-transaction]

**Primary recommendation:** Plan Phase 41 around a schema catalog plus `plan -> dry-run -> apply -> verify -> report` migration runner that preserves Phase 38 transform-only inputs, treats old storage as read-only evidence, and defers retrieval, shadow-run, and runtime cutover concerns to Phases 42-45. [CITED: .planning/ROADMAP.md; .planning/REQUIREMENTS.md; backend/src/dotmd/ingestion/migrate_surreal.py]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Snapshot and inventory old SQLite/Falkor/feedback state | Database / Storage | API / Backend | The source of truth is persisted storage plus exporter surfaces, and Phase 38 already captured copied-snapshot discipline here. [CITED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-01-INVENTORY.md; backend/src/dotmd/storage/surreal_inventory.py] |
| Define target Surreal schema and schema version rules | Database / Storage | API / Backend | This is a storage-contract responsibility, not a runtime API concern. [CITED: backend/src/dotmd/storage/surreal.py; https://surrealdb.com/docs/reference/query-language/statements/define/table] |
| Orchestrate dry-run/apply/verify/report migration phases | API / Backend | Database / Storage | The runner owns sequencing, validation, and reporting while calling storage helpers. [CITED: backend/src/dotmd/ingestion/migrate_surreal.py; .planning/REQUIREMENTS.md] |
| Enforce source-preserving boundaries and no-recompute defaults | API / Backend | Database / Storage | The policy lives in migration orchestration and tests, while storage helpers execute the transforms. [CITED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-02-IMPORT-PROOF.md; backend/tests/ingestion/test_surreal_transform_only_migration.py] |
| Backup/restore rehearsal evidence and rollback manifests | Database / Storage | API / Backend | The artifacts describe database recovery state first, then feed later cutover steps. [CITED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-04-OPERATIONS.md; https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery] |

## Project Constraints (from AGENTS.md)

- All public runtime APIs must continue to route through `backend/src/dotmd/api/service.py`; Phase 41 should add migration tooling, not a parallel runtime surface. [CITED: AGENTS.md]
- New storage backends must respect `storage/base.py` protocols, and new search engines must respect `search/base.py` protocols. [CITED: AGENTS.md]
- Never reload indexes per request; Phase 41 should stay out of request-serving paths entirely. [CITED: AGENTS.md]
- Never run `dotmd index --force` while the container is running; Phase 41 must preserve the transform-first, no-reindex default. [CITED: AGENTS.md]
- Never restart production on small changes; Phase 41 should stop at migration tooling and evidence, not live cutover. [CITED: AGENTS.md]
- Production data root stays `/mnt`; migration planning should preserve current ref/document assumptions rather than narrowing the corpus. [CITED: AGENTS.md]
- dotMD production currently runs as a single healthy `dotmd` container backed by Docker volume `dotmd_dotmd-index`. [VERIFIED: docker ps; docker volume ls]

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| repo-local `dotmd.storage.surreal` | current checkout | Thin Surreal connection/store surface to evolve into a schema-owned storage layer. [CITED: backend/src/dotmd/storage/surreal.py] | It already owns the record-ID codec, table list, and replace-style helpers; Phase 41 should harden this surface instead of inventing a second Surreal adapter. [CITED: backend/src/dotmd/storage/surreal.py] |
| repo-local `dotmd.ingestion.migrate_surreal` | current checkout | Existing import runner and transform loaders. [CITED: backend/src/dotmd/ingestion/migrate_surreal.py] | It already encodes dry-run/apply separation and source-preserving loaders, so the planner should refactor and extend it rather than replace it. [CITED: backend/src/dotmd/ingestion/migrate_surreal.py] |
| repo-local `dotmd.storage.surreal_inventory` and `dotmd.storage.surreal_ops` | current checkout | Snapshot, inventory, safety, and restore/report helpers. [CITED: backend/src/dotmd/storage/surreal_inventory.py; backend/src/dotmd/storage/surreal_ops.py] | Phase 41 needs these evidence surfaces promoted from spike helpers into the production migration contract. [CITED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-01-INVENTORY.md; .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-04-OPERATIONS.md] |
| `surrealdb` [WARNING: flagged as suspicious - verify before using.] | local env `2.0.0`; docs state latest SDK `2.0.0`. [CITED: backend/pyproject.toml; https://surrealdb.com/docs/languages/python; https://pypi.org/project/surrealdb/] | Python SDK for embedded `surrealkv://` and remote ws/http connections. [CITED: https://surrealdb.com/docs/languages/python/concepts/connecting-to-surrealdb] | The repo already depends on it and local `uv run` resolves `2.0.0`, but the package-legitimacy seam flagged the PyPI package `SUS`, so any fresh install should be human-verified. [VERIFIED: importlib.metadata version; VERIFIED: package-legitimacy check] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest` | local env `9.0.3`. [VERIFIED: uv run pytest --version] | Migration regression tests. [CITED: backend/pyproject.toml] | Use for all Phase 41 schema/import/report tests and keep the existing repo test stack. [CITED: backend/pyproject.toml] |
| Docker `dotmd` container | host Docker `29.5.3`; container healthy. [VERIFIED: docker --version; VERIFIED: docker ps] | Read-only runtime evidence source for live inventory assumptions. [CITED: AGENTS.md] | Use for read-only environment confirmation only; do not turn Phase 41 into a production restart phase. [CITED: AGENTS.md] |
| official `surreal export` / `surreal import` CLI | docs current; CLI missing on host and in container. [CITED: https://surrealdb.com/docs/reference/cli/surrealdb-cli/commands/export; https://surrealdb.com/docs/reference/cli/surrealdb-cli/commands/import; VERIFIED: command -v surreal; VERIFIED: docker exec dotmd command -v surreal] | Logical backup and restore path. [CITED: https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery] | Use for later restore/cutover rehearsals or explicit install tasks; do not block Phase 41 development on local CLI presence. [CITED: https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hardening the existing repo-local migration runner | Replacing it with a new CLI/import pipeline from scratch | The current repo already has transform loaders, safety-gate hooks, and fixture coverage; replacement would discard the verified Phase 38 evidence surface. [CITED: backend/src/dotmd/ingestion/migrate_surreal.py; backend/tests/ingestion/test_surreal_transform_only_migration.py] |
| One migration-specific relation table strategy that preserves `rel_type` and edge payloads | Collapsing graph edges into plain linked arrays on document or entity records | That would lose graph metadata and make Phase 42 traversal work harder. Surreal relation tables exist specifically for metadata-carrying edges. [CITED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-01-INVENTORY.md; https://surrealdb.com/docs/learn/data-models/graph/creating-relations] |
| SDK-driven batch apply plus explicit manifests now | Making Phase 41 depend on local `surreal import` CLI availability | The official CLI is the right restore path, but it is not installed here today, while the repo already has a working SDK-based apply path to harden. [CITED: backend/src/dotmd/ingestion/migrate_surreal.py; VERIFIED: command -v surreal] |

**Installation:**
```bash
cd /home/j2h4u/repos/j2h4u/dotmd/backend
uv sync --extra dev
```

**Version verification:** `backend/pyproject.toml` declares `surrealdb>=2.0.0`, local `uv run` resolves `surrealdb 2.0.0`, and SurrealDB's current Python SDK docs also state SDK version `2.0.0`. [CITED: backend/pyproject.toml; VERIFIED: importlib.metadata version; https://surrealdb.com/docs/languages/python]

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `surrealdb` | PyPI | First release Sep 17, 2022; current `2.0.0` released Apr 23, 2026. [CITED: https://pypi.org/project/surrealdb/] | unknown | official docs and PyPI link to `surrealdb/surrealdb.py`. [CITED: https://surrealdb.com/docs/languages/python; https://pypi.org/project/surrealdb/] | `SUS`. [VERIFIED: package-legitimacy check] | Existing dependency only; if a fresh install is needed, planner must add `checkpoint:human-verify` before installation. [VERIFIED: package-legitimacy check] |

**Packages removed due to `SLOP` verdict:** none.
**Packages flagged as suspicious `SUS`:** `surrealdb` - add `checkpoint:human-verify` before any fresh install. [VERIFIED: package-legitimacy check]

## Architecture Patterns

### System Architecture Diagram

```text
copied SQLite snapshot + Falkor exporter + feedback provider
                     |
                     v
            migration plan builder
                     |
         +-----------+-----------+
         |                       |
         v                       v
     dry-run report       apply phase runner
         |                       |
         |                phase-scoped Surreal writes
         |                       |
         v                       v
 count/diff manifest ----> verify counts + invariants
         |                       |
         +-----------+-----------+
                     |
                     v
         migration report + restore manifest
                     |
                     v
   later consumers: Phase 42 retrieval, Phase 43 shadow-run, Phase 44 cutover
```

The migration runner should consume stable source artifacts and emit stable evidence artifacts; it should not own retrieval semantics or runtime service switching. [CITED: .planning/ROADMAP.md; backend/src/dotmd/ingestion/migrate_surreal.py]

### Recommended Project Structure

```text
backend/
├── src/dotmd/storage/
│   ├── surreal.py                 # low-level connection/store helpers
│   ├── surreal_schema.py          # canonical schema DDL + schema version
│   ├── surreal_inventory.py       # source inventory + copied-snapshot helpers
│   └── surreal_ops.py             # restore/rollback/report helpers
├── src/dotmd/ingestion/
│   └── migrate_surreal.py         # plan/dry-run/apply/verify/report orchestration
└── tests/
    ├── ingestion/test_surreal_production_migration.py
    └── storage/test_surreal_schema_definition.py
```

This keeps storage DDL separate from orchestration and gives Phase 41 a clean place to add schema versioning without bloating the runtime-facing service layer. [CITED: backend/src/dotmd/storage/surreal.py; backend/src/dotmd/ingestion/migrate_surreal.py]

### Pattern 1: Schema Catalog, Not Prototype Table List

**What:** Replace the prototype's blanket `SCHEMALESS` table declarations with a canonical schema catalog that declares which tables are `SCHEMAFULL`, which are `TYPE RELATION`, and which fields/indexes are part of the migration contract. [CITED: backend/src/dotmd/storage/surreal.py; https://surrealdb.com/docs/reference/query-language/statements/define/table]

**When to use:** For every table in SURR-MIG-01 that must survive later retrieval and cutover phases. [CITED: .planning/REQUIREMENTS.md]

**Example:**
```sql
-- Source: https://surrealdb.com/docs/reference/query-language/statements/define/table
DEFINE TABLE documents SCHEMAFULL;
DEFINE TABLE chunks SCHEMAFULL;
DEFINE TABLE relations TYPE RELATION IN sections OUT entities | tags ENFORCED;
```

### Pattern 2: Plan -> Dry-Run -> Apply -> Verify -> Report

**What:** Split migration execution into explicit stages with machine-readable manifests rather than one opaque import call. [CITED: backend/src/dotmd/ingestion/migrate_surreal.py; .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-04-OPERATIONS.md]

**When to use:** For all production-grade import work where partial failure and reruns must be explainable. [CITED: .planning/REQUIREMENTS.md]

**Prescriptive guidance:**
- `plan`: inspect source counts, schema version, target emptiness/overwrite policy, and unsupported categories. [CITED: backend/src/dotmd/storage/surreal_inventory.py; backend/src/dotmd/ingestion/migrate_surreal.py]
- `dry-run`: produce expected counts plus target write plan without mutating the target. [CITED: backend/src/dotmd/ingestion/migrate_surreal.py]
- `apply`: write in named phases such as `documents`, `chunks`, `vectors`, `graph`, `feedback`, and `state`, with per-phase verification. [CITED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-01-MIGRATION-MAP.md]
- `verify`: compare actual counts, required edge/property shapes, unreadable refs, and sample lookups against the plan. [CITED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-04-OPERATIONS.md]
- `report`: emit JSON and Markdown artifacts that Phase 43 and Phase 44 can consume. [CITED: .planning/phases/40-evaluation-harness-and-golden-queries/40-RESEARCH.md]

### Pattern 3: Preserve Graph Semantics With Relation Rows

**What:** Keep graph edges as first-class relation rows that preserve `rel_type`, `weight`, and edge metadata instead of flattening them into denormalized string arrays. [CITED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-01-INVENTORY.md; https://surrealdb.com/docs/learn/data-models/graph/creating-relations]

**When to use:** For imported Falkor `REL` edges and any later Phase 42 traversal work. [CITED: .planning/ROADMAP.md]

**Example:**
```sql
-- Source: https://surrealdb.com/docs/learn/data-models/graph/creating-relations
DEFINE TABLE relations TYPE RELATION IN sections OUT entities | tags ENFORCED;
```

### Anti-Patterns to Avoid

- **Prototype-wide target wipe:** `clear_phase38_tables()` is acceptable for the spike but not for production migration semantics. Replace it with explicit overwrite policy and per-phase replay rules. [CITED: backend/src/dotmd/ingestion/migrate_surreal.py]
- **Default recomputation:** Do not backfill missing rows by calling TEI, GLiNER, or the indexing pipeline unless a later proof shows the transform path is unsafe. [CITED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-02-IMPORT-PROOF.md]
- **Feedback direct SQL:** Keep feedback import behind the provider/exporter surface. [CITED: AGENTS.md; .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-01-INVENTORY.md]
- **Phase 42 work inside Phase 41:** Weighted FTS, vector index strategy, graph traversal semantics, and hybrid attribution are retrieval work, not migration work. [CITED: .planning/ROADMAP.md; .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Backup/restore format | ad hoc JSON dumps of selected tables | official `surreal export` / `surreal import` restore path plus repo-level manifests | Official docs define this as the logical backup surface and document restore validation expectations. [CITED: https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery; https://surrealdb.com/docs/reference/cli/surrealdb-cli/commands/export; https://surrealdb.com/docs/reference/cli/surrealdb-cli/commands/import] |
| Graph edge modeling | embedded edge arrays on chunk/entity records | Surreal relation tables | Relation tables preserve metadata and traversal semantics directly. [CITED: https://surrealdb.com/docs/learn/data-models/graph/creating-relations] |
| Record-ID escaping | manual string concatenation into Surreal record IDs | the existing `SurrealRecordIdCodec` | The repo already has a tested codec for special characters and Unicode-bearing IDs. [CITED: backend/src/dotmd/storage/surreal.py; .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-02-IMPORT-PROOF.md] |
| Table-name validation | interpolating unchecked SQLite table names | the existing safe-name regex helpers | The current loaders already guard table-name shape; keep that pattern for any expanded source-table selection. [CITED: backend/src/dotmd/ingestion/migrate_surreal.py; backend/src/dotmd/storage/surreal_inventory.py] |

**Key insight:** Phase 41 should harden the import contract around manifesting and validation, not replace repo-local safety primitives that already encode the tricky parts. [CITED: backend/src/dotmd/storage/surreal.py; backend/src/dotmd/ingestion/migrate_surreal.py]

## Runtime State Inventory

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | SQLite `index.db` in Docker volume `dotmd_dotmd-index` holds chunks, provenance, bindings, fingerprints, checkpoints, and vector tables; `feedback.db` holds feedback evidence; Falkor holds graph nodes and `REL` edges with `rel_type` and `weight`. [CITED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-01-INVENTORY.md; VERIFIED: docker volume ls] | Phase 41 must treat these as read-only migration sources, emit copied-snapshot or exporter evidence, and preserve D-01 categories by transform where practical. [CITED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-01-MIGRATION-MAP.md] |
| Live service config | The healthy `dotmd` container still serves the old stack; AGENTS documents live env vars for `/mnt`, SQLite index, TEI, and FalkorDB. [VERIFIED: docker ps; CITED: AGENTS.md] | No live config flip in Phase 41. The planner should add report fields for target namespace/database/path, but actual runtime cutover stays Phase 44. [CITED: .planning/ROADMAP.md; AGENTS.md] |
| OS-registered state | No repo-owned systemd, launchd, pm2, or scheduler registrations were identified in this phase scope; the only verified runtime registration is the Docker container plus volume. [VERIFIED: docker ps; VERIFIED: docker volume ls] | None for Phase 41 beyond preserving container-safe, read-only evidence capture discipline. [CITED: AGENTS.md] |
| Secrets/env vars | Production env vars still describe the old storage topology and `/mnt` data root. [CITED: AGENTS.md] | Phase 41 should not rename secrets or mutate env contracts; later cutover phases must update runtime config explicitly after migration and retrieval gates pass. [CITED: .planning/ROADMAP.md; AGENTS.md] |
| Build artifacts | Local backend tooling resolves `surrealdb 2.0.0`, but the standalone `surreal` CLI is missing on both host and current `dotmd` container. [VERIFIED: importlib.metadata version; VERIFIED: command -v surreal; VERIFIED: docker exec dotmd command -v surreal] | Phase 41 can proceed with SDK-driven local migration work. If a plan step needs `surreal export/import`, add an explicit install or alternate execution checkpoint instead of assuming the CLI exists. [CITED: https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery] |

## Common Pitfalls

### Pitfall 1: Treating Phase 41 As Retrieval Work

**What goes wrong:** The plan expands into weighted FTS, HNSW tuning, graph traversal semantics, or hybrid attribution work. [CITED: .planning/ROADMAP.md]
**Why it happens:** Phase 38's rejection mixed import and parity evidence, so it is easy to keep chasing retrieval inside the migration phase. [CITED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-RECOMMENDATION.md]
**How to avoid:** Lock Phase 41 to schema/import/reporting and carry retrieval acceptance criteria forward as inputs only. [CITED: .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md]
**Warning signs:** Plan tasks mention BM25 weighting, HNSW build metrics, graph traversal ranking, or reranker candidate behavior. [CITED: .planning/ROADMAP.md]

### Pitfall 2: Assuming One Giant Embedded SDK Transaction Exists

**What goes wrong:** The plan assumes a single high-level transaction can wrap the full embedded import. [CITED: https://surrealdb.com/docs/languages/python/api/core/surreal-transaction]
**Why it happens:** SurrealQL supports transactions, but the Python SDK's transaction object is not available on embedded connections. [CITED: https://surrealdb.com/docs/reference/query-language/language-primitives/transactions; https://surrealdb.com/docs/languages/python/api/core/surreal-transaction]
**How to avoid:** Use explicit import phases, raw SurrealQL transaction blocks where suitable, and idempotent rerun semantics backed by manifests. [CITED: https://surrealdb.com/docs/reference/query-language/language-primitives/transactions; backend/src/dotmd/ingestion/migrate_surreal.py]
**Warning signs:** Apply design depends on `begin_transaction()` for `surrealkv://` or treats rollback as automatic across the whole run. [CITED: https://surrealdb.com/docs/languages/python/api/core/surreal-transaction]

### Pitfall 3: Preserving Prototype Wipe-And-Replay Semantics

**What goes wrong:** Production migration semantics inherit `clear_phase38_tables()` plus full replay on every apply. [CITED: backend/src/dotmd/ingestion/migrate_surreal.py]
**Why it happens:** The prototype only needed spike-level rollback cleanliness, not resumable production migration. [CITED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-02-IMPORT-PROOF.md]
**How to avoid:** Add explicit overwrite policy, target-state checks, per-phase checkpoints, and rerunnable reports. [CITED: .planning/REQUIREMENTS.md; .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-04-OPERATIONS.md]
**Warning signs:** The plan has no phase checkpoints, no target-empty guard, and no post-phase verification rows. [CITED: .planning/REQUIREMENTS.md]

### Pitfall 4: Smuggling Non-D-01 Caches Into The Required Success Path

**What goes wrong:** `embedding_cache`, `extraction_cache`, `search_log`, or sqlite-vec shadow tables become required migration deliverables. [CITED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-01-MIGRATION-MAP.md]
**Why it happens:** They are present in the source snapshot and can look important during inventory. [CITED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-01-INVENTORY.md]
**How to avoid:** Keep SURR-MIG-01 limited to domain data needed for later retrieval and cutover. [CITED: .planning/REQUIREMENTS.md]
**Warning signs:** Plan deliverables mention cache parity or migrate `search_log` before core row categories are fully verified. [CITED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-01-MIGRATION-MAP.md]

## Code Examples

### Relation Table For Metadata-Carrying Edges
```sql
-- Source: https://surrealdb.com/docs/learn/data-models/graph/creating-relations
DEFINE TABLE relations TYPE RELATION IN sections OUT entities | tags ENFORCED;
```

### Transaction Block With Explicit Failure Path
```sql
-- Source: https://surrealdb.com/docs/reference/query-language/language-primitives/transactions
BEGIN TRANSACTION;
-- batched import statements here
IF $phase_failed {
    THROW "phase failed";
};
COMMIT TRANSACTION;
```

### Embedded Python Connection Surface
```python
# Source: https://surrealdb.com/docs/languages/python/concepts/connecting-to-surrealdb
from surrealdb import Surreal

db = Surreal("surrealkv://path/to/database")
db.connect()
db.use("dotmd", "phase41")
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Phase 38 thin prototype with `SCHEMALESS` tables, target wipe, and spike-level rollback | Phase 41 should move to schema-owned, report-first migration tooling | Phase 41 planning target after Phase 38 rejection. [CITED: backend/src/dotmd/storage/surreal.py; .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-RECOMMENDATION.md] | Makes migration rerunnable and auditable without pretending retrieval or cutover are done. [CITED: .planning/REQUIREMENTS.md] |
| Retrieval parity as the main decision gate inside the spike | Accepted-difference evaluation harness separated into Phase 40 and later shadow-run work | Phase 39-40. [CITED: .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md; .planning/phases/40-evaluation-harness-and-golden-queries/40-RESEARCH.md] | Phase 41 can focus on data movement and recovery semantics instead of re-litigating parity. [CITED: .planning/ROADMAP.md] |
| Ad hoc backup/restore rehearsal around copied stores | Official Surreal guidance favors logical export/import plus restore sanity checks | Current docs. [CITED: https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery; https://surrealdb.com/docs/reference/cli/surrealdb-cli/commands/export; https://surrealdb.com/docs/reference/cli/surrealdb-cli/commands/import] | Phase 41 should emit manifests and hooks that later phases can drive through the official restore path. [CITED: .planning/REQUIREMENTS.md] |

**Deprecated/outdated:**
- Treating the Phase 38 prototype as "almost production" is outdated; the roadmap now separates migration hardening, retrieval implementation, shadow run, cutover, and deletion into distinct phases. [CITED: .planning/ROADMAP.md]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Phase 41 can stay SDK-first for local development even if later restore drills use the official CLI. [ASSUMED] | Standard Stack; Environment Availability | The plan may under-specify CLI installation work if the implementation must exercise logical import/export earlier than expected. |

## Open Questions

1. **What is the authoritative Phase 41 target endpoint shape: embedded `surrealkv://`, remote ws/http, or both?**
   - What we know: The current repo and Phase 38 code use embedded `surrealkv://` for the prototype, and official docs support both embedded and remote SDK connections. [CITED: backend/src/dotmd/storage/surreal.py; https://surrealdb.com/docs/languages/python/concepts/connecting-to-surrealdb]
   - What's unclear: The roadmap does not yet lock whether production migration writes go into an embedded file or a running Surreal service before Phase 44. [CITED: .planning/ROADMAP.md]
   - Recommendation: Make the Phase 41 runner endpoint-agnostic and require the planner to keep connection settings explicit in the report contract. [ASSUMED]

2. **Should graph import keep one canonical `relations` table with `rel_type`, or split relation types physically now?**
   - What we know: Phase 38 inventory proved the source graph uses one physical `REL` edge plus semantic `rel_type`, and Surreal relation tables can carry metadata. [CITED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-01-INVENTORY.md; https://surrealdb.com/docs/learn/data-models/graph/creating-relations]
   - What's unclear: The roadmap does not yet lock the Phase 42 traversal/index strategy. [CITED: .planning/ROADMAP.md]
   - Recommendation: Preserve one canonical imported relation shape in Phase 41 and defer any physical split to Phase 42 only if traversal evidence demands it. [ASSUMED]

3. **How early must restore drills use the official `surreal export/import` path if the CLI is absent today?**
   - What we know: Official docs recommend `surreal export` and `surreal import`, and neither host nor current container has the CLI installed. [CITED: https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery; VERIFIED: command -v surreal; VERIFIED: docker exec dotmd command -v surreal]
   - What's unclear: Whether Phase 41 should install the CLI or only define restore manifests and leave execution to Phase 44. [CITED: .planning/ROADMAP.md]
   - Recommendation: Phase 41 should define manifest and verification contracts first, then let the planner decide whether explicit CLI installation belongs in this phase or the later cutover phase. [ASSUMED]

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | backend migration code | yes | `3.13.5` | none needed. [VERIFIED: python3 --version] |
| `uv` | repo-local backend env and tests | yes | `0.11.19` | none needed. [VERIFIED: uv --version] |
| `pytest` | validation architecture | yes | `9.0.3` | none needed. [VERIFIED: uv run pytest --version] |
| Docker | live read-only runtime evidence and later rehearsal surfaces | yes | `29.5.3` | none needed. [VERIFIED: docker --version] |
| `dotmd` container | runtime-state confirmation | yes | healthy | repo-only research still possible without it, but runtime inventory would be weaker. [VERIFIED: docker ps] |
| `surrealdb` Python SDK | local migration implementation | yes | `2.0.0` | none inside the repo; fresh install requires human verification because package-legitimacy verdict is `SUS`. [VERIFIED: importlib.metadata version; VERIFIED: package-legitimacy check] |
| `surreal` CLI | official logical export/import path | no | - | use SDK-based local development now and add explicit install or later-phase execution checkpoint before relying on CLI restore drills. [VERIFIED: command -v surreal; VERIFIED: docker exec dotmd command -v surreal] |

**Missing dependencies with no fallback:**
- none for writing Phase 41 code and tests. [VERIFIED: python3 --version; VERIFIED: uv run pytest --version]

**Missing dependencies with fallback:**
- `surreal` CLI - fallback is SDK-based local development plus deferred CLI install/rehearsal planning. [CITED: https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery]

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest 9.0.3`. [VERIFIED: uv run pytest --version] |
| Config file | `backend/pyproject.toml`. [CITED: backend/pyproject.toml] |
| Quick run command | `cd backend && uv run pytest tests/ingestion/test_surreal_transform_only_migration.py tests/storage/test_surreal_storage_contract.py tests/storage/test_surreal_ops_safety.py -x` [CITED: backend/tests/ingestion/test_surreal_transform_only_migration.py; backend/tests/storage/test_surreal_storage_contract.py; backend/tests/storage/test_surreal_ops_safety.py] |
| Full suite command | `cd backend && uv run pytest` [CITED: backend/pyproject.toml] |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SURR-MIG-01 | Schema defines all required domain tables and preserves source row shapes | unit | `cd backend && uv run pytest tests/storage/test_surreal_storage_contract.py -x` | yes. [CITED: backend/tests/storage/test_surreal_storage_contract.py] |
| SURR-MIG-02 | Default import path reuses stored chunks, vectors, graph rows, feedback, cursors, and checkpoints without recomputation | unit | `cd backend && uv run pytest tests/ingestion/test_surreal_transform_only_migration.py -x` | yes. [CITED: backend/tests/ingestion/test_surreal_transform_only_migration.py] |
| SURR-MIG-03 | Migration reports backup/restore/rollback and partial-failure semantics that block unsafe apply or false success | unit | `cd backend && uv run pytest tests/storage/test_surreal_ops_safety.py tests/ingestion/test_surreal_transform_only_migration.py -x` | partial - spike coverage exists, production-grade coverage still missing. [CITED: backend/tests/storage/test_surreal_ops_safety.py; backend/tests/ingestion/test_surreal_transform_only_migration.py] |

### Sampling Rate
- **Per task commit:** `cd backend && uv run pytest tests/ingestion/test_surreal_transform_only_migration.py tests/storage/test_surreal_storage_contract.py tests/storage/test_surreal_ops_safety.py -x`
- **Per wave merge:** `cd backend && uv run pytest`
- **Phase gate:** Full suite green before `$gsd-verify-work`. [CITED: .planning/config.json]

### Wave 0 Gaps
- [ ] `backend/tests/ingestion/test_surreal_production_migration.py` - add plan/dry-run/apply/report/idempotency coverage for Phase 41 orchestration. [ASSUMED]
- [ ] `backend/tests/storage/test_surreal_schema_definition.py` - lock schema versioning, `SCHEMAFULL`, and relation-table expectations. [ASSUMED]
- [ ] `backend/tests/ingestion/test_surreal_restore_manifest.py` - cover restore manifest generation, partial-failure statuses, and overwrite-policy guards. [ASSUMED]

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Migration tooling is repo-local/operator-driven in this phase; no new auth surface is introduced. [CITED: .planning/ROADMAP.md] |
| V3 Session Management | no | Phase 41 does not add user sessions or tokens. [CITED: .planning/ROADMAP.md] |
| V4 Access Control | yes | Restrict target selection and overwrite/apply execution behind explicit mode flags, gate reports, and operator-provided paths/endpoints only. [CITED: backend/src/dotmd/ingestion/migrate_surreal.py; .planning/REQUIREMENTS.md] |
| V5 Input Validation | yes | Keep safe table-name validation and the record-ID codec; require explicit endpoint/path/schema-version validation before apply. [CITED: backend/src/dotmd/ingestion/migrate_surreal.py; backend/src/dotmd/storage/surreal.py] |
| V6 Cryptography | no | This phase should reuse platform/backup-storage encryption choices rather than implement any custom cryptography. [CITED: https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery] |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Unsafe record or table identifiers shaping SurrealQL structure | Tampering | Use `SurrealRecordIdCodec` and safe-name regex guards; never interpolate caller-owned identifiers directly into record IDs or table names. [CITED: backend/src/dotmd/storage/surreal.py; backend/src/dotmd/ingestion/migrate_surreal.py] |
| Applying against the wrong target or overwriting a non-empty target unexpectedly | Tampering | Add explicit target manifests, overwrite policy flags, schema version checks, and pre-apply emptiness/count checks. [CITED: .planning/REQUIREMENTS.md; backend/src/dotmd/ingestion/migrate_surreal.py] |
| False-success restore or partial import | Repudiation | Emit per-phase counts, restore manifests, and post-restore sanity checks before marking success. [CITED: .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-04-OPERATIONS.md; https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery] |
| Bypassing approved feedback export path | Information Disclosure | Keep feedback import behind the provider/exporter abstraction and never query live `feedback.db` directly. [CITED: AGENTS.md; backend/src/dotmd/ingestion/migrate_surreal.py] |

## Sources

### Primary (HIGH confidence)
- `backend/src/dotmd/storage/surreal.py` - current thin schema/store helpers and record-ID codec.
- `backend/src/dotmd/ingestion/migrate_surreal.py` - current dry-run/apply runner and transform loaders.
- `backend/src/dotmd/storage/surreal_inventory.py` - copied-snapshot and inventory helpers.
- `backend/src/dotmd/storage/surreal_ops.py` - embedded safety and restore/report helpers.
- `.planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-01-INVENTORY.md` - verified source data inventory.
- `.planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-01-MIGRATION-MAP.md` - D-01 transformability map.
- `.planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-02-IMPORT-PROOF.md` - transform-only import boundary.
- `.planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-04-OPERATIONS.md` - restore/rollback rehearsal evidence.
- `.planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-05-EMBEDDED-SAFETY-GATE.md` - embedded safety gate.
- `.planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md` - no-fallback/no-recompute contract.
- `.planning/ROADMAP.md` and `.planning/REQUIREMENTS.md` - v1.8 phase and requirement boundaries.

### Secondary (MEDIUM confidence)
- https://surrealdb.com/docs/reference/query-language/language-primitives/transactions - transaction, cancel, and `THROW` semantics.
- https://surrealdb.com/docs/reference/query-language/statements/define/table - `SCHEMAFULL`, `TYPE RELATION`, `ENFORCED`, and overwrite semantics.
- https://surrealdb.com/docs/learn/data-models/graph/creating-relations - relation-table modeling with metadata-carrying edges.
- https://surrealdb.com/docs/languages/python - current SDK version and compatibility note.
- https://surrealdb.com/docs/languages/python/concepts/connecting-to-surrealdb - embedded vs remote connection shapes.
- https://surrealdb.com/docs/languages/python/api/core/surreal-transaction - SDK transaction object limitation on embedded connections.
- https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery - official backup/restore guidance.
- https://surrealdb.com/docs/reference/cli/surrealdb-cli/commands/export - export semantics and `OPTION IMPORT`.
- https://surrealdb.com/docs/reference/cli/surrealdb-cli/commands/import - import semantics and validation guidance.
- https://pypi.org/project/surrealdb/ - release history and package metadata.

### Tertiary (LOW confidence)
- none.

## Metadata

**Confidence breakdown:**
- Standard stack: MEDIUM - the repo-local stack is clear, but the `surrealdb` package-legitimacy seam returned `SUS` and the local CLI restore path is absent. [VERIFIED: package-legitimacy check; VERIFIED: command -v surreal]
- Architecture: HIGH - the schema/import boundaries are strongly constrained by repo code, Phase 38 artifacts, and the roadmap split. [CITED: backend/src/dotmd/ingestion/migrate_surreal.py; .planning/ROADMAP.md]
- Pitfalls: HIGH - the current spike code and prior artifacts already expose the major failure modes directly. [CITED: backend/src/dotmd/ingestion/migrate_surreal.py; .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-RECOMMENDATION.md]

**Research date:** 2026-06-13
**Valid until:** 2026-06-20
