"""GLiNER batching benchmark for SPEED-02.

Measures texts/sec for sequential NER (predict_entities per text) vs
batch NER (inference with batch_size=1,4,8) and optionally with
sequence packing.

This is a standalone script -- does not import from the dotmd package
and never touches production indexes.
"""

import statistics
import time

from gliner import GLiNER

ENTITY_TYPES = ["person", "organization", "technology", "concept", "location"]
MODEL_NAME = "urchade/gliner_multi-v2.1"
THRESHOLD = 0.5


def generate_test_texts(n: int = 50, avg_words: int = 150) -> list[str]:
    """Generate n synthetic texts of ~avg_words length.

    Uses realistic content so tokenization is representative.
    Uses 50 texts (not 100) because GLiNER is slower (~1 text/sec on CPU).
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


def benchmark_sequential(model: GLiNER, texts: list[str]) -> float:
    """Process texts one at a time with predict_entities. Return texts/sec."""
    t0 = time.perf_counter()
    for text in texts:
        model.predict_entities(text, ENTITY_TYPES, threshold=THRESHOLD)
    elapsed = time.perf_counter() - t0
    return len(texts) / elapsed


def benchmark_batch(model: GLiNER, texts: list[str], batch_size: int) -> float:
    """Process texts in batches via inference(). Return texts/sec."""
    t0 = time.perf_counter()
    model.inference(texts, ENTITY_TYPES, threshold=THRESHOLD, batch_size=batch_size)
    elapsed = time.perf_counter() - t0
    return len(texts) / elapsed


def benchmark_batch_packed(model: GLiNER, texts: list[str], batch_size: int) -> float:
    """Process texts with batch inference + sequence packing. Return texts/sec.

    Returns -1.0 if packing is not available in the installed GLiNER version.
    """
    try:
        from gliner.infer_packing import InferencePackingConfig
    except ImportError:
        return -1.0

    packing = InferencePackingConfig(max_length=512, streams_per_batch=1)
    t0 = time.perf_counter()
    model.inference(
        texts,
        ENTITY_TYPES,
        threshold=THRESHOLD,
        batch_size=batch_size,
        packing_config=packing,
    )
    elapsed = time.perf_counter() - t0
    return len(texts) / elapsed


def main() -> None:
    print(f"Loading model {MODEL_NAME}...")
    model = GLiNER.from_pretrained(MODEL_NAME)
    print("Model loaded.")

    n_texts = 50
    avg_words = 150
    iterations = 3
    warmup_count = 5

    texts = generate_test_texts(n=n_texts, avg_words=avg_words)

    # Warmup -- run predict_entities on first few texts to prime model
    print(f"Warming up on {warmup_count} texts...")
    for text in texts[:warmup_count]:
        model.predict_entities(text, ENTITY_TYPES, threshold=THRESHOLD)
    print("Warmup complete.")
    print()

    configs: list[tuple[str, object, dict]] = [
        ("Sequential", benchmark_sequential, {"texts": texts}),
        ("Batch bs=1", benchmark_batch, {"texts": texts, "batch_size": 1}),
        ("Batch bs=4", benchmark_batch, {"texts": texts, "batch_size": 4}),
        ("Batch bs=8", benchmark_batch, {"texts": texts, "batch_size": 8}),
        ("Packed bs=8", benchmark_batch_packed, {"texts": texts, "batch_size": 8}),
    ]

    print("GLiNER Batching Benchmark")
    print("=========================")
    print(f"Model: {MODEL_NAME}")
    print(f"Entity types: {', '.join(ENTITY_TYPES)}")
    print(f"Test corpus: {n_texts} texts, ~{avg_words} words each")
    print(f"Warmup: {warmup_count} texts")
    print(f"Iterations: {iterations}")
    print()

    results: list[tuple[str, str, dict[str, float] | None]] = []

    for label, func, kwargs in configs:
        print(f"  Benchmarking {label}...", end="", flush=True)
        rates: list[float] = []
        skip = False
        for _ in range(iterations):
            rate = func(model, **kwargs)
            if rate < 0:
                skip = True
                break
            rates.append(rate)

        if skip:
            print(" N/A (packing not available)")
            results.append((label, _extract_batch_size(label), None))
        else:
            mean_val = statistics.mean(rates)
            print(f" {mean_val:.2f} texts/sec")
            results.append((
                label,
                _extract_batch_size(label),
                {
                    "mean": mean_val,
                    "stdev": statistics.stdev(rates) if len(rates) > 1 else 0.0,
                    "min": min(rates),
                    "max": max(rates),
                },
            ))

    print()

    # Print results table
    header = f"| {'Mode':<15} | {'batch_size':>10} | {'texts/sec (mean)':>16} | {'stddev':>6} | {'min':>6} | {'max':>6} |"
    sep = f"|{'-' * 17}|{'-' * 12}|{'-' * 18}|{'-' * 8}|{'-' * 8}|{'-' * 8}|"
    print(header)
    print(sep)

    for label, bs, stat in results:
        if stat is None:
            print(
                f"| {label:<15} | {bs:>10} | {'N/A':>16} | {'N/A':>6} | {'N/A':>6} | {'N/A':>6} |"
            )
        else:
            print(
                f"| {label:<15} | {bs:>10} | {stat['mean']:>16.2f} | {stat['stdev']:>6.3f} | {stat['min']:>6.2f} | {stat['max']:>6.2f} |"
            )

    print()

    # Determine best mode (exclude N/A rows)
    valid = [(label, stat) for label, _, stat in results if stat is not None]
    if not valid:
        print("CONCLUSION: No valid benchmark results.")
        return

    best_label, best_stat = max(valid, key=lambda x: x[1]["mean"])
    seq_stat = results[0][2]  # Sequential is always first

    if seq_stat is None:
        print("CONCLUSION: Sequential baseline failed. Cannot determine speedup.")
        return

    sequential_mean = seq_stat["mean"]
    best_mean = best_stat["mean"]
    speedup = best_mean / sequential_mean if sequential_mean > 0 else 0.0

    helps = best_label != "Sequential" and speedup > 1.05
    verdict = "helps" if helps else "does not help"

    print(f"CONCLUSION: Batching {verdict}. Best throughput at {best_label}.")
    print(f"Speedup vs sequential: {speedup:.2f}x")


def _extract_batch_size(label: str) -> str:
    """Extract batch_size display string from config label."""
    if "bs=" in label:
        return label.split("bs=")[1]
    return "1"


if __name__ == "__main__":
    main()
