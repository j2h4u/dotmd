---
phase: 29-telegram-adapter-mvp-ingestion
reviewed: 2026-05-08T08:25:36Z
depth: standard
files_reviewed: 19
files_reviewed_list:
  - /home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_api.py
  - /home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_client.py
  - /home/j2h4u/repos/j2h4u/mcp-telegram/tests/test_daemon.py
  - backend/src/dotmd/api/service.py
  - backend/src/dotmd/cli.py
  - backend/src/dotmd/core/config.py
  - backend/src/dotmd/core/models.py
  - backend/src/dotmd/ingestion/pipeline.py
  - backend/src/dotmd/ingestion/source_provider.py
  - backend/src/dotmd/ingestion/telegram_provider.py
  - backend/src/dotmd/search/fts5.py
  - backend/src/dotmd/storage/metadata.py
  - backend/tests/api/test_service_search.py
  - backend/tests/ingestion/application_source_fixtures.py
  - backend/tests/ingestion/test_application_source_provider.py
  - backend/tests/ingestion/test_telegram_ingestion.py
  - backend/tests/ingestion/test_telegram_provider.py
  - docs/mcp-telegram-source-contract.md
  - docs/source-adapter-architecture.md
findings:
  critical: 1
  warning: 2
  info: 0
  total: 3
status: issues_found
---

# Phase 29: Code Review Report

**Reviewed:** 2026-05-08T08:25:36Z
**Depth:** standard
**Files Reviewed:** 19
**Status:** issues_found

## Summary

Reviewed the dotMD Phase 29 Telegram source adapter and the included mcp-telegram daemon/client files. The live ingest path does not currently work against the daemon payload shape: mcp-telegram exports canonical `SourceDocument` / `SourceUnit` objects, while dotMD's mapper expects flattened fixture-only fields. I also found socket/client robustness issues that can hang or mislead callers.

## Critical Issues

### CR-01: BLOCKER - Live Telegram Export Payload Cannot Be Parsed By dotMD

**File:** `backend/src/dotmd/ingestion/telegram_provider.py:200`

**Issue:** `TelegramApplicationSourceProvider` expects `dialog_id`, `message_id`, `sent_at`, and related fields at the top level of `document` and `unit` payloads. The live daemon builds a different payload shape: those fields are nested in `metadata_json`, and the top level already carries `namespace`, `document_ref`, `unit_ref`, `updated_at`, etc. See `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_api.py:1107`. With the real daemon response, `_document_from_payload()` raises `KeyError` at `unit_payload["dialog_id"]`, and `_unit_from_payload()` would also fail at `payload["dialog_id"]`. The Phase 29 live boundary `mcp-telegram export -> dotMD ingest` is blocked; current tests only cover flattened fixtures, not the actual daemon shape.

**Fix:**
Normalize from the real source-model payload first, and only support flattened fixtures as a compatibility fallback if needed. Add a test fixture copied from `_source_row_to_change()` output.

```python
def _change_from_payload(self, payload: dict) -> ApplicationSourceChange:
    document_payload = payload["document"]
    unit_payload = payload["unit"]
    document = SourceDocument(**document_payload)
    unit = self._unit_from_source_payload(unit_payload)
    return ApplicationSourceChange(document=document, unit=unit)

def _unit_from_source_payload(self, payload: dict) -> SourceUnit:
    metadata = dict(payload.get("metadata_json") or {})
    text = str(payload.get("text") or "")
    metadata["standalone_search"] = not is_low_signal_telegram_text(text)
    return SourceUnit(
        namespace=payload["namespace"],
        document_ref=payload["document_ref"],
        unit_ref=payload["unit_ref"],
        unit_type=payload["unit_type"],
        text=text,
        order_key=payload["order_key"],
        fingerprint=payload["fingerprint"],
        updated_at=_parse_datetime(payload["updated_at"]),
        metadata_json=metadata,
        chunking_hints=payload.get("chunking_hints", {}),
    )
```

## Warnings

### WR-01: WARNING - Synchronous UNIX Socket Client Can Hang Forever

**File:** `backend/src/dotmd/ingestion/telegram_provider.py:117`

**Issue:** `UnixSocketTelegramSourceClient._request()` uses a blocking socket with no connect, send, or receive timeout, then reads until a newline. If the daemon accepts the connection but stalls before writing the terminating newline, `dotmd telegram ingest`, service reads, or any future scheduled ingest can block indefinitely. This is a robustness defect at the external source boundary.

**Fix:** Set a bounded timeout on the socket and convert `socket.timeout` into a source-client error that callers can report and retry.

```python
def _request(self, payload: dict) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(30.0)
        try:
            sock.connect(str(self._socket_path))
            sock.sendall(json.dumps(payload).encode("utf-8") + b"\n")
            data = b""
            while not data.endswith(b"\n"):
                chunk = sock.recv(1024 * 1024)
                if not chunk:
                    break
                data += chunk
        except socket.timeout as exc:
            raise RuntimeError("Telegram daemon request timed out") from exc
```

### WR-02: WARNING - Daemon Client Claims Multi-Request Connections That The Server Closes

**File:** `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_client.py:6`

**Issue:** `daemon_client.py` documents that a `DaemonConnection` "supports multiple sequential request() calls within the same async-with block", and `DaemonConnection.request()` is written as if callers can reuse the stream. The daemon handler explicitly reads only one request and then closes the connection (`daemon_api.py:883`). A caller that follows the client contract and sends two requests in one `async with daemon_connection()` will get EOF or a broken pipe on the second request. This is a misleading API contract and a latent tool failure.

**Fix:** Either make the server loop over request lines until EOF, or change the client contract and tests to enforce one request per connection. Server-side loop is the least surprising fix:

```python
async def handle_client(self, reader, writer) -> None:
    try:
        while line := await reader.readline():
            response = await self._handle_request_line(line)
            writer.write(json.dumps(response).encode() + b"\n")
            await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()
```

Add a daemon-client test that performs two `conn.request(...)` calls inside one context.

---

_Reviewed: 2026-05-08T08:25:36Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
