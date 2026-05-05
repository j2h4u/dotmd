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
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer

from dotmd.core.models import FileInfo, TrickleStatus
from dotmd.ingestion.lock import indexing_lock

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

    status: str = TrickleStatus.IDLE
    indexed_count: int = 0
    total_files: int = 0
    current_file: str | None = None
    files_per_hour: float = 0.0
    chunks_per_hour: float = 0.0
    total_chunks_done: int = 0
    eta_minutes: float | None = None
    last_indexed_at: datetime | None = None
    _start_time: float = field(default_factory=time.monotonic, repr=False)


def _format_duration(seconds: float) -> str:
    """Format a short human-readable duration for progress logs."""
    seconds = max(0, round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m{seconds:02d}s"


def _format_rate(per_hour: float, unit: str) -> str:
    """Render stored per-hour throughput as the more readable per-second rate."""
    per_second = per_hour / 3600
    if per_second >= 10:
        return f"{per_second:.0f} {unit}/s"
    if per_second >= 1:
        return f"{per_second:.1f} {unit}/s"
    return f"{per_second:.2f} {unit}/s"


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

    def on_created(self, event):
        self._enqueue(event.src_path)

    def on_modified(self, event):
        self._enqueue(event.src_path)

    def on_deleted(self, event):
        self._enqueue(event.src_path)

    def _enqueue(self, path_str: str) -> None:
        now = time.monotonic()
        p = Path(path_str)
        # Debounce: ignore events within 2 seconds for same file
        if path_str in self._debounce and now - self._debounce[path_str] < 2.0:
            logger.debug("Watch: debounced %s", p.name)
            return
        self._debounce[path_str] = now
        # Check exclude patterns
        for pattern in self._exclude:
            bare = pattern.replace("**/", "").replace("*/", "")
            if bare in p.parts:
                logger.debug("Watch: excluded %s (matched %s)", p.name, pattern)
                return
        self._loop.call_soon_threadsafe(self._queue.put_nowait, path_str)
        logger.info("Watch: enqueued %s", p.name)


class TrickleIndexer:
    """Background indexer that processes files one at a time.

    Parameters
    ----------
    settings:
        Application settings with indexing paths, exclude, pause config.
    pipeline:
        The IndexingPipeline instance (shared with DotMDService).
        Optional at construction time; must be set before calling ``run()``.
    """

    def __init__(
        self,
        settings: Settings,
        pipeline: IndexingPipeline | None = None,
    ) -> None:
        self._settings = settings
        self._pipeline = pipeline
        self._state = TrickleState()
        self._file_queue: asyncio.Queue[str] = asyncio.Queue()
        self._observer: Observer | None = None
        self._needs_vacuum: bool = False

    @property
    def state(self) -> TrickleState:
        """Return current indexer state (read by status endpoint)."""
        return self._state

    async def run(self, shutdown: asyncio.Event) -> None:
        """Main entry point: process backlog, then watch for new files.

        Acquires an exclusive file lock for the entire session so that
        CLI commands (``dotmd index --force``, ``dotmd reset``) cannot
        run concurrently.  To use those commands, stop the server first.

        Parameters
        ----------
        shutdown:
            Event set by the server lifespan to signal graceful shutdown.
        """
        if not self._settings.indexing_paths:
            logger.info("Trickle indexer idle — no indexing_paths in config")
            self._state.status = TrickleStatus.IDLE
            await shutdown.wait()
            return

        # Lock must be acquired before any indexing work.  flock is a
        # synchronous syscall — safe to call directly in an async function.
        with indexing_lock(self._settings.index_dir):
            await self._run_locked(shutdown)

    async def _run_locked(self, shutdown: asyncio.Event) -> None:
        """Body of run(), executed while holding the indexing lock."""
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
            await self._run_index_loop(shutdown)
        except Exception:
            logger.exception("Trickle indexer crashed")
        finally:
            self._stop_observer()
            self._state.status = TrickleStatus.STOPPING
            logger.info(
                "Trickle indexer stopped (indexed %d files)",
                self._state.indexed_count,
            )

    async def _run_index_loop(self, shutdown: asyncio.Event) -> None:
        """Core index loop: startup checks, backlog, watch mode.

        Extracted as a separate method so tests can patch it to verify
        that the startup lock check runs before any indexing work begins.
        """
        # Startup health checks
        await self._startup_checks()
        if shutdown.is_set():
            return

        # Start the inotify observer BEFORE backlog so that any files written
        # during backlog scan are queued via inotify and picked up by the drain
        # loop in watch mode.  Without this, files created in the window
        # between discovery and observer start are missed by both, and only
        # caught by the next polling fallback (up to poll_interval_seconds
        # later).  Re-discovery is harmless: content-checksum dedup ensures
        # already-indexed files are skipped on the second pass.
        self._start_observer()

        # Phase 1: Process existing backlog
        await self._process_backlog(shutdown)
        if shutdown.is_set():
            return

        # Phase 2: Watch mode (observer already running)
        await self._watch_mode(shutdown)

    # ------------------------------------------------------------------
    # Startup checks (integrity + orphan cleanup)
    # ------------------------------------------------------------------

    async def _startup_checks(self) -> None:
        """Run integrity check and orphan cleanup at startup."""
        # 1. PRAGMA integrity_check — early corruption detection
        try:
            result = await asyncio.to_thread(
                lambda: self._pipeline.conn.execute(
                    "PRAGMA integrity_check"
                ).fetchone(),
            )
            if result and result[0] != "ok":
                logger.error(
                    "SQLite integrity check FAILED: %s — continuing anyway",
                    result[0],
                )
            else:
                logger.info("SQLite integrity check: ok")
        except Exception:
            logger.exception("SQLite integrity check error — continuing anyway")

        # 2. Orphan cleanup — remove indexed data for files no longer on disk
        try:
            from dotmd.ingestion.reader import discover_files_multi

            all_files = await asyncio.to_thread(
                discover_files_multi,
                self._settings.indexing_paths,
                self._settings.effective_indexing_exclude,
            )
            discovered_paths = {str(fi.path) for fi in all_files}
            logger.info(
                "Orphan cleanup: checking %d discovered files against index...",
                len(discovered_paths),
            )

            files_rm, chunks_rm, vecs_rm = await asyncio.to_thread(
                self._pipeline.purge_orphaned_files, discovered_paths,
            )
            if files_rm:
                logger.info(
                    "Orphan cleanup: removed %d files (%d chunks, %d vectors)",
                    files_rm, chunks_rm, vecs_rm,
                )
                self._needs_vacuum = True
            else:
                logger.info("Orphan cleanup: no orphans found")
        except Exception:
            logger.exception("Orphan cleanup failed — continuing anyway")

    # ------------------------------------------------------------------
    # Backlog processing
    # ------------------------------------------------------------------

    async def _process_backlog(self, shutdown: asyncio.Event) -> None:
        """Discover and process all unindexed files (newest first)."""
        self._state.status = TrickleStatus.BACKLOG
        logger.info(
            "Discovering unindexed files from %d paths...",
            len(self._settings.indexing_paths),
        )

        # Discover all files from configured paths
        from dotmd.ingestion.reader import discover_files_multi

        all_files = await asyncio.to_thread(
            discover_files_multi,
            self._settings.indexing_paths,
            self._settings.effective_indexing_exclude,
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
        n_queued = len(diff.new) + len(diff.modified)
        if n_queued > 0:
            basenames = [fi.path.name for fi in unindexed]
            if n_queued < 8:
                queued_str = ", ".join(basenames)
            else:
                queued_str = ", ".join(basenames[:5]) + f", ... and {n_queued - 5} more"
            logger.info(
                "Backlog: %d new, %d modified, %d deleted, %d unchanged, %d total"
                " — queued: %s",
                len(diff.new),
                len(diff.modified),
                len(diff.deleted),
                len(diff.unchanged),
                len(all_files),
                queued_str,
            )
        else:
            last_act = (
                self._state.last_indexed_at.strftime("%Y-%m-%dT%H:%M:%SZ")
                if self._state.last_indexed_at
                else "never"
            )
            logger.info(
                "Backlog: idle (%d indexed, last activity %s)",
                len(diff.unchanged),
                last_act,
            )

        if not unindexed:
            return

        succeeded = 0
        failed = 0
        self._state._start_time = time.monotonic()
        self._state.indexed_count = 0
        self._state.total_chunks_done = 0
        self._state.files_per_hour = 0.0
        self._state.chunks_per_hour = 0.0
        self._state.eta_minutes = None

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
            self._state.last_indexed_at = datetime.now(UTC)
            self._update_eta(i + 1, len(unindexed))

            elapsed = time.monotonic() - self._state._start_time
            if self._state.eta_minutes is not None:
                eta_seconds = self._state.eta_minutes * 60
                eta_str = f", ETA ~{_format_duration(eta_seconds)}"
            else:
                eta_str = ", ETA: estimating..."
            rate_str = ""
            if self._state.chunks_per_hour > 0:
                rate_str = (
                    f" @ {_format_rate(self._state.chunks_per_hour, 'chunks')}"
                    f", {_format_rate(self._state.files_per_hour, 'files')}"
                )
            logger.info(
                "[%d/%d] %d chunks in %s%s%s",
                succeeded,
                len(unindexed),
                self._state.total_chunks_done,
                _format_duration(elapsed),
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
        """Watch configured paths for new files via inotify + polling fallback.

        The watchdog Observer is started by _run_index_loop BEFORE backlog so
        inotify events accumulate in _file_queue while backlog runs.  The drain
        loop below picks them up on the first iteration here.
        """
        self._state.status = TrickleStatus.WATCHING
        logger.info(
            "Entering watch mode (poll interval: %ds)",
            int(self._settings.poll_interval_seconds),
        )

        while not shutdown.is_set():
            # Process any files queued by watchdog events
            while not self._file_queue.empty():
                # Initialise before try so the outer except can reference it
                # safely even if get_nowait() raises (shouldn't, given the
                # empty() guard, but pyright cannot infer that invariant).
                path_str: str = "<unknown>"
                try:
                    path_str = self._file_queue.get_nowait()
                    file_path = Path(path_str)

                    # File deleted — purge from all stores
                    if not file_path.exists():
                        try:
                            await asyncio.to_thread(
                                self._pipeline._purge_file, path_str,
                            )
                            logger.info(
                                "Watch: purged deleted %s", Path(path_str).name,
                            )
                            self._needs_vacuum = True
                        except Exception:
                            logger.exception(
                                "Watch: failed to purge %s", path_str,
                            )
                        continue

                    if not file_path.is_file():
                        continue

                    stat = file_path.stat()
                    fi = FileInfo(
                        path=file_path,
                        title=file_path.stem,
                        last_modified=datetime.fromtimestamp(
                            stat.st_mtime, tz=UTC
                        ),
                        size_bytes=stat.st_size,
                    )
                    self._state.current_file = path_str
                    try:
                        await asyncio.to_thread(self._process_one_file, fi)
                        self._state.indexed_count += 1
                        self._state.last_indexed_at = datetime.now(UTC)
                        logger.info("Watch: indexed %s", file_path.name)
                    finally:
                        self._state.current_file = None
                except Exception:
                    logger.exception("Watch: failed to index %s", path_str)

            # Deferred maintenance: run when idle, after deletions.
            # Order matters — DELETE all orphans BEFORE VACUUM so the freed
            # pages are reclaimed in a single pass:
            #   1. Graph orphan sweep   (drops isolated graph nodes)
            #   2. extraction_cache prune (drops cache rows for removed chunks)
            #   3. VACUUM                (compacts DB file)
            if self._needs_vacuum:
                try:
                    await asyncio.to_thread(self._pipeline.sweep_graph_orphans)
                except Exception:
                    logger.exception("Graph orphan sweep failed")
                try:
                    await asyncio.to_thread(self._pipeline.prune_extraction_cache)
                except Exception:
                    logger.exception("Extraction cache prune failed")
                try:
                    logger.info("Running VACUUM (deferred)")
                    await asyncio.to_thread(
                        self._pipeline.conn.execute, "VACUUM",
                    )
                    self._needs_vacuum = False
                    logger.info("VACUUM complete")
                except Exception:
                    logger.exception("VACUUM failed — will retry next idle")

            # Wait for: shutdown OR queue item OR poll interval timeout.
            # Earlier versions awaited only shutdown.wait() with a long timeout,
            # which left inotify-queued files sitting in _file_queue for up to
            # poll_interval_seconds before the drain loop ran again.  Watching
            # the queue here lets watchdog events wake us within milliseconds.
            shutdown_task = asyncio.create_task(shutdown.wait())
            queue_task = asyncio.create_task(self._file_queue.get())
            try:
                done, _ = await asyncio.wait(
                    {shutdown_task, queue_task},
                    timeout=self._settings.poll_interval_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                for t in (shutdown_task, queue_task):
                    if not t.done():
                        t.cancel()

            if shutdown_task in done:
                return
            if queue_task in done:
                # Re-enqueue so the drain loop at the top of the next iteration
                # processes it (keeps a single drain code path).
                self._file_queue.put_nowait(queue_task.result())
                continue

            # Polling fallback: timeout fired with no queue activity.
            # _process_backlog logs at INFO when it finds files; only this
            # entry-point line stays at DEBUG to avoid polluting steady-state.
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

        Two-line-per-file steady state (Fix 2):
          1. ``pipeline: {basename} DONE N chunks X.Xs (...)``  — emitted by pipeline._index_file
          2. ``{basename} — N chunks, X.Xs``                    — emitted here (only when n_chunks > 0)
        No other INFO lines are emitted per file from this method.
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
            loop, self._file_queue, self._settings.effective_indexing_exclude
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
        """Update throughput rates and ETA.

        ETA is suppressed until at least 3 files have been processed AND
        at least 120 seconds have elapsed, to avoid wildly inflated early estimates.
        """
        elapsed = time.monotonic() - self._state._start_time
        if elapsed > 0 and files_done > 0:
            self._state.files_per_hour = files_done / (elapsed / 3600)
            if self._state.total_chunks_done > 0:
                self._state.chunks_per_hour = self._state.total_chunks_done / (elapsed / 3600)
            # Suppress ETA until sample is large enough to be meaningful
            if files_done >= 3 and elapsed >= 120:
                remaining = files_total - files_done
                if self._state.files_per_hour > 0:
                    self._state.eta_minutes = remaining / (self._state.files_per_hour / 60)
            else:
                self._state.eta_minutes = None  # "estimating..."
