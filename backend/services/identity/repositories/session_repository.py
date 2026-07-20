from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from services.identity.models import Session
from services.identity.repositories.base import InMemoryRepository, Repository


class SessionRepository(Repository[Session], ABC):

    @abstractmethod
    async def find_by_user_id(self, user_id: str) -> List[Session]:
        ...

    @abstractmethod
    async def find_active_by_user_id(self, user_id: str) -> List[Session]:
        ...

    @abstractmethod
    async def revoke_all_for_user(self, user_id: str) -> int:
        ...

    @abstractmethod
    async def revoke_all_for_org(self, organization_id: str) -> int:
        ...

    @abstractmethod
    async def count_active_by_user_id(self, user_id: str) -> int:
        ...


class InMemorySessionRepository(InMemoryRepository[Session], SessionRepository):

    async def find_by_user_id(self, user_id: str) -> list[Session]:
        return [s for s in self._all() if s.user_id == user_id]

    async def find_active_by_user_id(self, user_id: str) -> list[Session]:
        return [
            s for s in self._all()
            if s.user_id == user_id and s.is_active
        ]

    async def revoke_all_for_user(self, user_id: str) -> int:
        count = 0
        for s in self._all():
            if s.user_id == user_id and not s.is_revoked:
                s.revoke()
                count += 1
        return count

    async def revoke_all_for_org(self, organization_id: str) -> int:
        count = 0
        for s in self._all():
            if s.organization_id == organization_id and not s.is_revoked:
                s.revoke()
                count += 1
        return count

    async def count_active_by_user_id(self, user_id: str) -> int:
        return len(await self.find_active_by_user_id(user_id))
