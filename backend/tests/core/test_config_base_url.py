"""Settings tests for DOTMD_BASE_URL OAuth configuration."""

import pytest
from pydantic import ValidationError

from dotmd.core.config import Settings


def _settings(base_url: str | None = None) -> Settings:
    return Settings(embedding_url="http://localhost:8088", base_url=base_url)


def test_base_url_defaults_to_none() -> None:
    assert _settings().base_url is None


def test_base_url_accepts_https() -> None:
    settings = _settings("https://senbonzakura.tailf87223.ts.net/dotmd")

    assert settings.base_url == "https://senbonzakura.tailf87223.ts.net/dotmd"


def test_base_url_rejects_non_https_non_localhost() -> None:
    with pytest.raises(ValidationError, match="must use HTTPS"):
        _settings("http://example.com")


def test_base_url_accepts_localhost_http() -> None:
    settings = _settings("http://localhost:8080")

    assert settings.base_url == "http://localhost:8080"


def test_base_url_strips_trailing_slash() -> None:
    settings = _settings("https://example.com/path/")

    assert settings.base_url == "https://example.com/path"
