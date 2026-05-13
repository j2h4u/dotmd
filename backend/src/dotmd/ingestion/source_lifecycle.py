"""Source runtime lifecycle construction boundary."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, SkipValidation, model_validator

from dotmd.core.config import Settings
from dotmd.core.models import SourceCapability, SourceDescriptor
from dotmd.core.source_registry import SourceRegistry
from dotmd.ingestion.source import FilesystemMarkdownSourceAdapter
from dotmd.ingestion.source_provider import ApplicationSourceProviderProtocol
from dotmd.ingestion.source_registry import default_source_registry
from dotmd.ingestion.telegram_provider import (
    TelegramApplicationSourceProvider,
    TelegramSourceClientProtocol,
    UnixSocketTelegramSourceClient,
)
from dotmd.storage.metadata import SQLiteMetadataStore

logger = logging.getLogger(__name__)


class SourceLifecycleConfigError(ValueError):
    """Raised when a source runtime cannot be constructed from local config."""


class FilesystemSourceConfig(BaseModel):
    """Local filesystem runtime config."""

    model_config = ConfigDict(extra="forbid", strict=True)

    paths: list[str]
    exclude: list[str] = Field(default_factory=list)


class TelegramSourceConfig(BaseModel):
    """Local Telegram delegated-runtime config."""

    model_config = ConfigDict(extra="forbid", strict=True)

    socket_path: Path | None = None


class GmailSourceConfig(BaseModel):
    """Gmail OAuth runtime config.

    The refresh_token field holds the OAuth refresh token directly in the config
    object rather than in SourceAccess.delegated_to. This avoids a semantic
    mismatch because delegated_to is for identity delegation strings, not raw
    secrets.

    search_result_limit is validated to stay within Gmail API bounds (1-500).
    Default 20 is conservative because Gmail metadata fetch currently performs
    O(n) round-trips.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    client_id: str
    client_secret: str
    refresh_token: str
    search_result_limit: int = Field(
        default=20,
        ge=1,
        le=500,
        description="Max results per Gmail search query. Gmail API hard cap is 500.",
    )


SourceConfig = FilesystemSourceConfig | TelegramSourceConfig | GmailSourceConfig


class SourceCredentialRef(BaseModel):
    """Reference to credential material owned outside source descriptors."""

    model_config = ConfigDict(extra="forbid", strict=True)

    namespace: str
    credential_ref: str | None = None


class SourceAccess(BaseModel):
    """Access result supplied to runtime construction."""

    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["none", "delegated"]
    delegated_to: str | None = None


class SourceConfigRecord(BaseModel):
    """Typed local config plus credential reference for one source namespace."""

    model_config = ConfigDict(extra="forbid", strict=True)

    namespace: str
    config: SourceConfig
    credential_ref: SourceCredentialRef | None = None

    @model_validator(mode="after")
    def _default_credential_ref(self) -> SourceConfigRecord:
        if self.credential_ref is None:
            self.credential_ref = SourceCredentialRef(namespace=self.namespace)
        return self


class SourceConfigStoreProtocol(Protocol):
    """Local source config lookup boundary."""

    def get_config(self, namespace: str) -> SourceConfigRecord | None:
        """Return local source config for a namespace."""
        ...


class SourceCredentialProviderProtocol(Protocol):
    """Credential/access provider boundary used by runtime construction."""

    def get_access(
        self,
        descriptor: SourceDescriptor,
        credential_ref: SourceCredentialRef,
    ) -> SourceAccess:
        """Return source access details for a descriptor."""
        ...


class SourceCursorStoreProtocol(Protocol):
    """Cursor/checkpoint persistence boundary."""

    def get_checkpoint(self, namespace: str) -> dict[str, object] | None:
        """Return durable checkpoint state for a namespace."""
        ...

    def commit_checkpoint(
        self,
        namespace: str,
        checkpoint_cursor: str | None,
        *,
        conn: Any,
        metadata_json: dict[str, object] | None = None,
    ) -> None:
        """Persist a checkpoint inside the caller-owned transaction."""
        ...

    def record_error(
        self,
        namespace: str,
        error: str,
        *,
        conn: Any | None = None,
    ) -> None:
        """Persist source checkpoint diagnostics."""
        ...


