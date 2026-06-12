"""Integration tests for Plan 02 pipeline branching logic (Phase 999.12).

Covers:
- Fast path detection: metadata-only vs body change vs no change
- Schema version wipe: _check_schema_version() clears all 7 state components (atomic)
- e_text BLOB missing fallback: fast path falls back to full embed when BLOBs missing
- Weight change recompute: _check_weights_changed() recomputes e_fused without TEI
- CONCERN-01 regression: _embed_chunks() returns e_text (not e_fused) from cache

All tests mock encode_batch — no live TEI required.
"""

import pathlib
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

# ── Helpers ─────────────────────────────────────────────────────────────────


def _write_md(path: pathlib.Path, title: str, tags: list, body: str) -> None:
    tags_yaml = "\n".join(f"  - {t}" for t in tags) if tags else ""
    tags_section = f"tags:\n{tags_yaml}\n" if tags else ""
    path.write_text(
        f"---\ntitle: {title}\n{tags_section}kind: document\n---\n{body}",
        encoding="utf-8",
    )


@pytest.fixture
def minimal_settings(tmp_path):
    """Minimal settings for pipeline construction without live TEI."""
    from dotmd.core.config import Settings
    from dotmd.core.models import ExtractDepth

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    return Settings(
        data_dir=data_dir,
        index_dir=index_dir,
        embedding_url="http://localhost:18088",  # not real; mocked
        indexing_paths=[str(data_dir)],
        extract_depth=ExtractDepth.STRUCTURAL,
        embedding_weights="text=0.7,meta=0.3",
    )


def _make_pipeline_with_mock_encode(settings):
    """Construct IndexingPipeline with mocked encode_batch. Returns (pipeline, call_log)."""
    from dotmd.ingestion.pipeline import IndexingPipeline

    dummy_vec = [0.1] * 768
    call_log = []

    def mock_encode(texts):
        call_log.append(list(texts))
        return [dummy_vec[:] for _ in texts]

    pipeline = IndexingPipeline(settings)
    mock_engine = MagicMock()
    mock_engine.encode_batch = mock_encode
    mock_engine.get_tei_model_id = MagicMock(return_value="test-model")
    pipeline._semantic_engine = mock_engine
    return pipeline, call_log


# ── CONCERN-01 regression: _embed_chunks returns e_text, not e_fused ─────────


def test_embed_chunks_returns_etext_not_efused_from_cache(minimal_settings, tmp_path):
    """_embed_chunks() returns e_text from VecComponentStore, not e_fused from vec0.

    Regression test for OpenCode CONCERN-01 (Phase 999.12 Cycle 2 review):
    lookup_embeddings_by_text_hash() returns vec0 content which post-999.12 is
    e_fused, not e_text. If _embed_chunks() used that lookup, shared-content
    chunks would be double-fused, silently degrading search quality.

    This test pre-populates VecComponentStore with a known e_text vector and
    verifies that _embed_chunks() returns THAT vector (not the different value
    in vec0). A future developer adding lookup_embeddings_by_text_hash back
    to _embed_chunks() would break this test.
    """
    from dotmd.core.models import Chunk

    pipeline, call_log = _make_pipeline_with_mock_encode(minimal_settings)

    # Create a fake chunk
    fake_chunk_id = "test_chunk_001"
    fake_chunk_text = "The budget discussion focused on Q4 projections."

    # Known e_text vector — what VecComponentStore has
    e_text_known = [0.11, 0.22, 0.33] + [0.0] * 765  # 768-dim

    # Pre-populate VecComponentStore with e_text_known
    pipeline._vec_components.store(fake_chunk_id, "text", e_text_known)
    pipeline._conn.commit()

    # Simulate a Chunk object
    chunk = Chunk(
        chunk_id=fake_chunk_id,
        text=fake_chunk_text,
        file_paths=[pathlib.Path("test.md")],
        chunk_index=0,
    )

    # Call _embed_chunks with this chunk
    call_log.clear()
    e_text_vectors, _text_hashes = pipeline._embed_chunks([chunk])

    # Result must be e_text_known from VecComponentStore (not e_fused from vec0)
    assert len(e_text_vectors) == 1
    result = e_text_vectors[0]
    assert len(result) == 768

    # The result must match e_text_known (from VecComponentStore cache hit)
    assert abs(result[0] - 0.11) < 1e-5, (
        f"_embed_chunks() must return e_text from VecComponentStore (0.11), "
        f"not e_fused from vec0. Got: {result[0]:.4f}. "
        f"This is a regression for CONCERN-01 — double-fusion prevention."
    )

    # encode_batch must NOT have been called (cache hit)
    assert len(call_log) == 0, (
        f"encode_batch must not be called when e_text is in VecComponentStore. "
        f"Got {len(call_log)} calls."
    )


