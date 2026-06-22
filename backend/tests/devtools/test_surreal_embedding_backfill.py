from __future__ import annotations

import argparse
from pathlib import Path

import devtools.surreal_embedding_backfill as backfill

from dotmd.ingestion.surreal_delta_sync import SurrealDeltaChange


def _embedding_ref(chunk_strategy: str, embedding_model: str, chunk_id: str) -> str:
    return "\x1f".join((chunk_strategy, embedding_model, chunk_id))


class _FakeBackfillConnection:
    def __init__(self, chunks: dict[str, dict], embeddings: dict[str, dict]) -> None:
        self._chunks = chunks
        self._embeddings = embeddings
        self.select_calls: list[str] = []
        self.closed = False

    def select(self, record: object) -> dict:
        self.select_calls.append(str(record))
        codec = backfill.SurrealRecordIdCodec()
        table = str(record).split(":", 1)[0]
        raw_identifier = codec.decode(record)  # type: ignore[arg-type]
        if table == "chunks":
            return dict(self._chunks.get(raw_identifier, {}))
        if table == "embeddings":
            return dict(self._embeddings.get(raw_identifier, {}))
        return {}

    def close(self) -> None:
        self.closed = True


class _FakeEncoder:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.batch_inputs: list[list[str]] = []

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        self.batch_inputs.append(list(texts))
        return [[float(index + 1), 0.0, 0.0] for index, _ in enumerate(texts)]


class _FakeWriter:
    def __init__(self, connection: object) -> None:
        self.connection = connection
        self.writes: list[list[SurrealDeltaChange]] = []

    def write_embeddings(self, rows: list[SurrealDeltaChange]) -> int:
        self.writes.append(list(rows))
        return len(rows)


