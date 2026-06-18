from __future__ import annotations

import argparse
import json
from pathlib import Path

from devtools.surreal_embedding_shard_runner import _copy_rows_to_shards, _shard_index

from dotmd.storage.surreal import SurrealConnection, SurrealStoreConfig


def test_shard_index_is_stable_and_in_range() -> None:
    row = {
        "chunk_strategy": "contextual_512_50",
        "embedding_model": "model",
        "chunk_id": "chunk-alpha",
    }

    assert _shard_index(row, 3) == _shard_index(dict(row), 3)
    assert 0 <= _shard_index(row, 3) < 3


def test_copy_rows_to_shards_from_existing_embeddings_table(tmp_path: Path) -> None:
    target_url = f"surrealkv://{tmp_path / 'target.surreal.db'}"
    with SurrealConnection(
        SurrealStoreConfig(url=target_url, namespace="dotmd_test", database="shards")
    ) as connection:
        connection.query("DEFINE TABLE embeddings SCHEMALESS;")
        connection.insert_rows(
            "embeddings",
            [
                {
                    "id": "embeddings:one",
                    "chunk_id": "chunk-one",
                    "chunk_strategy": "contextual_512_50",
                    "embedding_model": "model",
                    "text_hash": "h1",
                    "embedding": [1.0, 0.0, 0.0],
                },
                {
                    "id": "embeddings:two",
                    "chunk_id": "chunk-two",
                    "chunk_strategy": "contextual_512_50",
                    "embedding_model": "model",
                    "text_hash": "h2",
                    "embedding": [0.0, 1.0, 0.0],
                },
            ],
            batch_size=10,
        )

    result = _copy_rows_to_shards(
        argparse.Namespace(
            target_url=target_url,
            target_namespace="dotmd_test",
            target_database="shards",
            embedding_shard_count=2,
            source_sqlite=None,
            batch_size=10,
            progress_every=100,
            recreate_shards=True,
        )
    )

    assert result["status"] == "verified"
    assert result["copied_rows"] == 2
    assert sum(result["observed_counts"].values()) == 2
    json.dumps(result)
