from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from services.onboarding.models import OnboardingSession, UserLifecycle

T = TypeVar("T")


class Repository(ABC, Generic[T]):

    @abstractmethod
    async def save(self, entity: T) -> T:
        ...

    @abstractmethod
    async def get(self, entity_id: str) -> T | None:
        ...

    @abstractmethod
    async def delete(self, entity_id: str) -> bool:
        ...


class InMemoryRepository(Repository[T]):

    def __init__(self) -> None:
        self._store: dict[str, T] = {}

    async def save(self, entity: T) -> T:
        entity_id = str(getattr(entity, "id", ""))
        self._store[entity_id] = entity
        return entity

    async def get(self, entity_id: str) -> T | None:
        return self._store.get(entity_id)

    async def delete(self, entity_id: str) -> bool:
        if entity_id in self._store:
            del self._store[entity_id]
            return True
        return False

    def _all(self) -> list[T]:
        return list(self._store.values())

    def clear(self) -> None:
        self._store.clear()


# ─── LifecycleRepository ──────────────────────────────────────────────


class LifecycleRepository(Repository[UserLifecycle], ABC):

    @abstractmethod
    async def find_by_user_id(self, user_id: str) -> UserLifecycle | None:
        ...

    @abstractmethod
    async def list_all(self) -> list[UserLifecycle]:
        ...


class InMemoryLifecycleRepository(InMemoryRepository[UserLifecycle], LifecycleRepository):

    async def find_by_user_id(self, user_id: str) -> UserLifecycle | None:
        for lc in self._all():
            if lc.user_id == user_id:
                return lc
        return None

    async def list_all(self) -> list[UserLifecycle]:
        return self._all()


# ─── OnboardingSessionRepository ─────────────────────────────────────


class OnboardingSessionRepository(Repository[OnboardingSession], ABC):

    @abstractmethod
    async def find_active_by_user_id(self, user_id: str) -> OnboardingSession | None:
        ...

    @abstractmethod
    async def find_by_user_id(self, user_id: str) -> list[OnboardingSession]:
        ...


class InMemoryOnboardingSessionRepository(
    InMemoryRepository[OnboardingSession], OnboardingSessionRepository,
):

    async def find_active_by_user_id(self, user_id: str) -> OnboardingSession | None:
        for s in self._all():
            if s.user_id == user_id and s.is_active and not s.is_expired:
                return s
        return None

    async def find_by_user_id(self, user_id: str) -> list[OnboardingSession]:
        return [s for s in self._all() if s.user_id == user_id]
