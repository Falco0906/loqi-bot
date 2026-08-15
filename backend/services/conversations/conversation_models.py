"""Conversation domain models.

Every sent outbound message belongs to exactly one Conversation.
Conversations are provider-agnostic — they can represent Gmail, LinkedIn, etc.
"""

from __future__ import annotations
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class ConversationStatus(str, Enum):
    NEW = "new"
    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    REPLIED = "replied"
    FOLLOW_UP_PENDING = "follow_up_pending"
    FOLLOW_UP_READY = "follow_up_ready"
    FOLLOW_UP_SENT = "follow_up_sent"
    INTERESTED = "interested"
    MEETING_BOOKED = "meeting_booked"
    CLOSED_WON = "closed_won"
    CLOSED_LOST = "closed_lost"
    BOUNCED = "bounced"


class ReplyCategory(str, Enum):
    INTERESTED = "interested"
    NOT_INTERESTED = "not_interested"
    QUESTION = "question"
    PRICING_REQUEST = "pricing_request"
    MEETING_REQUEST = "meeting_request"
    REFERRAL = "referral"
    OUT_OF_OFFICE = "out_of_office"
    BOUNCE = "bounce"
    AUTO_REPLY = "auto_reply"
    UNKNOWN = "unknown"


class ConversationParticipant:
    def __init__(
        self,
        email: str,
        name: str = "",
        role: str = "contact",
        provider_id: str = "",
        external_id: str = "",
    ):
        self.email = email
        self.name = name
        self.role = role
        self.provider_id = provider_id
        self.external_id = external_id

    def to_dict(self) -> dict:
        return {
            "email": self.email,
            "name": self.name,
            "role": self.role,
            "provider_id": self.provider_id,
            "external_id": self.external_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ConversationParticipant:
        return cls(
            email=data.get("email", ""),
            name=data.get("name", ""),
            role=data.get("role", "contact"),
            provider_id=data.get("provider_id", ""),
            external_id=data.get("external_id", ""),
        )


class ConversationSummary:
    def __init__(
        self,
        company: str = "",
        contact_name: str = "",
        contact_email: str = "",
        interest_level: str = "unknown",
        key_points: list[str] = None,
        next_action: str = "",
        last_summary: str = "",
        updated_at: Optional[datetime] = None,
    ):
        self.company = company
        self.contact_name = contact_name
        self.contact_email = contact_email
        self.interest_level = interest_level
        self.key_points = key_points or []
        self.next_action = next_action
        self.last_summary = last_summary
        self.updated_at = updated_at or datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            "company": self.company,
            "contact_name": self.contact_name,
            "contact_email": self.contact_email,
            "interest_level": self.interest_level,
            "key_points": self.key_points,
            "next_action": self.next_action,
            "last_summary": self.last_summary,
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
        }

    @classmethod
    def from_dict(cls, data: dict) -> ConversationSummary:
        updated = data.get("updated_at")
        if updated and isinstance(updated, str):
            try:
                updated = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            except Exception:
                updated = datetime.now(timezone.utc)
        return cls(
            company=data.get("company", ""),
            contact_name=data.get("contact_name", ""),
            contact_email=data.get("contact_email", ""),
            interest_level=data.get("interest_level", "unknown"),
            key_points=data.get("key_points", []),
            next_action=data.get("next_action", ""),
            last_summary=data.get("last_summary", ""),
            updated_at=updated,
        )


