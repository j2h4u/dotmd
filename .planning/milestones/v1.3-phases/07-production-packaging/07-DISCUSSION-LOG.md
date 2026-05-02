# Phase 7: Production Packaging - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-27
**Phase:** 07-production-packaging
**Areas discussed:** Compose architecture, Health & startup, Env config, WAL mode, Deployment model

---

## Self-contained Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Только ссылки | TEI/FalkorDB как внешние сервисы. External networks + healthchecks | |
| Всё в одном compose | TEI/FalkorDB как сервисы прямо в docker-compose.yml | |
| Profiles | TEI/FalkorDB как optional profiles. По умолчанию external, --profile bundled для автономного стека | ✓ |

**User's choice:** Profiles
**Notes:** Compromise — default mode uses external services (senbonzakura setup), `--profile bundled` brings everything up for new server setup.

---

## Health Endpoint

| Option | Description | Selected |
|--------|-------------|----------|
| Только себя | 200 если FastAPI жив. Зависимости через depends_on при старте | ✓ |
| Глубокий | Пингует TEI /health и FalkorDB redis ping на каждый запрос | |
| Ты решай | Claude's discretion | |

**User's choice:** Только себя (Recommended)
**Notes:** Minimal health — FastAPI alive = 200. Dependency health checked via depends_on at startup, not per-request.

---

## Env Configuration

| Option | Description | Selected |
|--------|-------------|----------|
| В репо | .env.example в корне репо с документированными дефолтами. Compose через env_file. ~/.secrets/ для секретов | ✓ |
| Только документация | .env.example как справка, compose не менять — env vars остаются захардкоженные | |
| Ты решай | Claude's discretion | |

**User's choice:** В репо (Recommended)
**Notes:** .env.example in repo, compose uses env_file, secrets separate via ~/.secrets/

---

## Compose File Location (extended discussion)

Initial question: where does the compose file live?

**User clarified through free-text discussion:**
1. Prefers production separated from development
2. All Docker containers must be in `/opt/docker/` (server convention)
3. Doesn't want secrets or server-specific paths in the GitHub repo

**Resolution:** Two-layer approach:
- Repo compose: fully parameterized, no secrets, single source of truth for service definitions
- `/opt/docker/dotmd/`: `include:` directive pointing to repo compose + production `.env` + secrets `env_file`

| Option | Description | Selected |
|--------|-------------|----------|
| Single compose in repo | Everything runs from repo directory | |
| Include from /opt/docker/ | Production compose uses include: to reference repo compose + .env overlay | ✓ |
| Two independent files | Separate production and repo composes (drift risk) | |

**User's choice:** Include from /opt/docker/
**Notes:** User explicitly stated preference for `/opt/docker/` convention and no secrets in repo. Include approach satisfies both constraints with zero drift.

---

## WAL Mode

Not discussed as a gray area — technical task with clear answer. metadata.db already has WAL. vec.db needs one-line addition.

---

## Claude's Discretion

- Health endpoint response format details
- TEI/FalkorDB bundled profile service definitions
- MCP service inclusion in new compose
- Compose service ordering and .env.example grouping

## Deferred Ideas

- Automated deployment (git hook / systemd path unit)
- CI/CD via GitHub Actions
- MCP service in compose (deferred to planning decision)
