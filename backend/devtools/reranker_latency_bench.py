"""Canonical reranker latency benchmark runner for Phase 20."""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotmd.api.service import DotMDService, format_elapsed_ms
from dotmd.core.config import Settings

PHASE = "20"
QUERY_SET_NAME = "QUERY_SET_V1"
QUERY_SET_V1 = [
    "как подключить MCP к ChatGPT",
    "Claude Desktop OAuth connector setup",
    "почему hybrid search теряет BM25 результаты",
    "FalkorDB graph backend migration notes",
    "как работает content-addressed chunk cache",
    "dotMD trickle indexer orphan cleanup",
    "sqlite-vec unified index schema",
    "русскоязычный reranker для markdown базы знаний",
    "Tailscale Funnel OAuth protected resource metadata",
    "embedding model swap TEI batch size tuning",
]
DEFAULT_RERANKERS = [
    "mmarco-minilm",
]

FAST_P95_MS = 10_000.0
ACCEPTABLE_P95_MS = 30_000.0
SLOW_P95_MS = 120_000.0


JsonRow = dict[str, Any]
ServiceFactory = Callable[[Settings], DotMDService]


@dataclass(frozen=True)
class BenchmarkConfig:
    rerankers: list[str]
    output: Path
    summary: Path
    mode: str = "hybrid"
    top_n: int = 3
    pool_size: int = 20
    cold_passes: int = 1
    hot_passes: int = 3
    model_wall_timeout_s: int = 900
    hot_query_timeout_s: int = 120
    commit: str | None = None


def parse_rerankers(raw: str | None) -> list[str]:
    """Parse a comma-separated reranker list."""
    if raw is None or not raw.strip():
        return list(DEFAULT_RERANKERS)
    return [name.strip() for name in raw.split(",") if name.strip()]


def percentile(values: list[float], pct: float) -> float:
    """Return an interpolated percentile for a non-empty numeric list."""
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def latency_band(p95_ms: float | None, *, errors: int = 0, timeouts: int = 0) -> str:
    """Classify hot reranking latency into Phase 20 bands."""
    if p95_ms is None or errors or timeouts:
        return "unusable"
    if p95_ms <= FAST_P95_MS:
        return "fast"
    if p95_ms <= ACCEPTABLE_P95_MS:
        return "acceptable"
    if p95_ms <= SLOW_P95_MS:
        return "slow"
    return "unusable"


def human_ms(value: float | None) -> str:
    if value is None:
        return "n/a"
    return format_elapsed_ms(value)


def get_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def make_row(
    *,
    config: BenchmarkConfig,
    commit: str,
    query_index: int,
    query: str,
    model: str,
    pass_kind: str,
    pass_index: int,
    result: dict[str, Any] | None,
    error: str | None = None,
    timeout: bool = False,
) -> JsonRow:
    return {
        "phase": PHASE,
        "query_set": QUERY_SET_NAME,
        "query_index": query_index,
        "query": query,
        "model": model,
        "model_name": result.get("model_name") if result else model,
        "pass_kind": pass_kind,
        "pass_index": pass_index,
        "shared_pool_size": config.pool_size,
        "top_n": config.top_n,
        "mode": config.mode,
        "expand": True,
        "load_ms": result.get("load_ms") if result else None,
        "rerank_ms": result.get("rerank_ms") if result else None,
        "elapsed_ms": result.get("elapsed_ms") if result else None,
        "returned_count": result.get("returned_count", 0) if result else 0,
        "error": error or (result.get("error") if result else None),
        "timeout": timeout,
        "commit": commit,
    }


