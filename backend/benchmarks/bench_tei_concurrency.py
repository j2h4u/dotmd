"""TEI concurrency benchmark for SPEED-01.

Measures texts/sec for 1, 2, and 3 concurrent TEI request workers,
keeping batch_size fixed at the production value (DOTMD_TEI_BATCH_SIZE).

This is a standalone script -- does not import from dotmd package
and never touches production indexes.
"""

import os
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx


def generate_test_texts(n: int = 100, avg_words: int = 150) -> list[str]:
    """Generate n synthetic texts of ~avg_words length.

    Uses realistic content so tokenization is representative.
    Length varies slightly per text for natural distribution.
    """
    base = (
        "The server infrastructure runs on a dedicated machine with Docker containers. "
        "Each service communicates through internal networks using REST APIs. "
        "The knowledge base contains transcribed voice notes and documentation files. "
        "Search combines semantic embeddings, keyword matching, and graph traversal. "
    )
    words = base.split()
    texts = []
    for i in range(n):
        target = avg_words + (i % 20) - 10
        repeated = (words * ((target // len(words)) + 1))[:target]
        texts.append(" ".join(repeated))
    return texts


def embed_batch(client: httpx.Client, url: str, texts: list[str]) -> int:
    """Send a batch to TEI /embed, return count of texts embedded."""
    resp = client.post(
        f"{url}/embed",
        json={"inputs": texts, "truncate": True},
        timeout=120.0,
    )
    resp.raise_for_status()
    return len(texts)


def benchmark_concurrency(
    url: str,
    texts: list[str],
    batch_size: int,
    max_workers: int,
    warmup_batches: int = 2,
) -> float:
    """Return texts/sec for given concurrency level."""
    batches = [texts[i : i + batch_size] for i in range(0, len(texts), batch_size)]

    with httpx.Client() as client:
        # Warmup -- run a few batches sequentially to prime TEI
        for b in batches[:warmup_batches]:
            embed_batch(client, url, b)

        # Timed run -- submit all batches with thread pool
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(embed_batch, client, url, b) for b in batches]
            total = sum(f.result() for f in as_completed(futures))
        elapsed = time.perf_counter() - t0

    return total / elapsed


def main() -> None:
    url = os.environ.get("DOTMD_EMBEDDING_URL", "http://embeddings:80")
    batch_size = int(os.environ.get("DOTMD_TEI_BATCH_SIZE", "4"))
    worker_counts = [1, 2, 3]
    iterations = 3
    n_texts = 100
    avg_words = 150
    warmup_batches = 2

    texts = generate_test_texts(n=n_texts, avg_words=avg_words)

    print("TEI Concurrency Benchmark")
    print("=========================")
    print(f"Embedding URL: {url}")
    print(f"Test corpus: {n_texts} texts, ~{avg_words} words each")
    print(f"Batch size per request: {batch_size}")
    print(f"Warmup: {warmup_batches} batches")
    print(f"Iterations: {iterations}")
    print()

    results: dict[int, list[float]] = {}

    for workers in worker_counts:
        print(f"  Benchmarking workers={workers}...", end="", flush=True)
        rates: list[float] = []
        for _ in range(iterations):
            rate = benchmark_concurrency(
                url, texts, batch_size, workers, warmup_batches
            )
            rates.append(rate)
        results[workers] = rates
        print(f" {statistics.mean(rates):.1f} texts/sec")

    print()

    # Print results table
    header = f"| {'Workers':>7} | {'texts/sec (mean)':>16} | {'stddev':>6} | {'min':>6} | {'max':>6} |"
    sep = f"|{'-' * 9}|{'-' * 18}|{'-' * 8}|{'-' * 8}|{'-' * 8}|"
    print(header)
    print(sep)

    stats: dict[int, dict[str, float]] = {}
    for workers in worker_counts:
        rates = results[workers]
        mean_val = statistics.mean(rates)
        stdev_val = statistics.stdev(rates) if len(rates) > 1 else 0.0
        min_val = min(rates)
        max_val = max(rates)
        stats[workers] = {
            "mean": mean_val,
            "stdev": stdev_val,
            "min": min_val,
            "max": max_val,
        }
        print(
            f"| {workers:>7} | {mean_val:>16.1f} | {stdev_val:>6.2f} | {min_val:>6.1f} | {max_val:>6.1f} |"
        )

    print()

    # Determine best worker count
    best_workers = max(worker_counts, key=lambda w: stats[w]["mean"])
    best_mean = stats[best_workers]["mean"]
    sequential_mean = stats[1]["mean"]
    speedup = best_mean / sequential_mean if sequential_mean > 0 else 0.0

    helps = best_workers > 1 and speedup > 1.05
    verdict = "helps" if helps else "does not help"

    print(
        f"CONCLUSION: Concurrency {verdict}. Best throughput at workers={best_workers}."
    )
    print(f"Speedup vs sequential: {speedup:.2f}x")


if __name__ == "__main__":
    main()
