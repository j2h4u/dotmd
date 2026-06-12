"""Read-only inventory helpers for Phase 38 storage evaluation.

These helpers inspect current SQLite, FalkorDB, and feedback state without
mutating the live stores. They exist to answer one question: how much of the
current production data can move into a Surreal-backed prototype by transform
only, without rechunking, reembedding, or re-extracting graph entities.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_VALID_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REQUIRED_CATEGORIES = {
    "chunks",
    "provenance",
    "bindings",
    "fingerprints",
    "source_state",
    "embeddings",
    "vector_components",
    "graph",
    "feedback",
}
_KNOWN_CATEGORY_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "chunks": ("chunk_id",),
    "provenance": ("chunk_id", "document_ref"),
    "bindings": ("resource_ref",),
    "fingerprints": ("fingerprint",),
    "source_state": ("checkpoint_cursor",),
    "embeddings": ("chunk_id",),
    "vector_components": ("entity_id", "component"),
    "graph": ("relation_label",),
    "feedback": ("status",),
}


@dataclass(frozen=True)
class GraphRelationSummary:
    relation_label: str
    count: int
    weights: list[float] = field(default_factory=list)
    metadata_keys: list[str] = field(default_factory=list)
    property_value_types: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SQLiteSnapshotInventory:
    source_path: Path
    snapshot_path: Path
    snapshot_created_at: str
    wal_mode: str
    manifest: dict[str, Any]
    table_counts: dict[str, int] = field(default_factory=dict)
    unmapped_tables: list[str] = field(default_factory=list)
    sha256: str | None = None


@dataclass(frozen=True)
class FalkorSnapshotInventory:
    node_counts: dict[str, int]
    edge_count: int
    relation_summaries: list[GraphRelationSummary]
    available: bool = True
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class FeedbackSnapshotInventory:
    total_feedback: int
    status_counts: dict[str, int]
    severity_counts: dict[str, int]
    available: bool = True
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class MigrationCategoryDisposition:
    disposition: str
    reason: str
    source_fields: list[str] = field(default_factory=list)
    transform_target: str | None = None
    cpu_recomputation_required: bool = False
    safety_caveats: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SurrealMigrationMap:
    categories: dict[str, MigrationCategoryDisposition]
    generated_at: str


def _utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_connect_read_only(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _validate_known_table_name(table_name: str, known_tables: set[str]) -> str:
    if not _VALID_TABLE_NAME.match(table_name):
        raise ValueError(f"Unsafe SQLite table name: {table_name!r}")
    if table_name not in known_tables:
        raise ValueError(f"Unknown SQLite table name: {table_name!r}")
    return table_name


def _discover_tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        ).fetchall()
    }


def _discover_virtual_tables(conn: sqlite3.Connection, *, prefix: str) -> list[str]:
    return [
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name LIKE ? AND sql LIKE 'CREATE VIRTUAL TABLE%'",
            (f"{prefix}%",),
        ).fetchall()
    ]


def _count_rows(conn: sqlite3.Connection, table_name: str, known_tables: set[str]) -> int:
    safe_name = _validate_known_table_name(table_name, known_tables)
    return int(conn.execute(f"SELECT COUNT(*) FROM {safe_name}").fetchone()[0])


def _sum_matching_tables(
    conn: sqlite3.Connection,
    known_tables: set[str],
    *,
    prefix: str,
    exclude_prefixes: tuple[str, ...] = (),
) -> int:
    total = 0
    for table_name in sorted(known_tables):
        if not table_name.startswith(prefix):
            continue
        if any(table_name.startswith(excluded) for excluded in exclude_prefixes):
            continue
        total += _count_rows(conn, table_name, known_tables)
    return total


def _journal_mode(db_path: Path) -> str:
    with _sqlite_connect_read_only(db_path) as conn:
        return str(conn.execute("PRAGMA journal_mode").fetchone()[0])


def copy_sqlite_snapshot(source_path: Path, snapshot_dir: Path, name: str) -> SQLiteSnapshotInventory:
    """Create a consistent standalone SQLite snapshot via the backup API.

    The source path is caller-provided on purpose: the helper must remain
    agnostic to Docker volume layout and any live deployment path choices.
    """

    source_path = Path(source_path)
    snapshot_dir = Path(snapshot_dir)
    if not source_path.exists():
        raise FileNotFoundError(source_path)

    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_name = Path(name).name
    if Path(snapshot_name).suffix:
        snapshot_path = snapshot_dir / snapshot_name
    else:
        suffix = source_path.suffix or ".db"
        snapshot_path = snapshot_dir / f"{snapshot_name}{suffix}"

    source_stat_before = source_path.stat()
    journal_mode = _journal_mode(source_path)
    wal_path = Path(f"{source_path}-wal")
    shm_path = Path(f"{source_path}-shm")
    sidecars = [path.name for path in (wal_path, shm_path) if path.exists()]

    with _sqlite_connect_read_only(source_path) as source_conn:
        with sqlite3.connect(snapshot_path) as snapshot_conn:
            source_conn.backup(snapshot_conn)
            snapshot_conn.commit()

    source_stat_after = source_path.stat()
    manifest = {
        "source_size_bytes": source_stat_before.st_size,
        "snapshot_size_bytes": snapshot_path.stat().st_size,
        "source_mtime_ns_before": source_stat_before.st_mtime_ns,
        "source_mtime_ns_after": source_stat_after.st_mtime_ns,
        "journal_mode": journal_mode,
        "sidecars": sidecars,
        "snapshot_strategy": "sqlite-backup",
        "source_unchanged": {
            "mtime_ns": source_stat_before.st_mtime_ns == source_stat_after.st_mtime_ns,
            "size_bytes": source_stat_before.st_size == source_stat_after.st_size,
        },
    }

    return SQLiteSnapshotInventory(
        source_path=source_path,
        snapshot_path=snapshot_path,
        snapshot_created_at=_utc_now(),
        wal_mode="sqlite-backup",
        manifest=manifest,
        sha256=_sha256_file(snapshot_path),
    )


def collect_sqlite_inventory(db_path: Path) -> SQLiteSnapshotInventory:
    """Collect row counts for the current SQLite storage surface."""

    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(db_path)

    with _sqlite_connect_read_only(db_path) as conn:
        known_tables = _discover_tables(conn)
        table_counts = {
            "chunks": _sum_matching_tables(
                conn,
                known_tables,
                prefix="chunks_",
                exclude_prefixes=("chunks_fts_",),
            ),
            "fts_rows": sum(
                _count_rows(conn, table_name, known_tables)
                for table_name in _discover_virtual_tables(conn, prefix="chunks_fts_")
            ),
            "vectors": _sum_matching_tables(conn, known_tables, prefix="vec_meta_"),
            "vec_components": _sum_matching_tables(conn, known_tables, prefix="vec_components_"),
            "source_documents": (
                _count_rows(conn, "source_documents", known_tables)
                if "source_documents" in known_tables
                else 0
            ),
            "resource_bindings": (
                _count_rows(conn, "resource_bindings", known_tables)
                if "resource_bindings" in known_tables
                else 0
            ),
            "chunk_fingerprints": _sum_matching_tables(
                conn, known_tables, prefix="chunk_fingerprints_"
            ),
            "embed_fingerprints": _sum_matching_tables(
                conn, known_tables, prefix="embed_fingerprints_"
            ),
            "source_unit_fingerprints": (
                _count_rows(conn, "source_unit_fingerprints", known_tables)
                if "source_unit_fingerprints" in known_tables
                else 0
            ),
            "source_checkpoints": (
                _count_rows(conn, "source_checkpoints", known_tables)
                if "source_checkpoints" in known_tables
                else 0
            ),
            "caches": sum(
                _count_rows(conn, table_name, known_tables)
                for table_name in sorted(known_tables)
                if "cache" in table_name
            ),
        }
        mapped_names = {
            "source_documents",
            "resource_bindings",
            "source_unit_fingerprints",
            "source_checkpoints",
        }
        mapped_prefixes = (
            "chunks_",
            "chunks_fts_",
            "vec_meta_",
            "vec_components_",
            "chunk_fingerprints_",
            "embed_fingerprints_",
        )
        unmapped_tables = [
            table_name
            for table_name in sorted(known_tables)
            if table_name not in mapped_names
            and not any(table_name.startswith(prefix) for prefix in mapped_prefixes)
        ]

    return SQLiteSnapshotInventory(
        source_path=db_path,
        snapshot_path=db_path,
        snapshot_created_at=_utc_now(),
        wal_mode=_journal_mode(db_path),
        manifest={
            "source_size_bytes": db_path.stat().st_size,
            "snapshot_strategy": "read-only-inventory",
        },
        table_counts=table_counts,
        unmapped_tables=unmapped_tables,
        sha256=_sha256_file(db_path),
    )


def collect_falkor_inventory(exporter: Any) -> FalkorSnapshotInventory:
    """Collect graph inventory through a supported exporter abstraction."""

    try:
        raw_inventory = exporter.export_inventory()
    except Exception as exc:
        return FalkorSnapshotInventory(
            node_counts={},
            edge_count=0,
            relation_summaries=[],
            available=False,
            unavailable_reason=str(exc),
        )

    summaries = [
        GraphRelationSummary(
            relation_label=str(item["relation_label"]),
            count=int(item["count"]),
            weights=[float(value) for value in item.get("weights", [])],
            metadata_keys=[str(value) for value in item.get("metadata_keys", [])],
            property_value_types={
                str(key): str(value)
                for key, value in dict(item.get("property_value_types", {})).items()
            },
        )
        for item in raw_inventory.get("relation_summaries", [])
    ]
    return FalkorSnapshotInventory(
        node_counts={
            str(key): int(value) for key, value in dict(raw_inventory.get("node_counts", {})).items()
        },
        edge_count=int(raw_inventory.get("edge_count", 0)),
        relation_summaries=summaries,
    )


def collect_feedback_inventory(provider: Any) -> FeedbackSnapshotInventory:
    """Collect feedback counts through the provider surface, never raw SQL."""

    try:
        rows = list(provider.list_all(limit=1000, include_closed=True))
    except Exception as exc:
        return FeedbackSnapshotInventory(
            total_feedback=0,
            status_counts={},
            severity_counts={},
            available=False,
            unavailable_reason=str(exc),
        )

    status_counts = Counter(str(row.get("status", "unknown")) for row in rows)
    severity_counts = Counter(
        str(row["severity"]) for row in rows if row.get("severity") is not None
    )
    return FeedbackSnapshotInventory(
        total_feedback=len(rows),
        status_counts=dict(status_counts),
        severity_counts=dict(severity_counts),
    )


def build_surreal_migration_map(
    *, categories: dict[str, dict[str, Any]]
) -> SurrealMigrationMap:
    """Classify current data categories for transform-first migration."""

    missing = sorted(_REQUIRED_CATEGORIES - set(categories))
    if missing:
        raise ValueError(f"Missing required migration categories: {', '.join(missing)}")

    dispositions: dict[str, MigrationCategoryDisposition] = {}
    for category_name, details in categories.items():
        expected_fields = _KNOWN_CATEGORY_REQUIREMENTS.get(category_name)
        actual_fields = [
            str(value)
            for key in ("columns", "properties", "fields")
            for value in details.get(key, [])
        ]
        verified = bool(details.get("verified", False))

        if expected_fields is None:
            dispositions[category_name] = MigrationCategoryDisposition(
                disposition="unsupported",
                reason="Unknown category: no approved transform target",
                source_fields=actual_fields,
                transform_target=None,
                cpu_recomputation_required=True,
                safety_caveats=["Review manually before any Surreal import work."],
            )
            continue

        missing_fields = [field for field in expected_fields if field not in actual_fields]
        if missing_fields:
            dispositions[category_name] = MigrationCategoryDisposition(
                disposition="unsafe",
                reason=f"Missing required source fields: {', '.join(missing_fields)}",
                source_fields=actual_fields,
                transform_target=f"surreal::{category_name}",
                cpu_recomputation_required=False,
                safety_caveats=["Cannot prove transform-only import from current evidence."],
            )
            continue

        if not verified:
            dispositions[category_name] = MigrationCategoryDisposition(
                disposition="unsafe",
                reason="Category present but not verified from source artifacts",
                source_fields=actual_fields,
                transform_target=f"surreal::{category_name}",
                cpu_recomputation_required=False,
                safety_caveats=["Evidence gap must be closed before migration recommendation."],
            )
            continue

        dispositions[category_name] = MigrationCategoryDisposition(
            disposition="transformable",
            reason="Verified source fields support transform-first migration",
            source_fields=actual_fields,
            transform_target=f"surreal::{category_name}",
            cpu_recomputation_required=False,
            safety_caveats=[],
        )

    return SurrealMigrationMap(categories=dispositions, generated_at=_utc_now())


def write_inventory_reports(
    *,
    inventory_path: Path,
    migration_map_path: Path,
    sqlite_inventory: SQLiteSnapshotInventory,
    falkor_inventory: FalkorSnapshotInventory,
    feedback_inventory: FeedbackSnapshotInventory,
    migration_map: SurrealMigrationMap,
) -> None:
    """Write Markdown inventory and migration-map reports."""

    inventory_lines = [
        "# Storage Inventory",
        "",
        f"- Generated: {sqlite_inventory.snapshot_created_at}",
        f"- SQLite source: `{sqlite_inventory.source_path}`",
        f"- SQLite snapshot: `{sqlite_inventory.snapshot_path}`",
        f"- SQLite snapshot strategy: `{sqlite_inventory.wal_mode}`",
        f"- SQLite SHA256: `{sqlite_inventory.sha256}`",
        "",
        "## SQLite Counts",
        "",
    ]
    for key, value in sorted(sqlite_inventory.table_counts.items()):
        inventory_lines.append(f"- `{key}`: {value}")
    inventory_lines.extend(
        [
            "",
            "## SQLite Manifest",
            "",
            "```json",
            json.dumps(sqlite_inventory.manifest, indent=2, sort_keys=True),
            "```",
            "",
            "## SQLite Unmapped Tables",
            "",
        ]
    )
    if sqlite_inventory.unmapped_tables:
        inventory_lines.extend(f"- `{name}`" for name in sqlite_inventory.unmapped_tables)
    else:
        inventory_lines.append("- None")
    inventory_lines.extend(["", "## Falkor Inventory", ""])
    if falkor_inventory.available:
        for label, count in sorted(falkor_inventory.node_counts.items()):
            inventory_lines.append(f"- `{label}` nodes: {count}")
        inventory_lines.append(f"- `edges`: {falkor_inventory.edge_count}")
        inventory_lines.append("")
        inventory_lines.append("### Relation Summaries")
        inventory_lines.append("")
        for summary in falkor_inventory.relation_summaries:
            inventory_lines.append(
                f"- `{summary.relation_label}`: count={summary.count}, "
                f"weights={summary.weights}, keys={summary.metadata_keys}, "
                f"types={summary.property_value_types}"
            )
    else:
        inventory_lines.append(f"- Unavailable: {falkor_inventory.unavailable_reason}")
    inventory_lines.extend(["", "## Feedback Inventory", ""])
    if feedback_inventory.available:
        inventory_lines.append(f"- Total feedback: {feedback_inventory.total_feedback}")
        inventory_lines.append(f"- Status counts: {feedback_inventory.status_counts}")
        inventory_lines.append(f"- Severity counts: {feedback_inventory.severity_counts}")
    else:
        inventory_lines.append(f"- Unavailable: {feedback_inventory.unavailable_reason}")

    migration_lines = [
        "# Surreal Migration Map",
        "",
        f"- Generated: {migration_map.generated_at}",
        "",
        "| Category | Disposition | Transform Target | Source Fields | CPU Recompute | Reason |",
        "|---|---|---|---|---|---|",
    ]
    for category_name, disposition in migration_map.categories.items():
        migration_lines.append(
            "| {name} | {disposition} | {target} | {fields} | {recompute} | {reason} |".format(
                name=category_name,
                disposition=disposition.disposition,
                target=disposition.transform_target or "—",
                fields=", ".join(disposition.source_fields) or "—",
                recompute="yes" if disposition.cpu_recomputation_required else "no",
                reason=disposition.reason,
            )
        )

    inventory_path.write_text("\n".join(inventory_lines) + "\n", encoding="utf-8")
    migration_map_path.write_text("\n".join(migration_lines) + "\n", encoding="utf-8")