def append_jsonl(path: Path, rows: list[JsonRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def run_model_sequence(
    model: str,
    config: BenchmarkConfig,
    output_path: Path,
    commit: str,
    *,
    service_factory: ServiceFactory | None = None,
) -> None:
    """Run one model sequence in one process and append raw JSONL rows."""
    factory = service_factory or DotMDService
    service = factory(
        Settings(
            embedding_url="http://localhost:8088",
            rerank_pool_size=config.pool_size,
        )
    )
    timeout_ms = config.hot_query_timeout_s * 1000.0

    for pass_kind, pass_count in (("cold", config.cold_passes), ("hot", config.hot_passes)):
        for pass_index in range(pass_count):
            for query_index, query in enumerate(QUERY_SET_V1, start=1):
                try:
                    comparison = service.compare_rerankers(
                        query,
                        [model],
                        top_k=config.top_n,
                        mode=config.mode,
                        expand=True,
                    )
                    result = cast(dict[str, Any], comparison["rerankers"][0])
                    timed_out = (
                        pass_kind == "hot"
                        and result.get("rerank_ms") is not None
                        and float(result["rerank_ms"]) > timeout_ms
                    )
                    row = make_row(
                        config=config,
                        commit=commit,
                        query_index=query_index,
                        query=query,
                        model=model,
                        pass_kind=pass_kind,
                        pass_index=pass_index,
                        result=result,
                        timeout=timed_out,
                    )
                    append_jsonl(output_path, [row])
                    if row["error"] or timed_out:
                        return
                except Exception as exc:
                    row = make_row(
                        config=config,
                        commit=commit,
                        query_index=query_index,
                        query=query,
                        model=model,
                        pass_kind=pass_kind,
                        pass_index=pass_index,
                        result=None,
                        error=str(exc),
                    )
                    append_jsonl(output_path, [row])
                    return


def _run_model_child(model: str, config: BenchmarkConfig, commit: str) -> None:
    run_model_sequence(model, config, config.output, commit)


def dnf_row(model: str, config: BenchmarkConfig, commit: str) -> JsonRow:
    return make_row(
        config=config,
        commit=commit,
        query_index=0,
        query="",
        model=model,
        pass_kind="dnf",
        pass_index=0,
        result=None,
        error="model_wall_timeout_s exceeded",
        timeout=True,
    )


def iter_jsonl(path: Path) -> list[JsonRow]:
    if not path.exists():
        return []
    rows: list[JsonRow] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def summarize_rows(rows: list[JsonRow]) -> list[JsonRow]:
    by_model: dict[str, list[JsonRow]] = defaultdict(list)
    for row in rows:
        by_model[row["model"]].append(row)

    summaries: list[JsonRow] = []
    for model, model_rows in by_model.items():
        hot_rows = [row for row in model_rows if row.get("pass_kind") == "hot"]
        hot_values = [
            float(row["rerank_ms"])
            for row in hot_rows
            if row.get("rerank_ms") is not None and not row.get("error")
        ]
        cold_values = [
            float(row["load_ms"])
            for row in model_rows
            if row.get("pass_kind") == "cold" and row.get("load_ms") is not None
        ]
        errors = sum(1 for row in model_rows if row.get("error"))
        timeouts = sum(1 for row in model_rows if row.get("timeout"))
        p50 = percentile(hot_values, 50) if hot_values else None
        p95 = percentile(hot_values, 95) if hot_values else None
        max_hot = max(hot_values) if hot_values else None
        summaries.append(
            {
                "model": model,
                "model_name": next((row.get("model_name") for row in model_rows if row.get("model_name")), model),
                "hot_samples": len(hot_values),
                "p50_rerank_ms": p50,
                "p95_rerank_ms": p95,
                "max_rerank_ms": max_hot,
                "cold_load_max_ms": max(cold_values) if cold_values else None,
                "error_count": errors,
                "timeout_count": timeouts,
                "latency_band": latency_band(p95, errors=errors, timeouts=timeouts),
            }
        )

    band_order = {"fast": 0, "acceptable": 1, "slow": 2, "unusable": 3}
    return sorted(
        summaries,
        key=lambda row: (
            band_order.get(str(row["latency_band"]), 99),
            float(row["p95_rerank_ms"]) if row["p95_rerank_ms"] is not None else float("inf"),
            str(row["model"]),
        ),
    )


def write_summary_markdown(summaries: list[JsonRow], path: Path, *, config: BenchmarkConfig, commit: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Phase 20 Canonical Reranker Latency Summary",
        "",
        f"- commit: `{commit}`",
        "- query set: `QUERY_SET_V1`",
        f"- `shared_pool_size={config.pool_size}`",
        f"- `top_n={config.top_n}`",
        f"- mode: `{config.mode}`",
        "- expansion: enabled",
        f"- `cold_passes={config.cold_passes}`",
        f"- `hot_passes={config.hot_passes}`",
        f"- `hot_samples_per_model={len(QUERY_SET_V1) * config.hot_passes}`",
        f"- `model_wall_timeout_s={config.model_wall_timeout_s}`",
        f"- `hot_query_timeout_s={config.hot_query_timeout_s}`",
        "",
        "Rows are sorted by hot p95 `rerank_ms` from fastest to slowest. Bands use hot rows only; any provider error, timeout, or DNF is `unusable`.",
        "",
        "| Model | Band | Hot samples | p50 rerank | p95 rerank | max rerank | cold load max | Errors | Timeouts |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries:
        lines.append(
            "| {model} | {band} | {samples} | {p50} | {p95} | {max_hot} | {cold} | {errors} | {timeouts} |".format(
                model=f"`{row['model']}`",
                band=row["latency_band"],
                samples=row["hot_samples"],
                p50=human_ms(row["p50_rerank_ms"]),
                p95=human_ms(row["p95_rerank_ms"]),
                max_hot=human_ms(row["max_rerank_ms"]),
                cold=human_ms(row["cold_load_max_ms"]),
                errors=row["error_count"],
                timeouts=row["timeout_count"],
            )
        )
    lines.append("")
    lines.append("This summary does not judge relevance quality and does not change the production default reranker.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_benchmark(config: BenchmarkConfig) -> list[JsonRow]:
    commit = config.commit or get_commit()
    config.output.parent.mkdir(parents=True, exist_ok=True)
    config.output.write_text("", encoding="utf-8")

    for model in config.rerankers:
        started = time.monotonic()
        print(f"benchmark model={model} started", flush=True)
        process = mp.Process(target=_run_model_child, args=(model, config, commit))
        process.start()
        process.join(config.model_wall_timeout_s)
        if process.is_alive():
            process.terminate()
            process.join(10)
            append_jsonl(config.output, [dnf_row(model, config, commit)])
            print(
                f"benchmark model={model} timeout after {format_elapsed_ms((time.monotonic() - started) * 1000.0)}",
                flush=True,
            )
        elif process.exitcode not in (0, None):
            append_jsonl(
                config.output,
                [
                    make_row(
                        config=config,
                        commit=commit,
                        query_index=0,
                        query="",
                        model=model,
                        pass_kind="dnf",
                        pass_index=0,
                        result=None,
                        error=f"child exited with code {process.exitcode}",
                    )
                ],
            )
        print(
            f"benchmark model={model} finished in {format_elapsed_ms((time.monotonic() - started) * 1000.0)}",
            flush=True,
        )

    summaries = summarize_rows(iter_jsonl(config.output))
    write_summary_markdown(summaries, config.summary, config=config, commit=commit)
    return summaries


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Phase 20 reranker latency benchmark.")
    parser.add_argument("--rerankers", default=None, help="Comma-separated reranker names.")
    parser.add_argument("--output", required=True, type=Path, help="JSONL output path.")
    parser.add_argument("--summary", required=True, type=Path, help="Markdown summary output path.")
    parser.add_argument("--mode", default="hybrid")
    parser.add_argument("--top-n", type=int, default=3)
    parser.add_argument("--pool-size", type=int, default=20)
    parser.add_argument("--cold-passes", type=int, default=1)
    parser.add_argument("--hot-passes", type=int, default=3)
    parser.add_argument("--model-wall-timeout-s", type=int, default=900)
    parser.add_argument("--hot-query-timeout-s", type=int, default=120)
    parser.add_argument("--commit", default=None, help="Commit hash to record; defaults to git HEAD.")
    return parser


def config_from_args(args: argparse.Namespace) -> BenchmarkConfig:
    return BenchmarkConfig(
        rerankers=parse_rerankers(args.rerankers),
        output=args.output,
        summary=args.summary,
        mode=args.mode,
        top_n=args.top_n,
        pool_size=args.pool_size,
        cold_passes=args.cold_passes,
        hot_passes=args.hot_passes,
        model_wall_timeout_s=args.model_wall_timeout_s,
        hot_query_timeout_s=args.hot_query_timeout_s,
        commit=args.commit,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summaries = run_benchmark(config_from_args(args))
    print(json.dumps(summaries, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
