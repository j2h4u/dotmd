"""Telegram application-source provider."""

from __future__ import annotations

import hashlib
import json
import socket
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Protocol

from dotmd.core.models import (
    ApplicationSourceChange,
    ApplicationSourceChangeBatch,
    ApplicationSourceDescription,
    SearchCandidate,
    SourceDocument,
    SourceUnit,
    SourceUnitWindow,
)
from dotmd.ingestion.source_provider import ApplicationSourceProviderProtocol

LOW_SIGNAL_TEXTS = {
    "ok",
    "yes",
    "yep",
    "no",
    "+1",
    "thanks",
    "thx",
    "да",
    "нет",
    "ок",
    "окей",
    "спасибо",
    "ага",
    "угу",
}

# Metadata whitelist for federated search candidates (cycle-2 MEDIUM fold-in)
TELEGRAM_PROVIDER_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "dialog_id",
        "message_id",
        "sender",
        "sent_at",
        "dialog_name",
    }
)


class TelegramSourceClientProtocol(Protocol):
    """Structured source client boundary owned outside dotMD."""

    def describe_source(self) -> dict:
        """Describe the structured Telegram source."""
        ...

    def export_source_changes(
        self,
        cursor: str | None,
        limit: int,
        updated_after: str | None = None,
        updated_after_cursor: str | None = None,
    ) -> dict:
        """Export structured message changes."""
        ...

    def read_source_unit_window(
        self,
        unit_ref: str,
        before: int,
        after: int,
    ) -> dict:
        """Read neighboring structured message units."""
        ...

    def search_messages(
        self,
        query: str,
        limit: int,
        dialog_id: int | None = None,
    ) -> dict:
        """Search Telegram messages via daemon FTS. Returns {messages: [...], total: int, ...}"""
        ...


class UnixSocketTelegramSourceClient:
    """Synchronous client for the mcp-telegram UNIX-socket JSON API."""

    def __init__(self, socket_path: Path, *, timeout_seconds: float = 30.0) -> None:
        self._socket_path = socket_path
        self._timeout_seconds = timeout_seconds

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    def describe_source(self) -> dict:
        """Describe the structured Telegram source."""
        return self._request({"method": "describe_source"})

    def export_source_changes(
        self,
        cursor: str | None,
        limit: int,
        updated_after: str | None = None,
        updated_after_cursor: str | None = None,
    ) -> dict:
        """Export structured message changes."""
        payload: dict = {
            "method": "export_source_changes",
            "cursor": cursor,
            "limit": limit,
        }
        if updated_after is not None:
            payload["updated_after"] = updated_after
        if updated_after_cursor is not None:
            payload["updated_after_cursor"] = updated_after_cursor
        return self._request(payload)

    def read_source_unit_window(
        self,
        unit_ref: str,
        before: int,
        after: int,
    ) -> dict:
        """Read neighboring structured message units."""
        return self._request(
            {
                "method": "read_source_unit_window",
                "unit_ref": unit_ref,
                "before": before,
                "after": after,
            }
        )

    def search_messages(
        self,
        query: str,
        limit: int,
        dialog_id: int | None = None,
    ) -> dict:
        """Search Telegram messages via daemon FTS. Returns {messages: [...], total: int, ...}"""
        payload: dict = {
            "method": "search_messages",
            "query": query,
            "limit": limit,
        }
        if dialog_id is not None:
            payload["dialog_id"] = dialog_id
        return self._request(payload)

    def _request(self, payload: dict) -> dict:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(self._timeout_seconds)
            try:
                sock.connect(str(self._socket_path))
                sock.sendall(json.dumps(payload).encode("utf-8") + b"\n")
                data = b""
                while not data.endswith(b"\n"):
                    chunk = sock.recv(1024 * 1024)
                    if not chunk:
                        break
                    data += chunk
            except TimeoutError as exc:
                raise RuntimeError("Telegram daemon request timed out") from exc
        if not data:
            raise RuntimeError("Telegram daemon returned no response")
        response = json.loads(data.decode("utf-8"))
        if response.get("ok") is not True:
            error = response.get("message") or response.get("error") or "unknown error"
            raise RuntimeError(f"Telegram daemon request failed: {error}")
        data_payload = response.get("data")
        if not isinstance(data_payload, dict):
            raise RuntimeError("Telegram daemon returned malformed data payload")
        return data_payload