class Conversation:
    def __init__(
        self,
        conversation_id: str = "",
        provider_id: str = "",
        provider_type: str = "",
        external_thread_id: str = "",
        subject: str = "",
        status: ConversationStatus = ConversationStatus.NEW,
        participants: list[ConversationParticipant] = None,
        summary: Optional[ConversationSummary] = None,
        campaign_id: str = "",
        workflow_id: str = "",
        lead_id: str = "",
        owner_id: str = "",
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        last_activity_at: Optional[datetime] = None,
        message_count: int = 0,
        metadata: dict = None,
    ):
        self.conversation_id = conversation_id or str(uuid.uuid4())
        self.provider_id = provider_id
        self.provider_type = provider_type
        self.external_thread_id = external_thread_id
        self.subject = subject
        self.status = status
        self.participants = participants or []
        self.summary = summary or ConversationSummary()
        self.campaign_id = campaign_id
        self.workflow_id = workflow_id
        self.lead_id = lead_id
        self.owner_id = owner_id
        self.created_at = created_at or datetime.now(timezone.utc)
        self.updated_at = updated_at or datetime.now(timezone.utc)
        self.last_activity_at = last_activity_at or datetime.now(timezone.utc)
        self.message_count = message_count
        self.metadata = metadata or {}

    def to_dict(self) -> dict:
        now = datetime.now(timezone.utc)
        return {
            "conversation_id": self.conversation_id,
            "provider_id": self.provider_id,
            "provider_type": self.provider_type,
            "external_thread_id": self.external_thread_id,
            "subject": self.subject,
            "status": self.status.value,
            "participants": [p.to_dict() for p in self.participants],
            "summary": self.summary.to_dict() if self.summary else {},
            "campaign_id": self.campaign_id,
            "workflow_id": self.workflow_id,
            "lead_id": self.lead_id,
            "owner_id": self.owner_id,
            "created_at": self.created_at.isoformat() if self.created_at else now.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else now.isoformat(),
            "last_activity_at": self.last_activity_at.isoformat() if self.last_activity_at else now.isoformat(),
            "message_count": self.message_count,
            "last_message_preview": self.metadata.get("last_message_preview", ""),
            "company_name": self.summary.company if self.summary else "",
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Conversation:
        def _parse_dt(key: str) -> Optional[datetime]:
            val = data.get(key)
            if val and isinstance(val, str):
                try:
                    return datetime.fromisoformat(val.replace("Z", "+00:00"))
                except Exception:
                    pass
            return None

        participants = [ConversationParticipant.from_dict(p) for p in data.get("participants", [])]
        summary_raw = data.get("summary", {})
        summary = ConversationSummary.from_dict(summary_raw) if summary_raw else None
        status_val = data.get("status", "new")
        try:
            status = ConversationStatus(status_val)
        except ValueError:
            status = ConversationStatus.NEW
        return cls(
            conversation_id=data.get("conversation_id", ""),
            provider_id=data.get("provider_id", ""),
            provider_type=data.get("provider_type", ""),
            external_thread_id=data.get("external_thread_id", ""),
            subject=data.get("subject", ""),
            status=status,
            participants=participants,
            summary=summary,
            campaign_id=data.get("campaign_id", ""),
            workflow_id=data.get("workflow_id", ""),
            lead_id=data.get("lead_id", ""),
            owner_id=data.get("owner_id", ""),
            created_at=_parse_dt("created_at"),
            updated_at=_parse_dt("updated_at"),
            last_activity_at=_parse_dt("last_activity_at"),
            message_count=data.get("message_count", 0),
            metadata=data.get("metadata", {}),
        )


class ConversationThread:
    """A thread within a conversation.
    One conversation may have multiple threads (e.g. a follow-up thread).
    """

    def __init__(
        self,
        thread_id: str = "",
        conversation_id: str = "",
        external_thread_id: str = "",
        provider_id: str = "",
        subject: str = "",
        created_at: Optional[datetime] = None,
        last_message_at: Optional[datetime] = None,
        message_count: int = 0,
        metadata: dict = None,
    ):
        self.thread_id = thread_id or str(uuid.uuid4())
        self.conversation_id = conversation_id
        self.external_thread_id = external_thread_id
        self.provider_id = provider_id
        self.subject = subject
        self.created_at = created_at or datetime.now(timezone.utc)
        self.last_message_at = last_message_at or datetime.now(timezone.utc)
        self.message_count = message_count
        self.metadata = metadata or {}

    def to_dict(self) -> dict:
        now = datetime.now(timezone.utc)
        return {
            "thread_id": self.thread_id,
            "conversation_id": self.conversation_id,
            "external_thread_id": self.external_thread_id,
            "provider_id": self.provider_id,
            "subject": self.subject,
            "created_at": self.created_at.isoformat() if self.created_at else now.isoformat(),
            "last_message_at": self.last_message_at.isoformat() if self.last_message_at else now.isoformat(),
            "message_count": self.message_count,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ConversationThread:
        def _parse_dt(key: str) -> Optional[datetime]:
            val = data.get(key)
            if val and isinstance(val, str):
                try:
                    return datetime.fromisoformat(val.replace("Z", "+00:00"))
                except Exception:
                    pass
            return None

        return cls(
            thread_id=data.get("thread_id", ""),
            conversation_id=data.get("conversation_id", ""),
            external_thread_id=data.get("external_thread_id", ""),
            provider_id=data.get("provider_id", ""),
            subject=data.get("subject", ""),
            created_at=_parse_dt("created_at"),
            last_message_at=_parse_dt("last_message_at"),
            message_count=data.get("message_count", 0),
            metadata=data.get("metadata", {}),
        )


class ConversationMessage:
    """A single message within a conversation thread."""

    def __init__(
        self,
        message_id: str = "",
        conversation_id: str = "",
        thread_id: str = "",
        provider_id: str = "",
        external_message_id: str = "",
        direction: str = "outbound",
        from_email: str = "",
        from_name: str = "",
        to_email: str = "",
        to_name: str = "",
        subject: str = "",
        body: str = "",
        body_preview: str = "",
        sent_at: Optional[datetime] = None,
        classification: Optional[dict] = None,
        metadata: dict = None,
    ):
        self.message_id = message_id or str(uuid.uuid4())
        self.conversation_id = conversation_id
        self.thread_id = thread_id
        self.provider_id = provider_id
        self.external_message_id = external_message_id
        self.direction = direction
        self.from_email = from_email
        self.from_name = from_name
        self.to_email = to_email
        self.to_name = to_name
        self.subject = subject
        self.body = body
        self.body_preview = body_preview or body[:200] if body else ""
        self.sent_at = sent_at or datetime.now(timezone.utc)
        self.classification = classification or {}
        self.metadata = metadata or {}

    def to_dict(self) -> dict:
        now = datetime.now(timezone.utc)
        return {
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "thread_id": self.thread_id,
            "provider_id": self.provider_id,
            "external_message_id": self.external_message_id,
            "direction": self.direction,
            "from_email": self.from_email,
            "from_name": self.from_name,
            "to_email": self.to_email,
            "to_name": self.to_name,
            "subject": self.subject,
            "body": self.body,
            "body_preview": self.body_preview,
            "sent_at": self.sent_at.isoformat() if self.sent_at else now.isoformat(),
            "classification": self.classification,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ConversationMessage:
        def _parse_dt(key: str) -> Optional[datetime]:
            val = data.get(key)
            if val and isinstance(val, str):
                try:
                    return datetime.fromisoformat(val.replace("Z", "+00:00"))
                except Exception:
                    pass
            return None

        return cls(
            message_id=data.get("message_id", ""),
            conversation_id=data.get("conversation_id", ""),
            thread_id=data.get("thread_id", ""),
            provider_id=data.get("provider_id", ""),
            external_message_id=data.get("external_message_id", ""),
            direction=data.get("direction", "outbound"),
            from_email=data.get("from_email", ""),
            from_name=data.get("from_name", ""),
            to_email=data.get("to_email", ""),
            to_name=data.get("to_name", ""),
            subject=data.get("subject", ""),
            body=data.get("body", ""),
            body_preview=data.get("body_preview", ""),
            sent_at=_parse_dt("sent_at"),
            classification=data.get("classification", {}),
            metadata=data.get("metadata", {}),
        )
