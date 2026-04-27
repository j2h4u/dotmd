"""End-to-end invariant: metadata-only change triggers exactly 1 TEI call (Phase 999.12).

This is the core correctness guarantee of Phase 999.12:
  tag update → 1 encode_batch call (for e_meta), NOT N calls (one per chunk).

No live TEI required — encode_batch is mocked.
"""
import pathlib
import pytest
from unittest.mock import MagicMock


def _write_md(path: pathlib.Path, title: str, tags: list, body: str) -> None:
    tags_yaml = "\n".join(f"  - {t}" for t in tags) if tags else ""
    tags_section = f"tags:\n{tags_yaml}\n" if tags else ""
    path.write_text(
        f"---\ntitle: {title}\n{tags_section}kind: document\n---\n{body}",
        encoding="utf-8",
    )


@pytest.fixture
def pipeline_settings(tmp_path):
    from dotmd.core.config import Settings
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    return Settings(
        data_dir=data_dir,
        index_dir=index_dir,
        embedding_url="http://localhost:18088",
        vector_backend="sqlite-vec",
        graph_backend="ladybugdb",
        extract_depth="structural",
        embedding_weights="text=0.7,meta=0.3",
    )


def test_metadata_only_reindex_exactly_one_tei_call(pipeline_settings):
    """After initial index, a tag-only change triggers exactly 1 encode_batch call.

    Phase 999.12 invariant: metadata-only fast path reads stored e_text BLOBs,
    calls encode_batch once for e_meta, recomputes e_fused locally.
    This test proves the O(1) TEI call property.

    PRECONDITION (addresses Codex HIGH review concern, Cycle 2):
    This invariant holds ONLY in steady-state: after a successful initial full index
    where e_text BLOBs for all chunks are stored in VecComponentStore.

    It does NOT hold in the following cases:
    - First run after schema version wipe (e_text BLOBs missing → fallback to full embed)
    - Fresh install with no prior index

    In those cases, the fast path detects missing e_text BLOBs and falls back to
    full re-embedding for the missing chunks (N+1 TEI calls instead of 1).
    This fallback is correct behavior, not a bug.

    Separate test `test_metadata_only_with_missing_etext_falls_back_to_full_embed`
    in test_pipeline_metadata.py covers the fallback path.
    """
    from dotmd.ingestion.pipeline import IndexingPipeline

    doc = pipeline_settings.data_dir / "test.md"
    _write_md(doc, "Test Document", ["alpha"], "This is the body text of the document.")

    dummy_vec = [0.1] * 768
    encode_calls = []

    def mock_encode_batch(texts):
        encode_calls.append(list(texts))
        return [dummy_vec[:] for _ in texts]

    pipeline = IndexingPipeline(pipeline_settings)
    mock_engine = MagicMock()
    mock_engine.encode_batch = mock_encode_batch
    mock_engine.get_tei_model_id = MagicMock(return_value="test-model")
    pipeline._semantic_engine = mock_engine

    # Steady-state precondition: initial full index must complete successfully,
    # storing e_text BLOBs in VecComponentStore for all chunks.
    encode_calls.clear()
    pipeline.index(pipeline_settings.data_dir)
    assert len(encode_calls) >= 1, "Initial index must call encode_batch at least once"

    # Verify precondition: VecComponentStore has e_text entries after initial index
    assert pipeline._vec_components.count() > 0, (
        "Precondition failed: VecComponentStore must have e_text entries after initial index. "
        "The 1-TEI-call invariant only holds in steady-state."
    )

    # Metadata-only change: add tags, body unchanged
    _write_md(doc, "Test Document", ["alpha", "beta", "gamma"], "This is the body text of the document.")

    encode_calls.clear()
    pipeline.index(pipeline_settings.data_dir)

    # THE INVARIANT (steady-state only — see precondition note above)
    assert len(encode_calls) == 1, (
        f"Metadata-only change MUST trigger exactly 1 encode_batch call (for e_meta). "
        f"Got {len(encode_calls)} calls: {encode_calls}. "
        f"Precondition: this test verifies steady-state behavior after initial index. "
        f"For post-wipe behavior, see test_metadata_only_with_missing_etext_falls_back_to_full_embed."
    )
    assert len(encode_calls[0]) == 1, (
        f"The single encode_batch call MUST encode exactly 1 text (the meta string title+tags). "
        f"Got {len(encode_calls[0])} texts: {encode_calls[0]}"
    )


def test_body_change_triggers_full_reembedding(pipeline_settings):
    """Body change triggers full re-embedding (chunk bodies + e_meta)."""
    from dotmd.ingestion.pipeline import IndexingPipeline

    doc = pipeline_settings.data_dir / "test.md"
    _write_md(doc, "Test Document", ["alpha"], "Original body content here.")

    dummy_vec = [0.1] * 768
    encode_calls = []

    def mock_encode_batch(texts):
        encode_calls.append(list(texts))
        return [dummy_vec[:] for _ in texts]

    pipeline = IndexingPipeline(pipeline_settings)
    mock_engine2 = MagicMock()
    mock_engine2.encode_batch = mock_encode_batch
    mock_engine2.get_tei_model_id = MagicMock(return_value="test-model")
    pipeline._semantic_engine = mock_engine2

    pipeline.index(pipeline_settings.data_dir)
    encode_calls.clear()

    _write_md(doc, "Test Document", ["alpha"], "Completely different body text now.")
    pipeline.index(pipeline_settings.data_dir)

    chunk_count = pipeline._conn.execute(
        f"SELECT COUNT(*) FROM chunks_{pipeline._strategy}"
    ).fetchone()[0]
    total_texts = sum(len(c) for c in encode_calls)
    assert total_texts >= chunk_count + 1, (
        f"Body change must encode chunk bodies ({chunk_count}) + e_meta (1). "
        f"Got {total_texts} total texts across {len(encode_calls)} calls."
    )
