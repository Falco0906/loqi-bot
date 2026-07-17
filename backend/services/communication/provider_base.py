"""Abstract provider interface.

Every communication provider (Gmail, Outlook, LinkedIn, etc.)
must implement this interface.

Providers NEVER contain business logic.
They only fetch → normalize → store → emit events.
"""

from abc import ABC, abstractmethod
from typing import Optional

from services.communication.provider_models import (
    CommunicationProvider,
    ProviderMessage,
    SyncResult,
    ProviderType,
    ProviderStatus,
)


class CommunicationProviderBase(ABC):
    """Abstract base for all communication providers."""

    provider_type: ProviderType

    @abstractmethod
    def connect(self, auth_token: str, **kwargs) -> CommunicationProvider:
        """Establish connection and return provider record."""
        ...

    @abstractmethod
    def disconnect(self) -> bool:
        """Disconnect and clean up resources."""
        ...

    @abstractmethod
    def health(self) -> ProviderStatus:
        """Return current health status."""
        ...

    @abstractmethod
    def sync(self, cursor: str = "") -> SyncResult:
        """Perform incremental sync since cursor. Empty cursor = full sync."""
        ...

    @abstractmethod
    def fetch_thread(self, thread_id: str) -> list[ProviderMessage]:
        """Fetch all messages in a thread by external thread ID."""
        ...

    @abstractmethod
    def fetch_message(self, message_id: str) -> Optional[ProviderMessage]:
        """Fetch a single message by external message ID."""
        ...

    @abstractmethod
    def normalize(self, message: ProviderMessage) -> dict:
        """Convert a provider-specific message into a normalized dict
        compatible with NormalizedMessage."""
        ...

    @abstractmethod
    def watch(self) -> bool:
        """Start watching for new messages (webhooks/polling)."""
        ...

    @abstractmethod
    def stop_watch(self) -> bool:
        """Stop watching for new messages."""
        ...
