"""Background trickle indexer for dotMD.

Processes unindexed files one at a time in the background while the API
serves search queries. Uses watchdog for filesystem monitoring and
asyncio for lifecycle management within FastAPI's lifespan.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer

from dotmd.core.models import FileInfo

if TYPE_CHECKING:
    from dotmd.core.config import Settings
    from dotmd.ingestion.pipeline import IndexingPipeline

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State tracking
# ---------------------------------------------------------------------------


@dataclass
class TrickleState:
    """Observable state of the background indexer."""

    status: str = "idle"  # "idle", "backlog", "watching", "stopping"
    indexed_count: int = 0
    total_files: int = 0
    current_file: str | None = None
    files_per_hour: float = 0.0
    chunks_per_hour: float = 0.0
    total_chunks_done: int = 0
    eta_minutes: float | None = None
    _start_time: float = field(default_factory=time.monotonic, repr=False)


# ---------------------------------------------------------------------------
# Watchdog -> asyncio bridge
# ---------------------------------------------------------------------------


class _MarkdownEventHandler(PatternMatchingEventHandler):
    """Watches for new/modified .md files and enqueues them."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue,
        exclude: list[str],
    ) -> None:
        super().__init__(patterns=["*.md"], ignore_directories=True)
        self._loop = loop
        self._queue = queue
        self._exclude = exclude
        self._debounce: dict[str, float] = {}

    def on_created(self, event):  # noqa: ANN001
        self._enqueue(event.src_path)

    def on_modified(self, event):  # noqa: ANN001
        self._enqueue(event.src_path)

    def _enqueue(self, path_str: str) -> None:
        now = time.monotonic()
        # Debounce: ignore events within 2 seconds for same file
        if path_str in self._debounce and now - self._debounce[path_str] < 2.0:
            return
        self._debounce[path_str] = now
        # Check exclude patterns
        p = Path(path_str)
        for pattern in self._exclude:
            bare = pattern.replace("**/", "").replace("*/", "")
            if bare in p.parts:
                return
        self._loop.call_soon_threadsafe(self._queue.put_nowait, path_str)


# ---------------------------------------------------------------------------
# TrickleIndexer
# ---------------------------------------------------------------------------


