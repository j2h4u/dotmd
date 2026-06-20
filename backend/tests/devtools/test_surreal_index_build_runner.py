from __future__ import annotations

import argparse
import json
from pathlib import Path

import devtools.surreal_index_build_runner as runner
from devtools.surreal_index_build_runner import (
    _index_name_present,
    _run_step_with_heartbeat,
    _snapshot_with_delta,
    _surreal_runtime_env_snapshot,
    _surrealkv_file_snapshot,
    _target_size_bytes,
    build_index_steps,
    build_parser,
)


def test_index_build_plan_orders_unique_guard_before_secondary_indexes() -> None:
    steps = build_index_steps("all", embedding_dimension=1024, hnsw_m=4, hnsw_ef=64)

    assert [step.name for step in steps] == [
        "embeddings_strategy_chunk_model_idx",
        "embeddings_strategy_model_idx",
        "embeddings_text_hash_idx",
        "embeddings_vector_hnsw",
    ]
    assert steps[0].statement.endswith("embedding_model UNIQUE;")
    assert steps[-1].statement == (
        "DEFINE INDEX embeddings_vector_hnsw ON TABLE embeddings FIELDS vector "
        "HNSW DIMENSION 1024 DIST COSINE TYPE F32 EFC 64 M 4;"
    )


def test_index_build_plan_threads_custom_vector_index_type_through_hnsw_steps() -> None:
    steps = build_index_steps(
        "hnsw",
        embedding_dimension=1024,
        hnsw_m=4,
        hnsw_ef=32,
        vector_index_type="f16",
        embedding_shard_count=2,
    )

    assert [step.statement for step in steps] == [
        "DEFINE INDEX embeddings_0_vector_hnsw ON TABLE embeddings_0 FIELDS vector "
        "HNSW DIMENSION 1024 DIST COSINE TYPE F16 EFC 32 M 4;",
        "DEFINE INDEX embeddings_1_vector_hnsw ON TABLE embeddings_1 FIELDS vector "
        "HNSW DIMENSION 1024 DIST COSINE TYPE F16 EFC 32 M 4;",
    ]


def test_index_build_plan_can_target_unique_guard_only() -> None:
    steps = build_index_steps("unique-only", embedding_dimension=1024)

    assert len(steps) == 1
    assert steps[0].name == "embeddings_strategy_chunk_model_idx"


def test_index_build_plan_can_target_sharded_hnsw_indexes() -> None:
    steps = build_index_steps(
        "hnsw",
        embedding_dimension=1024,
        hnsw_m=4,
        hnsw_ef=32,
        embedding_shard_count=3,
    )

    assert [step.name for step in steps] == [
        "embeddings_0_vector_hnsw",
        "embeddings_1_vector_hnsw",
        "embeddings_2_vector_hnsw",
    ]
    assert [step.table_name for step in steps] == ["embeddings_0", "embeddings_1", "embeddings_2"]
    assert steps[0].statement == (
        "DEFINE INDEX embeddings_0_vector_hnsw ON TABLE embeddings_0 FIELDS vector "
        "HNSW DIMENSION 1024 DIST COSINE TYPE F32 EFC 32 M 4;"
    )


def test_index_name_detection_accepts_raw_info_payload() -> None:
    payload = {
        "info": {
            "result": {
                "indexes": {
                    "embeddings_strategy_chunk_model_idx": "DEFINE INDEX ...",
                }
            }
        }
    }

    assert _index_name_present(payload, "embeddings_strategy_chunk_model_idx") is True
    assert _index_name_present(payload, "embeddings_text_hash_idx") is False


def test_build_parser_defaults_rebuild_existing_to_false() -> None:
    args = build_parser().parse_args([])

    assert args.rebuild_existing is False


