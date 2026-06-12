backend := "backend"

# Show available commands.
default:
    @just --list

# Install backend dev dependencies.
setup:
    cd {{backend}} && uv sync --extra dev

# Compile Python sources for syntax errors.
_compile:
    cd {{backend}} && uv run python -m compileall -q src devtools tests

# Check formatting without writing.
_fmt-check:
    cd {{backend}} && uv run ruff format --check src tests devtools

# Run Ruff lint checks at the current dotMD baseline.
_lint:
    cd {{backend}} && uv run ruff check src tests devtools

# Check import-layer architecture contracts.
_import-contracts:
    cd {{backend}} && uv run lint-imports

# Check GitHub Actions workflow syntax and expressions.
_actionlint:
    cd {{backend}} && uv run actionlint ../.github/workflows/*.yml

# Scan for dead code. Vendored Airweave is excluded because local deltas are
# tracked separately in vendor notes and should stay close to upstream shape.
_dead-code:
    cd {{backend}} && uv run vulture src tests --min-confidence 80 --exclude "*/vendor/*"

# Run local backend pytest suite. Live MCP checks are opt-in.
test *args:
    cd {{backend}} && uv run pytest -m "not e2e and not smoke" {{args}}

# Unit tests only.
unit *args:
    cd {{backend}} && uv run pytest -q -m "not e2e and not smoke" {{args}}

# Run live MCP e2e tests inside the running dotMD container.
test-e2e *args:
    docker exec dotmd sh -lc 'cd /mnt/home/repos/j2h4u/dotmd/backend && python -m pytest tests/e2e/ -p no:cacheprovider --tb=short -q {{args}}'

# Run production MCP/Funnel connectivity smoke against live containers.
test-mcp-remote *args:
    cd {{backend}} && uv run python devtools/mcp_remote_smoke.py {{args}}

# Run Ruff lint checks.
lint: _lint

# Format Python code and apply safe Ruff fixes.
fmt:
    cd {{backend}} && uv run ruff format src tests devtools
    cd {{backend}} && uv run ruff check --fix src tests devtools

# Alias for fmt.
format: fmt

# Run Pyright ratchet against the checked-in baseline.
typecheck:
    cd {{backend}} && uv run python devtools/pyright_ratchet.py

# Opt-in stricter basedpyright source gate; not part of check until existing
# diagnostics are paid down.
typecheck-strict:
    cd {{backend}} && uv run basedpyright src --warnings

# Opt-in mcp-strava-style Ruff hardening gate; not part of check until current
# findings are intentionally fixed or ratcheted.
lint-strict:
    cd {{backend}} && uv run ruff check src tests devtools --select E4,E7,E9,F,I,B,BLE,UP,C4,PIE,ISC,RSE,FLY,RUF,PERF,SIM,PTH,DTZ,PGH,PLE,LOG,G,FURB,RET,N818 --ignore RUF001,RUF002,RUF003,ISC001,E501,B008,N802,N803,N806,SIM108

# Static quality gate: lint, types, imports, workflows, compile, dead code.
# _fmt-check is available but not mandatory until the existing formatting debt is
# paid down in a dedicated mechanical commit.
check: _lint typecheck _import-contracts _actionlint _compile _dead-code

# Full local gate for agents before claiming completion.
verify: check unit

# Build the dotMD container image.
docker-build:
    docker compose build dotmd

# Start dotMD container.
docker-up:
    docker compose up dotmd

# Start dotMD with bundled TEI and FalkorDB.
docker-up-bundled:
    docker compose --profile bundled up dotmd tei falkordb

# Stop containers.
docker-down:
    docker compose down

# Remove local Python/tool caches.
clean:
    find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache -o -name .mypy_cache -o -name .pyright \) -prune -exec rm -rf {} +
