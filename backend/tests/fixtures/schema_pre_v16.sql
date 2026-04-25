-- Canonical pre-v16 schema DDL.
-- Source: live production index.db from dotmd container (pre-Phase-16 state,
--         captured 2026-04-25).
-- Two strategies present: heading_512_50 and contextual_512_50.
-- Model: multilingual_e5_large.
--
-- This file is used by conftest.py fixtures via executescript() to build
-- test databases that mirror the production pre-v16 state byte-equivalently.
--
-- The companion file schema_pre_v16.sqlite.dump is the byte-level reference
-- (sqlite_master output from the live DB) used by test_fixture_fidelity.py
-- to verify that this SQL produces the identical schema.
--
-- NOTE: vec_chunks_* VIRTUAL TABLES (vec0) are intentionally omitted because
-- creating them requires the sqlite_vec extension loaded at connection time.
-- The migration tests that need vector data use the vec_meta_* plain tables
-- (which store chunk_id + text_hash) and mock or skip vec0 operations.
-- migration_v16_state is also omitted from the reference dump (Phase 15 never
-- ran on production); it is created by migration_v16.py itself.

CREATE TABLE chunk_fingerprints_contextual_512_50 (
    file_path   TEXT PRIMARY KEY,
    mtime       REAL    NOT NULL,
    size_bytes  INTEGER NOT NULL,
    checksum    TEXT    NOT NULL,
    indexed_at  TEXT    NOT NULL
);
CREATE TABLE chunk_fingerprints_heading_512_50 (
    file_path   TEXT PRIMARY KEY,
    mtime       REAL    NOT NULL,
    size_bytes  INTEGER NOT NULL,
    checksum    TEXT    NOT NULL,
    indexed_at  TEXT    NOT NULL
);
CREATE TABLE chunks_contextual_512_50 (
    chunk_id        TEXT PRIMARY KEY,
    file_path       TEXT    NOT NULL,
    heading_hierarchy TEXT  NOT NULL DEFAULT '[]',
    level           INTEGER NOT NULL DEFAULT 0,
    text            TEXT    NOT NULL DEFAULT '',
    chunk_index     INTEGER NOT NULL DEFAULT 0,
    char_offset     INTEGER NOT NULL DEFAULT 0
);
CREATE VIRTUAL TABLE chunks_fts_contextual_512_50 USING fts5(
    chunk_id UNINDEXED,
    text,
    title,
    tags,
    tokenize = 'unicode61'
);
CREATE VIRTUAL TABLE chunks_fts_heading_512_50 USING fts5(
    chunk_id UNINDEXED,
    text,
    tokenize = 'unicode61'
);
CREATE TABLE chunks_heading_512_50 (
    chunk_id        TEXT PRIMARY KEY,
    file_path       TEXT    NOT NULL,
    heading_hierarchy TEXT  NOT NULL DEFAULT '[]',
    level           INTEGER NOT NULL DEFAULT 0,
    text            TEXT    NOT NULL DEFAULT '',
    chunk_index     INTEGER NOT NULL DEFAULT 0,
    char_offset     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE embed_fingerprints_contextual_512_50_multilingual_e5_large (
    file_path   TEXT PRIMARY KEY,
    mtime       REAL    NOT NULL,
    size_bytes  INTEGER NOT NULL,
    checksum    TEXT    NOT NULL,
    indexed_at  TEXT    NOT NULL
);
CREATE TABLE embed_fingerprints_heading_512_50_multilingual_e5_large (
    file_path   TEXT PRIMARY KEY,
    mtime       REAL    NOT NULL,
    size_bytes  INTEGER NOT NULL,
    checksum    TEXT    NOT NULL,
    indexed_at  TEXT    NOT NULL
);
CREATE TABLE embedding_cache (
                text_hash  TEXT NOT NULL,
                model_name TEXT NOT NULL,
                embedding  BLOB NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (text_hash, model_name)
            );
CREATE TABLE embedding_cache_meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
CREATE TABLE extraction_cache (
                cache_key    TEXT PRIMARY KEY,
                entities_json  TEXT NOT NULL,
                co_occurs_json TEXT NOT NULL,
                created_at   TEXT NOT NULL DEFAULT (datetime('now'))
            );
CREATE TABLE extraction_cache_meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
CREATE INDEX idx_chunks_contextual_512_50_file_path ON chunks_contextual_512_50(file_path);
CREATE INDEX idx_chunks_heading_512_50_file_path ON chunks_heading_512_50(file_path);
CREATE TABLE stats (
    id              INTEGER PRIMARY KEY DEFAULT 1,
    total_files     INTEGER NOT NULL DEFAULT 0,
    total_chunks    INTEGER NOT NULL DEFAULT 0,
    total_entities  INTEGER NOT NULL DEFAULT 0,
    total_edges     INTEGER NOT NULL DEFAULT 0,
    last_indexed    TEXT
, new_files INTEGER NOT NULL DEFAULT 0, modified_files INTEGER NOT NULL DEFAULT 0, deleted_files INTEGER NOT NULL DEFAULT 0, unchanged_files INTEGER NOT NULL DEFAULT 0, data_dir TEXT);
CREATE TABLE vec_meta_contextual_512_50_multilingual_e5_large (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                chunk_id TEXT NOT NULL UNIQUE,
                text_hash TEXT
            );
CREATE TABLE vec_meta_heading_512_50_multilingual_e5_large (
                rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                chunk_id TEXT NOT NULL UNIQUE,
                text_hash TEXT
            );
