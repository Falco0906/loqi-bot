from __future__ import annotations

from abc import ABC, abstractmethod

from services.identity.models.oauth_session import OAuthSession
from services.identity.repositories.base import InMemoryRepository, Repository


class OAuthSessionRepository(Repository[OAuthSession], ABC):

    @abstractmethod
    async def find_by_state(self, state: str) -> OAuthSession | None:
        ...


class InMemoryOAuthSessionRepository(
    InMemoryRepository[OAuthSession], OAuthSessionRepository,
):

    async def find_by_state(self, state: str) -> OAuthSession | None:
        for s in self._all():
            if s.state == state:
                return s
        return None
