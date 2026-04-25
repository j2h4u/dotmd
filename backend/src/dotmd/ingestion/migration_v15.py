"""Superseded by migration_v16 (Phase 16). No-op stub.

This module is intentionally a no-op. The one-time chunk_id migration
is now performed by migration_v16.py which also handles the M2M schema
transition (content-dedup Phase 16).

Removal is deferred to the release cycle after Phase 16 ships; tracked
as GSD backlog item 999.7 (Decision #9). Do NOT delete this file in
Phase 16.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_MSG = (
    "migration_v15 is superseded by migration_v16 — this script is a "
    "no-op. Run `dotmd migrate` to apply the Phase 16 migration instead."
)


def needs_migration_v15(index_db_path: Path) -> bool:  # noqa: ARG001
    """Always returns False. Superseded by migration_v16."""
    logger.info(_MSG)
    return False


def run_migration_v15(index_db_path: Path, *args, **kwargs) -> None:  # noqa: ARG001
    """No-op stub. Superseded by migration_v16."""
    logger.info(_MSG)
