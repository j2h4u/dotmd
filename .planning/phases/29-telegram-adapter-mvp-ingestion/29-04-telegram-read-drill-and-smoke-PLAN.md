---
phase: "29"
plan: "04"
type: tdd
wave: 4
depends_on:
  - "29-03"
files_modified:
  - backend/src/dotmd/core/config.py
  - backend/src/dotmd/api/service.py
  - backend/src/dotmd/cli.py
  - backend/tests/api/test_service_search.py
  - backend/tests/ingestion/test_telegram_ingestion.py
  - docs/mcp-telegram-source-contract.md
  - docs/source-adapter-architecture.md
autonomous: true
requirements: ["R4", "R5", "R7", "R8"]
requirements_addressed: ["R4", "R5", "R7", "R8"]
must_haves:
  truths:
    - "D-03: Resolver support accepts concrete Telegram message refs."
    - "D-04: read(ref) returns a window around the target message."
    - "D-05: drill(ref) exposes Telegram source metadata without filesystem frontmatter."
    - "D-10: Window/context provenance remains anchored to one concrete target message."
    - "D-14: Live smoke proves only the ingestion boundary."
    - "D-15: Full public search -> ref -> read/drill live smoke remains Phase 31 scope."
    - "D-16: Resolver tests include topic/reply metadata and duplicate short-message refs where useful."
    - "Review-HIGH: Message refs must resolve active bindings at dialog scope while preserving message-level target refs."
    - "Review-HIGH: Production smoke must specify how dotMD reaches the mcp-telegram daemon."
    - "Full-reindex answer: resolver/docs/smoke work must use existing Telegram ingest state and must not force a full index rebuild."
---

# Phase 29 Plan 04: Telegram Read/Drill Resolver And Smoke

<objective>
Add initial Telegram `read(ref)` and `drill(ref)` resolver support plus docs
and smoke commands that prove the Phase 29 ingestion boundary without claiming
Phase 31 public search quality is complete.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Telegram refs fall back into filesystem frontmatter reads | HIGH | Add Telegram-specific branches and tests proving no file path is required. |
| Phase 29 overclaims full search/read/drill live behavior | HIGH | Docs and smoke explicitly limit live validation to export/import/metadata/index state. |
| Inactive bindings can be read through Telegram resolver | HIGH | Reuse `_require_active_source_document` before Telegram read/drill resolution. |
| Message-level refs fail active-binding lookup | HIGH | Parse `telegram:dialog:<dialog_id>:message:<message_id>` into dialog `document_ref=dialog:<dialog_id>` for binding checks and target `unit_ref=dialog:<dialog_id>:message:<message_id>` for reads. |
| dotMD container cannot reach mcp-telegram during smoke | HIGH | Add `DOTMD_TELEGRAM_DAEMON_SOCKET`/`DOTMD_TELEGRAM_DAEMON_URL` configuration and verify the chosen path inside the dotMD container before claiming live smoke. |
| Window reads return whole dialogs | MEDIUM | Clamp default before/after windows and test target-centered output. |
| Operational smoke requires unsafe restart/reindex | MEDIUM | Use existing runtime boundary and a dry-run/limited ingest command; do not call `dotmd index --force`. |
</threat_model>

<tasks>
<task id="1" type="tdd">
<title>Add Telegram read/drill resolver tests</title>
<name>Add Telegram read/drill resolver tests</name>
<read_first>
- `backend/src/dotmd/api/service.py`
- `backend/tests/api/test_service_search.py`
- `backend/src/dotmd/core/models.py`
- `backend/src/dotmd/ingestion/telegram_provider.py`
- `.planning/phases/29-telegram-adapter-mvp-ingestion/29-CONTEXT.md`
</read_first>
<files>
- `backend/tests/api/test_service_search.py`
</files>
<behavior>
- `drill("telegram:dialog:-1001:message:42")` returns Telegram metadata without frontmatter.
- `read("telegram:dialog:-1001:message:42")` returns a target-centered message window.
- Inactive Telegram resource bindings reject both read and drill.
</behavior>
<action>
Extend `backend/tests/api/test_service_search.py` with Telegram resolver tests.

