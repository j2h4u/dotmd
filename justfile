backend := "backend"

# Show available commands.
default:
    @just --list

# Install backend dev dependencies.
setup:
    cd {{backend}} && uv sync --extra dev

# Run local backend pytest suite. Live MCP checks are opt-in.
test *args:
    cd {{backend}} && uv run pytest -m "not e2e and not smoke" {{args}}

# Run live MCP e2e tests inside the running dotMD container.
test-e2e *args:
    docker exec dotmd sh -lc 'cd /mnt/home/repos/j2h4u/dotmd/backend && python -m pytest tests/e2e/ -p no:cacheprovider --tb=short -q {{args}}'

# Run production MCP/Funnel connectivity smoke against live containers.
test-mcp-remote *args:
    cd {{backend}} && uv run python devtools/mcp_remote_smoke.py {{args}}

# Run Ruff lint checks.
lint:
    cd {{backend}} && uv run ruff check src tests devtools

# Format Python code and apply safe Ruff fixes.
fmt:
    cd {{backend}} && uv run ruff format src tests devtools
    cd {{backend}} && uv run ruff check --fix src tests devtools

# Alias for fmt.
format: fmt

# Run Pyright ratchet against the checked-in baseline.
typecheck:
    cd {{backend}} && uv run python devtools/pyright_ratchet.py

# Run lint, typecheck, and tests.
check: lint typecheck test

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
