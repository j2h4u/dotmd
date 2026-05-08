---
phase: 32
slug: source-capability-registry
status: verified
threats_open: 0
asvs_level: 1
created: 2026-05-08
register_authored_at_plan_time: true
---

# Phase 32 - Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Descriptor model boundary | Source descriptor payloads enter strict Pydantic models before registry use. | Source metadata, config schema, auth schema, cursor schema, capability flags |
| Registry/runtime boundary | Phase 32 registry entries describe source capabilities but must not construct providers, read credentials, or persist cursors. | Declarative descriptor metadata only |
| dotMD/mcp-telegram boundary | Telegram remains delegated to `mcp-telegram`; dotMD consumes provider payloads and does not own Telegram API auth. | Telegram source descriptions, exported source units, provider cursors |
| dotMD/Airweave reference boundary | Airweave is reference material for source catalog concepts, not a runtime dependency or copied implementation schema. | Public architecture documentation only |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-32-01 | Tampering | Capability vocabulary | mitigate | `SourceCapability(StrEnum)` defines the closed vocabulary and tests assert exact values. Evidence: `backend/src/dotmd/core/models.py:71`, `backend/tests/ingestion/test_source_registry.py:55`. | closed |
| T-32-02 | Elevation of privilege | Descriptor/runtime boundary | mitigate | Descriptor models and registry remain declarative with no provider construction methods. Evidence: `backend/src/dotmd/core/models.py:88`, `backend/src/dotmd/core/source_registry.py:8`, `docs/source-adapter-architecture.md:208`. | closed |
| T-32-03 | Tampering | Descriptor schemas | mitigate | Descriptor schema models use `ConfigDict(extra="forbid")` and concrete fields. Evidence: `backend/src/dotmd/core/models.py:91`, `backend/src/dotmd/core/models.py:102`, `backend/src/dotmd/core/models.py:120`, `backend/tests/ingestion/test_source_registry.py:85`. | closed |
| T-32-04 | Tampering | Schema field vocabulary | mitigate | `SOURCE_SCHEMA_FIELD_TYPES` constrains allowed field type strings and tests reject unknown values. Evidence: `backend/src/dotmd/core/models.py:83`, `backend/src/dotmd/core/models.py:109`, `backend/tests/ingestion/test_source_registry.py:93`. | closed |
| T-32-05 | Information disclosure | Auth/cursor schema boundary | mitigate | Auth and cursor schemas are descriptions only; docs state credentials and cursor commits remain Phase 33 scope. Evidence: `backend/src/dotmd/core/models.py:127`, `backend/src/dotmd/core/models.py:138`, `docs/source-adapter-architecture.md:221`. | closed |
| T-32-06 | Tampering | Default source registry | mitigate | `default_source_registry()` registers exactly filesystem and Telegram, with tests asserting both namespaces. Evidence: `backend/src/dotmd/ingestion/source_registry.py:106`, `backend/tests/ingestion/test_source_registry.py:147`. | closed |
| T-32-07 | Elevation of privilege | Telegram auth ownership | mitigate | Telegram auth is delegated to `mcp-telegram`; no direct Telegram API auth method is modeled in the descriptor. Evidence: `backend/src/dotmd/ingestion/source_registry.py:87`, `backend/tests/ingestion/test_source_registry.py:185`. | closed |
| T-32-08 | Tampering | Source capability claims | mitigate | Filesystem and Telegram capability sets are declared explicitly and tested. Evidence: `backend/src/dotmd/ingestion/source_registry.py:53`, `backend/src/dotmd/ingestion/source_registry.py:96`, `backend/tests/ingestion/test_source_registry.py:169`. | closed |
| T-32-09 | Tampering | Filesystem config schema | mitigate | Filesystem descriptor keeps `paths` required and `exclude` optional as typed `list[str]` fields. Evidence: `backend/src/dotmd/ingestion/source_registry.py:31`, `backend/src/dotmd/ingestion/source_registry.py:37`, `backend/tests/ingestion/test_source_registry.py:162`. | closed |
| T-32-10 | Repudiation | Source descriptor usefulness | mitigate | Seed descriptors include config, auth, cursor, capability, and metadata details rather than empty placeholders. Evidence: `backend/src/dotmd/ingestion/source_registry.py:17`, `backend/src/dotmd/ingestion/source_registry.py:65`, `backend/tests/ingestion/test_source_registry.py:155`. | closed |
| T-32-11 | Denial of service | Provider compatibility | mitigate | Existing provider protocol still returns `ApplicationSourceDescription`, avoiding forced lifecycle migration. Evidence: `backend/src/dotmd/ingestion/source_provider.py:14`, `backend/tests/ingestion/test_application_source_provider.py:152`. | closed |
| T-32-12 | Tampering | Descriptor/description compatibility | mitigate | `ApplicationSourceDescription.from_descriptor()` converts descriptors into the lightweight provider description shape. Evidence: `backend/src/dotmd/core/models.py:286`, `backend/tests/ingestion/test_source_registry.py:198`. | closed |
| T-32-13 | Denial of service | Telegram daemon compatibility | mitigate | Raw legacy daemon capability strings are still accepted by `ApplicationSourceDescription`. Evidence: `backend/src/dotmd/core/models.py:283`, `backend/tests/ingestion/test_application_source_provider.py:165`. | closed |
| T-32-14 | Tampering | Capability taxonomy migration | mitigate | Legacy capability aliases normalize `unit-window` and `incremental-export` to canonical Phase 32 values. Evidence: `backend/src/dotmd/core/models.py:269`, `backend/src/dotmd/core/models.py:302`, `backend/tests/ingestion/test_telegram_provider.py:193`. | closed |
| T-32-15 | Elevation of privilege | Compatibility bridge lifecycle boundary | mitigate | Compatibility work is limited to model conversion and normalization; docs keep provider factories, credential access, and cursor commits in Phase 33. Evidence: `backend/src/dotmd/core/models.py:286`, `docs/source-adapter-architecture.md:221`. | closed |
| T-32-16 | Tampering | Airweave concept mapping | mitigate | Airweave mapping doc includes field-by-field copied/adapted/rejected/deferred classifications. Evidence: `docs/source-registry-airweave-mapping.md:11`. | closed |
| T-32-17 | Elevation of privilege | Airweave runtime boundary | mitigate | Documentation states dotMD has no runtime Airweave dependency and rejects Airweave runtime subsystems. Evidence: `docs/source-registry-airweave-mapping.md:3`, `docs/source-registry-airweave-mapping.md:66`. Backend import scan found no `from airweave` or `import airweave` matches. | closed |
| T-32-18 | Repudiation | Registry/lifecycle documentation | mitigate | Architecture docs explicitly state Phase 33 owns lifecycle construction, credentials, factories, rate limits, and cursor commits. Evidence: `docs/source-adapter-architecture.md:221`. | closed |
| T-32-19 | Information disclosure | Public documentation examples | mitigate | Mapping and architecture docs use generic filesystem/Telegram source references, and no real dialog names or personal source details were added. Evidence: `docs/source-registry-airweave-mapping.md:1`, `docs/source-adapter-architecture.md:214`. | closed |

*Status: open - closed*
*Disposition: mitigate (implementation required) - accept (documented risk) - transfer (third-party)*

---

## Accepted Risks Log

No accepted risks.

---

## Unregistered Flags

No unregistered threat flags. Phase 32 summaries do not contain `## Threat Flags` sections.

---

## Security Audit 2026-05-08

| Metric | Count |
|--------|-------|
| Threats found | 19 |
| Closed | 19 |
| Open | 0 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-05-08 | 19 | 19 | 0 | Codex |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-05-08
