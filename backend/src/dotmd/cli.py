"""CLI interface for dotMD — thin wrapper over DotMDService."""

from __future__ import annotations

import sys
import time
from datetime import UTC
from pathlib import Path

import click

from dotmd.api.service import DotMDService
from dotmd.auth import DotMDOAuthProvider
from dotmd.core.config import load_settings
from dotmd.core.exceptions import IndexingLockError
from dotmd.core.models import SearchMode, TrickleStatus
from dotmd.feedback import FeedbackStore
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
    settings = load_settings(**overrides)
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
    "--force",
    "-f",
    is_flag=True,
    default=False,
    help="Force full re-index, bypassing incremental change detection.",
)
@click.pass_context
def index(
    ctx: click.Context, directory: Path, extract_depth: str, entity_types: str | None, force: bool
) -> None:
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
        raise SystemExit(1) from None
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
@click.option("--reranker", default=None, help="Reranker name to use.")
@click.pass_context
def search(
    ctx: click.Context,
    query: str,
    top: int,
    mode: str,
    no_rerank: bool,
    no_expand: bool,
    reranker: str | None,
) -> None:
    """Search the indexed knowledgebase."""
    service = _get_service_from_ctx(ctx)
    try:
        results = service.search(
            query=query,
            top_k=top,
            mode=mode,
            rerank=not no_rerank,
            expand=not no_expand,
            reranker_name=reranker,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    candidates = results.candidates
    if not candidates:
        click.echo("No results found.")
        return

    for i, r in enumerate(candidates, 1):
        click.echo(f"\n{'─' * 60}")
        click.echo(f"  [{i}] {r.ref}")
        if r.heading_path:
            click.echo(f"      {r.heading_path}")
        click.echo(f"      Score: {r.fused_score:.4f}  Engines: {', '.join(r.matched_engines)}")
        click.echo(f"      {r.snippet}")


@main.group("rerank")
def rerank_group() -> None:
    """Developer reranker diagnostics."""


@rerank_group.command("compare")
@click.argument("query")
@click.option("--rerankers", default=None, help="Comma-separated reranker names.")
@click.option("--top", "-n", default=10, help="Number of candidates to report.")
@click.option(
    "--mode",
    type=click.Choice([m.value for m in SearchMode]),
    default="hybrid",
)
@click.option("--no-expand", is_flag=True, help="Skip query expansion.")
@click.pass_context
def compare(
    ctx: click.Context,
    query: str,
    rerankers: str | None,
    top: int,
    mode: str,
    no_expand: bool,
) -> None:
    """Compare reranker diagnostics over one shared candidate pool."""
    service = _get_service_from_ctx(ctx)
    names = [name.strip() for name in rerankers.split(",") if name.strip()] if rerankers else None
    try:
        comparison = service.compare_rerankers(
            query=query,
            reranker_names=names,
            top_k=top,
            mode=mode,
            expand=not no_expand,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"Shared pool: {comparison['shared_pool_size']} candidates")
    for run in comparison["rerankers"]:
        top_ids = ", ".join(run["top_chunk_ids"]) or "none"
        scores = ", ".join(f"{score:.4f}" for score in run["scores"]) or "none"
        row = (
            f"{run['name']} model={run['model_name']} "
            f"elapsed_ms={run['elapsed_ms']:.1f} "
            f"elapsed={run['elapsed']} "
            f"load_ms={run['load_ms']:.1f} "
            f"load={run['load']} "
            f"rerank_ms={run['rerank_ms']:.1f} "
            f"rerank={run['rerank']} "
            f"returned_count={run['returned_count']} "
            f"top_chunk_ids={top_ids} scores={scores}"
        )
        if run["error"]:
            row += f" ERROR: {run['error']}"
        click.echo(row)
    reference = comparison["overlap_reference"] or "none"
    click.echo(f"Overlap reference: {reference}")
    click.echo(f"Overlap: {comparison['overlap']}")


@main.command()
@click.option("--verbose", "-V", is_flag=True, help="Show per-strategy/model table details.")
@click.pass_context
def status(ctx: click.Context, verbose: bool) -> None:
    """Show index statistics."""
    service = _get_service_from_ctx(ctx)
    stats = service.status()

    click.echo(f"Files:    {stats.total_files}")
    click.echo(f"Chunks:   {stats.total_chunks}")
    click.echo(f"Entities: {stats.total_entities}")
    click.echo(f"Edges:    {stats.total_edges}")
    # Graph backend info
    settings = load_settings()
    if settings.graph_backend == "falkordb":
        click.echo(f"Graph:    falkordb @ {settings.falkordb_url}/dotmd")
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
                strategy = name[len("chunks_") :]
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
                suffix = name[len("vec_meta_") :]
                # suffix is {strategy}_{model} — find the split point
                # by matching against known strategies
                for strategy in strategies:
                    prefix = strategy + "_"
                    if suffix.startswith(prefix):
                        model = suffix[len(prefix) :]
                        count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
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
                chunks_per_second = stats.trickle_chunks_per_hour / 3600
                files_per_second = (stats.trickle_files_per_hour or 0.0) / 3600
                rate = f" @ {chunks_per_second:.2f} chunks/s ({files_per_second:.2f} files/s)"
            eta = ""
            if stats.trickle_eta_minutes is not None:
                if stats.trickle_eta_minutes < 60:
                    eta = f", ETA ~{stats.trickle_eta_minutes:.0f}min"
                else:
                    hours = stats.trickle_eta_minutes / 60
                    eta = f", ETA ~{hours:.1f}hr"
            click.echo(f"Background: indexing{progress}{rate}{eta}")
        elif stats.trickle_status == TrickleStatus.WATCHING:
            click.echo(
                f"Background: watching for new files (indexed {stats.trickle_indexed or 0} total)"
            )
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
        raise SystemExit(1) from None
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
        raise SystemExit(1) from None
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
        raise SystemExit(1) from None
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
        raise SystemExit(1) from None
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
        raise SystemExit(1) from None
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
        raise SystemExit(1) from None
    click.echo(f"Dropped strategy '{name}' and all associated data.")


@main.group()
def telegram() -> None:
    """Telegram source smoke commands."""


@telegram.command("ingest")
@click.option("--limit", default=100, show_default=True, help="Maximum source units to request.")
@click.option("--dry-run", is_flag=True, help="Fetch one source batch without writing dotMD state.")
@click.option("--single-batch/--loop", default=True, help="Run exactly one provider batch.")
@click.pass_context
def telegram_ingest(
    ctx: click.Context,
    limit: int,
    dry_run: bool,
    single_batch: bool,
) -> None:
    """Run a bounded Telegram source ingest smoke."""
    if limit <= 0:
        raise click.BadParameter("limit must be positive", param_hint="--limit")
    if not single_batch:
        raise click.ClickException("Loop mode is not implemented in Phase 29; use --single-batch")

    index_dir = (ctx.obj or {}).get("index_dir")
    overrides: dict[str, object] = {}
    if index_dir is not None:
        overrides["index_dir"] = index_dir
    settings = load_settings(**overrides)
    socket_path = settings.telegram_daemon_socket
    if socket_path is None:
        raise click.ClickException("Telegram daemon socket is not configured")
    if not socket_path.exists():
        raise click.ClickException(f"Telegram daemon socket does not exist: {socket_path}")
    if not socket_path.is_socket():
        raise click.ClickException(f"Telegram daemon socket is not a socket: {socket_path}")

    service = DotMDService(settings=settings)
    bundle = service._pipeline.source_runtime_factory.build("telegram")
    provider = bundle.provider
    if provider is None:
        raise click.ClickException("Telegram lifecycle runtime has no provider")
    if dry_run:
        description = provider.describe_source()
        batch = provider.export_changes(None, limit)
        click.echo(
            "telegram_ingest "
            f"dry_run=true single_batch=true namespace={description.namespace} "
            f"discovered={len(batch.changes)} "
            f"next_cursor={batch.next_cursor or ''} "
            f"checkpoint_cursor={batch.checkpoint_cursor or ''}"
        )
        return

    result = service._pipeline.ingest_application_source_runtime(bundle, limit=limit)
    click.echo(
        "telegram_ingest "
        "dry_run=false single_batch=true "
        f"discovered={result.discovered} "
        f"new_units={result.new_units} "
        f"changed_units={result.changed_units} "
        f"rebound_units={result.rebound_units} "
        f"skipped_units={result.skipped_units} "
        f"hidden_units={result.hidden_units} "
        f"failed_units={result.failed_units} "
        f"reused_units={result.reused_units}"
    )


@telegram.command("reset-index")
@click.option("--yes", is_flag=True, help="Confirm deletion of indexed Telegram state.")
@click.pass_context
def telegram_reset_index(ctx: click.Context, yes: bool) -> None:
    """Delete indexed Telegram state so the next ingest recomputes it."""
    if not yes:
        raise click.ClickException("Refusing to reset Telegram index without --yes")

    index_dir = (ctx.obj or {}).get("index_dir")
    overrides: dict[str, object] = {}
    if index_dir is not None:
        overrides["index_dir"] = index_dir
    settings = load_settings(**overrides)
    service = DotMDService(settings=settings)
    result = service._pipeline.purge_application_source("telegram")
    click.echo(
        "telegram_reset_index "
        f"namespace={result.namespace} "
        f"chunks_deleted={result.chunks_deleted} "
        f"source_units_deleted={result.source_units_deleted} "
        f"documents_deleted={result.documents_deleted} "
        f"bindings_deleted={result.bindings_deleted} "
        f"checkpoints_deleted={result.checkpoints_deleted} "
        f"vec_components_deleted={result.vec_components_deleted}"
    )


@main.command()
@click.option("--host", default="127.0.0.1", help="Bind host.")
@click.option("--port", "-p", default=8000, help="Bind port.")
def serve(host: str, port: int) -> None:
    """Start the REST API server."""
    from dotmd.api.server import main as run_server

    click.echo(f"Starting dotMD API on {host}:{port}")
    run_server(host=host, port=port)


@main.command()
@click.option(
    "--transport",
    default="stdio",
    type=click.Choice(["stdio", "streamable-http"]),
    help="MCP transport.",
)
@click.option("--host", default="0.0.0.0", help="Bind host (streamable-http only).")
@click.option("--port", "-p", default=8080, help="Bind port (streamable-http only).")
def mcp(transport: str, host: str, port: int) -> None:
    """Start the MCP (Model Context Protocol) server."""
    import asyncio

    click.echo(f"Starting dotMD MCP server ({transport})...", err=True)

    if transport == "streamable-http":
        import uvicorn

        from dotmd.mcp_server import create_app
        from dotmd.mcp_server import mcp as mcp_app
        from dotmd.utils.logging import setup_logging

        # FastMCP.__init__ installs a RichHandler on the root logger at import
        # time. Reconfigure now so all loggers use a consistent format.
        setup_logging()

        mcp_app.settings.host = host
        mcp_app.settings.port = port
        app = create_app()
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level=mcp_app.settings.log_level.lower(),
            access_log=False,
            log_config=None,  # don't let uvicorn override our logging setup
        )
        asyncio.run(uvicorn.Server(config).serve())
    else:
        from dotmd.mcp_server import _init_for_stdio
        from dotmd.mcp_server import mcp as mcp_app
        from dotmd.utils.logging import setup_logging

        setup_logging()
        _init_for_stdio()
        mcp_app.run(transport="stdio")


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
# feedback command group
# ---------------------------------------------------------------------------