class TelegramApplicationSourceProvider(ApplicationSourceProviderProtocol):
    """Map structured Telegram payloads into dotMD source models."""

    def __init__(self, client: TelegramSourceClientProtocol) -> None:
        self._client = client

    def describe_source(self) -> ApplicationSourceDescription:
        return ApplicationSourceDescription(**self._client.describe_source())

    def export_changes(
        self,
        cursor: str | None,
        limit: int,
        updated_after: str | None = None,
        updated_after_cursor: str | None = None,
    ) -> ApplicationSourceChangeBatch:
        payload = self._client.export_source_changes(
            cursor,
            limit,
            updated_after=updated_after,
            updated_after_cursor=updated_after_cursor,
        )
        return ApplicationSourceChangeBatch(
            changes=[self._change_from_payload(change) for change in payload.get("changes", [])],
            next_cursor=payload.get("next_cursor"),
            checkpoint_cursor=payload.get("checkpoint_cursor"),
            updated_after=payload.get("updated_after"),
            updated_after_cursor=payload.get("updated_after_cursor"),
        )

    def read_unit_window(
        self,
        unit_ref: str,
        before: int,
        after: int,
    ) -> SourceUnitWindow:
        payload = self._client.read_source_unit_window(unit_ref, before, after)
        return SourceUnitWindow(
            namespace=payload["namespace"],
            document_ref=payload["document_ref"],
            unit_ref=payload["unit_ref"],
            units=[self._unit_from_payload(unit) for unit in payload["units"]],
            metadata_json=payload.get("metadata_json", {}),
        )

    def search_native(self, query: str, limit: int) -> list[SearchCandidate]:
        """Search Telegram messages and return SearchCandidate list.

        Returns candidates with federated-specific fields (source_native_score,
        source_native_rank, provider_metadata). can_read is derived from
        provider capability at runtime.
        """
        payload = self._client.search_messages(query=query, limit=limit)
        hits = payload.get("messages", [])

        # Derive can_read from provider capability (cycle-2 MEDIUM fold-in)
        can_read_local = callable(
            getattr(self._client, "read_source_unit_window", None),
        )

        candidates: list[SearchCandidate] = []
        for rank, hit in enumerate(hits):
            dialog_id = _coerce_int(hit["dialog_id"])
            message_id = _coerce_int(hit["message_id"])
            ref = f"telegram:dialog:{dialog_id}:message:{message_id}"
            text = str(hit.get("text", ""))

            # Whitelist provider_metadata keys (cycle-2 MEDIUM fold-in)
            metadata = {
                key: hit[key]
                for key in TELEGRAM_PROVIDER_METADATA_KEYS
                if key in hit and hit[key] is not None
            }

            candidates.append(
                SearchCandidate(
                    ref=ref,
                    namespace="telegram",
                    descriptor_key="telegram",  # cycle-2 HIGH-1
                    source_kind="chat",
                    retrieval_kind="tg:fts",
                    title=hit.get("dialog_name"),
                    snippet=text,
                    fused_score=0.0,
                    can_read=can_read_local,  # cycle-2 MEDIUM (derived)
                    can_materialize=False,
                    source_native_score=hit.get("score"),
                    source_native_rank=rank,  # zero-based per D-RANK-ZERO-BASED
                    provider_metadata=metadata or None,
                )
            )
        return candidates

    def _change_from_payload(self, payload: dict) -> ApplicationSourceChange:
        document_payload = payload["document"]
        unit_payload = payload["unit"]
        if _is_source_document_payload(document_payload) and _is_source_unit_payload(unit_payload):
            return ApplicationSourceChange(
                document=SourceDocument(**document_payload),
                unit=self._unit_from_payload(unit_payload),
            )
        return ApplicationSourceChange(
            document=self._document_from_payload(document_payload, unit_payload),
            unit=self._unit_from_payload(unit_payload),
        )

    def _document_from_payload(
        self,
        document_payload: dict,
        unit_payload: dict,
    ) -> SourceDocument:
        dialog_id = _coerce_int(document_payload.get("dialog_id", unit_payload["dialog_id"]))
        dialog_name = str(
            document_payload.get("dialog_name")
            or unit_payload.get("dialog_name")
            or f"Telegram dialog {dialog_id}"
        )
        updated_at = _parse_datetime(
            document_payload.get("updated_at")
            or unit_payload.get("unit_updated_at")
            or unit_payload.get("edit_date")
            or unit_payload["sent_at"]
        )
        document_ref = f"dialog:{dialog_id}"
        metadata_json = {
            "dialog_id": dialog_id,
            "dialog_name": dialog_name,
            **{
                key: value
                for key, value in document_payload.items()
                if key not in {"dialog_id", "dialog_name", "updated_at"}
            },
        }

        return SourceDocument(
            namespace="telegram",
            document_ref=document_ref,
            ref=f"telegram:{document_ref}",
            title=dialog_name,
            source_uri=f"telegram://dialog/{dialog_id}",
            media_type="text/plain",
            parser_name="telegram-message",
            document_type="dialog",
            updated_at=updated_at,
            content_fingerprint=_sha256_json(
                {
                    "dialog_id": dialog_id,
                    "latest_unit_ref": _unit_ref(unit_payload),
                    "updated_at": _isoformat_z(updated_at),
                }
            ),
            metadata_fingerprint=_sha256_json(metadata_json),
            metadata_json=metadata_json,
        )

    def _unit_from_payload(self, payload: dict) -> SourceUnit:
        if _is_source_unit_payload(payload):
            metadata_json = dict(payload.get("metadata_json", {}))
            text = str(payload.get("text") or "")
            metadata_json["standalone_search"] = not is_low_signal_telegram_text(text)
            return SourceUnit(
                namespace=payload["namespace"],
                document_ref=payload["document_ref"],
                unit_ref=payload["unit_ref"],
                unit_type=payload["unit_type"],
                text=text,
                order_key=payload["order_key"],
                fingerprint=payload["fingerprint"],
                updated_at=_parse_datetime(payload["updated_at"]),
                metadata_json=metadata_json,
                chunking_hints=payload.get("chunking_hints", {}),
            )

        dialog_id = _coerce_int(payload["dialog_id"])
        message_id = _coerce_int(payload["message_id"])
        unit_ref = _unit_ref(payload)
        text = str(payload.get("text") or "")
        updated_at = _parse_datetime(
            payload.get("unit_updated_at") or payload.get("edit_date") or payload["sent_at"]
        )
        metadata_json = {
            "dialog_id": dialog_id,
            "dialog_name": payload.get("dialog_name"),
            "message_id": message_id,
            "sent_at": payload.get("sent_at"),
            "sender_id": payload.get("sender_id"),
            "sender_name": payload.get("sender_name"),
            "topic_id": payload.get("topic_id"),
            "topic_title": payload.get("topic_title"),
            "reply_to_msg_id": payload.get("reply_to_msg_id"),
            "edit_date": payload.get("edit_date"),
            "is_deleted": bool(payload.get("is_deleted", False)),
            "standalone_search": not is_low_signal_telegram_text(text),
        }

        return SourceUnit(
            namespace="telegram",
            document_ref=f"dialog:{dialog_id}",
            unit_ref=unit_ref,
            unit_type="message",
            text=text,
            order_key=f"{message_id:020d}",
            fingerprint=_message_fingerprint(text, metadata_json, payload),
            updated_at=updated_at,
            metadata_json=metadata_json,
            chunking_hints={},
        )


