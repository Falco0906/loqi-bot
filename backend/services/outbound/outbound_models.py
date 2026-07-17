"""Outbound models — provider-agnostic Pydantic models for outbound communication.

These models are the universal language for outbound operations.
No provider-specific fields.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4
from pydantic import BaseModel


class DeliveryStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    CLICKED = "clicked"
    BOUNCED = "bounced"
    FAILED = "failed"
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"


class DraftStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_APPROVED = "auto_approved"
    SENDING = "sending"
    SENT = "sent"
    SCHEDULED = "scheduled"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


class ApprovalState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_APPROVED = "auto_approved"


class Recipient(BaseModel):
    email: str
    name: str = ""


class Attachment(BaseModel):
    filename: str
    content_type: str = ""
    data: str = ""
    size: int = 0


class OutboundMessage(BaseModel):
    id: str = ""
    provider_id: str
    conversation_id: str = ""
    thread_id: str = ""
    workflow_id: str = ""
    subject: str
    body: str
    recipient: Recipient
    sender: Recipient
    cc: list[Recipient] = []
    bcc: list[Recipient] = []
    attachments: list[Attachment] = []
    reply_to_message_id: str = ""
    in_reply_to: str = ""
    references: str = ""
    metadata: dict[str, Any] = {}

    def model_post_init(self, __context) -> None:
        if not self.id:
            self.id = str(uuid4())[:12]


class DraftMessage(BaseModel):
    id: str = ""
    provider_id: str
    external_draft_id: str = ""
    gmail_message_id: str = ""
    gmail_thread_id: str = ""
    conversation_id: str = ""
    thread_id: str = ""
    workflow_id: str = ""
    subject: str
    body: str
    recipient: Recipient
    sender: Recipient
    cc: list[Recipient] = []
    bcc: list[Recipient] = []
    attachments: list[Attachment] = []
    reply_to_message_id: str = ""
    in_reply_to: str = ""
    references: str = ""
    status: DraftStatus = DraftStatus.DRAFT
    approval_state: ApprovalState = ApprovalState.PENDING
    created_at: str = ""
    updated_at: str = ""
    version: int = 1
    last_editor: str = ""
    metadata: dict[str, Any] = {}

    def model_post_init(self, __context) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if not self.id:
            self.id = str(uuid4())[:12]
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now


class DraftVersion(BaseModel):
    draft_id: str
    version: int
    subject: str
    body: str
    editor: str = ""
    edited_at: str = ""
    change_summary: str = ""

    def model_post_init(self, __context) -> None:
        if not self.edited_at:
            self.edited_at = datetime.now(timezone.utc).isoformat()


class SendRequest(BaseModel):
    provider_id: str
    conversation_id: str = ""
    thread_id: str = ""
    workflow_id: str = ""
    subject: str
    body: str
    recipient: Recipient
    sender: Recipient
    cc: list[Recipient] = []
    bcc: list[Recipient] = []
    attachments: list[Attachment] = []
    reply_to_message_id: str = ""
    in_reply_to: str = ""
    references: str = ""
    draft_id: str = ""


class SendResult(BaseModel):
    id: str = ""
    provider_id: str
    external_message_id: str = ""
    thread_id: str = ""
    status: DeliveryStatus = DeliveryStatus.PENDING
    sent_at: str = ""
    error: str = ""
    draft_id: str = ""

    def model_post_init(self, __context) -> None:
        if not self.id:
            self.id = str(uuid4())[:12]
        if not self.sent_at:
            self.sent_at = datetime.now(timezone.utc).isoformat()


class ScheduledMessage(BaseModel):
    id: str = ""
    provider_id: str
    conversation_id: str = ""
    workflow_id: str = ""
    subject: str
    body: str
    recipient: Recipient
    sender: Recipient
    send_at: str
    status: DeliveryStatus = DeliveryStatus.SCHEDULED
    created_at: str = ""
    draft_id: str = ""

    def model_post_init(self, __context) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if not self.id:
            self.id = str(uuid4())[:12]
        if not self.created_at:
            self.created_at = now


class OutboundMetadata(BaseModel):
    provider_id: str
    conversation_id: str = ""
    workflow_id: str = ""
    thread_id: str = ""


class DraftListResult(BaseModel):
    drafts: list[DraftMessage] = []
    total: int = 0


class SendHistoryItem(BaseModel):
    id: str = ""
    provider_id: str
    external_message_id: str = ""
    conversation_id: str = ""
    thread_id: str = ""
    workflow_id: str = ""
    subject: str
    recipient: Recipient
    status: DeliveryStatus
    sent_at: str = ""
    draft_id: str = ""
    error: str = ""

    def model_post_init(self, __context) -> None:
        if not self.id:
            self.id = str(uuid4())[:12]
        if not self.sent_at:
            self.sent_at = datetime.now(timezone.utc).isoformat()
