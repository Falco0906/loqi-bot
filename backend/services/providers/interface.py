from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from services.providers.capabilities import Capability, CapabilitySet
from services.providers.health import HealthCheckResult


class Provider(ABC):
    """Abstract interface for all production providers.

    Every external service must implement this interface.
    No business logic inside implementations — providers only:

        1. authenticate
        2. fetch data
        3. normalize data
        4. publish events

    The rest of the architecture never knows which provider
    supplied the data.  Reasoners, narrative engine, learning
    layer, and UI remain provider-agnostic.

    Lifecycle:
        connect()   → establish auth, validate credentials
        health()    → check the provider is operational
        sync()      → fetch new/changed data, return events
        disconnect() → clean up resources
    """

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Unique identifier for this provider instance."""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable provider name (e.g. 'Gmail', 'People Data Labs')."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> CapabilitySet:
        """Declare what this provider can do.

        The registry and workflows use this for discovery without
        importing concrete provider classes.
        """
        ...

    @abstractmethod
    def connect(self) -> None:
        """Establish the provider connection.

        For OAuth providers this means validating the token is valid
        and the API is reachable.  For API-key providers it means
        testing the credentials.

        Raises ProviderSetupError on failure.
        """
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """Clean up provider resources.

        Called when the provider is being removed or replaced.
        Should revoke tokens, close sessions, etc.
        """
        ...

    @abstractmethod
    def health(self) -> HealthCheckResult:
        """Verify the provider is operational.

        This must be fast (<1s).  It should check connectivity
        without performing expensive data operations.

        Returns a HealthCheckResult — never raises.
        """
        ...

    def sync(self) -> list[dict[str, Any]]:
        """Fetch new or changed data.

        Returns a list of normalized event dicts ready for the
        World Model event system.

        Override this in providers that support incremental sync.
        Default: no-op (empty list).
        """
        return []

    def publish_events(self) -> list[dict[str, Any]]:
        """Publish pending events to the World Model event system.

        Called periodically by the scheduler to flush any queued
        events the provider accumulated during sync.

        Default: no-op (empty list).
        """
        return []

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "capabilities": self.capabilities.to_dict(),
        }


class ProviderSetupError(Exception):
    """Raised when provider connection/configuration fails."""
    pass


class ProviderSyncError(Exception):
    """Raised when a sync operation fails."""
    pass


class ProviderPublishError(Exception):
    """Raised when event publishing fails."""
    pass