def _set_env(monkeypatch) -> None:
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL_URL", "http://surreal.example:8000")
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL_NAMESPACE", "dotmd")
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL_DATABASE", "production")
    monkeypatch.delenv("DOTMD_SURREAL_RETRIEVAL_USERNAME", raising=False)
    monkeypatch.delenv("DOTMD_SURREAL_RETRIEVAL_PASSWORD", raising=False)
    monkeypatch.delenv("DOTMD_SURREAL_RETRIEVAL_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("DOTMD_EMBEDDING_URL", "http://embeddings.example:8088")
    monkeypatch.setenv("DOTMD_EMBEDDING_MODEL", "model-a")
    monkeypatch.setenv("DOTMD_TEI_BATCH_SIZE", "8")
    monkeypatch.setenv("DOTMD_CHUNK_STRATEGY", "env_strategy")


def test_dry_run_reads_chunk_ids_file_without_writing(monkeypatch, tmp_path: Path) -> None:
    _set_env(monkeypatch)
    ids_file = tmp_path / "chunk-ids.txt"
    ids_file.write_text("chunk-present\nchunk-missing\n", encoding="utf-8")

    connection = _FakeBackfillConnection(
        chunks={
            "chunk-present": {
                "chunk_id": "chunk-present",
                "text": "already embedded",
                "chunk_strategy": "row_strategy",
            },
            "chunk-missing": {
                "chunk_id": "chunk-missing",
                "text": "needs embedding",
            },
        },
        embeddings={
            _embedding_ref("row_strategy", "model-a", "chunk-present"): {
                "chunk_id": "chunk-present",
                "chunk_strategy": "row_strategy",
                "embedding_model": "model-a",
                "vector": [1.0, 0.0, 0.0],
            }
        },
    )
    encoder = _FakeEncoder()
    writer = _FakeWriter(connection)
    configs: list[object] = []

    monkeypatch.setattr(backfill, "SurrealConnection", lambda config: configs.append(config) or connection)
    monkeypatch.setattr(backfill, "EmbeddingEncoder", lambda *args, **kwargs: encoder)
    monkeypatch.setattr(backfill, "SurrealDeltaStoreWriter", lambda connection: writer)

    result = backfill._run_backfill(
        argparse.Namespace(
            chunk_id=[],
            chunk_ids_file=ids_file,
            apply=False,
            json_output=None,
        )
    )

    assert len(configs) == 1
    assert connection.closed is True
    assert encoder.batch_inputs == [["needs embedding"]]
    assert writer.writes == []
    assert result["status"] == "verified"
    assert result["mode"] == "dry_run"
    assert result["planned_writes"] == 1
    assert result["applied_writes"] == 0
    assert [row["status"] for row in result["chunk_results"]] == [
        "already_present",
        "dry_run_planned",
    ]


def test_apply_writes_only_missing_embedding(monkeypatch) -> None:
    _set_env(monkeypatch)

    connection = _FakeBackfillConnection(
        chunks={
            "chunk-present": {
                "chunk_id": "chunk-present",
                "text": "already embedded",
                "chunk_strategy": "row_strategy",
            },
            "chunk-missing": {
                "chunk_id": "chunk-missing",
                "text": "needs embedding",
            },
        },
        embeddings={
            _embedding_ref("row_strategy", "model-a", "chunk-present"): {
                "chunk_id": "chunk-present",
                "chunk_strategy": "row_strategy",
                "embedding_model": "model-a",
                "vector": [1.0, 0.0, 0.0],
            }
        },
    )
    encoder = _FakeEncoder()
    writer = _FakeWriter(connection)

    monkeypatch.setattr(backfill, "SurrealConnection", lambda config: connection)
    monkeypatch.setattr(backfill, "EmbeddingEncoder", lambda *args, **kwargs: encoder)
    monkeypatch.setattr(backfill, "SurrealDeltaStoreWriter", lambda connection: writer)

    result = backfill._run_backfill(
        argparse.Namespace(
            chunk_id=["chunk-present", "chunk-missing"],
            chunk_ids_file=None,
            apply=True,
            json_output=None,
        )
    )

    assert encoder.batch_inputs == [["needs embedding"]]
    assert len(writer.writes) == 1
    written = writer.writes[0]
    assert len(written) == 1
    assert written[0].row["chunk_id"] == "chunk-missing"
    assert written[0].row["chunk_strategy"] == "env_strategy"
    assert written[0].row["embedding_model"] == "model-a"
    assert result["status"] == "verified"
    assert result["mode"] == "apply"
    assert result["planned_writes"] == 1
    assert result["applied_writes"] == 1
    assert [row["status"] for row in result["chunk_results"]] == [
        "already_present",
        "written",
    ]


def test_empty_chunk_is_reported_and_blocks(monkeypatch) -> None:
    _set_env(monkeypatch)

    connection = _FakeBackfillConnection(
        chunks={
            "chunk-empty": {
                "chunk_id": "chunk-empty",
                "text": "   ",
            },
        },
        embeddings={},
    )
    encoder = _FakeEncoder()
    writer = _FakeWriter(connection)

    monkeypatch.setattr(backfill, "SurrealConnection", lambda config: connection)
    monkeypatch.setattr(backfill, "EmbeddingEncoder", lambda *args, **kwargs: encoder)
    monkeypatch.setattr(backfill, "SurrealDeltaStoreWriter", lambda connection: writer)

    result = backfill._run_backfill(
        argparse.Namespace(
            chunk_id=["chunk-empty"],
            chunk_ids_file=None,
            apply=True,
            json_output=None,
        )
    )

    assert encoder.batch_inputs == []
    assert writer.writes == []
    assert result["status"] == "blocked"
    assert result["planned_writes"] == 0
    assert result["applied_writes"] == 0
    assert result["skipped"] == [
        {
            "chunk_id": "chunk-empty",
            "status": "empty_text",
            "error": "chunk text is empty",
        }
    ]
    assert result["chunk_results"] == [
        {
            "chunk_id": "chunk-empty",
            "status": "empty_text",
            "error": "chunk text is empty",
        }
    ]


def test_help_includes_container_default_and_host_debug_examples() -> None:
    help_text = backfill.build_parser().format_help()

    assert "docker exec dotmd" in help_text
    assert "docker compose exec dotmd" in help_text
    assert "python3 devtools/surreal_embedding_backfill.py" in help_text
    assert "DOTMD_EMBEDDING_URL=http://embeddings:80" in help_text
    assert "DOTMD_SURREAL_RETRIEVAL_URL=http://surrealdb:8000" in help_text
    assert "Dev/debug only" in help_text
    assert "DOTMD_EMBEDDING_URL=http://127.0.0.1:8088" in help_text
    assert "DOTMD_SURREAL_RETRIEVAL_URL=ws://127.0.0.1:8000" in help_text
