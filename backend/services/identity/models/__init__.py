from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from services.identity.models.oauth_session import OAuthSession
from services.identity.types import (
    EmailAddress,
    ExternalIdentityId,
    PasswordHash,
    TokenHash,
)


class MembershipStatus(str, Enum):
    ACTIVE = "active"
    INVITED = "invited"
    SUSPENDED = "suspended"


class InvitationStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    REVOKED = "revoked"


class VerificationTokenPurpose(str, Enum):
    VERIFY_EMAIL = "verify_email"
    ACCEPT_INVITE = "accept_invite"
    CHANGE_EMAIL = "change_email"


class RegistrationSessionStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    COMPLETED = "completed"
    EXPIRED = "expired"


# ─── User ──────────────────────────────────────────────────────────────

@dataclass
class User:
    id: str = field(default_factory=lambda: str(uuid4()))
    display_name: str = ""
    avatar_url: str = ""
    locale: str = "en"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    deleted_at: datetime | None = None

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        self.deleted_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)


# ─── EmailIdentity ─────────────────────────────────────────────────────

@dataclass
class EmailIdentity:
    id: str = field(default_factory=lambda: str(uuid4()))
    user_id: str = ""
    email: EmailAddress | str = ""
    is_verified: bool = False
    is_primary: bool = False
    verified_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if isinstance(self.email, str) and self.email:
            self.email = EmailAddress(self.email)

    def verify(self) -> None:
        self.is_verified = True
        self.verified_at = datetime.now(timezone.utc)


# ─── PasswordCredential ────────────────────────────────────────────────

@dataclass
class PasswordCredential:
    id: str = field(default_factory=lambda: str(uuid4()))
    user_id: str = ""
    password_hash: PasswordHash | str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_changed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if isinstance(self.password_hash, str) and self.password_hash:
            self.password_hash = PasswordHash(self.password_hash)

    def update_hash(self, new_hash: PasswordHash) -> None:
        self.password_hash = new_hash
        self.last_changed_at = datetime.now(timezone.utc)


# ─── Organization ──────────────────────────────────────────────────────

@dataclass
class Organization:
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    slug: str = ""
    owner_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    deleted_at: datetime | None = None

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def soft_delete(self) -> None:
        self.deleted_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)


# ─── Membership ────────────────────────────────────────────────────────

@dataclass
class Membership:
    id: str = field(default_factory=lambda: str(uuid4()))
    user_id: str = ""
    organization_id: str = ""
    role: str = "member"
    status: MembershipStatus = MembershipStatus.ACTIVE
    invited_by: str = ""
    invited_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    accepted_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.status == MembershipStatus.ACTIVE

    def activate(self) -> None:
        self.status = MembershipStatus.ACTIVE
        self.accepted_at = datetime.now(timezone.utc)

    def suspend(self) -> None:
        self.status = MembershipStatus.SUSPENDED


# ─── Session ───────────────────────────────────────────────────────────

@dataclass
class Session:
    id: str = field(default_factory=lambda: str(uuid4()))
    user_id: str = ""
    organization_id: str = ""
    provider_type: str = ""
    device_info: str = ""
    ip_address: str = ""
    user_agent: str = ""
    last_activity_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    revoked_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_active(self) -> bool:
        return (
            self.revoked_at is None
            and datetime.now(timezone.utc) < self.expires_at
        )

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at

    def revoke(self) -> None:
        self.revoked_at = datetime.now(timezone.utc)

    def touch(self) -> None:
        self.last_activity_at = datetime.now(timezone.utc)


# ─── RefreshToken ──────────────────────────────────────────────────────

@dataclass
class RefreshToken:
    id: str = field(default_factory=lambda: str(uuid4()))
    session_id: str = ""
    token_hash: TokenHash | str = ""
    family: str = ""
    sequence: int = 1
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    revoked_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if isinstance(self.token_hash, str) and self.token_hash:
            self.token_hash = TokenHash(self.token_hash)

    @property
    def is_active(self) -> bool:
        return (
            self.revoked_at is None
            and datetime.now(timezone.utc) < self.expires_at
        )

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def revoke(self) -> None:
        self.revoked_at = datetime.now(timezone.utc)


# ─── VerificationToken ─────────────────────────────────────────────────

@dataclass
class VerificationToken:
    id: str = field(default_factory=lambda: str(uuid4()))
    purpose: VerificationTokenPurpose = VerificationTokenPurpose.VERIFY_EMAIL
    target: str = ""
    token_hash: TokenHash | str = ""
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    used_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if isinstance(self.token_hash, str) and self.token_hash:
            self.token_hash = TokenHash(self.token_hash)

    @property
    def is_used(self) -> bool:
        return self.used_at is not None

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at

    @property
    def is_valid(self) -> bool:
        return not self.is_used and not self.is_expired

    def mark_used(self) -> None:
        self.used_at = datetime.now(timezone.utc)


# ─── Invitation ────────────────────────────────────────────────────────

@dataclass
class Invitation:
    id: str = field(default_factory=lambda: str(uuid4()))
    organization_id: str = ""
    invited_by_user_id: str = ""
    invitee_email: EmailAddress | str = ""
    status: InvitationStatus = InvitationStatus.PENDING
    role: str = "member"
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    accepted_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if isinstance(self.invitee_email, str) and self.invitee_email:
            self.invitee_email = EmailAddress(self.invitee_email)

    @property
    def is_pending(self) -> bool:
        return (
            self.status == InvitationStatus.PENDING
            and datetime.now(timezone.utc) < self.expires_at
        )

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at

    def accept(self) -> None:
        self.status = InvitationStatus.ACCEPTED
        self.accepted_at = datetime.now(timezone.utc)

    def revoke(self) -> None:
        self.status = InvitationStatus.REVOKED


# ─── PasswordResetRequest ──────────────────────────────────────────────

@dataclass
class PasswordResetRequest:
    id: str = field(default_factory=lambda: str(uuid4()))
    user_id: str = ""
    token_hash: TokenHash | str = ""
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    used_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if isinstance(self.token_hash, str) and self.token_hash:
            self.token_hash = TokenHash(self.token_hash)

    @property
    def is_used(self) -> bool:
        return self.used_at is not None

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at

    @property
    def is_valid(self) -> bool:
        return not self.is_used and not self.is_expired

    def mark_used(self) -> None:
        self.used_at = datetime.now(timezone.utc)


# ─── ExternalIdentity ──────────────────────────────────────────────────

@dataclass
class ExternalIdentity:
    id: str = field(default_factory=lambda: str(uuid4()))
    user_id: str = ""
    provider_type: str = ""
    provider_subject: str = ""
    email: str = ""
    display_name: str = ""
    avatar_url: str = ""
    provider_metadata: dict[str, Any] = field(default_factory=dict)
    linked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_login_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ─── RegistrationSession ────────────────────────────────────────────────

@dataclass
class RegistrationSession:
    id: str = field(default_factory=lambda: str(uuid4()))
    email: str = ""
    status: RegistrationSessionStatus = RegistrationSessionStatus.PENDING
    verification_token_id: str = ""
    email_identity_id: str = ""
    user_id: str = ""
    organization_id: str = ""
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at

    def mark_verified(self, email_identity_id: str) -> None:
        self.status = RegistrationSessionStatus.VERIFIED
        self.email_identity_id = email_identity_id
        self.updated_at = datetime.now(timezone.utc)

    def mark_completed(self, user_id: str, organization_id: str) -> None:
        self.status = RegistrationSessionStatus.COMPLETED
        self.user_id = user_id
        self.organization_id = organization_id
        self.updated_at = datetime.now(timezone.utc)
