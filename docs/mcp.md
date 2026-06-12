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

## Agent Workflow

The public MCP workflow is source-ref-first:

```text
search(query) -> ref
drill(ref) -> source metadata
read(ref, start, end) -> chunk text
```

Search returns refs that are safe to pass back to `drill` and `read`. For
filesystem documents, refs use `filesystem:<document_ref>`, where
`document_ref = str(Path(file_path).resolve())`. The filesystem path is readable
inside that ref, but it is not exposed as a separate public search identity.

## Tools

### `search`

Search the indexed markdown knowledgebase.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | required | Natural-language search query |
| `top_k` | integer | `10` | Maximum results to return, 1-100 |

Returns ranked hits with this public shape:

```text
{ ref, heading?, snippet, score }
```

`heading` is optional because not every source or chunk has markdown headings.
Do not look for public `file_path` or `file_paths` fields in search results.

### `read`

Read chunks from a source ref returned by `search`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `ref` | string | required | Source ref from a search result |
| `start` | integer | `0` | First chunk index to return |
| `end` | integer or null | `null` | Exclusive end chunk index; omitted means metadata only |

Use `read(ref)` first to inspect `frontmatter` and `total_chunks`, then request
chunk ranges such as `read(ref, 0, 20)`.

Invalid refs are reported as tool-level errors with an actionable hint:
`Action: pass a ref returned by search.`

### `drill`

Inspect source metadata for a ref returned by `search`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `ref` | string | required | Source ref from a search result |

Use `drill(ref)` when an agent needs frontmatter, source metadata, document
type, parser name, source URI, or chunk count before deciding which ranges to
read. `drill` is intentionally separate from `read`; `read` stays focused on
content chunks.

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
| `DOTMD_FALKORDB_URL` | FalkorDB Redis URL |
| `DOTMD_BASE_URL` | Public HTTPS base URL for OAuth-enabled remote MCP |

See the main [README](../README.md) for the full configuration table.
