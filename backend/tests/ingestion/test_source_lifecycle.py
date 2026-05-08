"""Tests for source lifecycle runtime bundle construction."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError
import pytest

from dotmd.core.config import Settings
from dotmd.core.models import SourceDescriptor
from dotmd.ingestion.source import FilesystemMarkdownSourceAdapter
from dotmd.ingestion.source_lifecycle import (
    DefaultSourceCredentialProvider,
    FilesystemSourceConfig,
    InMemorySourceConfigStore,
    SQLiteSourceCursorStore,
    SourceAccess,
    SourceConfigRecord,
    SourceCredentialProviderProtocol,
    SourceCredentialRef,
    SourceCursorStoreProtocol,
    SourceLifecycleConfigError,
    SourceRuntimeFactory,
    TelegramSourceConfig,
)
import dotmd.ingestion.source_lifecycle as source_lifecycle
from dotmd.ingestion.source_registry import default_source_registry
from dotmd.ingestion.telegram_provider import (
    TelegramApplicationSourceProvider,
)
from dotmd.storage.metadata import SQLiteMetadataStore


class RecordingCredentialProvider:
    """Credential provider fixture that records descriptor namespaces."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, SourceCredentialRef]] = []

    def get_access(
        self,
        descriptor: SourceDescriptor,
        credential_ref: SourceCredentialRef,
    ) -> SourceAccess:
        self.calls.append((descriptor.namespace, credential_ref))
        return SourceAccess(kind="delegated", delegated_to="mcp-telegram")


class FakeTelegramClient:
    """Minimal Telegram source client fixture."""

    def __init__(self, socket_path: Path) -> None:
        self.socket_path = socket_path

    def describe_source(self) -> dict[str, Any]:
        return {
            "namespace": "telegram",
            "source_kind": "chat",
            "display_name": "Telegram",
            "capabilities": [],
        }

    def export_source_changes(
        self,
        cursor: str | None,
        limit: int,
        updated_after: str | None = None,
        updated_after_cursor: str | None = None,
    ) -> dict[str, Any]:
        _ = (cursor, limit, updated_after, updated_after_cursor)
        return {"changes": [], "checkpoint_cursor": None}

    def read_source_unit_window(
        self,
        unit_ref: str,
        before: int,
        after: int,
    ) -> dict[str, Any]:
        _ = (unit_ref, before, after)
        return {
            "namespace": "telegram",
            "document_ref": "dialog:1",
            "unit_ref": "dialog:1:message:1",
            "units": [],
        }


def _metadata_store(tmp_path: Path) -> SQLiteMetadataStore:
    return SQLiteMetadataStore(
        db_path=tmp_path / "metadata.db",
        table_name="chunks_heading_512_50",
    )


def test_filesystem_runtime_bundle_contains_descriptor_config_access_and_source(
    tmp_path: Path,
) -> None:
    config_store = InMemorySourceConfigStore(
        [
            SourceConfigRecord(
                namespace="filesystem",
                config=FilesystemSourceConfig(
                    paths=[str(tmp_path)],
                    exclude=[".git"],
                ),
            )
        ]
    )
    cursor_store = SQLiteSourceCursorStore(_metadata_store(tmp_path))
    factory = SourceRuntimeFactory(
        registry=default_source_registry(),
        config_store=config_store,
        credential_provider=DefaultSourceCredentialProvider(),
        cursor_store=cursor_store,
    )

    bundle = factory.build("filesystem")

    assert bundle.descriptor.namespace == "filesystem"
    assert isinstance(bundle.config, FilesystemSourceConfig)
    assert bundle.config.paths == [str(tmp_path)]
    assert bundle.access.kind == "none"
    assert isinstance(bundle.source, FilesystemMarkdownSourceAdapter)
    assert bundle.provider is None
    assert bundle.cursor_store is cursor_store


def test_telegram_runtime_bundle_uses_delegated_access_and_provider(
    tmp_path: Path,
) -> None:
    socket_path = tmp_path / "daemon.sock"
    credential_provider = RecordingCredentialProvider()
    config_store = InMemorySourceConfigStore(
        [
            SourceConfigRecord(
                namespace="telegram",
                config=TelegramSourceConfig(socket_path=socket_path),
            )
        ]
    )
    factory = SourceRuntimeFactory(
        registry=default_source_registry(),
        config_store=config_store,
        credential_provider=credential_provider,
        cursor_store=SQLiteSourceCursorStore(_metadata_store(tmp_path)),
        telegram_client_factory=FakeTelegramClient,
    )

    bundle = factory.build("telegram")

    assert credential_provider.calls == [
        ("telegram", SourceCredentialRef(namespace="telegram"))
    ]
    assert bundle.access.kind == "delegated"
    assert bundle.access.delegated_to == "mcp-telegram"
    assert isinstance(bundle.provider, TelegramApplicationSourceProvider)
    assert bundle.source is None


def test_build_fails_fast_when_required_filesystem_paths_missing(
    tmp_path: Path,
) -> None:
    factory = SourceRuntimeFactory(
        registry=default_source_registry(),
        config_store=InMemorySourceConfigStore(),
        credential_provider=DefaultSourceCredentialProvider(),
        cursor_store=SQLiteSourceCursorStore(_metadata_store(tmp_path)),
    )

    with pytest.raises(SourceLifecycleConfigError, match="filesystem.paths"):
        factory.build("filesystem")


def test_build_fails_fast_when_telegram_socket_missing(tmp_path: Path) -> None:
    factory = SourceRuntimeFactory(
        registry=default_source_registry(),
        config_store=InMemorySourceConfigStore(
            [
                SourceConfigRecord(
                    namespace="telegram",
                    config=TelegramSourceConfig(),
                )
            ]
        ),
        credential_provider=DefaultSourceCredentialProvider(),
        cursor_store=SQLiteSourceCursorStore(_metadata_store(tmp_path)),
    )

    with pytest.raises(SourceLifecycleConfigError, match="telegram.socket_path"):
        factory.build("telegram")


