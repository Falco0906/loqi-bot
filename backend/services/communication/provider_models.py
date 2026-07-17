"""Provider models — strongly typed Pydantic models for the provider abstraction layer.

These models are NEVER exposed outside the provider layer.
Conversation Intelligence never sees these types.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4
from pydantic import BaseModel


class ProviderType(str, Enum):
    GMAIL = "gmail"
    OUTLOOK = "outlook"
    LINKEDIN = "linkedin"
    MANUAL = "manual"
    API = "api"


class ProviderStatus(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    OFFLINE = "offline"
    EXPIRED_TOKEN = "expired_token"
    DISCONNECTED = "disconnected"
    SCOPE_INSUFFICIENT = "scope_insufficient"


class ProviderHealth(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    OFFLINE = "offline"
    EXPIRED_TOKEN = "expired_token"
    SCOPE_INSUFFICIENT = "scope_insufficient"


class ConnectionState(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class MessageDirection(str, Enum):
    INCOMING = "incoming"
    OUTGOING = "outgoing"


class ProviderEventType(str, Enum):
    CONNECTED = "provider_connected"
    DISCONNECTED = "provider_disconnected"
    SYNC_STARTED = "sync_started"
    SYNC_COMPLETED = "sync_completed"
    SYNC_FAILED = "sync_failed"
    MESSAGE_RECEIVED = "message_received"
    THREAD_UPDATED = "thread_updated"
    TOKEN_EXPIRING = "token_expiring"
    TOKEN_REFRESHED = "token_refreshed"
    TOKEN_FAILED = "token_failed"


class CommunicationProvider(BaseModel):
    id: str = ""
    provider_type: ProviderType
    user_id: str
    status: ProviderStatus = ProviderStatus.DISCONNECTED
    last_sync: str = ""
    sync_cursor: str = ""
    metadata: dict[str, Any] = {}
    created_at: str = ""
    updated_at: str = ""

    def model_post_init(self, __context) -> None:
        if not self.id:
            self.id = str(uuid4())[:12]
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now


class ProviderMessage(BaseModel):
    """Raw provider-specific message. Never exposed outside provider layer."""
    id: str = ""
    provider_id: str
    external_id: str
    thread_id: str
    direction: MessageDirection = MessageDirection.INCOMING
    raw_headers: dict[str, str] = {}
    raw_body: str = ""
    attachments: list[dict[str, Any]] = []
    received_at: str = ""
    provider_metadata: dict[str, Any] = {}

    def model_post_init(self, __context) -> None:
        if not self.id:
            self.id = str(uuid4())[:12]
        if not self.received_at:
            self.received_at = datetime.now(timezone.utc).isoformat()


class NormalizedMessage(BaseModel):
    """Maps directly into ConversationMessage. Provider-agnostic."""
    conversation_id: str
    message_id: str
    direction: MessageDirection
    sender: str
    recipient: str
    subject: str
    body: str
    timestamp: str
    provider: str
    provider_metadata: dict[str, Any] = {}


class SyncCursor(BaseModel):
    provider_id: str
    cursor: str
    last_sync: str = ""

    def model_post_init(self, __context) -> None:
        if not self.last_sync:
            self.last_sync = datetime.now(timezone.utc).isoformat()


class ThreadMapping(BaseModel):
    """Maps an external thread to a Loqi conversation."""
    provider_id: str
    external_thread_id: str
    conversation_id: str
    subject: str = ""
    last_message_at: str = ""

    def model_post_init(self, __context) -> None:
        if not self.last_message_at:
            self.last_message_at = datetime.now(timezone.utc).isoformat()


class SyncResult(BaseModel):
    provider_id: str
    threads_synced: int = 0
    messages_synced: int = 0
    new_conversations: int = 0
    errors: list[str] = []
    cursor: str = ""
    duration_ms: int = 0
