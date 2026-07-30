from __future__ import annotations

import asyncio
import json
from typing import Any

from services.billing.models import (
    BillingEvent,
    CheckoutSession,
    Customer,
    Invoice,
    Plan,
    Subscription,
)
from services.billing.repositories import (
    BillingEventRepository,
    CheckoutRepository,
    CustomerRepository,
    InvoiceRepository,
    PlanRepository,
    SubscriptionRepository,
)
from services.persistence.base_repository import SupabaseRepository, _deserialize, _serialize


class SupabasePlanRepository(SupabaseRepository[Plan], PlanRepository):

    @property
    def _table_name(self) -> str:
        return "billing_plans"

    @classmethod
    def _entity_type(cls) -> type[Plan]:
        return Plan

    def _to_row(self, entity: Plan) -> dict[str, Any]:
        row = _serialize(entity)
        if entity.metadata:
            row["metadata"] = json.dumps(entity.metadata)
        return row

    def _from_row(self, row: dict[str, Any]) -> Plan:
        metadata_raw = row.pop("metadata", None)
        plan = _deserialize(Plan, row)
        if metadata_raw and isinstance(metadata_raw, str):
            plan.metadata = json.loads(metadata_raw)
        return plan

    async def find_by_code(self, code: str) -> Plan | None:
        client = self._client()
        if client is None:
            return None
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("code", code)
            .limit(1)
            .execute()
        )
        row = self._first(result)
        if row is None:
            return None
        return self._from_row(row)

    async def list_active(self) -> list[Plan]:
        client = self._client()
        if client is None:
            return []
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .execute()
        )
        return [self._from_row(r) for r in (getattr(result, "data", None) or [])]


class SupabaseCustomerRepository(SupabaseRepository[Customer], CustomerRepository):

    @property
    def _table_name(self) -> str:
        return "billing_customers"

    @classmethod
    def _entity_type(cls) -> type[Customer]:
        return Customer

    def _to_row(self, entity: Customer) -> dict[str, Any]:
        row = _serialize(entity)
        if entity.metadata:
            row["metadata"] = json.dumps(entity.metadata)
        return row

    def _from_row(self, row: dict[str, Any]) -> Customer:
        metadata_raw = row.pop("metadata", None)
        customer = _deserialize(Customer, row)
        if metadata_raw and isinstance(metadata_raw, str):
            customer.metadata = json.loads(metadata_raw)
        return customer

    async def find_by_organization_id(self, organization_id: str) -> Customer | None:
        client = self._client()
        if client is None:
            return None
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("organization_id", organization_id)
            .limit(1)
            .execute()
        )
        row = self._first(result)
        if row is None:
            return None
        return self._from_row(row)

    async def find_by_provider_customer_id(self, provider_customer_id: str) -> Customer | None:
        client = self._client()
        if client is None:
            return None
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("provider_customer_id", provider_customer_id)
            .limit(1)
            .execute()
        )
        row = self._first(result)
        if row is None:
            return None
        return self._from_row(row)


class SupabaseSubscriptionRepository(SupabaseRepository[Subscription], SubscriptionRepository):

    @property
    def _table_name(self) -> str:
        return "billing_subscriptions"

    @classmethod
    def _entity_type(cls) -> type[Subscription]:
        return Subscription

    async def find_by_organization_id(self, organization_id: str) -> list[Subscription]:
        client = self._client()
        if client is None:
            return []
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("organization_id", organization_id)
            .order("created_at", desc=True)
            .execute()
        )
        return [self._from_row(r) for r in (getattr(result, "data", None) or [])]

    async def find_active_by_organization_id(self, organization_id: str) -> Subscription | None:
        client = self._client()
        if client is None:
            return None
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("organization_id", organization_id)
            .in_("status", ("active", "trialing"))
            .limit(1)
            .execute()
        )
        row = self._first(result)
        if row is None:
            return None
        return self._from_row(row)

    async def find_by_provider_subscription_id(
        self, provider_subscription_id: str,
    ) -> Subscription | None:
        client = self._client()
        if client is None:
            return None
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("provider_subscription_id", provider_subscription_id)
            .limit(1)
            .execute()
        )
        row = self._first(result)
        if row is None:
            return None
        return self._from_row(row)


