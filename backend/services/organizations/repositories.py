from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from services.organizations.models import Invitation, InvitationStatus, Membership, MembershipRole, MembershipStatus, Organization

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


# ─── OrganizationRepository ─────────────────────────────────────────


class OrganizationRepository(Repository[Organization], ABC):

    @abstractmethod
    async def find_by_slug(self, slug: str) -> Organization | None:
        ...

    @abstractmethod
    async def find_by_name(self, name: str) -> Organization | None:
        ...

    @abstractmethod
    async def find_owned_by(self, user_id: str) -> list[Organization]:
        ...


class InMemoryOrganizationRepository(InMemoryRepository[Organization], OrganizationRepository):

    async def find_by_slug(self, slug: str) -> Organization | None:
        for org in self._all():
            if org.slug == slug and not org.is_deleted:
                return org
        return None

    async def find_by_name(self, name: str) -> Organization | None:
        for org in self._all():
            if org.name == name and not org.is_deleted:
                return org
        return None

    async def find_owned_by(self, user_id: str) -> list[Organization]:
        return [org for org in self._all() if org.created_by == user_id and not org.is_deleted]


# ─── MembershipRepository ───────────────────────────────────────────


class MembershipRepository(Repository[Membership], ABC):

    @abstractmethod
    async def find_by_user_and_org(self, user_id: str, organization_id: str) -> Membership | None:
        ...

    @abstractmethod
    async def find_by_org_id(self, organization_id: str) -> list[Membership]:
        ...

    @abstractmethod
    async def find_by_user_id(self, user_id: str) -> list[Membership]:
        ...

    @abstractmethod
    async def count_owners(self, organization_id: str) -> int:
        ...

    @abstractmethod
    async def find_active_by_user_id(self, user_id: str) -> list[Membership]:
        ...


class InMemoryMembershipRepository(InMemoryRepository[Membership], MembershipRepository):

    async def find_by_user_and_org(self, user_id: str, organization_id: str) -> Membership | None:
        for m in self._all():
            if m.user_id == user_id and m.organization_id == organization_id:
                return m
        return None

    async def find_by_org_id(self, organization_id: str) -> list[Membership]:
        return [m for m in self._all() if m.organization_id == organization_id]

    async def find_by_user_id(self, user_id: str) -> list[Membership]:
        return [m for m in self._all() if m.user_id == user_id]

    async def count_owners(self, organization_id: str) -> int:
        return sum(
            1 for m in self._all()
            if m.organization_id == organization_id and m.role == MembershipRole.OWNER and m.is_active
        )

    async def find_active_by_user_id(self, user_id: str) -> list[Membership]:
        return [m for m in self._all() if m.user_id == user_id and m.is_active]


# ─── InvitationRepository ───────────────────────────────────────────


class InvitationRepository(Repository[Invitation], ABC):

    @abstractmethod
    async def find_by_org_id(self, organization_id: str) -> list[Invitation]:
        ...

    @abstractmethod
    async def find_pending_by_email(self, email: str) -> list[Invitation]:
        ...

    @abstractmethod
    async def find_by_token(self, token: str) -> Invitation | None:
        ...


class InMemoryInvitationRepository(InMemoryRepository[Invitation], InvitationRepository):

    async def find_by_org_id(self, organization_id: str) -> list[Invitation]:
        return [i for i in self._all() if i.organization_id == organization_id]

    async def find_pending_by_email(self, email: str) -> list[Invitation]:
        return [i for i in self._all() if i.email == email and i.status == InvitationStatus.PENDING]

    async def find_by_token(self, token: str) -> Invitation | None:
        for i in self._all():
            if i.token == token:
                return i
        return None
