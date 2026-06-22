"""GAP-04 (T-34-14) and GAP-05 (T-34-15): Phase 34 behavioral gaps.

GAP-04: service.search(include_federated=True) end-to-end fan-out includes
        tg:fts engine in source_status when Telegram lifecycle bundle has
        FEDERATED_SEARCH capability and search_native.

GAP-05: can_materialize=False for every Phase 34 SearchCandidate; manual
        sweep + assertion test.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tests.conftest import make_surreal_service


def _get_service(tmp_path: Path):  # type: ignore[no-untyped-def]
    return make_surreal_service(
        tmp_path,
        data_dir=tmp_path,
        indexing_paths=[str(tmp_path)],
        embedding_url="http://localhost:8088",
    )


def test_telegram_federated_engine_participates(tmp_path: Path) -> None:
    """T-34-14: service.search(include_federated=True) includes tg:fts in
    source_status when Telegram lifecycle bundle has FEDERATED_SEARCH
    capability and search_native method.

    The source_status in the returned SearchResponse must contain an entry
    with name="tg:fts" when federated search is explicitly enabled.
    """
    from dotmd.core.models import SearchCandidate, SearchResponse
    from tests.search.conftest import StubFederatedProvider, make_federated_bundle

    service = _get_service(tmp_path)

    # Build a Telegram-like federated bundle with FEDERATED_SEARCH capability
    tg_provider = StubFederatedProvider(
        candidates=[
            SearchCandidate(
                ref="telegram:dialog:42:message:99",
                namespace="telegram",
                descriptor_key="telegram",
                source_kind="chat",
                retrieval_kind="tg:fts",
                snippet="kantine is open",
                fused_score=0.8,
                can_read=True,
                can_materialize=False,
            )
        ]
    )
    tg_bundle = make_federated_bundle(name="telegram", provider=tg_provider)

    # Inject the bundle directly into the service's federated bundle dict
    service._lifecycle_bundles["telegram"] = tg_bundle

    # Stub _execute_search so local engines don't need a real index
    with patch.object(service, "_execute_search", return_value=[]):
        response = service.search(
            "kantine",
            rerank=False,
            expand=False,
            include_federated=True,
        )

    assert isinstance(response, SearchResponse)

    source_names = {s.name for s in response.source_status}
    assert "tg:fts" in source_names, (
        f"Expected 'tg:fts' in source_status but got: {source_names!r}. "
        "The federated fan-out did not include the Telegram engine. "
        "This indicates the fan-out integration in search_async is not yet complete (TODO stub)."
    )


def test_phase_34_candidates_never_materializable(tmp_path: Path) -> None:
    """T-34-15: can_materialize=False for every Phase 34 SearchCandidate.

    This sweeps across:
    - Local filesystem candidates from build_candidates
    - Federated Telegram candidates constructed by TelegramApplicationSourceProvider
    - Direct SearchCandidate construction (the model default)

    If any candidate has can_materialize=True the test fails.
    """
    from dotmd.core.models import SearchCandidate
    from dotmd.ingestion.telegram_provider import TelegramApplicationSourceProvider

    # --- Case 1: Default SearchCandidate construction ---
    local_candidate = SearchCandidate(
        ref="filesystem:/mnt/test.md#0",
        namespace="filesystem",
        descriptor_key="filesystem-mnt",
        source_kind="markdown",
        retrieval_kind="semantic",
        snippet="local snippet",
        fused_score=0.9,
        can_read=True,
    )
    assert local_candidate.can_materialize is False, (
        "Default SearchCandidate.can_materialize must be False (D-14)"
    )

    # --- Case 2: Federated Telegram candidates from search_native ---
    class _FakeClient:
        def search_messages(self, query: str, limit: int, dialog_id: int | None = None) -> dict:
            return {
                "messages": [
                    {
                        "dialog_id": 42,
                        "dialog_name": "Project Chat",
                        "message_id": 99,
                        "text": "kantine is open",
                        "sender": "alice",
                        "sent_at": "2026-04-12T08:11:00+00:00",
                        "score": 0.93,
                    }
                ]
            }

        def read_source_unit_window(self, unit_ref: str, before: int, after: int) -> dict:
            return {"units": []}

    provider = TelegramApplicationSourceProvider(_FakeClient())  # type: ignore[arg-type]
    tg_candidates = provider.search_native("kantine", limit=5)
    assert len(tg_candidates) >= 1, "Expected at least one Telegram candidate"
    for i, c in enumerate(tg_candidates):
        assert c.can_materialize is False, (
            f"TelegramApplicationSourceProvider candidate[{i}] has "
            f"can_materialize={c.can_materialize!r} — must be False (D-14)"
        )

    # --- Case 3: Candidates from service.search() ---
    service = _get_service(tmp_path)
    stub_candidates = [
        SearchCandidate(
            ref=f"filesystem:/mnt/doc{i}.md#0",
            namespace="filesystem",
            descriptor_key="filesystem-mnt",
            source_kind="markdown",
            retrieval_kind="semantic",
            snippet=f"snippet {i}",
            fused_score=float(i + 1) / 10,
            can_read=True,
            can_materialize=False,
        )
        for i in range(3)
    ]
    with patch.object(service, "_execute_search", return_value=stub_candidates):
        response = service.search("test", rerank=False, expand=False)

    for i, c in enumerate(response.candidates):
        assert c.can_materialize is False, (
            f"service.search() candidate[{i}] ref={c.ref!r} has "
            f"can_materialize={c.can_materialize!r} — must always be False (D-14)"
        )
