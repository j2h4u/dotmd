# Phase 17: MCP OAuth 2.0 — Pattern Map

**Mapped:** 2026-04-29
**Files analyzed:** 3 (1 new, 2 modified)
**Analogs found:** 3 / 3

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/src/dotmd/auth.py` | provider (storage backend) | request-response + async I/O | `backend/src/dotmd/feedback.py` | role-match (same tier: top-level module, path-backed persistence, sync/async boundary) |
| `backend/src/dotmd/mcp_server.py` | server entry point | request-response | itself (existing file, modify in place) | self |
| `backend/src/dotmd/core/config.py` | config | — | itself (existing file, modify in place) | self |

---

## Pattern Assignments

### `backend/src/dotmd/auth.py` (new — provider, async I/O)

**Analog:** `backend/src/dotmd/feedback.py`

**Why this analog:** `feedback.py` is the closest structural match — same package tier (top-level `src/dotmd/` module), same pattern of a class that owns a file on disk, initialises it in `__init__`, exposes focused write methods, and is instantiated once at server startup. The key difference is that `auth.py` needs `asyncio.Lock` because its methods are `async` (called directly from FastMCP's async handlers), whereas `FeedbackStore` is sync. The Protocol it implements (`OAuthAuthorizationServerProvider`) is defined by the MCP SDK — there is no codebase analog for that.

**Module header pattern** (`feedback.py` lines 1-11):
```python
"""Feedback storage for MCP SubmitFeedback tool."""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)
```

Copy this header shape for `auth.py`, substituting the relevant stdlib imports (`asyncio`, `json`, `os`, `secrets`, `time`) and the MCP SDK imports:
```python
"""OAuth 2.0 Authorization Server provider for dotMD — JSON-backed storage."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from pathlib import Path

from mcp.server.auth.provider import (
    OAuthAuthorizationServerProvider,
    AuthorizationCode,
    AccessToken,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

logger = logging.getLogger(__name__)
```

**Class init pattern** (`feedback.py` lines 16-26):
```python
class FeedbackStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
```

Corresponding pattern for `auth.py` — load-on-init with in-memory dict (not lazy):
```python
_EMPTY_STATE: dict = {
    "clients": {},
    "auth_codes": {},
    "access_tokens": {},
    "refresh_tokens": {},
}

class DotMDOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    def __init__(self, state_path: Path) -> None:
        self._path = state_path
        self._lock = asyncio.Lock()
        self._state: dict = dict(_EMPTY_STATE)
        if state_path.exists():
            self._state = json.loads(state_path.read_text())
```

**Atomic-write flush helper** (no analog in codebase — use research pattern):
```python
async def _flush(self) -> None:
    """Write state to disk atomically (tmp + os.replace)."""
    tmp = self._path.with_suffix(".tmp")
    tmp.write_text(json.dumps(self._state, indent=2, default=str))
    os.replace(tmp, self._path)
```

**Error and validation pattern** (`feedback.py` lines 59-68 — guard then write, log after):
```python
def submit(self, message: str, severity: str | None = None, ...) -> None:
    if severity and severity not in _VALID_SEVERITIES:
        severity = None
    now = int(time.time())
    with self._connect() as conn:
        cur = conn.execute(...)
    logger.info("Feedback submitted: id=%d severity=%s", cur.lastrowid, severity)
```

Mirror this guard-then-mutate-then-log discipline in `auth.py`'s mutating methods (`register_client`, `exchange_authorization_code`, etc.).

**Storage Protocol pattern** (`storage/base.py` lines 26-28 — Protocol with `@runtime_checkable`):
```python
@runtime_checkable
class VectorStoreProtocol(Protocol):
    """Protocol for vector similarity-search backends."""
```

`OAuthAuthorizationServerProvider` follows the same Protocol pattern but is defined by the SDK. `DotMDOAuthProvider` does NOT need `@runtime_checkable` — it's a concrete class implementing the SDK Protocol, not defining a new one.

---

### `backend/src/dotmd/mcp_server.py` (modify — server entry point)

**Analog:** itself. Changes are additive — two new module-level variables and two new kwargs on the existing `FastMCP(...)` constructor call.

**Current `mcp = FastMCP(...)` block** (`mcp_server.py` lines 90-105) — copy pattern, add auth kwargs:
```python
mcp = FastMCP(
    "dotmd",
    instructions=_INSTRUCTIONS,
    host="0.0.0.0",
    port=8080,
    json_response=True,
    stateless_http=True,
    # No lifespan= here — FastMCP's lifespan fires per MCP session ...
)
```

New form — insert `_base_url` / `_provider` at module scope BEFORE the `mcp = FastMCP(...)` line, then extend the constructor:
```python
# Module-scope, before mcp = FastMCP(...)
import os
from pathlib import Path
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from dotmd.auth import DotMDOAuthProvider

_base_url = os.environ.get("DOTMD_BASE_URL", "").rstrip("/")

_provider: DotMDOAuthProvider | None = None
if _base_url:
    _provider = DotMDOAuthProvider(Path("/dotmd-index/oauth_state.json"))

mcp = FastMCP(
    "dotmd",
    instructions=_INSTRUCTIONS,
    host="0.0.0.0",
    port=8080,
    json_response=True,
    stateless_http=True,
    auth_server_provider=_provider,
    auth=AuthSettings(
        issuer_url=_base_url,
        resource_server_url=f"{_base_url}/mcp",
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["dotmd"],
            default_scopes=["dotmd"],
        ),
    ) if _base_url else None,
)
```

**`create_app()` route-copy pattern** (`mcp_server.py` lines 156 and 190-194) — no change needed:
```python
mcp_starlette = mcp.streamable_http_app()
# ...
return Starlette(
    debug=mcp.settings.debug,
    routes=mcp_starlette.routes,   # picks up auth routes automatically
    lifespan=_server_lifespan,
)
```

`routes=mcp_starlette.routes` already copies ALL routes including the new auth routes that `streamable_http_app()` adds when `auth_server_provider` is set. No change required to `create_app()`.

**`_init_for_stdio()` pattern** (`mcp_server.py` lines 125-139) — no change. Auth is not needed for stdio transport (auth is disabled when `DOTMD_BASE_URL` is unset, matching the conditional above).

**Import placement convention** (`mcp_server.py` lines 1-23): existing imports use `from __future__ import annotations` at top, stdlib before third-party before local. The three new imports (`os`, `Path`, auth SDK) should be inserted following this same order:
- `os` joins existing stdlib block (lines 4-10)
- `from pathlib import Path` joins the same stdlib block
- `from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions` joins the existing `mcp.*` import block (line 12)
- `from dotmd.auth import DotMDOAuthProvider` joins the `dotmd.*` local imports block (lines 18-22)

---

### `backend/src/dotmd/core/config.py` (modify — config)

**Analog:** itself. The change is a single new optional field following the established field pattern.

**Field declaration pattern** (`config.py` lines 37-38, 49 — optional with default, required without):
```python
# Required (no default) — raises ValidationError at startup if unset:
embedding_url: str

# Optional with default:
vector_backend: Literal["lancedb", "sqlite-vec"] = "sqlite-vec"

# Optional that can be None:
embedding_uses_prefix: bool | None = None
```

New field follows the `bool | None = None` pattern (optional, auth disabled when absent):
```python
# Base URL for OAuth endpoints (e.g. https://senbonzakura.tailf87223.ts.net/dotmd).
# When unset, OAuth auth is disabled — server runs without authentication.
# Must include path prefix matching Tailscale Serve mount (/dotmd).
# Set DOTMD_BASE_URL in docker-compose or environment.
base_url: str | None = None
```

**`env_prefix` convention** (`config.py` lines 22-25): all env vars are `DOTMD_`-prefixed automatically via `model_config`. The new field `base_url` will be read from `DOTMD_BASE_URL` automatically — no explicit `alias` or `env` needed.

**Field validator pattern** (`config.py` lines 87-133) — only needed if validation is complex. For `base_url`, a simple `@field_validator` that strips trailing slash and checks HTTPS when set is sufficient, mirroring the `embedding_weights` validator style:
```python
@field_validator("base_url")
@classmethod
def validate_base_url(cls, v: str | None) -> str | None:
    if v is None:
        return None
    v = v.rstrip("/")
    if not v.startswith("https://") and not v.startswith("http://localhost"):
        raise ValueError(
            f"base_url must use HTTPS (got {v!r}). "
            "OAuth requires HTTPS except for localhost."
        )
    return v
```

---

## Shared Patterns

### `from __future__ import annotations`
**Source:** Every dotmd module (e.g. `feedback.py` line 1, `mcp_server.py` line 1, `config.py` — not present but all others use it)
**Apply to:** `auth.py`
Always the first line after the module docstring. Required for forward-reference type annotations.

### Logger per module
**Source:** `feedback.py` line 10, `mcp_server.py` line 24
```python
logger = logging.getLogger(__name__)
```
**Apply to:** `auth.py` — same pattern, module-scope logger.

### Module docstring style
**Source:** `feedback.py` line 1, `mcp_server.py` line 1, `config.py` line 1
```python
"""One-line description — purpose and scope."""
```
Short, imperative, ends with period. No multi-paragraph prose in the docstring.

### `Path` for all filesystem references
**Source:** `feedback.py` line 8, `config.py` lines 29-30
```python
from pathlib import Path
self._db_path = db_path  # type: Path
```
**Apply to:** `auth.py` — `state_path: Path` parameter, not `str`.

### Pydantic model round-trip pattern (no direct codebase analog — from research)
`OAuthClientInformationFull`, `AuthorizationCode`, `AccessToken`, `RefreshToken` are all SDK Pydantic BaseModel subclasses. Serialize with `.model_dump(mode="json")`, deserialize with `.model_validate(data)`. This is standard Pydantic v2 — consistent with how `config.py` uses Pydantic v2 validators.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `auth.py` (Protocol implementation) | OAuth AS provider | — | No existing OAuth or async-lock JSON provider in the codebase. The closest structural analog is `feedback.py` (same tier, path-backed persistence) but the Protocol contract is entirely SDK-defined. All 9 async methods and their exact signatures must come from RESEARCH.md (`mcp/server/auth/provider.py` lines 106-275). |

---

## Metadata

**Analog search scope:** `backend/src/dotmd/` (all subdirectories)
**Files scanned:** `mcp_server.py`, `core/config.py`, `feedback.py`, `storage/base.py`, full file list
**Pattern extraction date:** 2026-04-29
