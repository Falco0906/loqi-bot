from __future__ import annotations

from abc import ABC, abstractmethod

from services.identity.models import PasswordCredential
from services.identity.repositories.base import InMemoryRepository, Repository


class PasswordCredentialRepository(Repository[PasswordCredential], ABC):

    @abstractmethod
    async def find_by_user_id(self, user_id: str) -> PasswordCredential | None:
        ...


class InMemoryPasswordCredentialRepository(
    InMemoryRepository[PasswordCredential], PasswordCredentialRepository
):

    async def find_by_user_id(self, user_id: str) -> PasswordCredential | None:
        for cred in self._all():
            if cred.user_id == user_id:
                return cred
        return None
