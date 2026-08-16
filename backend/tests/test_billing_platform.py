from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from services.billing.api import (
    BillingDeps,
    register_deps as _register_billing_deps,
    register_provider_and_config as _register_billing_provider_config,
    _get_current_user,
)
from services.billing.config import BillingConfig
from services.billing.events import BillingDomainEvent, BillingEventType
from services.billing.exceptions import (
    CheckoutSessionNotFound,
    CustomerAlreadyExists,
    CustomerNotFound,
    DuplicateWebhookEvent,
    NoActiveSubscription,
    OrganizationNotConfigured,
    PlanNotFound,
    ProviderError,
    SubscriptionNotFound,
    WebhookSignatureInvalid,
)
from services.billing.models import (
    BillingEvent,
    BillingInterval,
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
    CheckoutResult,
    PortalResult,
    ProviderCustomerResult,
    ProviderSubscriptionResult,
    WebhookPayload,
)
from services.billing.repositories import (
    InMemoryBillingEventRepository,
    InMemoryCheckoutRepository,
    InMemoryCustomerRepository,
    InMemoryInvoiceRepository,
    InMemoryPlanRepository,
    InMemorySubscriptionRepository,
)
from services.billing.services import (
    CheckoutService,
    CustomerService,
    PlanService,
    SubscriptionService,
    WebhookService,
)
from services.billing.stripe_provider import MockStripeBillingProvider, StripeBillingProvider


# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def billing_config() -> BillingConfig:
    return BillingConfig(
        stripe_secret_key="sk_test_mock",
        stripe_webhook_secret="whsec_mock",
        trial_duration_days=14,
    )


@pytest.fixture
def provider(billing_config) -> MockStripeBillingProvider:
    return MockStripeBillingProvider(billing_config)


@pytest.fixture
def customer_repo() -> InMemoryCustomerRepository:
    return InMemoryCustomerRepository()


@pytest.fixture
def plan_repo() -> InMemoryPlanRepository:
    return InMemoryPlanRepository()


@pytest.fixture
def sub_repo() -> InMemorySubscriptionRepository:
    return InMemorySubscriptionRepository()


@pytest.fixture
def checkout_repo() -> InMemoryCheckoutRepository:
    return InMemoryCheckoutRepository()


@pytest.fixture
def invoice_repo() -> InMemoryInvoiceRepository:
    return InMemoryInvoiceRepository()


@pytest.fixture
def event_repo() -> InMemoryBillingEventRepository:
    return InMemoryBillingEventRepository()


@pytest.fixture
def plan_service(plan_repo, billing_config) -> PlanService:
    return PlanService(plan_repo, billing_config)


@pytest.fixture
def customer_service(customer_repo, provider) -> CustomerService:
    return CustomerService(customer_repo, provider)


@pytest.fixture
def checkout_service(checkout_repo, plan_service, customer_service, provider, billing_config) -> CheckoutService:
    return CheckoutService(checkout_repo, plan_service, customer_service, provider, billing_config)


@pytest.fixture
def sub_service(sub_repo, invoice_repo, provider) -> SubscriptionService:
    return SubscriptionService(sub_repo, invoice_repo, provider)


@pytest.fixture
def webhook_service(customer_repo, sub_repo, checkout_repo, invoice_repo, event_repo, provider, billing_config) -> WebhookService:
    return WebhookService(
        customer_repo, sub_repo, checkout_repo, invoice_repo,
        event_repo, provider, billing_config,
    )


@pytest.fixture
async def seeded_plan(plan_service) -> Plan:
    plans = await plan_service.seed_plans()
    return plans[0]


@pytest.fixture
async def created_customer(customer_service) -> Customer:
    return await customer_service.get_or_create_customer(
        organization_id="org-1", email="test@example.com",
    )


# ─── Model Tests ────────────────────────────────────────────────────


class TestModels:

    def test_plan_display_price(self):
        p = Plan(price=2999)
        assert p.display_price == "29.99"

    def test_subscription_is_active(self):
        assert Subscription(status=SubscriptionStatus.ACTIVE).is_active
        assert Subscription(status=SubscriptionStatus.TRIALING).is_active
        assert not Subscription(status=SubscriptionStatus.CANCELED).is_active
        assert not Subscription(status=SubscriptionStatus.INCOMPLETE).is_active

    def test_subscription_is_canceled(self):
        assert Subscription(status=SubscriptionStatus.CANCELED).is_canceled
        assert not Subscription(status=SubscriptionStatus.ACTIVE).is_canceled

    def test_checkout_complete(self):
        cs = CheckoutSession()
        assert not cs.is_complete
        cs.complete()
        assert cs.is_complete
        assert cs.status == CheckoutStatus.COMPLETE
        assert cs.completed_at is not None

    def test_invoice_mark_paid(self):
        inv = Invoice()
        assert not inv.is_paid
        inv.mark_paid()
        assert inv.is_paid
        assert inv.status == InvoiceStatus.PAID
        assert inv.paid_at is not None

    def test_billing_event_mark_processed(self):
        ev = BillingEvent()
        assert not ev.processed
        ev.mark_processed()
        assert ev.processed
        assert ev.processed_at is not None


# ─── Provider Tests ─────────────────────────────────────────────────


