FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

# Layer 1 (rare): CPU-only PyTorch pinned for AVX-only CPUs
RUN pip install --no-cache-dir 'torch<2.5' --index-url https://download.pytorch.org/whl/cpu

# Layer 2 (rare): project dependencies — only rebuilds when pyproject.toml changes
COPY pyproject.toml ./
RUN mkdir -p src/dotmd && touch src/dotmd/__init__.py && \
    pip install --no-cache-dir -e . && \
    pip cache purge

# Layer 3 (frequent): application code only
COPY src/ ./src/

FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app

ENV DOTMD_INDEX_DIR=/dotmd-index
ENV DOTMD_DATA_DIR=/data

VOLUME ["/data", "/dotmd-index"]

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["dotmd"]
