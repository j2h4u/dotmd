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
    - "Review-HIGH: Telegram chunks intentionally use file_paths=[] and must be accessed through source provenance helpers, not file-path joins."
    - "Review-HIGH: A behavior-pinning test must prove save_chunks(file_paths=[]) works before Telegram ingestion relies on it."
    - "Review-HIGH: Telegram embeddings must keep the dual-component contract by embedding real source metadata text as e_meta; e_meta = e_text is forbidden."
    - "Review-HIGH: FTS5 receives explicit Telegram title/tags metadata through a named source-meta wrapper, not an empty-key convention."
    - "Review-HIGH: Initial bootstrap is a single-batch ingest per call in Phase 29; callers loop by re-invoking until next_cursor/checkpoint indicates no more rows."
    - "Review-HIGH: Metadata, FTS5, vector writes, delete cascades, and checkpoint commits must share one SQLite transaction or roll back together."
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
| M2M file-path joins drop Telegram chunks | HIGH | Store chunks with `file_paths=[]` and add provenance-based metadata helpers for Telegram chunk lookup/read/drill. |
| `save_chunks(file_paths=[])` assumption breaks Telegram persistence | HIGH | First pin existing empty-file-path behavior in a storage test before adding Telegram-specific ingestion assertions. |
| Embedding flow requires filesystem `FileInfo` | HIGH | Refactor metadata embedding to accept a generic metadata dict/source-meta object and embed Telegram metadata text separately; do not set `e_meta = e_text`. |
| Metadata, FTS5, and vector writes partially commit | HIGH | Use one `index.db` SQLite transaction for metadata, FTS5, vector rows, delete cascades, and checkpoint commit; tests inject vector failure and assert rollback. |
| Initial bootstrap silently imports only one page | HIGH | Phase 29 `ingest_application_source()` is explicitly single-batch per call; the CLI loop is explicit and smoke uses bounded single-batch semantics. |
| FTS5 title/tags degrade to accidental blanks | MEDIUM | Add a named `add_chunks_with_source_meta(chunks, title, tags_csv, conn=conn)` wrapper for Telegram chunks. |
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
- It can retrieve Telegram chunks by `namespace/document_ref/source_unit_ref` without using `chunk_file_paths_*`.
- It commits the provider checkpoint only after successful local persistence.
- Existing `save_chunks(file_paths=[])` behavior is pinned before Telegram ingestion relies on it.
- Metadata rows, FTS5 rows, vector rows, provenance rows, and checkpoint rows roll back together when vector writing fails.
</behavior>
<action>
Create `backend/tests/ingestion/test_telegram_ingestion.py` with a deterministic provider fixture.

Concrete test cases:
- `test_save_chunks_accepts_empty_file_paths_before_telegram_refactor`:
  - create one normal `Chunk` with `file_paths=[]` and non-empty text;
  - call `metadata_store.save_chunks([chunk])` before invoking any Telegram ingestion helper;
  - assert the chunk row exists in `chunks_<strategy>`;
  - assert no row is required in `chunk_file_paths_<strategy>`;
  - assert this test fails if `save_chunks()` rejects or short-circuits empty path lists.
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
- `test_telegram_chunks_with_empty_file_paths_are_saved_and_hydrated_by_provenance`:
  - substantive Telegram chunks have `file_paths == []`;
  - `get_chunks_by_source_unit_ref("telegram", "dialog:-1001", "dialog:-1001:message:42", strategy)` returns the chunk;
  - the same test proves no `chunk_file_paths_<strategy>` row is required.
- `test_telegram_fts_and_vector_index_without_fileinfo_frontmatter`:
  - FTS rows for Telegram chunks have non-empty `title == "Project Chat"` and `tags` containing `telegram`;
  - vector rows are written for Telegram chunk ids with separate text and metadata embeddings;
  - monkeypatch metadata embedding input and assert it contains Telegram metadata such as `Project Chat`, sender, topic, or `telegram`, not the full message text duplicated as metadata.
- `test_telegram_transaction_rolls_back_metadata_fts_vectors_and_checkpoint_on_vector_failure`:
  - monkeypatch vector persistence to raise after metadata/chunk preparation starts;
  - after the failure, assert no source document, source unit fingerprint, chunk row, provenance row, FTS row, vector row, or checkpoint row remains for the failed batch.
- `test_initial_bootstrap_single_batch_semantics_are_explicit`:
  - provider has more rows than `limit`;
  - one `ingest_application_source(provider, limit=2)` call processes exactly two rows and persists the returned `checkpoint_cursor`;
  - a second call resumes from that checkpoint and processes the next rows;
  - the test name or assertion text contains `single_batch`.
