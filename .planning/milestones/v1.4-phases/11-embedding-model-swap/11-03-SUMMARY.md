---
phase: 11-embedding-model-swap
plan: 03
subsystem: embeddings
tags: [pplx-embed, context-aware-encoding, superseded]

# Dependency graph
requires:
  - phase: 11-embedding-model-swap
    plan: 02
    provides: "Prefix-aware SemanticSearchEngine and two-model config fields"
provides:
  - "Historical record of context-aware indexing implementation"
  - "Closure artifact for superseded pplx-embed-context experiment"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns: [grouped-document-encoding, superseded-experiment-closeout]

key-files:
  created: []
  modified:
    - backend/src/dotmd/search/semantic.py
    - backend/src/dotmd/ingestion/pipeline.py

key-decisions:
  - "Context-aware grouped-chunk indexing was implemented for evaluation."
  - "The context-aware path was later removed as model-specific dead code during v1.4 closeout."
  - "E5-large remained the retained production embedding model for better Russian semantic quality."

requirements-completed: [EMBED-01]

# Metrics
completed: 2026-04-02
status: superseded
---

# Phase 11 Plan 03: Context-Aware Encoding Closeout

Plan 03 integrated the `pplx-embed-context-v1-0.6B` experiment: grouped chunks by
document, added a context-aware encoding path, and wired indexing to use grouped
document embeddings when configured.

That experiment was later superseded. The v1.4 roadmap closeout records the final
decision: E5-large was retained for production because it performed better on
Russian semantic quality, and the context-aware path was evaluated and removed as
model-specific dead code.

## Historical Implementation

- `f71b4ae feat(11-03): add context-aware encoding to SemanticSearchEngine`
- `acd4ad0 feat(11-03): grouped-chunk context-aware indexing in pipeline`

## Supersession / Removal

- `a85fbaf docs: close v1.4 milestone — Search Quality & Architecture shipped`
  records Phase 11 as complete and notes: `Context-aware encoding evaluated and removed`.
- Current source no longer contains `encode_batch_context`, `context_model_name`, or
  `AutoModel.from_pretrained` in `backend/src/dotmd`; those references remain only
  in historical planning artifacts.

## Outcome

The plan is closed for GSD accounting purposes as **superseded**:

- The work was implemented and evaluated.
- The production outcome was to keep E5-large.
- The experimental context-aware code path is intentionally absent from current source.

## Deviations from Plan

**[Scope outcome] Implementation did not remain in final production architecture**
- Found during: v1.4 closeout and later forensics.
- Issue: The original plan expected context-aware indexing to remain available.
- Final decision: remove it as model-specific dead code after evaluation.
- Impact: no open implementation work remains, but the summary artifact was missing and
  caused GSD progress routing to incorrectly treat Phase 11 as incomplete.

## Known Stubs

None. The current absence of context-aware code is intentional.

## Self-Check: PASSED

- Phase 11 now has 3 plans and 3 summaries.
- The summary reflects the actual production decision instead of reintroducing
  superseded code.
- ROADMAP.md already marks Phase 11/v1.4 as shipped.
