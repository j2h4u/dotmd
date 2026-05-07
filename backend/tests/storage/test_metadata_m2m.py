"""RED test skeletons for SQLiteMetadataStore M2M surface (P1 — Task 1).

After Phase 16 P1 ships, SQLiteMetadataStore gains:
  - insert_chunk (INSERT OR IGNORE, no file_path/chunk_index/char_offset)
  - add_file_path (INSERT OR IGNORE on M2M table)
  - get_file_paths_by_chunk_id (sorted lex)
  - get_file_paths_for_chunk_ids (batch hydration, single SELECT)
  - delete_m2m_for_file (returns orphans, uses caller conn)
  - get_stored_payload

These tests will FAIL until P1 (wave 2) implements the new metadata surface.

Assertion style: return-value assertions only (Review-LOW-10).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

# These imports will ImportError or AttributeError until P1 ships:
from dotmd.core.models import Chunk, ChunkProvenance, ResourceBinding, SourceDocument
from dotmd.storage.metadata import SQLiteMetadataStore

STRATEGY = "heading_512_50"
MODEL = "multilingual_e5_large"
VALID_CHUNK_ID = "a" * 64  # 64-char fake blake3 id


def _build_m2m_store(tmp_path: Path) -> SQLiteMetadataStore:
    """Return a SQLiteMetadataStore using the post-v16 M2M schema."""
    db_path = tmp_path / "metadata.db"
    store = SQLiteMetadataStore(db_path=db_path, table_name=f"chunks_{STRATEGY}")
    # P1 must provide ensure_m2m_table — call it to create chunk_file_paths_*
    store.ensure_m2m_table(STRATEGY)
    return store


def _source_document(path: Path) -> SourceDocument:
    document_ref = str(path.resolve())
    return SourceDocument(
        namespace="filesystem",
        document_ref=document_ref,
        ref=f"filesystem:{document_ref}",
        source_uri=document_ref,
        file_path=path,
        media_type="text/markdown",
        parser_name="markdown",
        document_type="document",
        title="Source Document",
        updated_at=datetime.now(tz=UTC),
        content_fingerprint="content-fp",
        metadata_fingerprint="metadata-fp",
        metadata_json={"tags": ["source"]},
    )


def _filesystem_provenance(path: Path) -> ChunkProvenance:
    document_ref = str(path.resolve())
    return ChunkProvenance(
        namespace="filesystem",
        document_ref=document_ref,
        ref=f"filesystem:{document_ref}",
        source_unit_refs=[],
        chunk_strategy=STRATEGY,
        parser_name="markdown",
    )


def _resource_binding(path: Path, *, active: bool = True) -> ResourceBinding:
    document_ref = str(path.resolve())
    return ResourceBinding(
        namespace="filesystem",
        resource_ref=document_ref,
        document_ref=document_ref,
        ref=f"filesystem:{document_ref}",
        active=active,
        bound_at=datetime.now(tz=UTC),
        unbound_at=None,
        content_fingerprint="content-fp",
        metadata_fingerprint="metadata-fp",
        source_unit_refs=[],
        metadata_json={"deactivation_reason": "file_missing"} if not active else {},
    )


class TestInsertChunkIsIdempotent:
    """insert_chunk is INSERT OR IGNORE — second call with same chunk_id is a no-op."""

    def test_insert_chunk_is_idempotent(self, tmp_path: Path) -> None:
        """Inserting the same chunk_id twice does not raise and does not duplicate the row."""
        store = _build_m2m_store(tmp_path)

        store.insert_chunk(
            STRATEGY,
            chunk_id=VALID_CHUNK_ID,
            heading_hierarchy=["Heading"],
            level=1,
            text="Test content",
        )
        # Second insert with same id — must be silent no-op
        store.insert_chunk(
            STRATEGY,
            chunk_id=VALID_CHUNK_ID,
            heading_hierarchy=["Heading"],
            level=1,
            text="Test content",
        )

        conn = sqlite3.connect(str(tmp_path / "metadata.db"))
        count = conn.execute(
            f"SELECT COUNT(*) FROM chunks_{STRATEGY} WHERE chunk_id=?",
            (VALID_CHUNK_ID,),
        ).fetchone()[0]
        conn.close()
        assert count == 1, f"Expected 1 row after idempotent insert, got {count}"


class TestAddFilePathIsIdempotent:
    """add_file_path is INSERT OR IGNORE — duplicate (chunk_id, file_path, chunk_index) is a no-op."""

    def test_add_file_path_is_idempotent(self, tmp_path: Path) -> None:
        """Adding the same (chunk_id, file_path, chunk_index) twice does not duplicate the M2M row."""
        store = _build_m2m_store(tmp_path)
        store.insert_chunk(STRATEGY, VALID_CHUNK_ID, ["H"], 1, "text")

        store.add_file_path(STRATEGY, VALID_CHUNK_ID, "/path/file.md", chunk_index=0)
        store.add_file_path(STRATEGY, VALID_CHUNK_ID, "/path/file.md", chunk_index=0)

        conn = sqlite3.connect(str(tmp_path / "metadata.db"))
        count = conn.execute(
            f"SELECT COUNT(*) FROM chunk_file_paths_{STRATEGY} WHERE chunk_id=?",
            (VALID_CHUNK_ID,),
        ).fetchone()[0]
        conn.close()
        assert count == 1, f"Expected 1 M2M row after idempotent add_file_path, got {count}"


class TestGetFilePathsSortedLex:
    """get_file_paths_by_chunk_id returns paths in lexicographic order."""

    def test_get_file_paths_sorted_lex(self, tmp_path: Path) -> None:
        """File paths for a chunk_id are returned sorted lexicographically."""
        store = _build_m2m_store(tmp_path)
        store.insert_chunk(STRATEGY, VALID_CHUNK_ID, ["H"], 1, "text")

        paths = ["/z/last.md", "/a/first.md", "/m/middle.md"]
        for _i, fp in enumerate(paths):
            store.add_file_path(STRATEGY, VALID_CHUNK_ID, fp, chunk_index=0)

        result = store.get_file_paths_by_chunk_id(STRATEGY, VALID_CHUNK_ID)
        assert result == sorted(paths), (
            f"Expected sorted lex order {sorted(paths)!r}, got {result!r}"
        )


class TestGetFilePathsForChunkIdsSingleQuery:
    """get_file_paths_for_chunk_ids uses a single SELECT (Review-LOW-12 batch hydration)."""

    def test_get_file_paths_for_chunk_ids_single_query(self, tmp_path: Path) -> None:
        """Batch hydration of 5 chunk_ids uses at most 1 SQL round-trip per strategy."""
        store = _build_m2m_store(tmp_path)

        chunk_ids = [chr(ord("a") + i) * 64 for i in range(5)]
        for i, cid in enumerate(chunk_ids):
            store.insert_chunk(STRATEGY, cid, ["H"], 1, f"text {i}")
            store.add_file_path(STRATEGY, cid, f"/path/file_{i}.md", chunk_index=0)

        # Spy on the execute method to count SELECT calls
        original_execute = store._conn.execute
        call_count = {"n": 0}

        def counting_execute(sql: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if str(sql).strip().upper().startswith("SELECT"):
                call_count["n"] += 1
            return original_execute(sql, *args, **kwargs)

        store._conn.execute = counting_execute  # type: ignore[method-assign]
        call_count["n"] = 0  # reset

        result = store.get_file_paths_for_chunk_ids(STRATEGY, chunk_ids)

        assert call_count["n"] <= 1, (
            f"Expected single SELECT for batch hydration, but {call_count['n']} SELECT calls made"
        )
        assert isinstance(result, dict)
        assert len(result) == 5
        for cid in chunk_ids:
            assert cid in result
            assert isinstance(result[cid], list)
            assert len(result[cid]) == 1


class TestDeleteM2MForFileReturnsOrphans:
    """delete_m2m_for_file returns chunk_ids whose holder count dropped to 0."""

    def test_delete_m2m_for_file_returns_orphans_uses_caller_conn(
        self, tmp_path: Path
    ) -> None:
        """delete_m2m_for_file uses the caller-supplied connection; returns orphan chunk_ids."""
        store = _build_m2m_store(tmp_path)

        # shared_cid is held by two files — NOT an orphan after removing file_a
        shared_cid = "b" * 64
        # sole_cid is held only by file_a — IS an orphan after removing file_a
        sole_cid = "c" * 64

        store.insert_chunk(STRATEGY, shared_cid, ["H"], 1, "shared text")
        store.insert_chunk(STRATEGY, sole_cid, ["H"], 1, "sole text")

        store.add_file_path(STRATEGY, shared_cid, "/file_a.md", chunk_index=0)
        store.add_file_path(STRATEGY, shared_cid, "/file_b.md", chunk_index=0)
        store.add_file_path(STRATEGY, sole_cid, "/file_a.md", chunk_index=1)

        # delete_m2m_for_file MUST use the caller's conn (contract: no internal commit)
        conn = sqlite3.connect(str(tmp_path / "metadata.db"))
        orphans = store.delete_m2m_for_file(STRATEGY, "/file_a.md", conn=conn)
        conn.commit()
        conn.close()

        assert sole_cid in orphans, (
            f"sole_cid should be in orphans (last holder removed), got {orphans!r}"
        )
        assert shared_cid not in orphans, (
            f"shared_cid should NOT be in orphans (still held by file_b), got {orphans!r}"
        )


class TestSourceDocumentPersistence:
    """source_documents stores filesystem source document identity additively."""

    def test_source_document_persistence(self, tmp_path: Path) -> None:
        store = _build_m2m_store(tmp_path)
        md_path = tmp_path / "note.md"
        md_path.write_text("# Note\n", encoding="utf-8")
        document = _source_document(md_path)

        conn = sqlite3.connect(str(tmp_path / "metadata.db"))
        store.upsert_source_document(document, conn=conn)
        conn.commit()
        conn.close()

        loaded = store.get_source_document("filesystem", str(md_path.resolve()))

        assert loaded is not None
        assert loaded.document_ref == str(md_path.resolve())
        assert loaded.ref == f"filesystem:{md_path.resolve()}"
        assert loaded.file_path == md_path
        assert loaded.metadata_json == {"tags": ["source"]}


class TestChunkSourceProvenance:
    """chunk_source_provenance_<strategy> stores filesystem chunk provenance."""

    def test_filesystem_chunk_provenance_round_trips_empty_source_unit_refs(
        self, tmp_path: Path
    ) -> None:
        store = _build_m2m_store(tmp_path)
        store.ensure_chunk_source_provenance_table(STRATEGY)
        md_path = tmp_path / "note.md"
        md_path.write_text("# Note\n", encoding="utf-8")

        conn = sqlite3.connect(str(tmp_path / "metadata.db"))
        store.add_chunk_provenance(
            STRATEGY,
            _filesystem_provenance(md_path),
            VALID_CHUNK_ID,
            conn=conn,
        )
        conn.commit()
        conn.close()

        loaded = store.get_chunk_provenance_for_chunk_ids(
            STRATEGY,
            [VALID_CHUNK_ID],
        )

        assert loaded[VALID_CHUNK_ID].document_ref == str(md_path.resolve())
        assert loaded[VALID_CHUNK_ID].source_unit_refs == []
        assert loaded[VALID_CHUNK_ID].parser_name == "markdown"

    def test_file_paths_still_return_for_chunk_with_provenance(
        self, tmp_path: Path
    ) -> None:
        store = _build_m2m_store(tmp_path)
        store.ensure_chunk_source_provenance_table(STRATEGY)
        md_path = tmp_path / "note.md"
        md_path.write_text("# Note\n", encoding="utf-8")
        store.insert_chunk(STRATEGY, VALID_CHUNK_ID, ["H"], 1, "text")
        store.add_file_path(
            STRATEGY,
            VALID_CHUNK_ID,
            str(md_path),
            chunk_index=0,
        )
        conn = sqlite3.connect(str(tmp_path / "metadata.db"))
        store.add_chunk_provenance(
            STRATEGY,
            _filesystem_provenance(md_path),
            VALID_CHUNK_ID,
            conn=conn,
        )
        conn.commit()
        conn.close()

        assert store.get_file_paths_by_chunk_id(STRATEGY, VALID_CHUNK_ID) == [
            str(md_path)
        ]

    def test_chunk_provenance_batch_hydration(
        self, tmp_path: Path
    ) -> None:
        store = _build_m2m_store(tmp_path)
        store.ensure_chunk_source_provenance_table(STRATEGY)
        md_path = tmp_path / "note.md"
        md_path.write_text("# Note\n", encoding="utf-8")
        chunk_ids = ["e" * 64, "f" * 64]

        conn = sqlite3.connect(str(tmp_path / "metadata.db"))
        for chunk_id in chunk_ids:
            store.add_chunk_provenance(
                STRATEGY,
                _filesystem_provenance(md_path),
                chunk_id,
                conn=conn,
            )
        conn.commit()
        conn.close()

        loaded = store.get_chunk_provenance_for_chunk_ids(STRATEGY, chunk_ids)

        assert sorted(loaded) == sorted(chunk_ids)
        assert all(
            provenance.source_unit_refs == []
            for provenance in loaded.values()
        )


class TestResourceBindings:
    """resource_bindings tracks active source visibility separately."""

    def test_resource_binding_model_requires_canonical_ref(
        self,
        tmp_path: Path,
    ) -> None:
        md_path = tmp_path / "note.md"
        md_path.write_text("# Note\n", encoding="utf-8")
        binding = _resource_binding(md_path)

        assert binding.ref == f"filesystem:{md_path.resolve()}"
        assert binding.active is True

        with pytest.raises(ValueError):
            ResourceBinding(
                namespace="filesystem",
                resource_ref=str(md_path.resolve()),
                document_ref=str(md_path.resolve()),
                ref="filesystem:wrong",
                active=True,
                bound_at=datetime.now(tz=UTC),
                content_fingerprint="content-fp",
                metadata_fingerprint="metadata-fp",
            )

    def test_resource_binding_round_trips_and_counts_active_state(
        self,
        tmp_path: Path,
    ) -> None:
        store = _build_m2m_store(tmp_path)
        active_path = tmp_path / "active.md"
        inactive_path = tmp_path / "inactive.md"
        active_path.write_text("# Active\n", encoding="utf-8")
        inactive_path.write_text("# Inactive\n", encoding="utf-8")

        conn = sqlite3.connect(str(tmp_path / "metadata.db"))
        store.upsert_resource_binding(_resource_binding(active_path), conn=conn)
        store.upsert_resource_binding(
            _resource_binding(inactive_path, active=False),
            conn=conn,
        )
        store.set_resource_binding_active(
            "filesystem",
            str(inactive_path.resolve()),
            False,
            conn=conn,
            unbound_at=datetime.now(tz=UTC),
        )
        conn.commit()
        conn.close()

        active = store.get_resource_binding(
            "filesystem",
            str(active_path.resolve()),
        )
        inactive = store.get_resource_binding(
            "filesystem",
            str(inactive_path.resolve()),
        )

        assert active is not None
        assert active.active is True
        assert active.content_fingerprint == "content-fp"
        assert inactive is not None
        assert inactive.active is False
        assert inactive.unbound_at is not None
        assert store.is_resource_binding_active(
            "filesystem",
            str(active_path.resolve()),
        )
        assert not store.is_resource_binding_active(
            "filesystem",
            str(inactive_path.resolve()),
        )
        assert store.count_resource_bindings() == {
            "active": 1,
            "inactive": 1,
            "total": 2,
        }

    def test_backfill_existing_source_documents_creates_active_bindings(
        self,
        tmp_path: Path,
    ) -> None:
        store = _build_m2m_store(tmp_path)
        md_path = tmp_path / "note.md"
        md_path.write_text("# Note\n", encoding="utf-8")
        source_document = _source_document(md_path)

        conn = sqlite3.connect(str(tmp_path / "metadata.db"))
        store.upsert_source_document(source_document, conn=conn)
        conn.commit()
        conn.close()

        backfilled = store.backfill_resource_bindings_from_source_documents()
        binding = store.get_resource_binding(
            "filesystem",
            str(md_path.resolve()),
        )

        assert backfilled == 1
        assert binding is not None
        assert binding.active is True
        assert binding.resource_ref == source_document.document_ref
        assert binding.document_ref == source_document.document_ref
        assert binding.ref == source_document.ref
        assert binding.content_fingerprint == source_document.content_fingerprint
        assert binding.metadata_fingerprint == source_document.metadata_fingerprint
        assert binding.source_unit_refs == []
        assert binding.metadata_json == {}

        assert store.backfill_resource_bindings_from_source_documents() == 0

    def test_resource_binding_startup_backfill_is_idempotent(
        self,
        tmp_path: Path,
    ) -> None:
        store = _build_m2m_store(tmp_path)
        md_path = tmp_path / "startup.md"
        md_path.write_text("# Startup\n", encoding="utf-8")

        conn = sqlite3.connect(str(tmp_path / "metadata.db"))
        store.upsert_source_document(_source_document(md_path), conn=conn)
        conn.commit()
        conn.close()

        restarted = SQLiteMetadataStore(
            db_path=tmp_path / "metadata.db",
            table_name=f"chunks_{STRATEGY}",
        )

        assert restarted.is_resource_binding_active(
            "filesystem",
            str(md_path.resolve()),
        )
        assert restarted.backfill_resource_bindings_from_source_documents() == 0

    def test_backfill_does_not_reactivate_inactive_binding(
        self,
        tmp_path: Path,
    ) -> None:
        store = _build_m2m_store(tmp_path)
        md_path = tmp_path / "inactive.md"
        md_path.write_text("# Inactive\n", encoding="utf-8")

        conn = sqlite3.connect(str(tmp_path / "metadata.db"))
        store.upsert_source_document(_source_document(md_path), conn=conn)
        store.upsert_resource_binding(_resource_binding(md_path), conn=conn)
        store.set_resource_binding_active(
            "filesystem",
            str(md_path.resolve()),
            False,
            conn=conn,
            unbound_at=datetime.now(tz=UTC),
        )
        conn.commit()
        conn.close()

        assert store.backfill_resource_bindings_from_source_documents() == 0
        binding = store.get_resource_binding(
            "filesystem",
            str(md_path.resolve()),
        )
        assert binding is not None
        assert binding.active is False


class TestDeleteAllClearsSourceProvenance:
    """delete_all clears source-aware tables alongside legacy chunk tables."""

    def test_delete_all_clears_source_documents_and_chunk_provenance(
        self,
        tmp_path: Path,
    ) -> None:
        store = _build_m2m_store(tmp_path)
        store.ensure_chunk_source_provenance_table(STRATEGY)
        md_path = tmp_path / "note.md"
        md_path.write_text("# Note\n", encoding="utf-8")

        conn = sqlite3.connect(str(tmp_path / "metadata.db"))
        store.upsert_source_document(_source_document(md_path), conn=conn)
        store.add_chunk_provenance(
            STRATEGY,
            _filesystem_provenance(md_path),
            VALID_CHUNK_ID,
            conn=conn,
        )
        conn.commit()
        conn.close()

        store.delete_all()

        source_count = store._conn.execute(
            "SELECT COUNT(*) FROM source_documents"
        ).fetchone()[0]
        provenance_count = store._conn.execute(
            f"SELECT COUNT(*) FROM chunk_source_provenance_{STRATEGY}"
        ).fetchone()[0]
        assert source_count == 0
        assert provenance_count == 0


class TestChunkModelRejectsCharOffset:
    """Decision #8: Chunk model must not accept char_offset after P1."""

    def test_chunk_model_rejects_char_offset(self) -> None:
        """Constructing a Chunk with char_offset raises an error (field removed in P1)."""
        with pytest.raises((TypeError, ValueError)):
            Chunk(
                chunk_id="d" * 64,
                file_paths=[Path("/some/file.md")],
                heading_hierarchy=["H"],
                level=1,
                text="text",
                chunk_index=0,
                char_offset=10,  # Must be rejected
            )
