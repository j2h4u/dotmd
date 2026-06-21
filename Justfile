set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

default:
    @just --list

# Human CRAP report over the full backend suite.
crap:
    cd backend && uv run pytest tests --ignore=tests/e2e --cov=src/dotmd --cov-report=term-missing --crap --crap-threshold=30 --crap-top-n=30

# CI/regression CRAP gate that checks the tracked baseline.
crap-check: crap-ratchet

# Regenerate the tracked CRAP baseline from the current coverage state.
crap-baseline:
    cd backend && coverage_file="$(mktemp /tmp/dotmd-crap-coverage.XXXXXX.json)"; \
    trap 'rm -f "$coverage_file"' EXIT; \
    uv run pytest tests --ignore=tests/e2e --cov=src/dotmd --cov-report=json:"$coverage_file"; \
    uv run python -m devtools.crap_ratchet --coverage "$coverage_file" --baseline reports/crap-baseline.json --src src/dotmd --threshold 30 --write-baseline

# Tighten the tracked CRAP baseline by clamping existing entries downward and adding
# only new entries that are at/below threshold.
crap-tighten:
    cd backend && coverage_file="$(mktemp /tmp/dotmd-crap-coverage.XXXXXX.json)"; \
    trap 'rm -f "$coverage_file"' EXIT; \
    uv run pytest tests --ignore=tests/e2e --cov=src/dotmd --cov-report=json:"$coverage_file"; \
    uv run python -m devtools.crap_ratchet --coverage "$coverage_file" --baseline reports/crap-baseline.json --src src/dotmd --threshold 30 --tighten-baseline

# Enforce the CRAP ratchet against the tracked baseline.
crap-ratchet:
    cd backend && coverage_file="$(mktemp /tmp/dotmd-crap-coverage.XXXXXX.json)"; \
    trap 'rm -f "$coverage_file"' EXIT; \
    uv run pytest tests --ignore=tests/e2e --cov=src/dotmd --cov-report=json:"$coverage_file"; \
    uv run python -m devtools.crap_ratchet --coverage "$coverage_file" --baseline reports/crap-baseline.json --src src/dotmd --threshold 30
