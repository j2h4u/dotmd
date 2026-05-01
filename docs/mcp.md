# dotMD MCP Server

dotMD exposes the indexed markdown knowledgebase as an MCP server so agents can search and read notes directly.

## Transports

### stdio

stdio is useful for local MCP clients that spawn a fresh dotMD process:

```bash
cd backend
uv run dotmd mcp
```

Generate a local client config:

```bash
cd backend
uv run dotmd mcp-config
```

Example client entry:

```json
{
  "mcpServers": {
    "dotmd": {
      "command": "/absolute/path/to/backend/.venv/bin/dotmd",
      "args": ["mcp"]
    }
  }
}
```

### streamable-http

HTTP transport is the production container path:

```bash
cd backend
uv run dotmd mcp --transport streamable-http --host 0.0.0.0 --port 8080
```

The Docker entrypoint runs the same command. Health is available at `GET /health`.

## Tools

### `search`

Search the indexed markdown knowledgebase.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | required | Natural-language search query |
| `top_k` | integer | `10` | Maximum results to return, 1-100 |

Returns ranked hits with source `file_paths`, cleaned snippet text, relevance score, and optional heading.

### `read`

Read chunks from a file returned by `search`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_path` | string | required | Absolute file path from a search result |
| `start` | integer | `0` | First chunk index to return |
| `end` | integer or null | `null` | Exclusive end chunk index; omitted means metadata only |

Use `read(file_path)` first to inspect `frontmatter` and `total_chunks`, then request chunk ranges such as `read(file_path, 0, 20)`.

### `feedback`

Submit agent feedback for later maintainer review.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `message` | string | required | What was observed |
| `severity` | string or null | `null` | `bug`, `suggestion`, or `question` |
| `context` | string or null | `null` | Tool, arguments, or task context |
| `model` | string or null | `null` | Agent/model that submitted feedback |
| `harness` | string or null | `null` | Client or environment |

Feedback is stored in `feedback.db` under the configured index directory and can be reviewed through the CLI:

```bash
cd backend
uv run dotmd feedback list
uv run dotmd feedback list --all
uv run dotmd feedback status <id> done --reason "handled"
```

## Configuration

The server uses the same `DOTMD_` settings as the CLI and REST API. Important variables:

| Variable | Description |
|----------|-------------|
| `DOTMD_INDEX_DIR` | Index storage directory |
| `DOTMD_EMBEDDING_URL` | TEI-compatible embedding endpoint |
| `DOTMD_GRAPH_BACKEND` | `ladybugdb` or `falkordb` |
| `DOTMD_BASE_URL` | Public HTTPS base URL for OAuth-enabled remote MCP |

See the main [README](../README.md) for the full configuration table.
