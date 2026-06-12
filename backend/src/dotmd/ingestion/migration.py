"""One-time migration from legacy schema to Phase 12 unified index.db.

Migrates:
  metadata.db + vec.db  →  index.db

All tables get strategy and/or model suffixes.
Original files are renamed to .migrated (not deleted).
Backups are created as .bak before any changes.

Run standalone:
    python -m dotmd.ingestion.migration /path/to/index_dir
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


def needs_migration(index_dir: Path) -> bool:
    """Check if old schema (metadata.db without index.db) needs migration."""
    return (index_dir / "metadata.db").exists() and not (index_dir / "index.db").exists()


def run_migration(
    index_dir: Path,
    strategy: str = "heading_512_50",
    embedding_model: str = "intfloat/multilingual-e5-large",
) -> None:
    """Migrate legacy schema to unified index.db.

    Safe: backups created first, originals renamed (not deleted).
    """
    from dotmd.ingestion.pipeline import _model_to_table_suffix

    metadata_path = index_dir / "metadata.db"
    vec_path = index_dir / "vec.db"
    index_path = index_dir / "index.db"

    if not metadata_path.exists():
        logger.info("No metadata.db found — nothing to migrate")
        return
    if index_path.exists():
        logger.info("index.db already exists — migration already done")
        return

    model_suffix = _model_to_table_suffix(embedding_model)
    logger.info(
        "Starting migration: strategy=%s, model=%s (suffix=%s)",
        strategy,
        embedding_model,
        model_suffix,
    )

    # ------------------------------------------------------------------
    # Step 0: Backup
    # ------------------------------------------------------------------
    shutil.copy2(metadata_path, index_dir / "metadata.db.bak")
    if vec_path.exists():
        shutil.copy2(vec_path, index_dir / "vec.db.bak")
    logger.info("Backups created (.bak)")

    # ------------------------------------------------------------------
    # Step 1: Create index.db with sqlite-vec extension
    # ------------------------------------------------------------------
    conn = sqlite3.connect(str(index_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.enable_load_extension(True)
    try:
        import sqlite_vec

        sqlite_vec.load(conn)
    except Exception:
        logger.warning("sqlite-vec extension not available — vec tables will be skipped")
    conn.enable_load_extension(False)

    # Register hash UDF for text_hash computation during migration
    conn.create_function(
        "blake2b_hash",
        1,
        lambda t: hashlib.blake2b(t.encode()).hexdigest() if t else None,
    )

    try:
        _copy_metadata(conn, metadata_path, strategy, model_suffix)
        if vec_path.exists():
            _copy_vectors(conn, vec_path, strategy, model_suffix)
        _rename_graph(index_dir, strategy)
        _verify(conn, strategy, model_suffix)
        conn.commit()
    except Exception:
        conn.close()
        # Remove partial index.db on failure — backups are safe
        if index_path.exists():
            index_path.unlink()
        logger.exception("Migration FAILED — index.db removed, originals untouched")
        raise

    conn.close()

    # ------------------------------------------------------------------
    # Step 7: Rename old files (not delete)
    # ------------------------------------------------------------------
    _safe_rename(metadata_path, index_dir / "metadata.db.migrated")
    if vec_path.exists():
        _safe_rename(vec_path, index_dir / "vec.db.migrated")
    # WAL/SHM files
    for base in [metadata_path, vec_path]:
        for ext in ["-wal", "-shm"]:
            f = Path(str(base) + ext)
            if f.exists():
                _safe_rename(f, Path(str(base) + ".migrated" + ext))

    logger.info("Migration complete. Old files renamed to .migrated")


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _copy_metadata(
    conn: sqlite3.Connection,
    metadata_path: Path,
    strategy: str,
    model_suffix: str,
) -> None:
    """Copy chunks, FTS5, fingerprints, stats from old metadata.db."""
    conn.execute(f"ATTACH '{metadata_path}' AS meta_old")

    # -- chunks --------------------------------------------------------
    conn.execute(f"CREATE TABLE chunks_{strategy} AS SELECT * FROM meta_old.chunks")
    conn.execute(f"CREATE INDEX idx_chunks_{strategy}_file_path ON chunks_{strategy}(file_path)")
    chunks_count = conn.execute(f"SELECT COUNT(*) FROM chunks_{strategy}").fetchone()[0]
    logger.info("Copied chunks_%s: %d rows", strategy, chunks_count)

    # -- FTS5 ----------------------------------------------------------
    conn.execute(
        f"CREATE VIRTUAL TABLE chunks_fts_{strategy} USING fts5("
        "chunk_id UNINDEXED, text, tokenize = 'unicode61')"
    )
    conn.execute(
        f"INSERT INTO chunks_fts_{strategy}(chunk_id, text) "
        "SELECT chunk_id, text FROM meta_old.chunks_fts"
    )
    fts_count = conn.execute(f"SELECT COUNT(*) FROM chunks_fts_{strategy}").fetchone()[0]
    logger.info("Copied chunks_fts_%s: %d rows", strategy, fts_count)

    # -- chunk_fingerprints (from UNION of all model fp tables) --------
    fp_tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM meta_old.sqlite_master "
            "WHERE name LIKE 'file_fingerprints%' AND type='table'"
        ).fetchall()
    ]
    logger.info("Found fingerprint tables: %s", fp_tables)

    conn.execute(
        f"CREATE TABLE chunk_fingerprints_{strategy} ("
        "file_path TEXT PRIMARY KEY, mtime REAL NOT NULL, "
        "size_bytes INTEGER NOT NULL, checksum TEXT NOT NULL, "
        "indexed_at TEXT NOT NULL)"
    )
    # INSERT OR IGNORE: first table's data wins per file_path
    for fp_table in fp_tables:
        conn.execute(
            f"INSERT OR IGNORE INTO chunk_fingerprints_{strategy} "
            f"SELECT file_path, mtime, size_bytes, checksum, indexed_at "
            f"FROM meta_old.{fp_table}"
        )
    chunk_fp_count = conn.execute(f"SELECT COUNT(*) FROM chunk_fingerprints_{strategy}").fetchone()[
        0
    ]
    logger.info("Created chunk_fingerprints_%s: %d rows", strategy, chunk_fp_count)

    # -- embed_fingerprints (per model, skip legacy unsuffixed) --------
    for fp_table in fp_tables:
        old_suffix = fp_table.replace("file_fingerprints", "")
        if not old_suffix:
            # Legacy table (no suffix) — skip
            logger.info("Skipping legacy %s", fp_table)
            continue
        new_name = f"embed_fingerprints_{strategy}{old_suffix}"
        conn.execute(f"CREATE TABLE {new_name} AS SELECT * FROM meta_old.{fp_table}")
        count = conn.execute(f"SELECT COUNT(*) FROM {new_name}").fetchone()[0]
        logger.info("Created %s: %d rows", new_name, count)

    # -- stats ---------------------------------------------------------
    try:
        conn.execute("CREATE TABLE stats AS SELECT * FROM meta_old.stats")
    except sqlite3.OperationalError:
        conn.execute(
            "CREATE TABLE stats (id INTEGER PRIMARY KEY, "
            "total_files INTEGER, total_chunks INTEGER, total_entities INTEGER, "
            "total_edges INTEGER, last_indexed TEXT, new_files INTEGER, "
            "modified_files INTEGER, deleted_files INTEGER, unchanged_files INTEGER, "
            "data_dir TEXT)"
        )

    conn.execute("DETACH meta_old")
    conn.commit()


def _copy_vectors(
    conn: sqlite3.Connection,
    vec_path: Path,
    strategy: str,
    model_suffix: str,
) -> None:
    """Copy vec tables from old vec.db to unified index.db."""
    conn.execute(f"ATTACH '{vec_path}' AS vec_old")

    # Find model-specific vec_meta tables (skip legacy unsuffixed)
    meta_tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM vec_old.sqlite_master WHERE name LIKE 'vec_meta_%' AND type='table'"
        ).fetchall()
    ]
    logger.info("Found vec_meta tables: %s", meta_tables)

    for old_meta in meta_tables:
        old_suffix = old_meta.replace("vec_meta", "")  # e.g., "_multilingual_e5_large"
        old_vec = f"vec_chunks{old_suffix}"
        old_config = f"vec_config{old_suffix}"

        new_meta = f"vec_meta_{strategy}{old_suffix}"
        new_vec = f"vec_chunks_{strategy}{old_suffix}"
        new_config = f"vec_config_{strategy}{old_suffix}"

        # Get dimensionality
        try:
            dim_row = conn.execute(
                f"SELECT value FROM vec_old.{old_config} WHERE key='dim'"
            ).fetchone()
            dim = int(dim_row[0]) if dim_row else 1024
        except sqlite3.OperationalError:
            dim = 1024
            logger.warning("No %s found, assuming dim=%d", old_config, dim)

        # vec_meta with text_hash
        conn.execute(
            f"CREATE TABLE {new_meta} ("
            "rowid INTEGER PRIMARY KEY AUTOINCREMENT, "
            "chunk_id TEXT NOT NULL, "
            "text_hash TEXT)"
        )
        conn.execute(
            f"INSERT INTO {new_meta}(rowid, chunk_id) "
            f"SELECT rowid, chunk_id FROM vec_old.{old_meta}"
        )

        # Populate text_hash from chunks
        updated = conn.execute(
            f"UPDATE {new_meta} SET text_hash = ("
            f"SELECT blake2b_hash(text) FROM chunks_{strategy} "
            f"WHERE chunk_id = {new_meta}.chunk_id)"
        ).rowcount
        logger.info(
            "Populated text_hash for %s: %d/%d",
            new_meta,
            updated,
            conn.execute(f"SELECT COUNT(*) FROM {new_meta}").fetchone()[0],
        )

        # vec0 virtual table + copy embeddings
        conn.execute(f"CREATE VIRTUAL TABLE {new_vec} USING vec0(embedding float[{dim}])")

        # Read all embeddings via JOIN from old DB
        rows = conn.execute(
            f"SELECT vm.rowid, vc.embedding "
            f"FROM vec_old.{old_meta} vm "
            f"JOIN vec_old.{old_vec} vc ON vm.rowid = vc.rowid"
        ).fetchall()

        # Insert into new table
        for rowid, embedding in rows:
            conn.execute(
                f"INSERT INTO {new_vec}(rowid, embedding) VALUES (?, ?)",
                (rowid, embedding),
            )

        # vec_config
        try:
            conn.execute(f"CREATE TABLE {new_config} AS SELECT * FROM vec_old.{old_config}")
        except sqlite3.OperationalError:
            logger.warning("No %s to copy", old_config)

        logger.info(
            "Migrated %s: %d vectors (%d-dim)",
            new_vec,
            len(rows),
            dim,
        )

    conn.execute("DETACH vec_old")
    conn.commit()


def _rename_graph(index_dir: Path, strategy: str) -> None:
    """Rename graphdb → graphdb_{strategy}."""
    old = index_dir / "graphdb"
    new = index_dir / f"graphdb_{strategy}"
    if old.exists() and not new.exists():
        old.rename(new)
        logger.info("Renamed graphdb → graphdb_%s", strategy)


def _verify(conn: sqlite3.Connection, strategy: str, model_suffix: str) -> None:
    """Log row counts for verification."""
    logger.info("--- Verification ---")
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]
    for t in tables:
        try:
            n = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            logger.info("  %s: %d rows", t, n)
        except Exception:
            logger.info("  %s: (virtual table)", t)


def _safe_rename(src: Path, dst: Path) -> None:
    """Rename file, overwriting destination if it exists."""
    if dst.exists():
        dst.unlink()
    src.rename(dst)


# ------------------------------------------------------------------
# Standalone entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    from dotmd.utils.logging import setup_logging

    setup_logging(verbose=True)
    index_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / ".dotmd"
    if needs_migration(index_dir):
        run_migration(index_dir)
    else:
        print("No migration needed")
