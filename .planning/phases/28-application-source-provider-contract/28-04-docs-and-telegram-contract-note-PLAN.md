---
phase: "28"
plan: "04"
type: execute
wave: 4
depends_on:
  - "28-01"
  - "28-02"
  - "28-03"
files_modified:
  - docs/mcp-telegram-source-contract.md
  - docs/source-adapter-architecture.md
  - docs/architecture.md
  - .planning/phases/28-application-source-provider-contract/28-04-SUMMARY.md
autonomous: true
requirements: ["R3", "R4", "R8"]
requirements_addressed: ["R3", "R4", "R8"]
must_haves:
  truths:
    - "D-02: Docs state Telegram is the first proof source, while the contract remains reusable for Slack, Notion, PDFs, and other sources."
    - "D-03: Docs state dotMD must not read mcp-telegram private SQLite tables directly."
    - "D-07/D-08: Docs show checkpoint_cursor persisted only after local transaction success and distinguish it from next_cursor."
    - "D-19: Phase 28 includes a short mcp-telegram contract note with example payloads, not a full mcp-telegram implementation plan."
    - "D-20: The note maps Telegram dialog to SourceDocument, message to SourceUnit, export_changes with checkpoint_cursor, and read_unit_window with neighboring context."
    - "D-21: The note is concrete enough for Phase 29 planning without reopening the integration boundary."
    - "D-15: Docs keep delete/hidden/tombstone lifecycle deferred from the common provider contract."
    - "Full-reindex answer: docs explicitly say Phase 28 provider-contract work requires no dotmd index --force or full rebuild."
---

# Phase 28 Plan 04: Docs and Telegram Contract Note

<objective>
Close Phase 28 by documenting the minimal provider contract and the structured
`mcp-telegram` payload boundary that Phase 29 should implement against.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Phase 29 reopens the Telegram/dotMD boundary | HIGH | Write concrete payload examples for source description, export changes, and read window. |
| Docs imply Telegram ingestion shipped in Phase 28 | HIGH | Explicitly say Phase 28 ships contract and fixtures only. |
| Docs encourage private SQLite coupling | HIGH | State dotMD consumes only structured source/export payloads, never mcp-telegram private tables. |
| Cursor semantics are ambiguous | HIGH | Include both `next_cursor` and `checkpoint_cursor` example and commit ordering rule. |
| Lifecycle semantics creep in | MEDIUM | Mark delete/hidden/tombstone common lifecycle as deferred. |
</threat_model>

<tasks>
<task id="1" type="execute">
<title>Write mcp-telegram source contract note</title>
<name>Write mcp-telegram source contract note</name>
<read_first>
- `.planning/phases/28-application-source-provider-contract/28-CONTEXT.md`
- `.planning/phases/28-application-source-provider-contract/28-RESEARCH.md`
- `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_client.py`
- `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/models.py`
- `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/sync_db.py`
- `docs/source-adapter-architecture.md`
</read_first>
<files>
- `docs/mcp-telegram-source-contract.md`
</files>
<action>
Create `docs/mcp-telegram-source-contract.md` as a concise implementation-contract note for Phase 29 planning.

Required content:
- Title: `# mcp-telegram Source Contract for dotMD`.
- Boundary statement: dotMD does not import Telethon, instantiate a Telegram API client, or read private `mcp-telegram` SQLite tables.
- Method list exactly:
  - `describe_source()`
  - `export_changes(cursor, limit)`
  - `read_unit_window(unit_ref, before, after)`
- Telegram mapping:
  - `namespace = "telegram"`
  - `SourceDocument.document_ref = "dialog:<dialog_id>"`
  - `SourceDocument.ref = "telegram:dialog:<dialog_id>"`
  - `SourceUnit.unit_ref = "dialog:<dialog_id>:message:<message_id>"`
- Example `export_changes` JSON containing:
  - `changes`
  - `document`
  - `unit`
  - `fingerprint`
  - `updated_at`
  - `order_key`
  - `metadata_json` with sender/topic/reply/edit fields where available
  - `next_cursor`
  - `checkpoint_cursor`
