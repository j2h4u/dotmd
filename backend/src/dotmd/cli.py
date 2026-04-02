"""CLI interface for dotMD — thin wrapper over DotMDService."""

from __future__ import annotations

from pathlib import Path

import click

from dotmd.api.service import DotMDService
from dotmd.core.config import Settings
from dotmd.core.exceptions import IndexingLockError
from dotmd.core.models import SearchMode
from dotmd.utils.logging import setup_logging


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging.")
@click.pass_context
def main(ctx: click.Context, verbose: bool) -> None:
    """dotMD — Search your markdown knowledgebase.

    In normal operation, the background trickle indexer (started with
    'serve') detects new, modified, and deleted files automatically.
    Manual indexing commands are only needed for development and debugging.
    """
    setup_logging(verbose=verbose)
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose


def _get_service(**overrides: object) -> DotMDService:
    settings = Settings(**overrides)  # type: ignore[arg-type]
    return DotMDService(settings=settings)


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
def search(query: str, top: int, mode: str, no_rerank: bool, no_expand: bool) -> None:
    """Search the indexed knowledgebase."""
    service = _get_service(read_only=True)
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
        click.echo(f"  [{i}] {r.file_path}")
        if r.heading_path:
            click.echo(f"      {r.heading_path}")
        click.echo(f"      Score: {r.fused_score:.4f}  Engines: {', '.join(r.matched_engines)}")
        click.echo(f"      {r.snippet}")


@main.command()
@click.option("--verbose", "-V", is_flag=True, help="Show per-strategy/model table details.")
def status(verbose: bool) -> None:
    """Show index statistics."""
    service = _get_service(read_only=True)
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
        strategies: dict[str, tuple[int, int]] = {}  # strategy -> (chunks, files)
        for (name,) in rows:
            if name.startswith("chunks_") and not name.startswith("chunks_fts_"):
                strategy = name[len("chunks_"):]
                count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                files = conn.execute(
                    f"SELECT COUNT(DISTINCT file_path) FROM {name}"
                ).fetchone()[0]
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
    if stats.trickle_status and stats.trickle_status != "idle":
        click.echo("")  # blank line separator
        if stats.trickle_status == "backlog":
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
        elif stats.trickle_status == "watching":
            click.echo(f"Background: watching for new files (indexed {stats.trickle_indexed or 0} total)")
        elif stats.trickle_status == "stopping":
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
    import sys

    dotmd_bin = shutil.which("dotmd") or sys.executable
    config = {
        "dotmd": {
            "command": str(Path(dotmd_bin).resolve()),
            "args": ["mcp"],
        }
    }
    click.echo(json.dumps(config, indent=2))