Concrete tests:
- Build a fake active `SourceDocument(namespace="telegram", document_ref="dialog:-1001", ref="telegram:dialog:-1001", title="Project Chat", source_uri="telegram://dialog/-1001", parser_name="telegram-message", document_type="dialog", metadata_json={"dialog_id": -1001, "dialog_name": "Project Chat"})`.
- Mock metadata store active binding lookup so `is_resource_binding_active("telegram", "dialog:-1001")` is `True`.
- Mock source document lookup so the service can resolve `telegram:dialog:-1001` from a message ref.
- Assert `_parse_telegram_message_ref("telegram:dialog:-1001:message:42")` returns document ref `dialog:-1001` and unit ref `dialog:-1001:message:42`.
- Assert active binding is checked with namespace `telegram` and resource/document ref `dialog:-1001`, not `dialog:-1001:message:42`.
- Provide a fake provider/window resolver returning units `41`, `42`, and `43`.
- Assert `drill()` payload has:
  - `ref == "telegram:dialog:-1001:message:42"` or an explicit `target_ref` with that value;
  - `document_ref == "dialog:-1001"` or metadata equivalent;
  - no `frontmatter` key, or `frontmatter == {}` if the existing payload contract requires the key.
- Assert `read()` payload includes message ids `41`, `42`, and `43` and marks message `42` as target.
- Assert `read(ref, start=2, end=4)` maps to `before=2, after=4` for Telegram refs; if `end is None`, default to `before=5, after=5`.
- Assert inactive binding raises `ValueError("Unknown source ref: telegram:dialog:-1001:message:42")`.
- Add a stored-chunk fallback test for Phase 29: when no live provider is configured, `read()` can return indexed Telegram chunks from `get_chunks_by_source_unit_ref` and must mark the target unit ref.
</action>
<verify>
<automated>cd backend && uv run pytest tests/api/test_service_search.py -q</automated>
</verify>
<acceptance_criteria>
- `backend/tests/api/test_service_search.py` contains `telegram:dialog:-1001:message:42`.
- `backend/tests/api/test_service_search.py` contains `read_unit_window` or the final resolver method name.
- `backend/tests/api/test_service_search.py` asserts a three-message window.
- `backend/tests/api/test_service_search.py` asserts `dialog:-1001` is the active binding lookup key.
- `backend/tests/api/test_service_search.py` contains `get_chunks_by_source_unit_ref`.
- `backend/tests/api/test_service_search.py` asserts inactive Telegram refs raise `Unknown source ref`.
- The focused pytest command initially fails before implementation and exits 0 after implementation.
</acceptance_criteria>
</task>

