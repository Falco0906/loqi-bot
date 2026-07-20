from __future__ import annotations

from services.organizations.exceptions import MembershipNotFound, OrganizationNotFound
from services.organizations.models import MembershipRole
from services.organizations.repositories import MembershipRepository, OrganizationRepository


class CurrentOrganizationResolver:

    def __init__(
        self,
        org_repo: OrganizationRepository,
        membership_repo: MembershipRepository,
    ) -> None:
        self._org_repo = org_repo
        self._membership_repo = membership_repo

    async def resolve(self, user_id: str) -> str | None:
        memberships = await self._membership_repo.find_active_by_user_id(user_id)
        if not memberships:
            return None
        return memberships[0].organization_id

    async def require(self, user_id: str) -> str:
        org_id = await self.resolve(user_id)
        if org_id is None:
            raise MembershipNotFound("User does not belong to any organization")
        return org_id

    async def resolve_org_id(self, user_id: str, organization_id: str | None = None) -> str:
        if organization_id:
            return organization_id
        return await self.require(user_id)

    async def get_role(self, user_id: str, organization_id: str | None = None) -> str | None:
        resolved_org_id = organization_id or await self.resolve(user_id)
        if not resolved_org_id:
            return None
        membership = await self._membership_repo.find_by_user_and_org(user_id, resolved_org_id)
        if membership is None:
            return None
        return membership.role.value

    async def require_role(self, user_id: str, organization_id: str | None = None) -> str:
        role = await self.get_role(user_id, organization_id)
        if role is None:
            raise MembershipNotFound("User is not a member of this organization")
        return role

    async def require_at_least_admin(self, user_id: str, organization_id: str | None = None) -> None:
        resolved_org_id = organization_id or await self.require(user_id)
        role = await self.get_role(user_id, resolved_org_id)
        if role not in (MembershipRole.OWNER.value, MembershipRole.ADMIN.value):
            raise PermissionError("Admin or Owner role required")

    async def require_owner(self, user_id: str, organization_id: str | None = None) -> None:
        resolved_org_id = organization_id or await self.require(user_id)
        role = await self.get_role(user_id, resolved_org_id)
        if role != MembershipRole.OWNER.value:
            raise PermissionError("Owner role required")
