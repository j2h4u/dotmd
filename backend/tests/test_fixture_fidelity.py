"""Fixture fidelity tests — three-layer assertion suite (Task 1 cycle-2 MEDIUM fix).

Layer 1 (weak, retained for readability):
    DDL-signature presence check — every expected table/index name appears in
    schema_pre_v16.sql.

Layer 2 (strong, new — closes cycle-2 MEDIUM):
    Set-equivalence of CREATE statements after whitespace-normalisation between
    the fixture-built DB and the committed schema_pre_v16.sqlite.dump reference.
    Catches column ordering, index drift, auxiliary table omissions — anything
    beyond raw name presence.

Layer 3 (sanity floor):
    Reference dump is non-empty and contains at least 10 CREATE TABLE statements.

Rationale: asserting DDL signatures alone would pass even if column ordering,
index definitions, or auxiliary tables drift.  Set-equivalence of CREATE
statements after whitespace-normalisation catches real divergence while
tolerating cosmetic differences (trailing newlines, indentation) that are
too brittle for a one-user local project.  Full byte-exact diff was rejected
as too brittle per cycle-2 MEDIUM guidance.
"""

from __future__ import annotations

import re
import sqlite3
import tempfile
from pathlib import Path

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_SCHEMA_SQL = _FIXTURES_DIR / "schema_pre_v16.sql"
_SCHEMA_DUMP = _FIXTURES_DIR / "schema_pre_v16.sqlite.dump"

# Strategies expected in the pre-v16 schema
_STRATEGIES = ["heading_512_50", "contextual_512_50"]


def _normalise(text: str) -> set[str]:
    """Normalise CREATE statements for set-equivalence comparison.

    Handles two input formats:
    - Reference dump (schema_pre_v16.sqlite.dump): statements end with ';'
    - sqlite_master rows joined with '\\n': no trailing semicolons; each
      statement begins on a new line that starts with CREATE/CREATE VIRTUAL/
      CREATE INDEX/CREATE TABLE/CREATE UNIQUE.

    Strategy:
      1. Try splitting on semicolons (reference dump format).
      2. Fall back to splitting on the start of new CREATE keywords when no
         semicolons are found.

    Returns a set of normalised CREATE statements with internal whitespace
    collapsed to single spaces.  Non-CREATE content is silently ignored.
    """
    stripped = text.strip()

    # If the text contains semicolons, split on them (reference dump format)
    if ";" in stripped:
        # Also handle the last statement which may not end with ;
        raw_stmts = re.split(r";[ \t]*\n?", stripped)
    else:
        # sqlite_master format: split on blank lines or on the start of a new
        # top-level CREATE statement.  Each row from sqlite_master is already
        # a complete statement without semicolon.
        # Split on double-newlines first, then re-split within each block on
        # lines that start with CREATE (catching multi-row DDL like stats table
        # whose CREATE spans many lines).
        raw_stmts = re.split(r"\n(?=CREATE )", stripped)

    result = set()
    for s in raw_stmts:
        # Strip trailing semicolon and whitespace
        s = s.rstrip("; \t\n").strip()
        if not s:
            continue
        # Normalise internal whitespace to single spaces
        s = re.sub(r"\s+", " ", s)
        if re.match(r"CREATE\b", s, re.IGNORECASE):
            # Exclude internal SQLite tables (sqlite_sequence, etc.)
            if "sqlite_sequence" not in s:
                result.add(s)
    return result


class TestDDLSignaturePresence:
    """Layer 1: weak DDL-signature check retained for readability."""

    def test_schema_pre_v16_sql_contains_required_ddl_signatures(self) -> None:
        """schema_pre_v16.sql contains CREATE TABLE for every expected table."""
        content = _SCHEMA_SQL.read_text()

        for strategy in _STRATEGIES:
            assert f"chunks_{strategy}" in content, (
                f"Missing chunks_{strategy} in schema_pre_v16.sql"
            )
            assert f"chunks_fts_{strategy}" in content, (
                f"Missing chunks_fts_{strategy} in schema_pre_v16.sql"
            )
            assert f"vec_meta_{strategy}" in content, (
                f"Missing vec_meta_{strategy} in schema_pre_v16.sql"
            )
            assert f"chunk_fingerprints_{strategy}" in content, (
                f"Missing chunk_fingerprints_{strategy} in schema_pre_v16.sql"
            )

        # migration_v15_state is NOT in the reference dump (Phase 15 never ran on
        # production). migration_v16.py creates it during migration. The fixture
        # SQL mirrors actual production state — no migration_v15_state table.
        assert "file_path" in content, (
            "schema_pre_v16.sql should contain file_path column (pre-v16 shape)"
        )
        assert "chunk_index" in content, (
            "schema_pre_v16.sql should contain chunk_index column (pre-v16 shape)"
        )
        assert "char_offset" in content, (
            "schema_pre_v16.sql should contain char_offset column (pre-v16 shape)"
        )


class TestByteEquivalenceFidelity:
    """Layer 2: strong set-equivalence check against committed reference dump."""

    def test_fixture_schema_byte_matches_reference_dump(self) -> None:
        """Fixture DB schema matches the committed reference dump (set-equivalence).

        Steps:
          1. Build a temp DB via executescript(schema_pre_v16.sql).
          2. Extract its CREATE statements via sqlite_master.
          3. Load the committed reference dump.
          4. Normalise both sides and compare as equal sets.
        """
        ddl = _SCHEMA_SQL.read_text()
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "fidelity_test.db"
            conn = sqlite3.connect(str(db_path))
            conn.executescript(ddl)

            rows = conn.execute(
                "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name"
            ).fetchall()
            actual_text = "\n".join(r[0] for r in rows)
            conn.close()

        reference_text = _SCHEMA_DUMP.read_text()

        actual_set = _normalise(actual_text)
        reference_set = _normalise(reference_text)

        in_fixture_not_in_ref = actual_set - reference_set
        in_ref_not_in_fixture = reference_set - actual_set

        assert actual_set == reference_set, (
            f"Fixture schema drifted from reference dump.\n"
            f"In fixture NOT in reference ({len(in_fixture_not_in_ref)}):\n"
            + "\n".join(f"  {s[:120]}" for s in sorted(in_fixture_not_in_ref))
            + f"\nIn reference NOT in fixture ({len(in_ref_not_in_fixture)}):\n"
            + "\n".join(f"  {s[:120]}" for s in sorted(in_ref_not_in_fixture))
        )


class TestReferenceDumpSanity:
    """Layer 3: sanity floor — reference dump is non-empty and well-formed."""

    def test_reference_dump_is_committed_and_non_empty(self) -> None:
        """schema_pre_v16.sqlite.dump exists and has >= 10 CREATE TABLE statements."""
        assert _SCHEMA_DUMP.exists(), (
            "schema_pre_v16.sqlite.dump is missing — run Task 1 step 5 to regenerate"
        )

        content = _SCHEMA_DUMP.read_text()
        assert len(content) > 100, "schema_pre_v16.sqlite.dump is suspiciously short"

        create_table_count = len(re.findall(r"^\s*CREATE TABLE", content, re.MULTILINE | re.IGNORECASE))
        assert create_table_count >= 10, (
            f"Expected >= 10 CREATE TABLE statements in reference dump, "
            f"found {create_table_count}. "
            f"Sanity floor: chunks_*, vec_meta_*, fingerprints across >= 2 strategies."
        )