def test_build_if_configured_returns_none_for_optional_telegram_without_socket(
    tmp_path: Path,
) -> None:
    factory = SourceRuntimeFactory(
        registry=default_source_registry(),
        config_store=InMemorySourceConfigStore(),
        credential_provider=DefaultSourceCredentialProvider(),
        cursor_store=SQLiteSourceCursorStore(_metadata_store(tmp_path)),
    )

    assert factory.build_if_configured("telegram") is None


def test_source_config_store_keeps_credential_refs_separate_from_config() -> None:
    record = SourceConfigRecord(
        namespace="telegram",
        config=TelegramSourceConfig(socket_path=Path("/tmp/telegram.sock")),
        credential_ref=SourceCredentialRef(
            namespace="telegram",
            credential_ref="delegated:mcp-telegram",
        ),
    )
    config_store = InMemorySourceConfigStore([record])

    stored = config_store.get_config("telegram")

    assert stored is not None
    assert stored.credential_ref == SourceCredentialRef(
        namespace="telegram",
        credential_ref="delegated:mcp-telegram",
    )
    payload = stored.config.model_dump()
    assert "credential_ref" not in payload
    assert not {"secret", "token", "password"} & set(payload)


def test_source_runtime_factory_from_settings_seeds_telegram_config_when_socket_configured(
    tmp_path: Path,
) -> None:
    socket_path = tmp_path / "daemon.sock"
    settings = Settings(
        data_dir=tmp_path / "data",
        index_dir=tmp_path / "index",
        embedding_url="http://localhost:18088",
        telegram_daemon_socket=socket_path,
    )
    metadata_store = _metadata_store(tmp_path)

    factory = source_lifecycle.source_runtime_factory_from_settings(
        settings,
        metadata_store,
    )

    record = factory._config_store.get_config("telegram")
    assert record is not None
    assert record.config == TelegramSourceConfig(socket_path=socket_path)
    assert record.credential_ref == SourceCredentialRef(
        namespace="telegram",
        credential_ref="mcp-telegram",
    )


def test_telegram_lifecycle_does_not_accept_raw_secret_fields() -> None:
    with pytest.raises(ValidationError):
        TelegramSourceConfig.model_validate(
            {
                "socket_path": Path("/tmp/telegram.sock"),
                "token": "raw-token",
            }
        )
    with pytest.raises(ValidationError):
        SourceCredentialRef.model_validate(
            {
                "namespace": "telegram",
                "password": "raw-password",
            }
        )
    with pytest.raises(ValidationError):
        SourceAccess.model_validate(
            {
                "kind": "delegated",
                "delegated_to": "mcp-telegram",
                "secret": "raw-secret",
            }
        )


def test_telegram_access_remains_delegated_to_mcp_telegram(tmp_path: Path) -> None:
    socket_path = tmp_path / "daemon.sock"
    factory = SourceRuntimeFactory(
        registry=default_source_registry(),
        config_store=InMemorySourceConfigStore(
            [
                SourceConfigRecord(
                    namespace="telegram",
                    config=TelegramSourceConfig(socket_path=socket_path),
                    credential_ref=SourceCredentialRef(
                        namespace="telegram",
                        credential_ref="mcp-telegram",
                    ),
                )
            ]
        ),
        credential_provider=DefaultSourceCredentialProvider(),
        cursor_store=SQLiteSourceCursorStore(_metadata_store(tmp_path)),
        telegram_client_factory=FakeTelegramClient,
    )

    bundle = factory.build("telegram")

    assert bundle.access.kind == "delegated"
    assert bundle.access.delegated_to == "mcp-telegram"
    assert bundle.config.model_dump() == {"socket_path": socket_path}


def test_source_cursor_store_requires_transaction_for_commit(tmp_path: Path) -> None:
    metadata_store = _metadata_store(tmp_path)
    cursor_store: SourceCursorStoreProtocol = SQLiteSourceCursorStore(metadata_store)

    with pytest.raises(TypeError):
        cursor_store.commit_checkpoint("telegram", "checkpoint:1")  # type: ignore[reportCallIssue]

    conn = metadata_store._conn
    conn.execute("BEGIN")
    cursor_store.commit_checkpoint(
        "telegram",
        "checkpoint:1",
        conn=conn,
        metadata_json={"batch": 1},
    )
    conn.rollback()

    assert cursor_store.get_checkpoint("telegram") is None


def test_default_credential_provider_matches_protocol() -> None:
    provider: SourceCredentialProviderProtocol = DefaultSourceCredentialProvider()
    descriptor = default_source_registry().require("filesystem")

    access = provider.get_access(
        descriptor,
        SourceCredentialRef(namespace="filesystem"),
    )

    assert access.kind == "none"


def test_source_runtime_factory_from_settings_seeds_filesystem_config(
    tmp_path: Path,
) -> None:
    from dotmd.core.config import Settings

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    settings = Settings(
        data_dir=data_dir,
        index_dir=index_dir,
        embedding_url="http://localhost:18088",
        indexing_paths=[str(data_dir)],
        indexing_extra_exclude=["ignored"],
    )

    factory = source_lifecycle.source_runtime_factory_from_settings(
        settings,
        _metadata_store(tmp_path),
    )
    bundle = factory.build("filesystem")

    assert isinstance(bundle.config, FilesystemSourceConfig)
    assert bundle.config.paths == [str(data_dir)]
    assert "ignored" in bundle.config.exclude
    assert bundle.provider is None
    assert bundle.cursor_store.get_checkpoint("filesystem") is None