class TestMockStripeBillingProvider:

    def test_create_customer(self, provider):
        result = provider.create_customer(
            email="test@example.com",
            organization_id="org-1",
        )
        assert result.provider_customer_id.startswith("cus_mock_")

    def test_create_checkout_session(self, provider):
        provider.create_customer(email="test@example.com", organization_id="org-1")
        customer_id = list(provider._customers.keys())[0]
        result = provider.create_checkout_session(
            customer_id=customer_id,
            plan_id="plan-1",
            success_url="http://example.com/success",
            cancel_url="http://example.com/cancel",
        )
        assert result.url.startswith("https://checkout.stripe.com/mock/")
        assert result.provider_checkout_id.startswith("cs_mock_")

    def test_create_checkout_session_no_customer(self, provider):
        with pytest.raises(Exception, match="Customer not found"):
            provider.create_checkout_session(
                customer_id="cus_nonexistent",
                plan_id="plan-1",
                success_url="http://example.com/success",
                cancel_url="http://example.com/cancel",
            )

    def test_customer_portal(self, provider):
        provider.create_customer(email="test@example.com", organization_id="org-1")
        customer_id = list(provider._customers.keys())[0]
        result = provider.create_customer_portal(
            customer_id=customer_id,
            return_url="http://example.com/return",
        )
        assert result.url.startswith("https://billing.stripe.com/mock/")

    def test_subscription_lifecycle(self, provider):
        provider._add_subscription({
            "id": "sub_mock_123",
            "status": "active",
            "current_period_start": 1000,
            "current_period_end": 2000,
        })
        result = provider.get_subscription("sub_mock_123")
        assert result.status == "active"

        result = provider.cancel_subscription("sub_mock_123", at_period_end=True)
        assert result.cancel_at_period_end

        result = provider.resume_subscription("sub_mock_123")
        assert not result.cancel_at_period_end

    def test_webhook_supported_events(self, provider):
        assert "checkout.session.completed" in provider.WEBHOOK_EVENTS
        assert "invoice.paid" in provider.WEBHOOK_EVENTS

    def test_webhook_unknown_event_ignored(self, provider):
        payload = json.dumps({"type": "unknown.event", "id": "evt_1"}).encode()
        wp = WebhookPayload(raw_body=payload)
        results = provider.handle_webhook(wp)
        assert len(results) == 0

    def test_webhook_checkout_completed(self, provider):
        provider.create_customer(email="test@example.com", organization_id="org-1")
        customer_id = list(provider._customers.keys())[0]
        provider.create_checkout_session(
            customer_id=customer_id, plan_id="plan-1",
            success_url="http://example.com/success",
            cancel_url="http://example.com/cancel",
        )
        checkout_id = list(provider._checkout_sessions.keys())[0]
        payload = json.dumps({
            "type": "checkout.session.completed",
            "id": "evt_1",
            "data": {"object": {"id": checkout_id}},
        }).encode()
        wp = WebhookPayload(raw_body=payload)
        results = provider.handle_webhook(wp)
        assert len(results) == 1
        assert provider._checkout_sessions[checkout_id]["status"] == "complete"

    def test_verify_signature_valid(self, provider):
        payload = b'{"test": "data"}'
        import hmac, hashlib
        sig = hmac.new(b"whsec_mock", payload, hashlib.sha256).hexdigest()
        provider._verify_signature(payload, sig)

    def test_verify_signature_invalid(self, provider):
        payload = b'{"test": "data"}'
        with pytest.raises(WebhookSignatureInvalid):
            provider._verify_signature(payload, "invalid_signature")


# ─── Live Stripe Provider Tests (mocked SDK) ──────────────────────────


class MockStripeResource:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def _make_mock_stripe():
    import types
    mock = types.ModuleType("stripe")
    mock.api_key = ""

    class StripeError(Exception):
        def __init__(self, message, http_body=None):
            super().__init__(message)
            self.http_body = http_body

    class SignatureVerificationError(StripeError):
        pass

    mock.error = types.ModuleType("stripe.error")
    mock.error.StripeError = StripeError
    mock.error.SignatureVerificationError = SignatureVerificationError

    mock.Customer = types.ModuleType("stripe.Customer")
    mock.Customer.create = MagicMock()

    mock.checkout = types.ModuleType("stripe.checkout")
    mock.checkout.Session = types.ModuleType("stripe.checkout.Session")
    mock.checkout.Session.create = MagicMock()

    mock.billing_portal = types.ModuleType("stripe.billing_portal")
    mock.billing_portal.Session = types.ModuleType("stripe.billing_portal.Session")
    mock.billing_portal.Session.create = MagicMock()

    mock.Subscription = types.ModuleType("stripe.Subscription")
    mock.Subscription.retrieve = MagicMock()
    mock.Subscription.modify = MagicMock()
    mock.Subscription.delete = MagicMock()

    mock.Webhook = types.ModuleType("stripe.Webhook")
    mock.Webhook.construct_event = MagicMock()

    return mock


