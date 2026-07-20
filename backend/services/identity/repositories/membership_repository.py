from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from services.identity.models import Membership
from services.identity.repositories.base import InMemoryRepository, Repository


class MembershipRepository(Repository[Membership], ABC):

    @abstractmethod
    async def find_by_user_and_org(
        self, user_id: str, organization_id: str,
    ) -> Membership | None:
        ...

    @abstractmethod
    async def find_by_user_id(self, user_id: str) -> List[Membership]:
        ...

    @abstractmethod
    async def find_by_org_id(self, organization_id: str) -> List[Membership]:
        ...

    @abstractmethod
    async def find_active_by_user_id(self, user_id: str) -> List[Membership]:
        ...


class InMemoryMembershipRepository(InMemoryRepository[Membership], MembershipRepository):

    async def find_by_user_and_org(
        self, user_id: str, organization_id: str,
    ) -> Membership | None:
        for m in self._all():
            if m.user_id == user_id and m.organization_id == organization_id:
                return m
        return None

    async def find_by_user_id(self, user_id: str) -> list[Membership]:
        return [m for m in self._all() if m.user_id == user_id]

    async def find_by_org_id(self, organization_id: str) -> list[Membership]:
        return [m for m in self._all() if m.organization_id == organization_id]

    async def find_active_by_user_id(self, user_id: str) -> list[Membership]:
        return [
            m for m in self._all()
            if m.user_id == user_id and m.is_active
        ]
