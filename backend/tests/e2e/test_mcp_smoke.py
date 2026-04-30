"""MCP smoke tests — run inside the dotMD container against the live server.

Parametrized over two transports (http, stdio) — same assertions, both must pass.

Usage:
    docker exec dotmd sh -c "cd /mnt/home/repos/j2h4u/dotmd/backend && \
        python -m pytest tests/e2e/ -v -p no:cacheprovider"

PINNING CONTRACT
---------------
EXPECTED_TOOLS is the authoritative list of supported MCP tools.
test_tool_surface enforces an exact match — adding or removing a tool without
updating this set fails the suite immediately. This prevents silent drift where
new tools ship without smoke coverage.

Workflow when adding a new tool:
  1. Add the tool name to EXPECTED_TOOLS.
  2. Add a smoke test class for it below (call + field shape check).
  3. Run the suite to confirm green.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.e2e.conftest import _is_tool_error, _tool_result_structured, _tool_result_text

pytestmark = pytest.mark.e2e

# ---------------------------------------------------------------------------
# Pinned surface contracts
# ---------------------------------------------------------------------------

# KEEP IN SYNC WITH mcp_server.py.
# Exact match — test_tool_surface will fail if actual != expected.
EXPECTED_TOOLS: frozenset[str] = frozenset({"search", "read", "feedback"})

# Fields always present in every search result dict.
REQUIRED_SEARCH_RESULT_FIELDS: frozenset[str] = frozenset({"file_paths", "snippet", "score"})
# heading is optional — present only for docs with markdown headings.
OPTIONAL_SEARCH_RESULT_FIELDS: frozenset[str] = frozenset({"heading"})

# Top-level keys returned by read().
EXPECTED_READ_KEYS: frozenset[str] = frozenset({"file_path", "total_chunks", "frontmatter", "chunks"})


# ---------------------------------------------------------------------------
# Surface contract
# ---------------------------------------------------------------------------


class TestToolSurface:
    """Exact tool list — fails immediately when surface changes without test coverage."""

    def test_tool_list_matches_pinned(self, mcp_call: Callable):
        data = mcp_call("tools/list")
        assert "result" in data, f"unexpected response: {data}"
        actual = frozenset(t["name"] for t in data["result"]["tools"])
        assert actual == EXPECTED_TOOLS, (
            f"MCP tool surface changed!\n"
            f"  Pinned : {sorted(EXPECTED_TOOLS)}\n"
            f"  Actual : {sorted(actual)}\n"
            f"  Added  : {sorted(actual - EXPECTED_TOOLS)}\n"
            f"  Removed: {sorted(EXPECTED_TOOLS - actual)}\n"
            "→ Add smoke tests for new tools, then update EXPECTED_TOOLS."
        )


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


class TestSearchSmoke:
    def test_returns_results_for_generic_query(self, mcp_call: Callable):
        data = mcp_call("tools/call", {"name": "search", "arguments": {"query": "встреча", "top_k": 3}})
        assert not _is_tool_error(data), f"search returned error: {_tool_result_text(data)}"
        results = _tool_result_structured(data)
        assert isinstance(results, list), f"search must return a list, got: {type(results)}"
        assert len(results) > 0, "search returned no results — index may be empty"

    def test_result_fields_match_pinned(self, mcp_call: Callable):
        """Required fields always present; heading may be absent (optional)."""
        data = mcp_call("tools/call", {"name": "search", "arguments": {"query": "тест"}})
        results = _tool_result_structured(data)
        if not results:
            pytest.skip("no results to check fields against")
        actual_keys = frozenset(results[0].keys())
        allowed = REQUIRED_SEARCH_RESULT_FIELDS | OPTIONAL_SEARCH_RESULT_FIELDS
        assert actual_keys >= REQUIRED_SEARCH_RESULT_FIELDS, (
            f"search result missing required fields!\n"
            f"  Required: {sorted(REQUIRED_SEARCH_RESULT_FIELDS)}\n"
            f"  Actual  : {sorted(actual_keys)}"
        )
        assert actual_keys <= allowed, (
            f"search result contains unexpected fields!\n"
            f"  Allowed: {sorted(allowed)}\n"
            f"  Actual : {sorted(actual_keys)}\n"
            f"  Unknown: {sorted(actual_keys - allowed)}"
        )

    def test_file_paths_is_list(self, mcp_call: Callable):
        data = mcp_call("tools/call", {"name": "search", "arguments": {"query": "тест"}})
        results = _tool_result_structured(data)
        if not results:
            pytest.skip("no results to check")
        assert isinstance(results[0]["file_paths"], list)
        assert all(isinstance(p, str) for p in results[0]["file_paths"])

    def test_score_is_float_in_range(self, mcp_call: Callable):
        data = mcp_call("tools/call", {"name": "search", "arguments": {"query": "тест"}})
        results = _tool_result_structured(data)
        if not results:
            pytest.skip("no results to check")
        score = results[0]["score"]
        assert isinstance(score, float), f"score must be float, got {type(score)}"
        assert 0.0 <= score <= 1.0, f"score out of range: {score}"

    def test_top_k_respected(self, mcp_call: Callable):
        data = mcp_call("tools/call", {"name": "search", "arguments": {"query": "тест", "top_k": 2}})
        results = _tool_result_structured(data)
        assert len(results) <= 2, f"top_k=2 but got {len(results)} results"


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


class TestReadSmoke:
    def test_meta_only_returns_without_error(self, mcp_call: Callable):
        """read without end returns frontmatter + total_chunks, no chunk text."""
        search = mcp_call("tools/call", {"name": "search", "arguments": {"query": "встреча", "top_k": 1}})
        results = _tool_result_structured(search)
        if not results:
            pytest.skip("search returned no results — cannot test read")

        file_path = results[0]["file_paths"][0]
        data = mcp_call("tools/call", {"name": "read", "arguments": {"file_path": file_path}})
        assert not _is_tool_error(data), f"read errored on {file_path}: {_tool_result_text(data)}"

        payload = _tool_result_structured(data)
        assert isinstance(payload, dict)
        actual_keys = frozenset(payload.keys())
        assert actual_keys == EXPECTED_READ_KEYS, (
            f"read result fields changed!\n"
            f"  Pinned: {sorted(EXPECTED_READ_KEYS)}\n"
            f"  Actual: {sorted(actual_keys)}"
        )
        assert payload["chunks"] == [], "meta-only call (no end) must return empty chunks"
        assert isinstance(payload["total_chunks"], int)
        assert payload["total_chunks"] > 0
        assert isinstance(payload["frontmatter"], dict)

    def test_ranged_read_returns_chunks(self, mcp_call: Callable):
        """read with end returns chunk text in [start, end)."""
        search = mcp_call("tools/call", {"name": "search", "arguments": {"query": "встреча", "top_k": 1}})
        results = _tool_result_structured(search)
        if not results:
            pytest.skip("search returned no results — cannot test read")

        file_path = results[0]["file_paths"][0]
        data = mcp_call("tools/call", {"name": "read", "arguments": {"file_path": file_path, "start": 0, "end": 3}})
        assert not _is_tool_error(data), f"read errored: {_tool_result_text(data)}"

        payload = _tool_result_structured(data)
        assert len(payload["chunks"]) <= 3
        for chunk in payload["chunks"]:
            assert "index" in chunk
            assert "text" in chunk
            assert isinstance(chunk["text"], str)
            assert len(chunk["text"]) > 0

    def test_nonexistent_path_returns_empty(self, mcp_call: Callable):
        """read on a missing file returns empty frontmatter and zero chunks, not a crash."""
        data = mcp_call("tools/call", {"name": "read", "arguments": {"file_path": "/nonexistent/file.md"}})
        assert not data.get("error"), f"protocol-level error: {data.get('error')}"
        assert "result" in data
        payload = _tool_result_structured(data)
        assert payload["total_chunks"] == 0
        assert payload["chunks"] == []

    def test_cap_at_50_chunks(self, mcp_call: Callable):
        """end - start > 50 is capped server-side."""
        search = mcp_call("tools/call", {"name": "search", "arguments": {"query": "встреча", "top_k": 1}})
        results = _tool_result_structured(search)
        if not results:
            pytest.skip("no results")

        file_path = results[0]["file_paths"][0]
        data = mcp_call("tools/call", {"name": "read", "arguments": {"file_path": file_path, "start": 0, "end": 200}})
        payload = _tool_result_structured(data)
        assert len(payload["chunks"]) <= 50, f"cap not enforced: got {len(payload['chunks'])} chunks"


# ---------------------------------------------------------------------------
# feedback
# ---------------------------------------------------------------------------


class TestFeedbackSmoke:
    """Pinning + behavior checks for the feedback tool.

    Two regression anchors:
      1. Lowercase tool name.
      2. Optional parameters serialize as flat strings — the JSON Schema MUST
         NOT contain ``anyOf: [{type: ...}, {type: null}]`` because Claude
         Desktop renders that as broken UI. The _collapse_null hook enforces this.
    """

    def _props(self, mcp_call: Callable) -> dict:
        data = mcp_call("tools/list")
        tools = {t["name"]: t for t in data["result"]["tools"]}
        assert "feedback" in tools, "feedback missing from tools/list"
        return tools["feedback"]["inputSchema"]["properties"]

    def test_message_is_required_string(self, mcp_call: Callable):
        props = self._props(mcp_call)
        assert props["message"]["type"] == "string"
        assert props["message"].get("minLength") == 1
        assert props["message"].get("maxLength") == 10000

    def test_optional_params_have_no_anyOf_null(self, mcp_call: Callable):
        """severity/context/model/harness must NOT carry anyOf:[T, null].

        Regression anchor for the _collapse_null hook in mcp_server.py.
        """
        props = self._props(mcp_call)
        for field in ("severity", "context", "model", "harness"):
            schema = props[field]
            assert "anyOf" not in schema, (
                f"feedback.{field} has anyOf — _collapse_null is broken.\n"
                f"  Got: {schema}\n"
                "  Expected: a flat schema (e.g., {'type': 'string'} or {'enum': [...]})."
            )
            assert "default" not in schema, (
                f"feedback.{field} should not expose default:null in the schema. "
                f"Got: {schema}"
            )

    def test_severity_enum_preserved(self, mcp_call: Callable):
        """After collapsing the null variant, severity's Literal must still be honored."""
        props = self._props(mcp_call)
        sev = props["severity"]
        assert sev.get("enum") == ["bug", "suggestion", "question"], (
            f"severity enum drift — expected ['bug','suggestion','question'], got {sev!r}"
        )

    def test_empty_message_returns_not_recorded(self, mcp_call: Callable):
        """Whitespace-only messages early-return without persisting a row."""
        data = mcp_call("tools/call", {
            "name": "feedback",
            "arguments": {"message": "   "},
        })
        assert not _is_tool_error(data), f"unexpected error: {_tool_result_text(data)}"
        text = _tool_result_text(data).lower()
        assert "not recorded" in text, (
            f"expected 'not recorded' marker, got: {_tool_result_text(data)!r}"
        )

    def test_happy_path_records_and_cleans_up(self, mcp_call: Callable):
        """Submit a marker-tagged feedback row, verify it persists, then remove it."""
        import sqlite3
        import uuid

        from dotmd.core.config import Settings

        marker = f"__e2e_smoke__{uuid.uuid4().hex[:12]}"
        message = f"{marker} (delete me — emitted by tests/e2e/test_mcp_smoke.py)"

        data = mcp_call("tools/call", {
            "name": "feedback",
            "arguments": {
                "message": message,
                "severity": "question",
                "context": "smoke test",
                "model": "pytest",
                "harness": "e2e",
            },
        })
        assert not _is_tool_error(data), f"feedback errored: {_tool_result_text(data)}"
        assert "recorded" in _tool_result_text(data).lower()

        feedback_db = Settings().index_dir / "feedback.db"
        try:
            conn = sqlite3.connect(str(feedback_db))
            try:
                row = conn.execute(
                    "SELECT severity, context, model, harness "
                    "FROM feedback WHERE message = ?",
                    (message,),
                ).fetchone()
                assert row is not None, f"feedback row not persisted in {feedback_db}"
                assert row == ("question", "smoke test", "pytest", "e2e")
            finally:
                conn.close()
        finally:
            conn = sqlite3.connect(str(feedback_db))
            try:
                conn.execute("DELETE FROM feedback WHERE message LIKE ?", (f"{marker}%",))
                conn.commit()
            finally:
                conn.close()
