from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class IdentityEventType(str, Enum):
    USER_CREATED = "user.created"
    EMAIL_VERIFIED = "email.verified"
    PASSWORD_SET = "password.set"
    PASSWORD_CHANGED = "password.changed"
    ORGANIZATION_CREATED = "organization.created"
    MEMBER_INVITED = "member.invited"
    MEMBER_JOINED = "member.joined"
    SESSION_CREATED = "session.created"
    SESSION_REVOKED = "session.revoked"
    PASSWORD_RESET_REQUESTED = "password_reset.requested"
    PASSWORD_RESET_COMPLETED = "password_reset.completed"
    LOGIN_SUCCESS = "login.success"
    TOKEN_REFRESHED = "token.refreshed"
    OAUTH_LOGIN = "oauth.login"
    OAUTH_LINKED = "oauth.linked"


@dataclass
class IdentityEvent:
    event_type: IdentityEventType
    entity_id: str = ""
    actor_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def user_created(cls, user_id: str, email: str = "") -> IdentityEvent:
        return cls(
            event_type=IdentityEventType.USER_CREATED,
            entity_id=user_id,
            data={"email": email},
        )

    @classmethod
    def email_verified(cls, user_id: str, email: str) -> IdentityEvent:
        return cls(
            event_type=IdentityEventType.EMAIL_VERIFIED,
            entity_id=user_id,
            data={"email": email},
        )

    @classmethod
    def password_set(cls, user_id: str) -> IdentityEvent:
        return cls(
            event_type=IdentityEventType.PASSWORD_SET,
            entity_id=user_id,
        )

    @classmethod
    def password_changed(cls, user_id: str) -> IdentityEvent:
        return cls(
            event_type=IdentityEventType.PASSWORD_CHANGED,
            entity_id=user_id,
        )

    @classmethod
    def organization_created(cls, org_id: str, owner_id: str, name: str) -> IdentityEvent:
        return cls(
            event_type=IdentityEventType.ORGANIZATION_CREATED,
            entity_id=org_id,
            actor_id=owner_id,
            data={"name": name},
        )

    @classmethod
    def member_invited(cls, org_id: str, invited_by: str, invitee_email: str) -> IdentityEvent:
        return cls(
            event_type=IdentityEventType.MEMBER_INVITED,
            entity_id=org_id,
            actor_id=invited_by,
            data={"invitee_email": invitee_email},
        )

    @classmethod
    def member_joined(cls, org_id: str, user_id: str) -> IdentityEvent:
        return cls(
            event_type=IdentityEventType.MEMBER_JOINED,
            entity_id=org_id,
            actor_id=user_id,
        )

    @classmethod
    def session_created(cls, session_id: str, user_id: str) -> IdentityEvent:
        return cls(
            event_type=IdentityEventType.SESSION_CREATED,
            entity_id=session_id,
            actor_id=user_id,
        )

    @classmethod
    def session_revoked(cls, session_id: str, user_id: str) -> IdentityEvent:
        return cls(
            event_type=IdentityEventType.SESSION_REVOKED,
            entity_id=session_id,
            actor_id=user_id,
        )

    @classmethod
    def password_reset_requested(cls, user_id: str) -> IdentityEvent:
        return cls(
            event_type=IdentityEventType.PASSWORD_RESET_REQUESTED,
            entity_id=user_id,
        )

    @classmethod
    def password_reset_completed(cls, user_id: str) -> IdentityEvent:
        return cls(
            event_type=IdentityEventType.PASSWORD_RESET_COMPLETED,
            entity_id=user_id,
        )

    @classmethod
    def login_success(cls, user_id: str, session_id: str) -> IdentityEvent:
        return cls(
            event_type=IdentityEventType.LOGIN_SUCCESS,
            entity_id=user_id,
            data={"session_id": session_id},
        )

    @classmethod
    def token_refreshed(cls, user_id: str, session_id: str, family: str) -> "IdentityEvent":
        return cls(
            event_type=IdentityEventType.TOKEN_REFRESHED,
            entity_id=session_id,
            actor_id=user_id,
            data={"family": family},
        )

    @classmethod
    def oauth_login(cls, user_id: str, provider: str) -> "IdentityEvent":
        return cls(
            event_type=IdentityEventType.OAUTH_LOGIN,
            entity_id=user_id,
            data={"provider": provider},
        )

    @classmethod
    def oauth_linked(cls, user_id: str, provider: str) -> "IdentityEvent":
        return cls(
            event_type=IdentityEventType.OAUTH_LINKED,
            entity_id=user_id,
            data={"provider": provider},
        )