def _get_feedback_store(ctx: click.Context) -> FeedbackStore:
    index_dir = (ctx.obj or {}).get("index_dir")
    if index_dir is None:
        index_dir = load_settings().index_dir
    return FeedbackStore(Path(index_dir) / "feedback.db")


def _parse_duration(value: str) -> int:
    text = value.strip().lower()
    if not text:
        raise click.BadParameter("duration must not be empty")
    unit = text[-1]
    number_text = text[:-1] if unit.isalpha() else text
    multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(unit, 1)
    try:
        number = float(number_text)
    except ValueError as exc:
        raise click.BadParameter("duration must be a number with optional s/m/h/d suffix") from exc
    seconds = int(number * multiplier)
    if seconds <= 0:
        raise click.BadParameter("duration must be positive")
    return seconds


# ---------------------------------------------------------------------------
# OAuth command group
# ---------------------------------------------------------------------------


@main.group()
def oauth() -> None:
    """Manage OAuth pairing for hosted MCP clients."""


@oauth.group("code")
def oauth_code() -> None:
    """Manage one-time OAuth pairing codes."""


@oauth_code.command("create")
@click.option("--ttl", default="10m", help="Code lifetime, e.g. 60s, 10m, 2h. Default: 10m.")
@click.pass_context
def oauth_code_create(ctx: click.Context, ttl: str) -> None:
    """Create a one-time code for pairing a hosted MCP client."""
    import asyncio

    index_dir = (ctx.obj or {}).get("index_dir")
    if index_dir is None:
        index_dir = Path.home() / ".dotmd"
    provider = DotMDOAuthProvider(Path(index_dir) / "oauth_state.json")
    ttl_seconds = _parse_duration(ttl)
    code, expires_at = asyncio.run(provider.create_pairing_code(ttl_seconds=ttl_seconds))
    expires = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(expires_at))
    click.echo(code)
    click.echo(f"Expires: {expires}")