class TestStripeBillingProvider:

    @pytest.fixture
    def live_config(self) -> BillingConfig:
        return BillingConfig(
            provider_mode="live",
            stripe_secret_key="sk_test_live",
            stripe_webhook_secret="whsec_live",
            stripe_publishable_key="pk_test_live",
            trial_duration_days=14,
        )

    @pytest.fixture
    def patch_stripe(self):
        mock_stripe = _make_mock_stripe()
        with patch.dict("sys.modules", {"stripe": mock_stripe}):
            from services.billing.stripe_provider import StripeBillingProvider as SBP
            yield SBP, mock_stripe

    def test_create_customer(self, live_config, patch_stripe):
        SBP, mock_stripe = patch_stripe
        mock_stripe.Customer.create.return_value = MockStripeResource(id="cus_live_123")
        provider = SBP(live_config)
        result = provider.create_customer(
            email="live@example.com",
            organization_id="org-live-1",
        )
        assert result.provider_customer_id == "cus_live_123"

    def test_create_customer_error(self, live_config, patch_stripe):
        SBP, mock_stripe = patch_stripe
        mock_stripe.Customer.create.side_effect = Exception("API error")
        provider = SBP(live_config)
        with pytest.raises(ProviderError, match="Stripe API error"):
            provider.create_customer(email="fail@example.com", organization_id="org-1")

    def test_create_checkout_session(self, live_config, patch_stripe):
        SBP, mock_stripe = patch_stripe
        mock_stripe.checkout.Session.create.return_value = MockStripeResource(
            id="cs_live_123", url="https://checkout.stripe.com/c/live_123", metadata={},
        )
        provider = SBP(live_config)
        result = provider.create_checkout_session(
            customer_id="cus_live_123",
            plan_id="price_live_123",
            success_url="http://example.com/success",
            cancel_url="http://example.com/cancel",
            trial_days=14,
        )
        assert result.url == "https://checkout.stripe.com/c/live_123"
        assert result.provider_checkout_id == "cs_live_123"

    def test_create_checkout_session_no_trial(self, live_config, patch_stripe):
        SBP, mock_stripe = patch_stripe
        mock_stripe.checkout.Session.create.return_value = MockStripeResource(
            id="cs_live_124", url="https://checkout.stripe.com/c/live_124", metadata={},
        )
        provider = SBP(live_config)
        result = provider.create_checkout_session(
            customer_id="cus_live_123",
            plan_id="price_live_123",
            success_url="http://example.com/success",
            cancel_url="http://example.com/cancel",
            trial_days=0,
        )
        assert result.provider_checkout_id == "cs_live_124"

    def test_create_customer_portal(self, live_config, patch_stripe):
        SBP, mock_stripe = patch_stripe
        mock_stripe.billing_portal.Session.create.return_value = MockStripeResource(
            url="https://billing.stripe.com/session/live_123",
        )
        provider = SBP(live_config)
        result = provider.create_customer_portal(
            customer_id="cus_live_123",
            return_url="http://example.com/return",
        )
        assert result.url == "https://billing.stripe.com/session/live_123"

    def test_get_subscription(self, live_config, patch_stripe):
        SBP, mock_stripe = patch_stripe
        mock_stripe.Subscription.retrieve.return_value = MockStripeResource(
            id="sub_live_123", status="active",
            current_period_start=1000, current_period_end=2000,
            cancel_at_period_end=False, trial_end=None,
        )
        provider = SBP(live_config)
        result = provider.get_subscription("sub_live_123")
        assert result.provider_subscription_id == "sub_live_123"
        assert result.status == "active"
        assert result.current_period_start == 1000

    def test_cancel_subscription_at_period_end(self, live_config, patch_stripe):
        SBP, mock_stripe = patch_stripe
        mock_stripe.Subscription.modify.return_value = MockStripeResource(
            id="sub_live_123", status="active",
            current_period_start=1000, current_period_end=2000,
            cancel_at_period_end=True,
        )
        provider = SBP(live_config)
        result = provider.cancel_subscription("sub_live_123", at_period_end=True)
        assert result.cancel_at_period_end

    def test_cancel_subscription_immediate(self, live_config, patch_stripe):
        SBP, mock_stripe = patch_stripe
        mock_stripe.Subscription.delete.return_value = MockStripeResource(
            id="sub_live_123", status="canceled",
            current_period_start=1000, current_period_end=2000,
            cancel_at_period_end=False,
        )
        provider = SBP(live_config)
        result = provider.cancel_subscription("sub_live_123", at_period_end=False)
        assert result.status == "canceled"

    def test_resume_subscription(self, live_config, patch_stripe):
        SBP, mock_stripe = patch_stripe
        mock_stripe.Subscription.modify.return_value = MockStripeResource(
            id="sub_live_123", status="active",
            current_period_start=1000, current_period_end=2000,
            cancel_at_period_end=False,
        )
        provider = SBP(live_config)
        result = provider.resume_subscription("sub_live_123")
        assert not result.cancel_at_period_end

    def test_webhook_known_event(self, live_config, patch_stripe):
        SBP, mock_stripe = patch_stripe
        mock_stripe.Webhook.construct_event.return_value = MockStripeResource(
            id="evt_live_123",
            type="checkout.session.completed",
            data=MockStripeResource(object={"id": "cs_live_123", "status": "complete"}),
        )
        provider = SBP(live_config)
        results = provider.handle_webhook(WebhookPayload(
            raw_body=b'{"type":"checkout.session.completed"}',
            signature="test_sig",
        ))
        assert len(results) == 1
        assert results[0]["event_id"] == "evt_live_123"
        assert results[0]["event_type"] == "checkout.session.completed"

    def test_webhook_unknown_event_ignored(self, live_config, patch_stripe):
        SBP, mock_stripe = patch_stripe
        mock_stripe.Webhook.construct_event.return_value = MockStripeResource(
            id="evt_unknown", type="unknown.event",
            data=MockStripeResource(object={}),
        )
        provider = SBP(live_config)
        results = provider.handle_webhook(WebhookPayload(
            raw_body=b'{"type":"unknown.event"}',
            signature="test_sig",
        ))
        assert len(results) == 0

    def test_webhook_invalid_signature(self, live_config, patch_stripe):
        SBP, mock_stripe = patch_stripe
        mock_stripe.Webhook.construct_event.side_effect = (
            mock_stripe.error.SignatureVerificationError("Invalid signature", None)
        )
        provider = SBP(live_config)
        with pytest.raises(WebhookSignatureInvalid):
            provider.handle_webhook(WebhookPayload(
                raw_body=b'{"type":"checkout.session.completed"}',
                signature="bad_sig",
            ))

    def test_webhook_invalid_payload(self, live_config, patch_stripe):
        SBP, mock_stripe = patch_stripe
        mock_stripe.Webhook.construct_event.side_effect = ValueError("Invalid payload")
        provider = SBP(live_config)
        with pytest.raises(ProviderError, match="Invalid webhook payload"):
            provider.handle_webhook(WebhookPayload(
                raw_body=b"not-json",
                signature="test",
            ))

    def test_provider_error_on_stripe_unavailable(self, live_config, patch_stripe):
        SBP, mock_stripe = patch_stripe
        mock_stripe.Customer.create.side_effect = Exception("Connection refused")
        provider = SBP(live_config)
        with pytest.raises(ProviderError, match="Stripe API error"):
            provider.create_customer(email="test@example.com", organization_id="org-1")

    def test_create_billing_provider_mock(self):
        from services.billing.api import create_billing_provider
        config = BillingConfig(provider_mode="mock", stripe_secret_key="")
        p = create_billing_provider(config)
        from services.billing.stripe_provider import MockStripeBillingProvider
        assert isinstance(p, MockStripeBillingProvider)

    def test_create_billing_provider_live(self):
        mock_stripe = _make_mock_stripe()
        with patch.dict("sys.modules", {"stripe": mock_stripe, "stripe.error": mock_stripe.error}):
            from services.billing.api import create_billing_provider
            config = BillingConfig(provider_mode="live", stripe_secret_key="sk_test_abc")
            p = create_billing_provider(config)
            from services.billing.stripe_provider import StripeBillingProvider
            assert isinstance(p, StripeBillingProvider)


