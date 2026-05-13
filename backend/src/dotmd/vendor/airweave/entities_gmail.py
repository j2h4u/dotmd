"""Gmail entity schemas vendored from Airweave."""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from pydantic import computed_field

from dotmd.vendor.airweave.entities_base import (
    AirweaveField,
    BaseEntity,
    Breadcrumb,
    DeletionEntity,
    EmailEntity,
    FileEntity,
)


def _parse_header(headers: list[dict[str, str]], name: str) -> str | None:
    """Return the first case-insensitive header value."""
    target = name.lower()
    for header in headers:
        if header.get("name", "").lower() == target:
            return header.get("value")
    return None


def _parse_address_list(value: str | None) -> list[str]:
    """Split a comma-separated address header."""
    if not value:
        return []
    return [address.strip() for address in value.split(",") if address.strip()]


def _parse_rfc2822_date(value: str | None) -> datetime | None:
    """Parse an RFC 2822 Date header."""
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def _internal_date_to_datetime(ms: str | None) -> datetime | None:
    """Convert Gmail's internalDate epoch-millis string to datetime."""
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=UTC)
    except (TypeError, ValueError):
        return None


class GmailThreadEntity(BaseEntity):
    """Schema for Gmail thread entities."""

    thread_key: str = AirweaveField(..., description="Stable Airweave thread key.", is_entity_id=True)
    gmail_thread_id: str = AirweaveField(..., description="Native Gmail thread ID", embeddable=False)
    title: str = AirweaveField(..., description="Display title.", is_name=True, embeddable=True)
    last_message_at: datetime | None = AirweaveField(
        None,
        description="Most recent message timestamp.",
        is_updated_at=True,
    )
    snippet: str | None = AirweaveField(None, description="Thread snippet.", embeddable=True)
    history_id: str | None = AirweaveField(None, description="Thread history ID.", embeddable=False)
    message_count: int | None = AirweaveField(0, description="Number of messages.", embeddable=False)
    label_ids: list[str] = AirweaveField(
        default_factory=list,
        description="Thread labels.",
        embeddable=True,
    )

    @classmethod
    def from_api(cls, data: dict[str, Any], *, thread_id: str) -> GmailThreadEntity:
        """Build from a Gmail API thread detail JSON object."""
        snippet = data.get("snippet", "")
        messages = data.get("messages", []) or []
        last_message_at = None
        if messages:
            sorted_messages = sorted(
                messages,
                key=lambda msg: int(msg.get("internalDate", 0)),
                reverse=True,
            )
            last_message_at = _internal_date_to_datetime(sorted_messages[0].get("internalDate"))
        title = snippet[:50] + "..." if len(snippet) > 50 else snippet or "Thread"
        return cls(
            breadcrumbs=[],
            thread_key=f"thread_{thread_id}",
            gmail_thread_id=thread_id,
            title=title,
            last_message_at=last_message_at,
            snippet=snippet,
            history_id=data.get("historyId"),
            message_count=len(messages),
            label_ids=messages[0].get("labelIds", []) if messages else [],
        )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Direct link to open the thread in Gmail."""
        return f"https://mail.google.com/mail/u/0/#inbox/{self.gmail_thread_id}"


class GmailMessageEntity(EmailEntity):
    """Schema for Gmail message entities."""

    message_key: str = AirweaveField(..., description="Stable Airweave message key.", is_entity_id=True)
    message_id: str = AirweaveField(..., description="Native Gmail message ID", embeddable=False)
    subject: str = AirweaveField(..., description="Subject line.", is_name=True, embeddable=True)
    sent_at: datetime = AirweaveField(..., description="Sent timestamp.", is_created_at=True)
    internal_timestamp: datetime = AirweaveField(
        ...,
        description="Internal Gmail timestamp.",
        is_updated_at=True,
    )
    thread_id: str = AirweaveField(..., description="Thread ID.", embeddable=False)
    sender: str | None = AirweaveField(None, description="Sender.", embeddable=True)
    to: list[str] = AirweaveField(default_factory=list, description="Recipients.", embeddable=True)
    cc: list[str] = AirweaveField(default_factory=list, description="CC recipients.", embeddable=True)
    bcc: list[str] = AirweaveField(default_factory=list, description="BCC recipients.", embeddable=True)
    date: datetime | None = AirweaveField(None, description="Date header.", embeddable=True)
    snippet: str | None = AirweaveField(None, description="Message snippet.", embeddable=True)
    label_ids: list[str] = AirweaveField(default_factory=list, description="Labels.", embeddable=True)
    internal_date: datetime | None = AirweaveField(
        None,
        description="Internal Gmail timestamp.",
        embeddable=False,
    )
    web_url_value: str | None = AirweaveField(None, description="Gmail URL.", embeddable=False)

    @classmethod
    def from_api(
        cls,
        data: dict[str, Any],
        *,
        thread_id: str,
        breadcrumbs: list[Breadcrumb],
    ) -> GmailMessageEntity:
        """Build from a Gmail API message detail JSON object."""
        message_id = data.get("id", "")
        internal_date = _internal_date_to_datetime(data.get("internalDate"))
        payload = data.get("payload", {}) or {}
        headers = payload.get("headers", []) or []
        subject = _parse_header(headers, "subject") or f"Message {message_id}"
        date = _parse_rfc2822_date(_parse_header(headers, "date"))
        sent_at = date or internal_date or datetime.fromtimestamp(0, tz=UTC)
        return cls(
            breadcrumbs=breadcrumbs,
            message_key=f"msg_{message_id}",
            message_id=message_id,
            subject=subject,
            sent_at=sent_at,
            internal_timestamp=internal_date or sent_at,
            url=f"https://mail.google.com/mail/u/0/#inbox/{message_id}",
            size=data.get("sizeEstimate", 0),
            file_type="html",
            mime_type="text/html",
            local_path=None,
            thread_id=thread_id,
            sender=_parse_header(headers, "from"),
            to=_parse_address_list(_parse_header(headers, "to")),
            cc=_parse_address_list(_parse_header(headers, "cc")),
            bcc=_parse_address_list(_parse_header(headers, "bcc")),
            date=date,
            snippet=data.get("snippet"),
            label_ids=data.get("labelIds", []),
            internal_date=internal_date,
            web_url_value=f"https://mail.google.com/mail/u/0/#inbox/{message_id}",
        )

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Direct link to open the message in Gmail."""
        return self.web_url_value or f"https://mail.google.com/mail/u/0/#inbox/{self.message_id}"