@main.group()
def feedback() -> None:
    """Review and manage agent feedback submissions."""


@feedback.command("list")
@click.option("--limit", "-n", default=50, help="Maximum rows to show.")
@click.option("--all", "show_all", is_flag=True, help="Include done and dismissed entries.")
@click.pass_context
def feedback_list(ctx: click.Context, limit: int, show_all: bool) -> None:
    """List open feedback submissions (newest first).

    By default shows only open and in_progress entries.
    Use --all to include done and dismissed history.
    """
    import datetime

    store = _get_feedback_store(ctx)
    rows = store.list_all(limit=limit, include_closed=show_all)

    if not rows:
        if show_all:
            click.echo("No feedback submissions found.")
        else:
            click.echo("No open or in-progress feedback. Use --all to show history.")
        return

    for row in rows:
        ts = datetime.datetime.fromtimestamp(row["submitted_at"], tz=UTC).strftime("%Y-%m-%d %H:%M")
        severity = f"[{row['severity']}]" if row["severity"] else "[?]"
        status = f"[{row['status']}]"
        meta = f"id={row['id']} {severity} {status} {ts}"
        if row.get("model"):
            meta += f" model={row['model']}"
        if row.get("harness"):
            meta += f" harness={row['harness']}"
        click.echo(meta)
        click.echo(f"  message: {row['message']}")
        if row.get("context"):
            click.echo(f"  context: {row['context']}")
        if row.get("status_comment"):
            click.echo(f"  status_comment: {row['status_comment']}")
        click.echo()


@feedback.command("status")
@click.argument("feedback_id", type=int)
@click.argument(
    "new_status", metavar="STATUS", type=click.Choice(["open", "in_progress", "done", "dismissed"])
)
@click.option("--reason", default=None, help="Optional reason for the status change.")
@click.pass_context
def feedback_status(
    ctx: click.Context, feedback_id: int, new_status: str, reason: str | None
) -> None:
    """Update the status of a feedback entry.

    STATUS must be one of: open, in_progress, done, dismissed.
    """
    store = _get_feedback_store(ctx)
    if store.set_status(feedback_id, new_status, reason):
        click.echo(f"Feedback {feedback_id} → {new_status}")
    else:
        click.echo(f"Feedback {feedback_id} not found.", err=True)
        raise SystemExit(1) from None


@feedback.command("delete")
@click.argument("feedback_id", type=int)
@click.pass_context
def feedback_delete(ctx: click.Context, feedback_id: int) -> None:
    """Permanently delete a feedback entry."""
    store = _get_feedback_store(ctx)
    if store.delete(feedback_id):
        click.echo(f"Feedback {feedback_id} deleted.")
    else:
        click.echo(f"Feedback {feedback_id} not found.", err=True)
        raise SystemExit(1) from None
