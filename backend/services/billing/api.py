from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from services.billing.config import BillingConfig
from services.billing.exceptions import (
    BillingException,
    CustomerAlreadyExists,
    CustomerNotFound,
    DuplicateWebhookEvent,
    InvoiceNotFound,
    NoActiveSubscription,
    OrganizationNotConfigured,
    PlanNotFound,
    ProviderError,
    SubscriptionNotFound,
    WebhookSignatureInvalid,
)
from services.billing.schemas import (
    CancelSubscriptionRequest,
    CancelSubscriptionResponse,
    CheckoutResponse,
    CreateCheckoutRequest,
    CustomerPortalRequest,
    CustomerPortalResponse,
    CustomerResponse,
    PlansListResponse,
    ResumeSubscriptionResponse,
    SubscriptionResponse,
)
from services.billing.services import (
    CheckoutService,
    CustomerService,
    PlanService,
    SubscriptionService,
    WebhookService,
)


def create_billing_provider(config: BillingConfig) -> object:
    mode = config.provider_mode
    if mode == "live":
        from services.billing.stripe_provider import StripeBillingProvider as LiveProvider
        return LiveProvider(config)
    from services.billing.stripe_provider import MockStripeBillingProvider
    return MockStripeBillingProvider(config)


def _build_billing_deps(
    provider: object,
    config: BillingConfig,
) -> BillingDeps:
    from services.billing.services import (
        CheckoutService,
        CustomerService,
        PlanService,
        SubscriptionService,
        WebhookService,
    )
    repos = _make_billing_repositories()
    plan_svc = PlanService(repos["plan_repo"], config)
    customer_svc = CustomerService(repos["customer_repo"], provider)
    checkout_svc = CheckoutService(
        repos["checkout_repo"], plan_svc, customer_svc, provider, config,
    )
    sub_svc = SubscriptionService(
        repos["sub_repo"], repos["invoice_repo"], provider,
    )
    webhook_svc = WebhookService(
        repos["customer_repo"], repos["sub_repo"], repos["checkout_repo"],
        repos["invoice_repo"], repos["event_repo"], provider, config,
    )
    return BillingDeps(
        plan_service=plan_svc,
        customer_service=customer_svc,
        checkout_service=checkout_svc,
        subscription_service=sub_svc,
        webhook_service=webhook_svc,
    )


router = APIRouter(prefix="/api/v1/billing", tags=["Billing"])


HTTP_ERROR_MAP: dict[type[Exception], int] = {
    PlanNotFound: 404,
    CustomerNotFound: 404,
    OrganizationNotConfigured: 404,
    SubscriptionNotFound: 404,
    NoActiveSubscription: 404,
    InvoiceNotFound: 404,
    CustomerAlreadyExists: 409,
    DuplicateWebhookEvent: 409,
    ProviderError: 502,
    WebhookSignatureInvalid: 400,
}


async def _get_current_user(request: Request) -> str:
    """Resolve the authenticated caller via the canonical identity dependency.

    The user is always derived from the ``Authorization: Bearer`` header;
    never from client-supplied input or ``request.state``.
    """
    from services.identity.dependencies import get_current_user_id
    return await get_current_user_id(request)


async def _assert_actor_org_access(current_user: str, organization_id: str) -> None:
    """Require the authenticated actor to be an active member of the target
    organization before any billing operation can target it.

    Prevents cross-tenant billing targeting (reading/modifying another
    organization's subscription, checkout, portal, cancel, resume) via a
    client-supplied ``organization_id``. Returns 404 (not 403) so non-member
    lookups cannot distinguish existing organizations.
    """
    if not organization_id:
        raise HTTPException(status_code=400, detail="organization_id required")
    from services.organizations.api import _get_membership_service
    from services.organizations.exceptions import MembershipNotFound
    membership_service = await _get_membership_service()
    try:
        membership = await membership_service.get_user_membership(current_user, organization_id)
    except MembershipNotFound:
        raise HTTPException(status_code=404, detail="Organization not found") from None
    status = getattr(membership.status, "value", membership.status)
    if status != "active":
        raise HTTPException(status_code=404, detail="Organization not found")


# ─── Dependency Functions ───────────────────────────────────────────


class BillingDeps:
    def __init__(
        self,
        plan_service: PlanService,
        customer_service: CustomerService,
        checkout_service: CheckoutService,
        subscription_service: SubscriptionService,
        webhook_service: WebhookService,
    ) -> None:
        self.plan_service = plan_service
        self.customer_service = customer_service
        self.checkout_service = checkout_service
        self.subscription_service = subscription_service
        self.webhook_service = webhook_service


_deps_registry: BillingDeps | None = None


def register_deps(deps: BillingDeps) -> None:
    global _deps_registry
    _deps_registry = deps