class GmailAttachmentEntity(FileEntity):
    """Schema for Gmail attachment entities."""

    attachment_key: str = AirweaveField(
        ...,
        description="Stable Airweave attachment key.",
        is_entity_id=True,
    )
    filename: str = AirweaveField(..., description="Attachment filename.", is_name=True, embeddable=True)
    message_id: str = AirweaveField(..., description="Message ID.", embeddable=False)
    attachment_id: str = AirweaveField(..., description="Gmail attachment ID.", embeddable=False)
    thread_id: str = AirweaveField(..., description="Thread ID.", embeddable=False)
    web_url_value: str | None = AirweaveField(None, description="Parent message URL.", embeddable=False)

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Link to the parent message view in Gmail."""
        return self.web_url_value or f"https://mail.google.com/mail/u/0/#inbox/{self.message_id}"


class GmailMessageDeletionEntity(DeletionEntity):
    """Deletion signal for a Gmail message."""

    deletes_entity_class = GmailMessageEntity

    message_key: str = AirweaveField(..., description="Deleted message key.", is_entity_id=True)
    label: str = AirweaveField(..., description="Deletion label.", is_name=True, embeddable=True)
    message_id: str = AirweaveField(..., description="Deleted Gmail message ID.", embeddable=False)
    thread_id: str | None = AirweaveField(None, description="Thread ID.", embeddable=False)

    @computed_field(return_type=str)
    def web_url(self) -> str:
        """Fallback link to Gmail inbox for the deleted message."""
        return f"https://mail.google.com/mail/u/0/#inbox/{self.message_id}"
