"""CLI interface for dotMD — thin wrapper over DotMDService."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from dotmd.api.service import DotMDService
from dotmd.core.config import Settings
from dotmd.core.exceptions import IndexingLockError
from dotmd.core.models import SearchMode, TrickleStatus
from dotmd.utils.logging import setup_logging


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging.")
@click.option(
    "--index-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Override index storage directory (default: ~/.dotmd).",
    envvar="DOTMD_INDEX_DIR",
)
@click.pass_context
def main(ctx: click.Context, verbose: bool, index_dir: Path | None) -> None:
    """dotMD — Search your markdown knowledgebase.

    In normal operation, the background trickle indexer (started with
    'serve') detects new, modified, and deleted files automatically.
    Manual indexing commands are only needed for development and debugging.
    """
    setup_logging(verbose=verbose)
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["index_dir"] = index_dir


def _get_service(**overrides: object) -> DotMDService:
    settings = Settings(**overrides)  # type: ignore[arg-type]
    return DotMDService(settings=settings)


def _get_service_from_ctx(ctx: click.Context, **overrides: object) -> DotMDService:
    """Build DotMDService, applying --index-dir from context if set."""
    index_dir = (ctx.obj or {}).get("index_dir")
    if index_dir is not None:
        overrides.setdefault("index_dir", index_dir)
    return _get_service(**overrides)


@main.command()
@click.argument("directory", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--extract-depth",
    type=click.Choice(["structural", "ner"]),
    default="ner",
    help="Extraction depth for graph building.",
)
@click.option(
    "--entity-types",
    default=None,
    help="Comma-separated GLiNER entity types (e.g. 'person,technology,concept').",
)
@click.option(
    "--force", "-f",
    is_flag=True,
    default=False,
    help="Force full re-index, bypassing incremental change detection.",
)
@click.pass_context
def index(ctx: click.Context, directory: Path, extract_depth: str, entity_types: str | None, force: bool) -> None:
    """Index all markdown files in DIRECTORY.

    DEV ONLY — in production, trickle indexer handles this automatically.
    Use for one-off debugging or after schema changes that require a full rebuild.
    """
    overrides: dict[str, object] = {"extract_depth": extract_depth}
    if entity_types:
        overrides["ner_entity_types"] = [t.strip() for t in entity_types.split(",")]

    service = _get_service(**overrides)
    mode_label = "full re-index" if force else "incremental"
    click.echo(f"Indexing {directory} ({mode_label})...")
    try:
        stats = service.index(directory, force=force)
    except IndexingLockError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    click.echo(
        f"{stats.new_files} new, {stats.modified_files} modified, "
        f"{stats.deleted_files} deleted, {stats.unchanged_files} unchanged"
    )
    click.echo(
        f"Done. {stats.total_files} files, {stats.total_chunks} chunks, "
        f"{stats.total_entities} entities, {stats.total_edges} edges."
    )


@main.command()
@click.argument("query")
@click.option("--top", "-n", default=10, help="Number of results to return.")
@click.option(
    "--mode",
    type=click.Choice([m.value for m in SearchMode]),
    default="hybrid",
    help="Search mode.",
)
@click.option("--no-rerank", is_flag=True, help="Skip cross-encoder reranking.")
@click.option("--no-expand", is_flag=True, help="Skip query expansion.")
@click.pass_context
def search(ctx: click.Context, query: str, top: int, mode: str, no_rerank: bool, no_expand: bool) -> None:
    """Search the indexed knowledgebase."""
    service = _get_service_from_ctx(ctx, read_only=True)
    results = service.search(
        query=query,
        top_k=top,
        mode=mode,
        rerank=not no_rerank,
        expand=not no_expand,
    )

    if not results:
        click.echo("No results found.")
        return

    for i, r in enumerate(results, 1):
        click.echo(f"\n{'─' * 60}")
        # Phase 16 P5: render file_paths list (locked format — Review-LOW-11)
        # Single holder: [i] path
        # Multi holder:  [i] path_0  (+N-1 more: path_1, path_2, …)
        paths = sorted(r.file_paths)  # validator already sorts, defensive re-sort
        if len(paths) == 0:
            path_line = f"  [{i}] (no path)"
        elif len(paths) == 1:
            path_line = f"  [{i}] {paths[0]}"
        else:
            rest = ", ".join(str(p) for p in paths[1:])
            path_line = f"  [{i}] {paths[0]}  (+{len(paths) - 1} more: {rest})"
        click.echo(path_line)
        if r.heading_path:
            click.echo(f"      {r.heading_path}")
        click.echo(f"      Score: {r.fused_score:.4f}  Engines: {', '.join(r.matched_engines)}")
        click.echo(f"      {r.snippet}")


@main.command()
@click.option("--verbose", "-V", is_flag=True, help="Show per-strategy/model table details.")
@click.pass_context
def status(ctx: click.Context, verbose: bool) -> None:
    """Show index statistics."""
    service = _get_service_from_ctx(ctx, read_only=True)
    stats = service.status()

    click.echo(f"Files:    {stats.total_files}")
    click.echo(f"Chunks:   {stats.total_chunks}")
    click.echo(f"Entities: {stats.total_entities}")
    click.echo(f"Edges:    {stats.total_edges}")
    # Graph backend info
    settings = Settings()
    if settings.graph_backend == "falkordb":
        click.echo(f"Graph:    falkordb @ {settings.falkordb_url}/{settings.falkordb_graph_name}")
    else:
        click.echo(f"Graph:    ladybugdb @ {settings.graph_db_path}")
    if stats.last_indexed:
        click.echo(f"Last indexed: {stats.last_indexed.isoformat()}")
    if stats.data_dir:
        if stats.new_files or stats.modified_files or stats.deleted_files:
            click.echo(
                f"Pending: {stats.new_files} new, {stats.modified_files} modified, "
                f"{stats.deleted_files} deleted since last index"
            )
        else:
            click.echo("No changes detected since last index.")

    # Verbose: per-strategy and per-model table details
    if verbose:
        conn = service._pipeline.conn
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()

        # Collect strategies from chunks_* tables
        # Phase 16 P5: file count from chunk_file_paths_* M2M table (not chunks_* file_path column)
        strategies: dict[str, tuple[int, int]] = {}  # strategy -> (chunks, files)
        for (name,) in rows:
            if name.startswith("chunks_") and not name.startswith("chunks_fts_"):
                strategy = name[len("chunks_"):]
                count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                m2m_table = f"chunk_file_paths_{strategy}"
                try:
                    files = conn.execute(
                        f"SELECT COUNT(DISTINCT file_path) FROM {m2m_table}"
                    ).fetchone()[0]
                except Exception:
                    files = 0
                strategies[strategy] = (count, files)

        if strategies:
            click.echo("")
            click.echo("Strategies:")
            for strategy, (chunks, files) in sorted(strategies.items()):
                click.echo(f"  {strategy}: {chunks} chunks, {files} files")

        # Collect models from vec_meta_* tables
        models: dict[tuple[str, str], int] = {}  # (strategy, model) -> vectors
        for (name,) in rows:
            if name.startswith("vec_meta_"):
                suffix = name[len("vec_meta_"):]
                # suffix is {strategy}_{model} — find the split point
                # by matching against known strategies
                for strategy in strategies:
                    prefix = strategy + "_"
                    if suffix.startswith(prefix):
                        model = suffix[len(prefix):]
                        count = conn.execute(
                            f"SELECT COUNT(*) FROM {name}"
                        ).fetchone()[0]
                        models[(strategy, model)] = count
                        break

        if models:
            click.echo("")
            click.echo("Models per strategy:")
            for (strategy, model), vectors in sorted(models.items()):
                click.echo(f"  {strategy} / {model}: {vectors} vectors")

    # Trickle indexer progress
    if stats.trickle_status and stats.trickle_status != TrickleStatus.IDLE:
        click.echo("")  # blank line separator
        if stats.trickle_status == TrickleStatus.BACKLOG:
            progress = ""
            if stats.trickle_total and stats.trickle_total > 0:
                progress = f" ({stats.trickle_indexed or 0}/{stats.trickle_total} files)"
            rate = ""
            if stats.trickle_chunks_per_hour:
                rate = f" @ {stats.trickle_chunks_per_hour:.0f} chunks/hr ({stats.trickle_files_per_hour:.0f} files/hr)"
            eta = ""
            if stats.trickle_eta_minutes is not None:
                if stats.trickle_eta_minutes < 60:
                    eta = f", ETA ~{stats.trickle_eta_minutes:.0f}min"
                else:
                    hours = stats.trickle_eta_minutes / 60
                    eta = f", ETA ~{hours:.1f}hr"
            click.echo(f"Background: indexing{progress}{rate}{eta}")
        elif stats.trickle_status == TrickleStatus.WATCHING:
            click.echo(f"Background: watching for new files (indexed {stats.trickle_indexed or 0} total)")
        elif stats.trickle_status == TrickleStatus.STOPPING:
            click.echo("Background: shutting down...")

        if stats.trickle_current_file:
            click.echo(f"  Current: {stats.trickle_current_file}")


@main.group()
def reindex() -> None:
    """Rebuild a specific index from stored chunks.

    Metadata (chunks) is the source of truth — each subcommand
    rebuilds one derived store without re-reading files from disk.
    """


@reindex.command("vectors")
def reindex_vectors() -> None:
    """Rebuild vector embeddings (requires TEI)."""
    service = _get_service()
    click.echo("Rebuilding vector index...")
    try:
        n = service.reindex("vectors")
    except IndexingLockError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    click.echo(f"Done. {n} chunks re-embedded.")


@reindex.command("fts5")
def reindex_fts5() -> None:
    """Rebuild FTS5 keyword index."""
    service = _get_service()
    click.echo("Rebuilding FTS5 index...")
    try:
        n = service.reindex("fts5")
    except IndexingLockError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    click.echo(f"Done. {n} chunks re-indexed.")


@reindex.command("graph")
def reindex_graph() -> None:
    """Rebuild knowledge graph (runs extraction)."""
    service = _get_service()
    click.echo("Rebuilding knowledge graph...")
    try:
        n = service.reindex("graph")
    except IndexingLockError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    click.echo(f"Done. {n} chunks processed.")


@reindex.command("all")
def reindex_all() -> None:
    """Rebuild all derived indexes (vectors + FTS5 + graph)."""
    service = _get_service()
    click.echo("Rebuilding all indexes...")
    try:
        n = service.reindex("all")
    except IndexingLockError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    click.echo(f"Done. {n} chunks across all stores.")


@main.group()
def reset() -> None:
    """Drop model vectors or chunk strategy data."""


@reset.command("model")
@click.argument("name")
def reset_model(name: str) -> None:
    """Drop vectors and embed fingerprints for a model."""
    if not click.confirm(f"This will delete all vectors for model '{name}'. Continue?"):
        return
    service = _get_service()
    try:
        service.drop_vectors()
    except IndexingLockError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    click.echo(f"Dropped vectors for model '{name}'.")


@reset.command("strategy")
@click.argument("name")
def reset_strategy(name: str) -> None:
    """Drop ALL data for a chunk strategy (chunks, FTS5, graph, vectors)."""
    if not click.confirm(
        f"This will delete ALL data for strategy '{name}' including all vectors. Continue?"
    ):
        return
    service = _get_service()
    try:
        service.drop_chunks()
    except IndexingLockError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    click.echo(f"Dropped strategy '{name}' and all associated data.")


@main.command()
@click.option("--host", default="127.0.0.1", help="Bind host.")
@click.option("--port", "-p", default=8000, help="Bind port.")
def serve(host: str, port: int) -> None:
    """Start the REST API server."""
    from dotmd.api.server import main as run_server

    click.echo(f"Starting dotMD API on {host}:{port}")
    run_server(host=host, port=port)


@main.command()
def mcp() -> None:
    """Start the MCP (Model Context Protocol) server."""
    from dotmd.mcp_server import mcp as mcp_app

    click.echo("Starting dotMD MCP server...", err=True)
    mcp_app.run()


@main.command("mcp-config")
def mcp_config() -> None:
    """Print MCP client configuration JSON with absolute paths."""
    import json
    import shutil

    dotmd_bin = shutil.which("dotmd") or sys.executable
    config = {
        "dotmd": {
            "command": str(Path(dotmd_bin).resolve()),
            "args": ["mcp"],
        }
    }
    click.echo(json.dumps(config, indent=2))


# ---------------------------------------------------------------------------
# migrate command group (Phase 16 P2 — wave 6)
# ---------------------------------------------------------------------------

@main.group()
def migrate() -> None:
    """Schema migration tools for the Phase 16 M2M content-dedup upgrade.

    Run offline (container / trickle indexer must be stopped):

    \b
      dotmd migrate run              -- execute the migration
      dotmd migrate run --dry-run    -- preview: no writes, reports counts
      dotmd migrate run --verify-only -- invariant check without mutation
      dotmd migrate status           -- inspect current migration state

    Exit codes for 'migrate run':
      0 -- success (run, dry-run, or verify-only completed cleanly)
      1 -- invariant violation detected (--verify-only)
      2 -- lock contention or mutually-exclusive flag combination
      3 -- unexpected exception
      4 -- payload divergence without --allow-payload-divergence (Decision #10)
      5 -- hard integrity error (text mismatch across collision group)
    """


def _resolve_index_db(ctx: click.Context) -> Path:
    """Resolve the index.db path from --index-dir context or default Settings."""
    index_dir = (ctx.obj or {}).get("index_dir")
    if index_dir is not None:
        return Path(index_dir) / "index.db"
    settings = Settings()
    return settings.index_dir / "index.db"


@migrate.command("run")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help=(
        "Preview the migration without persisting any changes. "
        "Acquires the advisory lock (mode=dry-run), runs all steps inside a "
        "single ROLLBACK transaction, and reports collision counts, divergence "
        "stats, payload_mismatch counts, divergence-group count + top-5 example "
        "paths, and a disk delta estimate. DB bytes are identical before/after."
    ),
)
@click.option(
    "--verify-only",
    is_flag=True,
    default=False,
    help=(
        "Run invariant checks against the live DB without any mutation. "
        "Exits 1 if any invariant fails. "
        "Exits 4 if payload divergence groups are detected and "
        "--allow-payload-divergence was not passed. "
        "Exits 0 otherwise."
    ),
)
@click.option(
    "--allow-payload-divergence",
    is_flag=True,
    default=False,
    help=(
        "Proceed with canonical-keep when a collision group has diverging "
        "heading_hierarchy or level across holders. WITHOUT this flag, the "
        "migration aborts with exit 4 and writes `divergence_report.txt` to "
        "the run directory. WITH this flag, canonical (MIN old chunk_id) "
        "metadata is kept and the divergence is recorded in "
        "migration_v16_state for audit. See Decision #10 in CONTEXT.md."
    ),
)
@click.pass_context
def migrate_run(
    ctx: click.Context,
    dry_run: bool,
    verify_only: bool,
    allow_payload_divergence: bool,
) -> None:
    """Execute the Phase 16 schema migration.

    Exit codes:
      0 -- success
      1 -- invariant violation (--verify-only)
      2 -- lock contention or --dry-run + --verify-only combined
      3 -- unexpected exception
      4 -- payload divergence without --allow-payload-divergence
      5 -- hard integrity error (text mismatch across collision group)
    """
    from dotmd.ingestion import migration_v16 as _m16

    # --- Flag mutex: --dry-run and --verify-only are mutually exclusive ---
    if dry_run and verify_only:
        click.echo(
            "ERROR: --dry-run and --verify-only are mutually exclusive. "
            "Use 'dotmd migrate status' to inspect current state without "
            "acquiring the lock.",
            err=True,
        )
        sys.exit(2)

    index_db = _resolve_index_db(ctx)

    try:
        report = _m16.run_migration_v16(
            index_db,
            dry_run=dry_run,
            verify_only=verify_only,
            allow_payload_divergence=allow_payload_divergence,
        )
    except _m16.PayloadDivergenceBlocked as exc:
        click.echo(f"ABORT: {exc}", err=True)
        run_dir = index_db.parent
        click.echo(f"See {run_dir}/divergence_report.txt", err=True)
        click.echo(
            "Hint: re-run with --allow-payload-divergence to proceed with "
            "canonical-keep (Decision #10).",
            err=True,
        )
        sys.exit(4)
    except RuntimeError as exc:
        msg = str(exc)
        if "text mismatch" in msg or "HARD ERROR" in msg:
            click.echo(f"FATAL: {msg}", err=True)
            sys.exit(5)
        if "migration_v16_lock is held" in msg:
            click.echo(f"ERROR: {msg}", err=True)
            click.echo(
                "If the previous run was interrupted, run:\n"
                "  DELETE FROM migration_v16_lock WHERE id = 1",
                err=True,
            )
            sys.exit(2)
        click.echo(f"UNEXPECTED ERROR: {msg}", err=True)
        sys.exit(3)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"UNEXPECTED ERROR: {exc}", err=True)
        sys.exit(3)

    # --- verify-only: check invariant results ---
    if verify_only:
        # Surface payload divergence preview (Decision #10)
        preview = report.payload_divergence_preview or {}
        div_count = preview.get("count", 0)
        example_paths = preview.get("example_paths", [])

        if div_count > 0:
            click.echo(f"payload_divergence_groups={div_count}")
            if example_paths:
                click.echo("  example paths:")
                for p in example_paths:
                    click.echo(f"    {p}")
            if not allow_payload_divergence:
                click.echo(
                    f"\n{div_count} divergence group(s) detected. Migration will "
                    "ABORT without --allow-payload-divergence.\n"
                    "Re-run `dotmd migrate run --verify-only --allow-payload-divergence` "
                    "to suppress this warning, or re-run "
                    "`dotmd migrate run --allow-payload-divergence` to commit."
                )
                sys.exit(4)

        # Check for invariant failures (run_invariants was called inside run_migration_v16)
        # We don't have the InvariantReport directly on MigrationReport, so we
        # re-run invariants as a read-only check to produce the exit code.
        import sqlite3 as _sqlite3
        _conn = _sqlite3.connect(str(index_db))
        try:
            inv = _m16.run_invariants(_conn)
        finally:
            _conn.close()

        if not inv.passed:
            click.echo("INVARIANT FAILURES:", err=True)
            for check in inv.checks:
                if not check["passed"]:
                    click.echo(
                        f"  FAIL {check['name']}: {check.get('detail', '')}",
                        err=True,
                    )
            sys.exit(1)

        click.echo("verify-only: all invariants passed.")
        sys.exit(0)

    # --- dry-run: print report summary ---
    if dry_run:
        preview = report.payload_divergence_preview or {}
        div_count = preview.get("count", 0)
        example_paths = preview.get("example_paths", [])
        would_abort = div_count > 0 and not allow_payload_divergence

        click.echo(
            f"dry-run summary: collisions_collapsed={report.collisions_collapsed} "
            f"divergence_warnings={report.divergence_warnings} "
            f"payload_mismatch_warnings={report.payload_mismatch_warnings}"
        )
        click.echo(
            f"  payload_divergence_groups={div_count} "
            f"would_abort_without_flag={str(would_abort).lower()}"
        )
        if div_count > 0 and example_paths:
            click.echo(f"  example_paths={','.join(example_paths[:5])}")
        if report.disk_delta_estimate is not None:
            click.echo(f"  disk_delta_estimate={report.disk_delta_estimate} bytes")
        sys.exit(0)

    # --- normal run: print completion summary ---
    click.echo(
        f"Migration complete: "
        f"strategies={len(report.completed_strategies)} "
        f"collisions_collapsed={report.collisions_collapsed} "
        f"divergence_warnings={report.divergence_warnings} "
        f"payload_mismatch_warnings={report.payload_mismatch_warnings} "
        f"allow_payload_divergence={report.allow_payload_divergence}"
    )
    if report.skipped_strategies:
        click.echo(f"  skipped (already migrated): {report.skipped_strategies}")


@migrate.command("status")
@click.pass_context
def migrate_status(ctx: click.Context) -> None:
    """Inspect current migration state (read-only).

    Reports:
      - Whether migration is needed
      - Per-strategy progress (status, completed_at, collision counts)
      - Advisory lock state (held / clear)
    """
    from dotmd.ingestion import migration_v16 as _m16

    index_db = _resolve_index_db(ctx)

    try:
        report = _m16.status(index_db)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"ERROR reading migration status: {exc}", err=True)
        sys.exit(3)

    # Needs migration?
    if report.needs_migration:
        click.echo("needs migration: YES")
    else:
        click.echo("needs migration: NO")

    # Per-strategy state
    if report.per_strategy_state:
        click.echo("\nPer-strategy state:")
        for strategy, state in sorted(report.per_strategy_state.items()):
            status_val = state.get("status", "unknown")
            completed_at = state.get("completed_at", "")
            collisions = state.get("collisions_collapsed", 0)
            pm_warns = state.get("payload_mismatch_warnings", 0)
            allow_div = state.get("allow_payload_divergence", False)
            click.echo(
                f"  {strategy}: status={status_val} "
                f"completed_at={completed_at} "
                f"collisions_collapsed={collisions} "
                f"payload_mismatch_warnings={pm_warns} "
                f"allow_payload_divergence={allow_div}"
            )
    else:
        click.echo("No migration_v16_state rows found.")

    # Lock state
    if report.lock_held and report.lock_info:
        info = report.lock_info
        click.echo(
            f"\nAdvisory lock: HELD "
            f"locked_at={info.get('locked_at')} "
            f"pid={info.get('pid')} "
            f"host={info.get('host')} "
            f"mode={info.get('mode')}"
        )
        click.echo(
            "  To clear a stale lock: "
            "DELETE FROM migration_v16_lock WHERE id = 1"
        )
    else:
        click.echo("\nAdvisory lock: clear")


