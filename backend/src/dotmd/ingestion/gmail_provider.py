"""Gmail federated source provider."""

from __future__ import annotations

import base64
import binascii
import hashlib
import html
import re
from abc import ABC, abstractmethod
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from dotmd.core.models import (
    ApplicationSourceChangeBatch,
    ApplicationSourceDescription,
    SearchCandidate,
    SourceUnit,
    SourceUnitWindow,
)
from dotmd.ingestion.source_provider import ApplicationSourceProviderProtocol
from dotmd.vendor.airweave.shims import GmailOAuthTokenProvider

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
GMAIL_PROVIDER_METADATA_KEYS = frozenset(
    {"message_id", "thread_id", "sender", "subject", "sent_at"}
)
GMAIL_BODY_MAX_BYTES = 1024 * 1024
GMAIL_API_TIMEOUT_SECONDS = 10.0


class SourceAuthError(RuntimeError):
    """Raised when Gmail returns an auth failure."""


class SourceTemporaryUnavailableError(RuntimeError):
    """Raised when Gmail is temporarily unavailable."""


SourceTemporaryUnavailable = SourceTemporaryUnavailableError


class BaseConnectorBridge(ABC):
    """Generic bridge contract for Airweave-style connectors to dotMD.

    Implementations provide connector-specific search and read logic. The
    abstract interface satisfies D-03: future connectors implement this same
    contract even when their concrete API calls differ from Gmail.
    """

    @abstractmethod
    def search_native(self, query: str, limit: int) -> list[SearchCandidate]:
        """Search the external source and return SearchCandidate objects."""
        ...

    @abstractmethod
    def read_unit_window(self, unit_ref: str, before: int, after: int) -> SourceUnitWindow:
        """Fetch full content for a previously returned ref."""
        ...

    @abstractmethod
    def to_search_candidate(self, entity_fields: dict[str, Any], rank: int) -> SearchCandidate:
        """Map connector entity fields to a SearchCandidate."""
        ...


class GmailBridge(BaseConnectorBridge):
    """Bridge direct Gmail API search/read calls into dotMD federated candidates."""

    def __init__(
        self,
        token_provider: GmailOAuthTokenProvider,
        *,
        search_result_limit: int = 10,
    ) -> None:
        self._token_provider = token_provider
        self._search_result_limit = search_result_limit
        self._client = httpx.Client(
            timeout=httpx.Timeout(GMAIL_API_TIMEOUT_SECONDS, connect=5.0)
        )

    def search_native(self, query: str, limit: int) -> list[SearchCandidate]:
        """Search Gmail and return ranked federated candidates.

        Known limitation: for limit=N this performs 1 list call plus up to N
        metadata calls. Gmail's batch endpoint could reduce this to fewer
        round-trips, but multipart/mixed batching is deferred from this spike.
        Follow-up: file a beads task for batch metadata fetch optimization.
        """
        bounded_limit = max(0, min(limit, self._search_result_limit))
        if bounded_limit == 0:
            return []

        response = self._get(
            f"{GMAIL_API_BASE}/messages",
            params={"q": query, "maxResults": bounded_limit},
            timeout_message="Gmail API timed out",
        )
        messages = response.get("messages", []) or []

        candidates: list[SearchCandidate] = []
        for rank, message in enumerate(messages[:bounded_limit]):
            message_id = str(message.get("id", ""))
            if not message_id:
                continue
            detail = self._get(
                f"{GMAIL_API_BASE}/messages/{message_id}",
                params={
                    "format": "metadata",
                    "metadataHeaders": ["Subject", "From", "Date"],
                },
                timeout_message="Gmail API timed out",
            )
            fields = _message_fields_from_metadata(detail)
            candidates.append(self.to_search_candidate(fields, rank))
        return candidates

    def read_unit_window(self, unit_ref: str, before: int, after: int) -> SourceUnitWindow:
        """Read a Gmail message body as a single source-unit window."""
        if not unit_ref.startswith("gmail:message:"):
            raise ValueError(f"Unknown Gmail unit ref: {unit_ref}")
        message_id = unit_ref.removeprefix("gmail:message:")
        response = self._get(
            f"{GMAIL_API_BASE}/messages/{message_id}",
            params={"format": "full"},
            timeout_message="Gmail read timed out",
        )
        payload = response.get("payload", {}) or {}
        text = _decode_gmail_body(payload)
        if not text:
            text = str(response.get("snippet") or "")
        sent_at = _parse_gmail_date(
            _extract_header((payload.get("headers", []) or []), "date")
        ) or datetime.fromtimestamp(0)
        metadata = {
            "message_id": message_id,
            "thread_id": response.get("threadId"),
            "subject": _extract_header((payload.get("headers", []) or []), "subject"),
            "sender": _extract_header((payload.get("headers", []) or []), "from"),
            "sent_at": sent_at.isoformat(),
        }
        unit = SourceUnit(
            namespace="gmail",
            document_ref=f"message:{message_id}",
            unit_ref=f"message:{message_id}",
            unit_type="email_body",
            text=text,
            order_key="00000000000000000000",
            fingerprint=_fingerprint_text(text, metadata),
            updated_at=sent_at,
            metadata_json={k: v for k, v in metadata.items() if v is not None},
            chunking_hints={},
        )
        return SourceUnitWindow(
            namespace="gmail",
            document_ref=f"message:{message_id}",
            unit_ref=f"message:{message_id}",
            units=[unit],
            metadata_json={k: v for k, v in metadata.items() if v is not None},
        )

    def to_search_candidate(self, entity_fields: dict[str, Any], rank: int) -> SearchCandidate:
        """Map Gmail message metadata into a federated SearchCandidate."""
        message_id = str(entity_fields["message_id"])
        metadata = {
            key: entity_fields[key]
            for key in GMAIL_PROVIDER_METADATA_KEYS
            if key in entity_fields and entity_fields[key] is not None
        }
        return SearchCandidate(
            ref=f"gmail:message:{message_id}",
            namespace="gmail",
            descriptor_key="gmail",
            source_kind="email",
            retrieval_kind="gmail:native",
            title=entity_fields.get("subject"),
            snippet=str(entity_fields.get("snippet") or entity_fields.get("subject") or ""),
            fused_score=0.0,
            can_read=True,
            can_materialize=False,
            source_native_score=None,
            source_native_rank=rank,
            provider_metadata=metadata or None,
        )

    def _get(
        self,
        url: str,
        *,
        params: dict[str, str | int | list[str]] | None,
        timeout_message: str,
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._token_provider.get_token()}"}
        try:
            response = self._client.get(
                url,
                headers=headers,
                params=params,
                timeout=httpx.Timeout(GMAIL_API_TIMEOUT_SECONDS, connect=5.0),
            )
        except httpx.TimeoutException as exc:
            raise SourceTemporaryUnavailableError(timeout_message) from exc

        if response.status_code in {401, 403}:
            self._token_provider._cached_token = None
            raise SourceAuthError(f"Gmail auth failed: {response.status_code}")
        if response.status_code == 429:
            raise SourceTemporaryUnavailableError("Gmail rate limited (429)")
        if response.status_code >= 500:
            raise SourceTemporaryUnavailableError(f"Gmail server error: {response.status_code}")
        if response.status_code >= 400:
            raise RuntimeError(f"Gmail API request failed: {response.status_code}")
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("Gmail API returned a malformed JSON object")
        return data


