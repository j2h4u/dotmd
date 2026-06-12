"""Minimal vendored Gmail source implementation from Airweave."""
# pyright: reportAttributeAccessIssue=false, reportIncompatibleMethodOverride=false

from __future__ import annotations

from collections.abc import AsyncGenerator
from inspect import isawaitable
from typing import Any

from dotmd.vendor.airweave.decorators import source
from dotmd.vendor.airweave.entities_base import BaseEntity
from dotmd.vendor.airweave.gmail_config import GmailConfig
from dotmd.vendor.airweave.source_base import (
    AirweaveHttpClient,
    AuthenticationMethod,
    BaseSource,
    ContextualLogger,
    NodeSelectionData,
    OAuthType,
    RateLimitLevel,
    SourceAuthProvider,
    SyncCursor,
)


@source(
    name="Gmail",
    short_name="gmail",
    auth_methods=[
        AuthenticationMethod.OAUTH_BROWSER,
        AuthenticationMethod.OAUTH_TOKEN,
        AuthenticationMethod.AUTH_PROVIDER,
    ],
    oauth_type=OAuthType.WITH_REFRESH,
    requires_byoc=True,
    auth_config_class=None,
    config_class=GmailConfig,
    labels=["Communication", "Email"],
    supports_continuous=True,
    federated_search=True,
    rate_limit_level=RateLimitLevel.ORG,
    cursor_class=dict,
)
class GmailSource(BaseSource):
    """Gmail source connector shell.

    NOTE: GmailSource does not implement search() — bridge uses direct API.
    """

    @classmethod
    async def create(
        cls,
        *,
        auth: SourceAuthProvider,
        logger: ContextualLogger,
        http_client: AirweaveHttpClient,
        config: GmailConfig,
    ) -> GmailSource:
        """Create a new Gmail source instance."""
        instance = cls(auth=auth, logger=logger, http_client=http_client)
        config_dict = config.model_dump() if config else {}
        instance.batch_size = int(config_dict.get("batch_size", 30))
        instance.max_queue_size = int(config_dict.get("max_queue_size", 200))
        instance.preserve_order = bool(config_dict.get("preserve_order", False))
        instance.stop_on_error = bool(config_dict.get("stop_on_error", False))
        instance.after_date = config_dict.get("after_date")
        instance.included_labels = config_dict.get("included_labels", ["inbox", "sent"])
        instance.excluded_labels = config_dict.get("excluded_labels", ["spam", "trash"])
        instance.excluded_categories = config_dict.get(
            "excluded_categories", ["promotions", "social"]
        )
        instance.gmail_query = config_dict.get("gmail_query")
        return instance

    def _build_gmail_query(self) -> str | None:
        """Build Gmail API query string from filter configuration."""
        if getattr(self, "gmail_query", None):
            self.logger.debug("Using custom Gmail query")
            return str(self.gmail_query)
        query_parts = self._build_query_parts()
        if not query_parts:
            return None
        query = " ".join(query_parts)
        self.logger.debug("Built Gmail query with %d parts", len(query_parts))
        return query

    def _build_query_parts(self) -> list[str]:
        """Build individual query parts from filter configuration."""
        parts: list[str] = []
        if getattr(self, "after_date", None):
            parts.append(f"after:{self.after_date}")
        included_labels = getattr(self, "included_labels", [])
        if included_labels:
            if len(included_labels) == 1:
                parts.append(f"in:{included_labels[0]}")
            else:
                parts.append("{" + " OR ".join(f"in:{label}" for label in included_labels) + "}")
        for label in getattr(self, "excluded_labels", []):
            parts.append(f"-in:{label}")
        for category in getattr(self, "excluded_categories", []):
            parts.append(f"-category:{category}")
        return parts

    async def generate_entities(
        self,
        *,
        cursor: SyncCursor | None = None,
        files: object | None = None,
        node_selections: list[NodeSelectionData] | None = None,
    ) -> AsyncGenerator[BaseEntity, None]:
        """Generation is outside dotMD's federated-search spike path."""
        if False:
            yield BaseEntity()

    async def validate(self) -> None:
        """Validate credentials by checking token availability."""
        token = self.auth.get_token()
        if isawaitable(token):
            await token

    def _message_matches_filters(self, message_data: dict[str, Any]) -> bool:
        """Check if a message matches configured filters."""
        label_ids = [label.lower() for label in message_data.get("labelIds", []) or []]
        included_labels = getattr(self, "included_labels", None)
        if included_labels and not any(label.lower() in label_ids for label in included_labels):
            return False
        excluded_labels = getattr(self, "excluded_labels", None)
        return not (
            excluded_labels and any(label.lower() in label_ids for label in excluded_labels)
        )
