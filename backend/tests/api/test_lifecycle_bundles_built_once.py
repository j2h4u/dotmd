"""GAP-01 (T-34-08): Lifecycle bundle is built once at service init and reused.

Requirement: build_if_configured is called only during DotMDService.__init__,
never during search() calls. Per-request rebuild would inflate latency/TEI cost.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests.conftest import make_surreal_service


def _get_service(tmp_path: Path):  # type: ignore[no-untyped-def]
    return make_surreal_service(
        tmp_path,
        data_dir=tmp_path,
        indexing_paths=[str(tmp_path)],
        embedding_url="http://localhost:8088",
    )


def test_lifecycle_bundles_built_once(tmp_path: Path) -> None:
    """Lifecycle bundles are built at init; no rebuild happens during search().

    T-34-08: Mock asserts build_if_configured is NOT called during search()
    after service construction completes.
    """
    service = _get_service(tmp_path)

    # Record calls to build_if_configured AFTER construction is complete.
    # Any call here means a per-request rebuild is happening — that's the defect.
    call_log: list[str] = []
    original_build = service._source_runtime_factory.build_if_configured

    def tracking_build(namespace: str) -> Any:
        call_log.append(namespace)
        return original_build(namespace)

    service._source_runtime_factory.build_if_configured = tracking_build  # type: ignore[method-assign]

    # Stub _execute_search so search doesn't need a real index
    from dotmd.core.models import SearchCandidate

    stub_candidate = SearchCandidate(
        ref="filesystem:/mnt/test.md#0",
        namespace="filesystem",
        descriptor_key="filesystem-mnt",
        source_kind="markdown",
        retrieval_kind="semantic",
        snippet="test",
        fused_score=0.9,
        can_read=True,
    )
    with patch.object(service, "_execute_search", return_value=[stub_candidate]):
        service.search("hello", rerank=False, expand=False)

    # The core assertion: zero calls to build_if_configured during search()
    assert call_log == [], (
        f"build_if_configured was called {len(call_log)} time(s) during search(): "
        f"{call_log!r} — lifecycle bundles must be built once at init, not per-request."
    )
