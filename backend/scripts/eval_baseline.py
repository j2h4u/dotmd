#!/usr/bin/env python3
"""Capture search quality baseline from a live dotMD service.

Runs a set of test queries against the search API and saves results
in a structured JSON file for later A/B comparison.

Usage:
    python eval_baseline.py --host http://localhost:8000 --output baseline.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

import httpx

# ---------------------------------------------------------------------------
# Test query set -- matches .planning/research/SEARCH-BASELINE.md
# ---------------------------------------------------------------------------

QUERIES = [
    {
        "id": "q1_semantic_concept",
        "query": "распределение прибыли",
        "type": "semantic concept, hybrid",
        "notes": "Should find meeting notes about profit distribution",
    },
    {
        "id": "q2_brand_name",
        "query": "hiveon",
        "type": "brand name, hybrid",
        "notes": "Should find Hiveon closure notes",
    },
    {
        "id": "q3_negative",
        "query": "trickle indexer",
        "type": "negative test",
        "notes": "Not in corpus -- should return 0 results",
    },
    {
        "id": "q4_entity_topic",
        "query": "Николай Сенин как делить деньги",
        "type": "entity+topic, hybrid",
        "notes": "Should find meeting notes with Nikolai Senin",
    },
    {
        "id": "q5_keyword",
        "query": "docker compose",
        "type": "keyword+semantic, hybrid",
        "notes": "Should find docker-compose docs",
    },
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fetch_model_info(client: httpx.Client, host: str) -> str:
    """Try to detect the embedding model from TEI /info or dotMD /status."""
    # Try dotMD /status first
    try:
        resp = client.get(f"{host}/status", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if "embedding_model" in data:
                return data["embedding_model"]
    except Exception:
        pass

    # Try TEI /info on common port
    for tei_port in (8088, 8080):
        try:
            base = host.rsplit(":", 1)[0]  # strip port from host
            resp = client.get(f"{base}:{tei_port}/info", timeout=5)
            if resp.status_code == 200:
                return resp.json().get("model_id", "unknown")
        except Exception:
            pass

    return "unknown"


def run_queries(
    host: str, top_k: int, timeout: float = 30.0
) -> dict:
    """Run all test queries and return structured results."""
    with httpx.Client() as client:
        model = fetch_model_info(client, host)

        results: dict = {}
        for q in QUERIES:
            qid = q["id"]
            query_text = q["query"]

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
                results[qid] = {
                    "query": query_text,
                    "type": q["type"],
                    "notes": q["notes"],
                    "count": 0,
                    "hits": [],
                    "error": f"HTTP {exc.response.status_code}",
                }
                continue
            except httpx.RequestError as exc:
                print(f"  ERROR [{qid}]: {exc}", file=sys.stderr)
                results[qid] = {
                    "query": query_text,
                    "type": q["type"],
                    "notes": q["notes"],
                    "count": 0,
                    "hits": [],
                    "error": str(exc),
                }
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
                "type": q["type"],
                "notes": q["notes"],
                "count": len(hits),
                "hits": hits,
            }

        baseline = {
            "metadata": {
                "date": datetime.now(timezone.utc).isoformat(),
                "model": model,
                "host": host,
                "top_k": top_k,
            },
            "results": results,
        }

    return baseline


def print_summary(baseline: dict) -> None:
    """Print a human-readable summary table to stdout."""
    print()
    print("=" * 72)
    print("SEARCH QUALITY BASELINE")
    print(f"  Model: {baseline['metadata']['model']}")
    print(f"  Date:  {baseline['metadata']['date']}")
    print(f"  Host:  {baseline['metadata']['host']}")
    print("=" * 72)

    for qid, data in baseline["results"].items():
        query = data["query"]
        count = data["count"]
        error = data.get("error")

        print(f"\n--- {qid}: \"{query}\" ---")
        if error:
            print(f"  ERROR: {error}")
            continue

        print(f"  Count: {count}")
        if count == 0:
            print("  (no results)")
            continue

        # Show top-3
        for hit in data["hits"][:3]:
            rank = hit["rank"]
            score = hit["score"]
            title = hit["title"] or hit["snippet"][:50]
            engines = ", ".join(hit.get("matched_engines", []))
            print(f"  {rank}. [{score:.3f}] {title}")
            if engines:
                print(f"     engines: {engines}")

        if count > 3:
            print(f"  ... and {count - 3} more")

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture search quality baseline from a dotMD service"
    )
    parser.add_argument(
        "--host",
        default="http://localhost:8000",
        help="dotMD API base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--output",
        default="eval_baseline.json",
        help="Output JSON file path (default: eval_baseline.json)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=10,
        help="Number of results to request per query (default: 10)",
    )
    args = parser.parse_args()

    print(f"Capturing baseline from {args.host} (top_k={args.top_k})...")

    baseline = run_queries(args.host, args.top_k)

    # Save JSON
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(baseline, f, indent=2, ensure_ascii=False)

    print(f"\nBaseline saved to: {args.output}")
    print_summary(baseline)


if __name__ == "__main__":
    main()