# ─── Repository Tests ───────────────────────────────────────────────


@pytest.mark.asyncio
class TestRepositories:

    async def test_customer_repo_find_by_org(self, customer_repo):
        c = Customer(organization_id="org-1")
        await customer_repo.save(c)
        found = await customer_repo.find_by_organization_id("org-1")
        assert found is not None
        assert found.id == c.id

    async def test_customer_repo_find_by_provider_id(self, customer_repo):
        c = Customer(provider_customer_id="cus_123")
        await customer_repo.save(c)
        found = await customer_repo.find_by_provider_customer_id("cus_123")
        assert found is not None

    async def test_plan_repo_find_by_code(self, plan_repo):
        p = Plan(code="pro_monthly")
        await plan_repo.save(p)
        found = await plan_repo.find_by_code("pro_monthly")
        assert found is not None

    async def test_sub_repo_find_by_org(self, sub_repo):
        s1 = Subscription(organization_id="org-1", status=SubscriptionStatus.ACTIVE)
        s2 = Subscription(organization_id="org-1", status=SubscriptionStatus.CANCELED)
        await sub_repo.save(s1)
        await sub_repo.save(s2)
        found = await sub_repo.find_by_organization_id("org-1")
        assert len(found) == 2
        active = await sub_repo.find_active_by_organization_id("org-1")
        assert active is not None
        assert active.id == s1.id

    async def test_checkout_repo_find_by_provider_id(self, checkout_repo):
        cs = CheckoutSession(provider_checkout_id="cs_123")
        await checkout_repo.save(cs)
        found = await checkout_repo.find_by_provider_checkout_id("cs_123")
        assert found is not None

    async def test_event_repo_find_by_provider_event_id(self, event_repo):
        ev = BillingEvent(provider_event_id="evt_1")
        await event_repo.save(ev)
        found = await event_repo.find_by_provider_event_id("evt_1")
        assert found is not None

    async def test_event_repo_find_by_idempotency_key(self, event_repo):
        ev = BillingEvent(idempotency_key="idem-1")
        await event_repo.save(ev)
        found = await event_repo.find_by_idempotency_key("idem-1")
        assert found is not None


# ─── PlanService Tests ──────────────────────────────────────────────


@pytest.mark.asyncio
class TestPlanService:

    async def test_seed_plans(self, plan_service):
        plans = await plan_service.seed_plans()
        assert len(plans) == 6
        codes = [p.code for p in plans]
        assert "starter_monthly" in codes
        assert "pro_yearly" in codes

    async def test_seed_is_idempotent(self, plan_service):
        await plan_service.seed_plans()
        plans2 = await plan_service.seed_plans()
        assert len(plans2) == 6

    async def test_list_plans(self, plan_service):
        plans = await plan_service.list_plans()
        assert len(plans) == 6

    async def test_get_plan(self, plan_service):
        plans = await plan_service.seed_plans()
        plan = await plan_service.get_plan(plans[0].id)
        assert plan.id == plans[0].id

    async def test_get_plan_not_found(self, plan_service):
        with pytest.raises(PlanNotFound):
            await plan_service.get_plan("nonexistent")

    async def test_get_plan_by_code(self, plan_service):
        await plan_service.seed_plans()
        plan = await plan_service.get_plan_by_code("pro_monthly")
        assert plan.code == "pro_monthly"
        assert plan.price == 7900


