"""Tests for source descriptor registry contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dotmd.core.models import (
    SOURCE_SCHEMA_FIELD_TYPES,
    SourceAuthSchema,
    SourceCapability,
    SourceConfigSchema,
    SourceCursorSchema,
    SourceDescriptor,
    SourceDisplayMetadata,
    SourceSchemaField,
)
from dotmd.core.source_registry import SourceRegistry


def _descriptor(namespace: str = "demo") -> SourceDescriptor:
    return SourceDescriptor(
        namespace=namespace,
        source_kind="fixture",
        display=SourceDisplayMetadata(
            display_name="Demo Source",
            description="Demo source descriptor",
            labels=["demo"],
        ),
        config_schema=SourceConfigSchema(
            name="DemoConfig",
            fields=[
                SourceSchemaField(
                    name="path",
                    field_type="path",
                    required=True,
                    description="Source path",
                )
            ],
        ),
        auth_schema=SourceAuthSchema(auth_kind="none"),
        cursor_schema=SourceCursorSchema(
            cursor_kind="none",
            examples=["demo:v1"],
            description="No cursor state",
        ),
        capabilities=[SourceCapability.LOCAL_SYNC],
        metadata_json={"owner": "dotmd"},
    )


def test_source_capability_is_closed_enum() -> None:
    assert [capability.value for capability in SourceCapability] == [
        "local_sync",
        "federated_search",
        "read_unit_window",
        "materialization",
        "browse_tree",
        "acl",
        "incremental_cursor",
    ]


def test_source_descriptor_requires_structural_schemas() -> None:
    descriptor = _descriptor()

    assert descriptor.display.display_name == "Demo Source"
    assert descriptor.config_schema.fields[0].field_type == "path"
    assert descriptor.auth_schema.auth_kind == "none"
    assert descriptor.cursor_schema.examples == ["demo:v1"]
    assert descriptor.capabilities == [SourceCapability.LOCAL_SYNC]


def test_source_descriptor_rejects_unknown_capability() -> None:
    payload = _descriptor().model_dump()
    payload["capabilities"] = ["made_up"]

    with pytest.raises(ValidationError):
        SourceDescriptor(**payload)


def test_source_descriptor_forbids_extra_fields() -> None:
    payload = _descriptor().model_dump()
    payload["organization_id"] = "airweave-only"

    with pytest.raises(ValidationError):
        SourceDescriptor(**payload)


def test_source_schema_field_type_vocabulary_is_documented() -> None:
    assert SOURCE_SCHEMA_FIELD_TYPES == frozenset(
        {"str", "int", "bool", "path", "list[str]", "dict[str, Any]"}
    )

    with pytest.raises(ValidationError):
        SourceSchemaField(name="bad", field_type="json")


def test_descriptor_collection_defaults_are_not_mutable() -> None:
    first = SourceDescriptor(
        namespace="first",
        source_kind="fixture",
        display=SourceDisplayMetadata(
            display_name="First",
            description="First descriptor",
        ),
        config_schema=SourceConfigSchema(name="FirstConfig"),
        auth_schema=SourceAuthSchema(auth_kind="none"),
        cursor_schema=SourceCursorSchema(cursor_kind="none"),
        capabilities=[],
    )
    second = SourceDescriptor(
        namespace="second",
        source_kind="fixture",
        display=SourceDisplayMetadata(
            display_name="Second",
            description="Second descriptor",
        ),
        config_schema=SourceConfigSchema(name="SecondConfig"),
        auth_schema=SourceAuthSchema(auth_kind="none"),
        cursor_schema=SourceCursorSchema(cursor_kind="none"),
        capabilities=[],
    )

    first.display.labels.append("changed")
    first.config_schema.fields.append(SourceSchemaField(name="flag", field_type="bool"))
    first.cursor_schema.examples.append("cursor")
    first.metadata_json["changed"] = True

    assert second.display.labels == []
    assert second.config_schema.fields == []
    assert second.cursor_schema.examples == []
    assert second.metadata_json == {}


def test_source_registry_rejects_duplicate_namespace() -> None:
    registry = SourceRegistry()
    registry.register(_descriptor("demo"))

    with pytest.raises(ValueError, match="source namespace already registered: demo"):
        registry.register(_descriptor("demo"))