class InMemorySourceConfigStore(SourceConfigStoreProtocol):
    """Copy-safe in-memory source config store for local runtime wiring."""

    def __init__(self, records: list[SourceConfigRecord] | None = None) -> None:
        self._records: dict[str, SourceConfigRecord] = {}
        for record in records or []:
            self.set_config(record)

    def set_config(self, record: SourceConfigRecord) -> None:
        """Store config for one namespace."""
        self._records[record.namespace] = record.model_copy(deep=True)

    def get_config(self, namespace: str) -> SourceConfigRecord | None:
        """Return config for one namespace."""
        record = self._records.get(namespace)
        if record is None:
            return None
        return record.model_copy(deep=True)


class DefaultSourceCredentialProvider(SourceCredentialProviderProtocol):
    """Default no-auth and delegated-auth access provider."""

    def get_access(
        self,
        descriptor: SourceDescriptor,
        credential_ref: SourceCredentialRef,
    ) -> SourceAccess:
        """Return source access based on descriptor auth schema."""
        if credential_ref.namespace != descriptor.namespace:
            raise SourceLifecycleConfigError(
                f"{descriptor.namespace}.credential_ref namespace mismatch"
            )

        if descriptor.auth_schema.auth_kind == "none":
            return SourceAccess(kind="none")

        if descriptor.auth_schema.auth_kind == "delegated":
            delegated_to = descriptor.auth_schema.delegated_to
            if delegated_to is None:
                raise SourceLifecycleConfigError(
                    f"{descriptor.namespace}.auth.delegated_to is required"
                )
            if not credential_ref.credential_ref:
                raise SourceLifecycleConfigError(
                    f"{descriptor.namespace}.credential_ref is required"
                )
            return SourceAccess(kind="delegated", delegated_to=delegated_to)

        raise SourceLifecycleConfigError(
            f"{descriptor.namespace}.auth_kind unsupported: "
            f"{descriptor.auth_schema.auth_kind}"
        )


class SQLiteSourceCursorStore(SourceCursorStoreProtocol):
    """SQLite-backed source cursor store preserving caller transactions."""

    def __init__(self, metadata_store: SQLiteMetadataStore) -> None:
        self._metadata_store = metadata_store

    def get_checkpoint(self, namespace: str) -> dict[str, object] | None:
        """Return durable checkpoint state for a namespace."""
        return self._metadata_store.get_source_checkpoint(namespace)

    def commit_checkpoint(
        self,
        namespace: str,
        checkpoint_cursor: str | None,
        *,
        conn: Any,
        metadata_json: dict[str, object] | None = None,
    ) -> None:
        """Persist a checkpoint inside the caller-owned transaction."""
        self._metadata_store.commit_source_checkpoint(
            namespace,
            checkpoint_cursor,
            conn=conn,
            metadata_json=metadata_json,
        )

    def record_error(
        self,
        namespace: str,
        error: str,
        *,
        conn: Any | None = None,
    ) -> None:
        """Persist source checkpoint diagnostics."""
        self._metadata_store.record_source_checkpoint_error(
            namespace,
            error,
            conn=conn,
        )


