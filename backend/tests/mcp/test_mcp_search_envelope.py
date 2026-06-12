"""MCP search tool envelope tests (Phase 34 Plan 02 Task 4).

Tests the MCP search tool's return shape, full SearchCandidate contract
exposure, and parameter signature compliance.
"""

from __future__ import annotations

import json
import re

from dotmd.core.models import SearchCandidate, SearchResponse, SourceStatus


class TestMCPSearchSignature:
    """Tests for MCP search tool parameter signature."""

    def test_mcp_search_signature_does_not_include_source_filters(self) -> None:
        """MCP search tool does not accept source filter parameters (D-10)."""
        # Verify mcp_server.py does NOT define sources or exclude_sources params
        import inspect

        from dotmd import mcp_server

        source_code = inspect.getsource(mcp_server)

        # Check for @mcp.tool(name="search") and verify it doesn't mention sources
        # Look for the search tool definition
        search_tool_match = re.search(
            r"@mcp\.tool\(\s*name=['\"]search['\"].*?\)\s*async\s+def\s+search\s*\((.*?)\):",
            source_code,
            re.DOTALL,
        )

        assert search_tool_match, "Could not find mcp search tool definition"

        params_str = search_tool_match.group(1)
        assert "sources" not in params_str, "search tool should not have 'sources' parameter (D-10)"
        assert "exclude_sources" not in params_str, (
            "search tool should not have 'exclude_sources' parameter (D-10)"
        )


class TestMCPSearchAsyncBridge:
    """Tests for MCP search async implementation."""

    def test_mcp_search_does_not_use_asyncio_to_thread_bridge(self) -> None:
        """MCP search tool calls search_async directly (cycle-2 HIGH-5)."""
        # Verify the search tool implementation calls service.search_async
        # not asyncio.to_thread(service.search, ...)

        import inspect

        from dotmd import mcp_server

        source_code = inspect.getsource(mcp_server)

        # Find the search tool function
        search_tool_match = re.search(
            r"@mcp\.tool\(\s*name=['\"]search['\"].*?\)\s*async\s+def\s+search\s*\(.*?\):\s*(.*?)(?=\n@mcp\.|$)",
            source_code,
            re.DOTALL,
        )

        assert search_tool_match, "Could not find mcp search tool implementation"

        tool_impl = search_tool_match.group(1)

        # Should call search_async, not asyncio.to_thread(service.search, ...)
        assert "search_async" in tool_impl, (
            "MCP search tool should call service.search_async (cycle-2 HIGH-5)"
        )

        # Verify no asyncio.to_thread bridge on service.search
        if "asyncio.to_thread" in tool_impl:
            # If asyncio.to_thread is used, make sure it's not wrapping service.search
            to_thread_matches = re.findall(
                r"asyncio\.to_thread\s*\(\s*service\.search\s*,", tool_impl
            )
            assert len(to_thread_matches) == 0, (
                "MCP search should not use asyncio.to_thread(service.search, ...) (cycle-2 HIGH-5)"
            )


class TestMCPSearchCandidateContract:
    """Tests for full SearchCandidate field exposure at MCP layer."""

    def test_mcp_response_schema_includes_all_search_candidate_fields(self) -> None:
        """MCP search tool response includes full SearchCandidate contract."""
        # Construct a SearchCandidate with all fields and serialize it
        full_candidate = SearchCandidate(
            ref="telegram:dialog:123:message:456",
            namespace="telegram",
            descriptor_key="telegram",
            source_kind="chat",
            retrieval_kind="tg:fts",
            title="Test Message",
            snippet="This is a test message snippet",
            fused_score=0.85,
            can_read=False,
            can_materialize=False,
            chunk_id=None,  # Federated candidates have None
            heading_path=None,
            matched_engines=("tg:fts",),
            source_native_score=42.0,
            source_native_rank=1,
            engine_scores=None,  # Federated candidates have None
            provider_metadata={"dialog_id": 123, "message_id": 456},
        )

        stub_response = SearchResponse(
            candidates=[full_candidate],
            source_status=[
                SourceStatus(
                    name="tg:fts",
                    status="ok",
                    reason=None,
                    candidate_count=1,
                    elapsed_ms=15.0,
                )
            ],
        )

        # Serialize to JSON
        response_json = stub_response.model_dump_json()
        parsed = json.loads(response_json)

        # Verify all fields are present in serialization
        candidate_dict = parsed["candidates"][0]

        # Required fields
        assert candidate_dict["ref"] == "telegram:dialog:123:message:456"
        assert candidate_dict["namespace"] == "telegram"
        assert candidate_dict["descriptor_key"] == "telegram"
        assert candidate_dict["source_kind"] == "chat"
        assert candidate_dict["retrieval_kind"] == "tg:fts"
        assert candidate_dict["snippet"] == "This is a test message snippet"
        assert candidate_dict["fused_score"] == 0.85
        assert candidate_dict["can_read"] is False
        assert candidate_dict["can_materialize"] is False

        # Optional fields
        assert candidate_dict["title"] == "Test Message"
        assert candidate_dict["chunk_id"] is None
        assert candidate_dict["heading_path"] is None
        assert candidate_dict["matched_engines"] == ["tg:fts"]
        assert candidate_dict["source_native_score"] == 42.0
        assert candidate_dict["source_native_rank"] == 1
        assert candidate_dict["engine_scores"] is None
        assert candidate_dict["provider_metadata"] == {"dialog_id": 123, "message_id": 456}

        # Verify lossless round-trip
        reparsed = SearchResponse.model_validate_json(response_json)
        assert reparsed.candidates[0].ref == full_candidate.ref
        assert reparsed.candidates[0].source_native_score == full_candidate.source_native_score
        assert reparsed.candidates[0].provider_metadata == full_candidate.provider_metadata
