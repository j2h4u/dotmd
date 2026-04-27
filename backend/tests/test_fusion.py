"""Tests for fusion math and weight validation (Phase 999.12)."""
import math
import pytest


def _normalize(v):
    """Reference normalize for test assertions."""
    mag = math.sqrt(sum(x * x for x in v))
    return [x / mag for x in v] if mag > 0 else v


def test_normalize_unit_vector():
    """Normalized vector has magnitude 1.0."""
    from dotmd.ingestion.pipeline import IndexingPipeline
    v = [3.0, 4.0]
    n = IndexingPipeline._normalize_vector(v)
    mag = math.sqrt(sum(x * x for x in n))
    assert abs(mag - 1.0) < 1e-6


def test_normalize_zero_vector():
    """Zero vector returned unchanged (no division by zero)."""
    from dotmd.ingestion.pipeline import IndexingPipeline
    v = [0.0, 0.0, 0.0]
    n = IndexingPipeline._normalize_vector(v)
    assert n == [0.0, 0.0, 0.0]


class _FakePipeline:
    """Minimal shim to test _fuse_vectors without full pipeline init.

    _normalize_vector is a @staticmethod on IndexingPipeline, so we can
    delegate to it directly without needing full pipeline construction.
    """

    @staticmethod
    def _normalize_vector(v):
        from dotmd.ingestion.pipeline import IndexingPipeline
        return IndexingPipeline._normalize_vector(v)

    def _fuse_vectors(self, e_text, e_meta, weights):
        from dotmd.ingestion.pipeline import IndexingPipeline
        return IndexingPipeline._fuse_vectors(self, e_text, e_meta, weights)


def test_fuse_vectors_output_is_unit():
    """e_fused is a unit vector."""
    p = _FakePipeline()
    e_text = [1.0, 0.0, 0.0]
    e_meta = [0.0, 1.0, 0.0]
    weights = {"text": 0.7, "meta": 0.3}
    e_fused = p._fuse_vectors(e_text, e_meta, weights)
    mag = math.sqrt(sum(x * x for x in e_fused))
    assert abs(mag - 1.0) < 1e-6


def test_fuse_vectors_text_only_weight():
    """With weight text=1.0, meta=0.0, e_fused == normalize(e_text)."""
    p = _FakePipeline()
    e_text = [3.0, 4.0]
    e_meta = [1.0, 0.0]
    weights = {"text": 1.0, "meta": 0.0}
    e_fused = p._fuse_vectors(e_text, e_meta, weights)
    expected = _normalize(e_text)
    assert all(abs(a - b) < 1e-6 for a, b in zip(e_fused, expected))


def test_fuse_vectors_dimension_mismatch_raises():
    """Mismatched dimensions between e_text and e_meta must raise ValueError.

    Phase 999.12 change (addresses Codex MEDIUM review concern):
    _fuse_vectors raises ValueError on mismatch — silent truncation would be
    data corruption since both vectors must come from the same TEI model.
    """
    p = _FakePipeline()
    e_text = [1.0, 0.0, 0.0]
    e_meta = [0.0, 1.0]  # shorter — dimension mismatch
    weights = {"text": 0.7, "meta": 0.3}
    with pytest.raises(ValueError, match="dimension mismatch"):
        p._fuse_vectors(e_text, e_meta, weights)


def test_weight_validation_sum_must_be_one():
    """Settings rejects weights that don't sum to 1.0."""
    import os
    os.environ.setdefault("DOTMD_EMBEDDING_URL", "http://localhost:8088")
    from dotmd.core.config import Settings
    with pytest.raises(Exception, match="sum"):
        Settings(embedding_weights="text=0.5,meta=0.3")


def test_weight_validation_accepts_valid():
    """Settings accepts valid weights."""
    import os
    os.environ.setdefault("DOTMD_EMBEDDING_URL", "http://localhost:8088")
    from dotmd.core.config import Settings
    s = Settings(embedding_weights="text=0.7,meta=0.3")
    w = s.parsed_embedding_weights
    assert abs(w["text"] - 0.7) < 1e-9
    assert abs(w["meta"] - 0.3) < 1e-9


def test_weight_validation_invalid_format():
    """Settings rejects malformed weight entries."""
    import os
    os.environ.setdefault("DOTMD_EMBEDDING_URL", "http://localhost:8088")
    from dotmd.core.config import Settings
    with pytest.raises(Exception):
        Settings(embedding_weights="text_0.7_meta_0.3")


def test_weight_validation_requires_text_key():
    """Settings rejects weights missing the 'text' key.

    Addresses Codex MEDIUM review concern: validator must require both 'text' and
    'meta' keys. Accepting arbitrary keys would silently omit a component from fusion.
    """
    import os
    os.environ.setdefault("DOTMD_EMBEDDING_URL", "http://localhost:8088")
    from dotmd.core.config import Settings
    with pytest.raises(Exception, match="text"):
        Settings(embedding_weights="other=0.7,meta=0.3")


def test_weight_validation_requires_meta_key():
    """Settings rejects weights missing the 'meta' key."""
    import os
    os.environ.setdefault("DOTMD_EMBEDDING_URL", "http://localhost:8088")
    from dotmd.core.config import Settings
    with pytest.raises(Exception, match="meta"):
        Settings(embedding_weights="text=0.7,other=0.3")
