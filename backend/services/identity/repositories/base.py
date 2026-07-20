from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

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
