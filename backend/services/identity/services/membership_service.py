from __future__ import annotations

from services.identity.exceptions import (
    MembershipNotFoundException,
    OrganizationNotFoundException,
    UserNotFoundException,
)
from services.identity.models import Membership, MembershipStatus
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
        user = await self._user_repo.get(user_id)
        if user is None:
            raise UserNotFoundException(user_id)

        org = await self._org_repo.get(organization_id)
        if org is None:
            raise OrganizationNotFoundException(organization_id)

        membership = Membership(
            user_id=user_id,
            organization_id=organization_id,
            role=role,
            invited_by=invited_by,
        )
        return await self._membership_repo.save(membership)

    async def activate_membership(self, membership_id: str) -> Membership:
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
        membership = await self.get_membership(membership_id)
        membership.status = MembershipStatus.SUSPENDED
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
