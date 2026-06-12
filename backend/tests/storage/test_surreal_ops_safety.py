"""Embedded SurrealDB safety-gate tests for Phase 38."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

import pytest

from dotmd.storage.surreal_ops import (
    SurrealDecisionCategory,
    SurrealEmbeddedSafetyReport,
    SurrealImportCounts,
    SurrealOpsDecisionInputs,
    SurrealWriterGuard,
    assert_embedded_safety_gate_passed,
    build_storage_recommendation,
    force_release_surreal_writer_guard,
    rehearse_current_stack_rollback,
    rehearse_surreal_backup_restore,
    run_surreal_full_pipeline_smoke,
    probe_embedded_transaction_atomicity,
    probe_embedded_writer_safety,
    release_stale_surreal_writer_guard,
    validate_surreal_cli_or_fallback_restore,
    verify_surreal_restore_counts,
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


def test_backup_restore_rehearsal_validates_fallback_counts(tmp_path: Path) -> None:
    """Missing `surreal` CLI is acceptable only when fallback restore is verified."""
    source = tmp_path / "source.surrealkv"
    source.write_text("surreal-store-copy", encoding="utf-8")
    expected = SurrealImportCounts(
        documents=1,
        chunks=2,
        embeddings=2,
        entities=1,
        relations=1,
        feedback=1,
    )
    source.with_name(f"{source.name}.counts.json").write_text(
        json.dumps(asdict(expected)),
        encoding="utf-8",
    )

    backup = rehearse_surreal_backup_restore(
        source,
        tmp_path / "restore",
        expected_counts=expected,
        cli_path=None,
    )

    assert backup.cli_available is False
    assert backup.method == "validated-fallback-copy"
    assert backup.restore.verified is True
    assert backup.restore.restored_counts == expected
    assert verify_surreal_restore_counts(expected, backup.restore.restored_counts) is True
    assert validate_surreal_cli_or_fallback_restore(backup).verified is True


def test_recommendation_blocks_migrate_on_parity_and_scale_failures() -> None:
    """D-01/D-02 require a non-migrate decision when retrieval parity failed."""
    inputs = SurrealOpsDecisionInputs(
        transform_coverage_passed=True,
        embedded_safety_passed=True,
        retrieval_parity_passed=False,
        scale_gate_passed=True,
        backup_restore_passed=True,
        current_stack_rollback_passed=True,
        same_corpus_smoke_passed=True,
        writer_coordination_passed=True,
        failure_categories=[
            SurrealDecisionCategory.FTS_WEIGHTING,
            SurrealDecisionCategory.HYBRID_RRF_GAP,
        ],
        source_reports=["38-03-RETRIEVAL-PARITY.md"],
    )

    decision = build_storage_recommendation(inputs)

    assert decision.recommendation == "reject"
    assert decision.failure_category == SurrealDecisionCategory.HYBRID_RRF_GAP
    assert "retrieval parity" in " ".join(decision.reasons).lower()


def test_current_stack_rollback_restores_copied_sqlite_and_falkor_originals(
    tmp_path: Path,
) -> None:
    """Rollback rehearsal must prove return to current SQLite/FalkorDB originals."""
    sqlite_original = tmp_path / "index.db"
    falkor_original = tmp_path / "falkor-export.json"
    with sqlite3.connect(sqlite_original) as conn:
        conn.execute("CREATE TABLE smoke (query TEXT)")
        conn.execute("INSERT INTO smoke (query) VALUES ('Hiveon')")
    falkor_original.write_text('{"nodes": 2, "relations": 1}', encoding="utf-8")

    report = rehearse_current_stack_rollback(
        sqlite_original=sqlite_original,
        falkor_export=falkor_original,
        restore_dir=tmp_path / "rollback",
        smoke_queries=["Hiveon"],
    )

    assert report.verified is True
    assert report.sqlite_restored is True
    assert report.falkor_restored is True
    assert report.current_stack_smoke_passed is True
    assert "SQLite/sqlite-vec/FTS5" in report.stack
    assert "FalkorDB" in report.stack


def test_full_pipeline_smoke_requires_all_gates() -> None:
    """Same-corpus smoke must assemble inventory, safety, import, parity, ops, and decision."""
    passing_inputs = SurrealOpsDecisionInputs(
        transform_coverage_passed=True,
        embedded_safety_passed=True,
        retrieval_parity_passed=True,
        scale_gate_passed=True,
        backup_restore_passed=True,
        current_stack_rollback_passed=True,
        same_corpus_smoke_passed=True,
        writer_coordination_passed=True,
        failure_categories=[],
        source_reports=[
            "38-01-INVENTORY.md",
            "38-05-EMBEDDED-SAFETY-GATE.md",
            "38-02-IMPORT-PROOF.md",
            "38-03-RETRIEVAL-PARITY.md",
            "38-04-OPERATIONS.md",
        ],
    )

    smoke = run_surreal_full_pipeline_smoke(passing_inputs)

    assert smoke.passed is True
    assert smoke.decision.recommendation == "migrate"
    assert smoke.covered_stages == [
        "inventory",
        "embedded safety gate",
        "transform import",
        "retrieval parity",
        "operations",
        "recommendation",
    ]