- `test_filesystem_and_telegram_chunks_coexist`:
  - one existing filesystem fixture chunk and one Telegram chunk can be saved and fetched in the same active strategy;
  - filesystem `get_chunks_for_file_range()` still returns only filesystem chunks.
</action>
<verify>
<automated>cd backend && uv run pytest tests/ingestion/test_telegram_ingestion.py -q</automated>
</verify>
<acceptance_criteria>
- `backend/tests/ingestion/test_telegram_ingestion.py` contains `get_source_checkpoint`.
- `backend/tests/ingestion/test_telegram_ingestion.py` contains `test_save_chunks_accepts_empty_file_paths_before_telegram_refactor`.
- `backend/tests/ingestion/test_telegram_ingestion.py` contains `get_source_unit_fingerprint`.
- `backend/tests/ingestion/test_telegram_ingestion.py` contains `dialog:-1001:message:42`.
- `backend/tests/ingestion/test_telegram_ingestion.py` asserts an unchanged replay skip count.
- `backend/tests/ingestion/test_telegram_ingestion.py` asserts a changed/edited message count of one.
- `backend/tests/ingestion/test_telegram_ingestion.py` asserts low-signal `"ok"` is not a standalone normal chunk.
- `backend/tests/ingestion/test_telegram_ingestion.py` contains `get_chunks_by_source_unit_ref`.
- `backend/tests/ingestion/test_telegram_ingestion.py` asserts Telegram chunk `file_paths == []`.
- `backend/tests/ingestion/test_telegram_ingestion.py` asserts FTS title `Project Chat` or equivalent dialog title is present for Telegram chunks.
- `backend/tests/ingestion/test_telegram_ingestion.py` asserts Telegram metadata embedding input is distinct from message text and contains dialog/sender/topic metadata.
- `backend/tests/ingestion/test_telegram_ingestion.py` asserts rollback removes metadata, FTS5, vector, provenance, and checkpoint rows after injected vector failure.
- `backend/tests/ingestion/test_telegram_ingestion.py` contains `single_batch` and asserts a one-call bootstrap does not drain all provider pages.
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
- Changed messages remove/replace old Telegram chunks for that source unit before writing the replacement chunk.
- One `ingest_application_source()` call processes one provider batch. It does not loop internally during Phase 29; repeated bootstrap pages require explicit re-invocation by the CLI/operator.
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
- Define counts precisely:
  - `skipped_units`: exported units whose stored fingerprint already matches and no chunk/embedding/FTS work ran;
  - `reused_units`: retained existing chunk/vector artifacts reused for the same changed/new unit without a new embedding call; in Phase 29 this may remain `0` unless a concrete reuse path exists.
- Add `IndexingPipeline.ingest_application_source(provider: ApplicationSourceProviderProtocol, *, limit: int = 500) -> ApplicationSourceIngestResult`.
- The method reads `checkpoint = metadata_store.get_source_checkpoint(namespace)`.
- It calls `provider.export_changes(checkpoint_cursor, limit, updated_after=checkpoint.metadata_json.get("updated_after"))` so edited already-exported messages are delivered.
- It passes `updated_after_cursor=checkpoint.metadata_json.get("updated_after_cursor")` so same-timestamp edit ties are delivered without duplication or loss.
- It processes exactly the returned batch once and then returns. It must not loop internally. The operator CLI may implement an explicit loop by calling this method repeatedly until the provider returns no `next_cursor` and no changed update watermark.
- For each change:
  - `upsert_source_document(change.document, conn=conn)`;
  - `upsert_resource_binding(ResourceBinding(namespace="telegram", resource_ref=change.document.document_ref, document_ref=change.document.document_ref, ref=change.document.ref, active=True, bound_at=..., content_fingerprint=change.document.content_fingerprint, metadata_fingerprint=change.document.metadata_fingerprint, source_unit_refs=[] or a bounded sample only, metadata_json={**change.document.metadata_json, "unit_count": <known count when available>}), conn=conn)`; do not append every message unit ref to the binding on every batch.
  - `upsert_source_unit_fingerprint(change.unit, conn=conn)` to classify changed vs unchanged.
- If `change.unit.metadata_json["standalone_search"] is False`, persist the unit fingerprint and binding but do not create a standalone chunk.
- For substantive units, create a `Chunk` with:
  - `file_paths=[]`;
  - `heading_hierarchy=[change.document.title]`;
  - `text` prefixed with compact metadata lines for dialog, sender, sent_at, topic, reply when present;
  - `kind="document"`;
  - `provenance=ChunkProvenance(namespace="telegram", document_ref=change.document.document_ref, ref=f"telegram:{change.unit.unit_ref}", source_unit_refs=[change.unit.unit_ref], chunk_strategy=self._strategy, parser_name="telegram-message")`.