# ─── CustomerService Tests ──────────────────────────────────────────


@pytest.mark.asyncio
class TestCustomerService:

    async def test_get_or_create_customer(self, customer_service):
        customer = await customer_service.get_or_create_customer(
            organization_id="org-1", email="test@example.com",
        )
        assert customer.organization_id == "org-1"
        assert customer.email == "test@example.com"
        assert customer.provider == "stripe"
        assert customer.provider_customer_id.startswith("cus_mock_")

    async def test_get_or_create_customer_idempotent(self, customer_service):
        c1 = await customer_service.get_or_create_customer(
            organization_id="org-dup", email="test@example.com",
        )
        c2 = await customer_service.get_or_create_customer(
            organization_id="org-dup", email="test@example.com",
        )
        assert c1.id == c2.id

    async def test_get_customer_by_organization(self, customer_service):
        await customer_service.get_or_create_customer(
            organization_id="org-find", email="find@example.com",
        )
        customer = await customer_service.get_customer_by_organization("org-find")
        assert customer.email == "find@example.com"

    async def test_get_customer_not_found(self, customer_service):
        with pytest.raises(OrganizationNotConfigured):
            await customer_service.get_customer_by_organization("nonexistent")

    async def test_events_emitted(self, customer_service):
        await customer_service.get_or_create_customer(
            organization_id="org-events", email="events@example.com",
        )
        assert len(customer_service.events) == 1
        assert customer_service.events[0].event_type == BillingEventType.CUSTOMER_CREATED


# ─── CheckoutService Tests ──────────────────────────────────────────


@pytest.mark.asyncio
class TestCheckoutService:

    async def test_create_checkout(self, checkout_service, plan_service):
        await plan_service.seed_plans()
        plan = await plan_service.get_plan_by_code("pro_monthly")
        session = await checkout_service.create_checkout(
            organization_id="org-checkout",
            plan_id=plan.id,
            email="checkout@example.com",
        )
        assert session.organization_id == "org-checkout"
        assert session.plan_id == plan.id
        assert session.url.startswith("https://checkout.stripe.com/mock/")
        assert session.status == CheckoutStatus.OPEN

    async def test_create_checkout_emits_event(self, checkout_service, plan_service):
        await plan_service.seed_plans()
        plan = await plan_service.get_plan_by_code("starter_monthly")
        await checkout_service.create_checkout(
            organization_id="org-event",
            plan_id=plan.id,
            email="event@example.com",
        )
        assert len(checkout_service.events) == 1
        assert checkout_service.events[0].event_type == BillingEventType.CHECKOUT_STARTED

    async def test_create_checkout_creates_customer(self, checkout_service, plan_service, customer_repo):
        await plan_service.seed_plans()
        plan = await plan_service.get_plan_by_code("starter_monthly")
        await checkout_service.create_checkout(
            organization_id="org-auto-cust",
            plan_id=plan.id,
            email="auto@example.com",
        )
        customer = await customer_repo.find_by_organization_id("org-auto-cust")
        assert customer is not None
        assert customer.email == "auto@example.com"

    async def test_create_checkout_plan_not_found(self, checkout_service):
        with pytest.raises(PlanNotFound):
            await checkout_service.create_checkout(
                organization_id="org-1",
                plan_id="nonexistent",
                email="test@example.com",
            )

    async def test_get_checkout(self, checkout_service, plan_service):
        await plan_service.seed_plans()
        plan = await plan_service.get_plan_by_code("starter_monthly")
        session = await checkout_service.create_checkout(
            organization_id="org-get",
            plan_id=plan.id,
            email="get@example.com",
        )
        found = await checkout_service.get_checkout(session.id)
        assert found.id == session.id

    async def test_get_checkout_not_found(self, checkout_service):
        with pytest.raises(CheckoutSessionNotFound):
            await checkout_service.get_checkout("nonexistent")


# ─── SubscriptionService Tests ──────────────────────────────────────


@pytest.mark.asyncio
class TestSubscriptionService:

    async def test_get_active_subscription_not_found(self, sub_service):
        with pytest.raises(NoActiveSubscription):
            await sub_service.get_active_subscription("org-no-sub")

    async def test_cancel_subscription(self, sub_service, sub_repo, provider):
        sub = Subscription(
            organization_id="org-cancel",
            provider_subscription_id="sub_mock_cancel",
            status=SubscriptionStatus.ACTIVE,
        )
        await sub_repo.save(sub)
        provider._add_subscription({"id": "sub_mock_cancel", "status": "active"})
        result = await sub_service.cancel_subscription("org-cancel", at_period_end=True)
        assert result.cancel_at_period_end
        assert result.is_active

    async def test_cancel_subscription_immediate(self, sub_service, sub_repo, provider):
        sub = Subscription(
            organization_id="org-immediate",
            provider_subscription_id="sub_mock_imm",
            status=SubscriptionStatus.ACTIVE,
        )
        await sub_repo.save(sub)
        provider._add_subscription({"id": "sub_mock_imm", "status": "active"})
        result = await sub_service.cancel_subscription("org-immediate", at_period_end=False)
        assert result.is_canceled
        assert result.status == SubscriptionStatus.CANCELED

    async def test_cancel_subscription_no_active(self, sub_service):
        with pytest.raises(NoActiveSubscription):
            await sub_service.cancel_subscription("org-no-active")

    async def test_resume_subscription(self, sub_service, sub_repo, provider):
        sub = Subscription(
            organization_id="org-resume",
            provider_subscription_id="sub_mock_resume",
            status=SubscriptionStatus.ACTIVE,
            cancel_at_period_end=True,
        )
        await sub_repo.save(sub)
        provider._add_subscription({"id": "sub_mock_resume", "status": "active"})
        result = await sub_service.resume_subscription("org-resume")
        assert not result.cancel_at_period_end

    async def test_get_subscription(self, sub_service, sub_repo):
        sub = Subscription(
            organization_id="org-get-sub",
            provider_subscription_id="sub_mock_get",
            status=SubscriptionStatus.ACTIVE,
        )
        await sub_repo.save(sub)
        result = await sub_service.get_subscription("org-get-sub")
        assert result is not None
        assert result.id == sub.id

    async def test_cancel_emits_event(self, sub_service, sub_repo, provider):
        sub = Subscription(
            organization_id="org-event-cancel",
            provider_subscription_id="sub_mock_evt",
            status=SubscriptionStatus.ACTIVE,
        )
        await sub_repo.save(sub)
        provider._add_subscription({"id": "sub_mock_evt", "status": "active"})
        await sub_service.cancel_subscription("org-event-cancel")
        assert len(sub_service.events) == 1
        assert sub_service.events[0].event_type == BillingEventType.SUBSCRIPTION_CANCELLED


