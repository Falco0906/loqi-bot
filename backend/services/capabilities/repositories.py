from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from services.capabilities.models import (
    CapabilityDefinition,
    CapabilityLimits,
    CapabilityUsage,
    OrganizationCapability,
)

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
        if not entity_id:
            key = str(id(entity))
            self._store[key] = entity
        else:
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


# ─── CapabilityDefinitionRepository ─────────────────────────────────


class CapabilityDefinitionRepository(Repository[CapabilityDefinition], ABC):

    @abstractmethod
    async def find_by_slug(self, slug: str) -> CapabilityDefinition | None:
        ...

    @abstractmethod
    async def list_all(self) -> list[CapabilityDefinition]:
        ...

    @abstractmethod
    async def list_by_category(self, category: str) -> list[CapabilityDefinition]:
        ...


class InMemoryCapabilityDefinitionRepository(
    InMemoryRepository[CapabilityDefinition], CapabilityDefinitionRepository,
):

    async def find_by_slug(self, slug: str) -> CapabilityDefinition | None:
        for c in self._all():
            if c.slug == slug:
                return c
        return None

    async def list_all(self) -> list[CapabilityDefinition]:
        return self._all()

    async def list_by_category(self, category: str) -> list[CapabilityDefinition]:
        return [c for c in self._all() if c.category == category]


# ─── OrganizationCapabilityRepository ────────────────────────────────


class OrganizationCapabilityRepository(Repository[OrganizationCapability], ABC):

    @abstractmethod
    async def find_by_organization_and_slug(
        self, organization_id: str, slug: str,
    ) -> OrganizationCapability | None:
        ...

    @abstractmethod
    async def list_by_organization(
        self, organization_id: str,
    ) -> list[OrganizationCapability]:
        ...

    @abstractmethod
    async def list_enabled_by_organization(
        self, organization_id: str,
    ) -> list[OrganizationCapability]:
        ...


class InMemoryOrganizationCapabilityRepository(
    InMemoryRepository[OrganizationCapability], OrganizationCapabilityRepository,
):

    async def find_by_organization_and_slug(
        self, organization_id: str, slug: str,
    ) -> OrganizationCapability | None:
        for oc in self._all():
            if oc.organization_id == organization_id and oc.capability_slug == slug:
                return oc
        return None

    async def list_by_organization(
        self, organization_id: str,
    ) -> list[OrganizationCapability]:
        return [oc for oc in self._all() if oc.organization_id == organization_id]

    async def list_enabled_by_organization(
        self, organization_id: str,
    ) -> list[OrganizationCapability]:
        return [
            oc for oc in self._all()
            if oc.organization_id == organization_id and oc.enabled
        ]


# ─── CapabilityUsageRepository ──────────────────────────────────────


class CapabilityUsageRepository(Repository[CapabilityUsage], ABC):

    @abstractmethod
    async def find_by_organization_and_slug(
        self, organization_id: str, slug: str,
    ) -> CapabilityUsage | None:
        ...

    @abstractmethod
    async def list_by_organization(
        self, organization_id: str,
    ) -> list[CapabilityUsage]:
        ...


class InMemoryCapabilityUsageRepository(
    InMemoryRepository[CapabilityUsage], CapabilityUsageRepository,
):

    async def find_by_organization_and_slug(
        self, organization_id: str, slug: str,
    ) -> CapabilityUsage | None:
        for u in self._all():
            if u.organization_id == organization_id and u.capability_slug == slug:
                return u
        return None

    async def list_by_organization(
        self, organization_id: str,
    ) -> list[CapabilityUsage]:
        return [u for u in self._all() if u.organization_id == organization_id]


# ─── CapabilityLimitsRepository ─────────────────────────────────────


class CapabilityLimitsRepository(Repository[CapabilityLimits], ABC):

    @abstractmethod
    async def find_by_organization_and_slug(
        self, organization_id: str, slug: str,
    ) -> CapabilityLimits | None:
        ...


class InMemoryCapabilityLimitsRepository(
    InMemoryRepository[CapabilityLimits], CapabilityLimitsRepository,
):

    async def find_by_organization_and_slug(
        self, organization_id: str, slug: str,
    ) -> CapabilityLimits | None:
        for l in self._all():
            if l.organization_id == organization_id and l.capability_slug == slug:
                return l
        return None