async def _get_plan_service() -> PlanService:
    if _deps_registry is None:
        raise HTTPException(status_code=500, detail="Billing services not initialized")
    return _deps_registry.plan_service


async def _get_customer_service() -> CustomerService:
    if _deps_registry is None:
        raise HTTPException(status_code=500, detail="Billing services not initialized")
    return _deps_registry.customer_service


async def _get_checkout_service() -> CheckoutService:
    if _deps_registry is None:
        raise HTTPException(status_code=500, detail="Billing services not initialized")
    return _deps_registry.checkout_service


async def _get_subscription_service() -> SubscriptionService:
    if _deps_registry is None:
        raise HTTPException(status_code=500, detail="Billing services not initialized")
    return _deps_registry.subscription_service


async def _get_webhook_service() -> WebhookService:
    if _deps_registry is None:
        raise HTTPException(status_code=500, detail="Billing services not initialized")
    return _deps_registry.webhook_service


# ─── Plans ──────────────────────────────────────────────────────────


@router.get("/plans", response_model=PlansListResponse)
async def list_plans(
    plan_service: PlanService = Depends(_get_plan_service),
):
    plans = await plan_service.list_plans()
    return PlansListResponse(
        plans=[_plan_to_response(p) for p in plans]
    )


# ─── Subscription ───────────────────────────────────────────────────


@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    organization_id: str = "",
    sub_service: SubscriptionService = Depends(_get_subscription_service),
    current_user: str = Depends(_get_current_user),
):
    if not organization_id:
        raise HTTPException(status_code=400, detail="organization_id required")
    await _assert_actor_org_access(current_user, organization_id)
    try:
        sub = await sub_service.get_active_subscription(organization_id)
    except NoActiveSubscription as exc:
        sub = await sub_service.get_subscription(organization_id)
        if sub is None:
            raise HTTPException(status_code=404, detail=exc.message) from exc
    return _sub_to_response(sub)


# ─── Checkout ───────────────────────────────────────────────────────


@router.post("/checkout", response_model=CheckoutResponse, status_code=201)
async def create_checkout(
    body: CreateCheckoutRequest,
    checkout_service: CheckoutService = Depends(_get_checkout_service),
    current_user: str = Depends(_get_current_user),
):
    try:
        await _assert_actor_org_access(current_user, body.organization_id)
        session = await checkout_service.create_checkout(
            organization_id=body.organization_id,
            plan_id=body.plan_id,
            email=body.email,
            success_url=body.success_url,
            cancel_url=body.cancel_url,
            trial_days=body.trial_days,
        )
    except (PlanNotFound, CustomerAlreadyExists, ProviderError) as exc:
        raise HTTPException(
            status_code=HTTP_ERROR_MAP.get(type(exc), 500),
            detail=exc.message,
        ) from exc
    return CheckoutResponse(
        id=session.id,
        url=session.url,
        organization_id=session.organization_id,
        plan_id=session.plan_id,
        status=session.status.value,
    )


# ─── Customer Portal ────────────────────────────────────────────────


@router.post("/customer-portal", response_model=CustomerPortalResponse)
async def customer_portal(
    body: CustomerPortalRequest,
    customer_service: CustomerService = Depends(_get_customer_service),
    subscription_service: SubscriptionService = Depends(_get_subscription_service),
    current_user: str = Depends(_get_current_user),
):
    await _assert_actor_org_access(current_user, body.organization_id)
    try:
        customer = await customer_service.get_customer_by_organization(
            body.organization_id,
        )
    except OrganizationNotConfigured as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc

    return_url = body.return_url or "http://localhost:3000/settings/billing"

    from services.billing.api import _deps_registry as _reg
    if _reg is None:
        raise HTTPException(status_code=500, detail="Billing services not initialized")
    from services.billing.provider import BillingProvider
    provider: BillingProvider = _get_provider()
    from services.billing.config import BillingConfig
    config = _get_config()

    portal_result = provider.create_customer_portal(
        customer_id=customer.provider_customer_id,
        return_url=return_url,
    )
    return CustomerPortalResponse(url=portal_result.url)


