"""Direct in-memory Surreal delta manifest builder for filesystem slices."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from dotmd.core.models import ApplicationSourceChange, Chunk, SourceDocument, SourceUnit
from dotmd.ingestion.surreal_delta_sync import (
    SurrealDeltaChange,
    SurrealDeltaCheckpointCandidate,
    SurrealDeltaManifest,
    SurrealDeltaSection,
    SurrealDeltaSourceSelection,
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
    source_unit_refs = (
        list(provenance.source_unit_refs) if provenance is not None else []
    )
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
            "chunk_strategy": provenance.chunk_strategy if provenance is not None else chunk_strategy,
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
    source_unit_refs = (
        list(provenance.source_unit_refs) if provenance is not None else []
    )
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
            "chunk_strategy": provenance.chunk_strategy if provenance is not None else chunk_strategy,
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
            "vector_rowid": None,
            "vector": list(embedding),
            "metadata": {},
        },
    )


def build_surreal_application_source_manifest(
    write: SurrealApplicationSourceWrite,
    *,
    source_selection: SurrealDeltaSourceSelection,
    checkpoint_candidate: SurrealDeltaCheckpointCandidate,
    created_at: datetime | None = None,
) -> SurrealDeltaManifest:
    """Build a direct Surreal delta manifest from application-source state."""

    if len(write.chunks) != len(write.e_text_vectors) or len(write.chunks) != len(write.e_fused_vectors):
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

    document_changes = [
        _document_change(documents_by_ref[ref]) for ref in sorted(documents_by_ref)
    ]
    resource_binding_changes = [
        _resource_binding_change(documents_by_ref[ref])
        for ref in sorted(documents_by_ref)
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
        meta_vector = write.e_meta_by_source_key.get((source_document.namespace, source_document.document_ref))
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
        resource_bindings=SurrealDeltaSection(rows=[_resource_binding_change(write.source_document)]),
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
