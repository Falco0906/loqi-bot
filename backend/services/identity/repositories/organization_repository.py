from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from services.identity.models import Organization
from services.identity.repositories.base import InMemoryRepository, Repository


class OrganizationRepository(Repository[Organization], ABC):

    @abstractmethod
    async def find_by_slug(self, slug: str) -> Organization | None:
        ...

    @abstractmethod
    async def find_by_owner_id(self, owner_id: str) -> List[Organization]:
        ...


class InMemoryOrganizationRepository(InMemoryRepository[Organization], OrganizationRepository):

    async def find_by_slug(self, slug: str) -> Organization | None:
        for org in self._all():
            if org.slug == slug:
                return org
        return None

    async def find_by_owner_id(self, owner_id: str) -> list[Organization]:
        return [org for org in self._all() if org.owner_id == owner_id]
