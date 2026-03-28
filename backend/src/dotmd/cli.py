"""CLI interface for dotMD — thin wrapper over DotMDService."""

from __future__ import annotations

from pathlib import Path

import click

from dotmd.api.service import DotMDService
from dotmd.core.config import Settings
from dotmd.core.models import SearchMode
from dotmd.utils.logging import setup_logging


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging.")
@click.pass_context
def main(ctx: click.Context, verbose: bool) -> None:
    """dotMD — Search your markdown knowledgebase."""
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
    """Index all markdown files in DIRECTORY."""
    overrides: dict[str, object] = {"extract_depth": extract_depth}
    if entity_types:
        overrides["ner_entity_types"] = [t.strip() for t in entity_types.split(",")]

    service = _get_service(**overrides)
    mode_label = "full re-index" if force else "incremental"
    click.echo(f"Indexing {directory} ({mode_label})...")
    stats = service.index(directory, force=force)
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
def status() -> None:
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


@main.command()
def clear() -> None:
    """Clear the entire index."""
    if not click.confirm("This will delete the entire index. Continue?"):
        return
    service = _get_service()
    service.clear()
    click.echo("Index cleared.")


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