# ─── WebhookService Tests ───────────────────────────────────────────


@pytest.mark.asyncio
class TestWebhookService:

    async def test_process_checkout_completed(
        self, webhook_service, customer_service, checkout_service, plan_service,
    ):
        await plan_service.seed_plans()
        plan = await plan_service.get_plan_by_code("starter_monthly")
        session = await checkout_service.create_checkout(
            organization_id="org-webhook",
            plan_id=plan.id,
            email="webhook@example.com",
        )
        payload = json.dumps({
            "type": "checkout.session.completed",
            "id": "evt_checkout_1",
            "data": {"object": {"id": session.provider_checkout_id}},
        }).encode()
        results = await webhook_service.process_webhook(payload)
        assert len(results) == 1
        assert results[0]["processed"]

        updated = await checkout_service.get_checkout(session.id)
        assert updated.is_complete

    async def test_process_subscription_created(
        self, webhook_service, customer_service,
    ):
        await customer_service.get_or_create_customer(
            organization_id="org-sub-create",
            email="subcreate@example.com",
        )
        customer = await customer_service.get_customer_by_organization("org-sub-create")
        payload = json.dumps({
            "type": "customer.subscription.created",
            "id": "evt_sub_create_1",
            "data": {
                "object": {
                    "id": "sub_mock_webhook_1",
                    "customer": customer.provider_customer_id,
                    "status": "active",
                },
            },
        }).encode()
        results = await webhook_service.process_webhook(payload)
        assert len(results) == 1

    async def test_process_invoice_paid(
        self, webhook_service, customer_service, sub_repo,
    ):
        c = await customer_service.get_or_create_customer(
            organization_id="org-invoice",
            email="invoice@example.com",
        )
        sub = Subscription(
            organization_id="org-invoice",
            customer_id=c.id,
            provider_subscription_id="sub_mock_inv",
            status=SubscriptionStatus.ACTIVE,
        )
        await sub_repo.save(sub)
        payload = json.dumps({
            "type": "invoice.paid",
            "id": "evt_inv_1",
            "data": {
                "object": {
                    "id": "in_mock_1",
                    "subscription": "sub_mock_inv",
                    "amount_paid": 2900,
                },
            },
        }).encode()
        results = await webhook_service.process_webhook(payload)
        assert len(results) == 1

    async def test_duplicate_webhook_rejected(self, webhook_service):
        payload = json.dumps({
            "type": "customer.created",
            "id": "evt_dup_1",
            "data": {"object": {"id": "cus_mock_dup", "email": "dup@example.com"}},
        }).encode()
        await webhook_service.process_webhook(payload)
        with pytest.raises(DuplicateWebhookEvent):
            await webhook_service.process_webhook(payload)

    async def test_webhook_unknown_event_ignored(self, webhook_service):
        payload = json.dumps({
            "type": "unknown.event",
            "id": "evt_unknown",
            "data": {"object": {}},
        }).encode()
        results = await webhook_service.process_webhook(payload)
        assert len(results) == 0

    async def test_subscription_updated_webhook(
        self, webhook_service, customer_service, sub_repo,
    ):
        c = await customer_service.get_or_create_customer(
            organization_id="org-sub-upd",
            email="subupd@example.com",
        )
        sub = Subscription(
            organization_id="org-sub-upd",
            customer_id=c.id,
            provider_subscription_id="sub_mock_upd",
            status=SubscriptionStatus.ACTIVE,
        )
        await sub_repo.save(sub)
        payload = json.dumps({
            "type": "customer.subscription.updated",
            "id": "evt_sub_upd_1",
            "data": {
                "object": {
                    "id": "sub_mock_upd",
                    "status": "past_due",
                },
            },
        }).encode()
        await webhook_service.process_webhook(payload)
        updated = await sub_repo.find_by_provider_subscription_id("sub_mock_upd")
        assert updated is not None
        assert updated.status == SubscriptionStatus.PAST_DUE

    async def test_subscription_deleted_webhook(
        self, webhook_service, customer_service, sub_repo,
    ):
        c = await customer_service.get_or_create_customer(
            organization_id="org-sub-del",
            email="subdel@example.com",
        )
        sub = Subscription(
            organization_id="org-sub-del",
            customer_id=c.id,
            provider_subscription_id="sub_mock_del",
            status=SubscriptionStatus.ACTIVE,
        )
        await sub_repo.save(sub)
        payload = json.dumps({
            "type": "customer.subscription.deleted",
            "id": "evt_sub_del_1",
            "data": {
                "object": {
                    "id": "sub_mock_del",
                },
            },
        }).encode()
        await webhook_service.process_webhook(payload)
        updated = await sub_repo.find_by_provider_subscription_id("sub_mock_del")
        assert updated is not None
        assert updated.status == SubscriptionStatus.CANCELED

    async def test_invoice_failed_webhook(
        self, webhook_service, customer_service, sub_repo, invoice_repo,
    ):
        c = await customer_service.get_or_create_customer(
            organization_id="org-inv-fail",
            email="invfail@example.com",
        )
        sub = Subscription(
            organization_id="org-inv-fail",
            customer_id=c.id,
            provider_subscription_id="sub_mock_inv_fail",
            status=SubscriptionStatus.ACTIVE,
        )
        await sub_repo.save(sub)
        payload = json.dumps({
            "type": "invoice.payment_failed",
            "id": "evt_inv_fail_1",
            "data": {
                "object": {
                    "id": "in_mock_fail",
                    "subscription": "sub_mock_inv_fail",
                    "amount_due": 2900,
                },
            },
        }).encode()
        await webhook_service.process_webhook(payload)
        invoices = await invoice_repo.find_by_organization_id("org-inv-fail")
        assert len(invoices) == 1

    async def test_events_emitted_on_webhook(self, webhook_service):
        payload = json.dumps({
            "type": "customer.created",
            "id": "evt_events_1",
            "data": {"object": {"id": "cus_mock_events", "email": "evt@example.com"}},
        }).encode()
        await webhook_service.process_webhook(payload)
        assert len(webhook_service.events) >= 1


