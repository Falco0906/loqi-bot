from __future__ import annotations

import secrets
from datetime import datetime, timezone, timedelta

from services.organizations.events import OrgEvent
from services.organizations.exceptions import (
    CannotInviteExistingMember,
    CannotManageOwner,
    InsufficientRole,
    InvitationAlreadyAccepted,
    InvitationExpired,
    InvitationNotFound,
    LastOwnerCannotBeRemoved,
    LastOwnerCannotLeave,
    MembershipAlreadyExists,
    MembershipNotFound,
    OrganizationNotActive,
    OrganizationNotFound,
    OrganizationSlugTaken,
    OrganizationNameTaken,
)
from services.organizations.models import (
    Invitation,
    InvitationStatus,
    Membership,
    MembershipRole,
    MembershipStatus,
    Organization,
    OrganizationSettings,
    OrganizationStatus,
)
from services.organizations.repositories import (
    InvitationRepository,
    MembershipRepository,
    OrganizationRepository,
)


class OrganizationService:

    def __init__(
        self,
        org_repo: OrganizationRepository,
        membership_repo: MembershipRepository,
    ) -> None:
        self._org_repo = org_repo
        self._membership_repo = membership_repo
        self._events: list[OrgEvent] = []

    @property
    def events(self) -> list[OrgEvent]:
        return list(self._events)

    def clear_events(self) -> None:
        self._events.clear()

    async def create_organization(
        self,
        name: str,
        created_by: str,
        slug: str | None = None,
        display_name: str | None = None,
        description: str = "",
    ) -> Organization:
        if slug:
            existing = await self._org_repo.find_by_slug(slug)
            if existing:
                raise OrganizationSlugTaken(slug)
        else:
            slug = await self._generate_unique_slug(name)

        existing_name = await self._org_repo.find_by_name(name)
        if existing_name:
            raise OrganizationNameTaken(name)

        organization = Organization(
            name=name,
            slug=slug,
            display_name=display_name or name,
            description=description,
            created_by=created_by,
            settings=OrganizationSettings(),
        )

        organization = await self._org_repo.save(organization)

        owner_membership = Membership(
            organization_id=organization.id,
            user_id=created_by,
            role=MembershipRole.OWNER,
            status=MembershipStatus.ACTIVE,
            invited_by=created_by,
        )
        await self._membership_repo.save(owner_membership)

        self._events.append(OrgEvent.organization_created(organization.id, created_by, name))

        return organization

    async def get_organization(self, organization_id: str) -> Organization:
        org = await self._org_repo.get(organization_id)
        if org is None or org.is_deleted:
            raise OrganizationNotFound(organization_id)
        return org

    async def get_organization_by_slug(self, slug: str) -> Organization:
        org = await self._org_repo.find_by_slug(slug)
        if org is None:
            raise OrganizationNotFound(slug)
        return org

    async def update_organization(
        self,
        organization_id: str,
        updated_by: str,
        **kwargs: str | None,
    ) -> Organization:
        org = await self.get_organization(organization_id)

        changes: dict[str, object] = {}
        for field_name in ("name", "slug", "display_name", "description", "avatar_url"):
            if field_name in kwargs and kwargs[field_name] is not None:
                val = kwargs[field_name]
                if field_name == "slug" and val != org.slug:
                    existing = await self._org_repo.find_by_slug(val)
                    if existing:
                        raise OrganizationSlugTaken(val)
                if field_name == "name" and val != org.name:
                    existing = await self._org_repo.find_by_name(val)
                    if existing:
                        raise OrganizationNameTaken(val)
                setattr(org, field_name, val)
                changes[field_name] = val

        if kwargs.get("metadata") is not None:
            new_meta = kwargs["metadata"]
            if isinstance(new_meta, dict):
                old_meta = dict(org.metadata)
                org.metadata.update(new_meta)
                changes["metadata"] = new_meta

        org.touch()
        org = await self._org_repo.save(org)

        if changes:
            self._events.append(OrgEvent.organization_updated(organization_id, updated_by, changes))

        return org

    async def soft_delete_organization(self, organization_id: str, deleted_by: str) -> None:
        org = await self.get_organization(organization_id)
        org.soft_delete()
        await self._org_repo.save(org)
        self._events.append(OrgEvent.organization_deleted(organization_id, deleted_by))

    async def list_user_organizations(self, user_id: str) -> list[Organization]:
        memberships = await self._membership_repo.find_active_by_user_id(user_id)
        orgs: list[Organization] = []
        for membership in memberships:
            org = await self._org_repo.get(membership.organization_id)
            if org and not org.is_deleted:
                orgs.append(org)
        return orgs

    async def _generate_unique_slug(self, name: str) -> str:
        base = name.lower().replace(" ", "-").replace("_", "-")
        base = "".join(c for c in base if c.isalnum() or c == "-")
        slug = base
        suffix = 1
        while await self._org_repo.find_by_slug(slug):
            slug = f"{base}-{suffix}"
            suffix += 1
        return slug


