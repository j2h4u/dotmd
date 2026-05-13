"""Unit tests for Gmail federated bridge."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import httpx
import pytest

from dotmd.api.service import _is_low_signal_federated_candidate
from dotmd.core.models import SearchCandidate
from dotmd.ingestion.gmail_provider import (
    GMAIL_BODY_MAX_BYTES,
    GMAIL_PROVIDER_METADATA_KEYS,
    BaseConnectorBridge,
    GmailApplicationSourceProvider,
    GmailBridge,
    SourceAuthError,
    SourceTemporaryUnavailable,
    _decode_gmail_body,
)
from dotmd.search.federated import FederatedEngineOutcome


@pytest.fixture
def mock_token_provider() -> MagicMock:
    provider = MagicMock()
    provider.get_token.return_value = "fake-access-token"
    provider._cached_token = None
    return provider


def _json_response(payload: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=payload, request=httpx.Request("GET", "https://gmail"))


def _encoded(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


@pytest.fixture
def mock_gmail_messages_response() -> dict:
    return {"messages": [{"id": "msg001", "threadId": "thread001"}, {"id": "msg002", "threadId": "thread002"}]}


@pytest.fixture
def mock_gmail_message_detail() -> dict:
    return {
        "id": "msg001",
        "threadId": "thread001",
        "snippet": "Project update preview",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Project update"},
                {"name": "From", "value": "sender@example.com"},
                {"name": "Date", "value": "Mon, 1 Jan 2024 10:00:00 +0000"},
            ]
        },
    }


@pytest.fixture
def mock_gmail_message_full() -> dict:
    return {
        "id": "msg001",
        "threadId": "thread001",
        "payload": {
            "headers": [{"name": "Date", "value": "Mon, 1 Jan 2024 10:00:00 +0000"}],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _encoded("Plain body content")},
                }
            ],
        },
    }


def test_search_native_returns_candidates(
    mock_token_provider: MagicMock,
    mock_gmail_messages_response: dict,
    mock_gmail_message_detail: dict,
) -> None:
    provider = GmailApplicationSourceProvider(mock_token_provider, search_result_limit=10)
    detail_2 = dict(mock_gmail_message_detail, id="msg002", threadId="thread002")
    with patch.object(
        provider._bridge._client,
        "get",
        side_effect=[
            _json_response(mock_gmail_messages_response),
            _json_response(mock_gmail_message_detail),
            _json_response(detail_2),
        ],
    ):
        candidates = provider.search_native("test query", limit=2)

    assert len(candidates) == 2
    assert candidates[0].ref == "gmail:message:msg001"
    assert candidates[0].namespace == "gmail"
    assert candidates[0].descriptor_key == "gmail"
    assert candidates[0].retrieval_kind == "gmail:native"
    assert candidates[0].source_native_rank == 0
    assert candidates[0].source_native_score is None
    assert candidates[0].can_read is True
    assert candidates[0].can_materialize is False


def test_source_native_score_none_is_safe_for_federated_pipeline() -> None:
    candidate = _candidate(namespace="gmail", snippet="ok")
    outcome = FederatedEngineOutcome(
        name="gmail:native",
        status="ok",
        candidates=[candidate],
        reason=None,
        elapsed_ms=0.0,
    )
    assert outcome.candidates[0].source_native_score is None
    assert outcome.status == "ok"
    assert len(outcome.candidates) == 1


def test_source_neutral_low_signal_filter() -> None:
    assert _is_low_signal_federated_candidate(_candidate(namespace="gmail", snippet="ok")) is False
    assert _is_low_signal_federated_candidate(_candidate(namespace="telegram", snippet="ok")) is True


def test_search_candidate_ref_format() -> None:
    candidate = _candidate(namespace="gmail", snippet="snippet")
    assert candidate.ref == "gmail:message:abc"


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (401, SourceAuthError),
        (429, SourceTemporaryUnavailable),
        (500, SourceTemporaryUnavailable),
    ],
)
def test_search_native_api_errors(
    mock_token_provider: MagicMock,
    status_code: int,
    expected_error: type[Exception],
) -> None:
    provider = GmailApplicationSourceProvider(mock_token_provider)
    with patch.object(provider._bridge._client, "get", return_value=_json_response({}, status_code)):
        with pytest.raises(expected_error):
            provider.search_native("query", limit=5)


def test_provider_metadata_whitelist(
    mock_token_provider: MagicMock,
    mock_gmail_messages_response: dict,
    mock_gmail_message_detail: dict,
) -> None:
    provider = GmailApplicationSourceProvider(mock_token_provider)
    with patch.object(
        provider._bridge._client,
        "get",
        side_effect=[_json_response(mock_gmail_messages_response), _json_response(mock_gmail_message_detail)],
    ):
        candidate = provider.search_native("query", limit=1)[0]
    assert set(candidate.provider_metadata or {}) <= GMAIL_PROVIDER_METADATA_KEYS
    assert "body" not in (candidate.provider_metadata or {})


def test_read_unit_window_text_plain(
    mock_token_provider: MagicMock,
    mock_gmail_message_full: dict,
) -> None:
    provider = GmailApplicationSourceProvider(mock_token_provider)
    with patch.object(provider._bridge._client, "get", return_value=_json_response(mock_gmail_message_full)):
        result = provider.read_unit_window("gmail:message:msg001", before=0, after=0)
    assert result.namespace == "gmail"
    assert len(result.units) == 1
    assert result.units[0].unit_type == "email_body"
    assert result.units[0].text == "Plain body content"


def test_read_unit_window_html_only(mock_token_provider: MagicMock) -> None:
    provider = GmailApplicationSourceProvider(mock_token_provider)
    message = {
        "id": "msg001",
        "threadId": "thread001",
        "payload": {
            "headers": [],
            "parts": [{"mimeType": "text/html", "body": {"data": _encoded("<p>Hello <b>there</b></p>")}}],
        },
    }
    with patch.object(provider._bridge._client, "get", return_value=_json_response(message)):
        result = provider.read_unit_window("gmail:message:msg001", before=0, after=0)
    assert result.units[0].text == "Hello there"
    assert "<" not in result.units[0].text


def test_decode_gmail_body_multipart_alternative() -> None:
    payload = {
        "parts": [
            {"mimeType": "text/html", "body": {"data": _encoded("<p>HTML</p>")}},
            {"mimeType": "text/plain", "body": {"data": _encoded("Plain")}},
        ]
    }
    assert _decode_gmail_body(payload) == "Plain"


def test_decode_gmail_body_empty_payload() -> None:
    assert _decode_gmail_body({"parts": []}) == ""


def test_decode_gmail_body_size_limit() -> None:
    payload = {"mimeType": "text/plain", "body": {"data": _encoded("x" * (GMAIL_BODY_MAX_BYTES + 100))}}
    result = _decode_gmail_body(payload)
    assert len(result.encode("utf-8")) <= GMAIL_BODY_MAX_BYTES + len("[truncated]")
    assert result.endswith("[truncated]")


def test_decode_gmail_body_malformed_base64() -> None:
    assert _decode_gmail_body({"mimeType": "text/plain", "body": {"data": "%%%%"}}) == ""


@pytest.mark.skip(reason="depends on 37-03")
def test_gmail_descriptor() -> None:
    from dotmd.ingestion.source_registry import gmail_source_descriptor

    assert gmail_source_descriptor().namespace == "gmail"


@pytest.mark.skip(reason="depends on 37-03")
def test_lifecycle_build_missing_config_raises() -> None:
    raise AssertionError("implemented in 37-03")


def test_base_connector_bridge_is_abstract(mock_token_provider: MagicMock) -> None:
    with pytest.raises(TypeError):
        BaseConnectorBridge()
    assert issubclass(GmailBridge, BaseConnectorBridge)
    assert isinstance(GmailBridge(mock_token_provider), BaseConnectorBridge)


def test_to_search_candidate_generic_fields(mock_token_provider: MagicMock) -> None:
    bridge = GmailBridge(mock_token_provider)
    candidate = bridge.to_search_candidate(
        {
            "message_id": "abc",
            "thread_id": "thread",
            "sender": "sender@example.com",
            "subject": "Subject",
            "sent_at": "2024-01-01T00:00:00+00:00",
            "snippet": "Snippet",
            "body": "not whitelisted",
        },
        0,
    )
    assert candidate.namespace == "gmail"
    assert candidate.descriptor_key == "gmail"
    assert candidate.source_native_score is None
    assert candidate.source_native_rank == 0
    assert set(candidate.provider_metadata or {}) <= GMAIL_PROVIDER_METADATA_KEYS


def test_gmail_provider_describe_source_raises_not_implemented(mock_token_provider: MagicMock) -> None:
    provider = GmailApplicationSourceProvider(mock_token_provider)
    with pytest.raises(NotImplementedError, match="federated-only source"):
        provider.describe_source()


def test_gmail_provider_export_changes_raises_not_implemented(mock_token_provider: MagicMock) -> None:
    provider = GmailApplicationSourceProvider(mock_token_provider)
    with pytest.raises(NotImplementedError, match="federated-only source"):
        provider.export_changes(cursor=None, limit=10)


def test_gmail_provider_export_changes_accepts_all_protocol_params(mock_token_provider: MagicMock) -> None:
    provider = GmailApplicationSourceProvider(mock_token_provider)
    with pytest.raises(NotImplementedError, match="federated-only source"):
        provider.export_changes(
            None,
            10,
            updated_after="2026-01-01",
            updated_after_cursor="cursor-abc",
        )


def _candidate(namespace: str, snippet: str) -> SearchCandidate:
    retrieval_kind = "tg:fts" if namespace == "telegram" else "gmail:native"
    ref = "telegram:dialog:1:message:1" if namespace == "telegram" else "gmail:message:abc"
    return SearchCandidate(
        ref=ref,
        namespace=namespace,
        descriptor_key=namespace,
        source_kind="chat" if namespace == "telegram" else "email",
        retrieval_kind=retrieval_kind,
        title=None,
        snippet=snippet,
        fused_score=0.0,
        can_read=True,
        can_materialize=False,
        source_native_score=None,
        source_native_rank=0,
    )
