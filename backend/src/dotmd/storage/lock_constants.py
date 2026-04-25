"""Shared lock-table name constants for Phase 16.

Extracted from migration_v16.py so that runtime modules (trickle.py) can
import the lock-table name without taking a dependency on the migration
module — which would create a cross-module runtime coupling between the
production ingestion path and the offline migration tool.

Usage:
    from dotmd.storage.lock_constants import LOCK_TABLE
"""

LOCK_TABLE: str = "migration_v16_lock"
