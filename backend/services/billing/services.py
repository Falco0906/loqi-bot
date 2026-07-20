from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from services.billing.config import BillingConfig
from services.billing.events import BillingDomainEvent, BillingEventType
from services.billing.exceptions import (
    CheckoutSessionNotFound,
    CustomerAlreadyExists,
    CustomerNotFound,
    DuplicateWebhookEvent,
    InvoiceNotFound,
    NoActiveSubscription,
    OrganizationNotConfigured,
    PlanNotFound,
    ProviderError,
    SubscriptionNotFound,
)
from services.billing.models import (
    BillingEvent,
    CheckoutSession,
    CheckoutStatus,
    Customer,
    Invoice,
    InvoiceStatus,
    Plan,
    Subscription,
    SubscriptionStatus,
)
from services.billing.provider import (
    BillingProvider,
    WebhookPayload,
)
from services.billing.repositories import (
    BillingEventRepository,
    CheckoutRepository,
    CustomerRepository,
    InvoiceRepository,
    PlanRepository,
    SubscriptionRepository,
)


class CustomerService:

    def __init__(
        self,
        customer_repo: CustomerRepository,
        provider: BillingProvider,
    ) -> None:
        self._customer_repo = customer_repo
        self._provider = provider
        self._events: list[BillingDomainEvent] = []

    @property
    def events(self) -> list[BillingDomainEvent]:
        return list(self._events)

    def clear_events(self) -> None:
        self._events.clear()

    async def get_or_create_customer(
        self,
        organization_id: str,
        email: str,
        provider_name: str = "stripe",
    ) -> Customer:
        existing = await self._customer_repo.find_by_organization_id(organization_id)
        if existing is not None:
            return existing

        provider_result = self._provider.create_customer(
            email=email,
            organization_id=organization_id,
        )

        customer = Customer(
            organization_id=organization_id,
            provider=provider_name,
            provider_customer_id=provider_result.provider_customer_id,
            email=email,
        )
        customer = await self._customer_repo.save(customer)

        self._events.append(
            BillingDomainEvent.customer_created(customer.id, organization_id, provider_name)
        )
        return customer

    async def get_customer_by_organization(self, organization_id: str) -> Customer:
        customer = await self._customer_repo.find_by_organization_id(organization_id)
        if customer is None:
            raise OrganizationNotConfigured(organization_id)
        return customer


class PlanService:

    def __init__(
        self,
        plan_repo: PlanRepository,
        config: BillingConfig | None = None,
    ) -> None:
        self._plan_repo = plan_repo
        self._config = config

    async def seed_plans(self) -> list[Plan]:
        plans = await self._plan_repo.list_active()
        if plans:
            return plans
        defaults = [
            Plan(code="starter_monthly", name="Starter", description="Starter plan", billing_interval="monthly", price=2900),
            Plan(code="starter_yearly", name="Starter", description="Starter plan yearly", billing_interval="yearly", price=29000),
            Plan(code="pro_monthly", name="Professional", description="Professional plan", billing_interval="monthly", price=7900),
            Plan(code="pro_yearly", name="Professional", description="Professional plan yearly", billing_interval="yearly", price=79000),
            Plan(code="enterprise_monthly", name="Enterprise", description="Enterprise plan", billing_interval="monthly", price=19900),
            Plan(code="enterprise_yearly", name="Enterprise", description="Enterprise plan yearly", billing_interval="yearly", price=199000),
        ]
        seeded: list[Plan] = []
        for p in defaults:
            seeded.append(await self._plan_repo.save(p))
        return seeded

    async def get_plan(self, plan_id: str) -> Plan:
        plan = await self._plan_repo.get(plan_id)
        if plan is None:
            raise PlanNotFound(plan_id)
        return plan

    async def get_plan_by_code(self, code: str) -> Plan:
        plan = await self._plan_repo.find_by_code(code)
        if plan is None:
            raise PlanNotFound(code)
        return plan

    async def list_plans(self) -> list[Plan]:
        plans = await self._plan_repo.list_active()
        if not plans:
            return await self.seed_plans()
        return plans


