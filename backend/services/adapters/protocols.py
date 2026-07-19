from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class Validator(Protocol):
    """Protocol for adapters that support configuration validation."""

    async def validate(self) -> Optional[list[str]]:
        """Validate adapter configuration.

        Returns a list of configuration issues, or None/empty if valid.
        """


@runtime_checkable
class HealthCheckable(Protocol):
    """Protocol for adapters that expose a health-check endpoint."""

    async def health(self) -> dict:
        """Return a health-status dictionary.

        Expected keys include ``status``, ``uptime``, ``latency_ms``, etc.
        A non-empty dict with at least a ``status`` key is the minimum.
        """


@runtime_checkable
class CapabilityReporter(Protocol):
    """Protocol for adapters that expose dynamic capability discovery."""

    async def capabilities(self) -> list[str]:
        """Return a list of capability strings this adapter supports."""