class SourceRuntimeBundle(BaseModel):
    """Inspectable source runtime bundle assembled by the lifecycle factory."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    descriptor: SourceDescriptor
    config: SourceConfig
    access: SourceAccess
    cursor_store: SkipValidation[SourceCursorStoreProtocol]
    source: FilesystemMarkdownSourceAdapter | None = None
    provider: SkipValidation[ApplicationSourceProviderProtocol | None] = None
    metadata_json: dict[str, object] = Field(default_factory=dict)

    @property
    def supports_federated_search(self) -> bool:
        """Check if this bundle supports federated search (Phase 34).

        A bundle supports federated search if:
        1. The descriptor declares FEDERATED_SEARCH capability
        2. A provider is present
        3. The provider has a search_native method (duck-type check)
        """
        if SourceCapability.FEDERATED_SEARCH not in self.descriptor.capabilities:
            return False
        provider = self.provider
        if provider is None:
            return False
        return callable(getattr(provider, "search_native", None))


class SourceRuntimeFactory:
    """Build source runtime bundles from registry, config, access, and cursors."""

    def __init__(
        self,
        *,
        registry: SourceRegistry,
        config_store: SourceConfigStoreProtocol,
        credential_provider: SourceCredentialProviderProtocol,
        cursor_store: SourceCursorStoreProtocol,
        telegram_client_factory: Callable[
            [Path],
            TelegramSourceClientProtocol,
        ] = UnixSocketTelegramSourceClient,
    ) -> None:
        self._registry = registry
        self._config_store = config_store
        self._credential_provider = credential_provider
        self._cursor_store = cursor_store
        self._telegram_client_factory = telegram_client_factory

    def build(self, namespace: str) -> SourceRuntimeBundle:
        """Build a source runtime bundle or raise on missing required config."""
        descriptor = self._registry.require(namespace)
        record = self._require_config(namespace)
        credential_ref = self._credential_ref(record)

        if namespace == "filesystem":
            config = self._require_filesystem_config(record.config)
            access = self._credential_provider.get_access(descriptor, credential_ref)
            return SourceRuntimeBundle(
                descriptor=descriptor,
                config=config,
                access=access,
                cursor_store=self._cursor_store,
                source=FilesystemMarkdownSourceAdapter(),
                metadata_json=dict(descriptor.metadata_json),
            )

        if namespace == "telegram":
            config = self._require_telegram_config(record.config)
            socket_path = config.socket_path
            if socket_path is None:
                raise SourceLifecycleConfigError("telegram.socket_path is required")
            access = self._credential_provider.get_access(descriptor, credential_ref)
            client = self._telegram_client_factory(socket_path)
            return SourceRuntimeBundle(
                descriptor=descriptor,
                config=config,
                access=access,
                cursor_store=self._cursor_store,
                provider=TelegramApplicationSourceProvider(client),
                metadata_json=dict(descriptor.metadata_json),
            )

        if namespace == "gmail":
            config = self._require_gmail_config(record.config)
            from dotmd.ingestion.gmail_provider import GmailApplicationSourceProvider
            from dotmd.vendor.airweave.shims import GmailOAuthTokenProvider

            # Cycle 3 HIGH N2: Gmail bypasses DefaultSourceCredentialProvider.get_access().
            # That provider only handles auth_kind "none" and "delegated"; Gmail uses
            # auth_kind="oauth_refresh" and keeps OAuth material in GmailSourceConfig.
            access = SourceAccess(kind="none")
            token_provider = GmailOAuthTokenProvider(
                credentials={
                    "client_id": config.client_id,
                    "client_secret": config.client_secret,
                    "refresh_token": config.refresh_token,
                }
            )
            provider = GmailApplicationSourceProvider(
                token_provider=token_provider,
                search_result_limit=config.search_result_limit,
            )
            return SourceRuntimeBundle(
                descriptor=descriptor,
                config=config,
                access=access,
                cursor_store=self._cursor_store,
                provider=provider,
                metadata_json=dict(descriptor.metadata_json),
            )

        raise SourceLifecycleConfigError(f"{namespace} runtime is not supported")

    def build_if_configured(self, namespace: str) -> SourceRuntimeBundle | None:
        """Build an optional runtime if enough config is present."""
        record = self._config_store.get_config(namespace)
        if record is None:
            return None
        if namespace == "telegram":
            config = record.config
            if not isinstance(config, TelegramSourceConfig):
                return None
            if config.socket_path is None:
                return None
        elif namespace == "gmail":
            config = record.config
            if not isinstance(config, GmailSourceConfig):
                return None
        return self.build(namespace)

    def _require_config(self, namespace: str) -> SourceConfigRecord:
        record = self._config_store.get_config(namespace)
        if record is None:
            if namespace == "filesystem":
                raise SourceLifecycleConfigError("filesystem.paths is required")
            if namespace == "telegram":
                raise SourceLifecycleConfigError("telegram.socket_path is required")
            raise SourceLifecycleConfigError(f"{namespace}.config is required")
        return record

    def _credential_ref(self, record: SourceConfigRecord) -> SourceCredentialRef:
        if record.credential_ref is None:
            return SourceCredentialRef(namespace=record.namespace)
        return record.credential_ref

    def _require_filesystem_config(
        self,
        config: SourceConfig,
    ) -> FilesystemSourceConfig:
        if not isinstance(config, FilesystemSourceConfig):
            raise SourceLifecycleConfigError("filesystem.paths config is required")
        if not config.paths:
            raise SourceLifecycleConfigError("filesystem.paths is required")
        return config

    def _require_telegram_config(self, config: SourceConfig) -> TelegramSourceConfig:
        if not isinstance(config, TelegramSourceConfig):
            raise SourceLifecycleConfigError("telegram.socket_path config is required")
        if config.socket_path is None:
            raise SourceLifecycleConfigError("telegram.socket_path is required")
        return cast(TelegramSourceConfig, config)

    def _require_gmail_config(self, config: SourceConfig) -> GmailSourceConfig:
        if not isinstance(config, GmailSourceConfig):
            raise SourceLifecycleConfigError(
                f"gmail config must be GmailSourceConfig, got {type(config).__name__}"
            )
        return config


def source_runtime_factory_from_settings(
    settings: Settings,
    metadata_store: SQLiteMetadataStore,
) -> SourceRuntimeFactory:
    """Build the default source runtime factory from live dotMD settings."""
    records = [
        SourceConfigRecord(
            namespace="filesystem",
            config=FilesystemSourceConfig(
                paths=list(settings.indexing_paths),
                exclude=list(settings.effective_indexing_exclude),
            ),
            credential_ref=SourceCredentialRef(namespace="filesystem"),
        )
    ]
    if settings.telegram_daemon_socket is not None:
        records.append(
            SourceConfigRecord(
                namespace="telegram",
                config=TelegramSourceConfig(
                    socket_path=settings.telegram_daemon_socket,
                ),
                credential_ref=SourceCredentialRef(
                    namespace="telegram",
                    credential_ref="mcp-telegram",
                ),
            )
        )
    gmail_vars = {
        "DOTMD_GMAIL_CLIENT_ID": settings.gmail_client_id,
        "DOTMD_GMAIL_CLIENT_SECRET": settings.gmail_client_secret,
        "DOTMD_GMAIL_REFRESH_TOKEN": settings.gmail_refresh_token,
    }
    gmail_set = {key for key, value in gmail_vars.items() if value}
    gmail_missing = {key for key, value in gmail_vars.items() if not value}
    if len(gmail_set) == 3:
        records.append(
            SourceConfigRecord(
                namespace="gmail",
                config=GmailSourceConfig(
                    client_id=cast(str, settings.gmail_client_id),
                    client_secret=cast(str, settings.gmail_client_secret),
                    refresh_token=cast(str, settings.gmail_refresh_token),
                    search_result_limit=settings.gmail_search_result_limit,
                ),
                credential_ref=SourceCredentialRef(namespace="gmail"),
            )
        )
    elif gmail_set:
        logger.warning(
            "Gmail source not registered: partial configuration detected. "
            "Missing env vars: %s. Set all three to enable Gmail.",
            ", ".join(sorted(gmail_missing)),
        )

    return SourceRuntimeFactory(
        registry=default_source_registry(),
        config_store=InMemorySourceConfigStore(records),
        credential_provider=DefaultSourceCredentialProvider(),
        cursor_store=SQLiteSourceCursorStore(metadata_store),
    )