class MembershipService:

    def __init__(
        self,
        membership_repo: MembershipRepository,
        org_repo: OrganizationRepository,
    ) -> None:
        self._membership_repo = membership_repo
        self._org_repo = org_repo
        self._events: list[OrgEvent] = []

    @property
    def events(self) -> list[OrgEvent]:
        return list(self._events)

    def clear_events(self) -> None:
        self._events.clear()

    async def add_member(
        self,
        organization_id: str,
        user_id: str,
        role: MembershipRole = MembershipRole.MEMBER,
        invited_by: str = "",
    ) -> Membership:
        org = await self._org_repo.get(organization_id)
        if org is None or not org.is_active:
            raise OrganizationNotActive(organization_id)

        existing = await self._membership_repo.find_by_user_and_org(user_id, organization_id)
        if existing:
            if existing.is_active:
                raise MembershipAlreadyExists(user_id, organization_id)
            existing.status = MembershipStatus.ACTIVE
            existing.role = role
            existing.invited_by = invited_by
            existing.joined_at = datetime.now(timezone.utc)
            await self._membership_repo.save(existing)
            self._events.append(OrgEvent.member_joined(organization_id, user_id))
            return existing

        membership = Membership(
            organization_id=organization_id,
            user_id=user_id,
            role=role,
            invited_by=invited_by,
        )
        membership = await self._membership_repo.save(membership)
        self._events.append(OrgEvent.member_joined(organization_id, user_id))
        return membership

    async def require_actor_role(
        self,
        organization_id: str,
        actor_id: str,
        allowed_roles: set[MembershipRole],
    ) -> Membership:
        """Require that ``actor_id`` is an active member with one of the
        allowed roles in ``organization_id``. Raises ``InsufficientRole``
        otherwise (defense-in-depth beyond the API boundary)."""
        membership = await self._membership_repo.find_by_user_and_org(
            actor_id, organization_id,
        )
        if (
            membership is None
            or membership.status != MembershipStatus.ACTIVE
            or membership.role not in allowed_roles
        ):
            raise InsufficientRole("Insufficient permissions")
        return membership

    async def remove_member(self, organization_id: str, user_id: str, removed_by: str) -> None:
        if user_id == removed_by:
            raise LastOwnerCannotLeave("Cannot self-remove; use leave_organization")

        await self.require_actor_role(
            organization_id, removed_by, {MembershipRole.OWNER, MembershipRole.ADMIN},
        )

        membership = await self._membership_repo.find_by_user_and_org(user_id, organization_id)
        if membership is None:
            raise MembershipNotFound()

        if membership.role == MembershipRole.OWNER:
            owner_count = await self._membership_repo.count_owners(organization_id)
            if owner_count <= 1:
                raise LastOwnerCannotBeRemoved()

        membership.mark_removed()
        await self._membership_repo.save(membership)
        self._events.append(OrgEvent.member_removed(organization_id, removed_by, user_id))

    async def leave_organization(self, user_id: str, organization_id: str) -> None:
        membership = await self._membership_repo.find_by_user_and_org(user_id, organization_id)
        if membership is None:
            raise MembershipNotFound()

        if membership.role == MembershipRole.OWNER:
            owner_count = await self._membership_repo.count_owners(organization_id)
            if owner_count <= 1:
                raise LastOwnerCannotLeave(
                    "Cannot leave as the last owner. Transfer ownership first."
                )

        membership.mark_left()
        await self._membership_repo.save(membership)
        self._events.append(OrgEvent.member_left(organization_id, user_id))

    async def change_role(
        self,
        organization_id: str,
        target_user_id: str,
        new_role: MembershipRole,
        changed_by: str,
    ) -> Membership:
        await self.require_actor_role(
            organization_id, changed_by, {MembershipRole.OWNER, MembershipRole.ADMIN},
        )

        membership = await self._membership_repo.find_by_user_and_org(target_user_id, organization_id)
        if membership is None:
            raise MembershipNotFound()

        if membership.role == MembershipRole.OWNER:
            raise CannotManageOwner("Cannot change the owner's role; use transfer_ownership")

        old_role = membership.role.value
        membership.role = new_role
        await self._membership_repo.save(membership)
        self._events.append(
            OrgEvent.role_changed(organization_id, changed_by, target_user_id, old_role, new_role.value)
        )
        return membership

    async def transfer_ownership(
        self,
        organization_id: str,
        current_owner_id: str,
        new_owner_id: str,
    ) -> None:
        current_membership = await self._membership_repo.find_by_user_and_org(
            current_owner_id, organization_id
        )
        if current_membership is None or current_membership.role != MembershipRole.OWNER:
            raise InsufficientRole("Only the current owner can transfer ownership")

        new_owner_membership = await self._membership_repo.find_by_user_and_org(
            new_owner_id, organization_id
        )
        if new_owner_membership is None:
            raise MembershipNotFound("New owner is not a member of this organization")

        current_membership.role = MembershipRole.ADMIN
        new_owner_membership.role = MembershipRole.OWNER

        await self._membership_repo.save(current_membership)
        await self._membership_repo.save(new_owner_membership)

        self._events.append(
            OrgEvent.ownership_transferred(organization_id, current_owner_id, new_owner_id)
        )

    async def get_memberships(
        self,
        organization_id: str,
        status: MembershipStatus | None = None,
    ) -> list[Membership]:
        memberships = await self._membership_repo.find_by_org_id(organization_id)
        if status:
            memberships = [m for m in memberships if m.status == status]
        return memberships

    async def get_user_membership(
        self,
        user_id: str,
        organization_id: str,
    ) -> Membership:
        membership = await self._membership_repo.find_by_user_and_org(user_id, organization_id)
        if membership is None:
            raise MembershipNotFound()
        return membership


