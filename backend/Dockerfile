# syntax=docker/dockerfile:1.7

FROM python:3.14-slim AS builder

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

# Layer 1 (rare): CPU-only PyTorch. pip does not read uv's [[tool.uv.sources]],
# so the Docker build must pin the CPU wheel explicitly; otherwise
# `.[local-ml]` can resolve PyPI's CUDA-enabled Linux torch wheel.
RUN --mount=type=cache,id=dotmd-pip-py314,target=/root/.cache/pip,sharing=locked \
    printf '%s\n' \
    'torch==2.12.1+cpu' \
    > /tmp/constraints.txt && \
    pip install \
      --extra-index-url https://download.pytorch.org/whl/cpu \
      -c /tmp/constraints.txt \
      'torch==2.12.1+cpu'

# Layer 2 (rare): project dependencies — only rebuilds when pyproject.toml changes
COPY pyproject.toml ./
RUN --mount=type=cache,id=dotmd-pip-py314,target=/root/.cache/pip,sharing=locked \
    mkdir -p src/dotmd && touch src/dotmd/__init__.py && \
    pip install \
      --extra-index-url https://download.pytorch.org/whl/cpu \
      -c /tmp/constraints.txt \
      -e '.[local-ml]'

# Layer 3 (frequent): application code only
COPY src/ ./src/

FROM python:3.14-slim

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.14/site-packages /usr/local/lib/python3.14/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

ENV DOTMD_INDEX_DIR=/dotmd-index
ENV DOTMD_DATA_DIR=/data

VOLUME ["/data", "/dotmd-index"]

RUN apt-get update && apt-get install -y --no-install-recommends curl libatomic1 && rm -rf /var/lib/apt/lists/*

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

ENTRYPOINT ["/app/start.sh"]
