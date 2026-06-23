from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

import pytest

from dotmd.core.config import Settings
from dotmd.core.models import ExtractDepth, FileInfo
from dotmd.ingestion.pipeline import IndexingPipeline
from dotmd.ingestion.trickle import TrickleIndexer


def _surreal_settings(tmp_path: Path) -> Settings:
    data_dir = tmp_path / "data"
    index_dir = tmp_path / "index"
    data_dir.mkdir()
    index_dir.mkdir()
    return Settings(
        data_dir=data_dir,
        index_dir=index_dir,
        embedding={"url": "http://localhost:18088"},
        indexing={"paths": [str(data_dir)]},
        extraction={"depth": ExtractDepth.STRUCTURAL},
        surreal_retrieval={
            "url": "http://surrealdb:8000",
            "database": "dotmd",
            "embedding_dimension": 3,
        },
    )


def _surreal_pipeline(tmp_path: Path) -> IndexingPipeline:
    from dotmd.ingestion import pipeline as pipeline_module

    settings = _surreal_settings(tmp_path)
    with patch.object(
        pipeline_module,
        "_create_surreal_direct_writer",
        return_value=object(),
    ):
        return IndexingPipeline(settings)


@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        ("purge_application_source", ("fixture",)),
        ("drop_vectors", ()),
        ("drop_chunks", ()),
        ("clear", ()),
    ],
)
def test_surreal_pipeline_destructive_methods_refuse_and_preserve_local_tables(
    tmp_path: Path,
    method_name: str,
    args: tuple[object, ...],
) -> None:
    pipeline = _surreal_pipeline(tmp_path)

    if method_name == "clear":
        pipeline._settings.acronyms_path.write_text("{}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Surreal mode"):
        getattr(pipeline, method_name)(*args)

    if method_name == "clear":
        assert pipeline._settings.acronyms_path.exists()


@pytest.mark.asyncio
async def test_surreal_trickle_runs_startup_orphan_cleanup(
    tmp_path: Path,
) -> None:
    pipeline = _surreal_pipeline(tmp_path)
    settings = pipeline._settings
    indexer = TrickleIndexer(settings, pipeline)

    present_file = settings.data_dir / "present.md"
    present_file.write_text("# Present\n", encoding="utf-8")
    discovered = [
        FileInfo(
            path=present_file,
            title="Present",
            last_modified=datetime.now(UTC),
            size_bytes=present_file.stat().st_size,
        )
    ]

    purge_mock = Mock(return_value=(0, 0, 0))
    pipeline.purge_orphaned_files = purge_mock  # type: ignore[method-assign]

    from dotmd.ingestion import reader as reader_module

    with patch.object(reader_module, "discover_files_multi", return_value=discovered):
        await indexer._startup_checks()

    assert purge_mock.call_count == 1
    assert purge_mock.call_args.args == ({str(present_file)},)


@pytest.mark.asyncio
async def test_surreal_trickle_calls_deleted_file_purge_in_backlog(
    tmp_path: Path,
) -> None:
    settings = _surreal_settings(tmp_path)
    purge_mock = Mock(return_value=None)
    fake_pipeline = SimpleNamespace(
        file_tracker=SimpleNamespace(
            diff=lambda all_files: SimpleNamespace(
                new=[],
                modified=[],
                deleted=["/notes/orphan.md"],
                unchanged=[],
            )
        ),
        _purge_file=purge_mock,
    )
    indexer = TrickleIndexer(settings, cast(IndexingPipeline, fake_pipeline))

    from dotmd.ingestion import reader as reader_module

    with patch.object(reader_module, "discover_files_multi", return_value=[]):
        await indexer._process_backlog(asyncio.Event())

    assert purge_mock.call_count == 1
    assert purge_mock.call_args.args == ("/notes/orphan.md",)
