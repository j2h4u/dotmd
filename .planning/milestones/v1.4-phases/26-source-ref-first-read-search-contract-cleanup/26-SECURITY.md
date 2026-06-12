---
phase: 26
phase_name: source-ref-first-read-search-contract-cleanup
status: secured
threats_open: 0
register_source: plan-time threat_model blocks
audited_at: 2026-05-06
---

# Phase 26 Security Threat Verification

## Verdict

SECURED. All plan-time threats from the three Phase 26 plans are mitigated in the current checkout and runtime evidence. No open security threats remain.

This audit covers the source-ref-first public contract cleanup for search, read, drill, MCP schemas, API/CLI output, documentation, and no-full-reindex deployment safety.

## Verification Evidence

| Evidence | Result |
| --- | --- |
| `just test tests/api/test_search_result_shape.py tests/api/test_service_search.py tests/mcp/test_search_tool.py` | PASS: 38 passed |
| `docker exec dotmd sh -c 'cd /mnt/home/repos/j2h4u/dotmd/backend && python -m pytest tests/e2e/test_mcp_smoke.py -q -p no:cacheprovider'` | PASS: 36 passed |
| `rg -n 'read\(file_path\|Only pass file_paths\|Returns ranked hits with source file_paths' docs backend/src/dotmd/mcp_server.py backend/tests/e2e/test_mcp_smoke.py` | PASS: no matches |
| `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-VERIFICATION.md` | PASS: 12/12 must-haves verified |

## Threat Register

| ID | Source | Threat | Severity | Status | Mitigation Evidence |
| --- | --- | --- | --- | --- | --- |
| SEC-26-01 | 26-01 PLAN | Search results still expose holder paths as public identity | HIGH | MITIGATED | `SearchResult` exposes `ref` and has no public path field in `backend/src/dotmd/core/models.py:205`; MCP `SearchHit` serializes only `ref`, `snippet`, `score`, optional `heading` in `backend/src/dotmd/mcp_server.py:75`; regression tests assert no `file_path`/`file_paths` public fields. |
| SEC-26-02 | 26-01 PLAN | Legacy chunks without provenance silently fall back to public `file_paths` | HIGH | MITIGATED | Search hydration raises on missing provenance in `backend/src/dotmd/search/fusion.py:296`; count/backfill helpers are metadata-only and idempotent in `backend/src/dotmd/storage/metadata.py:448`; summaries record active strategy backfill from 19540 missing to 0 remaining. |
| SEC-26-03 | 26-01 PLAN | Deduped multi-holder chunks expose arbitrary source refs | HIGH | MITIGATED | Canonical provenance hydration orders by `chunk_id, namespace, document_ref` and uses first-wins population in `backend/src/dotmd/storage/metadata.py:427`; Phase 26 verification confirms deterministic canonical provenance tests. |
| SEC-26-04 | 26-01 PLAN | `read(ref)` reloads indexes or scans all metadata per request | HIGH | MITIGATED | `read()` resolves one source document and active-strategy chunk count/range through the initialized metadata store in `backend/src/dotmd/api/service.py:756`; no `load_index()` call appears in the read/drill path. |
| SEC-26-05 | 26-01 PLAN | Ref parsing mishandles filesystem paths containing colons | MEDIUM | MITIGATED | `_parse_ref()` uses `partition(":")`, rejects empty namespace/document refs, and preserves colons inside `document_ref` in `backend/src/dotmd/api/service.py:691`; `SearchResult` validation uses the same first-separator contract in `backend/src/dotmd/core/models.py:219`. |
| SEC-26-06 | 26-01 PLAN | Internal holder mechanics break while removing public paths | HIGH | MITIGATED | `Chunk.file_paths` remains internal in `backend/src/dotmd/core/models.py:145`; `chunk_file_paths_<strategy>` remains an internal holder table with comments in `backend/src/dotmd/storage/metadata.py:466`; docs preserve the internal holder rule. |
| SEC-26-07 | 26-02 PLAN | MCP tools still teach agents to use file paths | HIGH | MITIGATED | MCP instructions teach `search(query) -> ref`, `drill(ref)`, `read(ref,start,end)` in `backend/src/dotmd/mcp_server.py:123`; read/drill parameter descriptions require source refs from search results in `backend/src/dotmd/mcp_server.py:647` and `backend/src/dotmd/mcp_server.py:707`. |
| SEC-26-08 | 26-02 PLAN | `read` becomes overloaded with metadata and chunk content | MEDIUM | MITIGATED | `read()` returns content ranges and frontmatter, while `drill()` returns source metadata and chunk count as a separate API in `backend/src/dotmd/api/service.py:756` and `backend/src/dotmd/api/service.py:794`; MCP exposes separate tools. |
| SEC-26-09 | 26-02 PLAN | API/CLI lag behind MCP and preserve path-first public behavior | MEDIUM | MITIGATED | CLI search prints `r.ref` in `backend/src/dotmd/cli.py:144`; FastAPI `/search` delegates to the ref-first service model per Phase 26 verification; no FastAPI read route exists. |
| SEC-26-10 | 26-02 PLAN | Existing e2e smoke fails due pinned tool list drift | HIGH | MITIGATED | Live MCP smoke pins tools to `search`, `read`, `drill`, `feedback` and passed in the container: 36 passed. |
| SEC-26-11 | 26-02 PLAN | Error messages leave callers stuck after breaking change | HIGH | MITIGATED | MCP wraps read/drill `ValueError` into actionable tool errors containing `Action: pass a ref returned by search.` in `backend/src/dotmd/mcp_server.py:467`, `backend/src/dotmd/mcp_server.py:689`, and `backend/src/dotmd/mcp_server.py:728`; live smoke covers invalid refs. |
| SEC-26-12 | 26-03 PLAN | Tests pass locally but live MCP clients still see old schemas | HIGH | MITIGATED | Container-side live MCP smoke passed against the running `dotmd` container: 36 passed in 154.29s. |
| SEC-26-13 | 26-03 PLAN | Docs still teach `read(file_path)` or `file_paths` as public APIs | HIGH | MITIGATED | Docs grep gate found no stale public path-first instructions; remaining path references are filesystem ref construction or explicit internal-holder notes. |
| SEC-26-14 | 26-03 PLAN | Cleanup accidentally erases the internal holder-path invariants | HIGH | MITIGATED | Internal holder fields/tables remain in code and docs: `Chunk.file_paths`, `chunk_file_paths_<strategy>`, and file-range helpers are still used internally. |
| SEC-26-15 | 26-03 PLAN | Future Telegram work inherits graph `File` terminology | MEDIUM | MITIGATED | Source adapter docs distinguish filesystem compatibility from general source identity and state non-filesystem work should use SourceDocument/SourceUnit semantics. |
| SEC-26-16 | 26-03 PLAN | A hidden full-reindex requirement is discovered too late | HIGH | MITIGATED | Phase summaries and verification record metadata-only backfill/count evidence and no observed `dotmd index --force`; no full reindex was required or run. |
| SEC-26-17 | 26-03 PLAN | Invalid refs fail as protocol errors instead of recoverable tool errors | HIGH | MITIGATED | Live smoke covers malformed and nonexistent `read(ref)` plus invalid `drill(ref)` as tool-level errors with `Unknown source ref` and recovery action text. |

## Open Threats

None.

## Follow-Up

Run `$gsd-validate-phase 26` next if continuing the full post-execution gate sequence, then `$gsd-verify-work 26` for conversational UAT.
