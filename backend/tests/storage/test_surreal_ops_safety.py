"""Embedded SurrealDB safety-gate tests for Phase 38."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from dotmd.storage.surreal_ops import (
    SurrealEmbeddedSafetyReport,
    SurrealWriterGuard,
    assert_embedded_safety_gate_passed,
    force_release_surreal_writer_guard,
    probe_embedded_transaction_atomicity,
    probe_embedded_writer_safety,
    release_stale_surreal_writer_guard,
    write_embedded_safety_gate_report,
)


def test_probe_embedded_transaction_atomicity_commits_and_rolls_back(
    tmp_path: Path,
) -> None:
    """Embedded `surrealkv://` probe must verify commit visibility and rollback cleanup."""
    target_path = tmp_path / "embedded-atomicity.db"

    report = probe_embedded_transaction_atomicity(target_path)

    assert report.probe_kind == "embedded"
    assert report.target_url.startswith("surrealkv://")
    assert report.target_path == str(target_path)
    assert report.transaction_api_supported is False
    assert report.transaction_committed is True
    assert report.transaction_rollback_clean is True
    assert report.go_no_go is True
    assert report.control_result is False
    assert any("client-side transactions" in note.lower() for note in report.notes)


def test_writer_guard_blocks_second_writer_and_exposes_owner_metadata(
    tmp_path: Path,
) -> None:
    """A second same-target writer must be rejected until the first owner releases."""
    target_path = tmp_path / "embedded-writer.db"

    first = SurrealWriterGuard(target_path, owner_id="owner-a")
    second = SurrealWriterGuard(target_path, owner_id="owner-b")

    first_metadata = first.acquire()

    with pytest.raises(RuntimeError, match="already guarded"):
        second.acquire()

    assert second.read_current_owner() == first_metadata
    first.release()

    report = probe_embedded_writer_safety(target_path, stale_after_seconds=1.0)
    assert report.probe_kind == "writer"
    assert report.writer_guard_blocked_second_writer is True
    assert report.previous_owner_metadata is not None
    assert report.previous_owner_metadata["owner_id"] == "guard-owner-a"
    assert report.go_no_go is True


def test_release_stale_writer_guard_requires_ttl_expiry(tmp_path: Path) -> None:
    """Stale-owner recovery must refuse early release and allow post-TTL recovery."""
    target_path = tmp_path / "embedded-stale.db"
    stale_now = datetime.now(UTC) - timedelta(seconds=120)
    guard = SurrealWriterGuard(target_path, owner_id="stale-owner", now=stale_now)
    guard.acquire()

    with pytest.raises(RuntimeError, match="not stale"):
        release_stale_surreal_writer_guard(
            target_path,
            stale_after_seconds=300,
            now=datetime.now(UTC),
        )

    released = release_stale_surreal_writer_guard(
        target_path,
        stale_after_seconds=60,
        now=datetime.now(UTC),
    )

    assert released["owner_id"] == "stale-owner"
    assert not guard.guard_path.exists()


def test_force_release_requires_matching_target_path_and_records_previous_owner(
    tmp_path: Path,
) -> None:
    """Force-release must reject mismatched targets and report the evicted owner."""
    target_path = tmp_path / "embedded-force.db"
    guard = SurrealWriterGuard(target_path, owner_id="force-owner")
    guard.acquire()

    with pytest.raises(ValueError, match="target path mismatch"):
        force_release_surreal_writer_guard(
            target_path,
            expected_target_path=tmp_path / "different.db",
        )

    released = force_release_surreal_writer_guard(
        target_path,
        expected_target_path=target_path,
    )

    assert released["owner_id"] == "force-owner"
    assert released["target_path"] == str(target_path)
    assert not guard.guard_path.exists()


def test_write_embedded_safety_gate_report_blocks_when_only_control_passes(
    tmp_path: Path,
) -> None:
    """A WebSocket control result must never satisfy the embedded go/no-go gate."""
    embedded_fail = SurrealEmbeddedSafetyReport(
        probe_kind="embedded",
        target_url=f"surrealkv://{tmp_path / 'embedded.db'}",
        target_path=str(tmp_path / "embedded.db"),
        transaction_api_supported=False,
        transaction_committed=False,
        transaction_rollback_clean=False,
        go_no_go=False,
        blockers=["embedded rollback left partial records"],
        notes=["embedded probe failed"],
    )
    control_pass = SurrealEmbeddedSafetyReport(
        probe_kind="control",
        target_url="ws://localhost:8000/rpc",
        target_path="ws://localhost:8000/rpc",
        transaction_api_supported=True,
        transaction_committed=True,
        transaction_rollback_clean=True,
        control_result=True,
        go_no_go=True,
        notes=["WebSocket control result only"],
    )
    report_path = tmp_path / "38-05-EMBEDDED-SAFETY-GATE.md"

    merged = write_embedded_safety_gate_report(
        [embedded_fail, control_pass],
        report_path,
        evidence_paths=[str(tmp_path / "evidence.json")],
        downstream_plan="38-02",
    )

    text = report_path.read_text()
    assert merged.go_no_go is False
    assert "go_no_go: BLOCKED" in text
    assert "downstream_plan: 38-02" in text
    assert "ws://localhost:8000/rpc" in text
    assert "control result" in text.lower()
    assert "embedded rollback left partial records" in text

    with pytest.raises(RuntimeError, match="embedded safety gate failed"):
        assert_embedded_safety_gate_passed(merged)
