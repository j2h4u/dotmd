# SurrealDB Operations

Short runbook for the standalone SurrealDB backend used by dotMD. No external
collector is assumed.

## Symptoms Matrix

| Signal | What to check | What it usually means |
|--------|---------------|-----------------------|
| `GET /health` on SurrealDB | `curl -fsS http://surrealdb:8000/health` | SurrealDB liveness; an empty HTTP 200 is still acceptable here, and `{"status":"ok"}` or body `ok` are also fine |
| `RETURN 1` against SurrealDB | a direct low-cost query to the standalone database | stronger readiness signal for connectivity and auth; if this hangs, treat SurrealDB as degraded or unavailable |
| `GET /metrics` | manual scrape of the SurrealDB metrics endpoint, if exposed | resource pressure, query latency, and backlog signals; use it as a spot-check, not as a collector replacement |
| `docker stats` | CPU, memory, restart churn | sustained load, memory pressure, or a runaway query/index build |
| `docker logs` | recent errors and slow-query evidence | repeated scans, long-running schema work, or keepalive noise hiding the real stall |
| `process_alive_http_query_plane_unavailable` | process is up, but query plane checks are timing out | Docker can say Up while the service is still not healthy; confirm the `/health` path and the SurrealDB query path separately |

## What The Recent Incident Taught Us

- `DEFINE INDEX` can be a long-running operation, not a quick schema tweak.
- Full scans were the real cost driver.
- Exact anti-joins made the bad path much worse.
- Missing indexes turned routine admin work into table-wide work.
- WebSocket keepalives proved the connection was open, not that the operation was making useful progress.
- `process_alive_http_query_plane_unavailable` means the process survived but the HTTP/query plane did not become usable yet.

## Safe Rules For Admin Queries

- Run `EXPLAIN` or `EXPLAIN FULL` first.
- Prefer indexed predicates and bounded lookups.
- Do not use exact anti-join by default.
- Keep admin work low priority and out of normal traffic windows.
- Report progress at least every 120 seconds for anything long-running.
- If a wait is expected to run longer than 120 seconds, poll rarely instead of hammering the database.
- Stop and re-plan if the plan shows table scans, nested loops, or other obvious full-table work.

## Incident Decision Tree

1. If Docker says `Up` but `/health`, SQL, or metrics calls still read timeout, do not treat the container state as healthy unless a real healthcheck is present.
2. If the issue follows DDL and CPU stays at `0`, with no recent logs and all three probes still timing out for more than `N` minutes, wait briefly rather than restarting immediately.
3. If there is still no progress after that window, restart the service once and re-check `/health` plus a tiny SQL probe.
4. If the same pattern repeats after restart, treat it as a query-plane stall or schema-work regression and investigate the DDL path before retrying again.

## Running `backend/devtools/surreal_operational_probe.py`

Use the probe from `backend/` so it resolves the local package layout:

```bash
cd backend
uv run python devtools/surreal_operational_probe.py --help
```

Then run it against the target SurrealDB with explicit target URL, namespace,
database, and an output directory. Keep the query small first (`RETURN 1`),
then add only the next check you need. Prefer a bounded timeout and a low
heartbeat interval so the probe itself gives you progress without becoming the
load.

## Running The Embedding Backfill

The default backfill path is container-local, not host-local. Run it through
the dotMD container so the production env already resolves the in-network
services:

```bash
docker exec -w /app dotmd python devtools/surreal_embedding_backfill.py --chunk-id <chunk-id> --apply
```

or, if you prefer Compose:

```bash
docker compose exec -w /app dotmd python devtools/surreal_embedding_backfill.py --chunk-id <chunk-id> --apply
```

Inside that container network, the standard nested env values are already valid:
`DOTMD_EMBEDDING__URL=http://embeddings:80` and
`DOTMD_SURREAL_RETRIEVAL__URL=http://surrealdb:8000`.

For local experiments, run the script from an environment that can reach the
configured TEI and SurrealDB endpoints.

## Inspecting Logs Without Leaking Secrets

- Prefer narrow windows: `docker logs --since 15m --tail 200 surrealdb`.
- Copy only the few lines around the stall or failure.
- Redact auth headers, tokens, passwords, bearer strings, query bodies, and
  any connection strings with credentials before pasting elsewhere.
- Do not dump full env files, full query payloads, or raw exported traces into
  chat.

## Minimal Compose Improvements Later

- Add a `healthcheck` to the SurrealDB service with a bounded timeout and
  retry window. The official image used here does not include a shell, `curl`,
  or `wget`, so use the bundled CLI:
  `["CMD", "/surreal", "is-ready", "--endpoint", "ws://localhost:8000"]`.
- Keep metrics as a manual scrape step first; do not add a collector just for
  this runbook.
- Allow log-level changes only during incidents, then revert them.
