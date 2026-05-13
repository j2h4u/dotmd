"""Minimal Airweave entity base classes vendored for connector compatibility."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

SparseEmbedding = Any  # vendored stub


def AirweaveField(
    default: object = ...,
    *,
    is_entity_id: bool = False,
    is_name: bool = False,
    is_created_at: bool = False,
    is_updated_at: bool = False,
    embeddable: bool | None = None,
    unhashable: bool | None = None,
    **kwargs: object,
) -> Any:
    """Pydantic Field wrapper preserving Airweave metadata in json_schema_extra."""
    extras = kwargs.pop("json_schema_extra", None)
    if not isinstance(extras, dict):
        extras = {}
    extras.update(
        {
            "is_entity_id": is_entity_id,
            "is_name": is_name,
            "is_created_at": is_created_at,
            "is_updated_at": is_updated_at,
        }
    )
    if embeddable is not None:
        extras["embeddable"] = embeddable
    if unhashable is not None:
        extras["unhashable"] = unhashable
    return Field(default, json_schema_extra=extras, **kwargs)


class AirweaveFieldFlag(str, Enum):
    """Vendored field flags used by AirweaveField json_schema_extra."""

    IS_ENTITY_ID = "is_entity_id"
    IS_NAME = "is_name"
    IS_CREATED_AT = "is_created_at"
    IS_UPDATED_AT = "is_updated_at"


class Breadcrumb(BaseModel):
    """Breadcrumb for tracking source entity ancestry."""

    entity_id: str = Field(..., description="ID of the entity in the source.")
    name: str = Field(..., description="Display name of the entity.")
    entity_type: str = Field(..., description="Entity class name.")


class AccessControl(BaseModel):
    """Access-control metadata retained for schema compatibility only."""

    viewers: list[str] = Field(
        default_factory=list,
        description="Principal IDs who can view this entity.",
    )
    is_public: bool = Field(
        default=False,
        description="Whether this entity is publicly accessible.",
    )


class AirweaveSystemMetadata(BaseModel):
    """Airweave system metadata retained for compatibility analysis."""

    source_name: str | None = Field(None, description="Source name.")
    entity_type: str | None = Field(None, description="Entity type.")
    sync_id: UUID | None = Field(None, description="Sync ID.")
    sync_job_id: UUID | None = Field(None, description="Sync job ID.")
    hash: str | None = Field(None, description="Content hash.")
    chunk_index: int | None = Field(None, description="Chunk index.")
    original_entity_id: str | None = Field(None, description="Original entity ID before chunking.")
    dense_embedding: list[float] | None = Field(None, description="Dense embedding.")
    sparse_embedding: Any | None = Field(None, description="Sparse embedding stub.")
    db_entity_id: UUID | None = Field(None, description="Database entity ID.")
    db_created_at: datetime | None = Field(None, description="Database creation time.")
    db_updated_at: datetime | None = Field(None, description="Database update time.")


class BaseEntity(BaseModel):
    """Base entity schema."""

    entity_id: str | None = Field(None, description="ID of the entity in the source.")
    breadcrumbs: list[Breadcrumb] | None = Field(None, description="Breadcrumb chain.")
    name: str | None = Field(None, description="Entity display name.")
    created_at: datetime | None = Field(None, description="Creation time.")
    updated_at: datetime | None = Field(None, description="Last update time.")
    textual_representation: str | None = Field(None, description="Text used for embedding.")
    airweave_system_metadata: AirweaveSystemMetadata | None = Field(
        None,
        description="Airweave system metadata.",
    )
    access: AccessControl | None = Field(None, description="Access-control metadata.")

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="ignore")

    @model_validator(mode="after")
    def validate_flagged_fields(self) -> BaseEntity:
        """Populate common fields from AirweaveField flags without importing Airweave core."""
        flagged: dict[AirweaveFieldFlag, list[str]] = {
            AirweaveFieldFlag.IS_ENTITY_ID: [],
            AirweaveFieldFlag.IS_NAME: [],
            AirweaveFieldFlag.IS_CREATED_AT: [],
            AirweaveFieldFlag.IS_UPDATED_AT: [],
        }
        for field_name, field_info in self.__class__.model_fields.items():
            extras = field_info.json_schema_extra
            if not isinstance(extras, dict):
                continue
            for flag in flagged:
                if extras.get(flag.value):
                    flagged[flag].append(field_name)

        for flag, target_attr in (
            (AirweaveFieldFlag.IS_ENTITY_ID, "entity_id"),
            (AirweaveFieldFlag.IS_NAME, "name"),
            (AirweaveFieldFlag.IS_CREATED_AT, "created_at"),
            (AirweaveFieldFlag.IS_UPDATED_AT, "updated_at"),
        ):
            names = flagged[flag]
            if names:
                setattr(self, target_attr, getattr(self, names[0], None))

        if self.breadcrumbs is None:
            self.breadcrumbs = []
        return self


class FileEntity(BaseEntity):
    """File entity schema."""

    url: str = Field(..., description="URL to the file.")
    size: int = Field(..., description="Size of the file in bytes.")
    file_type: str = Field(..., description="Type of the file.")
    mime_type: str | None = Field(None, description="MIME type of the file.")
    local_path: str | None = Field(None, description="Local path of the file.")


class EmailEntity(FileEntity):
    """Base entity for email messages."""


class DeletionEntity(BaseEntity):
    """Base entity that supports deletion tracking."""

    deletes_entity_class: ClassVar[type[BaseEntity] | None] = None
    deletion_status: str = Field(
        "removed",
        description="Deletion status.",
    )
