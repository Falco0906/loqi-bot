from __future__ import annotations

from services.identity.exceptions import (
    InvalidMembershipTransitionException,
    MembershipAlreadyExistsException,
    MembershipNotFoundException,
    OrganizationNotFoundException,
    UserNotFoundException,
)
from services.identity.models import Membership
from services.identity.repositories import (
    MembershipRepository,
    OrganizationRepository,
    UserRepository,
)


class MembershipService:

    def __init__(
        self,
        membership_repo: MembershipRepository,
        user_repo: UserRepository,
        org_repo: OrganizationRepository,
    ) -> None:
        self._membership_repo = membership_repo
        self._user_repo = user_repo
        self._org_repo = org_repo

    async def add_member(
        self, user_id: str, organization_id: str, role: str = "member",
        invited_by: str = "",
    ) -> Membership:
        """Add or reactivate a member on the canonical durable membership row.

        Idempotent and safe: an existing non-active membership (pending,
        removed, left) is reactivated in place (never a duplicate row — the
        DB enforces one row per (user, organization)); an already-active
        membership is rejected rather than silently duplicated.
        """
        user = await self._user_repo.get(user_id)
        if user is None:
            raise UserNotFoundException(user_id)

        org = await self._org_repo.get(organization_id)
        if org is None:
            raise OrganizationNotFoundException(organization_id)

        existing = await self._membership_repo.find_by_user_and_org(
            user_id, organization_id,
        )
        if existing is not None:
            if existing.is_active:
                raise MembershipAlreadyExistsException(user_id, organization_id)
            existing.role = role
            existing.invited_by = invited_by
            existing.activate()  # pending/removed/left -> active
            return await self._membership_repo.save(existing)

        membership = Membership(
            user_id=user_id,
            organization_id=organization_id,
            role=role,
            invited_by=invited_by,
        )
        return await self._membership_repo.save(membership)

    async def activate_membership(self, membership_id: str) -> Membership:
        """Activate a membership (accept an invite or reactivate a member).

        Idempotent for an already-active membership. Reactivation of a removed
        or left member to active is supported by the canonical lifecycle (the
        same transition ``add_member`` performs); invalid transitions (e.g.
        active -> pending) are rejected by the model.
        """
        membership = await self._membership_repo.get(membership_id)
        if membership is None:
            raise MembershipNotFoundException()
        membership.activate()
        return await self._membership_repo.save(membership)

    async def get_membership(self, membership_id: str) -> Membership:
        membership = await self._membership_repo.get(membership_id)
        if membership is None:
            raise MembershipNotFoundException()
        return membership

    async def get_membership_for_user_in_org(
        self, user_id: str, organization_id: str,
    ) -> Membership | None:
        return await self._membership_repo.find_by_user_and_org(user_id, organization_id)

    async def list_members(self, organization_id: str) -> list[Membership]:
        return await self._membership_repo.find_by_org_id(organization_id)

    async def list_user_memberships(self, user_id: str) -> list[Membership]:
        return await self._membership_repo.find_by_user_id(user_id)

    async def remove_member(self, membership_id: str) -> None:
        """Remove (suspend) a member: pending/active -> removed.

        Idempotent for an already-removed membership; a left member must rejoin
        via ``add_member`` rather than being removed again.
        """
        membership = await self.get_membership(membership_id)
        membership.mark_removed()
        await self._membership_repo.save(membership)

    async def leave_organization(self, membership_id: str) -> None:
        """A member voluntarily leaves: active -> left.

        The last-owner invariant is enforced at the organization service layer
        (ownership transfer is out of scope for the identity membership layer).
        """
        membership = await self.get_membership(membership_id)
        membership.mark_left()
        await self._membership_repo.save(membership)

    async def change_role(
        self, membership_id: str, new_role: str,
    ) -> Membership:
        membership = await self.get_membership(membership_id)
        membership.role = new_role
        return await self._membership_repo.save(membership)

    async def is_member_of(self, user_id: str, organization_id: str) -> bool:
        membership = await self._membership_repo.find_by_user_and_org(
            user_id, organization_id,
        )
        return membership is not None and membership.is_active

    async def assert_valid_transition(
        self, membership: Membership, target: str,
    ) -> None:
        """Raise if ``target`` is not a valid canonical transition for ``membership``."""
        from services.identity.models import MembershipStatus
        try:
            membership.transition_to(MembershipStatus(target))
        except InvalidMembershipTransitionException as exc:
            raise InvalidMembershipTransitionException(
                membership.status.value, target,
            ) from exc