class CheckoutService:

    def __init__(
        self,
        checkout_repo: CheckoutRepository,
        plan_service: PlanService,
        customer_service: CustomerService,
        provider: BillingProvider,
        config: BillingConfig | None = None,
    ) -> None:
        self._checkout_repo = checkout_repo
        self._plan_service = plan_service
        self._customer_service = customer_service
        self._provider = provider
        self._config = config or BillingConfig()
        self._events: list[BillingDomainEvent] = []

    @property
    def events(self) -> list[BillingDomainEvent]:
        return list(self._events)

    def clear_events(self) -> None:
        self._events.clear()

    async def create_checkout(
        self,
        organization_id: str,
        plan_id: str,
        email: str,
        success_url: str | None = None,
        cancel_url: str | None = None,
        trial_days: int | None = None,
    ) -> CheckoutSession:
        plan = await self._plan_service.get_plan(plan_id)
        customer = await self._customer_service.get_or_create_customer(
            organization_id, email,
        )

        effective_trial = trial_days if trial_days is not None else self._config.trial_duration_days
        effective_success = success_url or self._config.checkout_success_url
        effective_cancel = cancel_url or self._config.checkout_cancel_url

        provider_result = self._provider.create_checkout_session(
            customer_id=customer.provider_customer_id,
            plan_id=plan_id,
            success_url=effective_success,
            cancel_url=effective_cancel,
            trial_days=effective_trial,
            metadata={
                "organization_id": organization_id,
                "plan_id": plan_id,
                "plan_code": plan.code,
            },
        )

        session = CheckoutSession(
            organization_id=organization_id,
            customer_id=customer.id,
            provider_checkout_id=provider_result.provider_checkout_id,
            plan_id=plan_id,
            url=provider_result.url,
            success_url=effective_success,
            cancel_url=effective_cancel,
            trial_days=effective_trial,
            metadata=provider_result.metadata,
        )
        session = await self._checkout_repo.save(session)

        self._events.append(
            BillingDomainEvent.checkout_started(session.id, organization_id, plan_id)
        )
        return session

    async def get_checkout(self, checkout_id: str) -> CheckoutSession:
        session = await self._checkout_repo.get(checkout_id)
        if session is None:
            raise CheckoutSessionNotFound()
        return session


class SubscriptionService:

    def __init__(
        self,
        sub_repo: SubscriptionRepository,
        invoice_repo: InvoiceRepository,
        provider: BillingProvider,
    ) -> None:
        self._sub_repo = sub_repo
        self._invoice_repo = invoice_repo
        self._provider = provider
        self._events: list[BillingDomainEvent] = []

    @property
    def events(self) -> list[BillingDomainEvent]:
        return list(self._events)

    def clear_events(self) -> None:
        self._events.clear()

    async def get_active_subscription(self, organization_id: str) -> Subscription:
        sub = await self._sub_repo.find_active_by_organization_id(organization_id)
        if sub is None:
            raise NoActiveSubscription(organization_id)
        return sub

    async def get_subscription(self, organization_id: str) -> Subscription | None:
        subs = await self._sub_repo.find_by_organization_id(organization_id)
        return subs[0] if subs else None

    async def cancel_subscription(
        self,
        organization_id: str,
        at_period_end: bool = True,
    ) -> Subscription:
        sub = await self.get_active_subscription(organization_id)
        provider_result = self._provider.cancel_subscription(
            sub.provider_subscription_id,
            at_period_end=at_period_end,
        )
        sub.status = SubscriptionStatus(provider_result.status)
        sub.cancel_at_period_end = provider_result.cancel_at_period_end
        if not at_period_end:
            sub.canceled_at = datetime.now(timezone.utc)
        sub.touch()
        sub = await self._sub_repo.save(sub)
        self._events.append(
            BillingDomainEvent.subscription_cancelled(sub.id, organization_id)
        )
        return sub

    async def resume_subscription(self, organization_id: str) -> Subscription:
        subs = await self._sub_repo.find_by_organization_id(organization_id)
        if not subs:
            raise SubscriptionNotFound()
        sub = subs[0]
        provider_result = self._provider.resume_subscription(
            sub.provider_subscription_id,
        )
        sub.status = SubscriptionStatus(provider_result.status)
        sub.cancel_at_period_end = False
        sub.touch()
        sub = await self._sub_repo.save(sub)
        return sub


