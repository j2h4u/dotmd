#!/usr/bin/env python3
"""Compare current search results against a saved baseline.

Loads a baseline JSON file (from eval_baseline.py), runs the same queries
against the current dotMD service, and reports rank/score differences.

Usage:
    python eval_compare.py --baseline baseline.json --host http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

import httpx

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SCORE_DEGRADATION_THRESHOLD = 0.05


def fetch_current_results(
    host: str, queries: dict, top_k: int, timeout: float = 30.0
) -> dict:
    """Run baseline queries against the current service."""
    with httpx.Client() as client:
        # Detect model
        model = "unknown"
        try:
            resp = client.get(f"{host}/status", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if "embedding_model" in data:
                    model = data["embedding_model"]
        except Exception:
            pass

        if model == "unknown":
            for tei_port in (8088, 8080):
                try:
                    base = host.rsplit(":", 1)[0]
                    resp = client.get(f"{base}:{tei_port}/info", timeout=5)
                    if resp.status_code == 200:
                        model = resp.json().get("model_id", "unknown")
                        break
                except Exception:
                    pass

        results: dict = {}
        for qid, qdata in queries.items():
            query_text = qdata["query"]
            try:
                resp = client.get(
                    f"{host}/search",
                    params={"q": query_text, "top_k": top_k},
                    timeout=timeout,
                )
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as exc:
                print(f"  ERROR [{qid}]: HTTP {exc.response.status_code}", file=sys.stderr)
                results[qid] = {"query": query_text, "count": 0, "hits": [], "error": str(exc)}
                continue
            except httpx.RequestError as exc:
                print(f"  ERROR [{qid}]: {exc}", file=sys.stderr)
                results[qid] = {"query": query_text, "count": 0, "hits": [], "error": str(exc)}
                continue

            hits = []
            for rank, r in enumerate(data.get("results", []), start=1):
                hits.append({
                    "rank": rank,
                    "score": r.get("fused_score", 0.0),
                    "chunk_id": r.get("chunk_id", ""),
                    "title": r.get("heading_path", ""),
                    "snippet": r.get("snippet", "")[:100],
                    "matched_engines": r.get("matched_engines", []),
                })

            results[qid] = {
                "query": query_text,
                "count": len(hits),
                "hits": hits,
            }

    return {"model": model, "results": results}


def compare_query(qid: str, baseline_data: dict, current_data: dict) -> dict:
    """Compare a single query's results between baseline and current."""
    b_hits = baseline_data.get("hits", [])
    c_hits = current_data.get("hits", [])
    b_count = baseline_data.get("count", 0)
    c_count = current_data.get("count", 0)

    # Build lookup by chunk_id
    b_by_id = {h["chunk_id"]: h for h in b_hits}
    c_by_id = {h["chunk_id"]: h for h in c_hits}

    b_ids = set(b_by_id.keys())
    c_ids = set(c_by_id.keys())

    shared_ids = b_ids & c_ids
    new_ids = c_ids - b_ids
    lost_ids = b_ids - c_ids

    # Rank changes for shared hits
    rank_changes = []
    score_deltas = []
    for cid in shared_ids:
        b_hit = b_by_id[cid]
        c_hit = c_by_id[cid]
        rank_delta = c_hit["rank"] - b_hit["rank"]
        score_delta = c_hit["score"] - b_hit["score"]
        rank_changes.append({
            "chunk_id": cid,
            "title": c_hit.get("title") or b_hit.get("title", ""),
            "baseline_rank": b_hit["rank"],
            "current_rank": c_hit["rank"],
            "rank_delta": rank_delta,
            "baseline_score": b_hit["score"],
            "current_score": c_hit["score"],
            "score_delta": score_delta,
        })
        score_deltas.append(score_delta)

    rank_changes.sort(key=lambda x: x["current_rank"])

    # New hits
    new_hits = []
    for cid in new_ids:
        h = c_by_id[cid]
        new_hits.append({
            "chunk_id": cid,
            "title": h.get("title", ""),
            "rank": h["rank"],
            "score": h["score"],
        })
    new_hits.sort(key=lambda x: x["rank"])

    # Lost hits
    lost_hits = []
    for cid in lost_ids:
        h = b_by_id[cid]
        lost_hits.append({
            "chunk_id": cid,
            "title": h.get("title", ""),
            "rank": h["rank"],
            "score": h["score"],
        })
    lost_hits.sort(key=lambda x: x["rank"])

    # Top-3 stability
    b_top3 = [h["chunk_id"] for h in b_hits[:3]]
    c_top3 = [h["chunk_id"] for h in c_hits[:3]]
    top3_matches = sum(1 for cid in c_top3 if cid in b_top3)
    top3_stable = top3_matches == 3 and b_top3 == c_top3

    # Average score delta
    avg_score_delta = sum(score_deltas) / len(score_deltas) if score_deltas else 0.0

    # Verdict for this query
    b_top3_scores = [h["score"] for h in b_hits[:3]]
    c_top3_scores = [h["score"] for h in c_hits[:3]]
    b_top3_avg = sum(b_top3_scores) / len(b_top3_scores) if b_top3_scores else 0.0
    c_top3_avg = sum(c_top3_scores) / len(c_top3_scores) if c_top3_scores else 0.0

    # A query is "improved" if:
    # (a) count of relevant hits increased, or
    # (b) top-3 scores are higher on average, or
    # (c) previously noisy results (rank 3-5) dropped out
    # "degraded" if top-3 hits lost or scores dropped significantly (>0.05)
    if lost_ids & set(b_top3):
        verdict = "degraded"
    elif c_top3_avg - b_top3_avg < -SCORE_DEGRADATION_THRESHOLD:
        verdict = "degraded"
    elif c_count > b_count and c_top3_avg >= b_top3_avg:
        verdict = "improved"
    elif c_top3_avg - b_top3_avg > SCORE_DEGRADATION_THRESHOLD:
        verdict = "improved"
    elif lost_ids and all(b_by_id[cid]["rank"] >= 3 for cid in lost_ids):
        # Noisy results dropped out
        verdict = "improved"
    else:
        verdict = "unchanged"

    return {
        "query": baseline_data["query"],
        "baseline_count": b_count,
        "current_count": c_count,
        "count_delta": c_count - b_count,
        "top3_stable": top3_stable,
        "top3_matches": top3_matches,
        "rank_changes": rank_changes,
        "new_hits": new_hits,
        "lost_hits": lost_hits,
        "avg_score_delta": avg_score_delta,
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def print_query_comparison(qid: str, comp: dict) -> None:
    """Print detailed comparison for a single query."""
    query = comp["query"]
    b_count = comp["baseline_count"]
    c_count = comp["current_count"]
    delta = comp["count_delta"]
    delta_str = f"+{delta}" if delta > 0 else str(delta)

    print(f"\n=== {qid}: \"{query}\" ===")
    print(f"Count: {b_count} -> {c_count} ({delta_str})")

    top3_matches = comp["top3_matches"]
    top3_stable = comp["top3_stable"]
    if top3_stable:
        print("Top-3 stable: YES")
    else:
        print(f"Top-3 stable: NO ({top3_matches}/3 match)")

    # Rank comparison table
    if comp["rank_changes"]:
        print()
        print(f"  {'Rank':<6} {'Baseline':<36} {'Current':<36} {'Delta':>8}")
        for rc in comp["rank_changes"]:
            title = rc["title"][:30] if rc["title"] else rc["chunk_id"][:30]
            b_str = f"[{rc['baseline_score']:.3f}] {title}"
            c_str = f"[{rc['current_score']:.3f}] {title}"
            sd = rc["score_delta"]
            delta_s = f"+{sd:.3f}" if sd >= 0 else f"{sd:.3f}"
            rank_note = ""
            if rc["rank_delta"] != 0:
                rank_note = f" (rank {rc['baseline_rank']}->{rc['current_rank']})"
            print(f"  {rc['current_rank']:<6} {b_str:<36} {c_str:<36} {delta_s:>8}{rank_note}")

    # New hits
    if comp["new_hits"]:
        print()
        titles = ", ".join(
            f"{h['title'] or h['chunk_id']} (score {h['score']:.3f})"
            for h in comp["new_hits"][:5]
        )
        print(f"  New hits: {titles}")

    # Lost hits
    if comp["lost_hits"]:
        titles = ", ".join(
            f"{h['title'] or h['chunk_id']} (was rank {h['rank']}, score {h['score']:.3f})"
            for h in comp["lost_hits"][:5]
        )
        print(f"  Lost hits: {titles}")

    print(f"\n  Verdict: {comp['verdict'].upper()}")


def print_summary(comparisons: dict, baseline_model: str, current_model: str) -> None:
    """Print overall summary verdict."""
    total = len(comparisons)
    improved = sum(1 for c in comparisons.values() if c["verdict"] == "improved")
    degraded = sum(1 for c in comparisons.values() if c["verdict"] == "degraded")
    unchanged = sum(1 for c in comparisons.values() if c["verdict"] == "unchanged")
    top3_stable = sum(1 for c in comparisons.values() if c["top3_stable"])

    all_deltas = [c["avg_score_delta"] for c in comparisons.values() if c["rank_changes"]]
    avg_delta = sum(all_deltas) / len(all_deltas) if all_deltas else 0.0
    delta_str = f"+{avg_delta:.3f}" if avg_delta >= 0 else f"{avg_delta:.3f}"

    print()
    print("=" * 72)
    print("SUMMARY")
    print(f"  Baseline model: {baseline_model}")
    print(f"  Current model:  {current_model}")
    print(f"  Queries improved:  {improved}/{total}")
    print(f"  Queries degraded:  {degraded}/{total}")
    print(f"  Queries unchanged: {unchanged}/{total}")
    print(f"  Top-3 stability:   {top3_stable}/{total} queries")
    print(f"  Average score delta: {delta_str}")
    print("=" * 72)

    if degraded > improved:
        print("\n  RECOMMENDATION: Current model shows degradation. Review before merging.")
    elif improved > degraded:
        print("\n  RECOMMENDATION: Current model shows improvement. Consider merging.")
    else:
        print("\n  RECOMMENDATION: Results are comparable. Review details above.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare current search results against a saved baseline"
    )
    parser.add_argument(
        "--baseline",
        required=True,
        help="Path to baseline JSON file (from eval_baseline.py)",
    )
    parser.add_argument(
        "--host",
        default="http://localhost:8000",
        help="dotMD API base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Save full comparison to JSON file (optional)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="Number of results to request per query (default: 10)",
    )
    args = parser.parse_args()

    # Load baseline
    try:
        with open(args.baseline, encoding="utf-8") as f:
            baseline = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: Baseline file not found: {args.baseline}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"ERROR: Invalid JSON in baseline file: {exc}", file=sys.stderr)
        sys.exit(1)

    baseline_model = baseline.get("metadata", {}).get("model", "unknown")
    baseline_queries = baseline.get("results", {})
    baseline_top_k = baseline.get("metadata", {}).get("top_k", args.top_k)

    # Use baseline top_k unless overridden
    top_k = args.top_k if args.top_k != 10 else baseline_top_k

    print(f"Comparing against baseline ({baseline_model})...")
    print(f"  Baseline date: {baseline.get('metadata', {}).get('date', 'unknown')}")
    print(f"  Queries: {len(baseline_queries)}")
    print(f"  Host: {args.host}")

    # Fetch current results
    current = fetch_current_results(args.host, baseline_queries, top_k)
    current_model = current["model"]
    current_results = current["results"]

    # Compare each query
    comparisons: dict = {}
    for qid in baseline_queries:
        if qid not in current_results:
            print(f"  WARNING: query {qid} missing from current results", file=sys.stderr)
            continue
        comparisons[qid] = compare_query(qid, baseline_queries[qid], current_results[qid])

    # Print per-query comparisons
    for qid, comp in comparisons.items():
        print_query_comparison(qid, comp)

    # Print summary
    print_summary(comparisons, baseline_model, current_model)

    # Save output if requested
    if args.output:
        output_data = {
            "metadata": {
                "date": datetime.now(timezone.utc).isoformat(),
                "baseline_file": args.baseline,
                "baseline_model": baseline_model,
                "current_model": current_model,
                "host": args.host,
                "top_k": top_k,
            },
            "comparisons": comparisons,
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        print(f"\nFull comparison saved to: {args.output}")


if __name__ == "__main__":
    main()
