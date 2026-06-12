
## Deferred — Pre-existing test failure

**tests/cli/test_search_output.py::TestRefRendering::test_renders_ref**
- Fails in both main repo (dev branch) and worktree at the same base commit
- Root cause: `DotMDService.search()` raises `SourceLifecycleConfigError("filesystem.paths is required")` in CLI test environment; the result has no `.candidates` attribute
- Out of scope: unrelated to Phase 36 work, pre-dates 36-01 commits
- Ticket: none created (single pre-existing failure, logged here per policy)