def test_run_index_build_rebuilds_existing_indexes_when_flag_enabled(
    monkeypatch, tmp_path: Path
) -> None:
    step = build_index_steps("hnsw", embedding_dimension=1024)[0]
    calls: list[dict[str, str]] = []

    monkeypatch.setattr(runner, "build_index_steps", lambda *args, **kwargs: [step])

    def fake_run_info_with_heartbeat(**kwargs):
        return {
            "status": "applied",
            "info": {"result": {"indexes": {step.name: "DEFINE INDEX existing"}}},
        }

    def fake_run_statement_with_heartbeat(**kwargs):
        calls.append(
            {
                "operation": kwargs["operation"],
                "statement": kwargs["statement"],
                "statement_hash": kwargs["statement_hash"],
            }
        )
        return {
            "index_name": kwargs["index_name"],
            "operation": kwargs["operation"],
            "statement_hash": kwargs["statement_hash"],
            "status": "applied",
            "finished_at": "2026-06-20T00:00:00Z",
        }

    monkeypatch.setattr(runner, "_run_info_with_heartbeat", fake_run_info_with_heartbeat)
    monkeypatch.setattr(runner, "_run_statement_with_heartbeat", fake_run_statement_with_heartbeat)

    result = runner.run_index_build(
        argparse.Namespace(
            index_mode="hnsw",
            embedding_dimension=1024,
            hnsw_m=12,
            hnsw_ef=40,
            vector_index_type="F16",
            embedding_shard_count=1,
            target_url="surrealkv://ignored.db",
            target_namespace="dotmd",
            target_database="production",
            output_dir=tmp_path,
            heartbeat_seconds=1.0,
            timeout_seconds=5.0,
            no_print_heartbeat=True,
            rebuild_existing=True,
        )
    )

    plan = json.loads((tmp_path / "index-build-plan.json").read_text(encoding="utf-8"))
    results = json.loads((tmp_path / "index-build-results.json").read_text(encoding="utf-8"))

    assert result == 0
    assert plan["rebuild_existing"] is True
    assert [call["operation"] for call in calls] == ["remove_index", "define_index"]
    assert calls[0]["statement"] == f"REMOVE INDEX {step.name} ON TABLE {step.table_name};"
    assert results["status"] == "verified"
    assert results["results"][0]["rebuild_existing"] is True
    assert results["results"][0]["rebuild_remove_result"]["operation"] == "remove_index"
    assert results["results"][0]["operation"] == "define_index"


def test_run_index_build_keeps_existing_index_as_already_present_without_rebuild(
    monkeypatch, tmp_path: Path
) -> None:
    step = build_index_steps("hnsw", embedding_dimension=1024)[0]
    calls: list[dict[str, str]] = []

    monkeypatch.setattr(runner, "build_index_steps", lambda *args, **kwargs: [step])

    def fake_run_info_with_heartbeat(**kwargs):
        return {
            "status": "applied",
            "info": {"result": {"indexes": {step.name: "DEFINE INDEX existing"}}},
        }

    def fake_run_statement_with_heartbeat(**kwargs):
        calls.append({"operation": kwargs["operation"]})
        raise AssertionError("define/remove should not run when rebuild_existing is false")

    monkeypatch.setattr(runner, "_run_info_with_heartbeat", fake_run_info_with_heartbeat)
    monkeypatch.setattr(runner, "_run_statement_with_heartbeat", fake_run_statement_with_heartbeat)

    result = runner.run_index_build(
        argparse.Namespace(
            index_mode="hnsw",
            embedding_dimension=1024,
            hnsw_m=12,
            hnsw_ef=40,
            vector_index_type="F16",
            embedding_shard_count=1,
            target_url="surrealkv://ignored.db",
            target_namespace="dotmd",
            target_database="production",
            output_dir=tmp_path,
            heartbeat_seconds=1.0,
            timeout_seconds=5.0,
            no_print_heartbeat=True,
            rebuild_existing=False,
        )
    )

    results = json.loads((tmp_path / "index-build-results.json").read_text(encoding="utf-8"))

    assert result == 0
    assert calls == []
    assert results["status"] == "verified"
    assert results["results"][0]["status"] == "already_present"


