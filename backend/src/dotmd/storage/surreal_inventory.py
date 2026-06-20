"""Read-only inventory helpers for Surreal migration evidence."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

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


def collect_feedback_inventory(provider: Any) -> FeedbackSnapshotInventory:
    """Collect feedback counts through the provider surface, never raw SQL."""

    try:
        limit = 1001
        rows = list(provider.list_all(limit=limit, include_closed=True))
        if len(rows) >= limit:
            raise RuntimeError(
                "feedback provider returned the page limit; exhaustive feedback export is unavailable"
            )
    except (KeyError, RuntimeError, TypeError, ValueError) as exc:
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


def build_surreal_migration_map(*, categories: dict[str, dict[str, Any]]) -> SurrealMigrationMap:
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
