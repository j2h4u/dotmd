"""Vendored Airweave decorator stubs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def source(
    name: str,
    short_name: str,
    auth_methods: list[object] | None = None,
    oauth_type: object | None = None,
    **kwargs: object,
) -> Callable[[type], type]:
    """No-op source decorator that preserves Airweave class metadata."""

    def decorator(cls: type) -> type:
        cls.is_source = True
        cls.source_name = name
        cls.short_name = short_name
        cls.auth_methods = auth_methods or []
        cls.oauth_type = oauth_type
        for key, value in kwargs.items():
            setattr(cls, key, value)
        return cls

    return decorator
