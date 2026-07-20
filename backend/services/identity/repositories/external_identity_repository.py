from __future__ import annotations

from abc import ABC, abstractmethod

from services.identity.models import ExternalIdentity
from services.identity.repositories.base import InMemoryRepository, Repository


class ExternalIdentityRepository(Repository[ExternalIdentity], ABC):

    @abstractmethod
    async def find_by_user_id(self, user_id: str) -> list[ExternalIdentity]:
        ...

    @abstractmethod
    async def find_by_provider(
        self, provider_type: str, provider_subject: str,
    ) -> ExternalIdentity | None:
        ...

    @abstractmethod
    async def find_by_email(self, email: str) -> list[ExternalIdentity]:
        ...


class InMemoryExternalIdentityRepository(
    InMemoryRepository[ExternalIdentity], ExternalIdentityRepository,
):

    async def find_by_user_id(self, user_id: str) -> list[ExternalIdentity]:
        return [ei for ei in self._all() if ei.user_id == user_id]

    async def find_by_provider(
        self, provider_type: str, provider_subject: str,
    ) -> ExternalIdentity | None:
        for ei in self._all():
            if ei.provider_type == provider_type and ei.provider_subject == provider_subject:
                return ei
        return None

    async def find_by_email(self, email: str) -> list[ExternalIdentity]:
        return [ei for ei in self._all() if ei.email == email]
