"""Modal GPU backend for pplx-embed context-aware document encoding.

Deploy:
    cd modal/
    uv run modal deploy embed.py

The deployed function is called by SemanticSearchEngine.encode_batch_context()
to produce context-aware embeddings on a remote GPU.
"""

import modal

app = modal.App("dotmd-embed")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "transformers>=4.45",
        "sentence-transformers>=3.0",
        "torch",
        "numpy",
        "huggingface_hub",
    )
    .run_commands(
        # Pre-download model at build time — avoids cold start latency
        "python -c \""
        "from transformers import AutoModel; "
        "AutoModel.from_pretrained("
        "'perplexity-ai/pplx-embed-context-v1-0.6B', "
        "trust_remote_code=True"
        ")\""
    )
)


@app.function(
    image=image,
    gpu="A10G",
    timeout=1800,
)
def encode_context(grouped_chunks: list[list[str]]) -> list[list[list[float]]]:
    """Encode document chunks using pplx-embed-context-v1-0.6B.

    Takes chunks grouped by document and returns per-chunk embeddings
    that incorporate surrounding document context.

    Parameters
    ----------
    grouped_chunks:
        List of documents, where each document is a list of chunk texts.
        Example: [["chunk1_docA", "chunk2_docA"], ["chunk1_docB"]]

    Returns
    -------
    list[list[list[float]]]
        Nested list matching input structure. Each innermost list is
        a 1024-dim float32 embedding vector.
    """
    import numpy as np
    from transformers import AutoModel

    model = AutoModel.from_pretrained(
        "perplexity-ai/pplx-embed-context-v1-0.6B",
        trust_remote_code=True,
    )

    raw_embeddings = model.encode(grouped_chunks)

    result = []
    for doc_embeddings in raw_embeddings:
        doc_vectors = []
        for chunk_vec in doc_embeddings:
            vec = np.asarray(chunk_vec, dtype=np.float32)
            doc_vectors.append(vec.tolist())
        result.append(doc_vectors)
    return result