<task id="2" type="tdd">
<title>Implement Telegram resolver and bounded ingest smoke command</title>
<name>Implement Telegram resolver and bounded ingest smoke command</name>
<read_first>
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/cli.py`
- `backend/src/dotmd/core/config.py`
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/src/dotmd/ingestion/telegram_provider.py`
- `backend/tests/api/test_service_search.py`
- `backend/tests/ingestion/test_telegram_ingestion.py`
</read_first>
<files>
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/cli.py`
- `backend/tests/api/test_service_search.py`
- `backend/tests/ingestion/test_telegram_ingestion.py`
</files>
<behavior>
- Service resolves Telegram message refs into document refs and unit refs.
- `read(ref)` returns a message window from the provider/client branch.
- `drill(ref)` returns Telegram source metadata and target message metadata.
- A bounded CLI or service smoke command can ingest a limited batch from the configured provider.
</behavior>
<action>
Implement resolver support and the smallest operator smoke surface.

Concrete target state:
- Add a parser helper such as `_parse_telegram_message_ref(ref: str) -> tuple[str, str]` where:
  - input `telegram:dialog:-1001:message:42`;
  - returns document_ref `dialog:-1001` and unit_ref `dialog:-1001:message:42`;
  - malformed Telegram refs raise `ValueError(f"Unknown source ref: {ref}")`.
- Add `_require_active_telegram_message_ref(ref: str) -> tuple[SourceDocument, str]` or equivalent wrapper so message refs check active binding on resource/document ref `dialog:<dialog_id>` and return the target unit ref separately.
- Add Telegram branches in `DotMDService.read()` and `DotMDService.drill()` before `_filesystem_path_for_source()`.
- For `read(ref)`, use this order:
  1. if a Telegram provider/client is configured, call `read_unit_window(unit_ref, before=<mapped start>, after=<mapped end>)`;
  2. otherwise return locally indexed chunks from `metadata_store.get_chunks_by_source_unit_ref("telegram", document_ref, unit_ref, self._settings.chunk_strategy)` so Phase 29 reads do not require live mcp-telegram availability after ingestion.
- Map Telegram `read(ref, start, end)` as window sizes, not filesystem chunk offsets: `before=max(0, min(start, 50))`; `after=5 if end is None else max(0, min(end, 50))`.
- Return a payload with:
  - `ref` as the target message ref;
  - `document_ref`;
  - `target_unit_ref`;
  - `chunks` or `units` containing message text, message_id, sender, sent_at, topic, reply metadata, and `target: true` on the anchor.
- For `drill(ref)`, return title/source_uri/document_type/parser_name plus Telegram metadata from `SourceDocument.metadata_json` and target unit metadata when available.
- Add settings:
  - `telegram_daemon_socket: Path | None = None` from `DOTMD_TELEGRAM_DAEMON_SOCKET`;
  - `telegram_daemon_url: str | None = None` from `DOTMD_TELEGRAM_DAEMON_URL`;
  - socket wins when both are set.
- Add a bounded CLI command `dotmd telegram ingest --limit 100 --dry-run` that builds the Telegram client from the configured socket/URL, calls `IndexingPipeline.ingest_application_source()`, and prints structured counts.
- If neither `DOTMD_TELEGRAM_DAEMON_SOCKET` nor `DOTMD_TELEGRAM_DAEMON_URL` is configured, the command exits non-zero with `Telegram daemon connection is not configured`.
</action>
<verify>
<automated>cd backend && uv run pytest tests/api/test_service_search.py tests/ingestion/test_telegram_ingestion.py -q</automated>
<automated>rg -n "telegram.*ingest|_parse_telegram_message_ref|read_unit_window|target_unit_ref|DOTMD_TELEGRAM_DAEMON_SOCKET|DOTMD_TELEGRAM_DAEMON_URL|get_chunks_by_source_unit_ref" backend/src/dotmd/api/service.py backend/src/dotmd/cli.py backend/src/dotmd/core/config.py backend/tests/api/test_service_search.py</automated>
</verify>
<acceptance_criteria>
- `backend/src/dotmd/api/service.py` contains `_parse_telegram_message_ref` or an equivalently named parser.
- `backend/src/dotmd/api/service.py` contains `read_unit_window`.
- `backend/src/dotmd/api/service.py` contains `get_chunks_by_source_unit_ref`.
- `backend/src/dotmd/api/service.py` does not call `_filesystem_path_for_source` for Telegram refs.
- `backend/src/dotmd/core/config.py` contains `telegram_daemon_socket` and `telegram_daemon_url`.
- `backend/src/dotmd/cli.py` contains `telegram` and `ingest` for the bounded smoke command or the final documented command name.
- `cd backend && uv run pytest tests/api/test_service_search.py tests/ingestion/test_telegram_ingestion.py -q` exits 0.
</acceptance_criteria>
</task>

<task id="3" type="execute">
<title>Document Phase 29 boundary and run focused smoke</title>
<name>Document Phase 29 boundary and run focused smoke</name>
<read_first>
- `docs/mcp-telegram-source-contract.md`
- `docs/source-adapter-architecture.md`
- `.planning/REQUIREMENTS.md`
- `.planning/phases/29-telegram-adapter-mvp-ingestion/29-CONTEXT.md`
- `backend/src/dotmd/cli.py`
</read_first>
<files>
- `docs/mcp-telegram-source-contract.md`
- `docs/source-adapter-architecture.md`
- `backend/tests/ingestion/test_telegram_ingestion.py`
</files>
<behavior>
- Docs describe what Phase 29 shipped and still defer Phase 31 public search/read/drill live smoke.
- Live smoke proves the ingestion boundary or records a clear no-data/runtime unavailable reason.
</behavior>
<action>
Update docs and run the smoke without broad rebuilds.

Concrete target state:
- `docs/mcp-telegram-source-contract.md` says the structured export API is implemented for Phase 29 once execution finishes.
- `docs/source-adapter-architecture.md` gains a `Phase 29 Delivered State` section.
- The delivered-state section includes:
  - Telegram dialog maps to `SourceDocument`;
  - Telegram message maps to `SourceUnit`;
  - message refs use `telegram:dialog:<dialog_id>:message:<message_id>`;
  - low-signal messages are stored but suppressed as standalone normal chunks;
  - Phase 31 still owns full public search/read/drill live smoke.
- Run the final smoke command chosen in task 2 with a small limit, e.g. `docker exec dotmd dotmd telegram ingest --limit 10 --dry-run` or the final equivalent.
- Before smoke, verify container connectivity with the exact configured path:
  - `docker exec dotmd printenv DOTMD_TELEGRAM_DAEMON_SOCKET DOTMD_TELEGRAM_DAEMON_URL`;
  - if socket is configured: `docker exec dotmd test -S "$DOTMD_TELEGRAM_DAEMON_SOCKET"`;
  - if URL is configured: `docker exec dotmd python - <<'PY'` with a small HTTP health/probe request to the configured URL, or use the implemented client probe if available.
- Production target for this plan is explicit: dotMD must reach the mcp-telegram daemon through `DOTMD_TELEGRAM_DAEMON_SOCKET` when the socket is bind-mounted into the dotMD container, or through `DOTMD_TELEGRAM_DAEMON_URL` when both services share a Docker network. The executor must choose and document the actual deployed value before claiming live smoke.
- Do not run `dotmd index --force`.
- If the live runtime has zero exportable synced messages or is unavailable, record the exact command and reason in the Phase 29 summary during execution; do not fabricate a pass.
</action>
<verify>
<automated>cd backend && uv run pytest tests/api/test_service_search.py tests/ingestion/test_telegram_ingestion.py -q</automated>
<automated>just typecheck</automated>
<automated>just lint</automated>
<manual>Run the final bounded Telegram ingest smoke command and capture structured counts or the exact no-data/runtime-unavailable reason.</manual>
</verify>
<acceptance_criteria>
- `docs/source-adapter-architecture.md` contains `Phase 29 Delivered State`.
- `docs/source-adapter-architecture.md` contains `telegram:dialog:<dialog_id>:message:<message_id>`.
- `docs/source-adapter-architecture.md` states Phase 31 owns full public search/read/drill live smoke.
- `docs/mcp-telegram-source-contract.md` contains `export_source_changes` or the final implemented method name.
- `docs/mcp-telegram-source-contract.md` still states dotMD does not read private `mcp-telegram` SQLite tables.
- `just typecheck` exits 0 or records a pre-existing ratchet in the execution summary.
- `just lint` exits 0 or records a pre-existing ratchet in the execution summary.
</acceptance_criteria>
</task>
</tasks>

<verification>
Run:

```bash
cd backend && uv run pytest tests/api/test_service_search.py tests/ingestion/test_telegram_ingestion.py -q
just typecheck
just lint
```

Then run the bounded live smoke command chosen during implementation.
</verification>

<success_criteria>
- Telegram refs can resolve through initial `read(ref)` and `drill(ref)` support without filesystem frontmatter.
- Docs accurately distinguish Phase 29 ingestion/resolver groundwork from Phase 31 full public search/read/drill smoke.
- Focused tests and bounded live smoke prove the MVP ingestion boundary.
</success_criteria>

## PLANNING COMPLETE
