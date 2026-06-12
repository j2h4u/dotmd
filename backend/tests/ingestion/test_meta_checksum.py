"""Tests for meta_checksum change detection invariants (Phase 999.12)."""

import pathlib

from dotmd.ingestion.reader import chunk_checksum, meta_checksum


def _write(path: pathlib.Path, title: str, tags: list, body: str) -> None:
    tags_yaml = "\n".join(f"  - {t}" for t in tags)
    path.write_text(
        f"---\ntitle: {title}\ntags:\n{tags_yaml}\n---\n{body}",
        encoding="utf-8",
    )


def test_meta_checksum_stable_on_body_change(tmp_path):
    """meta_checksum does not change when only body changes."""
    p = tmp_path / "test.md"
    _write(p, "My Title", ["foo", "bar"], "original body")
    mc1 = meta_checksum(p)
    _write(p, "My Title", ["foo", "bar"], "completely different body text here")
    mc2 = meta_checksum(p)
    assert mc1 == mc2, "meta_checksum must be stable across body-only changes"


def test_meta_checksum_changes_on_title_change(tmp_path):
    """meta_checksum changes when title changes."""
    p = tmp_path / "test.md"
    _write(p, "Original Title", ["foo"], "same body")
    mc1 = meta_checksum(p)
    _write(p, "Renamed Title", ["foo"], "same body")
    mc2 = meta_checksum(p)
    assert mc1 != mc2, "meta_checksum must change when title changes"


def test_meta_checksum_changes_on_tags_change(tmp_path):
    """meta_checksum changes when tags change."""
    p = tmp_path / "test.md"
    _write(p, "Title", ["alpha", "beta"], "same body")
    mc1 = meta_checksum(p)
    _write(p, "Title", ["alpha", "beta", "gamma"], "same body")
    mc2 = meta_checksum(p)
    assert mc1 != mc2, "meta_checksum must change when tags change"


def test_meta_checksum_tags_order_normalized(tmp_path):
    """meta_checksum is identical regardless of tag ordering in YAML."""
    p = tmp_path / "test.md"
    _write(p, "Title", ["beta", "alpha"], "body")
    mc1 = meta_checksum(p)
    _write(p, "Title", ["alpha", "beta"], "body")
    mc2 = meta_checksum(p)
    assert mc1 == mc2, "meta_checksum must be tag-order-independent (sorted)"


def test_meta_checksum_empty_frontmatter(tmp_path):
    """meta_checksum handles missing title and tags (None-safe).

    Addresses OpenCode LOW concern: meta_checksum must handle title=None and
    tags=None gracefully, using the same defensive pattern as embed_checksum
    (str(frontmatter.get("title", "")) and tags or []).
    """
    p = tmp_path / "empty_fm.md"
    # No title, no tags in frontmatter
    p.write_text("---\n---\nsome body text", encoding="utf-8")
    mc = meta_checksum(p)
    assert mc, "meta_checksum must return a non-empty hash for empty frontmatter"
    assert isinstance(mc, str), "meta_checksum must return a string"
    assert len(mc) == 64, "meta_checksum must return a 64-char blake3 hex digest"

    # Also verify stability: same empty frontmatter → same hash
    mc2 = meta_checksum(p)
    assert mc == mc2, "meta_checksum must be stable for empty frontmatter"


def test_chunk_checksum_changes_on_body_change(tmp_path):
    """chunk_checksum detects body changes (unchanged contract)."""
    p = tmp_path / "test.md"
    _write(p, "Title", ["foo"], "original body")
    cc1 = chunk_checksum(p)
    _write(p, "Title", ["foo"], "different body content")
    cc2 = chunk_checksum(p)
    assert cc1 != cc2


def test_chunk_checksum_stable_on_metadata_change(tmp_path):
    """chunk_checksum is stable when only title/tags change."""
    p = tmp_path / "test.md"
    _write(p, "Old Title", ["a"], "same body")
    cc1 = chunk_checksum(p)
    _write(p, "New Title", ["a", "b", "c"], "same body")
    cc2 = chunk_checksum(p)
    assert cc1 == cc2, "chunk_checksum must be stable across metadata-only changes"


def test_meta_and_chunk_orthogonal(tmp_path):
    """meta_checksum and chunk_checksum detect different dimensions of change."""
    p = tmp_path / "test.md"
    _write(p, "Title", ["foo"], "body")
    mc_orig = meta_checksum(p)
    cc_orig = chunk_checksum(p)

    # Body change: chunk_checksum changes, meta_checksum stable
    _write(p, "Title", ["foo"], "new body")
    assert chunk_checksum(p) != cc_orig
    assert meta_checksum(p) == mc_orig

    # Restore body, change title: meta_checksum changes, chunk_checksum stable
    _write(p, "New Title", ["foo"], "body")
    cc_after_title = chunk_checksum(p)
    mc_after_title = meta_checksum(p)
    assert mc_after_title != mc_orig
    assert cc_after_title == cc_orig


def test_embed_checksum_removed():
    """embed_checksum must not exist in reader (removed in Plan 02)."""
    import dotmd.ingestion.reader as r

    assert not hasattr(r, "embed_checksum"), (
        "embed_checksum must be removed from reader.py in Plan 02"
    )
