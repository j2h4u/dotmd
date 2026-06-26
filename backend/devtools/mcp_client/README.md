# MCP Test Client

Small stdio MCP client for regression testing the dotMD MCP server over its
stdio transport. Ported from `mcp-telegram/devtools/mcp_client`; same
client/cli/script schema.

## Usage

Run from `backend/`. Pass the server command after `--`.

```bash
uv run python -m devtools.mcp_client.cli list-tools -- docker exec -i dotmd dotmd mcp
```

```bash
uv run python -m devtools.mcp_client.cli call-tool \
  --name search \
  --arguments '{"query":"SurrealDB вектора graph","top_k":5}' \
  --timeout 60 \
  -- docker exec -i dotmd dotmd mcp
```

```bash
uv run python -m devtools.mcp_client.cli call-tool --name read --arguments '{"ref":"filesystem:/mnt/..."}' \
  -- docker exec -i dotmd dotmd mcp
```

## Smoke Test

End-to-end check of all 4 lowercase tools plus schema invariants:

```bash
uv run python -m devtools.mcp_client.cli script \
  --file devtools/mcp_client/smoke.json \
  --timeout 120 \
  -- docker exec -i dotmd dotmd mcp
```

For live HTTP validation against the running container, use `just test-e2e`.

The smoke step that calls `search` triggers cold-start of TEI + GLiNER + the
cross-encoder reranker on first run, which can take 15-20 s. Subsequent calls
are fast (~hundreds of ms).

## Script Format

```json
{
  "steps": [
    {"action": "list_tools"},
    {
      "action": "call_tool",
      "name": "search",
      "arguments": {"query": "SurrealDB вектора graph", "top_k": 5}
    }
  ]
}
```

Supported assertions:

- `expect.tool_names_include` — list of tool names that must be present
- `expect.tool_expectations` — per-tool `path.to.field`: expected_value pairs
  on the tool descriptor (typed inputSchema checks)
- `expect.path_equals` — same, but for `call_tool` results
- `expect.is_error` — assert the tool result `isError` flag
- `expect.content_text_contains` / `expect.content_text_not_contains` —
  substring match on the textual portion of `content[]`