class InvitationService:

    def __init__(
        self,
        invitation_repo: InvitationRepository,
        membership_repo: MembershipRepository,
        membership_service: MembershipService,
    ) -> None:
        self._invitation_repo = invitation_repo
        self._membership_repo = membership_repo
        self._membership_service = membership_service
        self._events: list[OrgEvent] = []

    INVITATION_EXPIRY_DAYS = 7

    @property
    def events(self) -> list[OrgEvent]:
        return list(self._events)

    def clear_events(self) -> None:
        self._events.clear()

    async def invite(
        self,
        organization_id: str,
        email: str,
        role: MembershipRole = MembershipRole.MEMBER,
        created_by: str = "",
    ) -> Invitation:
        if created_by:
            await self._membership_service.require_actor_role(
                organization_id, created_by, {MembershipRole.OWNER, MembershipRole.ADMIN},
            )
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(days=self.INVITATION_EXPIRY_DAYS)

        invitation = Invitation(
            organization_id=organization_id,
            email=email,
            role=role,
            token=token,
            expires_at=expires_at,
            created_by=created_by,
        )
        invitation = await self._invitation_repo.save(invitation)

        self._events.append(OrgEvent.member_invited(organization_id, created_by, email))
        return invitation

    async def accept_invitation(self, token: str, user_id: str) -> Membership:
        invitation = await self._invitation_repo.find_by_token(token)
        if invitation is None:
            raise InvitationNotFound()

        if not invitation.is_pending:
            if invitation.status == InvitationStatus.ACCEPTED:
                raise InvitationAlreadyAccepted()
            raise InvitationExpired()

        invitation.accept()
        await self._invitation_repo.save(invitation)

        membership = await self._membership_service.add_member(
            organization_id=invitation.organization_id,
            user_id=user_id,
            role=invitation.role,
            invited_by=invitation.created_by,
        )

        self._events.append(OrgEvent.invitation_accepted(invitation.organization_id, user_id))
        return membership

    async def revoke_invitation(self, invitation_id: str, revoked_by: str) -> None:
        invitation = await self._invitation_repo.get(invitation_id)
        if invitation is None:
            raise InvitationNotFound()

        await self._membership_service.require_actor_role(
            invitation.organization_id, revoked_by, {MembershipRole.OWNER, MembershipRole.ADMIN},
        )

        invitation.revoke()
        await self._invitation_repo.save(invitation)
        self._events.append(OrgEvent.invitation_revoked(invitation.organization_id, revoked_by, invitation_id))

    async def get_organization_invitations(
        self,
        organization_id: str,
    ) -> list[Invitation]:
        return await self._invitation_repo.find_by_org_id(organization_id)

    async def get_pending_invitations(self, email: str) -> list[Invitation]:
        return await self._invitation_repo.find_pending_by_email(email)