- Add `SQLiteMetadataStore.get_chunks_by_source_unit_ref(namespace, document_ref, source_unit_ref, strategy)` using `chunk_source_provenance_<strategy>` joined to `chunks_<strategy>`; do not use `chunk_file_paths_<strategy>` for this helper.
- Add `SQLiteMetadataStore.delete_chunks_for_source_unit(namespace, document_ref, source_unit_ref, strategy, conn=conn)` or equivalent so a changed message can remove previous Telegram rows for that unit before replacement. The helper must atomically delete all matching rows from `chunks_<strategy>`, `chunk_source_provenance_<strategy>`, `chunk_file_paths_<strategy>` if any, FTS5, and sqlite-vec/vector tables.
- Persist Telegram chunks with `metadata_store.save_chunks(chunks)`; current `save_chunks()` permits `file_paths=[]` because it only iterates file paths for M2M inserts.
- Add or refactor a helper such as `_embed_meta_component(source_meta: FileInfo | Mapping[str, Any])` or `_embed_source_meta_component(metadata_text: str)` so Telegram metadata gets a real metadata embedding. The Telegram metadata text must be synthesized from `dialog title`, `sender_name`, `topic_title`, `sent_at`, `reply_to_msg_id`, and literal source label `telegram`. Do not set `e_meta = e_text`.
- For FTS5, add a narrowly named `add_chunks_with_source_meta(chunks, title, tags_csv, conn=conn)` wrapper that delegates to the existing `add_chunks` machinery without using `file_meta={"": ...}` as a Telegram convention. Do not index a mixed-dialog batch with one shared title.
- Wrap source document upserts, resource binding upserts, fingerprint writes, delete cascades, chunk saves, FTS5 writes, vector writes, and `commit_source_checkpoint()` in the same `index.db` transaction/connection. If any write fails, rollback must remove metadata, FTS5, vector, provenance, and checkpoint changes from the failed batch.
- Commit `metadata_store.commit_source_checkpoint("telegram", batch.checkpoint_cursor, conn=conn, metadata_json={**result_counts, "updated_after": batch.updated_after, "updated_after_cursor": batch.updated_after_cursor, "single_batch": True})` only after all local persistence for the batch succeeds.
- On exception, roll back and call `record_source_checkpoint_error("telegram", str(exc))`.
- Do not call `self.run()`, `dotmd index --force`, `_purge_file`, or filesystem discovery from this method.
</action>
<verify>
<automated>cd backend && uv run pytest tests/ingestion/test_telegram_ingestion.py tests/ingestion/test_source_filesystem.py tests/storage/test_metadata_m2m.py -q</automated>
<automated>rg -n "ingest_application_source|ApplicationSourceIngestResult|standalone_search|telegram-message|get_chunks_by_source_unit_ref|updated_after|updated_after_cursor|add_chunks_with_source_meta|single_batch" backend/src/dotmd/ingestion/pipeline.py backend/src/dotmd/ingestion/telegram_provider.py backend/src/dotmd/storage/metadata.py backend/tests/ingestion/test_telegram_ingestion.py</automated>
<automated>! rg -n "e_meta\\s*=\\s*e_text|file_meta=\\{\\\"\\\"" backend/src/dotmd/ingestion/pipeline.py backend/src/dotmd/storage/metadata.py</automated>
</verify>
<acceptance_criteria>
- `backend/src/dotmd/ingestion/pipeline.py` contains `def ingest_application_source`.
- `backend/src/dotmd/ingestion/pipeline.py` contains `ApplicationSourceIngestResult`.
- `backend/src/dotmd/ingestion/pipeline.py` contains `commit_source_checkpoint`.
- `backend/src/dotmd/ingestion/pipeline.py` contains `standalone_search`.
- `backend/src/dotmd/ingestion/pipeline.py` contains `telegram-message`.
- `backend/src/dotmd/ingestion/pipeline.py` contains `updated_after`.
- `backend/src/dotmd/ingestion/pipeline.py` contains `updated_after_cursor`.
- `backend/src/dotmd/ingestion/pipeline.py` contains `single_batch`.
- `backend/src/dotmd/ingestion/pipeline.py` or `backend/src/dotmd/storage/metadata.py` contains `add_chunks_with_source_meta`.
- `backend/src/dotmd/storage/metadata.py` contains `get_chunks_by_source_unit_ref`.
- `backend/src/dotmd/storage/metadata.py` contains `delete_chunks_for_source_unit` or the final equivalent helper.
- `backend/src/dotmd/ingestion/pipeline.py` does not contain `e_meta = e_text`.
- `backend/src/dotmd/ingestion/pipeline.py` does not contain `file_meta={"":`.
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