def public_ref_for_unit(unit: SourceUnit) -> str:
    """Return the public message ref for a Telegram source unit."""
    return f"telegram:{unit.unit_ref}"


def is_low_signal_telegram_text(text: str) -> bool:
    """Return whether text is too small/noisy for standalone search."""
    stripped = text.strip()
    if not stripped:
        return True
    if stripped.casefold() in LOW_SIGNAL_TEXTS:
        return True
    if not any(ch.isalnum() for ch in stripped):
        return True
    return not any(ch.isalnum() for ch in stripped) or any(
        unicodedata.category(ch).startswith("S") for ch in stripped
    )


def _message_fingerprint(
    text: str,
    metadata_json: dict,
    payload: dict,
) -> str:
    values = {
        "normalized_text": " ".join(text.split()),
        "sent_at": metadata_json["sent_at"],
        "edit_date": metadata_json["edit_date"],
        "is_deleted": metadata_json["is_deleted"],
        "sender_id": metadata_json["sender_id"],
        "topic_id": metadata_json["topic_id"],
        "reply_to_msg_id": metadata_json["reply_to_msg_id"],
        "unit_updated_at": payload.get("unit_updated_at"),
    }
    return "telegram-message-v1:" + json.dumps(
        values,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _unit_ref(payload: dict) -> str:
    dialog_id = _coerce_int(payload["dialog_id"])
    message_id = _coerce_int(payload["message_id"])
    return f"dialog:{dialog_id}:message:{message_id}"


def _is_source_document_payload(payload: dict) -> bool:
    return {
        "namespace",
        "document_ref",
        "ref",
        "title",
        "source_uri",
        "updated_at",
        "content_fingerprint",
        "metadata_fingerprint",
    }.issubset(payload)


def _is_source_unit_payload(payload: dict) -> bool:
    return {
        "namespace",
        "document_ref",
        "unit_ref",
        "unit_type",
        "text",
        "order_key",
        "fingerprint",
        "updated_at",
    }.issubset(payload)


def _coerce_int(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not a valid Telegram id")
    return int(value)  # type: ignore[arg-type]


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError(f"Invalid datetime value: {value!r}")
    return datetime.fromisoformat(value)


def _sha256_json(value: dict) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _isoformat_z(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")
