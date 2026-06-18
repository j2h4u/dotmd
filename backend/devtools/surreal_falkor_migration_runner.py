"""Migrate FalkorDB graph data into standalone SurrealDB graph tables."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from devtools.surreal_standalone_migration_proof import (
    _target_and_data,
    batch_upsert,
    format_eta,
)
from dotmd.storage.surreal import SurrealConnection, SurrealRecordIdCodec, SurrealStoreConfig

GRAPH_LABELS: tuple[str, ...] = ("File", "Section", "Entity", "Tag")


@dataclass(frozen=True, slots=True)
class FalkorMigrationConfig:
    falkor_url: str
    graph_name: str
    batch_size: int = 500


@dataclass(frozen=True, slots=True)
class FalkorMigrationResult:
    nodes: int
    edges: int
    elapsed_seconds: float


class FalkorGraphReader:
    def __init__(self, url: str, graph_name: str) -> None:
        try:
            from falkordb import FalkorDB
        except ModuleNotFoundError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("install the falkordb package before graph migration") from exc
        parsed = urlparse(url)
        self._db = FalkorDB(host=parsed.hostname or "localhost", port=parsed.port or 6379)
        self._graph = self._db.select_graph(graph_name)

    def count_nodes(self, label: str) -> int:
        result = self._graph.ro_query(f"MATCH (n:{label}) RETURN count(n)")
        return int(result.result_set[0][0]) if result.result_set else 0

    def read_nodes(self, label: str, *, skip: int, limit: int) -> list[Any]:
        result = self._graph.ro_query(
            f"MATCH (n:{label}) RETURN n SKIP $skip LIMIT $limit",
            params={"skip": skip, "limit": limit},
        )
        return [row[0] for row in result.result_set]

    def count_edges(self) -> int:
        result = self._graph.ro_query("MATCH ()-[r:REL]->() RETURN count(r)")
        return int(result.result_set[0][0]) if result.result_set else 0

    def read_edges(self, *, skip: int, limit: int) -> list[tuple[Any, Any, Any]]:
        result = self._graph.ro_query(
            "MATCH (a)-[r:REL]->(b) RETURN a, r, b SKIP $skip LIMIT $limit",
            params={"skip": skip, "limit": limit},
        )
        return [(row[0], row[1], row[2]) for row in result.result_set]


def _properties(value: Any) -> dict[str, Any]:
    raw = getattr(value, "properties", {}) or {}
    return dict(raw)


def _labels(value: Any, fallback: str | None = None) -> list[str]:
    labels = list(getattr(value, "labels", []) or [])
    if not labels and fallback:
        labels = [fallback]
    return [str(label) for label in labels]


def _node_record(node: Any, fallback_label: str) -> dict[str, Any]:
    props = _properties(node)
    labels = _labels(node, fallback_label)
    return {
        "type": "graph_node",
        "data": {
            "node_id": str(props.get("id", "")),
            "labels": labels,
            "primary_label": fallback_label,
            "properties": props,
        },
    }


def _relation_label(relation: Any) -> str:
    for attr in ("relation", "type", "label"):
        value = getattr(relation, attr, None)
        if value:
            return str(value)
    return "REL"


def _edge_record(
    source: Any,
    relation: Any,
    target: Any,
    *,
    edge_key: str | None = None,
) -> dict[str, Any]:
    source_props = _properties(source)
    target_props = _properties(target)
    relation_props = _properties(relation)
    return {
        "type": "graph_edge",
        "data": {
            "source_id": str(source_props.get("id", "")),
            "source_labels": _labels(source),
            "target_id": str(target_props.get("id", "")),
            "target_labels": _labels(target),
            "edge_key": edge_key,
            "relation_label": _relation_label(relation),
            "relation_type": str(relation_props.get("rel_type", "")),
            "weight": float(relation_props.get("weight", 1.0) or 1.0),
            "properties": relation_props,
        },
    }


def _emit(printer: Callable[..., None], message: str) -> None:
    printer(message, flush=True)


def _flush_records(
    surreal: SurrealConnection,
    codec: SurrealRecordIdCodec,
    records: list[dict[str, Any]],
) -> None:
    rows = []
    for record in records:
        target, data = _target_and_data(record, codec)
        rows.append({"id": target, "data": data})
    batch_upsert(surreal, rows)


def run_falkor_migration(
    store_config: SurrealStoreConfig,
    migration_config: FalkorMigrationConfig,
    *,
    graph_reader_factory: Callable[[str, str], FalkorGraphReader] = FalkorGraphReader,
    connection_factory: Callable[[SurrealStoreConfig], SurrealConnection] = SurrealConnection,
    printer: Callable[..., None] = print,
    clock: Callable[[], float] = time.monotonic,
) -> FalkorMigrationResult:
    started = clock()
    codec = SurrealRecordIdCodec()
    reader = graph_reader_factory(migration_config.falkor_url, migration_config.graph_name)
    surreal = connection_factory(store_config)
    nodes_done = 0
    edges_done = 0
    try:
        for label in GRAPH_LABELS:
            total_nodes = reader.count_nodes(label)
            _emit(
                printer,
                f"surreal falkor migration: migrating nodes label={label} count={total_nodes}",
            )
            for offset in range(0, total_nodes, migration_config.batch_size):
                nodes = reader.read_nodes(
                    label,
                    skip=offset,
                    limit=migration_config.batch_size,
                )
                batch = [_node_record(node, label) for node in nodes]
                _flush_records(surreal, codec, batch)
                nodes_done += len(batch)
                elapsed = max(clock() - started, 0.001)
                remaining = total_nodes - offset - len(batch)
                rate = (nodes_done + edges_done) / elapsed
                _emit(
                    printer,
                    (
                        "surreal falkor migration: "
                        f"label={label} offset={offset + len(batch)}/{total_nodes} "
                        f"nodes={nodes_done} edges={edges_done} "
                        f"rate={rate:.1f} records/s ETA {format_eta(remaining / rate if rate else 0)}"
                    ),
                )

        total_edges = reader.count_edges()
        _emit(printer, f"surreal falkor migration: migrating edges count={total_edges}")
        for offset in range(0, total_edges, migration_config.batch_size):
            edges = reader.read_edges(skip=offset, limit=migration_config.batch_size)
            batch = [
                _edge_record(
                    source,
                    relation,
                    target,
                    edge_key=str(offset + index),
                )
                for index, (source, relation, target) in enumerate(edges)
            ]
            _flush_records(surreal, codec, batch)
            edges_done += len(batch)
            elapsed = max(clock() - started, 0.001)
            remaining = total_edges - edges_done
            rate = (nodes_done + edges_done) / elapsed
            _emit(
                printer,
                (
                    "surreal falkor migration: "
                    f"nodes={nodes_done} edges={edges_done}/{total_edges} "
                    f"rate={rate:.1f} records/s ETA {format_eta(remaining / rate if rate else 0)}"
                ),
            )
    finally:
        surreal.close()
    return FalkorMigrationResult(
        nodes=nodes_done,
        edges=edges_done,
        elapsed_seconds=round(clock() - started, 3),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--falkor-url", default="redis://localhost:6379")
    parser.add_argument("--graph-name", default="dotmd")
    parser.add_argument("--batch-size", type=int, default=500)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_falkor_migration(
            SurrealStoreConfig.from_env(),
            FalkorMigrationConfig(
                falkor_url=args.falkor_url,
                graph_name=args.graph_name,
                batch_size=args.batch_size,
            ),
        )
    except Exception as exc:
        print(f"surreal falkor migration failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(
        "surreal falkor migration ok: "
        f"nodes={result.nodes} edges={result.edges} elapsed={result.elapsed_seconds:.3f}s "
        f"counts={json.dumps({'graph_node': result.nodes, 'graph_edge': result.edges}, sort_keys=True)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