class SupabaseCheckoutRepository(SupabaseRepository[CheckoutSession], CheckoutRepository):

    @property
    def _table_name(self) -> str:
        return "billing_checkout_sessions"

    @classmethod
    def _entity_type(cls) -> type[CheckoutSession]:
        return CheckoutSession

    def _to_row(self, entity: CheckoutSession) -> dict[str, Any]:
        row = _serialize(entity)
        if entity.metadata:
            row["metadata"] = json.dumps(entity.metadata)
        return row

    def _from_row(self, row: dict[str, Any]) -> CheckoutSession:
        metadata_raw = row.pop("metadata", None)
        session = _deserialize(CheckoutSession, row)
        if metadata_raw and isinstance(metadata_raw, str):
            session.metadata = json.loads(metadata_raw)
        return session

    async def find_by_organization_id(self, organization_id: str) -> list[CheckoutSession]:
        client = self._client()
        if client is None:
            return []
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("organization_id", organization_id)
            .order("created_at", desc=True)
            .execute()
        )
        return [self._from_row(r) for r in (getattr(result, "data", None) or [])]

    async def find_by_provider_checkout_id(
        self, provider_checkout_id: str,
    ) -> CheckoutSession | None:
        client = self._client()
        if client is None:
            return None
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("provider_checkout_id", provider_checkout_id)
            .limit(1)
            .execute()
        )
        row = self._first(result)
        if row is None:
            return None
        return self._from_row(row)


class SupabaseInvoiceRepository(SupabaseRepository[Invoice], InvoiceRepository):

    @property
    def _table_name(self) -> str:
        return "billing_invoices"

    @classmethod
    def _entity_type(cls) -> type[Invoice]:
        return Invoice

    def _to_row(self, entity: Invoice) -> dict[str, Any]:
        row = _serialize(entity)
        if entity.metadata:
            row["metadata"] = json.dumps(entity.metadata)
        return row

    def _from_row(self, row: dict[str, Any]) -> Invoice:
        metadata_raw = row.pop("metadata", None)
        invoice = _deserialize(Invoice, row)
        if metadata_raw and isinstance(metadata_raw, str):
            invoice.metadata = json.loads(metadata_raw)
        return invoice

    async def find_by_organization_id(self, organization_id: str) -> list[Invoice]:
        client = self._client()
        if client is None:
            return []
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("organization_id", organization_id)
            .order("created_at", desc=True)
            .execute()
        )
        return [self._from_row(r) for r in (getattr(result, "data", None) or [])]

    async def find_by_provider_invoice_id(
        self, provider_invoice_id: str,
    ) -> Invoice | None:
        client = self._client()
        if client is None:
            return None
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("provider_invoice_id", provider_invoice_id)
            .limit(1)
            .execute()
        )
        row = self._first(result)
        if row is None:
            return None
        return self._from_row(row)


class SupabaseBillingEventRepository(SupabaseRepository[BillingEvent], BillingEventRepository):

    @property
    def _table_name(self) -> str:
        return "billing_events"

    @classmethod
    def _entity_type(cls) -> type[BillingEvent]:
        return BillingEvent

    def _to_row(self, entity: BillingEvent) -> dict[str, Any]:
        row = _serialize(entity)
        if entity.data:
            row["data"] = json.dumps(entity.data)
        return row

    def _from_row(self, row: dict[str, Any]) -> BillingEvent:
        data_raw = row.pop("data", None)
        event = _deserialize(BillingEvent, row)
        if data_raw and isinstance(data_raw, str):
            event.data = json.loads(data_raw)
        return event

    async def find_by_provider_event_id(self, provider_event_id: str) -> BillingEvent | None:
        client = self._client()
        if client is None:
            return None
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("provider_event_id", provider_event_id)
            .limit(1)
            .execute()
        )
        row = self._first(result)
        if row is None:
            return None
        return self._from_row(row)

    async def find_by_idempotency_key(self, key: str) -> BillingEvent | None:
        client = self._client()
        if client is None:
            return None
        result = await asyncio.to_thread(
            lambda: client.table(self._table_name)
            .select("*")
            .eq("idempotency_key", key)
            .limit(1)
            .execute()
        )
        row = self._first(result)
        if row is None:
            return None
        return self._from_row(row)
