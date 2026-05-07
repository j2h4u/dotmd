---
phase: "29"
plan: "03"
type: tdd
wave: 3
depends_on:
  - "29-01"
  - "29-02"
files_modified:
  - backend/src/dotmd/ingestion/pipeline.py
  - backend/src/dotmd/ingestion/telegram_provider.py
  - backend/src/dotmd/storage/metadata.py
  - backend/tests/ingestion/test_telegram_ingestion.py
autonomous: true
requirements: ["R4", "R5", "R8"]
requirements_addressed: ["R4", "R5", "R8"]
must_haves:
  truths:
    - "D-01: Ingestion scope is all Telegram dialogs currently available/synced through mcp-telegram, as exported by the provider."
    - "D-02: dotMD consumes provider export payloads and focuses on ingestion, provenance, indexing, and resolver support."
    - "D-06: Source-unit fingerprints are keyed by message unit, not whole-dialog content."
    - "D-07: Word-count merge blocks are not primary index identity."
    - "D-08: Substantive messages are indexed as message-anchored chunks with compact Telegram context."
    - "D-09: Low-signal messages are persisted as SourceUnit fingerprints/provenance inputs but hidden from standalone normal search chunks."
    - "D-10: Anchored-context chunks keep the public ref anchored to one message and record every included source unit."
    - "D-14: Smoke and tests prove ingestion boundary state, not full public search quality."
    - "D-16: Tests cover short acknowledgements, duplicate short messages, rapid multi-person chats, topic/reply metadata, edited fingerprints, and unchanged replay."
    - "D-17: Executors may use Graphify output only as a navigation aid for affected modules."
    - "D-18: Any graph-derived finding must be verified against live source files before implementation."
    - "Full-reindex answer: this plan adds an incremental application-source ingest path; it must not call dotmd index --force or rebuild existing filesystem indexes."
---

# Phase 29 Plan 03: dotMD Telegram Ingestion

<objective>
Persist Telegram provider batches into dotMD metadata, chunk provenance, FTS,
vector storage, and checkpoint state while treating each message as the
recomputation boundary.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| One new message forces whole-dialog reindex | HIGH | Source-unit fingerprints classify unchanged message units before chunking/indexing. |
| Checkpoint commits before local persistence | HIGH | Commit checkpoint inside the successful transaction after source document, binding, fingerprint, chunk/provenance, FTS/vector work. |
| Low-signal units are dropped from provenance | HIGH | Store fingerprints/bindings for every unit; only suppress standalone normal chunks. |
| Telegram chunks accidentally become filesystem chunks | HIGH | Add a dedicated application-source ingest path and provenance namespace `telegram`. |
| Existing filesystem indexing regresses | HIGH | Run existing filesystem source tests and keep chunk file path behavior untouched. |
</threat_model>

