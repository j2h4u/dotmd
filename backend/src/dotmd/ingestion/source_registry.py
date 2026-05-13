"""Default declarative source registry entries."""

from __future__ import annotations

from dotmd.core.models import (
    SourceAuthSchema,
    SourceCapability,
    SourceConfigSchema,
    SourceCursorSchema,
    SourceDescriptor,
    SourceDisplayMetadata,
    SourceSchemaField,
)
from dotmd.core.source_registry import SourceRegistry


def filesystem_source_descriptor() -> SourceDescriptor:
    """Return the declarative descriptor for filesystem Markdown sources."""
    return SourceDescriptor(
        namespace="filesystem",
        source_kind="local_filesystem",
        display=SourceDisplayMetadata(
            display_name="Filesystem Markdown",
            description="Local Markdown files discovered from configured paths.",
            labels=["local", "markdown"],
            docs_slug="filesystem",
        ),
        config_schema=SourceConfigSchema(
            name="FilesystemSourceConfig",
            fields=[
                SourceSchemaField(
                    name="paths",
                    field_type="list[str]",
                    required=True,
                    description="Markdown source root paths to discover",
                ),
                SourceSchemaField(
                    name="exclude",
                    field_type="list[str]",
                    required=False,
                    description="Optional glob/path patterns excluded during discovery",
                ),
            ],
        ),
        auth_schema=SourceAuthSchema(auth_kind="none"),
        cursor_schema=SourceCursorSchema(
            cursor_kind="fingerprint",
            description=(
                "fingerprint-based change detection over content and metadata "
                "fingerprints; filesystem does not own provider cursor commits"
            ),
        ),
        capabilities=[
            SourceCapability.LOCAL_SYNC,
            SourceCapability.MATERIALIZATION,
            SourceCapability.BROWSE_TREE,
        ],
        metadata_json={
            "media_type": "text/markdown",
            "parser_name": "markdown",
        },
    )


def telegram_source_descriptor() -> SourceDescriptor:
    """Return the declarative descriptor for Telegram application sources."""
    return SourceDescriptor(
        namespace="telegram",
        source_kind="chat",
        display=SourceDisplayMetadata(
            display_name="Telegram",
            description="Telegram dialogs and messages exported by mcp-telegram.",
            labels=["application", "chat"],
            docs_slug="telegram",
        ),
        config_schema=SourceConfigSchema(
            name="TelegramSourceConfig",
            fields=[
                SourceSchemaField(
                    name="socket_path",
                    field_type="path",
                    required=False,
                    description="Optional mcp-telegram daemon socket path override",
                )
            ],
        ),
        auth_schema=SourceAuthSchema(
            auth_kind="delegated",
            delegated_to="mcp-telegram",
        ),
        cursor_schema=SourceCursorSchema(
            cursor_kind="provider_checkpoint",
            examples=["telegram:v1:dialog:<dialog_id>:message:<message_id>"],
            description="Provider-owned cursor emitted by the mcp-telegram daemon.",
        ),
        capabilities=[
            SourceCapability.LOCAL_SYNC,
            SourceCapability.READ_UNIT_WINDOW,
            SourceCapability.INCREMENTAL_CURSOR,
            SourceCapability.FEDERATED_SEARCH,
        ],
        metadata_json={"transport": "mcp-telegram-daemon"},
    )


def gmail_source_descriptor() -> SourceDescriptor:
    """Return the declarative descriptor for Gmail federated search.

    AIR-03 compliance: registered via the same SourceRegistry path as
    filesystem_source_descriptor() and telegram_source_descriptor().
    """
    return SourceDescriptor(
        namespace="gmail",
        source_kind="email",
        display=SourceDisplayMetadata(
            display_name="Gmail",
            description="Gmail inbox and sent messages via Google OAuth.",
            labels=["application", "email"],
            docs_slug="gmail",
        ),
        config_schema=SourceConfigSchema(
            name="GmailSourceConfig",
            fields=[
                SourceSchemaField(
                    name="client_id",
                    field_type="str",
                    required=True,
                    description="Google OAuth client ID",
                ),
                SourceSchemaField(
                    name="client_secret",
                    field_type="str",
                    required=True,
                    description="Google OAuth client secret",
                ),
                SourceSchemaField(
                    name="search_result_limit",
                    field_type="int",
                    required=False,
                    description="Max results per search query (1-500, default 20)",
                ),
            ],
        ),
        auth_schema=SourceAuthSchema(
            auth_kind="oauth_refresh",
            methods=["oauth_browser", "oauth_token"],
        ),
        cursor_schema=SourceCursorSchema(
            cursor_kind="none",
            description="Federated-only - no local cursor for spike",
        ),
        capabilities=[
            SourceCapability.FEDERATED_SEARCH,
            SourceCapability.READ_UNIT_WINDOW,
        ],
        metadata_json={
            "media_type": "message/rfc822",
            "parser_name": "gmail-message",
        },
    )


def default_source_registry() -> SourceRegistry:
    """Return the Phase 32 default source registry."""
    registry = SourceRegistry()
    registry.register(filesystem_source_descriptor())
    registry.register(telegram_source_descriptor())
    registry.register(gmail_source_descriptor())
    return registry