- Commit-order rule: dotMD persists `checkpoint_cursor` only after local source-document, source-unit fingerprint, binding/provenance, and index persistence succeeds.
- Example `read_unit_window` JSON with at least three neighboring Telegram messages.
- Scope exclusions: no full delete/hidden/tombstone lifecycle, no attachments/media, no direct Telegram API client in dotMD, no generic plugin marketplace.
</action>
<verify>
<automated>rg "checkpoint_cursor|read_unit_window|SourceDocument|SourceUnit|private .*SQLite|no direct Telegram API client" docs/mcp-telegram-source-contract.md</automated>
</verify>
<acceptance_criteria>
- `docs/mcp-telegram-source-contract.md` contains `# mcp-telegram Source Contract for dotMD`.
- `docs/mcp-telegram-source-contract.md` contains `describe_source()`.
- `docs/mcp-telegram-source-contract.md` contains `export_changes(cursor, limit)`.
- `docs/mcp-telegram-source-contract.md` contains `read_unit_window(unit_ref, before, after)`.
- `docs/mcp-telegram-source-contract.md` contains `checkpoint_cursor`.
- `docs/mcp-telegram-source-contract.md` contains `telegram:dialog:<dialog_id>`.
- `docs/mcp-telegram-source-contract.md` contains `dialog:<dialog_id>:message:<message_id>`.
- `docs/mcp-telegram-source-contract.md` contains `private` and `SQLite`.
- `docs/mcp-telegram-source-contract.md` contains `no direct Telegram API client`.
</acceptance_criteria>
</task>

<task id="2" type="execute">
<title>Update architecture docs and record verification summary</title>
<name>Update architecture docs and record verification summary</name>
<read_first>
- `docs/source-adapter-architecture.md`
- `docs/source-adapter-architecture-panel-review.md`
- `docs/architecture.md`
- `docs/mcp-telegram-source-contract.md`
- `.planning/REQUIREMENTS.md`
</read_first>
<files>
- `docs/source-adapter-architecture.md`
- `docs/architecture.md`
- `.planning/phases/28-application-source-provider-contract/28-04-SUMMARY.md`
</files>
<action>
Update docs to reflect the Phase 28 contract boundary and record verification evidence.

Required doc updates:
- Add a `Phase 28 Planned Contract` or `Phase 28 Delivered State` section to `docs/source-adapter-architecture.md` after the Phase 27 section.
- State the minimal method set: `describe_source`, `export_changes`, `read_unit_window`.
- State `export_changes` carries documents and units in one payload for Phase 28.
- State `checkpoint_cursor` is saved only after local persistence succeeds.
- State `next_cursor` is not durable progress by itself.
- State `SourceUnit` is the provider-owned recomputation boundary.
- State deletes/hidden/tombstones are deferred from the common contract.
- Link to `docs/mcp-telegram-source-contract.md`.
- Update `docs/architecture.md` Future Source Adapters section with a short Phase 28 paragraph.
- Create `.planning/phases/28-application-source-provider-contract/28-04-SUMMARY.md` with:
  - commands run;
  - grep evidence for the contract note;
  - pytest/typecheck/lint outcomes or documented pre-existing ratchet;
  - statement `no dotmd index --force`;
  - `Self-Check: PASSED` only when verification criteria are met.
</action>
<verify>
<automated>rg "Phase 28|checkpoint_cursor|read_unit_window|mcp-telegram-source-contract|no dotmd index --force" docs/source-adapter-architecture.md docs/architecture.md .planning/phases/28-application-source-provider-contract/28-04-SUMMARY.md</automated>
</verify>
<acceptance_criteria>
- `docs/source-adapter-architecture.md` contains `Phase 28`.
- `docs/source-adapter-architecture.md` contains `checkpoint_cursor`.
- `docs/source-adapter-architecture.md` contains `read_unit_window`.
- `docs/source-adapter-architecture.md` links `mcp-telegram-source-contract.md`.
- `docs/architecture.md` contains `Phase 28`.
- `.planning/phases/28-application-source-provider-contract/28-04-SUMMARY.md` contains `no dotmd index --force`.
- `.planning/phases/28-application-source-provider-contract/28-04-SUMMARY.md` contains `Self-Check: PASSED` only if checks pass or ratchet status is documented.
</acceptance_criteria>
</task>
</tasks>

<verification>
Run:

```bash
rg "checkpoint_cursor|read_unit_window|SourceDocument|SourceUnit|private .*SQLite|no direct Telegram API client" docs/mcp-telegram-source-contract.md
rg "Phase 28|checkpoint_cursor|read_unit_window|mcp-telegram-source-contract|no dotmd index --force" docs/source-adapter-architecture.md docs/architecture.md .planning/phases/28-application-source-provider-contract/28-04-SUMMARY.md
cd backend && uv run pytest tests/ingestion/test_application_source_provider.py tests/storage/test_metadata_m2m.py tests/ingestion/test_source_filesystem.py tests/api/test_service_search.py -q
just typecheck
just lint
```
</verification>

<success_criteria>
- R3 is documented as a generic provider contract with explicit cursor semantics.
- R4 has a concrete `mcp-telegram` source/export payload note for Phase 29.
- R8 has documented fixture and command-based verification.
- Phase 28 does not claim Telegram ingestion, lifecycle deletes, attachments/media, plugin UI, or direct Telegram API ownership.
</success_criteria>

## PLANNING COMPLETE
