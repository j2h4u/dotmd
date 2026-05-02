---
phase: 07-production-packaging
plan: 02
subsystem: infra
tags: [docker-compose, profiles, env-config, include-directive, production-deploy]

# Dependency graph
requires:
  - phase: 07-production-packaging/01
    provides: /health endpoint, Dockerfile HEALTHCHECK, WAL mode
provides:
  - Parameterized repo docker-compose.yml with bundled profile (TEI + FalkorDB)
  - .env.example documenting all DOTMD_* configuration variables
  - Production /opt/docker/dotmd/ using include directive to reference repo compose
  - Production .env with server-specific values (1024-dim embeddings, FalkorDB)
affects: [07-03-verification]

# Tech tracking
tech-stack:
  added: []
  patterns: [compose profiles for optional bundled services, include directive for production overlay, env_file required:false for optional .env]

key-files:
  created:
    - .env.example
    - /opt/docker/dotmd/docker-compose.override.yml
    - /opt/docker/dotmd/.env
  modified:
    - docker-compose.yml
    - /opt/docker/dotmd/docker-compose.yml

key-decisions:
  - "Removed depends_on for profiled services -- compose v5.1 errors on depends_on referencing inactive-profile services despite docs claiming silent ignore"
  - "Used env_file path/required:false instead of env_file: .env -- compose include auto-discovers .env at included file directory, required:false prevents failure when absent"
  - "Port override via DOTMD_PORT in production .env instead of ports: in override -- avoids compose port list merge (append vs replace) issue"
  - "Production override provides env_file with both .env and huggingface.env -- env vars flow into container environment"

patterns-established:
  - "Compose profile pattern: services with profiles: [bundled] only activate with --profile bundled"
  - "Production include pattern: /opt/docker/dotmd/ compose uses include: to reference repo compose as source of truth"
  - "Empty .env at repo root required for include compatibility (gitignored, not committed)"

requirements-completed: [PACK-01, PACK-02, PACK-03]

# Metrics
duration: 5min
completed: 2026-03-27
---

# Phase 07 Plan 02: Docker Compose Stack Summary

**Parameterized compose with TEI/FalkorDB bundled profile, .env.example for all settings, and production include-based deploy at /opt/docker/dotmd/**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-27T14:08:15Z
- **Completed:** 2026-03-27T14:13:59Z
- **Tasks:** 2 of 3 (Task 3 is checkpoint:human-verify)
- **Files modified:** 5

## Accomplishments
- Replaced hardcoded repo docker-compose.yml with fully parameterized version using env vars and bundled profile
- Created .env.example documenting all 25+ DOTMD_* variables grouped by category
- Created production /opt/docker/dotmd/ with include directive referencing repo compose as single source of truth
- Production override adds external networks (embeddings_default, graphiti_default) and secrets (huggingface.env)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create repo docker-compose.yml with profiles and .env.example** - `fd900a8` (feat)
2. **Task 1 fix: env_file required:false for include compatibility** - `35d144c` (fix)
3. **Task 2: Create production /opt/docker/dotmd/ with include pattern** - no repo commit (files at /opt/docker/dotmd/, outside repo)

## Files Created/Modified
- `docker-compose.yml` - Parameterized with DOTMD_PORT, DOTMD_DATA_VOLUME, bundled profile for TEI/FalkorDB, healthchecks
- `.env.example` - Documents all DOTMD_* variables with defaults, grouped by category (Compose, Paths, Embedding, Vector Store, Graph, Extraction, Search, Reranker, Chunking)
- `/opt/docker/dotmd/docker-compose.yml` - 4-line include directive referencing repo compose + local override
- `/opt/docker/dotmd/docker-compose.override.yml` - Production volumes, networks (embeddings_default, graphiti_default), env_file with .env and huggingface.env
- `/opt/docker/dotmd/.env` - Production values: DOTMD_PORT=127.0.0.1:8321, DOTMD_EMBEDDING_DIM=1024, DOTMD_GRAPH_BACKEND=falkordb

## Decisions Made
- **depends_on removed for profiled services:** Compose v5.1 errors when depends_on references a service not in active profile, contrary to research expectation. Removed since healthchecks handle readiness independently.
- **env_file with required:false:** Compose include auto-discovers .env at the included file's directory. Using `required: false` prevents failure when the repo's .env doesn't exist. An empty .env at repo root (gitignored) provides additional compatibility.
- **Port via env var, not override ports:** Compose merges port lists (appends), so the override would create dual port mappings. Using DOTMD_PORT in production .env cleanly overrides the default.
- **Production env_file includes .env:** The override's env_file list includes both .env (DOTMD_* vars) and huggingface.env (HF_TOKEN), ensuring all vars reach the container.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed depends_on for profiled services**
- **Found during:** Task 1 (compose config validation)
- **Issue:** `depends_on` with `condition: service_healthy` on profiled services (tei, falkordb) caused "depends on undefined service" error in default mode
- **Fix:** Removed depends_on block from api service entirely
- **Files modified:** docker-compose.yml
- **Verification:** `docker compose config --quiet` passes in both default and bundled modes
- **Committed in:** fd900a8

**2. [Rule 3 - Blocking] Changed env_file to required:false for include compatibility**
- **Found during:** Task 2 (production compose validation)
- **Issue:** `include:` directive caused compose to auto-discover .env at the included file's directory, failing when absent
- **Fix:** Changed `env_file: .env` to `env_file: [{path: .env, required: false}]`
- **Files modified:** docker-compose.yml
- **Verification:** Both repo direct and production include `docker compose config` succeed
- **Committed in:** 35d144c

**3. [Rule 1 - Bug] Moved port override from compose override to DOTMD_PORT env var**
- **Found during:** Task 2 (production config rendering)
- **Issue:** Compose merges port lists from base + override, resulting in both 8000:8000 and 127.0.0.1:8321:8000
- **Fix:** Removed `ports:` from override, added `DOTMD_PORT=127.0.0.1:8321` to production .env
- **Files modified:** /opt/docker/dotmd/docker-compose.override.yml, /opt/docker/dotmd/.env
- **Verification:** `docker compose config` shows single port mapping 127.0.0.1:8321:8000

---

**Total deviations:** 3 auto-fixed (2 bugs, 1 blocking)
**Impact on plan:** All fixes necessary for compose to actually work. No scope creep -- same intent, corrected mechanisms.

## Issues Encountered
- Compose v5.1 `include:` directive auto-loads `.env` from the included file's project directory, ignoring `required: false` on the included file's service-level `env_file`. Workaround: empty `.env` at repo root (gitignored).
- Compose port list merge is append-only (not replace), making override-based port changes unreliable. Env var interpolation (`${DOTMD_PORT}`) is the correct pattern.

## User Setup Required
None for production -- all files created and validated. Task 3 (human-verify checkpoint) requires deploying and checking health.

## Known Stubs
None -- all files are complete and functional.

## Next Phase Readiness
- Task 3 (checkpoint:human-verify) pending: deploy with `docker compose up -d --build` and verify health endpoint
- All compose files validated via `docker compose config` in all modes
- Production config renders correct build context, environment, volumes, networks, and port

## Self-Check: PASSED

All 6 files verified present. Both commit hashes (fd900a8, 35d144c) confirmed in git log.

---
*Phase: 07-production-packaging*
*Completed: 2026-03-27 (Tasks 1-2; Task 3 pending human verification)*