<tasks>
<task id="1" type="tdd">
<title>Add Telegram ingestion persistence tests</title>
<name>Add Telegram ingestion persistence tests</name>
<read_first>
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/src/dotmd/ingestion/chunker.py`
- `backend/tests/ingestion/test_source_filesystem.py`
- `backend/tests/storage/test_metadata_m2m.py`
- `backend/tests/ingestion/test_telegram_provider.py`
- `.planning/phases/29-telegram-adapter-mvp-ingestion/29-CONTEXT.md`
</read_first>
<files>
- `backend/tests/ingestion/test_telegram_ingestion.py`
</files>
<behavior>
- Ingesting a Telegram batch persists a `SourceDocument` for the dialog.
- It creates an active `ResourceBinding` for the Telegram dialog/message scope.
- It persists `source_unit_fingerprints` for substantive and low-signal messages.
- It writes chunk provenance with namespace `telegram` and source-unit refs.
- It commits the provider checkpoint only after successful local persistence.
</behavior>
<action>
Create `backend/tests/ingestion/test_telegram_ingestion.py` with a deterministic provider fixture.

Concrete test cases:
- `test_ingest_telegram_batch_persists_documents_bindings_units_and_checkpoint`:
  - provider exports three messages: substantive message `42`, low-signal `"ok"` message `43`, substantive reply/topic message `44`;
  - after ingest, `get_source_document("telegram", "dialog:-1001")` is not `None`;
  - `is_resource_binding_active("telegram", "dialog:-1001")` is `True`;
  - `get_source_unit_fingerprint("telegram", "dialog:-1001", "dialog:-1001:message:42")` is not `None`;
  - same assertion for low-signal message `43`;
  - `get_source_checkpoint("telegram")["checkpoint_cursor"]` equals the provider checkpoint.
- `test_ingest_telegram_replay_skips_unchanged_units`:
  - first run reports `new_units == 3` or equivalent count;
  - second unchanged run reports `skipped_units == 3` and does not add duplicate chunks.
- `test_ingest_telegram_edit_reindexes_changed_unit_only`:
  - replay with changed fingerprint for message `42` reports exactly one changed/new unit and leaves messages `43` and `44` skipped.
- `test_low_signal_message_is_not_standalone_search_chunk`:
  - low-signal message fingerprint exists;
  - no chunk text equals only `"ok"` or equivalent standalone low-signal text.
</action>
<verify>
<automated>cd backend && uv run pytest tests/ingestion/test_telegram_ingestion.py -q</automated>
</verify>
<acceptance_criteria>
- `backend/tests/ingestion/test_telegram_ingestion.py` contains `get_source_checkpoint`.
- `backend/tests/ingestion/test_telegram_ingestion.py` contains `get_source_unit_fingerprint`.
- `backend/tests/ingestion/test_telegram_ingestion.py` contains `dialog:-1001:message:42`.
- `backend/tests/ingestion/test_telegram_ingestion.py` asserts an unchanged replay skip count.
- `backend/tests/ingestion/test_telegram_ingestion.py` asserts a changed/edited message count of one.
- `backend/tests/ingestion/test_telegram_ingestion.py` asserts low-signal `"ok"` is not a standalone normal chunk.
- The focused pytest command initially fails before implementation and exits 0 after implementation.
</acceptance_criteria>
</task>

<task id="2" type="tdd">
<title>Implement incremental Telegram ingestion path</title>
<name>Implement incremental Telegram ingestion path</name>
<read_first>
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/src/dotmd/ingestion/chunker.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/src/dotmd/core/models.py`
- `backend/src/dotmd/ingestion/telegram_provider.py`
- `backend/tests/ingestion/test_telegram_ingestion.py`
</read_first>
<files>
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/src/dotmd/ingestion/telegram_provider.py`
- `backend/tests/ingestion/test_telegram_ingestion.py`
</files>
<behavior>
- Ingestion processes provider batches incrementally from the stored checkpoint.
- Substantive messages are converted into message-anchored chunks with Telegram provenance.
- Unchanged messages skip chunk/embedding work.
- The method returns structured counts for discovered, new, changed, skipped, hidden, failed, and reused where available.
</behavior>
<action>
Add a focused application-source ingestion method to `IndexingPipeline`.

Concrete target state:
- Add `ApplicationSourceIngestResult` as a small dataclass or Pydantic model with integer keys:
  - `discovered`
  - `new_units`
  - `changed_units`
  - `skipped_units`
  - `hidden_units`
  - `failed_units`
  - `reused_units`
  - `chunks_indexed`
- Add `IndexingPipeline.ingest_application_source(provider: ApplicationSourceProviderProtocol, *, limit: int = 500) -> ApplicationSourceIngestResult`.
- The method reads `checkpoint = metadata_store.get_source_checkpoint(namespace)`.
- It calls `provider.export_changes(checkpoint_cursor, limit)`.
- For each change:
  - `upsert_source_document(change.document, conn=conn)`;
  - `upsert_resource_binding(ResourceBinding(namespace="telegram", resource_ref=change.document.document_ref, document_ref=change.document.document_ref, ref=change.document.ref, active=True, bound_at=..., content_fingerprint=change.document.content_fingerprint, metadata_fingerprint=change.document.metadata_fingerprint, source_unit_refs=[change.unit.unit_ref], metadata_json=change.document.metadata_json), conn=conn)`;
  - `upsert_source_unit_fingerprint(change.unit, conn=conn)` to classify changed vs unchanged.
- If `change.unit.metadata_json["standalone_search"] is False`, persist the unit fingerprint and binding but do not create a standalone chunk.
- For substantive units, create a `Chunk` with:
  - `file_paths=[]`;
  - `heading_hierarchy=[change.document.title]`;
  - `text` prefixed with compact metadata lines for dialog, sender, sent_at, topic, reply when present;
  - `kind="document"`;
  - `provenance=ChunkProvenance(namespace="telegram", document_ref=change.document.document_ref, ref=change.document.ref, source_unit_refs=[change.unit.unit_ref], chunk_strategy=self._strategy, parser_name="telegram-message")`.
- Reuse existing vector and FTS helpers for chunks where possible; if a helper requires file metadata, add a small Telegram-specific metadata payload instead of filesystem frontmatter.
- Commit `metadata_store.commit_source_checkpoint("telegram", batch.checkpoint_cursor, conn=conn, metadata_json=result_counts)` only after all local persistence for the batch succeeds.
- On exception, roll back and call `record_source_checkpoint_error("telegram", str(exc))`.
- Do not call `self.run()`, `dotmd index --force`, `_purge_file`, or filesystem discovery from this method.
</action>
<verify>
<automated>cd backend && uv run pytest tests/ingestion/test_telegram_ingestion.py tests/ingestion/test_source_filesystem.py tests/storage/test_metadata_m2m.py -q</automated>
<automated>rg -n "ingest_application_source|ApplicationSourceIngestResult|standalone_search|telegram-message" backend/src/dotmd/ingestion/pipeline.py backend/src/dotmd/ingestion/telegram_provider.py backend/tests/ingestion/test_telegram_ingestion.py</automated>
</verify>
<acceptance_criteria>
- `backend/src/dotmd/ingestion/pipeline.py` contains `def ingest_application_source`.
- `backend/src/dotmd/ingestion/pipeline.py` contains `ApplicationSourceIngestResult`.
- `backend/src/dotmd/ingestion/pipeline.py` contains `commit_source_checkpoint`.
- `backend/src/dotmd/ingestion/pipeline.py` contains `standalone_search`.
- `backend/src/dotmd/ingestion/pipeline.py` contains `telegram-message`.
- `backend/src/dotmd/ingestion/pipeline.py` does not call `dotmd index --force`.
- `cd backend && uv run pytest tests/ingestion/test_telegram_ingestion.py tests/ingestion/test_source_filesystem.py tests/storage/test_metadata_m2m.py -q` exits 0.
</acceptance_criteria>
</task>
</tasks>

<verification>
Run:

```bash
cd backend && uv run pytest tests/ingestion/test_telegram_ingestion.py tests/ingestion/test_source_filesystem.py tests/storage/test_metadata_m2m.py -q
```
</verification>

<success_criteria>
- Telegram source units persist with stable provenance and active bindings.
- Unchanged replay skips recomputation at message granularity.
- Low-signal messages remain retained source units without becoming standalone normal search hits.
- Checkpoint state advances only after local persistence succeeds.
</success_criteria>

## PLANNING COMPLETE
