# Phase 6: Docker Integration + Migration - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-27
**Phase:** 06-docker-integration-migration
**Areas discussed:** Docker networking, Environment config, Re-index strategy, Validation approach
**Mode:** --auto (all decisions auto-selected)

---

## Docker Networking

| Option | Description | Selected |
|--------|-------------|----------|
| External network in compose | Add `graphiti_default` as external network (same pattern as `embeddings_default`) | ✓ |
| Manual docker network connect | Run `docker network connect graphiti_default dotmd-api-1` after each restart | |
| Host networking | Use `network_mode: host` to access all local services | |

**User's choice:** [auto] External network in compose (recommended default)
**Notes:** Follows established pattern in the same compose file. Declarative, survives down/up cycles.

---

## Environment Config

| Option | Description | Selected |
|--------|-------------|----------|
| Inline in compose environment block | Add DOTMD_GRAPH_BACKEND, DOTMD_FALKORDB_URL, DOTMD_FALKORDB_GRAPH_NAME to environment list | ✓ |
| Separate .env file in ~/.secrets/ | Create ~/.secrets/dotmd-falkordb.env with FalkorDB vars | |
| Combined with existing env_file | Add to huggingface.env or create dotmd.env with all vars | |

**User's choice:** [auto] Inline in compose environment block (recommended default)
**Notes:** Only 3 vars, all non-secret. Matches existing pattern where non-secret config is inline.

---

## Re-index Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| One-off docker compose run | `docker compose run --rm api index --force /mnt` — manual, overnight | ✓ |
| Separate indexer service | Add `indexer` service to compose with `restart: no` | |
| Exec into running api container | `docker exec dotmd-api-1 dotmd index --force /mnt` | |

**User's choice:** [auto] One-off docker compose run (recommended default)
**Notes:** No persistent service needed for a one-time ~59min operation. Reuses same image/volumes/networks as api service. Stop api first to avoid concurrent file access.

---

## Validation Approach

| Option | Description | Selected |
|--------|-------------|----------|
| CLI search + status from container | `dotmd status` + `dotmd search --mode hybrid` + API curl test | ✓ |
| Automated test script | Write a validation script that checks all three | |
| Manual FalkorDB query | Connect to FalkorDB directly and count nodes/edges | |

**User's choice:** [auto] CLI search + status from container (recommended default)
**Notes:** Three checks: status (graph backend info), search (graph in matched_engines), serve + curl (concurrent access works).

---

## Folded Todos

- **Migrate graph store from LadybugDB to FalkorDB** (score: 0.9) — folded into phase scope, this IS the migration phase

## Deferred Ideas

- Scout other dotmd forks for ideas (score: 0.6) — not specific to Docker integration, stays in backlog
