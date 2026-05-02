"""Canonical reranker quality benchmark runner for Phase 21."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotmd.api.service import DotMDService, format_elapsed_ms
from dotmd.core.config import Settings

PHASE = "21"
DEFAULT_RERANKERS = [
    "mmarco-minilm",
]

JsonRow = dict[str, Any]


class BenchmarkService(Protocol):
    """Minimal service surface used by the reranker quality benchmark."""

    _settings: Any
    _pipeline: Any

    def compare_rerankers(
        self,
        query: str,
        reranker_names: list[str],
        top_k: int,
        mode: str,
        expand: bool,
    ) -> Any:
        """Compare rerankers for one query."""
        ...


@dataclass(frozen=True)
class BenchmarkConfig:
    labels: Path
    output: Path
    summary: Path
    rerankers: list[str]
    mode: str = "hybrid"
    top_n: int = 10
    pool_size: int = 20
    commit: str | None = None


@dataclass(frozen=True)
class LabelCase:
    id: str
    category: str
    query: str
    relevant: list[dict[str, str]]
    maybe: list[dict[str, str]]


@dataclass(frozen=True)
class ResolvedLabels:
    relevant_ids: set[str]
    maybe_ids: set[str]

    @property
    def all_ids(self) -> set[str]:
        return self.relevant_ids | self.maybe_ids


def parse_rerankers(raw: str | None) -> list[str]:
    if raw is None or not raw.strip():
        return list(DEFAULT_RERANKERS)
    return [name.strip() for name in raw.split(",") if name.strip()]


def get_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def load_labels(path: Path) -> list[LabelCase]:
    labels: list[LabelCase] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            if not raw.get("id") or not raw.get("query") or not raw.get("relevant"):
                raise ValueError(f"invalid label row at line {line_number}: id/query/relevant required")
            labels.append(
                LabelCase(
                    id=str(raw["id"]),
                    category=str(raw.get("category", "")),
                    query=str(raw["query"]),
                    relevant=list(raw["relevant"]),
                    maybe=list(raw.get("maybe", [])),
                )
            )
    return labels


def find_chunks_for_file_contains(service: BenchmarkService, file_path: str, contains: str) -> list[str]:
    """Resolve a file_path + substring label to chunk ids in the active chunk strategy."""
    strategy = service._settings.chunk_strategy
    metadata_store = service._pipeline.metadata_store
    total = metadata_store.get_chunk_count_for_file(strategy, file_path)
    chunks = metadata_store.get_chunks_for_file_range(strategy, file_path, 0, total)
    matched_texts = [chunk["text"] for chunk in chunks if contains in chunk.get("text", "")]
    if not matched_texts:
        return []

    matched_ids: list[str] = []
    for chunk_id in metadata_store.get_chunk_ids_by_file(strategy, file_path):
        payload = metadata_store.get_stored_payload(strategy, chunk_id)
        if payload and payload.get("text") in matched_texts:
            matched_ids.append(chunk_id)
    return matched_ids


def _resolve_label_object(label: dict[str, str], service: BenchmarkService) -> list[str]:
    if "chunk_id" in label:
        return [str(label["chunk_id"])]
    if "file_path" in label and "contains" in label:
        matches = find_chunks_for_file_contains(
            service,
            str(label["file_path"]),
            str(label["contains"]),
        )
        if len(matches) != 1:
            raise ValueError(
                "label {file_path!r} contains {contains!r} resolved to {count} chunks".format(
                    file_path=label["file_path"],
                    contains=label["contains"],
                    count=len(matches),
                )
            )
        return matches
    raise ValueError(f"unsupported label object: {label}")


def resolve_labels(label_case: LabelCase, service: BenchmarkService) -> ResolvedLabels:
    relevant: set[str] = set()
    maybe: set[str] = set()
    for label in label_case.relevant:
        relevant.update(_resolve_label_object(label, service))
    for label in label_case.maybe:
        maybe.update(_resolve_label_object(label, service))
    return ResolvedLabels(relevant_ids=relevant, maybe_ids=maybe - relevant)


def hit_at(ranked_ids: Sequence[str], relevant_ids: set[str], maybe_ids: set[str], k: int) -> float:
    accepted = relevant_ids | maybe_ids
    return 1.0 if any(chunk_id in accepted for chunk_id in ranked_ids[:k]) else 0.0


def mrr_at(
    ranked_ids: Sequence[str], relevant_ids: set[str], maybe_ids: set[str], k: int = 10
) -> float:
    accepted = relevant_ids | maybe_ids
    for index, chunk_id in enumerate(ranked_ids[:k], start=1):
        if chunk_id in accepted:
            return 1.0 / index
    return 0.0


def _gain(chunk_id: str, relevant_ids: set[str], maybe_ids: set[str]) -> float:
    if chunk_id in relevant_ids:
        return 2.0
    if chunk_id in maybe_ids:
        return 1.0
    return 0.0


def _dcg(gains: Sequence[float]) -> float:
    return sum(gain / math.log2(index + 1) for index, gain in enumerate(gains, start=1))


def ndcg_at(
    ranked_ids: Sequence[str], relevant_ids: set[str], maybe_ids: set[str], k: int = 10
) -> float:
    gains = [_gain(chunk_id, relevant_ids, maybe_ids) for chunk_id in ranked_ids[:k]]
    ideal_gains = sorted([2.0] * len(relevant_ids) + [1.0] * len(maybe_ids), reverse=True)[:k]
    ideal = _dcg(ideal_gains)
    if ideal == 0.0:
        return 0.0
    return _dcg(gains) / ideal


def labels_by_rank(
    ranked_ids: Sequence[str], relevant_ids: set[str], maybe_ids: set[str]
) -> list[str]:
    labels: list[str] = []
    for chunk_id in ranked_ids:
        if chunk_id in relevant_ids:
            labels.append("relevant")
        elif chunk_id in maybe_ids:
            labels.append("maybe")
        else:
            labels.append("irrelevant")
    return labels


def append_jsonl(path: Path, rows: list[JsonRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def make_result_row(
    *,
    label_case: LabelCase,
    resolved: ResolvedLabels,
    run: dict[str, Any],
    top_file_paths: list[list[str]],
    config: BenchmarkConfig,
    commit: str,
    chunk_strategy: str,
    shared_pool_size: int,
    candidate_pool_ids: list[str],
) -> JsonRow:
    top_chunk_ids = list(run.get("top_chunk_ids") or [])
    pool_miss = not bool(set(candidate_pool_ids) & resolved.all_ids)
    error = run.get("error")
    return {
        "phase": PHASE,
        "commit": commit,
        "query_id": label_case.id,
        "query": label_case.query,
        "category": label_case.category,
        "model": run["name"],
        "model_name": run.get("model_name", run["name"]),
        "mode": config.mode,
        "expand": True,
        "shared_pool_size": shared_pool_size,
        "candidate_pool_chunk_ids": candidate_pool_ids,
        "top_n": config.top_n,
        "chunk_strategy": chunk_strategy,
        "top_chunk_ids": top_chunk_ids,
        "top_file_paths": top_file_paths,
        "labels_by_rank": labels_by_rank(top_chunk_ids, resolved.relevant_ids, resolved.maybe_ids),
        "hit_at_1": hit_at(top_chunk_ids, resolved.relevant_ids, resolved.maybe_ids, 1),
        "hit_at_3": hit_at(top_chunk_ids, resolved.relevant_ids, resolved.maybe_ids, 3),
        "hit_at_5": hit_at(top_chunk_ids, resolved.relevant_ids, resolved.maybe_ids, 5),
        "mrr_at_10": mrr_at(top_chunk_ids, resolved.relevant_ids, resolved.maybe_ids, 10),
        "ndcg_at_10": ndcg_at(top_chunk_ids, resolved.relevant_ids, resolved.maybe_ids, 10),
        "rerank_ms": run.get("rerank_ms"),
        "rerank": format_elapsed_ms(float(run["rerank_ms"])) if run.get("rerank_ms") is not None else None,
        "error": error,
        "pool_miss": pool_miss,
    }


def hydrate_file_paths(service: BenchmarkService, chunk_strategy: str, chunk_ids: list[str]) -> list[list[str]]:
    paths_by_id = service._pipeline.metadata_store.get_file_paths_for_chunk_ids(
        chunk_strategy, chunk_ids
    )
    return [paths_by_id.get(chunk_id, []) for chunk_id in chunk_ids]


def summarize_rows(rows: list[JsonRow]) -> list[JsonRow]:
    by_model: dict[str, list[JsonRow]] = defaultdict(list)
    for row in rows:
        by_model[row["model"]].append(row)

    summaries: list[JsonRow] = []
    for model, model_rows in by_model.items():
        valid_rows = [
            row for row in model_rows if not row.get("pool_miss") and not row.get("error")
        ]
        rerank_values = [
            float(row["rerank_ms"])
            for row in model_rows
            if row.get("rerank_ms") is not None and not row.get("error")
        ]
        pool_miss_count = sum(1 for row in model_rows if row.get("pool_miss"))
        error_count = sum(1 for row in model_rows if row.get("error"))
        denominator = len(valid_rows)
        summaries.append(
            {
                "model": model,
                "model_name": next((row.get("model_name") for row in model_rows if row.get("model_name")), model),
                "valid_queries": denominator,
                "pool_miss_count": pool_miss_count,
                "error_count": error_count,
                "hit_at_1": _average(valid_rows, "hit_at_1"),
                "hit_at_3": _average(valid_rows, "hit_at_3"),
                "hit_at_5": _average(valid_rows, "hit_at_5"),
                "mrr_at_10": _average(valid_rows, "mrr_at_10"),
                "ndcg_at_10": _average(valid_rows, "ndcg_at_10"),
                "p50_rerank_ms": percentile(rerank_values, 50),
                "p95_rerank_ms": percentile(rerank_values, 95),
            }
        )

    return sorted(
        summaries,
        key=lambda row: (
            -float(row["ndcg_at_10"] or 0.0),
            -float(row["mrr_at_10"] or 0.0),
            -float(row["hit_at_3"] or 0.0),
            float(row["p95_rerank_ms"]) if row["p95_rerank_ms"] is not None else float("inf"),
            str(row["model"]),
        ),
    )


def _average(rows: list[JsonRow], key: str) -> float | None:
    if not rows:
        return None
    return sum(float(row[key]) for row in rows) / len(rows)


def fmt_metric(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"


def fmt_ms(value: float | None) -> str:
    if value is None:
        return "n/a"
    return format_elapsed_ms(value)


def write_summary_markdown(
    summaries: list[JsonRow],
    path: Path,
    *,
    rows: list[JsonRow],
    config: BenchmarkConfig,
    commit: str,
    chunk_strategy: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    query_count = len({row["query_id"] for row in rows})
    pool_miss_ids = sorted({row["query_id"] for row in rows if row.get("pool_miss")})
    lines = [
        "# Phase 21 Canonical Reranker Quality Summary",
        "",
        f"- commit: `{commit}`",
        f"- query_count: {query_count}",
        f"- `shared_pool_size={config.pool_size}`",
        f"- `top_n={config.top_n}`",
        f"- mode: `{config.mode}`",
        "- expansion: enabled",
        f"- `chunk_strategy={chunk_strategy}`",
        "- negative historical control: provided by explicit candidate set, if any",
        "",
        "Rows are sorted by `nDCG@10` descending, then `MRR@10`, `Hit@3`, and lower p95 hot `rerank_ms`.",
        "Pool-miss queries are retrieval gaps and are excluded from per-model quality averages.",
        "",
        "| Model | Valid queries | Pool misses | Errors | Hit@1 | Hit@3 | Hit@5 | MRR@10 | nDCG@10 | p50 rerank | p95 rerank |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        lines.append(
            "| {model} | {valid} | {misses} | {errors} | {h1} | {h3} | {h5} | {mrr} | {ndcg} | {p50} | {p95} |".format(
                model=f"`{row['model']}`",
                valid=row["valid_queries"],
                misses=row["pool_miss_count"],
                errors=row["error_count"],
                h1=fmt_metric(row["hit_at_1"]),
                h3=fmt_metric(row["hit_at_3"]),
                h5=fmt_metric(row["hit_at_5"]),
                mrr=fmt_metric(row["mrr_at_10"]),
                ndcg=fmt_metric(row["ndcg_at_10"]),
                p50=fmt_ms(row["p50_rerank_ms"]),
                p95=fmt_ms(row["p95_rerank_ms"]),
            )
        )

    lines.extend(["", "## Retrieval Gaps", ""])
    if pool_miss_ids:
        lines.append(f"pool_miss query ids: {', '.join(pool_miss_ids)}")
    else:
        lines.append("No pool_miss retrieval gaps.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_benchmark(config: BenchmarkConfig, service: BenchmarkService | None = None) -> list[JsonRow]:
    if service is None:
        service = cast(
            BenchmarkService,
            DotMDService(
                Settings(
                    embedding_url="http://localhost:8088",
                    rerank_pool_size=config.pool_size,
                )
            ),
        )
    commit = config.commit or get_commit()
    chunk_strategy = service._settings.chunk_strategy
    labels = load_labels(config.labels)
    config.output.parent.mkdir(parents=True, exist_ok=True)
    config.output.write_text("", encoding="utf-8")

    rows: list[JsonRow] = []
    for label_case in labels:
        resolved = resolve_labels(label_case, service)
        comparison = service.compare_rerankers(
            label_case.query,
            config.rerankers,
            top_k=config.top_n,
            mode=config.mode,
            expand=True,
        )
        runs_by_name = {run["name"]: run for run in comparison["rerankers"]}
        candidate_pool_ids = list(comparison.get("candidate_pool_chunk_ids") or [])
        if not candidate_pool_ids:
            candidate_pool_ids = sorted(
                {
                    chunk_id
                    for run in comparison["rerankers"]
                    for chunk_id in list(run.get("top_chunk_ids") or [])
                }
            )
        for model in config.rerankers:
            run = cast(
                dict[str, Any],
                runs_by_name.get(
                    model,
                    {
                        "name": model,
                        "model_name": model,
                        "top_chunk_ids": [],
                        "rerank_ms": None,
                        "error": "model missing from compare_rerankers output",
                    },
                ),
            )
            top_chunk_ids = list(run.get("top_chunk_ids") or [])
            row = make_result_row(
                label_case=label_case,
                resolved=resolved,
                run=run,
                top_file_paths=hydrate_file_paths(service, chunk_strategy, top_chunk_ids),
                config=config,
                commit=commit,
                chunk_strategy=chunk_strategy,
                shared_pool_size=int(comparison.get("shared_pool_size") or 0),
                candidate_pool_ids=candidate_pool_ids,
            )
            rows.append(row)
            append_jsonl(config.output, [row])

    summaries = summarize_rows(rows)
    write_summary_markdown(
        summaries,
        config.summary,
        rows=rows,
        config=config,
        commit=commit,
        chunk_strategy=chunk_strategy,
    )
    return summaries


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Phase 21 reranker quality benchmark.")
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--rerankers", default=None, help="Comma-separated reranker names.")
    parser.add_argument("--mode", default="hybrid")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--pool-size", type=int, default=20)
    parser.add_argument("--commit", default=None, help="Commit hash to record; defaults to git HEAD.")
    return parser


def config_from_args(args: argparse.Namespace) -> BenchmarkConfig:
    return BenchmarkConfig(
        labels=args.labels,
        output=args.output,
        summary=args.summary,
        rerankers=parse_rerankers(args.rerankers),
        mode=args.mode,
        top_n=args.top_n,
        pool_size=args.pool_size,
        commit=args.commit,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summaries = run_benchmark(config_from_args(args))
    print(json.dumps(summaries, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
