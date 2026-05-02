"""OAuth 2.0 Authorization Server provider for dotMD JSON-backed storage."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from pathlib import Path

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

logger = logging.getLogger(__name__)

_ACCESS_TOKEN_LIFETIME_SECONDS = 86400 * 30
_AUTH_CODE_LIFETIME_SECONDS = 300
_DEFAULT_PAIRING_CODE_TTL_SECONDS = 600
_DEFAULT_PENDING_CLIENT_TTL_SECONDS = 1800
_PAIRING_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_DEFAULT_ALLOWED_REDIRECT_URIS = ("https://claude.ai/api/mcp/auth_callback",)
_DEFAULT_ALLOWED_REDIRECT_URI_PREFIXES = ("https://chatgpt.com/connector/oauth/",)


def _allowed_redirect_uris() -> set[str]:
    raw = os.environ.get("DOTMD_OAUTH_ALLOWED_REDIRECT_URIS")
    if raw is None:
        return set(_DEFAULT_ALLOWED_REDIRECT_URIS)
    return {uri.strip().rstrip("/") for uri in raw.split(",") if uri.strip()}


def _allowed_redirect_uri_prefixes() -> tuple[str, ...]:
    raw = os.environ.get("DOTMD_OAUTH_ALLOWED_REDIRECT_URI_PREFIXES")
    if raw is None:
        return _DEFAULT_ALLOWED_REDIRECT_URI_PREFIXES
    return tuple(uri.strip() for uri in raw.split(",") if uri.strip())


def _redirect_uri_allowed(uri: str) -> bool:
    normalized = _normalize_uri(uri)
    if normalized in _allowed_redirect_uris():
        return True
    return any(normalized.startswith(prefix) for prefix in _allowed_redirect_uri_prefixes())


def _uses_redirect_uri_prefix(client_info: OAuthClientInformationFull, prefix: str) -> bool:
    return any(_normalize_uri(uri).startswith(prefix) for uri in client_info.redirect_uris or [])


def _pending_client_ttl_seconds() -> int:
    raw = os.environ.get("DOTMD_OAUTH_PENDING_CLIENT_TTL_SECONDS", str(_DEFAULT_PENDING_CLIENT_TTL_SECONDS))
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Invalid DOTMD_OAUTH_PENDING_CLIENT_TTL_SECONDS=%r; using default", raw)
        return _DEFAULT_PENDING_CLIENT_TTL_SECONDS
    return value if value > 0 else _DEFAULT_PENDING_CLIENT_TTL_SECONDS


def _normalize_uri(uri: object) -> str:
    return str(uri).rstrip("/")


def _new_state() -> dict[str, dict[str, object]]:
    return {
        "clients": {},
        "pending_clients": {},
        "pairing_codes": {},
        "auth_codes": {},
        "access_tokens": {},
        "refresh_tokens": {},
    }


def _require_client_id(client: OAuthClientInformationFull) -> str:
    if not client.client_id:
        raise ValueError("OAuth client_id is required")
    return client.client_id


def _normalize_pairing_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def _format_pairing_code(code: str) -> str:
    normalized = _normalize_pairing_code(code)
    return "-".join(normalized[i : i + 4] for i in range(0, len(normalized), 4))


def _pending_client_record(client_info: OAuthClientInformationFull) -> dict[str, object]:
    now = time.time()
    return {
        "client": client_info.model_dump(mode="json"),
        "created_at": now,
        "expires_at": now + _pending_client_ttl_seconds(),
    }


def _client_from_pending_record(data: object) -> OAuthClientInformationFull | None:
    if not isinstance(data, dict):
        return None
    client_data = data.get("client", data)
    return OAuthClientInformationFull.model_validate(client_data)


class PairingCodeError(ValueError):
    """Raised when an OAuth pairing code is missing, expired, or already used."""


class DotMDOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    """JSON-backed OAuth provider for a trusted single-user Tailnet deployment."""

    def __init__(self, state_path: Path) -> None:
        self._path = state_path
        self._lock = asyncio.Lock()
        self._state = _new_state()
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if self._path.exists():
            try:
                self._state = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning(
                    "Failed to load OAuth state from %s: %s; starting fresh",
                    self._path,
                    exc,
                )
        for key, value in _new_state().items():
            self._state.setdefault(key, value)

    def _reload_locked(self) -> None:
        self._load_from_disk()

    async def _flush(self) -> None:
        """Write state to disk atomically using tmp file plus os.replace()."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, self._path)

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with self._lock:
            self._reload_locked()
        data = self._state["clients"].get(client_id)
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def get_pending_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with self._lock:
            self._reload_locked()
            purged = self._purge_expired_pending_clients(now=time.time())
            data = self._state["pending_clients"].get(client_id)
            if purged:
                await self._flush()
        return _client_from_pending_record(data) if data else None

    async def create_pairing_code(self, ttl_seconds: int = _DEFAULT_PAIRING_CODE_TTL_SECONDS) -> tuple[str, float]:
        if ttl_seconds <= 0:
            raise ValueError("OAuth pairing code TTL must be positive")
        raw_code = "".join(secrets.choice(_PAIRING_CODE_ALPHABET) for _ in range(8))
        code = _normalize_pairing_code(raw_code)
        expires_at = time.time() + ttl_seconds
        async with self._lock:
            self._reload_locked()
            self._purge_expired_pairing_codes(now=time.time())
            self._state["pairing_codes"][code] = {
                "created_at": time.time(),
                "expires_at": expires_at,
            }
            await self._flush()
        logger.info("OAuth: pairing code created expires_at=%s", int(expires_at))
        return _format_pairing_code(code), expires_at

    def _purge_expired_pairing_codes(self, *, now: float) -> None:
        codes = self._state["pairing_codes"]
        expired = [
            code
            for code, data in codes.items()
            if isinstance(data, dict) and float(data.get("expires_at", 0)) < now
        ]
        for code in expired:
            codes.pop(code, None)

    def _purge_expired_pending_clients(self, *, now: float) -> int:
        clients = self._state["pending_clients"]
        expired = []
        for client_id, data in clients.items():
            if not isinstance(data, dict):
                continue
            expires_at = float(data.get("expires_at", now + 1))
            if expires_at < now:
                expired.append(client_id)
        for client_id in expired:
            clients.pop(client_id, None)
            logger.info("OAuth: expired pending client removed client_id=%s", client_id)
        return len(expired)

    def _consume_pairing_code_locked(self, code: str, client_id: str) -> None:
        now = time.time()
        self._purge_expired_pairing_codes(now=now)
        normalized = _normalize_pairing_code(code)
        if not normalized:
            raise PairingCodeError("OAuth pairing code is required")
        data = self._state["pairing_codes"].pop(normalized, None)
        if not isinstance(data, dict):
            raise PairingCodeError("OAuth pairing code is invalid or expired")
        expires_at = float(data.get("expires_at", 0))
        if expires_at < now:
            raise PairingCodeError("OAuth pairing code is invalid or expired")
        logger.info("OAuth: pairing code consumed client_id=%s", client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.client_id:
            raise ValueError("OAuth client registration requires client_id")
        redirect_uris = {_normalize_uri(uri) for uri in client_info.redirect_uris or []}
        if not redirect_uris or not all(_redirect_uri_allowed(uri) for uri in redirect_uris):
            logger.warning(
                "OAuth: rejected client registration client_id=%s redirect_uris=%s",
                client_info.client_id,
                sorted(redirect_uris),
            )
            raise RegistrationError(
                error="invalid_redirect_uri",
                error_description="OAuth client redirect_uri is not allowed",
            )
        if _uses_redirect_uri_prefix(client_info, "https://chatgpt.com/connector/oauth/"):
            client_info.token_endpoint_auth_method = "none"
            client_info.client_secret = None
            client_info.client_secret_expires_at = None
        async with self._lock:
            self._reload_locked()
            self._purge_expired_pending_clients(now=time.time())
            self._state["pending_clients"][client_info.client_id] = _pending_client_record(client_info)
            await self._flush()
        logger.info("OAuth: client pending_pairing client_id=%s", client_info.client_id)

    async def activate_pending_client(self, client: OAuthClientInformationFull, pairing_code: str) -> None:
        client_id = _require_client_id(client)
        async with self._lock:
            self._reload_locked()
            pending = self._state["pending_clients"].get(client_id)
            if pending is None:
                if client_id in self._state["clients"]:
                    return
                raise PairingCodeError("OAuth client is not pending pairing")
            self._purge_expired_pending_clients(now=time.time())
            pending = self._state["pending_clients"].get(client_id)
            if pending is None:
                raise PairingCodeError("OAuth client pairing request expired")
            self._consume_pairing_code_locked(pairing_code, client_id)
            client_data = pending.get("client", pending) if isinstance(pending, dict) else pending
            self._state["clients"][client_id] = client_data
            self._state["pending_clients"].pop(client_id, None)
            await self._flush()
        logger.info("OAuth: pending client activated client_id=%s", client_id)

    async def authorize(self, client: OAuthClientInformationFull, params) -> str:
        client_id = _require_client_id(client)
        client_redirects = {_normalize_uri(uri) for uri in client.redirect_uris or []}
        redirect_uri = _normalize_uri(params.redirect_uri)
        if redirect_uri not in client_redirects or not _redirect_uri_allowed(redirect_uri):
            logger.warning(
                "OAuth: rejected authorization client_id=%s redirect_uri=%s",
                client_id,
                redirect_uri,
            )
            raise AuthorizeError(
                error="unauthorized_client",
                error_description="OAuth redirect_uri is not allowed",
            )
        code = secrets.token_urlsafe(32)
        auth_code = AuthorizationCode(
            code=code,
            scopes=params.scopes or ["dotmd"],
            expires_at=time.time() + _AUTH_CODE_LIFETIME_SECONDS,
            client_id=client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        async with self._lock:
            self._reload_locked()
            self._state["auth_codes"][code] = auth_code.model_dump(mode="json")
            await self._flush()
        logger.info("OAuth: authorization code issued client_id=%s", client_id)
        redirect_kwargs = {"code": code, "state": params.state}
        issuer = os.environ.get("DOTMD_BASE_URL", "").rstrip("/")
        if issuer:
            redirect_kwargs["iss"] = issuer
        return construct_redirect_uri(str(params.redirect_uri), **redirect_kwargs)

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        async with self._lock:
            self._reload_locked()
        data = self._state["auth_codes"].get(authorization_code)
        return AuthorizationCode.model_validate(data) if data else None

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        client_id = _require_client_id(client)
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        exp = int(time.time()) + _ACCESS_TOKEN_LIFETIME_SECONDS
        access_token = AccessToken(
            token=access,
            client_id=client_id,
            scopes=authorization_code.scopes,
            expires_at=exp,
            resource=authorization_code.resource,
        )
        refresh_token = RefreshToken(
            token=refresh,
            client_id=client_id,
            scopes=authorization_code.scopes,
        )
        async with self._lock:
            self._reload_locked()
            self._state["auth_codes"].pop(authorization_code.code, None)
            self._state["access_tokens"][access] = access_token.model_dump(mode="json")
            self._state["refresh_tokens"][refresh] = refresh_token.model_dump(mode="json")
            await self._flush()
        logger.info("OAuth: access token issued client_id=%s expires_at=%s", client_id, exp)
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=_ACCESS_TOKEN_LIFETIME_SECONDS,
            refresh_token=refresh,
            scope=" ".join(authorization_code.scopes),
        )

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        async with self._lock:
            self._reload_locked()
        data = self._state["refresh_tokens"].get(refresh_token)
        return RefreshToken.model_validate(data) if data else None

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        client_id = _require_client_id(client)
        new_access = secrets.token_urlsafe(32)
        new_refresh = secrets.token_urlsafe(32)
        exp = int(time.time()) + _ACCESS_TOKEN_LIFETIME_SECONDS
        issued_scopes = scopes or refresh_token.scopes
        access_token = AccessToken(
            token=new_access,
            client_id=client_id,
            scopes=issued_scopes,
            expires_at=exp,
            resource=None,
        )
        new_refresh_token = RefreshToken(
            token=new_refresh,
            client_id=client_id,
            scopes=issued_scopes,
        )
        async with self._lock:
            self._reload_locked()
            self._state["refresh_tokens"].pop(refresh_token.token, None)
            self._state["access_tokens"][new_access] = access_token.model_dump(mode="json")
            self._state["refresh_tokens"][new_refresh] = new_refresh_token.model_dump(mode="json")
            await self._flush()
        logger.info("OAuth: refresh token rotated client_id=%s expires_at=%s", client_id, exp)
        return OAuthToken(
            access_token=new_access,
            token_type="Bearer",
            expires_in=_ACCESS_TOKEN_LIFETIME_SECONDS,
            refresh_token=new_refresh,
            scope=" ".join(issued_scopes),
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        async with self._lock:
            self._reload_locked()
        data = self._state["access_tokens"].get(token)
        if not data:
            return None
        access_token = AccessToken.model_validate(data)
        if access_token.expires_at and access_token.expires_at < time.time():
            return None
        logger.debug("OAuth: token verified client_id=%s", access_token.client_id)
        return access_token

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        async with self._lock:
            self._reload_locked()
            self._state["access_tokens"].pop(token.token, None)
            self._state["refresh_tokens"].pop(token.token, None)
            await self._flush()
        logger.info("OAuth: token revoked client_id=%s", token.client_id)
