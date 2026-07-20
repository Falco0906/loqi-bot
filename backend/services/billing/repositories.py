from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from services.billing.models import (
    CheckoutSession,
    Customer,
    Invoice,
    Plan,
    Subscription,
    SubscriptionStatus,
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


# ─── CustomerRepository ─────────────────────────────────────────────


class CustomerRepository(Repository[Customer], ABC):

    @abstractmethod
    async def find_by_organization_id(self, organization_id: str) -> Customer | None:
        ...

    @abstractmethod
    async def find_by_provider_customer_id(self, provider_customer_id: str) -> Customer | None:
        ...


class InMemoryCustomerRepository(InMemoryRepository[Customer], CustomerRepository):

    async def find_by_organization_id(self, organization_id: str) -> Customer | None:
        for c in self._all():
            if c.organization_id == organization_id:
                return c
        return None

    async def find_by_provider_customer_id(self, provider_customer_id: str) -> Customer | None:
        for c in self._all():
            if c.provider_customer_id == provider_customer_id:
                return c
        return None


# ─── PlanRepository ─────────────────────────────────────────────────


class PlanRepository(Repository[Plan], ABC):

    @abstractmethod
    async def find_by_code(self, code: str) -> Plan | None:
        ...

    @abstractmethod
    async def list_active(self) -> list[Plan]:
        ...


class InMemoryPlanRepository(InMemoryRepository[Plan], PlanRepository):

    async def find_by_code(self, code: str) -> Plan | None:
        for p in self._all():
            if p.code == code:
                return p
        return None

    async def list_active(self) -> list[Plan]:
        return self._all()


# ─── SubscriptionRepository ─────────────────────────────────────────


class SubscriptionRepository(Repository[Subscription], ABC):

    @abstractmethod
    async def find_by_organization_id(self, organization_id: str) -> list[Subscription]:
        ...

    @abstractmethod
    async def find_active_by_organization_id(self, organization_id: str) -> Subscription | None:
        ...

    @abstractmethod
    async def find_by_provider_subscription_id(
        self, provider_subscription_id: str,
    ) -> Subscription | None:
        ...


class InMemorySubscriptionRepository(InMemoryRepository[Subscription], SubscriptionRepository):

    async def find_by_organization_id(self, organization_id: str) -> list[Subscription]:
        return [s for s in self._all() if s.organization_id == organization_id]

    async def find_active_by_organization_id(self, organization_id: str) -> Subscription | None:
        for s in self._all():
            if s.organization_id == organization_id and s.is_active:
                return s
        return None

    async def find_by_provider_subscription_id(
        self, provider_subscription_id: str,
    ) -> Subscription | None:
        for s in self._all():
            if s.provider_subscription_id == provider_subscription_id:
                return s
        return None


# ─── CheckoutRepository ─────────────────────────────────────────────


class CheckoutRepository(Repository[CheckoutSession], ABC):

    @abstractmethod
    async def find_by_organization_id(self, organization_id: str) -> list[CheckoutSession]:
        ...

    @abstractmethod
    async def find_by_provider_checkout_id(
        self, provider_checkout_id: str,
    ) -> CheckoutSession | None:
        ...


class InMemoryCheckoutRepository(InMemoryRepository[CheckoutSession], CheckoutRepository):

    async def find_by_organization_id(self, organization_id: str) -> list[CheckoutSession]:
        return [c for c in self._all() if c.organization_id == organization_id]

    async def find_by_provider_checkout_id(
        self, provider_checkout_id: str,
    ) -> CheckoutSession | None:
        for c in self._all():
            if c.provider_checkout_id == provider_checkout_id:
                return c
        return None


# ─── InvoiceRepository ──────────────────────────────────────────────


class InvoiceRepository(Repository[Invoice], ABC):

    @abstractmethod
    async def find_by_organization_id(self, organization_id: str) -> list[Invoice]:
        ...

    @abstractmethod
    async def find_by_provider_invoice_id(
        self, provider_invoice_id: str,
    ) -> Invoice | None:
        ...


class InMemoryInvoiceRepository(InMemoryRepository[Invoice], InvoiceRepository):

    async def find_by_organization_id(self, organization_id: str) -> list[Invoice]:
        return [i for i in self._all() if i.organization_id == organization_id]

    async def find_by_provider_invoice_id(
        self, provider_invoice_id: str,
    ) -> Invoice | None:
        for i in self._all():
            if i.provider_invoice_id == provider_invoice_id:
                return i
        return None


# ─── BillingEventRepository (idempotency) ───────────────────────────


class BillingEventRepository(Repository["BillingEvent"], ABC):

    @abstractmethod
    async def find_by_provider_event_id(
        self, provider_event_id: str,
    ) -> "BillingEvent | None":
        ...

    @abstractmethod
    async def find_by_idempotency_key(self, key: str) -> "BillingEvent | None":
        ...


class InMemoryBillingEventRepository(
    InMemoryRepository["BillingEvent"], BillingEventRepository,
):

    async def find_by_provider_event_id(
        self, provider_event_id: str,
    ) -> "BillingEvent | None":
        from services.billing.models import BillingEvent
        for e in self._all():
            if e.provider_event_id == provider_event_id:
                return e
        return None

    async def find_by_idempotency_key(self, key: str) -> "BillingEvent | None":
        from services.billing.models import BillingEvent
        for e in self._all():
            if e.idempotency_key == key:
                return e
        return None
