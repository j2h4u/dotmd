set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

backend := "backend"

# Show available repo commands.
default:
    @just --list

# Install backend dev dependencies.
setup:
    cd {{backend}} && UV_LINK_MODE=hardlink uv sync --extra dev

# Compile Python sources for syntax errors.
_compile:
    cd {{backend}} && UV_LINK_MODE=hardlink uv run python -m compileall -q src devtools tests

# Check formatting without writing.
_fmt-check:
    cd {{backend}} && UV_LINK_MODE=hardlink uv run ruff format --check src tests devtools

# Run Ruff lint checks at the current dotMD baseline.
_lint:
    cd {{backend}} && UV_LINK_MODE=hardlink uv run ruff check src tests devtools

# Check import-layer architecture contracts.
_import-contracts:
    cd {{backend}} && UV_LINK_MODE=hardlink uv run lint-imports

# Check GitHub Actions workflow syntax and expressions.
_actionlint:
    cd {{backend}} && UV_LINK_MODE=hardlink uv run actionlint ../.github/workflows/*.yml

# Run Pyright as a hard zero-error gate.
_typecheck:
    cd {{backend}} && UV_LINK_MODE=hardlink uv run basedpyright

# Scan for dead code. Vendored Airweave is excluded because local deltas are
# tracked separately in vendor notes and should stay close to upstream shape.
_dead-code:
    cd {{backend}} && UV_LINK_MODE=hardlink uv run vulture src tests --min-confidence 65 --exclude "*/vendor/*"

# Strict Ruff hardening gate.
_lint-strict:
    cd {{backend}} && UV_LINK_MODE=hardlink uv run ruff check src tests devtools --select E4,E7,E9,F,I,B,BLE,UP,C4,PIE,ISC,RSE,FLY,RUF,PERF,SIM,PTH,DTZ,PGH,PLE,LOG,G,FURB,RET,N818 --ignore RUF001,RUF002,RUF003,ISC001,E501,B008,N802,N803,N806,SIM108

# Enforce the CRAP ratchet against the tracked baseline.
_crap-ratchet:
    cd {{backend}} && coverage_file="$(mktemp /tmp/dotmd-crap-coverage.XXXXXX.json)"; \
    trap 'rm -f "$coverage_file"' EXIT; \
    UV_LINK_MODE=hardlink uv run pytest tests --ignore=tests/e2e --cov=src/dotmd --cov-report=json:"$coverage_file"; \
    UV_LINK_MODE=hardlink uv run python -m devtools.crap_ratchet --coverage "$coverage_file" --baseline reports/crap-baseline.json --src src/dotmd --threshold 30

# Tighten the tracked CRAP baseline from the current coverage state.
_crap-tighten:
    cd {{backend}} && coverage_file="$(mktemp /tmp/dotmd-crap-coverage.XXXXXX.json)"; \
    trap 'rm -f "$coverage_file"' EXIT; \
    UV_LINK_MODE=hardlink uv run pytest tests --ignore=tests/e2e --cov=src/dotmd --cov-report=json:"$coverage_file"; \
    UV_LINK_MODE=hardlink uv run python -m devtools.crap_ratchet --coverage "$coverage_file" --baseline reports/crap-baseline.json --src src/dotmd --threshold 30 --tighten-baseline

# Run local backend pytest suite. Live MCP checks are opt-in.
test *args:
    cd {{backend}} && UV_LINK_MODE=hardlink uv run pytest -m "not e2e and not smoke" {{args}}

# Unit tests only.
unit *args:
    cd {{backend}} && UV_LINK_MODE=hardlink uv run pytest -q -m "not e2e and not smoke" {{args}}

# Run live MCP e2e tests inside the running dotMD container.
test-e2e *args:
    docker exec dotmd sh -lc 'cd /mnt/home/repos/j2h4u/dotmd/backend && python -m pytest -c tests/e2e/pytest.ini tests/e2e/ -p no:cacheprovider --tb=short -q {{args}}'

# Run production MCP/Funnel connectivity smoke against live containers.
test-mcp-remote *args:
    cd {{backend}} && UV_LINK_MODE=hardlink uv run python devtools/mcp_remote_smoke.py {{args}}

# Run Ruff lint checks.
lint: _lint

# Format Python code and apply safe Ruff fixes.
fmt:
    cd {{backend}} && UV_LINK_MODE=hardlink uv run ruff format src tests devtools
    cd {{backend}} && UV_LINK_MODE=hardlink uv run ruff check --fix src tests devtools

# Alias for fmt.
format: fmt

# Opt-in stricter basedpyright source gate.
typecheck-strict:
    cd {{backend}} && UV_LINK_MODE=hardlink uv run basedpyright src --warnings

# Non-mutating quality gate for GitHub CI.
ci: _fmt-check _lint-strict _typecheck _import-contracts _actionlint _compile _dead-code _crap-ratchet

# Local hot-path quality gate. CRAP ratchet auto-tightens here so agents do not
# need to remember a separate baseline maintenance command.
check: _fmt-check _lint-strict _typecheck _import-contracts _actionlint _compile _dead-code _crap-tighten

# Full local gate for agents before claiming completion.
verify: check

# Show external repo agenda that local tests cannot see.
agenda:
    @echo "== git =="
    @git status --short --branch
    @echo
    @echo "== open PRs =="
    @gh pr list --state open --limit 50
    @echo
    @echo "== open Dependabot alerts =="
    @gh api repos/j2h4u/dotmd/dependabot/alerts --paginate --jq '[.[] | select(.state == "open")] | length'
    @echo
    @echo "== recent main runs =="
    @gh run list --branch main --limit 8

# Hard external readiness gate for agents before saying "done".
ready:
    @test "$(git branch --show-current)" = "main" || { echo "Not on main"; exit 1; }
    @test -z "$(git status --porcelain)" || { echo "Working tree is dirty"; git status --short; exit 1; }
    @git fetch origin main --quiet
    @test "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" || { echo "main is not synced with origin/main"; exit 1; }
    @test "$(gh pr list --state open --limit 100 --json number --jq 'length')" = "0" || { echo "Open PRs remain:"; gh pr list --state open --limit 100; exit 1; }
    @test "$(gh api repos/j2h4u/dotmd/dependabot/alerts --paginate --jq '[.[] | select(.state == "open")] | length')" = "0" || { echo "Open Dependabot alerts remain"; exit 1; }
    @head="$(git rev-parse HEAD)"; \
    runs="$$(gh run list --branch main --limit 20 --json headSha,workflowName,status,conclusion)"; \
    HEAD="$$head" RUNS="$$runs" python -c 'import json, os, sys; head = os.environ["HEAD"]; runs = json.loads(os.environ["RUNS"]); missing = [wf for wf in ("CI", "CodeQL") if not any(r["headSha"] == head and r["workflowName"] == wf and r["status"] == "completed" and r["conclusion"] == "success" for r in runs)]; print("Missing green workflows for " + head + ": " + ", ".join(missing)) if missing else None; sys.exit(bool(missing))'
    @echo "ready: git clean, main synced, no open PRs, no Dependabot alerts, CI/CodeQL green"

# Explicit one-way ratchet tightening for focused CRAP baseline maintenance.
tighten: _crap-tighten

# Build the dotMD container image.
docker-build:
    docker compose build dotmd

# Start dotMD container.
docker-up:
    docker compose up dotmd

# Start dotMD with bundled TEI only; SurrealDB is external.
docker-up-bundled:
    docker compose --profile bundled up dotmd tei

# Stop containers.
docker-down:
    docker compose down

# Remove local Python/tool caches.
clean:
    find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache -o -name .mypy_cache -o -name .pyright \) -prune -exec rm -rf {} +