class GmailApplicationSourceProvider(ApplicationSourceProviderProtocol):
    """ApplicationSourceProviderProtocol for Gmail federated-only access."""

    def __init__(
        self,
        token_provider: GmailOAuthTokenProvider,
        *,
        search_result_limit: int = 10,
    ) -> None:
        self._bridge = GmailBridge(token_provider, search_result_limit=search_result_limit)

    def describe_source(self) -> ApplicationSourceDescription:
        raise NotImplementedError(
            "Gmail is a federated-only source; describe_source is not supported"
        )

    def export_changes(
        self,
        cursor: str | None,
        limit: int,
        updated_after: str | None = None,
        updated_after_cursor: str | None = None,
    ) -> ApplicationSourceChangeBatch:
        """Not supported because Gmail is federated-only."""
        raise NotImplementedError(
            "Gmail is a federated-only source; export_changes is not supported"
        )

    def search_native(self, query: str, limit: int) -> list[SearchCandidate]:
        return self._bridge.search_native(query, limit)

    def read_unit_window(self, unit_ref: str, before: int, after: int) -> SourceUnitWindow:
        return self._bridge.read_unit_window(unit_ref, before, after)


def _message_fields_from_metadata(message: dict[str, Any]) -> dict[str, Any]:
    payload = message.get("payload", {}) or {}
    headers = payload.get("headers", []) or []
    sent_at = _parse_gmail_date(_extract_header(headers, "date"))
    return {
        "message_id": message.get("id"),
        "thread_id": message.get("threadId"),
        "sender": _extract_header(headers, "from"),
        "subject": _extract_header(headers, "subject"),
        "sent_at": sent_at.isoformat() if sent_at else None,
        "snippet": message.get("snippet"),
    }


def _extract_header(headers: list[dict[str, str]], name: str) -> str | None:
    target = name.casefold()
    for header in headers:
        if header.get("name", "").casefold() == target:
            return header.get("value")
    return None


def _decode_gmail_body(payload: dict[str, Any]) -> str:
    """Decode Gmail MIME payload, preferring text/plain over stripped HTML."""
    plain, html_text = _decode_payload_part(payload)
    text = plain or _strip_html(html_text or "")
    if len(text.encode("utf-8")) <= GMAIL_BODY_MAX_BYTES:
        return text
    truncated = text.encode("utf-8")[:GMAIL_BODY_MAX_BYTES].decode("utf-8", errors="ignore")
    return truncated + "[truncated]"


def _decode_payload_part(part: dict[str, Any]) -> tuple[str, str]:
    mime_type = str(part.get("mimeType") or "")
    body = part.get("body", {}) or {}
    data = body.get("data")
    plain = ""
    html_text = ""
    if isinstance(data, str):
        decoded = _decode_base64url_text(data)
        if mime_type == "text/plain":
            plain = decoded
        elif mime_type == "text/html":
            html_text = decoded

    for child in part.get("parts", []) or []:
        child_plain, child_html = _decode_payload_part(child)
        if not plain:
            plain = child_plain
        if not html_text:
            html_text = child_html
    return plain, html_text


def _decode_base64url_text(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="ignore")
    except (binascii.Error, ValueError):
        return ""


def _parse_gmail_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except (TypeError, ValueError):
        return None


def _strip_html(html_text: str) -> str:
    without_scripts = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html_text)
    without_tags = re.sub(r"(?s)<[^>]+>", " ", without_scripts)
    return " ".join(html.unescape(without_tags).split())


def _fingerprint_text(text: str, metadata: dict[str, object]) -> str:
    hasher = hashlib.sha256()
    hasher.update(text.encode("utf-8"))
    for key in sorted(metadata):
        hasher.update(str(key).encode("utf-8"))
        hasher.update(str(metadata[key]).encode("utf-8"))
    return "gmail-message-v1:" + hasher.hexdigest()
