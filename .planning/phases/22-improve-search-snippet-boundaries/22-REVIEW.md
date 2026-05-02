---
phase: 22
status: clean
depth: standard
files_reviewed: 2
findings:
  critical: 0
  warning: 0
  info: 0
  total: 0
reviewed_at: "2026-05-02T18:36:30+05:00"
---

# Code Review — Phase 22

## Scope

- `backend/src/dotmd/search/fusion.py`
- `backend/tests/test_fusion.py`

## Result

No open issues found after review follow-up.

## Review Notes

- The initial review found one robustness issue in the new snippet focus logic:
  query-token offsets were computed against a lowercased copy of the selected
  text window. That could theoretically skew offsets for Unicode characters
  whose lowercase representation changes length.
- Fixed in commit `29c325a` by matching words on the original text and comparing
  `match.group(0).lower()` to the query-token set.
- Re-ran targeted pytest, ruff, pyright, recreated the `dotmd` container, and
  reran `just test-mcp-remote` after the fix.

## Checks

- `cd backend && uv run pytest tests/test_fusion.py -q` — passed.
- `cd backend && uv run ruff check src/dotmd/search/fusion.py tests/test_fusion.py` — passed.
- `cd backend && uv run pyright src/dotmd/search/fusion.py tests/test_fusion.py` — passed.
- `just test-mcp-remote` — passed after final container recreate.
