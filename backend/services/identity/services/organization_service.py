from __future__ import annotations

from datetime import datetime, timezone

from services.identity.events import IdentityEvent
from services.identity.exceptions import OrganizationNotFoundException
from services.identity.models import Membership, Organization
from services.identity.repositories import (
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

    async def create_organization(
        self, name: str, owner_id: str,
    ) -> tuple[Organization, Membership, IdentityEvent]:
        slug = await self._unique_slug(_generate_slug(name))

        org = Organization(name=name, slug=slug, owner_id=owner_id)
        saved_org = await self._org_repo.save(org)

        membership = Membership(
            user_id=owner_id,
            organization_id=saved_org.id,
            role="owner",
        )
        membership.activate()
        saved_membership = await self._membership_repo.save(membership)

        event = IdentityEvent.organization_created(saved_org.id, owner_id, name)
        return saved_org, saved_membership, event

    async def get_organization(self, org_id: str) -> Organization:
        org = await self._org_repo.get(org_id)
        if org is None:
            raise OrganizationNotFoundException(org_id)
        return org

    async def find_by_slug(self, slug: str) -> Organization | None:
        return await self._org_repo.find_by_slug(slug)

    async def update_organization(
        self, org_id: str, name: str | None = None,
    ) -> Organization:
        org = await self.get_organization(org_id)
        if name is not None:
            org.name = name
            org.slug = _generate_slug(name)
        org.updated_at = datetime.now(timezone.utc)
        return await self._org_repo.save(org)

    async def soft_delete_organization(self, org_id: str) -> None:
        org = await self.get_organization(org_id)
        org.soft_delete()
        await self._org_repo.save(org)

    async def list_organizations_for_user(self, user_id: str) -> list[Organization]:
        memberships = await self._membership_repo.find_active_by_user_id(user_id)
        orgs: list[Organization] = []
        for m in memberships:
            org = await self._org_repo.get(m.organization_id)
            if org is not None and not org.is_deleted:
                orgs.append(org)
        return orgs


    async def _unique_slug(self, base: str) -> str:
        # Durable organizations carry a unique partial index on slug
        # (006_workspaces.sql: WHERE deleted_at IS NULL), so two accounts
        # naming their org the same must not collide on insert.
        slug = base
        suffix = 1
        while await self._org_repo.find_by_slug(slug) is not None:
            slug = f"{base}-{suffix}"
            suffix += 1
        return slug


def _generate_slug(name: str) -> str:
    slug = name.lower().strip()
    for ch in " -_":
        slug = slug.replace(ch, "-")
    slug = "".join(c for c in slug if c.isalnum() or c == "-")
    slug = slug.strip("-")
    return slug[:64] or "org"
