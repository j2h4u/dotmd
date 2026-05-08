"""Declarative source descriptor registry."""

from __future__ import annotations

from dotmd.core.models import SourceDescriptor


class SourceRegistry:
    """In-memory registry for source descriptors keyed by namespace."""

    def __init__(self) -> None:
        self._descriptors: dict[str, SourceDescriptor] = {}

    def register(self, descriptor: SourceDescriptor) -> None:
        """Register a source descriptor."""
        if descriptor.namespace in self._descriptors:
            raise ValueError(
                f"source namespace already registered: {descriptor.namespace}"
            )
        self._descriptors[descriptor.namespace] = descriptor.model_copy(deep=True)

    def get(self, namespace: str) -> SourceDescriptor | None:
        """Return a source descriptor if present."""
        descriptor = self._descriptors.get(namespace)
        if descriptor is None:
            return None
        return descriptor.model_copy(deep=True)

    def require(self, namespace: str) -> SourceDescriptor:
        """Return a source descriptor or raise when missing."""
        descriptor = self.get(namespace)
        if descriptor is None:
            raise KeyError(f"source namespace not registered: {namespace}")
        return descriptor

    def list(self) -> list[SourceDescriptor]:
        """Return all registered source descriptors."""
        return [
            descriptor.model_copy(deep=True)
            for descriptor in self._descriptors.values()
        ]

