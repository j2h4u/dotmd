"""Minimal Airweave BaseSource contract and DI type stubs."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, AsyncGenerator, ClassVar, Protocol

import httpx
from pydantic import BaseModel

from dotmd.vendor.airweave.entities_base import BaseEntity

SyncCursor = dict[str, object]
NodeSelectionData = Any


class AuthenticationMethod(str, Enum):
    """Source authentication methods used by vendored decorators."""

    OAUTH_BROWSER = "oauth_browser"
    OAUTH_TOKEN = "oauth_token"
    AUTH_PROVIDER = "auth_provider"
    OAUTH_BYOC = "oauth_byoc"


class OAuthType(str, Enum):
    """OAuth token type."""

    WITH_REFRESH = "with_refresh"
    WITH_ROTATING_REFRESH = "with_rotating_refresh"


class RateLimitLevel(str, Enum):
    """Rate-limit scope stub."""

    ORG = "org"
    CONNECTION = "connection"


class ContextualLogger:
    """Logger structural stub."""

    def debug(self, msg: str, *args: object, **kwargs: object) -> None:
        pass

    def info(self, msg: str, *args: object, **kwargs: object) -> None:
        pass

    def warning(self, msg: str, *args: object, **kwargs: object) -> None:
        pass

    def error(self, msg: str, *args: object, **kwargs: object) -> None:
        pass


class SourceAuthProvider(Protocol):
    """Source auth provider structural contract."""

    provider_kind: str
    supports_refresh: bool

    async def get_token(self) -> str:
        """Return a valid access token."""
        ...


class AirweaveHttpClient:
    """Tiny wrapper around httpx.AsyncClient matching the methods GmailSource uses."""

    def __init__(self, wrapped_client: httpx.AsyncClient) -> None:
        self._client = wrapped_client

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, object] | None = None,
    ) -> httpx.Response:
        """Issue a GET request."""
        return await self._client.get(url, headers=headers, params=params)

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, object] | None = None,
    ) -> httpx.Response:
        """Issue a POST request."""
        return await self._client.post(url, headers=headers, json=json)


class BaseSource(ABC):
    """Base class for Airweave platform sources."""

    is_source: ClassVar[bool] = False
    source_name: ClassVar[str] = ""
    short_name: ClassVar[str] = ""
    auth_methods: ClassVar[list[AuthenticationMethod]] = []
    oauth_type: ClassVar[OAuthType | None] = None
    requires_byoc: ClassVar[bool] = False
    auth_config_class: ClassVar[type[BaseModel] | None] = None
    config_class: ClassVar[type[BaseModel] | None] = None
    supports_continuous: ClassVar[bool] = False
    federated_search: ClassVar[bool] = False
    supports_temporal_relevance: ClassVar[bool] = True
    supports_access_control: ClassVar[bool] = False
    supports_browse_tree: ClassVar[bool] = False
    cursor_class: ClassVar[type | None] = None
    rate_limit_level: ClassVar[RateLimitLevel | None] = None
    labels: ClassVar[list[str]] = []
    feature_flag: ClassVar[str | None] = None
    internal: ClassVar[bool] = False

    def __init__(
        self,
        *,
        auth: SourceAuthProvider,
        logger: ContextualLogger,
        http_client: AirweaveHttpClient,
    ) -> None:
        self._auth = auth
        self._logger = logger
        self._http_client = http_client

    @property
    def auth(self) -> SourceAuthProvider:
        """The auth provider for this source."""
        return self._auth

    @property
    def logger(self) -> ContextualLogger:
        """Contextual logger."""
        return self._logger

    @property
    def http_client(self) -> AirweaveHttpClient:
        """HTTP client."""
        return self._http_client

    async def get_access_token(self) -> str:
        """Get a valid access token via the auth provider."""
        return await self._auth.get_token()

    @classmethod
    @abstractmethod
    async def create(
        cls,
        *,
        auth: SourceAuthProvider,
        logger: ContextualLogger,
        http_client: AirweaveHttpClient,
        config: BaseModel,
    ) -> BaseSource:
        """Create a new source instance."""
        raise NotImplementedError

    @abstractmethod
    async def generate_entities(
        self,
        *,
        cursor: SyncCursor | None = None,
        files: object | None = None,
        node_selections: list[NodeSelectionData] | None = None,
    ) -> AsyncGenerator[BaseEntity, None]:
        """Generate entities for the source."""
        if False:
            yield BaseEntity()

    @abstractmethod
    async def validate(self) -> None:
        """Validate credentials."""
        raise NotImplementedError

    async def search(self, query: str, limit: int) -> AsyncGenerator[BaseEntity, None]:
        """Search the source for entities matching the query."""
        if not self.__class__.federated_search:
            raise NotImplementedError(
                f"Source {self.__class__.__name__} does not support federated search"
            )
        raise NotImplementedError(
            f"Source {self.__class__.__name__} has federated_search=True but "
            "search() method is not implemented"
        )

    def clean_content_for_embedding(self, content: str) -> str:
        """Clean content for embedding by removing huge URLs and extra whitespace."""
        if not content:
            return ""
        content = re.sub(r"!\[([^\]]*)\]\([^\?\)]+\?[^\)]+\)", r"[Image: \1]", content)
        content = re.sub(r"!\[([^\]]*)\]\([^\)]{200,}\)", r"[Image: \1]", content)
        content = re.sub(r"\[([^\]]+)\]\(https?://[^\s\)]+\?[^\)]{100,}\)", r"[\1]", content)
        content = re.sub(r"(https?://[^\s]+\?[^\s]{100,})", "[link]", content)
        content = re.sub(r"\n{3,}", "\n\n", content)
        return content.strip()
