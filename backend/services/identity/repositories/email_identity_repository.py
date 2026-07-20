from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from services.identity.models import EmailIdentity
from services.identity.repositories.base import InMemoryRepository, Repository


class EmailIdentityRepository(Repository[EmailIdentity], ABC):

    @abstractmethod
    async def find_by_email(self, email: str) -> EmailIdentity | None:
        ...

    @abstractmethod
    async def find_by_user_id(self, user_id: str) -> List[EmailIdentity]:
        ...

    @abstractmethod
    async def find_primary_by_user_id(self, user_id: str) -> EmailIdentity | None:
        ...


class InMemoryEmailIdentityRepository(InMemoryRepository[EmailIdentity], EmailIdentityRepository):

    async def find_by_email(self, email: str) -> EmailIdentity | None:
        for ei in self._all():
            if str(ei.email) == email:
                return ei
        return None

    async def find_by_user_id(self, user_id: str) -> list[EmailIdentity]:
        return [ei for ei in self._all() if ei.user_id == user_id]

    async def find_primary_by_user_id(self, user_id: str) -> EmailIdentity | None:
        for ei in self._all():
            if ei.user_id == user_id and ei.is_primary:
                return ei
        return None