class WebhookService:

    def __init__(
        self,
        customer_repo: CustomerRepository,
        sub_repo: SubscriptionRepository,
        checkout_repo: CheckoutRepository,
        invoice_repo: InvoiceRepository,
        event_repo: BillingEventRepository,
        provider: BillingProvider,
        config: BillingConfig | None = None,
    ) -> None:
        self._customer_repo = customer_repo
        self._sub_repo = sub_repo
        self._checkout_repo = checkout_repo
        self._invoice_repo = invoice_repo
        self._event_repo = event_repo
        self._provider = provider
        self._config = config or BillingConfig()
        self._events: list[BillingDomainEvent] = []

    @property
    def events(self) -> list[BillingDomainEvent]:
        return list(self._events)

    def clear_events(self) -> None:
        self._events.clear()

    async def process_webhook(
        self,
        raw_body: bytes,
        signature: str = "",
        provider_name: str = "stripe",
    ) -> list[dict[str, Any]]:
        payload = WebhookPayload(
            raw_body=raw_body,
            signature=signature,
            provider=provider_name,
        )

        raw_events = self._provider.handle_webhook(payload)

        results: list[dict[str, Any]] = []
        for raw_event in raw_events:
            result = await self._process_single_event(raw_event, provider_name)
            results.append(result)

        return results

    async def _process_single_event(
        self,
        raw_event: dict[str, Any],
        provider_name: str,
    ) -> dict[str, Any]:
        event_id = raw_event.get("event_id", "")
        event_type = raw_event.get("event_type", "")

        existing = await self._event_repo.find_by_provider_event_id(event_id)
        if existing is not None:
            raise DuplicateWebhookEvent(event_id)

        billing_event = BillingEvent(
            event_type=event_type,
            provider_event_id=event_id,
            provider=provider_name,
        )
        billing_event = await self._event_repo.save(billing_event)

        try:
            await self._route_event(event_type, raw_event)
            billing_event.mark_processed()
            await self._event_repo.save(billing_event)
        except Exception as exc:
            billing_event.data = {"error": str(exc)}
            await self._event_repo.save(billing_event)
            raise

        self._events.append(
            BillingDomainEvent.webhook_processed(event_id, event_type)
        )

        return {
            "event_id": event_id,
            "event_type": event_type,
            "processed": True,
        }

    async def _route_event(
        self,
        event_type: str,
        raw_event: dict[str, Any],
    ) -> None:
        if event_type == "checkout.session.completed":
            await self._handle_checkout_completed(raw_event)
        elif event_type == "customer.subscription.created":
            await self._handle_subscription_created(raw_event)
        elif event_type == "customer.subscription.updated":
            await self._handle_subscription_updated(raw_event)
        elif event_type == "customer.subscription.deleted":
            await self._handle_subscription_deleted(raw_event)
        elif event_type == "invoice.paid":
            await self._handle_invoice_paid(raw_event)
        elif event_type == "invoice.payment_failed":
            await self._handle_invoice_failed(raw_event)

    async def _handle_checkout_completed(self, raw_event: dict[str, Any]) -> None:
        event_data = raw_event.get("data", {})
        provider_checkout_id = event_data.get("id", raw_event.get("provider_event_id", ""))
        checkout = await self._checkout_repo.find_by_provider_checkout_id(
            provider_checkout_id,
        )
        if checkout is None:
            return

        checkout.complete()
        await self._checkout_repo.save(checkout)

    async def _handle_subscription_created(self, raw_event: dict[str, Any]) -> None:
        event_data = raw_event.get("data", {})
        provider_sub_id = event_data.get("id", raw_event.get("provider_event_id", ""))
        customer_provider_id = event_data.get("customer", "")
        customer = await self._customer_repo.find_by_provider_customer_id(
            customer_provider_id,
        )
        if customer is None:
            return

        status_str = event_data.get("status", "incomplete")
        now_ts = int(datetime.now(timezone.utc).timestamp())

        sub = Subscription(
            organization_id=customer.organization_id,
            customer_id=customer.id,
            provider_subscription_id=provider_sub_id,
            status=SubscriptionStatus(status_str),
        )
        sub = await self._sub_repo.save(sub)

        self._events.append(
            BillingDomainEvent.subscription_created(
                sub.id, customer.organization_id, sub.plan_id,
            )
        )

    async def _handle_subscription_updated(self, raw_event: dict[str, Any]) -> None:
        event_data = raw_event.get("data", {})
        provider_sub_id = event_data.get("id", raw_event.get("provider_event_id", ""))
        status_str = event_data.get("status", "")

        sub = await self._sub_repo.find_by_provider_subscription_id(provider_sub_id)
        if sub is None:
            return

        sub.status = SubscriptionStatus(status_str) if status_str else sub.status
        sub.touch()
        await self._sub_repo.save(sub)

        self._events.append(
            BillingDomainEvent.subscription_updated(
                sub.id, sub.organization_id, sub.status.value,
            )
        )

    async def _handle_subscription_deleted(self, raw_event: dict[str, Any]) -> None:
        event_data = raw_event.get("data", {})
        provider_sub_id = event_data.get("id", raw_event.get("provider_event_id", ""))

        sub = await self._sub_repo.find_by_provider_subscription_id(provider_sub_id)
        if sub is None:
            return

        sub.status = SubscriptionStatus.CANCELED
        sub.touch()
        await self._sub_repo.save(sub)

    async def _handle_invoice_paid(self, raw_event: dict[str, Any]) -> None:
        event_data = raw_event.get("data", {})
        provider_inv_id = event_data.get("id", "")
        provider_sub_id = event_data.get("subscription", "")
        amount = event_data.get("amount_paid", 0)

        sub = await self._sub_repo.find_by_provider_subscription_id(provider_sub_id)
        if sub is None:
            return

        invoice = Invoice(
            organization_id=sub.organization_id,
            customer_id=sub.customer_id,
            subscription_id=sub.id,
            provider_invoice_id=provider_inv_id,
            status=InvoiceStatus.PAID,
            amount_due=amount,
            amount_paid=amount,
        )
        invoice.mark_paid()
        await self._invoice_repo.save(invoice)

        self._events.append(
            BillingDomainEvent.payment_succeeded(
                invoice.id, sub.organization_id, amount,
            )
        )

    async def _handle_invoice_failed(self, raw_event: dict[str, Any]) -> None:
        event_data = raw_event.get("data", {})
        provider_inv_id = event_data.get("id", "")
        provider_sub_id = event_data.get("subscription", "")
        amount = event_data.get("amount_due", 0)

        sub = await self._sub_repo.find_by_provider_subscription_id(provider_sub_id)
        if sub is None:
            return

        invoice = Invoice(
            organization_id=sub.organization_id,
            customer_id=sub.customer_id,
            subscription_id=sub.id,
            provider_invoice_id=provider_inv_id,
            status=InvoiceStatus.OPEN,
            amount_due=amount,
        )
        await self._invoice_repo.save(invoice)

        self._events.append(
            BillingDomainEvent.payment_failed(
                invoice.id, sub.organization_id, amount,
            )
        )
