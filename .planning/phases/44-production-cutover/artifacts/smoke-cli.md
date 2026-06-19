# Phase 44 Smoke: CLI

## Result

Status: **blocked**

## Finding

The CLI exposes `dotmd search --no-rerank`, but it does not expose a
standalone-SurrealDB backend switch. CLI search still initializes the normal
old-stack service path unless a caller uses the shadow-run devtools directly.

## Pass Condition Not Met

Phase 44 requires CLI search/read behavior against standalone SurrealDB with no
hidden fallback. That runtime path does not exist yet.
