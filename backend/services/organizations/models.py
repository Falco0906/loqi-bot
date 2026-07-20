from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class MembershipRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class MembershipStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    REMOVED = "removed"
    LEFT = "left"


class InvitationStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"


class OrganizationStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


@dataclass
class OrganizationSettings:
    timezone: str = "UTC"
    locale: str = "en"
    branding: dict[str, Any] = field(default_factory=dict)
    preferences: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Organization:
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    slug: str = ""
    display_name: str = ""
    description: str = ""
    avatar_url: str = ""
    created_by: str = ""
    status: OrganizationStatus = OrganizationStatus.ACTIVE
    metadata: dict[str, Any] = field(default_factory=dict)
    settings: OrganizationSettings | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    deleted_at: datetime | None = None

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def is_active(self) -> bool:
        return self.status == OrganizationStatus.ACTIVE and not self.is_deleted

    def soft_delete(self) -> None:
        self.deleted_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)


@dataclass
class Membership:
    id: str = field(default_factory=lambda: str(uuid4()))
    organization_id: str = ""
    user_id: str = ""
    role: MembershipRole = MembershipRole.MEMBER
    status: MembershipStatus = MembershipStatus.ACTIVE
    joined_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    invited_by: str = ""

    @property
    def is_active(self) -> bool:
        return self.status == MembershipStatus.ACTIVE

    def activate(self) -> None:
        self.status = MembershipStatus.ACTIVE
        self.joined_at = datetime.now(timezone.utc)

    def mark_removed(self) -> None:
        self.status = MembershipStatus.REMOVED

    def mark_left(self) -> None:
        self.status = MembershipStatus.LEFT


@dataclass
class Invitation:
    id: str = field(default_factory=lambda: str(uuid4()))
    organization_id: str = ""
    email: str = ""
    role: MembershipRole = MembershipRole.MEMBER
    token: str = ""
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: InvitationStatus = InvitationStatus.PENDING
    created_by: str = ""
    accepted_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

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
