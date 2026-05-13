"""Vendored Gmail source config."""

from __future__ import annotations

from pydantic import BaseModel as BaseConfig
from pydantic import Field


class SourceConfig(BaseConfig):
    """Source config schema."""


class GmailConfig(SourceConfig):
    """Gmail configuration schema."""

    after_date: str | None = Field(
        default=None,
        description="Only sync messages after this date in YYYY/MM/DD format.",
    )
    included_labels: list[str] = Field(
        default_factory=lambda: ["inbox", "sent"],
        description="Gmail labels to include.",
    )
    excluded_labels: list[str] = Field(
        default_factory=lambda: ["spam", "trash"],
        description="Gmail labels to exclude.",
    )
    excluded_categories: list[str] = Field(
        default_factory=lambda: ["promotions", "social"],
        description="Gmail categories to exclude.",
    )
    gmail_query: str | None = Field(default=None, description="Optional Gmail search query.")
    batch_size: int = Field(default=30, description="Entity generation batch size.")
    max_queue_size: int = Field(default=200, description="Entity generation queue size.")
    preserve_order: bool = Field(default=False, description="Preserve generation order.")
    stop_on_error: bool = Field(default=False, description="Stop generation on first error.")
