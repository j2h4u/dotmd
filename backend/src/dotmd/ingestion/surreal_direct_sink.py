"""Direct in-memory Surreal delta manifest builder for filesystem slices."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from dotmd.core.models import (
    ApplicationSourceChange,
    Chunk,
    DocKind,
    Entity,
    EntityType,
    FileInfo,
    Relation,
    RelationType,
    SourceDocument,
    SourceUnit,
)
from dotmd.ingestion.surreal_delta_sync import (
    SurrealDeltaChange,
    SurrealDeltaCheckpointCandidate,
    SurrealDeltaManifest,
    SurrealDeltaSection,
    SurrealDeltaSourceSelection,
    _stable_vector_rowid,
    build_surreal_delta_manifest,
)


@dataclass(frozen=True, slots=True)
class SurrealDirectFileWrite:
    """In-memory filesystem slice used to build a Surreal delta manifest."""

    source_document: SourceDocument
    chunks: Sequence[Chunk]
    embeddings: Sequence[Sequence[float]]
    text_hashes: Mapping[str, str]
    chunk_strategy: str
    embedding_model: str


@dataclass(frozen=True, slots=True)
class SurrealApplicationSourceWrite:
    """In-memory application-source slice used to build a Surreal delta manifest."""

    changes: Sequence[ApplicationSourceChange]
    indexed_changes: Sequence[ApplicationSourceChange]
    chunks: Sequence[Chunk]
    e_text_vectors: Sequence[Sequence[float]]
    e_meta_by_source_key: Mapping[tuple[str, str], Sequence[float]]
    e_fused_vectors: Sequence[Sequence[float]]
    text_hashes: Mapping[str, str]
    chunk_strategy: str
    embedding_model: str


class _GraphExtractionLike(Protocol):
    entities: list[Entity]
    relations: list[Relation]


def _stable_composite_ref(*parts: object) -> str:
    return "\x1f".join(str(part) for part in parts)


def _chunk_title(chunk: Chunk, source_document: SourceDocument) -> str:
    return chunk.heading or source_document.title


def _chunk_tags_text(source_document: SourceDocument) -> str:
    tags = source_document.metadata_json.get("tags_text")
    if isinstance(tags, str):
        return tags
    tags_list = source_document.metadata_json.get("tags")
    if isinstance(tags_list, list):
        return " ".join(str(tag) for tag in tags_list if str(tag))
    return ""


def _chunk_file_paths(chunk: Chunk, source_document: SourceDocument) -> list[str]:
    if chunk.file_paths:
        return [str(path) for path in chunk.file_paths]
    if source_document.file_path is not None:
        return [str(source_document.file_path)]
    return []


def _document_change(source_document: SourceDocument) -> SurrealDeltaChange:
    return SurrealDeltaChange(
        ref=source_document.ref,
        table="source_documents",
        row={
            "namespace": source_document.namespace,
            "document_ref": source_document.document_ref,
            "ref": source_document.ref,
            "title": source_document.title,
            "media_type": source_document.media_type,
            "metadata": dict(source_document.metadata_json),
        },
    )


def _source_unit_change(source_unit: SourceUnit) -> SurrealDeltaChange:
    ref = _stable_composite_ref(
        source_unit.namespace,
        source_unit.document_ref,
        source_unit.unit_ref,
    )
    return SurrealDeltaChange(
        ref=ref,
        table="source_units",
        row={
            "namespace": source_unit.namespace,
            "document_ref": source_unit.document_ref,
            "unit_ref": source_unit.unit_ref,
            "ref": ref,
            "unit_type": source_unit.unit_type,
            "text": source_unit.text,
            "order_key": source_unit.order_key,
            "fingerprint": source_unit.fingerprint,
            "updated_at": source_unit.updated_at,
            "metadata": dict(source_unit.metadata_json),
            "chunking_hints": dict(source_unit.chunking_hints),
        },
    )


def _chunk_change(
    *,
    source_document: SourceDocument,
    chunk: Chunk,
    chunk_strategy: str,
) -> SurrealDeltaChange:
    provenance_ref = (
        chunk.provenance.ref
        if chunk.provenance is not None and chunk.provenance.ref
        else chunk.chunk_id
    )
    source_unit_refs = (
        list(chunk.provenance.source_unit_refs) if chunk.provenance is not None else []
    )
    return SurrealDeltaChange(
        ref=chunk.chunk_id,
        table="chunks",
        row={
            "chunk_id": chunk.chunk_id,
            "original_chunk_id": chunk.chunk_id,
            "chunk_strategy": chunk_strategy,
            "heading_hierarchy": list(chunk.heading_hierarchy),
            "level": chunk.level,
            "document_ref": source_document.document_ref,
            "ref": provenance_ref,
            "title": _chunk_title(chunk, source_document),
            "tags_text": _chunk_tags_text(source_document),
            "text": chunk.text,
            "file_paths": _chunk_file_paths(chunk, source_document),
            "file_bindings": [],
            "source_unit_refs": source_unit_refs,
            "metadata": {},
        },
    )


def _application_chunk_change(
    *,
    source_document: SourceDocument,
    chunk: Chunk,
    chunk_strategy: str,
) -> SurrealDeltaChange:
    provenance_ref = (
        chunk.provenance.ref
        if chunk.provenance is not None and chunk.provenance.ref
        else chunk.chunk_id
    )
    source_unit_refs = (
        list(chunk.provenance.source_unit_refs) if chunk.provenance is not None else []
    )
    return SurrealDeltaChange(
        ref=provenance_ref,
        table="chunks",
        row={
            "chunk_id": chunk.chunk_id,
            "original_chunk_id": chunk.chunk_id,
            "chunk_strategy": chunk_strategy,
            "heading_hierarchy": list(chunk.heading_hierarchy),
            "level": chunk.level,
            "document_ref": source_document.document_ref,
            "ref": provenance_ref,
            "title": _chunk_title(chunk, source_document),
            "tags_text": _chunk_tags_text(source_document),
            "text": chunk.text,
            "file_paths": _chunk_file_paths(chunk, source_document),
            "file_bindings": [],
            "source_unit_refs": source_unit_refs,
            "metadata": {},
        },
    )


def _application_provenance_change(
    *,
    source_document: SourceDocument,
    chunk: Chunk,
    chunk_strategy: str,
) -> SurrealDeltaChange:
    provenance = chunk.provenance
    namespace = provenance.namespace if provenance is not None else source_document.namespace
    source_unit_refs = list(provenance.source_unit_refs) if provenance is not None else []
    parser_name = provenance.parser_name if provenance is not None else source_document.parser_name
    provenance_id = _stable_composite_ref(chunk.chunk_id, namespace, source_document.document_ref)
    return SurrealDeltaChange(
        ref=provenance_id,
        table="provenance",
        row={
            "chunk_id": chunk.chunk_id,
            "provenance_id": provenance_id,
            "namespace": namespace,
            "document_ref": source_document.document_ref,
            "chunk_strategy": provenance.chunk_strategy
            if provenance is not None
            else chunk_strategy,
            "source_unit_refs": source_unit_refs,
            "parser_name": parser_name,
            "metadata": {},
        },
    )


def _chunk_file_binding_changes(
    *,
    source_document: SourceDocument,
    chunk: Chunk,
) -> list[SurrealDeltaChange]:
    file_paths = [str(path) for path in chunk.file_paths]
    if not file_paths and source_document.file_path is not None:
        file_paths = [str(source_document.file_path)]
    if not file_paths and source_document.namespace == "filesystem":
        file_paths = [source_document.document_ref]

    rows: list[SurrealDeltaChange] = []
    for file_path in file_paths:
        binding_id = _stable_composite_ref(chunk.chunk_id, file_path, chunk.chunk_index)
        rows.append(
            SurrealDeltaChange(
                ref=binding_id,
                table="chunk_file_bindings",
                row={
                    "binding_id": binding_id,
                    "chunk_id": chunk.chunk_id,
                    "file_path": file_path,
                    "chunk_index": chunk.chunk_index,
                    "metadata": {},
                },
            )
        )
    return rows


def _provenance_change(
    *,
    source_document: SourceDocument,
    chunk: Chunk,
    chunk_strategy: str,
) -> SurrealDeltaChange:
    provenance = chunk.provenance
    namespace = provenance.namespace if provenance is not None else source_document.namespace
    source_unit_refs = list(provenance.source_unit_refs) if provenance is not None else []
    parser_name = provenance.parser_name if provenance is not None else source_document.parser_name
    provenance_id = _stable_composite_ref(chunk.chunk_id, namespace, source_document.document_ref)
    return SurrealDeltaChange(
        ref=provenance_id,
        table="provenance",
        row={
            "chunk_id": chunk.chunk_id,
            "provenance_id": provenance_id,
            "namespace": namespace,
            "document_ref": source_document.document_ref,
            "chunk_strategy": provenance.chunk_strategy
            if provenance is not None
            else chunk_strategy,
            "source_unit_refs": source_unit_refs,
            "parser_name": parser_name,
            "metadata": {},
        },
    )


def _resource_binding_change(source_document: SourceDocument) -> SurrealDeltaChange:
    binding_ref = _stable_composite_ref(source_document.namespace, source_document.document_ref)
    return SurrealDeltaChange(
        ref=binding_ref,
        table="bindings",
        row={
            "namespace": source_document.namespace,
            "resource_ref": source_document.document_ref,
            "document_ref": source_document.document_ref,
            "ref": source_document.ref,
            "active": True,
            "bound_at": source_document.updated_at,
            "unbound_at": None,
            "content_fingerprint": source_document.content_fingerprint,
            "metadata_fingerprint": source_document.metadata_fingerprint,
            "source_unit_refs": [],
            "metadata": dict(source_document.metadata_json),
        },
    )


def _vector_component_change(
    *,
    owner_id: str,
    component: str,
    embedding: Sequence[float],
    chunk_strategy: str,
    embedding_model: str,
    metadata: Mapping[str, object] | None = None,
) -> SurrealDeltaChange:
    component_ref = _stable_composite_ref(chunk_strategy, embedding_model, owner_id, component)
    return SurrealDeltaChange(
        ref=component_ref,
        table="vector_components",
        row={
            "chunk_strategy": chunk_strategy,
            "embedding_model": embedding_model,
            "chunk_id": owner_id,
            "component": component,
            "embedding": list(embedding),
            "metadata": dict(metadata or {}),
        },
    )


def _embedding_change(
    *,
    chunk: Chunk,
    embedding: Sequence[float],
    chunk_strategy: str,
    embedding_model: str,
    text_hashes: Mapping[str, str],
) -> SurrealDeltaChange:
    text_hash = text_hashes.get(chunk.chunk_id)
    if text_hash is None:
        raise ValueError(f"missing text hash for chunk_id={chunk.chunk_id!r}")
    embedding_id = _stable_composite_ref(chunk_strategy, embedding_model, chunk.chunk_id)
    return SurrealDeltaChange(
        ref=embedding_id,
        table="embeddings",
        row={
            "chunk_strategy": chunk_strategy,
            "embedding_model": embedding_model,
            "chunk_id": chunk.chunk_id,
            "text_hash": text_hash,
            "vector_rowid": _stable_vector_rowid(chunk_strategy, embedding_model, chunk.chunk_id),
            "vector": list(embedding),
            "metadata": {},
        },
    )


def _graph_file_change(file_info: FileInfo) -> SurrealDeltaChange:
    file_path = str(file_info.path)
    return SurrealDeltaChange(
        ref=file_path,
        table="files",
        row={
            "path": file_path,
            "file_path": file_path,
            "title": file_info.title,
            "metadata": {},
        },
    )


def _graph_section_change(chunk: Chunk, *, file_path: str) -> SurrealDeltaChange:
    return SurrealDeltaChange(
        ref=chunk.chunk_id,
        table="sections",
        row={
            "chunk_id": chunk.chunk_id,
            "document_ref": file_path,
            "file_path": file_path,
            "heading": chunk.heading,
            "level": chunk.level,
            "text_preview": chunk.text[:200],
            "metadata": {},
        },
    )


def _graph_entity_change(name: str, *, entity_type: str, source: str) -> SurrealDeltaChange:
    return SurrealDeltaChange(
        ref=name,
        table="entities",
        row={
            "name": name,
            "entity_type": entity_type,
            "source": source,
            "metadata": {},
        },
    )


def _graph_tag_change(name: str) -> SurrealDeltaChange:
    return SurrealDeltaChange(
        ref=name,
        table="tags",
        row={
            "name": name,
            "metadata": {},
        },
    )


def _graph_relation_change(
    *,
    source_id: str,
    source_table: str,
    target_id: str,
    target_table: str,
    relation_type: str,
    weight: float = 1.0,
    properties: Mapping[str, object] | None = None,
) -> SurrealDeltaChange:
    relation_id = _stable_composite_ref(source_id, target_id, relation_type)
    return SurrealDeltaChange(
        ref=relation_id,
        table="relations",
        row={
            "relation_id": relation_id,
            "rel_type": relation_type,
            "relation_type": relation_type,
            "weight": weight,
            "source_id": source_id,
            "target_id": target_id,
            "source_table": source_table,
            "target_table": target_table,
            "properties": dict(properties or {}),
            "metadata": {},
        },
    )


def _frontmatter_tag_targets(tag_value: object) -> tuple[str, str]:
    tag_str = str(tag_value).strip()
    parts = tag_str.split(":", 1)
    if len(parts) == 2 and parts[0].strip():
        return parts[1].strip(), parts[0].strip().upper()
    return tag_str, ""


def _graph_row_sort_key(change: SurrealDeltaChange) -> tuple[int, str]:
    order = {"files": 0, "sections": 1, "entities": 2, "tags": 3, "relations": 4}
    return order.get(change.table, 99), change.ref


def build_surreal_graph_rows(
    files: Sequence[FileInfo],
    chunks: Sequence[Chunk],
    extraction: _GraphExtractionLike | None = None,
) -> list[SurrealDeltaChange]:
    """Build direct graph rows from in-memory file, chunk, and extraction state."""

    rows: dict[tuple[str, str], SurrealDeltaChange] = {}
    file_paths = {str(file_info.path) for file_info in files}
    chunk_ids = {chunk.chunk_id for chunk in chunks}
    entity_names: set[str] = set()
    tag_names: set[str] = set()

    def add(change: SurrealDeltaChange) -> None:
        rows.setdefault((change.table, change.ref), change)

    for file_info in files:
        add(_graph_file_change(file_info))

    for chunk in chunks:
        file_path = (
            str(chunk.file_paths[0])
            if chunk.file_paths
            else (sorted(file_paths)[0] if file_paths else "")
        )
        add(_graph_section_change(chunk, file_path=file_path))
        if file_path:
            add(
                _graph_relation_change(
                    source_id=file_path,
                    source_table="files",
                    target_id=chunk.chunk_id,
                    target_table="sections",
                    relation_type=str(RelationType.CONTAINS),
                )
            )

    if extraction is not None:
        for entity in extraction.entities:
            if entity.type.lower() == EntityType.TAG.value.lower():
                tag_names.add(entity.name)
                add(_graph_tag_change(entity.name))
            else:
                entity_names.add(entity.name)
                add(
                    _graph_entity_change(
                        entity.name,
                        entity_type=entity.type,
                        source=str(entity.source),
                    )
                )

    for file_info in files:
        file_path = str(file_info.path)
        frontmatter = file_info.frontmatter or {}
        tags = frontmatter.get("tags", [])
        for tag_value in tags if isinstance(tags, list) else []:
            tag_name, entity_type = _frontmatter_tag_targets(tag_value)
            if not tag_name:
                continue
            if entity_type:
                entity_names.add(tag_name)
                add(
                    _graph_entity_change(
                        tag_name,
                        entity_type=entity_type,
                        source="frontmatter",
                    )
                )
                target_table = "entities"
            else:
                tag_names.add(tag_name)
                add(_graph_tag_change(tag_name))
                target_table = "tags"
            add(
                _graph_relation_change(
                    source_id=file_path,
                    source_table="files",
                    target_id=tag_name,
                    target_table=target_table,
                    relation_type=str(RelationType.HAS_TAG),
                )
            )

        if str(file_info.kind) == DocKind.MEETING_TRANSCRIPT.value:
            participants = frontmatter.get("participants", [])
            for participant in participants if isinstance(participants, list) else []:
                participant_name = str(participant).strip()
                if not participant_name:
                    continue
                entity_names.add(participant_name)
                add(
                    _graph_entity_change(
                        participant_name,
                        entity_type=EntityType.PERSON.value,
                        source="frontmatter",
                    )
                )
                add(
                    _graph_relation_change(
                        source_id=file_path,
                        source_table="files",
                        target_id=participant_name,
                        target_table="entities",
                        relation_type="HAS_PARTICIPANT",
                    )
                )

    if extraction is not None:
        for relation in extraction.relations:
            relation_type = str(relation.relation_type)

            if relation.source_id in file_paths:
                source_table = "files"
            elif relation.source_id in chunk_ids:
                source_table = "sections"
            elif relation.source_id in tag_names:
                source_table = "tags"
            elif relation.source_id in entity_names:
                source_table = "entities"
            else:
                source_table = "entities"

            if relation.target_id in file_paths:
                target_table = "files"
            elif relation.target_id in chunk_ids:
                target_table = "sections"
            elif relation.target_id in tag_names:
                target_table = "tags"
            elif relation.target_id in entity_names:
                target_table = "entities"
            else:
                target_table = "entities"

            add(
                _graph_relation_change(
                    source_id=relation.source_id,
                    source_table=source_table,
                    target_id=relation.target_id,
                    target_table=target_table,
                    relation_type=relation_type,
                    weight=relation.weight,
                    properties=relation.properties,
                )
            )

    return sorted(rows.values(), key=_graph_row_sort_key)


def build_surreal_graph_manifest(
    files: Sequence[FileInfo],
    chunks: Sequence[Chunk],
    extraction: _GraphExtractionLike | None,
    *,
    source_selection: SurrealDeltaSourceSelection,
    checkpoint_candidate: SurrealDeltaCheckpointCandidate,
    created_at: datetime | None = None,
) -> SurrealDeltaManifest:
    """Build a direct Surreal delta manifest containing only graph rows."""

    return build_surreal_delta_manifest(
        source_selection=source_selection,
        checkpoint_candidate=checkpoint_candidate,
        graph=SurrealDeltaSection(rows=build_surreal_graph_rows(files, chunks, extraction)),
        created_at=created_at,
    )


def build_surreal_application_source_manifest(
    write: SurrealApplicationSourceWrite,
    *,
    source_selection: SurrealDeltaSourceSelection,
    checkpoint_candidate: SurrealDeltaCheckpointCandidate,
    created_at: datetime | None = None,
) -> SurrealDeltaManifest:
    """Build a direct Surreal delta manifest from application-source state."""

    if len(write.chunks) != len(write.e_text_vectors) or len(write.chunks) != len(
        write.e_fused_vectors
    ):
        raise ValueError("chunks, e_text_vectors, and e_fused_vectors must be aligned")
    if len(write.indexed_changes) != len(write.chunks):
        raise ValueError("indexed_changes and chunks must be aligned")

    documents_by_ref: dict[str, SourceDocument] = {}
    source_units = sorted(
        (_source_unit_change(change.unit) for change in write.changes),
        key=lambda change: change.ref,
    )
    for change in write.changes:
        documents_by_ref.setdefault(change.document.ref, change.document)

    document_changes = [_document_change(documents_by_ref[ref]) for ref in sorted(documents_by_ref)]
    resource_binding_changes = [
        _resource_binding_change(documents_by_ref[ref]) for ref in sorted(documents_by_ref)
    ]

    chunk_changes: list[SurrealDeltaChange] = []
    provenance_changes: list[SurrealDeltaChange] = []
    embedding_changes: list[SurrealDeltaChange] = []
    vector_component_changes: list[SurrealDeltaChange] = []

    for change, chunk, e_text, e_fused in zip(
        write.indexed_changes,
        write.chunks,
        write.e_text_vectors,
        write.e_fused_vectors,
        strict=True,
    ):
        source_document = change.document
        chunk_changes.append(
            _application_chunk_change(
                source_document=source_document,
                chunk=chunk,
                chunk_strategy=write.chunk_strategy,
            )
        )
        provenance_changes.append(
            _application_provenance_change(
                source_document=source_document,
                chunk=chunk,
                chunk_strategy=write.chunk_strategy,
            )
        )
        embedding_changes.append(
            _embedding_change(
                chunk=chunk,
                embedding=e_fused,
                chunk_strategy=write.chunk_strategy,
                embedding_model=write.embedding_model,
                text_hashes=write.text_hashes,
            )
        )
        vector_component_changes.append(
            _vector_component_change(
                owner_id=chunk.chunk_id,
                component="text",
                embedding=e_text,
                chunk_strategy=write.chunk_strategy,
                embedding_model=write.embedding_model,
            )
        )

    for ref in sorted(documents_by_ref):
        source_document = documents_by_ref[ref]
        meta_vector = write.e_meta_by_source_key.get(
            (source_document.namespace, source_document.document_ref)
        )
        if meta_vector is None:
            continue
        vector_component_changes.append(
            _vector_component_change(
                owner_id=source_document.ref,
                component="meta",
                embedding=meta_vector,
                chunk_strategy=write.chunk_strategy,
                embedding_model=write.embedding_model,
                metadata={
                    "namespace": source_document.namespace,
                    "document_ref": source_document.document_ref,
                },
            )
        )

    chunk_changes.sort(key=lambda change: change.ref)
    provenance_changes.sort(key=lambda change: change.ref)
    embedding_changes.sort(key=lambda change: change.ref)
    vector_component_changes.sort(key=lambda change: change.ref)

    return build_surreal_delta_manifest(
        source_selection=source_selection,
        checkpoint_candidate=checkpoint_candidate,
        documents=SurrealDeltaSection(rows=document_changes),
        source_units=SurrealDeltaSection(rows=source_units),
        chunks=SurrealDeltaSection(rows=chunk_changes),
        chunk_file_bindings=SurrealDeltaSection(),
        provenance=SurrealDeltaSection(rows=provenance_changes),
        resource_bindings=SurrealDeltaSection(rows=resource_binding_changes),
        fingerprints=SurrealDeltaSection(),
        embeddings=SurrealDeltaSection(rows=embedding_changes),
        vector_components=SurrealDeltaSection(rows=vector_component_changes),
        graph=SurrealDeltaSection(),
        feedback=SurrealDeltaSection(),
        created_at=created_at,
    )


def build_surreal_direct_manifest(
    write: SurrealDirectFileWrite,
    *,
    source_selection: SurrealDeltaSourceSelection,
    checkpoint_candidate: SurrealDeltaCheckpointCandidate,
    created_at: datetime | None = None,
) -> SurrealDeltaManifest:
    """Build a direct Surreal delta manifest from in-memory indexing objects.

    This first slice is filesystem-only. It intentionally leaves source_units,
    fingerprints, vector_components, graph, and feedback empty/deferred because
    no in-memory source-unit model is wired into this path yet.
    """

    if len(write.chunks) != len(write.embeddings):
        raise ValueError("chunks and embeddings must be aligned")

    document_change = _document_change(write.source_document)
    chunk_changes: list[SurrealDeltaChange] = []
    chunk_file_binding_changes: list[SurrealDeltaChange] = []
    provenance_changes: list[SurrealDeltaChange] = []
    embedding_changes: list[SurrealDeltaChange] = []

    for chunk, embedding in zip(write.chunks, write.embeddings, strict=True):
        chunk_changes.append(
            _chunk_change(
                source_document=write.source_document,
                chunk=chunk,
                chunk_strategy=write.chunk_strategy,
            )
        )
        chunk_file_binding_changes.extend(
            _chunk_file_binding_changes(source_document=write.source_document, chunk=chunk)
        )
        provenance_changes.append(
            _provenance_change(
                source_document=write.source_document,
                chunk=chunk,
                chunk_strategy=write.chunk_strategy,
            )
        )
        embedding_changes.append(
            _embedding_change(
                chunk=chunk,
                embedding=embedding,
                chunk_strategy=write.chunk_strategy,
                embedding_model=write.embedding_model,
                text_hashes=write.text_hashes,
            )
        )

    return build_surreal_delta_manifest(
        source_selection=source_selection,
        checkpoint_candidate=checkpoint_candidate,
        documents=SurrealDeltaSection(rows=[document_change]),
        source_units=SurrealDeltaSection(),
        chunks=SurrealDeltaSection(rows=chunk_changes),
        chunk_file_bindings=SurrealDeltaSection(rows=chunk_file_binding_changes),
        provenance=SurrealDeltaSection(rows=provenance_changes),
        resource_bindings=SurrealDeltaSection(
            rows=[_resource_binding_change(write.source_document)]
        ),
        fingerprints=SurrealDeltaSection(),
        embeddings=SurrealDeltaSection(rows=embedding_changes),
        vector_components=SurrealDeltaSection(),
        graph=SurrealDeltaSection(
            deferred=True,
            deferred_reason="graph sync is deferred for the direct filesystem slice",
        ),
        feedback=SurrealDeltaSection(
            deferred=True,
            deferred_reason="feedback sync is deferred for the direct filesystem slice",
        ),
        created_at=created_at,
    )