def _make_billing_repositories():
    from services.persistence import REPOSITORY_PROVIDER, RepositoryProvider
    if REPOSITORY_PROVIDER == RepositoryProvider.SUPABASE:
        from services.persistence.repositories import (
            SupabaseBillingEventRepository,
            SupabaseCheckoutRepository,
            SupabaseCustomerRepository,
            SupabaseInvoiceRepository,
            SupabasePlanRepository,
            SupabaseSubscriptionRepository,
        )
        plan_repo = SupabasePlanRepository()
        customer_repo = SupabaseCustomerRepository()
        sub_repo = SupabaseSubscriptionRepository()
        checkout_repo = SupabaseCheckoutRepository()
        invoice_repo = SupabaseInvoiceRepository()
        event_repo = SupabaseBillingEventRepository()
    else:
        from services.billing.repositories import (
            InMemoryBillingEventRepository,
            InMemoryCheckoutRepository,
            InMemoryCustomerRepository,
            InMemoryInvoiceRepository,
            InMemoryPlanRepository,
            InMemorySubscriptionRepository,
        )
        plan_repo = InMemoryPlanRepository()
        customer_repo = InMemoryCustomerRepository()
        sub_repo = InMemorySubscriptionRepository()
        checkout_repo = InMemoryCheckoutRepository()
        invoice_repo = InMemoryInvoiceRepository()
        event_repo = InMemoryBillingEventRepository()
    return {
        "plan_repo": plan_repo,
        "customer_repo": customer_repo,
        "sub_repo": sub_repo,
        "checkout_repo": checkout_repo,
        "invoice_repo": invoice_repo,
        "event_repo": event_repo,
    }


# ─── Cancel / Resume ────────────────────────────────────────────────


@router.post("/cancel", response_model=CancelSubscriptionResponse)
async def cancel_subscription(
    body: CancelSubscriptionRequest,
    sub_service: SubscriptionService = Depends(_get_subscription_service),
    current_user: str = Depends(_get_current_user),
):
    try:
        await _assert_actor_org_access(current_user, body.organization_id)
        sub = await sub_service.cancel_subscription(
            body.organization_id,
            at_period_end=body.at_period_end,
        )
    except (NoActiveSubscription, SubscriptionNotFound) as exc:
        raise HTTPException(
            status_code=HTTP_ERROR_MAP.get(type(exc), 500),
            detail=exc.message,
        ) from exc
    return CancelSubscriptionResponse(
        subscription=_sub_to_response(sub),
        message="Subscription will be canceled at period end"
        if sub.cancel_at_period_end
        else "Subscription canceled",
    )


@router.post("/resume", response_model=ResumeSubscriptionResponse)
async def resume_subscription(
    organization_id: str = "",
    sub_service: SubscriptionService = Depends(_get_subscription_service),
    current_user: str = Depends(_get_current_user),
):
    if not organization_id:
        raise HTTPException(status_code=400, detail="organization_id required")
    await _assert_actor_org_access(current_user, organization_id)
    try:
        sub = await sub_service.resume_subscription(organization_id)
    except SubscriptionNotFound as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    return ResumeSubscriptionResponse(subscription=_sub_to_response(sub))


# ─── Webhook ────────────────────────────────────────────────────────


@router.post("/webhooks/stripe")
async def stripe_webhook(
    request: Request,
    webhook_service: WebhookService = Depends(_get_webhook_service),
):
    raw_body = await request.body()
    signature = request.headers.get("stripe-signature", "")

    try:
        results = await webhook_service.process_webhook(
            raw_body=raw_body,
            signature=signature,
            provider_name="stripe",
        )
    except DuplicateWebhookEvent as exc:
        return {"status": "duplicate", "detail": exc.message}
    except (WebhookSignatureInvalid, ProviderError) as exc:
        raise HTTPException(
            status_code=HTTP_ERROR_MAP.get(type(exc), 500),
            detail=exc.message,
        ) from exc

    return {"status": "processed", "events": results}


# ─── Helpers ────────────────────────────────────────────────────────


def _plan_to_response(p) -> PlanResponse:
    from services.billing.schemas import PlanResponse
    return PlanResponse(
        id=p.id,
        code=p.code,
        name=p.name,
        description=p.description,
        billing_interval=p.billing_interval.value if hasattr(p.billing_interval, "value") else p.billing_interval,
        currency=p.currency,
        price=p.price,
        display_price=p.display_price,
        metadata=p.metadata,
    )


def _sub_to_response(s) -> SubscriptionResponse:
    return SubscriptionResponse(
        id=s.id,
        organization_id=s.organization_id,
        plan_id=s.plan_id,
        status=s.status.value if hasattr(s.status, "value") else s.status,
        trial_ends_at=s.trial_ends_at,
        current_period_start=s.current_period_start,
        current_period_end=s.current_period_end,
        cancel_at_period_end=s.cancel_at_period_end,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


# ─── Provider/Config access (wired from main.py) ────────────────────

_provider_instance: object | None = None
_config_instance: BillingConfig | None = None


def register_provider_and_config(
    provider: object,
    config: BillingConfig,
) -> None:
    global _provider_instance, _config_instance
    _provider_instance = provider
    _config_instance = config


def _get_provider() -> object:
    if _provider_instance is None:
        raise HTTPException(status_code=500, detail="Billing provider not initialized")
    return _provider_instance


def _get_config() -> BillingConfig:
    if _config_instance is None:
        return BillingConfig()
    return _config_instance
