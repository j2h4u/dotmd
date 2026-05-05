"""Source adapter boundary for markdown ingestion."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from dotmd.core.models import FileInfo, SourceDocument
from dotmd.ingestion.reader import (
    chunk_checksum,
    discover_files,
    discover_files_multi,
    meta_checksum,
)


def filesystem_document_ref(path: Path) -> str:
    """Return the canonical document ref for a filesystem path."""
    return str(Path(path).resolve())


class SourceAdapterProtocol(Protocol):
    """Discovery boundary for source-backed documents."""

    def discover(self, directory: Path) -> list[SourceDocument]:
        """Discover source documents under a directory."""
        ...

    def discover_multi(
        self,
        paths: list[str],
        exclude: list[str] | None = None,
    ) -> list[SourceDocument]:
        """Discover source documents from multiple path specs."""
        ...


class FilesystemMarkdownSourceAdapter:
    """In-process adapter for current filesystem Markdown files."""

    namespace = "filesystem"
    media_type = "text/markdown"
    parser_name = "markdown"

    def discover(self, directory: Path) -> list[SourceDocument]:
        """Discover markdown files under a directory."""
        return [
            self._from_file_info(file_info)
            for file_info in discover_files(directory)
        ]

    def discover_multi(
        self,
        paths: list[str],
        exclude: list[str] | None = None,
    ) -> list[SourceDocument]:
        """Discover markdown files from multiple path specs."""
        return [
            self._from_file_info(file_info)
            for file_info in discover_files_multi(paths, exclude or [])
        ]

    def _from_file_info(self, file_info: FileInfo) -> SourceDocument:
        document_ref = filesystem_document_ref(file_info.path)
        return SourceDocument(
            namespace=self.namespace,
            document_ref=document_ref,
            ref=f"{self.namespace}:{document_ref}",
            title=file_info.title,
            source_uri=document_ref,
            media_type=self.media_type,
            parser_name=self.parser_name,
            document_type=file_info.kind,
            updated_at=file_info.last_modified,
            content_fingerprint=chunk_checksum(file_info.path),
            metadata_fingerprint=meta_checksum(file_info.path),
            metadata_json=dict(file_info.frontmatter),
            file_path=file_info.path,
        )
