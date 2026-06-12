---
phase: 33
slug: source-lifecycle-config-auth-cursor-boundary
status: verified
threats_open: 0
asvs_level: 1
created: 2026-05-08
verified: 2026-05-08
---

# Phase 33 - Security

Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Source lifecycle factory | Central construction boundary for source runtimes from registry descriptors, typed config, credential refs, cursor stores, and runtime helpers. | Source config, credential references, cursor state, source/provider objects |
| Credential provider | Runtime construction obtains access through a provider interface instead of adapter-owned secret reads. | Auth schema, credential references, delegated access labels |
| Cursor store | Application-source checkpoint persistence is behind a store that requires caller-owned transactions for commits. | Provider checkpoint cursors and checkpoint metadata |
| Telegram delegation | dotMD builds a delegated Telegram provider over the `mcp-telegram` socket and does not own Telegram API credentials. | Unix socket path, structured provider payloads, delegated auth reference |
| Filesystem source runtime | Filesystem discovery is constructed through lifecycle while filesystem paths remain internal holder mechanics. | Local path specs, excludes, filesystem source refs |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status | Evidence |
|-----------|----------|-----------|-------------|------------|--------|----------|
| T-33-01 | Tampering | Lifecycle implementation | mitigate | Lifecycle stays dotMD-native and does not import Airweave runtime code. | closed | `backend/src/dotmd/ingestion/source_lifecycle.py:11`; `rg -n "from airweave\|import airweave" backend/src backend/tests` returned no matches. |
| T-33-02 | Information disclosure | Local source config | mitigate | Config records separate typed config from credential refs; strict models forbid raw secret fields. | closed | `backend/src/dotmd/ingestion/source_lifecycle.py:29`, `backend/src/dotmd/ingestion/source_lifecycle.py:38`, `backend/src/dotmd/ingestion/source_lifecycle.py:49`, `backend/src/dotmd/ingestion/source_lifecycle.py:67`, `backend/tests/ingestion/test_source_lifecycle.py:257`. |
| T-33-03 | Elevation of privilege | Credential access | mitigate | Runtime construction calls a credential provider and returns delegated Telegram access through `mcp-telegram`. | closed | `backend/src/dotmd/ingestion/source_lifecycle.py:91`, `backend/src/dotmd/ingestion/source_lifecycle.py:152`, `backend/src/dotmd/ingestion/source_lifecycle.py:286`, `backend/tests/ingestion/test_source_lifecycle.py:130`. |
| T-33-04 | Denial of service | Runtime config validation | mitigate | Factory fails fast on missing filesystem paths, missing Telegram socket, namespace mismatch, and unsupported config. | closed | `backend/src/dotmd/ingestion/source_lifecycle.py:299`, `backend/src/dotmd/ingestion/source_lifecycle.py:312`, `backend/src/dotmd/ingestion/source_lifecycle.py:327`, `backend/src/dotmd/ingestion/source_lifecycle.py:337`, `backend/tests/ingestion/test_source_lifecycle.py:162`. |
| T-33-05 | Repudiation | Cursor commits | mitigate | Cursor commits require a caller-owned transaction and metadata storage is called with `conn=`; rollback tests prove no checkpoint is committed on failure. | closed | `backend/src/dotmd/ingestion/source_lifecycle.py:103`, `backend/src/dotmd/ingestion/source_lifecycle.py:187`, `backend/src/dotmd/ingestion/pipeline.py:490`, `backend/src/dotmd/ingestion/pipeline.py:685`, `backend/tests/ingestion/test_source_lifecycle.py:331`, `backend/tests/ingestion/test_telegram_ingestion.py:392`. |
| T-33-06 | Repudiation | Runtime observability | mitigate | Runtime bundle exposes descriptor, config, access result, cursor store, provider/source object, and metadata helpers for audits/tests. | closed | `backend/src/dotmd/ingestion/source_lifecycle.py:228`, `backend/src/dotmd/ingestion/source_lifecycle.py:272`, `backend/src/dotmd/ingestion/source_lifecycle.py:288`, `backend/tests/ingestion/test_source_lifecycle.py:130`. |
| T-33-07 | Tampering | Filesystem runtime migration | mitigate | Pipeline filesystem discovery and FileInfo bridging build through the lifecycle factory. | closed | `backend/src/dotmd/ingestion/pipeline.py:1298`, `backend/src/dotmd/ingestion/pipeline.py:1305`, `backend/src/dotmd/ingestion/pipeline.py:1362`, `backend/tests/ingestion/test_source_filesystem.py:283`. |
| T-33-08 | Spoofing | Filesystem public identity | mitigate | Filesystem refs remain `filesystem:<resolved_path>` and public source-ref-first behavior is asserted in lifecycle regression tests. | closed | `backend/src/dotmd/ingestion/pipeline.py:1370`, `backend/tests/ingestion/test_source_filesystem.py:301`, `.planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-VERIFICATION.md:36`. |
| T-33-09 | Repudiation | Filesystem cursor semantics | mitigate | Filesystem bundles expose a source adapter only and do not include an application provider or provider checkpoint commit path. | closed | `backend/src/dotmd/ingestion/source_lifecycle.py:269`, `backend/src/dotmd/ingestion/source_lifecycle.py:272`, `backend/tests/ingestion/test_source_lifecycle.py:121`. |
| T-33-10 | Tampering | Pipeline call sites | mitigate | Direct filesystem adapter construction is removed from the pipeline. | closed | `backend/src/dotmd/ingestion/pipeline.py:1300`, `backend/src/dotmd/ingestion/pipeline.py:1311`, `rg -n "FilesystemMarkdownSourceAdapter\(\)" backend/src/dotmd/ingestion/pipeline.py` returned no matches. |
| T-33-11 | Denial of service | Settings/config drift | mitigate | Lifecycle factory seeds filesystem config from live `Settings.indexing_paths` and `Settings.effective_indexing_exclude`. | closed | `backend/src/dotmd/ingestion/source_lifecycle.py:345`, `backend/src/dotmd/ingestion/source_lifecycle.py:350`, `backend/tests/ingestion/test_source_lifecycle.py:231`. |
| T-33-12 | Information disclosure | Retained artifact visibility | mitigate | Phase 33 does not alter active resource-binding gates; retained artifacts remain hidden unless actively bound. | closed | `.planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-VERIFICATION.md:36`, `.planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-VERIFICATION.md:88`, `backend/tests/api/test_service_search.py:269`. |
| T-33-13 | Tampering | Telegram construction | mitigate | Service and CLI build Telegram provider/runtime through lifecycle, and static checks reject direct construction in those call sites. | closed | `backend/src/dotmd/api/service.py:207`, `backend/src/dotmd/cli.py:461`, `backend/tests/api/test_service_search.py:50`, `rg -n "TelegramApplicationSourceProvider\(\|UnixSocketTelegramSourceClient\(" backend/src/dotmd/api/service.py backend/src/dotmd/cli.py` returned no matches. |
| T-33-14 | Information disclosure | Telegram credentials/API access | mitigate | Telegram access is delegated to `mcp-telegram`; raw Telegram credentials and direct Telegram/private SQLite access are absent from runtime source. | closed | `backend/src/dotmd/ingestion/source_lifecycle.py:360`, `backend/src/dotmd/ingestion/source_lifecycle.py:367`, `backend/tests/ingestion/test_source_lifecycle.py:231`, `rg -n "Telethon\|telegram\\.client\|sqlite.*telegram\|telegram.*sqlite" backend/src backend/tests` returned no matches. |
| T-33-15 | Repudiation | Telegram cursor commits | mitigate | Application-source ingest uses lifecycle cursor store and commits checkpoint only after local writes/vectors succeed inside the transaction. | closed | `backend/src/dotmd/ingestion/pipeline.py:456`, `backend/src/dotmd/ingestion/pipeline.py:685`, `backend/tests/ingestion/test_telegram_ingestion.py:375`, `backend/tests/ingestion/test_telegram_ingestion.py:392`. |
| T-33-16 | Denial of service | Optional Telegram startup | mitigate | Optional service startup calls `build_if_configured("telegram")` and returns `None` when the socket is not configured. | closed | `backend/src/dotmd/ingestion/source_lifecycle.py:299`, `backend/src/dotmd/api/service.py:207`, `backend/tests/api/test_service_search.py:50`. |
| T-33-17 | Tampering | Telegram refs/read windows | mitigate | Lifecycle wiring preserves existing Telegram message refs and read/drill behavior; focused service/provider tests passed. | closed | `.planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-VERIFICATION.md:18`, `.planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-VERIFICATION.md:88`, `backend/tests/api/test_service_search.py:607`. |
| T-33-18 | Repudiation | Lifecycle documentation | mitigate | Architecture docs record Phase 33 lifecycle boundaries while preserving source-ref-first and retained-artifact guardrails. | closed | `docs/source-adapter-architecture.md`, `docs/source-registry-airweave-mapping.md`, `.planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-VERIFICATION.md:59`. |

Status: open or closed. Disposition: mitigate, accept, or transfer.

---

## Accepted Risks Log

No accepted risks.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-05-08 | 18 | 18 | 0 | Codex |

## Security Audit 2026-05-08

| Metric | Count |
|--------|-------|
| Threats found | 18 |
| Closed | 18 |
| Open | 0 |

### Verification Commands

| Command | Result |
|---------|--------|
| `cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_telegram_ingestion.py tests/ingestion/test_telegram_provider.py tests/api/test_service_search.py tests/storage/test_metadata_m2m.py -q` | 128 passed, 71 warnings in 5.57s |
| `rg -n "from airweave\|import airweave" backend/src backend/tests` | no matches |
| `rg -n "Telethon\|telegram\\.client\|sqlite.*telegram\|telegram.*sqlite" backend/src backend/tests` | no matches |
| `rg -n "FilesystemMarkdownSourceAdapter\(\)" backend/src/dotmd/ingestion/pipeline.py` | no matches |
| `rg -n "TelegramApplicationSourceProvider\(\|UnixSocketTelegramSourceClient\(" backend/src/dotmd/api/service.py backend/src/dotmd/cli.py` | no matches |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-05-08
