"""Read-only export runner for Phase 43 SurrealDB source capture refresh."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from dotmd.core.config import DEFAULT_FALKORDB_GRAPH_NAME, load_settings
    from dotmd.feedback import FeedbackStore
    from dotmd.storage.falkordb_graph import FalkorDBGraphStore
except ModuleNotFoundError:  # pragma: no cover - import fallback for direct test imports
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from dotmd.core.config import DEFAULT_FALKORDB_GRAPH_NAME, load_settings
    from dotmd.feedback import FeedbackStore
    from dotmd.storage.falkordb_graph import FalkorDBGraphStore

DEFAULT_GRAPH_EXPORT_PAGE_SIZE = 5_000
DEFAULT_GRAPH_QUERY_TIMEOUT_MS = 120_000


@dataclass(slots=True, frozen=True)
class SurrealSourceExportRunnerConfig:
    graph_output: Path
    feedback_output: Path
    falkordb_url: str
    graph_name: str = DEFAULT_FALKORDB_GRAPH_NAME
    index_dir: Path | None = None
    feedback_db: Path | None = None
    progress_interval_seconds: float = 5.0
    graph_page_size: int = DEFAULT_GRAPH_EXPORT_PAGE_SIZE
    graph_query_timeout_ms: int = DEFAULT_GRAPH_QUERY_TIMEOUT_MS


@dataclass(slots=True, frozen=True)
class SurrealSourceExportRunnerResult:
    graph_output: Path
    feedback_output: Path
    graph_rows: dict[str, list[dict[str, Any]]]
    feedback_rows: list[dict[str, Any]]
    exit_code: int


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_default(value: object) -> str:
    return str(value)


def _canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonicalize(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    if isinstance(value, tuple):
        return [_canonicalize(item) for item in value]
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            _canonicalize(payload),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        )
        + "\n",
        encoding="utf-8",
    )


def _progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _row_identity_digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(_canonicalize(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_default)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _query_result_rows(result: Any) -> list[Any]:
    return list(getattr(result, "result_set", []))


def _query_scalar_int(graph: Any, statement: str, params: dict[str, Any] | None = None) -> int:
    rows = _query_result_rows(graph.ro_query(statement, params=params))
    if not rows or not rows[0]:
        return 0
    return int(rows[0][0])


def _node_properties(node: Any) -> dict[str, Any]:
    if hasattr(node, "properties"):
        return dict(node.properties)
    if isinstance(node, dict):
        return dict(node)
    return {}


def _relation_properties(relation: Any) -> dict[str, Any]:
    if hasattr(relation, "properties"):
        return dict(relation.properties)
    if isinstance(relation, dict):
        return dict(relation)
    return {}


def _page_query(
    graph: Any,
    *,
    statement: str,
    params: dict[str, Any] | None,
    expected_total: int,
    category_label: str,
    page_size: int,
    query_timeout_ms: int,
) -> list[Any]:
    rows: list[Any] = []
    skip = 0
    page = 0
    while True:
        page_rows = _query_result_rows(
            graph.ro_query(
                statement,
                params={**(params or {}), "skip": skip, "limit": page_size},
                timeout=query_timeout_ms,
            )
        )
        rows.extend(page_rows)
        page += 1
        _progress(
            f"graph export: {category_label} page {page} applied {len(rows)}/{expected_total}"
        )
        if len(page_rows) < page_size:
            break
        skip += page_size
    if len(rows) != expected_total:
        raise RuntimeError(
            f"graph export: {category_label} count mismatch: expected {expected_total}, got {len(rows)}"
        )
    _progress(
        f"graph export: completed reading {category_label} ({len(rows)}/{expected_total} rows)"
    )
    return rows


def _read_graph_rows(
    graph_store: FalkorDBGraphStore,
    *,
    page_size: int = DEFAULT_GRAPH_EXPORT_PAGE_SIZE,
    query_timeout_ms: int = DEFAULT_GRAPH_QUERY_TIMEOUT_MS,
) -> dict[str, list[dict[str, Any]]]:
    graph = graph_store._graph

    _progress("graph export: reading File nodes")
    file_count = _query_scalar_int(graph, "MATCH (n:File) RETURN count(n)")
    _progress(f"graph export: planned File nodes ({file_count} rows)")
    file_rows = _page_query(
        graph,
        statement="MATCH (n:File) RETURN n ORDER BY n.id SKIP $skip LIMIT $limit",
        params=None,
        expected_total=file_count,
        category_label="File nodes",
        page_size=page_size,
        query_timeout_ms=query_timeout_ms,
    )

    _progress("graph export: reading Section nodes")
    section_count = _query_scalar_int(graph, "MATCH (n:Section) RETURN count(n)")
    _progress(f"graph export: planned Section nodes ({section_count} rows)")
    section_rows = _page_query(
        graph,
        statement="MATCH (n:Section) RETURN n ORDER BY n.id SKIP $skip LIMIT $limit",
        params=None,
        expected_total=section_count,
        category_label="Section nodes",
        page_size=page_size,
        query_timeout_ms=query_timeout_ms,
    )

    _progress("graph export: reading Tag nodes")
    tag_count = _query_scalar_int(graph, "MATCH (n:Tag) RETURN count(n)")
    _progress(f"graph export: planned Tag nodes ({tag_count} rows)")
    tag_rows = _page_query(
        graph,
        statement="MATCH (n:Tag) RETURN n ORDER BY n.id SKIP $skip LIMIT $limit",
        params=None,
        expected_total=tag_count,
        category_label="Tag nodes",
        page_size=page_size,
        query_timeout_ms=query_timeout_ms,
    )

    _progress("graph export: reading Entity nodes")
    entity_count = _query_scalar_int(graph, "MATCH (n:Entity) RETURN count(n)")
    _progress(f"graph export: planned Entity nodes ({entity_count} rows)")
    entity_rows = _page_query(
        graph,
        statement="MATCH (n:Entity) RETURN n ORDER BY n.id SKIP $skip LIMIT $limit",
        params=None,
        expected_total=entity_count,
        category_label="Entity nodes",
        page_size=page_size,
        query_timeout_ms=query_timeout_ms,
    )

    _progress("graph export: reading Section NER links")
    section_ner_count = _query_scalar_int(
        graph,
        "MATCH (s:Section)-[:REL]->(e:Entity) WHERE e.source = 'ner' RETURN count(*)",
    )
    _progress(f"graph export: planned Section NER links ({section_ner_count} rows)")
    section_ner_rows = _page_query(
        graph,
        statement=(
            "MATCH (s:Section)-[:REL]->(e:Entity) "
            "WHERE e.source = 'ner' "
            "RETURN s.id, e.id ORDER BY s.id, e.id SKIP $skip LIMIT $limit"
        ),
        params=None,
        expected_total=section_ner_count,
        category_label="Section NER links",
        page_size=page_size,
        query_timeout_ms=query_timeout_ms,
    )

    section_ner_entities: dict[str, list[str]] = {}
    for row in section_ner_rows:
        if len(row) < 2:
            continue
        section_id = str(row[0])
        entity_id = str(row[1])
        section_ner_entities.setdefault(section_id, []).append(entity_id)
    for entity_ids in section_ner_entities.values():
        entity_ids.sort()

    _progress("graph export: reading relations")
    relation_count = _query_scalar_int(graph, "MATCH (a)-[r]->(b) RETURN count(r)")
    _progress(f"graph export: planned relations ({relation_count} rows)")
    relation_rows = _page_query(
        graph,
        statement=(
            "MATCH (a)-[r]->(b) "
            "RETURN a.id, b.id, r.rel_type, r.weight, r "
            "SKIP $skip LIMIT $limit"
        ),
        params=None,
        expected_total=relation_count,
        category_label="relations",
        page_size=page_size,
        query_timeout_ms=query_timeout_ms,
    )

    nodes: list[dict[str, Any]] = []
    for label, rows in (
        ("File", file_rows),
        ("Section", section_rows),
        ("Entity", entity_rows),
        ("Tag", tag_rows),
    ):
        for row in rows:
            if not row:
                continue
            node = row[0]
            node_properties = _node_properties(node)
            node_id = str(node_properties.get("id", "") or getattr(node, "id", ""))
            properties = {key: value for key, value in node_properties.items() if key != "id"}
            if label == "Section" and node_id in section_ner_entities:
                properties = {**properties, "ner_entities": section_ner_entities[node_id]}
            nodes.append(
                {
                    "id": node_id,
                    "label": label,
                    "properties": properties,
                }
            )

    edges: list[dict[str, Any]] = []
    for row in relation_rows:
        if len(row) < 4:
            continue
        source_id = str(row[0])
        target_id = str(row[1])
        relation_type = str(row[2])
        weight = row[3]
        relation_properties = _relation_properties(row[4]) if len(row) > 4 else {}
        properties = {
            key: value
            for key, value in relation_properties.items()
            if key not in {"rel_type", "weight"}
        }
        edges.append(
            {
                "source": source_id,
                "target": target_id,
                "relation_type": relation_type,
                "weight": float(weight) if weight is not None else 1.0,
                **properties,
            }
        )

    return {"nodes": nodes, "edges": edges}


def _transform_graph_rows(
    graph_data: dict[str, Any],
    *,
    progress_interval_seconds: float,
) -> dict[str, list[dict[str, Any]]]:
    nodes = list(graph_data.get("nodes", []))
    edges = list(graph_data.get("edges", []))

    grouped_nodes: dict[str, list[dict[str, Any]]] = {"File": [], "Section": [], "Entity": [], "Tag": []}
    for node in nodes:
        label = str(node.get("label", ""))
        if label in grouped_nodes:
            grouped_nodes[label].append(dict(node))

    for rows in grouped_nodes.values():
        rows.sort(key=lambda row: str(row.get("id", "")))

    rows: dict[str, list[dict[str, Any]]] = {
        "files": [],
        "sections": [],
        "tags": [],
        "entities": [],
        "relations": [],
    }

    start = time.monotonic()
    last_report = start
    total_nodes = len(nodes)
    processed_nodes = 0

    for label, category in (("File", "files"), ("Section", "sections"), ("Tag", "tags"), ("Entity", "entities")):
        category_rows = grouped_nodes[label]
        _progress(f"graph export: transforming {category} ({len(category_rows)} rows)")
        for row in category_rows:
            processed_nodes += 1
            if category == "files":
                file_path = str(row.get("id", ""))
                properties = dict(row.get("properties", {}))
                rows[category].append(
                    {
                        "id": file_path,
                        "original_id": file_path,
                        "file_path": file_path,
                        "path": file_path,
                        "title": str(properties.get("title", "")),
                        "metadata": _canonicalize(
                            {
                                key: value
                                for key, value in properties.items()
                                if key != "title"
                            }
                        ),
                    }
                )
            elif category == "sections":
                chunk_id = str(row.get("id", ""))
                properties = dict(row.get("properties", {}))
                rows[category].append(
                    {
                        "id": chunk_id,
                        "original_id": chunk_id,
                        "chunk_id": chunk_id,
                        "heading": str(properties.get("heading", "")),
                        "level": int(properties.get("level", 0) or 0),
                        "file_path": str(properties.get("file_path", "")),
                        "text_preview": str(properties.get("text_preview", "")),
                        "metadata": _canonicalize(
                            {
                                key: value
                                for key, value in properties.items()
                                if key not in {"heading", "level", "file_path", "text_preview"}
                            }
                        ),
                    }
                )
            elif category == "tags":
                tag_name = str(row.get("id", ""))
                properties = dict(row.get("properties", {}))
                rows[category].append(
                    {
                        "id": tag_name,
                        "original_id": tag_name,
                        "name": tag_name,
                        "metadata": _canonicalize(properties),
                    }
                )
            else:
                entity_name = str(row.get("id", ""))
                properties = dict(row.get("properties", {}))
                rows[category].append(
                    {
                        "id": entity_name,
                        "original_id": entity_name,
                        "name": entity_name,
                        "entity_type": str(properties.get("type", "Entity")),
                        "source": str(properties.get("source", "")),
                        "metadata": _canonicalize(
                            {
                                key: value
                                for key, value in properties.items()
                                if key not in {"type", "source"}
                            }
                        ),
                    }
                )
            now = time.monotonic()
            if now - last_report >= progress_interval_seconds:
                _progress(
                    f"graph export: {processed_nodes}/{total_nodes} nodes transformed"
                )
                last_report = now

    relations = sorted(
        (dict(edge) for edge in edges),
        key=lambda row: (
            str(row.get("source", "")),
            str(row.get("target", "")),
            str(row.get("relation_type", "")),
            str(row.get("weight", "")),
        ),
    )
    _progress(f"graph export: transforming relations ({len(relations)} rows)")
    last_report = time.monotonic()
    for index, row in enumerate(relations, start=1):
        properties = _canonicalize({key: value for key, value in row.items() if key not in {"source", "target", "relation_type", "weight"}})
        relation_payload = {
            "source_id": str(row.get("source", "")),
            "target_id": str(row.get("target", "")),
            "relation_type": str(row.get("relation_type", "")),
            "weight": float(row.get("weight", 1.0) or 1.0),
            "properties": properties,
        }
        relation_digest = _row_identity_digest(relation_payload)
        rows["relations"].append(
            {
                "relation_id": f"rel:{relation_digest[:24]}",
                **relation_payload,
            }
        )
        now = time.monotonic()
        if now - last_report >= progress_interval_seconds:
            _progress(f"graph export: {index}/{len(relations)} relations transformed")
            last_report = now
    _progress(f"graph export: completed relations ({len(relations)} rows)")

    return rows


def _transform_feedback_rows(
    rows: list[dict[str, Any]],
    *,
    progress_interval_seconds: float,
) -> list[dict[str, Any]]:
    sorted_rows = sorted(rows, key=lambda row: (-int(row.get("submitted_at", 0) or 0), int(row.get("id", 0) or 0)))
    _progress(f"feedback export: transforming {len(sorted_rows)} rows")
    result: list[dict[str, Any]] = []
    start = time.monotonic()
    last_report = start
    for index, row in enumerate(sorted_rows, start=1):
        result.append(
            {
                "id": int(row["id"]),
                "submitted_at": int(row["submitted_at"]),
                "message": row["message"],
                "severity": row.get("severity"),
                "status": row.get("status"),
                "context": row.get("context"),
                "model": row.get("model"),
                "harness": row.get("harness"),
                "status_comment": row.get("status_comment"),
                "metadata": _canonicalize(
                    {
                        key: value
                        for key, value in row.items()
                        if key
                        not in {
                            "id",
                            "submitted_at",
                            "message",
                            "severity",
                            "status",
                            "context",
                            "model",
                            "harness",
                            "status_comment",
                        }
                    }
                ),
            }
        )
        now = time.monotonic()
        if now - last_report >= progress_interval_seconds:
            _progress(f"feedback export: {index}/{len(sorted_rows)} rows transformed")
            last_report = now
    _progress(f"feedback export: completed {len(sorted_rows)} rows")
    return result


def _graph_inventory(rows: dict[str, list[dict[str, Any]]], *, edge_count: int) -> dict[str, Any]:
    return {
        "generated_at": _utc_now(),
        "row_counts": {key: len(value) for key, value in rows.items()},
        "node_counts": {
            "File": len(rows["files"]),
            "Section": len(rows["sections"]),
            "Tag": len(rows["tags"]),
            "Entity": len(rows["entities"]),
        },
        "edge_count": edge_count,
    }


def _feedback_inventory(rows: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status", "unknown"))
        severity = row.get("severity")
        status_counts[status] = status_counts.get(status, 0) + 1
        if severity is not None:
            severity_key = str(severity)
            severity_counts[severity_key] = severity_counts.get(severity_key, 0) + 1
    return {
        "generated_at": _utc_now(),
        "total_feedback": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "severity_counts": dict(sorted(severity_counts.items())),
    }


def _feedback_store_path(config: SurrealSourceExportRunnerConfig) -> Path:
    if config.feedback_db is not None:
        return config.feedback_db
    if config.index_dir is not None:
        return Path(config.index_dir) / "feedback.db"
    settings = load_settings()
    return Path(settings.index_dir) / "feedback.db"


def run_export_command(config: SurrealSourceExportRunnerConfig) -> SurrealSourceExportRunnerResult:
    if config.graph_page_size < 1:
        raise ValueError("graph_page_size must be positive")
    if config.graph_query_timeout_ms < 1:
        raise ValueError("graph_query_timeout_ms must be positive")

    graph_store = FalkorDBGraphStore(url=config.falkordb_url, graph_name=config.graph_name)
    graph_data = _read_graph_rows(
        graph_store,
        page_size=config.graph_page_size,
        query_timeout_ms=config.graph_query_timeout_ms,
    )
    graph_rows = _transform_graph_rows(
        graph_data,
        progress_interval_seconds=config.progress_interval_seconds,
    )
    graph_payload = {
        "exported_at": _utc_now(),
        "inventory": _graph_inventory(graph_rows, edge_count=len(graph_data.get("edges", []))),
        "rows": graph_rows,
    }

    feedback_store = FeedbackStore(_feedback_store_path(config))
    raw_feedback_rows = feedback_store.list_all(limit=1_000_000, include_closed=True)
    if len(raw_feedback_rows) >= 1_000_000:
        raise RuntimeError(
            "feedback export reached the page limit; use a larger limit or reduce source size"
        )
    feedback_rows = _transform_feedback_rows(
        list(raw_feedback_rows),
        progress_interval_seconds=config.progress_interval_seconds,
    )
    feedback_payload = {
        "exported_at": _utc_now(),
        "inventory": _feedback_inventory(feedback_rows),
        "truncated": False,
        "rows": feedback_rows,
    }

    _write_json(config.graph_output, graph_payload)
    _write_json(config.feedback_output, feedback_payload)

    _progress(
        f"export complete: graph_rows={sum(len(rows) for rows in graph_rows.values())} "
        f"feedback_rows={len(feedback_rows)}"
    )
    _progress(f"wrote graph export to {config.graph_output}")
    _progress(f"wrote feedback export to {config.feedback_output}")

    return SurrealSourceExportRunnerResult(
        graph_output=config.graph_output,
        feedback_output=config.feedback_output,
        graph_rows=graph_rows,
        feedback_rows=feedback_rows,
        exit_code=0,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export current production graph and feedback rows.")
    parser.add_argument("--graph-output", type=Path, required=True)
    parser.add_argument("--feedback-output", type=Path, required=True)
    parser.add_argument("--falkordb-url", required=True)
    parser.add_argument("--graph-name", default=DEFAULT_FALKORDB_GRAPH_NAME)
    parser.add_argument("--index-dir", type=Path, default=None)
    parser.add_argument("--feedback-db", type=Path, default=None)
    parser.add_argument(
        "--progress-interval-seconds",
        type=float,
        default=5.0,
        help="Print progress after this many seconds while transforming rows.",
    )
    parser.add_argument(
        "--graph-page-size",
        type=int,
        default=DEFAULT_GRAPH_EXPORT_PAGE_SIZE,
        help="Rows to read from FalkorDB per graph export page.",
    )
    parser.add_argument(
        "--graph-query-timeout-ms",
        type=int,
        default=DEFAULT_GRAPH_QUERY_TIMEOUT_MS,
        help="FalkorDB read-only query timeout for each graph export page.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.index_dir is None and args.feedback_db is None:
        raise SystemExit("--index-dir or --feedback-db is required")
    run_export_command(
        SurrealSourceExportRunnerConfig(
            graph_output=args.graph_output,
            feedback_output=args.feedback_output,
            falkordb_url=args.falkordb_url,
            graph_name=args.graph_name,
            index_dir=args.index_dir,
            feedback_db=args.feedback_db,
            progress_interval_seconds=args.progress_interval_seconds,
            graph_page_size=args.graph_page_size,
            graph_query_timeout_ms=args.graph_query_timeout_ms,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