@pytest.mark.real_semantic_encode_batch
def test_embed_chunks_sends_context_prefixed_text_to_encode_boundary(
    minimal_settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_embed_chunks sends heading context through SemanticSearchEngine.encode_batch.

    This bypasses the global zero-vector encode_batch patch and records the
    controlled TEI boundary instead of starting a real TEI server.
    """
    from dotmd.core.models import Chunk
    from dotmd.ingestion.pipeline import IndexingPipeline

    pipeline = IndexingPipeline(minimal_settings)
    recorded_batches: list[list[str]] = []

    def record_tei_boundary(inputs: str | list[str]) -> list[list[float]]:
        batch = [inputs] if isinstance(inputs, str) else list(inputs)
        recorded_batches.append(batch)
        return [[0.1, 0.2, 0.3] for _ in batch]

    monkeypatch.setattr(pipeline._semantic_engine, "_encode_via_tei", record_tei_boundary)

    chunk = Chunk(
        chunk_id="d" * 64,
        file_paths=[minimal_settings.data_dir / "roadmap.md"],
        heading_hierarchy=["Product Roadmap"],
        level=1,
        text="Product Roadmap\n\nShip Phase 23 test contract.",
        chunk_index=0,
    )

    embeddings, text_hashes = pipeline._embed_chunks([chunk])

    assert recorded_batches == [["passage: Product Roadmap\n\nShip Phase 23 test contract."]]
    assert embeddings == [[0.1, 0.2, 0.3]]
    assert set(text_hashes) == {chunk.chunk_id}


# ── Fast path detection ──────────────────────────────────────────────────────


def test_metadata_only_change_calls_encode_batch_once(minimal_settings, tmp_path):
    """Tag-only change after initial index triggers exactly 1 encode_batch call (e_meta)."""
    doc = minimal_settings.data_dir / "test.md"
    _write_md(doc, "Test Doc", ["alpha"], "This is the body text of the document.")

    pipeline, call_log = _make_pipeline_with_mock_encode(minimal_settings)

    # Initial full index
    pipeline.index(minimal_settings.data_dir)
    call_log.clear()

    # Change only tags (body unchanged)
    _write_md(doc, "Test Doc", ["alpha", "beta", "gamma"], "This is the body text of the document.")
    pipeline.index(minimal_settings.data_dir)

    # Core invariant: exactly 1 encode_batch call, with 1 text (the meta string)
    assert len(call_log) == 1, (
        f"Metadata-only change must trigger exactly 1 encode_batch call, "
        f"got {len(call_log)}: {call_log}"
    )
    assert len(call_log[0]) == 1, (
        f"e_meta encode_batch call must encode 1 text, got {len(call_log[0])}"
    )


def test_body_change_triggers_chunk_reembedding(minimal_settings, tmp_path):
    """Body change triggers encode_batch for chunk bodies (more than 1 text total)."""
    doc = minimal_settings.data_dir / "test.md"
    _write_md(doc, "Test Doc", ["alpha"], "Original body content here.")

    pipeline, call_log = _make_pipeline_with_mock_encode(minimal_settings)
    pipeline.index(minimal_settings.data_dir)
    call_log.clear()

    _write_md(doc, "Test Doc", ["alpha"], "Completely different body text now.")
    pipeline.index(minimal_settings.data_dir)

    chunk_count = pipeline._conn.execute(
        f"SELECT COUNT(*) FROM chunks_{pipeline._strategy}"
    ).fetchone()[0]
    total_texts = sum(len(c) for c in call_log)
    assert total_texts >= chunk_count + 1, (
        f"Body change must encode chunk bodies ({chunk_count}) + e_meta (1). "
        f"Got {total_texts} total texts in {len(call_log)} calls."
    )


def test_no_change_skips_encode_batch(minimal_settings, tmp_path):
    """No change after initial index: encode_batch not called at all."""
    doc = minimal_settings.data_dir / "test.md"
    _write_md(doc, "No Change Doc", ["foo"], "Stable body text.")

    pipeline, call_log = _make_pipeline_with_mock_encode(minimal_settings)
    pipeline.index(minimal_settings.data_dir)
    call_log.clear()

    # Run again with no file changes
    pipeline.index(minimal_settings.data_dir)

    assert len(call_log) == 0, (
        f"No file change must not call encode_batch. Got {len(call_log)} calls."
    )


def test_both_body_and_metadata_change_uses_full_path(minimal_settings, tmp_path):
    """Simultaneous body + metadata change uses full embed path (not fast path)."""
    doc = minimal_settings.data_dir / "test.md"
    _write_md(doc, "Original Title", ["alpha"], "Original body content.")

    pipeline, call_log = _make_pipeline_with_mock_encode(minimal_settings)
    pipeline.index(minimal_settings.data_dir)
    call_log.clear()

    # Change both title AND body
    _write_md(doc, "New Title", ["alpha", "beta"], "New body content altogether.")
    pipeline.index(minimal_settings.data_dir)

    chunk_count = pipeline._conn.execute(
        f"SELECT COUNT(*) FROM chunks_{pipeline._strategy}"
    ).fetchone()[0]
    total_texts = sum(len(c) for c in call_log)
    assert total_texts >= chunk_count + 1, (
        f"Body + metadata change must trigger full embed path "
        f"(chunk bodies ({chunk_count}) + e_meta (1))."
    )


# ── e_text BLOB missing fallback ─────────────────────────────────────────────


def test_metadata_only_with_missing_etext_falls_back_to_full_embed(minimal_settings, tmp_path):
    """Fast path with missing e_text BLOBs falls back to full embed for those chunks."""
    doc = minimal_settings.data_dir / "test.md"
    _write_md(doc, "Doc", ["alpha"], "Body text for this document.")

    pipeline, call_log = _make_pipeline_with_mock_encode(minimal_settings)
    pipeline.index(minimal_settings.data_dir)

    # Manually wipe vec_components AND embedding_cache to simulate missing e_text BLOBs
    # with no global cache fallback — forces the full TEI encode path.
    pipeline._vec_components.delete_all()
    pipeline._embedding_cache.clear()
    pipeline._conn.commit()
    call_log.clear()

    # Trigger metadata-only change (body unchanged)
    _write_md(doc, "Doc", ["alpha", "newTag"], "Body text for this document.")
    pipeline.index(minimal_settings.data_dir)

    # Fallback must have re-embedded chunk bodies (more than just 1 call for e_meta)
    chunk_count = pipeline._conn.execute(
        f"SELECT COUNT(*) FROM chunks_{pipeline._strategy}"
    ).fetchone()[0]
    total_texts = sum(len(c) for c in call_log)
    assert total_texts >= chunk_count + 1, (
        f"Missing e_text BLOBs must trigger fallback to full embed. "
        f"Got {total_texts} total texts (expected >= {chunk_count + 1})."
    )


# ── Schema version wipe ──────────────────────────────────────────────────────


@pytest.mark.real_schema_check
def test_schema_version_wipe_clears_all_state(minimal_settings, tmp_path):
    """_check_schema_version() with stale version clears all 7 state components."""
    doc = minimal_settings.data_dir / "test.md"
    _write_md(doc, "Doc", ["alpha"], "Body.")

    pipeline, call_log = _make_pipeline_with_mock_encode(minimal_settings)
    pipeline.index(minimal_settings.data_dir)

    # Corrupt schema_version to simulate old-version deploy.
    # Must be a non-None value different from SCHEMA_VERSION to trigger the wipe path.
    vector_store = cast(Any, pipeline._vector_store)
    config_table = vector_store._CONFIG_TABLE
    pipeline._conn.execute(
        f"INSERT OR REPLACE INTO {config_table} (key, value) VALUES ('schema_version', '1')"
    )
    pipeline._conn.commit()

    # Run schema check — should wipe all state
    call_log.clear()
    pipeline._check_schema_version()

    # All 7 state components must be cleared
    # 1. embedding_cache
    cache_count = pipeline._conn.execute("SELECT COUNT(*) FROM embedding_cache").fetchone()[0]
    assert cache_count == 0, f"embedding_cache must be wiped (got {cache_count} rows)"

    # 2. vec_components
    comp_count = pipeline._vec_components.count()
    assert comp_count == 0, f"vec_components must be wiped (got {comp_count} rows)"

    # 3. chunk_tracker fingerprints (FileTracker uses ._table attribute)
    chunk_fp_count = pipeline._conn.execute(
        f"SELECT COUNT(*) FROM {pipeline._chunk_tracker._table}"
    ).fetchone()[0]
    assert chunk_fp_count == 0, f"chunk_tracker must be wiped (got {chunk_fp_count} rows)"

    # 4. meta_tracker fingerprints
    meta_fp_count = pipeline._conn.execute(
        f"SELECT COUNT(*) FROM {pipeline._meta_tracker._table}"
    ).fetchone()[0]
    assert meta_fp_count == 0, f"meta_tracker must be wiped (got {meta_fp_count} rows)"

    # 5. Schema version sentinel updated to current version
    row = pipeline._conn.execute(
        f"SELECT value FROM {config_table} WHERE key = 'schema_version'"
    ).fetchone()
    assert row is not None and row[0] == pipeline.SCHEMA_VERSION, (
        f"schema_version sentinel must be updated to {pipeline.SCHEMA_VERSION!r}"
    )

    # 6. vec0 fused vector table (delete_all() drops it entirely)
    vec0_exists = pipeline._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (vector_store._VEC_TABLE,),
    ).fetchone()
    assert vec0_exists is None, (
        f"vec0 table must be dropped by wipe (still exists: {vector_store._VEC_TABLE!r})"
    )

    # 7. vec_meta text_hash index (cleared by delete_all, not dropped)
    # Note: chunks_*, chunk_file_paths_*, and FTS5 are intentionally NOT cleared —
    # schema wipe only resets vector state so trickle can rebuild embeddings.
    vec_meta_count = pipeline._conn.execute(
        f"SELECT COUNT(*) FROM {vector_store._META_TABLE}"
    ).fetchone()[0]
    assert vec_meta_count == 0, f"vec_meta must be wiped (got {vec_meta_count} rows)"


# ── Weight change recompute ──────────────────────────────────────────────────


def test_weight_change_recomputes_fused_without_tei(minimal_settings, tmp_path):
    """Changing embedding weights recomputes e_fused from stored components, no TEI calls."""
    doc = minimal_settings.data_dir / "test.md"
    _write_md(doc, "Doc", ["alpha"], "Body text.")

    pipeline, call_log = _make_pipeline_with_mock_encode(minimal_settings)
    pipeline.index(minimal_settings.data_dir)
    call_log.clear()

    # Change weights in settings (simulate env var change on next startup)
    from dotmd.core.config import Settings
    from dotmd.core.models import ExtractDepth

    new_settings = Settings(
        data_dir=minimal_settings.data_dir,
        index_dir=minimal_settings.index_dir,
        embedding_url=minimal_settings.embedding_url,
        indexing_paths=list(minimal_settings.indexing_paths),
        extract_depth=ExtractDepth.STRUCTURAL,
        embedding_weights="text=0.6,meta=0.4",
    )
    pipeline._settings = new_settings

    # Trigger weight change detection
    pipeline._check_weights_changed()

    # encode_batch must NOT have been called (weight recompute is local math only)
    assert len(call_log) == 0, (
        f"Weight change must not call encode_batch. Got {len(call_log)} calls: {call_log}"
    )