def test_target_size_bytes_sums_surrealkv_directory(tmp_path: Path) -> None:
    target_dir = tmp_path / "target.surreal.db"
    nested = target_dir / "clog"
    nested.mkdir(parents=True)
    (target_dir / "manifest").write_bytes(b"abcd")
    (nested / "0001").write_bytes(b"abcdef")

    assert _target_size_bytes(f"surrealkv://{target_dir}") == 10


def test_surrealkv_file_snapshot_reports_clog_sizes_and_deltas(tmp_path: Path) -> None:
    target_dir = tmp_path / "target.surreal.db"
    clog = target_dir / "clog"
    manifest = target_dir / "manifest"
    clog.mkdir(parents=True)
    manifest.mkdir()
    (clog / "00000000000000000000.clog").write_bytes(b"a" * 10)
    (manifest / "00000000000000000000.manifest").write_bytes(b"b" * 4)

    first = _surrealkv_file_snapshot(f"surrealkv://{target_dir}")

    assert first is not None
    assert first["total_size_bytes"] == 14
    assert first["clog_total_size_bytes"] == 10
    assert first["largest_clog_file"] == {
        "path": "clog/00000000000000000000.clog",
        "size_bytes": 10,
    }

    (clog / "00000000000000000001.clog").write_bytes(b"c" * 7)
    second = _snapshot_with_delta(f"surrealkv://{target_dir}", first)

    assert second is not None
    assert second["delta_total_size_bytes"] == 7
    assert second["delta_clog_total_size_bytes"] == 7


def test_surreal_runtime_env_snapshot_records_surrealkv_limits(monkeypatch) -> None:
    monkeypatch.setenv("SURREAL_SURREALKV_MAX_SEGMENT_SIZE", "1073741824")
    monkeypatch.setenv("SURREAL_SYNC_DATA", "false")
    monkeypatch.setenv("UNRELATED_ENV", "ignored")

    assert _surreal_runtime_env_snapshot() == {
        "SURREAL_SURREALKV_MAX_SEGMENT_SIZE": "1073741824",
        "SURREAL_SYNC_DATA": "false",
    }


def test_opaque_index_timeout_writes_uncertain_result(
    monkeypatch, tmp_path: Path
) -> None:
    class _FakePipe:
        def read(self) -> str:
            return ""

    class _FakeProcess:
        stderr = _FakePipe()
        returncode = None

        def poll(self) -> None:
            return None

        def kill(self) -> None:
            self.returncode = -9

        def communicate(self, timeout: int | None = None) -> tuple[str, str]:
            return "", ""

    monkeypatch.setattr(
        "devtools.surreal_index_build_runner.subprocess.Popen",
        lambda *_args, **_kwargs: _FakeProcess(),
    )
    monkeypatch.setattr("devtools.surreal_index_build_runner.time.sleep", lambda _seconds: None)
    times = iter([0.0, 2.0])
    monkeypatch.setattr("devtools.surreal_index_build_runner.time.monotonic", lambda: next(times))
    step = build_index_steps("unique-only", embedding_dimension=1024)[0]

    result = _run_step_with_heartbeat(
        step=step,
        step_index=1,
        total_steps=1,
        target_url=f"surrealkv://{tmp_path / 'target.db'}",
        target_namespace="dotmd",
        target_database="phase43",
        output_dir=tmp_path,
        heartbeat_seconds=1.0,
        timeout_seconds=1.0,
        print_heartbeat=False,
    )

    assert result["status"] == "timed_out_uncertain"
    heartbeat = json.loads((tmp_path / "index-build-heartbeat.jsonl").read_text().splitlines()[0])
    assert heartbeat["state"] == "waiting_opaque_define_index"
    assert heartbeat["index_name"] == "embeddings_strategy_chunk_model_idx"