# ─── Idempotency Tests ──────────────────────────────────────────────


@pytest.mark.asyncio
class TestIdempotency:

    async def test_idempotency_key_stored(self, event_repo):
        ev = BillingEvent(idempotency_key="unique-key-1")
        await event_repo.save(ev)
        found = await event_repo.find_by_idempotency_key("unique-key-1")
        assert found is not None

    async def test_duplicate_provider_event_rejected(self, webhook_service):
        payload = json.dumps({
            "type": "customer.created",
            "id": "evt_idem_dup",
            "data": {"object": {"id": "cus_idem", "email": "idem@example.com"}},
        }).encode()
        await webhook_service.process_webhook(payload)
        with pytest.raises(DuplicateWebhookEvent):
            await webhook_service.process_webhook(payload)


# ─── Full Flow Integration Tests ────────────────────────────────────


@pytest.mark.asyncio
class TestFullFlow:

    async def test_organization_to_active_subscription(
        self, plan_service, customer_service, checkout_service,
        webhook_service, sub_repo,
    ):
        await plan_service.seed_plans()
        plan = await plan_service.get_plan_by_code("pro_monthly")

        session = await checkout_service.create_checkout(
            organization_id="org-full-flow",
            plan_id=plan.id,
            email="fullflow@example.com",
        )
        assert session is not None
        assert session.url is not None

        checkout_payload = json.dumps({
            "type": "checkout.session.completed",
            "id": "evt_full_checkout",
            "data": {"object": {"id": session.provider_checkout_id}},
        }).encode()
        await webhook_service.process_webhook(checkout_payload)

        customer = await customer_service.get_customer_by_organization("org-full-flow")
        sub_payload = json.dumps({
            "type": "customer.subscription.created",
            "id": "evt_full_sub",
            "data": {
                "object": {
                    "id": "sub_mock_full",
                    "customer": customer.provider_customer_id,
                    "status": "active",
                },
            },
        }).encode()
        await webhook_service.process_webhook(sub_payload)

        active = await sub_repo.find_active_by_organization_id("org-full-flow")
        assert active is not None
        assert active.status == SubscriptionStatus.ACTIVE


# ─── API Integration Tests ──────────────────────────────────────────


