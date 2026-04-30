#!/bin/sh
# Container entrypoint.
#
# When ENVIRONMENT=dev (set in docker-compose.override.yml on the dev host),
# run a pre-flight gate before serving:
#   1. ruff check (lint clean)
#   2. pyright ratchet (no new type errors vs baseline)
#   3. start MCP server in background, wait for /health
#   4. pytest tests/e2e/ (live integration smoke)
#   5. if all green, keep the already-running server; else kill and exit 1
#
# Any other ENVIRONMENT value (incl. unset, empty, "prod") skips the gate
# and execs the server directly — production deploys never pay the cost.
set -e

SRC_ROOT=/mnt/home/repos/j2h4u/dotmd/backend
SERVE_CMD="dotmd mcp --transport streamable-http --host 0.0.0.0 --port 8080"

# Anything other than ENVIRONMENT=dev (unset, empty, "prod", "staging", …)
# skips the gate and execs the server directly.  Two reasons this is the
# safe default:
#   1. Production never pays the gate's CPU cost (~2 min of e2e tests).
#   2. Any deploy without the dev bind-mounts (src/, tests/, devtools/)
#      can't even run the gate — its tools and source aren't available.
# Opt INTO the gate by setting ENVIRONMENT=dev in the compose override.
if [ "${ENVIRONMENT}" != "dev" ]; then
    exec $SERVE_CMD
fi

if [ ! -d "$SRC_ROOT" ]; then
    echo "ENVIRONMENT=dev but $SRC_ROOT not bind-mounted — refusing to start" >&2
    exit 1
fi

cd "$SRC_ROOT"

echo "==> ENVIRONMENT=dev — running pre-flight gate" >&2

echo "==> [1/3] ruff" >&2
ruff check --cache-dir /tmp/.ruff_cache src/ tests/ devtools/ >&2

echo "==> [2/3] pyright ratchet" >&2
python3 devtools/pyright_ratchet.py >&2

echo "==> [3/3] e2e smoke (server in background, auth disabled)" >&2
DOTMD_BASE_URL= $SERVE_CMD &
SERVER_PID=$!

cleanup_and_exit() {
    code=$1
    kill -TERM $SERVER_PID 2>/dev/null || true
    wait $SERVER_PID 2>/dev/null || true
    exit "$code"
}

trap 'cleanup_and_exit 1' INT TERM

# Wait for /health (max 90s — first start loads ML models)
n=0
until curl -sf http://localhost:8080/health > /dev/null 2>&1; do
    n=$((n + 1))
    if [ $n -gt 90 ]; then
        echo "Pre-flight: server health timed out after 90s" >&2
        cleanup_and_exit 1
    fi
    if ! kill -0 $SERVER_PID 2>/dev/null; then
        echo "Pre-flight: server process died during startup" >&2
        exit 1
    fi
    sleep 1
done

# Run e2e against the running server.  pytest writes its cache under cwd
# which is read-only, so redirect cache + tmpdir to /tmp.
export PYTEST_DEBUG_TEMPROOT=/tmp
if DOTMD_BASE_URL= pytest -p no:cacheprovider tests/e2e/ --tb=short -q >&2; then
    echo "==> Pre-flight passed — starting final server" >&2
    kill -TERM $SERVER_PID 2>/dev/null || true
    wait $SERVER_PID 2>/dev/null || true
    exec $SERVE_CMD
else
    echo "==> Pre-flight: e2e failed — killing server, exiting" >&2
    cleanup_and_exit 1
fi
