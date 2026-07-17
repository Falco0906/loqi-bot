"""Abstract outbound provider interface.

Every outbound provider (Gmail, Outlook, LinkedIn, Slack)
must implement this interface.

Providers NEVER contain business logic.
They are pure transport layers.
"""
from abc import ABC, abstractmethod
from typing import Optional

from services.outbound.outbound_models import (
    DraftMessage,
    SendRequest,
    SendResult,
    ScheduledMessage,
    DraftListResult,
)


class OutboundProviderBase(ABC):
    provider_type: str = ""

    @abstractmethod
    def create_draft(self, draft: DraftMessage) -> DraftMessage:
        ...

    @abstractmethod
    def update_draft(self, draft: DraftMessage) -> DraftMessage:
        ...

    @abstractmethod
    def delete_draft(self, draft_id: str) -> bool:
        ...

    @abstractmethod
    def send(self, request: SendRequest) -> SendResult:
        ...

    @abstractmethod
    def schedule(self, draft: DraftMessage, send_at: str) -> ScheduledMessage:
        ...

    @abstractmethod
    def cancel_schedule(self, schedule_id: str) -> bool:
        ...

    @abstractmethod
    def get_status(self, message_id: str) -> str:
        ...

    @abstractmethod
    def fetch_draft(self, draft_id: str) -> Optional[DraftMessage]:
        ...

    @abstractmethod
    def list_drafts(self) -> DraftListResult:
        ...