@pytest.fixture(scope="module")
def billing_api_client() -> TestClient:
    from main import app
    _config = BillingConfig(
        stripe_secret_key="sk_test_mock",
        stripe_webhook_secret="whsec_mock",
    )
    _provider = MockStripeBillingProvider(_config)
    _cust_repo = InMemoryCustomerRepository()
    _plan_repo = InMemoryPlanRepository()
    _sub_repo = InMemorySubscriptionRepository()
    _checkout_repo = InMemoryCheckoutRepository()
    _inv_repo = InMemoryInvoiceRepository()
    _evt_repo = InMemoryBillingEventRepository()

    _plan_svc = PlanService(_plan_repo, _config)
    _cust_svc = CustomerService(_cust_repo, _provider)
    _checkout_svc = CheckoutService(_checkout_repo, _plan_svc, _cust_svc, _provider, _config)
    _sub_svc = SubscriptionService(_sub_repo, _inv_repo, _provider)
    _webhook_svc = WebhookService(
        _cust_repo, _sub_repo, _checkout_repo, _inv_repo, _evt_repo, _provider, _config,
    )
    _register_billing_deps(BillingDeps(
        plan_service=_plan_svc,
        customer_service=_cust_svc,
        checkout_service=_checkout_svc,
        subscription_service=_sub_svc,
        webhook_service=_webhook_svc,
    ))
    _register_billing_provider_config(_provider, _config)

    # SaaS-1.4: billing operations are bound to the actor's organization
    # membership. Register in-memory org deps and grant the billing actor an
    # OWNER membership in every organization the API tests target.
    from services.organizations.api import register_deps as _register_org_deps
    from services.organizations.api import OrgDeps as _OrgDeps
    from services.organizations.repositories import (
        InMemoryInvitationRepository as _InMemoryInvitationRepository,
        InMemoryMembershipRepository as _InMemoryMembershipRepository,
        InMemoryOrganizationRepository as _InMemoryOrganizationRepository,
    )
    from services.organizations.resolver import CurrentOrganizationResolver as _CurrentOrganizationResolver
    from services.organizations.services import (
        InvitationService as _InvitationService,
        MembershipService as _MembershipService,
        OrganizationService as _OrganizationService,
    )
    from services.organizations.models import Membership, MembershipRole, MembershipStatus

    _org_repo = _InMemoryOrganizationRepository()
    _membership_repo = _InMemoryMembershipRepository()
    _invitation_repo = _InMemoryInvitationRepository()
    _org_svc = _OrganizationService(_org_repo, _membership_repo)
    _membership_svc = _MembershipService(_membership_repo, _org_repo)
    _invitation_svc = _InvitationService(_invitation_repo, _membership_repo, _membership_svc)
    _register_org_deps(_OrgDeps(
        org_service=_org_svc,
        membership_service=_membership_svc,
        invitation_service=_invitation_svc,
        resolver=_CurrentOrganizationResolver(_org_repo, _membership_repo),
    ))
    for _org_id in ("org-api-1", "org-no-sub", "org-portal", "org-1"):
        asyncio.run(_membership_repo.save(Membership(
            organization_id=_org_id,
            user_id="billing-user",
            role=MembershipRole.OWNER,
            status=MembershipStatus.ACTIVE,
        )))

    client = TestClient(app)
    return client


class TestBillingAPI:

    def _override_auth(self, client, user_id: str = "billing-user"):
        async def override() -> str:
            return user_id
        client.app.dependency_overrides[_get_current_user] = override

    def _clear_overrides(self, client):
        client.app.dependency_overrides.clear()

    def test_list_plans(self, billing_api_client):
        self._override_auth(billing_api_client)
        resp = billing_api_client.get("/api/v1/billing/plans")
        self._clear_overrides(billing_api_client)
        assert resp.status_code == 200
        data = resp.json()
        assert "plans" in data
        assert len(data["plans"]) >= 1

    def test_create_checkout_api(self, billing_api_client):
        self._override_auth(billing_api_client)
        plan_resp = billing_api_client.get("/api/v1/billing/plans")
        plan = plan_resp.json()["plans"][0]
        resp = billing_api_client.post(
            "/api/v1/billing/checkout",
            json={
                "organization_id": "org-api-1",
                "plan_id": plan["id"],
                "email": "api@example.com",
            },
        )
        self._clear_overrides(billing_api_client)
        assert resp.status_code == 201
        data = resp.json()
        assert data["url"].startswith("https://checkout.stripe.com/mock/")
        assert data["status"] == "open"

    def test_get_subscription_api(self, billing_api_client):
        self._override_auth(billing_api_client)
        resp = billing_api_client.get(
            "/api/v1/billing/subscription",
            params={"organization_id": "org-no-sub"},
        )
        self._clear_overrides(billing_api_client)
        assert resp.status_code == 404

    def test_customer_portal_api(self, billing_api_client):
        self._override_auth(billing_api_client)
        plan_resp = billing_api_client.get("/api/v1/billing/plans")
        plan = plan_resp.json()["plans"][0]
        billing_api_client.post(
            "/api/v1/billing/checkout",
            json={
                "organization_id": "org-portal",
                "plan_id": plan["id"],
                "email": "portal@example.com",
            },
        )
        resp = billing_api_client.post(
            "/api/v1/billing/customer-portal",
            json={"organization_id": "org-portal"},
        )
        self._clear_overrides(billing_api_client)
        assert resp.status_code == 200
        data = resp.json()
        assert "url" in data

    def test_stripe_webhook_api(self, billing_api_client):
        payload = json.dumps({
            "type": "customer.created",
            "id": "evt_webhook_api_test",
            "data": {"object": {"id": "cus_api_test", "email": "apiwh@example.com"}},
        })
        resp = billing_api_client.post(
            "/api/v1/billing/webhooks/stripe",
            content=payload,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "processed"

    def test_stripe_webhook_duplicate(self, billing_api_client):
        payload = json.dumps({
            "type": "customer.created",
            "id": "evt_webhook_dup_api",
            "data": {"object": {"id": "cus_dup_api", "email": "dupapi@example.com"}},
        })
        billing_api_client.post(
            "/api/v1/billing/webhooks/stripe",
            content=payload,
            headers={"Content-Type": "application/json"},
        )
        resp = billing_api_client.post(
            "/api/v1/billing/webhooks/stripe",
            content=payload,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "duplicate"

    def test_unauthorized_access(self, billing_api_client):
        self._clear_overrides(billing_api_client)
        resp = billing_api_client.post(
            "/api/v1/billing/checkout",
            json={"organization_id": "org-1", "plan_id": "plan-1", "email": "test@example.com"},
        )
        assert resp.status_code == 401
