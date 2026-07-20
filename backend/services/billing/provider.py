from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CheckoutResult:
    url: str
    provider_checkout_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PortalResult:
    url: str


@dataclass
class ProviderCustomerResult:
    provider_customer_id: str


@dataclass
class ProviderSubscriptionResult:
    provider_subscription_id: str
    status: str
    current_period_start: int | None = None
    current_period_end: int | None = None
    cancel_at_period_end: bool = False
    trial_end: int | None = None


@dataclass
class WebhookPayload:
    raw_body: bytes = b""
    signature: str = ""
    provider: str = "stripe"


class BillingProvider(ABC):

    @abstractmethod
    def create_customer(
        self,
        email: str,
        organization_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> ProviderCustomerResult:
        ...

    @abstractmethod
    def create_checkout_session(
        self,
        customer_id: str,
        plan_id: str,
        success_url: str,
        cancel_url: str,
        trial_days: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> CheckoutResult:
        ...

    @abstractmethod
    def create_customer_portal(
        self,
        customer_id: str,
        return_url: str,
    ) -> PortalResult:
        ...

    @abstractmethod
    def get_subscription(self, subscription_id: str) -> ProviderSubscriptionResult:
        ...

    @abstractmethod
    def cancel_subscription(
        self,
        subscription_id: str,
        at_period_end: bool = True,
    ) -> ProviderSubscriptionResult:
        ...

    @abstractmethod
    def resume_subscription(self, subscription_id: str) -> ProviderSubscriptionResult:
        ...

    @abstractmethod
    def handle_webhook(self, payload: WebhookPayload) -> list[dict[str, Any]]:
        ...
