from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from services.adapters.adapter_context import AdapterContext
from services.adapters.models import AdapterMetadata, AdapterResult


class ExecutionAdapter(ABC):
    """Abstract base class for all execution adapters.

    Every adapter must implement three things:
      1. A ``metadata`` property that describes the adapter.
      2. An ``execute`` method that performs the actual work.
      3. Optionally override ``validate``, ``health``, or ``capabilities``.

    Adapters are stateless — all execution state lives in
    ``AdapterContext``.
    """

    @property
    @abstractmethod
    def metadata(self) -> AdapterMetadata:
        """Return the adapter's immutable metadata descriptor."""

    @abstractmethod
    async def execute(self, context: AdapterContext) -> AdapterResult:
        """Execute the operation described by *context*.

        Args:
            context: Carries everything the adapter needs (session,
                     task, action, params, credentials, config, logger).

        Returns:
            An ``AdapterResult`` with ``success=True`` on success or
            ``success=False`` with an error message on failure.
        """

    async def validate(self) -> Optional[list[str]]:
        """Validate adapter configuration.

        Returns a list of issues if invalid, or None if valid.
        Override to implement adapter-specific validation.
        """
        return None

    async def health(self) -> dict:
        """Return a health check dictionary.

        Override to provide meaningful health information.
        The default returns ``{"status": "unknown"}``.
        """
        return {"status": "unknown"}

    async def capabilities(self) -> list[str]:
        """Return supported capability strings.

        Override to expose dynamic capabilities.
        The default returns an empty list.
        """
        return []

    def __repr__(self) -> str:
        meta = self.metadata
        return (
            f"{type(self).__name__}(name={meta.name!r}, "
            f"version={meta.version!r})"
        )