class TrickleIndexer:
    """Background indexer that processes files one at a time.

    Parameters
    ----------
    pipeline:
        The IndexingPipeline instance (shared with DotMDService).
    settings:
        Application settings with indexing paths, exclude, pause config.
    """

    def __init__(self, pipeline: IndexingPipeline, settings: Settings) -> None:
        self._pipeline = pipeline
        self._settings = settings
        self._state = TrickleState()
        self._file_queue: asyncio.Queue[str] = asyncio.Queue()
        self._observer: Observer | None = None

    @property
    def state(self) -> TrickleState:
        """Return current indexer state (read by status endpoint)."""
        return self._state

    async def run(self, shutdown: asyncio.Event) -> None:
        """Main entry point: process backlog, then watch for new files.

        Parameters
        ----------
        shutdown:
            Event set by the server lifespan to signal graceful shutdown.
        """
        if not self._settings.indexing_paths:
            logger.info("Trickle indexer idle — no indexing_paths in config")
            self._state.status = "idle"
            await shutdown.wait()
            return

        logger.info(
            "Trickle indexer starting — %d paths configured: %s",
            len(self._settings.indexing_paths),
            ", ".join(self._settings.indexing_paths),
        )

        # Reset counters once at startup (not on every poll cycle)
        self._state._start_time = time.monotonic()
        self._state.indexed_count = 0
        self._state.total_chunks_done = 0

        try:
            # Phase 1: Process existing backlog
            await self._process_backlog(shutdown)
            if shutdown.is_set():
                return

            # Phase 2: Watch mode
            await self._watch_mode(shutdown)
        except Exception:
            logger.exception("Trickle indexer crashed")
        finally:
            self._stop_observer()
            self._state.status = "stopping"
            logger.info(
                "Trickle indexer stopped (indexed %d files)",
                self._state.indexed_count,
            )

    # ------------------------------------------------------------------
    # Backlog processing
    # ------------------------------------------------------------------

    async def _process_backlog(self, shutdown: asyncio.Event) -> None:
        """Discover and process all unindexed files (newest first)."""
        self._state.status = "backlog"
        logger.info(
            "Discovering unindexed files from %d paths...",
            len(self._settings.indexing_paths),
        )

        # Discover all files from configured paths
        from dotmd.ingestion.reader import discover_files_multi

        all_files = await asyncio.to_thread(
            discover_files_multi,
            self._settings.indexing_paths,
            self._settings.indexing_exclude,
        )

        # Diff against file tracker to find unindexed files
        diff = self._pipeline.file_tracker.diff(all_files)
        unindexed_paths = set(diff.new) | set(diff.modified)
        unindexed = [fi for fi in all_files if str(fi.path) in unindexed_paths]

        # Sort by mtime descending — newest first
        unindexed.sort(key=lambda fi: fi.last_modified, reverse=True)

        # Purge deleted files (in tracker but no longer on disk / now excluded)
        if diff.deleted:
            logger.info("Purging %d deleted/excluded files from index", len(diff.deleted))
            for path_str in diff.deleted:
                try:
                    await asyncio.to_thread(self._pipeline._purge_file, path_str)
                except Exception:
                    logger.exception("Failed to purge %s", path_str)
            logger.info("Purge complete: %d files removed from all stores", len(diff.deleted))

        self._state.total_files = len(unindexed)
        logger.info(
            "Backlog: %d new, %d modified, %d deleted, %d unchanged, %d total",
            len(diff.new),
            len(diff.modified),
            len(diff.deleted),
            len(diff.unchanged),
            len(all_files),
        )

        if not unindexed:
            return

        if len(unindexed) <= 5:
            for fi in unindexed:
                logger.info("  queued: %s (mtime %s)", fi.path, fi.last_modified.isoformat())

        succeeded = 0
        failed = 0

        for i, file_info in enumerate(unindexed):
            if shutdown.is_set():
                logger.info(
                    "Shutdown requested -- stopping backlog at %d/%d",
                    i,
                    len(unindexed),
                )
                return

            self._state.current_file = str(file_info.path)
            try:
                n_chunks = await asyncio.to_thread(self._process_one_file, file_info)
            except Exception:
                failed += 1
                logger.exception("Failed to index %s -- skipping", file_info.path)
                continue

            succeeded += 1
            self._state.indexed_count = succeeded
            self._state.total_chunks_done += n_chunks or 0
            self._update_eta(i + 1, len(unindexed))

            # Progress log every file
            eta_str = ""
            if self._state.eta_minutes is not None:
                if self._state.eta_minutes < 60:
                    eta_str = f", ETA ~{self._state.eta_minutes:.0f}min"
                else:
                    eta_str = f", ETA ~{self._state.eta_minutes / 60:.1f}hr"
            rate_str = ""
            if self._state.chunks_per_hour > 0:
                rate_str = f" @ {self._state.chunks_per_hour:.0f} chunks/hr ({self._state.files_per_hour:.0f} files/hr)"
            logger.info(
                "[%d/%d] %d chunks total%s%s",
                succeeded,
                len(unindexed),
                self._state.total_chunks_done,
                rate_str,
                eta_str,
            )

        self._state.current_file = None
        if failed:
            logger.warning("Backlog done: %d indexed, %d failed (of %d total)", succeeded, failed, len(unindexed))
        else:
            logger.info("Backlog complete: %d files indexed", succeeded)

    # ------------------------------------------------------------------
    # Watch mode
    # ------------------------------------------------------------------

    async def _watch_mode(self, shutdown: asyncio.Event) -> None:
        """Watch configured paths for new files via inotify + polling fallback."""
        self._state.status = "watching"
        logger.info(
            "Entering watch mode (poll interval: %ds)",
            int(self._settings.poll_interval_seconds),
        )

        self._start_observer()

        while not shutdown.is_set():
            # Process any files queued by watchdog events
            while not self._file_queue.empty():
                try:
                    path_str = self._file_queue.get_nowait()
                    file_path = Path(path_str)
                    if not file_path.exists() or not file_path.is_file():
                        continue
                    stat = file_path.stat()
                    fi = FileInfo(
                        path=file_path,
                        title=file_path.stem,
                        last_modified=datetime.fromtimestamp(
                            stat.st_mtime, tz=timezone.utc
                        ),
                        size_bytes=stat.st_size,
                    )
                    self._state.current_file = path_str
                    try:
                        await asyncio.to_thread(self._process_one_file, fi)
                        self._state.indexed_count += 1
                        logger.info("Watch: indexed %s", file_path.name)
                    finally:
                        self._state.current_file = None
                except Exception:
                    logger.exception("Watch: failed to index %s", path_str)

            # Wait for shutdown or poll interval timeout
            try:
                await asyncio.wait_for(
                    shutdown.wait(),
                    timeout=self._settings.poll_interval_seconds,
                )
                return  # shutdown signaled
            except asyncio.TimeoutError:
                # Polling fallback: re-scan for files inotify may have missed
                logger.debug("Polling fallback: re-scanning paths")
                try:
                    await self._process_backlog(shutdown)
                except Exception:
                    logger.exception("Poll-cycle backlog scan failed — will retry next interval")

    # ------------------------------------------------------------------
    # Per-file processing (synchronous, runs in thread pool)
    # ------------------------------------------------------------------

    def _process_one_file(self, file_info: FileInfo) -> int:
        """Process a single file through the pipeline.

        Delegates to ``IndexingPipeline.index_file`` which handles purge,
        chunk, embed, store, extract, graph, and fingerprint.

        Runs synchronously in a thread pool to avoid blocking the event loop.
        """
        t0 = time.perf_counter()
        n_chunks = self._pipeline.index_file(file_info)
        elapsed = time.perf_counter() - t0
        if n_chunks:
            logger.info("%s — %d chunks, %.1fs", file_info.path.name, n_chunks, elapsed)
        else:
            logger.debug("Skipping %s — empty after chunking", file_info.path.name)
        return n_chunks

    # ------------------------------------------------------------------
    # Observer management
    # ------------------------------------------------------------------

    def _start_observer(self) -> None:
        """Start watchdog Observer for all configured directory paths."""
        loop = asyncio.get_running_loop()
        handler = _MarkdownEventHandler(
            loop, self._file_queue, self._settings.indexing_exclude
        )
        self._observer = Observer()

        for path_spec in self._settings.indexing_paths:
            # Only watch actual directories, not glob patterns
            if "*" not in path_spec and "?" not in path_spec:
                watch_path = Path(path_spec)
                if watch_path.is_dir():
                    self._observer.schedule(handler, str(watch_path), recursive=True)
                    logger.info("Watching directory: %s", watch_path)

        self._observer.start()

    def _stop_observer(self) -> None:
        """Stop watchdog Observer cleanly to prevent thread leak."""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=10)
            self._observer = None

    def _update_eta(self, files_done: int, files_total: int) -> None:
        """Update throughput rates and ETA."""
        elapsed = time.monotonic() - self._state._start_time
        if elapsed > 0 and files_done > 0:
            self._state.files_per_hour = files_done / (elapsed / 3600)
            if self._state.total_chunks_done > 0:
                self._state.chunks_per_hour = self._state.total_chunks_done / (elapsed / 3600)
            remaining = files_total - files_done
            if self._state.files_per_hour > 0:
                self._state.eta_minutes = remaining / (self._state.files_per_hour / 60)
