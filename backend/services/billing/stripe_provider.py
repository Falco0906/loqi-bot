from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from uuid import uuid4

from services.billing.config import BillingConfig
from services.billing.exceptions import ProviderError, WebhookSignatureInvalid
from services.billing.provider import (
    BillingProvider,
    CheckoutResult,
    PortalResult,
    ProviderCustomerResult,
    ProviderSubscriptionResult,
    WebhookPayload,
)


class MockStripeBillingProvider(BillingProvider):

    WEBHOOK_EVENTS: set[str] = {
        "checkout.session.completed",
        "customer.created",
        "customer.updated",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.paid",
        "invoice.payment_failed",
    }

    def __init__(self, config: BillingConfig | None = None) -> None:
        self._config = config or BillingConfig()
        self._customers: dict[str, dict[str, Any]] = {}
        self._checkout_sessions: dict[str, dict[str, Any]] = {}
        self._subscriptions: dict[str, dict[str, Any]] = {}
        self._next_number: int = 1

    def create_customer(
        self,
        email: str,
        organization_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> ProviderCustomerResult:
        cust_id = f"cus_mock_{uuid4().hex[:12]}"
        self._customers[cust_id] = {
            "id": cust_id,
            "email": email,
            "organization_id": organization_id,
            "metadata": metadata or {},
            "created": int(time.time()),
        }
        return ProviderCustomerResult(provider_customer_id=cust_id)

    def create_checkout_session(
        self,
        customer_id: str,
        plan_id: str,
        success_url: str,
        cancel_url: str,
        trial_days: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> CheckoutResult:
        if customer_id not in self._customers:
            raise ProviderError(f"Customer not found: {customer_id}")

        checkout_id = f"cs_mock_{uuid4().hex[:12]}"
        self._checkout_sessions[checkout_id] = {
            "id": checkout_id,
            "customer": customer_id,
            "plan_id": plan_id,
            "mode": "subscription",
            "status": "open",
            "url": f"https://checkout.stripe.com/mock/{checkout_id}",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "trial_days": trial_days,
            "metadata": metadata or {},
            "created": int(time.time()),
        }
        return CheckoutResult(
            url=self._checkout_sessions[checkout_id]["url"],
            provider_checkout_id=checkout_id,
            metadata=self._checkout_sessions[checkout_id]["metadata"],
        )

    def create_customer_portal(
        self,
        customer_id: str,
        return_url: str,
    ) -> PortalResult:
        if customer_id not in self._customers:
            raise ProviderError(f"Customer not found: {customer_id}")
        return PortalResult(
            url=f"https://billing.stripe.com/mock/session/{customer_id[:8]}",
        )

    def get_subscription(self, subscription_id: str) -> ProviderSubscriptionResult:
        sub = self._subscriptions.get(subscription_id)
        if sub is None:
            raise ProviderError(f"Subscription not found: {subscription_id}")
        return ProviderSubscriptionResult(
            provider_subscription_id=sub["id"],
            status=sub["status"],
            current_period_start=sub.get("current_period_start"),
            current_period_end=sub.get("current_period_end"),
            cancel_at_period_end=sub.get("cancel_at_period_end", False),
            trial_end=sub.get("trial_end"),
        )

    def cancel_subscription(
        self,
        subscription_id: str,
        at_period_end: bool = True,
    ) -> ProviderSubscriptionResult:
        sub = self._subscriptions.get(subscription_id)
        if sub is None:
            raise ProviderError(f"Subscription not found: {subscription_id}")
        sub["cancel_at_period_end"] = at_period_end
        if not at_period_end:
            sub["status"] = "canceled"
        return ProviderSubscriptionResult(
            provider_subscription_id=sub["id"],
            status=sub["status"],
            current_period_start=sub.get("current_period_start"),
            current_period_end=sub.get("current_period_end"),
            cancel_at_period_end=sub.get("cancel_at_period_end", False),
        )

    def resume_subscription(self, subscription_id: str) -> ProviderSubscriptionResult:
        sub = self._subscriptions.get(subscription_id)
        if sub is None:
            raise ProviderError(f"Subscription not found: {subscription_id}")
        sub["cancel_at_period_end"] = False
        if sub["status"] not in ("active", "trialing", "past_due"):
            sub["status"] = "active"
        return ProviderSubscriptionResult(
            provider_subscription_id=sub["id"],
            status=sub["status"],
            current_period_start=sub.get("current_period_start"),
            current_period_end=sub.get("current_period_end"),
            cancel_at_period_end=sub.get("cancel_at_period_end", False),
        )

    def handle_webhook(self, payload: WebhookPayload) -> list[dict[str, Any]]:
        if payload.signature:
            self._verify_signature(payload.raw_body, payload.signature)

        try:
            event = json.loads(payload.raw_body)
        except json.JSONDecodeError as exc:
            raise ProviderError("Invalid webhook payload") from exc

        event_type = event.get("type", "")
        if event_type not in self.WEBHOOK_EVENTS:
            return []

        events: list[dict[str, Any]] = [event]
        return self._process_webhook_events(events)

    def _verify_signature(self, payload: bytes, signature: str) -> None:
        secret = self._config.stripe_webhook_secret
        if not secret:
            return
        expected = hmac.new(
            secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise WebhookSignatureInvalid()

    def _process_webhook_events(
        self, events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for event in events:
            event_type = event.get("type", "")
            event_id = event.get("id", str(uuid4()))
            data = event.get("data", {}).get("object", {})

            if event_type == "customer.created":
                self._handle_customer_created(data)
            elif event_type == "customer.updated":
                self._handle_customer_updated(data)
            elif event_type == "checkout.session.completed":
                self._handle_checkout_completed(data)
            elif event_type in (
                "customer.subscription.created",
                "customer.subscription.updated",
            ):
                self._handle_subscription_updated(data)
            elif event_type == "customer.subscription.deleted":
                self._handle_subscription_deleted(data)
            elif event_type == "invoice.paid":
                self._handle_invoice_paid(data)
            elif event_type == "invoice.payment_failed":
                self._handle_invoice_failed(data)

            results.append({
                "event_id": event_id,
                "event_type": event_type,
                "provider_event_id": event_id,
                "data": data,
                "processed": True,
            })

        return results

    def _handle_customer_created(self, data: dict[str, Any]) -> None:
        cust_id = data.get("id", "")
        if cust_id:
            self._customers.setdefault(cust_id, {"id": cust_id})
            self._customers[cust_id].update({
                "email": data.get("email", ""),
                "metadata": data.get("metadata", {}),
            })

    def _handle_customer_updated(self, data: dict[str, Any]) -> None:
        cust_id = data.get("id", "")
        if cust_id and cust_id in self._customers:
            self._customers[cust_id].update({
                "email": data.get("email", self._customers[cust_id].get("email", "")),
                "metadata": data.get("metadata", self._customers[cust_id].get("metadata", {})),
            })

    def _handle_checkout_completed(self, data: dict[str, Any]) -> None:
        checkout_id = data.get("id", "")
        if checkout_id and checkout_id in self._checkout_sessions:
            self._checkout_sessions[checkout_id]["status"] = "complete"

    def _handle_subscription_updated(self, data: dict[str, Any]) -> None:
        sub_id = data.get("id", "")
        if not sub_id:
            return
        status = data.get("status", "incomplete")
        self._subscriptions.setdefault(sub_id, {"id": sub_id})
        self._subscriptions[sub_id].update({
            "status": status,
            "current_period_start": data.get("current_period_start"),
            "current_period_end": data.get("current_period_end"),
            "cancel_at_period_end": data.get("cancel_at_period_end", False),
            "trial_end": data.get("trial_end"),
            "plan_id": (
                data.get("plan", {}).get("id", "") if isinstance(data.get("plan"), dict) else ""
            ),
            "customer": data.get("customer", ""),
        })

    def _handle_subscription_deleted(self, data: dict[str, Any]) -> None:
        sub_id = data.get("id", "")
        if sub_id and sub_id in self._subscriptions:
            self._subscriptions[sub_id]["status"] = "canceled"

    def _handle_invoice_paid(self, data: dict[str, Any]) -> None:
        pass

    def _handle_invoice_failed(self, data: dict[str, Any]) -> None:
        pass

    def _add_subscription(self, sub_data: dict[str, Any]) -> None:
        sub_id = sub_data.get("id", f"sub_mock_{uuid4().hex[:12]}")
        self._subscriptions[sub_id] = {"id": sub_id, **sub_data}

    def _add_checkout_session(self, cs_data: dict[str, Any]) -> None:
        cs_id = cs_data.get("id", f"cs_mock_{uuid4().hex[:12]}")
        self._checkout_sessions[cs_id] = {"id": cs_id, **cs_data}


class StripeBillingProvider(BillingProvider):

    WEBHOOK_EVENTS: set[str] = {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.paid",
        "invoice.payment_failed",
    }

    def __init__(self, config: BillingConfig | None = None) -> None:
        self._config = config or BillingConfig()
        self._stripe = self._get_stripe_module()

    def _get_stripe_module(self):
        try:
            import stripe
            stripe.api_key = self._config.stripe_secret_key
            return stripe
        except ImportError as exc:
            raise ProviderError(
                "Stripe SDK not installed. Add 'stripe' to requirements.txt"
            ) from exc

    def _map_stripe_error(self, exc: Exception) -> ProviderError:
        return ProviderError(f"Stripe API error: {exc}")

    def create_customer(
        self,
        email: str,
        organization_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> ProviderCustomerResult:
        try:
            stripe_customer = self._stripe.Customer.create(
                email=email,
                metadata={
                    "organization_id": organization_id,
                    **(metadata or {}),
                },
            )
            return ProviderCustomerResult(
                provider_customer_id=stripe_customer.id,
            )
        except Exception as exc:
            raise self._map_stripe_error(exc) from exc

    def create_checkout_session(
        self,
        customer_id: str,
        plan_id: str,
        success_url: str,
        cancel_url: str,
        trial_days: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> CheckoutResult:
        try:
            session_data: dict[str, Any] = {
                "customer": customer_id,
                "mode": "subscription",
                "line_items": [{"price": plan_id, "quantity": 1}],
                "success_url": success_url,
                "cancel_url": cancel_url,
                "metadata": metadata or {},
            }
            if trial_days > 0:
                session_data["subscription_data"] = {
                    "trial_period_days": trial_days,
                }

            session = self._stripe.checkout.Session.create(**session_data)
            return CheckoutResult(
                url=session.url or "",
                provider_checkout_id=session.id,
                metadata=dict(session.metadata or {}),
            )
        except Exception as exc:
            raise self._map_stripe_error(exc) from exc

    def create_customer_portal(
        self,
        customer_id: str,
        return_url: str,
    ) -> PortalResult:
        try:
            portal = self._stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
            )
            return PortalResult(url=portal.url)
        except Exception as exc:
            raise self._map_stripe_error(exc) from exc

    def get_subscription(self, subscription_id: str) -> ProviderSubscriptionResult:
        try:
            sub = self._stripe.Subscription.retrieve(subscription_id)
            return ProviderSubscriptionResult(
                provider_subscription_id=sub.id,
                status=sub.status,
                current_period_start=sub.current_period_start,
                current_period_end=sub.current_period_end,
                cancel_at_period_end=sub.cancel_at_period_end,
                trial_end=sub.trial_end,
            )
        except Exception as exc:
            raise self._map_stripe_error(exc) from exc

    def cancel_subscription(
        self,
        subscription_id: str,
        at_period_end: bool = True,
    ) -> ProviderSubscriptionResult:
        try:
            if at_period_end:
                sub = self._stripe.Subscription.modify(
                    subscription_id,
                    cancel_at_period_end=True,
                )
            else:
                sub = self._stripe.Subscription.delete(subscription_id)
            return ProviderSubscriptionResult(
                provider_subscription_id=sub.id,
                status=sub.status,
                current_period_start=getattr(sub, "current_period_start", None),
                current_period_end=getattr(sub, "current_period_end", None),
                cancel_at_period_end=getattr(sub, "cancel_at_period_end", False),
            )
        except Exception as exc:
            raise self._map_stripe_error(exc) from exc

    def resume_subscription(self, subscription_id: str) -> ProviderSubscriptionResult:
        try:
            sub = self._stripe.Subscription.modify(
                subscription_id,
                cancel_at_period_end=False,
            )
            return ProviderSubscriptionResult(
                provider_subscription_id=sub.id,
                status=sub.status,
                current_period_start=sub.current_period_start,
                current_period_end=sub.current_period_end,
                cancel_at_period_end=sub.cancel_at_period_end,
            )
        except Exception as exc:
            raise self._map_stripe_error(exc) from exc

    def handle_webhook(self, payload: WebhookPayload) -> list[dict[str, Any]]:
        try:
            event = self._stripe.Webhook.construct_event(
                payload=payload.raw_body,
                sig_header=payload.signature,
                secret=self._config.stripe_webhook_secret,
            )
        except ValueError as exc:
            raise ProviderError(f"Invalid webhook payload: {exc}") from exc
        except self._stripe.error.SignatureVerificationError as exc:
            raise WebhookSignatureInvalid() from exc
        except Exception as exc:
            raise self._map_stripe_error(exc) from exc

        event_type = event.type
        if event_type not in self.WEBHOOK_EVENTS:
            return []

        data = event.data.object if hasattr(event, "data") else {}
        data_dict = json.loads(json.dumps(data, default=str))

        return [{
            "event_id": event.id,
            "event_type": event_type,
            "provider_event_id": event.id,
            "data": data_dict,
            "processed": True,
        }]
