"""File discovery and reading for markdown knowledge bases."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path

from dotmd.core.models import FileInfo

logger = logging.getLogger(__name__)

_HEADING_RE = re.compile(r"^#\s+(.+)", re.MULTILINE)


def _extract_title(content: str, path: Path) -> str:
    """Extract a human-readable title from file content or fall back to the filename.

    Looks for the first top-level ``# heading`` in *content*.  If none is
    found the file stem (filename without extension) is returned instead.
    """
    match = _HEADING_RE.search(content)
    if match:
        return match.group(1).strip()
    return path.stem


def discover_files(directory: Path) -> list[FileInfo]:
    """Recursively discover all ``.md`` files under *directory*.

    Parameters
    ----------
    directory:
        Root directory to search.  Must exist and be a directory.

    Returns
    -------
    list[FileInfo]
        Sorted by file path for deterministic ordering.

    Raises
    ------
    FileNotFoundError
        If *directory* does not exist.
    NotADirectoryError
        If *directory* is not a directory.
    """
    if not directory.exists():
        raise FileNotFoundError(f"Directory does not exist: {directory}")
    if not directory.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {directory}")

    results: list[FileInfo] = []
    for md_path in sorted(directory.rglob("*.md")):
        if not md_path.is_file():
            continue
        try:
            content = read_file(md_path)
            stat = md_path.stat()
            results.append(
                FileInfo(
                    path=md_path,
                    title=_extract_title(content, md_path),
                    last_modified=datetime.fromtimestamp(
                        stat.st_mtime, tz=timezone.utc
                    ),
                    size_bytes=stat.st_size,
                )
            )
        except OSError:
            logger.warning("Skipping unreadable file: %s", md_path, exc_info=True)

    logger.info("Discovered %d markdown files in %s", len(results), directory)
    return results


def _extract_exclude_names(exclude: list[str]) -> set[str]:
    """Extract simple directory/file names from exclude patterns.

    For patterns like ``**/node_modules`` or ``**/.git``, extract the
    trailing component (``node_modules``, ``.git``) for fast directory
    pruning during ``os.walk``.
    """
    names: set[str] = set()
    for pattern in exclude:
        # Strip leading **/ prefixes to get the bare name
        bare = pattern.lstrip("*").lstrip("/")
        if bare and "*" not in bare and "?" not in bare:
            names.add(bare)
    return names


def _prune_dirs(dirs: list[str], exclude_names: set[str]) -> None:
    """Remove excluded directory names from *dirs* in-place (for os.walk pruning)."""
    dirs[:] = [d for d in dirs if d not in exclude_names]


def _is_excluded(path: Path, exclude_names: set[str]) -> bool:
    """Check if any component of *path* matches an excluded name."""
    return bool(exclude_names.intersection(path.parts))


def discover_files_multi(
    paths: list[str],
    exclude: list[str],
) -> list[FileInfo]:
    """Discover ``.md`` files from multiple directory paths and/or glob patterns.

    Parameters
    ----------
    paths:
        List of directory paths (full recursive scan) or glob patterns
        (e.g., ``/home/**/README.md``).  Directories are walked recursively
        for all ``.md`` files.  Glob patterns are expanded and filtered to
        ``.md`` files only.
    exclude:
        Glob-style patterns for paths to skip.  Patterns like
        ``**/node_modules`` cause both directory pruning during walk and
        post-filtering for glob results.

    Returns
    -------
    list[FileInfo]
        Deduplicated, sorted by resolved path for deterministic ordering.
    """
    exclude_names = _extract_exclude_names(exclude)
    seen: set[Path] = set()
    results: list[FileInfo] = []

    for path_spec in paths:
        if "*" in path_spec or "?" in path_spec:
            # Glob pattern -- find the root directory before the first wildcard
            _collect_glob(path_spec, exclude_names, seen, results)
        else:
            # Plain directory path -- recursive walk
            _collect_directory(Path(path_spec), exclude_names, seen, results)

    results.sort(key=lambda fi: fi.path)
    logger.info(
        "Multi-path discovery: %d files from %d path specs", len(results), len(paths)
    )
    return results


def _collect_directory(
    directory: Path,
    exclude_names: set[str],
    seen: set[Path],
    results: list[FileInfo],
) -> None:
    """Walk a directory recursively, pruning excluded dirs, collecting .md files."""
    if not directory.is_dir():
        logger.warning("Skipping non-directory path: %s", directory)
        return

    for dirpath, dirs, files in os.walk(directory):
        _prune_dirs(dirs, exclude_names)
        for fname in files:
            if not fname.endswith(".md"):
                continue
            md_path = Path(dirpath) / fname
            _add_file(md_path, exclude_names, seen, results)


def _collect_glob(
    pattern: str,
    exclude_names: set[str],
    seen: set[Path],
    results: list[FileInfo],
) -> None:
    """Expand a glob pattern and collect matching .md files."""
    # Find the root directory: everything before the first wildcard segment
    parts = Path(pattern).parts
    root_parts: list[str] = []
    glob_parts: list[str] = []
    found_wild = False
    for part in parts:
        if found_wild or "*" in part or "?" in part:
            found_wild = True
            glob_parts.append(part)
        else:
            root_parts.append(part)

    if not root_parts:
        root = Path(".")
    else:
        root = Path(*root_parts) if len(root_parts) > 1 else Path(root_parts[0])

    glob_pattern = str(Path(*glob_parts)) if glob_parts else "*"

    if not root.is_dir():
        logger.warning("Glob root does not exist: %s (from pattern %s)", root, pattern)
        return

    for match in root.glob(glob_pattern):
        if match.is_file() and match.suffix == ".md":
            _add_file(match, exclude_names, seen, results)


def _add_file(
    md_path: Path,
    exclude_names: set[str],
    seen: set[Path],
    results: list[FileInfo],
) -> None:
    """Add a single .md file to results if not excluded or already seen."""
    resolved = md_path.resolve()
    if resolved in seen:
        return
    if _is_excluded(md_path, exclude_names):
        return

    try:
        stat = md_path.stat()
        if stat.st_size == 0:
            logger.info("Skipping empty file (0 bytes): %s", md_path)
            return
        content = read_file(md_path)
        results.append(
            FileInfo(
                path=md_path,
                title=_extract_title(content, md_path),
                last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                size_bytes=stat.st_size,
            )
        )
        seen.add(resolved)
    except OSError:
        logger.warning("Skipping unreadable file: %s", md_path, exc_info=True)


def read_file(path: Path) -> str:
    """Read and return the full text content of a file.

    Parameters
    ----------
    path:
        Path to the file to read.

    Returns
    -------
    str
        The file contents decoded as UTF-8.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    """
    return path.read_text(encoding="utf-8")
