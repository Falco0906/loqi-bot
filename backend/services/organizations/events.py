from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class OrgEventType(str, Enum):
    ORGANIZATION_CREATED = "organization.created"
    ORGANIZATION_UPDATED = "organization.updated"
    ORGANIZATION_DELETED = "organization.deleted"
    MEMBER_INVITED = "member.invited"
    MEMBER_JOINED = "member.joined"
    MEMBER_LEFT = "member.left"
    MEMBER_REMOVED = "member.removed"
    ROLE_CHANGED = "role.changed"
    OWNERSHIP_TRANSFERRED = "ownership.transferred"
    INVITATION_ACCEPTED = "invitation.accepted"
    INVITATION_REVOKED = "invitation.revoked"


@dataclass
class OrgEvent:
    event_type: OrgEventType
    entity_id: str = ""
    actor_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def organization_created(cls, org_id: str, created_by: str, name: str) -> OrgEvent:
        return cls(
            event_type=OrgEventType.ORGANIZATION_CREATED,
            entity_id=org_id,
            actor_id=created_by,
            data={"name": name},
        )

    @classmethod
    def organization_updated(cls, org_id: str, updated_by: str, changes: dict[str, Any]) -> OrgEvent:
        return cls(
            event_type=OrgEventType.ORGANIZATION_UPDATED,
            entity_id=org_id,
            actor_id=updated_by,
            data={"changes": changes},
        )

    @classmethod
    def organization_deleted(cls, org_id: str, deleted_by: str) -> OrgEvent:
        return cls(
            event_type=OrgEventType.ORGANIZATION_DELETED,
            entity_id=org_id,
            actor_id=deleted_by,
        )

    @classmethod
    def member_invited(cls, org_id: str, invited_by: str, email: str) -> OrgEvent:
        return cls(
            event_type=OrgEventType.MEMBER_INVITED,
            entity_id=org_id,
            actor_id=invited_by,
            data={"email": email},
        )

    @classmethod
    def member_joined(cls, org_id: str, user_id: str) -> OrgEvent:
        return cls(
            event_type=OrgEventType.MEMBER_JOINED,
            entity_id=org_id,
            actor_id=user_id,
        )

    @classmethod
    def member_left(cls, org_id: str, user_id: str) -> OrgEvent:
        return cls(
            event_type=OrgEventType.MEMBER_LEFT,
            entity_id=org_id,
            actor_id=user_id,
        )

    @classmethod
    def member_removed(cls, org_id: str, removed_by: str, removed_user_id: str) -> OrgEvent:
        return cls(
            event_type=OrgEventType.MEMBER_REMOVED,
            entity_id=org_id,
            actor_id=removed_by,
            data={"removed_user_id": removed_user_id},
        )

    @classmethod
    def role_changed(cls, org_id: str, changed_by: str, target_user_id: str, old_role: str, new_role: str) -> OrgEvent:
        return cls(
            event_type=OrgEventType.ROLE_CHANGED,
            entity_id=org_id,
            actor_id=changed_by,
            data={"target_user_id": target_user_id, "old_role": old_role, "new_role": new_role},
        )

    @classmethod
    def ownership_transferred(cls, org_id: str, previous_owner_id: str, new_owner_id: str) -> OrgEvent:
        return cls(
            event_type=OrgEventType.OWNERSHIP_TRANSFERRED,
            entity_id=org_id,
            actor_id=previous_owner_id,
            data={"new_owner_id": new_owner_id},
        )

    @classmethod
    def invitation_accepted(cls, org_id: str, user_id: str) -> OrgEvent:
        return cls(
            event_type=OrgEventType.INVITATION_ACCEPTED,
            entity_id=org_id,
            actor_id=user_id,
        )

    @classmethod
    def invitation_revoked(cls, org_id: str, revoked_by: str, invitation_id: str) -> OrgEvent:
        return cls(
            event_type=OrgEventType.INVITATION_REVOKED,
            entity_id=org_id,
            actor_id=revoked_by,
            data={"invitation_id": invitation_id},
        )
