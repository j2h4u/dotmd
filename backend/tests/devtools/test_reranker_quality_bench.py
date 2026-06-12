import json
from pathlib import Path

import pytest
from devtools.reranker_quality_bench import (
    DEFAULT_RERANKERS,
    BenchmarkConfig,
    find_chunks_for_file_contains,
    hit_at,
    load_labels,
    mrr_at,
    ndcg_at,
    resolve_labels,
    run_benchmark,
    summarize_rows,
)


class FakeMetadataStore:
    def __init__(self) -> None:
        self._chunks = {
            "doc.md": [
                {"index": 0, "heading_hierarchy": [], "text": "first text"},
                {"index": 1, "heading_hierarchy": [], "text": "target text"},
            ]
        }
        self._ids = ["cid-first", "cid-target"]

    def get_chunk_count_for_file(self, strategy: str, file_path: str) -> int:
        assert strategy == "strategy-v1"
        return len(self._chunks[file_path])

    def get_chunks_for_file_range(
        self, strategy: str, file_path: str, start: int, end: int
    ) -> list[dict]:
        assert strategy == "strategy-v1"
        return self._chunks[file_path][start:end]

    def get_chunk_ids_by_file(self, strategy: str, file_path: str) -> list[str]:
        assert strategy == "strategy-v1"
        assert file_path == "doc.md"
        return list(self._ids)

    def get_stored_payload(self, strategy: str, chunk_id: str) -> dict | None:
        assert strategy == "strategy-v1"
        if chunk_id == "cid-first":
            return {"text": "first text"}
        if chunk_id == "cid-target":
            return {"text": "target text"}
        return None

    def get_file_paths_for_chunk_ids(
        self, strategy: str, chunk_ids: list[str]
    ) -> dict[str, list[str]]:
        assert strategy == "strategy-v1"
        return {chunk_id: [f"{chunk_id}.md"] for chunk_id in chunk_ids}


class FakePipeline:
    def __init__(self) -> None:
        self.metadata_store = FakeMetadataStore()


class FakeSettings:
    chunk_strategy = "strategy-v1"


class FakeService:
    def __init__(self) -> None:
        self._settings = FakeSettings()
        self._pipeline = FakePipeline()
        self.calls: list[tuple[str, list[str], int, str, bool]] = []

    def compare_rerankers(
        self,
        query: str,
        reranker_names: list[str],
        top_k: int,
        mode: str,
        expand: bool,
    ) -> dict:
        self.calls.append((query, reranker_names, top_k, mode, expand))
        pool_ids = ["miss"] if query == "miss query" else ["miss", "rel", "maybe"]
        return {
            "shared_pool_size": len(pool_ids),
            "candidate_pool_chunk_ids": pool_ids,
            "rerankers": [
                {
                    "name": "fast",
                    "model_name": "fast-model",
                    "top_chunk_ids": ["miss", "rel", "maybe"],
                    "rerank_ms": 10.0,
                    "error": None,
                },
                {
                    "name": "slow",
                    "model_name": "slow-model",
                    "top_chunk_ids": ["miss", "other"],
                    "rerank_ms": 30.0,
                    "error": None,
                },
            ],
        }


def test_defaults_are_canonical() -> None:
    assert DEFAULT_RERANKERS == [
        "mmarco-minilm",
    ]


def test_metrics_treat_relevant_and_maybe_as_hits_with_graded_ndcg() -> None:
    ranked = ["miss", "maybe", "rel"]

    assert hit_at(ranked, {"rel"}, {"maybe"}, 1) == 0.0
    assert hit_at(ranked, {"rel"}, {"maybe"}, 3) == 1.0
    assert mrr_at(ranked, {"rel"}, {"maybe"}) == 0.5
    assert ndcg_at(ranked, {"rel"}, {"maybe"}) == pytest.approx(0.61990623)


def test_load_labels_and_resolve_file_contains(tmp_path: Path) -> None:
    labels_path = tmp_path / "labels.jsonl"
    labels_path.write_text(
        json.dumps(
            {
                "id": "rq-001",
                "category": "setup",
                "query": "query",
                "relevant": [{"file_path": "doc.md", "contains": "target"}],
                "maybe": [{"chunk_id": "maybe"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    service = FakeService()

    labels = load_labels(labels_path)
    resolved = resolve_labels(labels[0], service)

    assert find_chunks_for_file_contains(service, "doc.md", "target") == ["cid-target"]
    assert resolved.relevant_ids == {"cid-target"}
    assert resolved.maybe_ids == {"maybe"}


def test_run_benchmark_restores_model_order_and_marks_pool_miss(tmp_path: Path) -> None:
    labels_path = tmp_path / "labels.jsonl"
    labels_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "rq-001",
                        "category": "setup",
                        "query": "hit query",
                        "relevant": [{"chunk_id": "rel"}],
                        "maybe": [{"chunk_id": "maybe"}],
                    }
                ),
                json.dumps(
                    {
                        "id": "rq-002",
                        "category": "setup",
                        "query": "miss query",
                        "relevant": [{"chunk_id": "absent"}],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "rows.jsonl"
    summary = tmp_path / "summary.md"
    service = FakeService()
    config = BenchmarkConfig(
        labels=labels_path,
        output=output,
        summary=summary,
        rerankers=["slow", "fast"],
        top_n=3,
        commit="abc123",
    )

    summaries = run_benchmark(config, service=service)
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

    assert service.calls == [
        ("hit query", ["slow", "fast"], 3, "hybrid", True),
        ("miss query", ["slow", "fast"], 3, "hybrid", True),
    ]
    assert [row["model"] for row in rows[:2]] == ["slow", "fast"]
    assert [row["pool_miss"] for row in rows] == [False, False, True, True]
    assert rows[1]["candidate_pool_chunk_ids"] == ["miss", "rel", "maybe"]
    assert rows[1]["pool_miss"] is False
    assert summaries[0]["model"] == "fast"
    assert "Retrieval Gaps" in summary.read_text(encoding="utf-8")
    assert "chunk_strategy=strategy-v1" in summary.read_text(encoding="utf-8")


def test_summarize_rows_excludes_pool_misses_from_quality_averages() -> None:
    rows = [
        {
            "model": "a",
            "pool_miss": False,
            "hit_at_1": 1.0,
            "hit_at_3": 1.0,
            "hit_at_5": 1.0,
            "mrr_at_10": 1.0,
            "ndcg_at_10": 1.0,
            "rerank_ms": 100.0,
            "error": None,
        },
        {
            "model": "a",
            "pool_miss": True,
            "hit_at_1": 0.0,
            "hit_at_3": 0.0,
            "hit_at_5": 0.0,
            "mrr_at_10": 0.0,
            "ndcg_at_10": 0.0,
            "rerank_ms": 200.0,
            "error": None,
        },
    ]

    summary = summarize_rows(rows)

    assert summary[0]["valid_queries"] == 1
    assert summary[0]["pool_miss_count"] == 1
    assert summary[0]["hit_at_1"] == 1.0
