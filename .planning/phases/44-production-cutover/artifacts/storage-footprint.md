# Phase 44 Storage and Memory Footprint

## Live Paths

- Old dotMD index volume: `/var/lib/docker/volumes/dotmd_dotmd-index/_data`
- Old runtime mount inside `dotmd`: `/dotmd-index`
- Old graph store: `/srv/falkordb`
- Standalone SurrealDB store: `/srv/surrealdb/data/main.db`
- Standalone SurrealDB compose root: `/opt/docker/surrealdb`

## Current Sizes

- Old dotMD index mount observed inside container: `/dotmd-index` = `4.9G`
- Old `index.db`: `2.4G`
- Old `feedback.db`: `28K`
- Old FalkorDB host store: about `31M`
- Standalone SurrealDB host store: `/srv/surrealdb/data` = `3.8G`
- Repo-local `data/`: `8K`, only zero-byte historical DB placeholders.

## Runtime Memory Sample

Single `docker stats --no-stream` sample:

- `surrealdb`: `447.7MiB / 8GiB`
- `dotmd`: `1.047GiB / 15.54GiB`
- `falkordb`: `238.5MiB / 15.54GiB`
- `embeddings`: `1.447GiB / 8GiB`

## SurrealDB Candidate Identity

- Namespace: `dotmd`
- Populated database: `phase43_refresh_20260618g`
- Verified bounded counts:
  - `documents=1441`
  - `chunks=149839`
  - `relations=344102`
  - `entities=81822`
- `embeddings` full count over HTTP timed out and should not be used as a
  fast readiness probe.

## Decision

Storage footprint is **not a cutover blocker by itself**.

Standalone SurrealDB is smaller than the current full old index mount, but not
dramatically smaller than `index.db` alone. Disk is acceptable for continued
Phase 44 work; runtime wiring and reranker-on latency are the blocking issues.
