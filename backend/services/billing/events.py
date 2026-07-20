from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class BillingEventType(str, Enum):
    CUSTOMER_CREATED = "billing.customer.created"
    CHECKOUT_STARTED = "billing.checkout.started"
    CHECKOUT_COMPLETED = "billing.checkout.completed"
    SUBSCRIPTION_CREATED = "billing.subscription.created"
    SUBSCRIPTION_UPDATED = "billing.subscription.updated"
    SUBSCRIPTION_CANCELLED = "billing.subscription.cancelled"
    SUBSCRIPTION_RENEWED = "billing.subscription.renewed"
    PAYMENT_SUCCEEDED = "billing.payment.succeeded"
    PAYMENT_FAILED = "billing.payment.failed"
    WEBHOOK_PROCESSED = "billing.webhook.processed"


@dataclass
class BillingDomainEvent:
    event_type: BillingEventType
    entity_id: str = ""
    organization_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def customer_created(
        cls, customer_id: str, organization_id: str, provider: str,
    ) -> BillingDomainEvent:
        return cls(
            event_type=BillingEventType.CUSTOMER_CREATED,
            entity_id=customer_id,
            organization_id=organization_id,
            data={"provider": provider},
        )

    @classmethod
    def checkout_started(
        cls, checkout_id: str, organization_id: str, plan_id: str,
    ) -> BillingDomainEvent:
        return cls(
            event_type=BillingEventType.CHECKOUT_STARTED,
            entity_id=checkout_id,
            organization_id=organization_id,
            data={"plan_id": plan_id},
        )

    @classmethod
    def checkout_completed(
        cls, checkout_id: str, organization_id: str, subscription_id: str,
    ) -> BillingDomainEvent:
        return cls(
            event_type=BillingEventType.CHECKOUT_COMPLETED,
            entity_id=checkout_id,
            organization_id=organization_id,
            data={"subscription_id": subscription_id},
        )

    @classmethod
    def subscription_created(
        cls, subscription_id: str, organization_id: str, plan_id: str,
    ) -> BillingDomainEvent:
        return cls(
            event_type=BillingEventType.SUBSCRIPTION_CREATED,
            entity_id=subscription_id,
            organization_id=organization_id,
            data={"plan_id": plan_id},
        )

    @classmethod
    def subscription_updated(
        cls, subscription_id: str, organization_id: str, status: str,
    ) -> BillingDomainEvent:
        return cls(
            event_type=BillingEventType.SUBSCRIPTION_UPDATED,
            entity_id=subscription_id,
            organization_id=organization_id,
            data={"status": status},
        )

    @classmethod
    def subscription_cancelled(
        cls, subscription_id: str, organization_id: str,
    ) -> BillingDomainEvent:
        return cls(
            event_type=BillingEventType.SUBSCRIPTION_CANCELLED,
            entity_id=subscription_id,
            organization_id=organization_id,
        )

    @classmethod
    def payment_succeeded(
        cls, invoice_id: str, organization_id: str, amount: int,
    ) -> BillingDomainEvent:
        return cls(
            event_type=BillingEventType.PAYMENT_SUCCEEDED,
            entity_id=invoice_id,
            organization_id=organization_id,
            data={"amount": amount},
        )

    @classmethod
    def payment_failed(
        cls, invoice_id: str, organization_id: str, amount: int,
    ) -> BillingDomainEvent:
        return cls(
            event_type=BillingEventType.PAYMENT_FAILED,
            entity_id=invoice_id,
            organization_id=organization_id,
            data={"amount": amount},
        )

    @classmethod
    def webhook_processed(
        cls, provider_event_id: str, event_type: str,
    ) -> BillingDomainEvent:
        return cls(
            event_type=BillingEventType.WEBHOOK_PROCESSED,
            entity_id=provider_event_id,
            data={"provider_event_type": event_type},
        )
