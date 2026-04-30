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
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

logger = logging.getLogger(__name__)

_ACCESS_TOKEN_LIFETIME_SECONDS = 86400 * 30
_AUTH_CODE_LIFETIME_SECONDS = 300


def _new_state() -> dict[str, dict[str, object]]:
    return {
        "clients": {},
        "auth_codes": {},
        "access_tokens": {},
        "refresh_tokens": {},
    }


def _require_client_id(client: OAuthClientInformationFull) -> str:
    if not client.client_id:
        raise ValueError("OAuth client_id is required")
    return client.client_id


class DotMDOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    """JSON-backed OAuth provider for a trusted single-user Tailnet deployment."""

    def __init__(self, state_path: Path) -> None:
        self._path = state_path
        self._lock = asyncio.Lock()
        self._state = _new_state()
        if state_path.exists():
            try:
                self._state = json.loads(state_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning(
                    "Failed to load OAuth state from %s: %s; starting fresh",
                    state_path,
                    exc,
                )

    async def _flush(self) -> None:
        """Write state to disk atomically using tmp file plus os.replace()."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, self._path)

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        data = self._state["clients"].get(client_id)
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.client_id:
            raise ValueError("OAuth client registration requires client_id")
        async with self._lock:
            self._state["clients"][client_info.client_id] = client_info.model_dump(mode="json")
            await self._flush()
        logger.info("OAuth: client registered client_id=%s", client_info.client_id)

    async def authorize(self, client: OAuthClientInformationFull, params) -> str:
        client_id = _require_client_id(client)
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
            self._state["auth_codes"][code] = auth_code.model_dump(mode="json")
            await self._flush()
        logger.info("OAuth: authorization code issued client_id=%s", client_id)
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
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
            self._state["access_tokens"].pop(token.token, None)
            self._state["refresh_tokens"].pop(token.token, None)
            await self._flush()
        logger.info("OAuth: token revoked client_id=%s", token.client_id)
