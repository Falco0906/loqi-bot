from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class SubscriptionStatus(str, Enum):
    INCOMPLETE = "incomplete"
    INCOMPLETE_EXPIRED = "incomplete_expired"
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    UNPAID = "unpaid"
    PAUSED = "paused"


class BillingInterval(str, Enum):
    MONTHLY = "monthly"
    YEARLY = "yearly"


class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    OPEN = "open"
    PAID = "paid"
    UNCOLLECTIBLE = "uncollectible"
    VOID = "void"


class CheckoutStatus(str, Enum):
    OPEN = "open"
    COMPLETE = "complete"
    EXPIRED = "expired"


@dataclass
class Plan:
    id: str = field(default_factory=lambda: str(uuid4()))
    code: str = ""
    name: str = ""
    description: str = ""
    billing_interval: BillingInterval = BillingInterval.MONTHLY
    currency: str = "usd"
    price: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def display_price(self) -> str:
        return f"{self.price / 100:.2f}"


@dataclass
class Customer:
    id: str = field(default_factory=lambda: str(uuid4()))
    organization_id: str = ""
    provider: str = ""
    provider_customer_id: str = ""
    email: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Subscription:
    id: str = field(default_factory=lambda: str(uuid4()))
    organization_id: str = ""
    customer_id: str = ""
    provider_subscription_id: str = ""
    status: SubscriptionStatus = SubscriptionStatus.INCOMPLETE
    plan_id: str = ""
    trial_ends_at: datetime | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    canceled_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_active(self) -> bool:
        return self.status in (
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.TRIALING,
        )

    @property
    def is_canceled(self) -> bool:
        return self.status == SubscriptionStatus.CANCELED

    @property
    def is_trialing(self) -> bool:
        return self.status == SubscriptionStatus.TRIALING

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)


@dataclass
class CheckoutSession:
    id: str = field(default_factory=lambda: str(uuid4()))
    organization_id: str = ""
    customer_id: str = ""
    provider_checkout_id: str = ""
    plan_id: str = ""
    status: CheckoutStatus = CheckoutStatus.OPEN
    url: str = ""
    mode: str = "subscription"
    success_url: str = ""
    cancel_url: str = ""
    trial_days: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None

    @property
    def is_complete(self) -> bool:
        return self.status == CheckoutStatus.COMPLETE

    def complete(self) -> None:
        self.status = CheckoutStatus.COMPLETE
        self.completed_at = datetime.now(timezone.utc)

    def mark_expired(self) -> None:
        self.status = CheckoutStatus.EXPIRED


@dataclass
class Invoice:
    id: str = field(default_factory=lambda: str(uuid4()))
    organization_id: str = ""
    customer_id: str = ""
    subscription_id: str = ""
    provider_invoice_id: str = ""
    status: InvoiceStatus = InvoiceStatus.DRAFT
    amount_due: int = 0
    amount_paid: int = 0
    currency: str = "usd"
    period_start: datetime | None = None
    period_end: datetime | None = None
    paid_at: datetime | None = None
    hosted_url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_paid(self) -> bool:
        return self.status == InvoiceStatus.PAID

    def mark_paid(self) -> None:
        self.status = InvoiceStatus.PAID
        self.paid_at = datetime.now(timezone.utc)


@dataclass
class BillingEvent:
    id: str = field(default_factory=lambda: str(uuid4()))
    event_type: str = ""
    provider_event_id: str = ""
    provider: str = ""
    organization_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    processed: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    processed_at: datetime | None = None

    def mark_processed(self) -> None:
        self.processed = True
        self.processed_at = datetime.now(timezone.utc)
