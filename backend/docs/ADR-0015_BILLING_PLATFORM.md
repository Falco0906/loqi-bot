# ADR-0015 — Billing Platform

## Metadata

| Field | Value |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-20 |
| **Status** | **DRAFT** |

---

## Decision

A Billing Platform is established as a first-class platform responsible for all monetary concerns: customers, plans, subscriptions, invoices, trials, coupons, payment methods, and checkout sessions.

Billing is provider-agnostic. A `BillingProvider` interface abstracts all payment provider interactions. Stripe is the first implementation. No code outside the Billing Platform references Stripe APIs, Stripe SDK types, or Stripe webhook payloads.

Billing does not own lifecycle, onboarding, or capability gating. It owns money. Capability gating is owned by the Access Control Platform (see ADR-0016).

---

## Rationale

Without a Billing Platform, billing logic leaks into:

- Identity Platform (subscription status stored on User or Organization)
- Onboarding Service (checkout logic embedded in lifecycle steps)
- Frontend (plan prices and feature availability hardcoded)
- Business logic (inline plan checks scattered across codebase)

A provider-agnostic Billing Platform isolates payment provider complexity, provides a single entry point for all monetary operations, and ensures that Stripe types never contaminate the rest of the system.

---

## Billing State Machine

### Subscription States

```
NONE
  │
  ▼
TRIAL
  │
  ├──────────────────────────────────────────┐
  │                                          │
  ▼                                          │
ACTIVE                                       │
  │                                          │
  ├─────────────────────┐                    │
  │                     │                    │
  ▼                     ▼                    │
PAST_DUE             ACTIVE                  │
  │                  (renewed)               │
  ├──────────┐                               │
  │          │                               │
  ▼          ▼                               │
SUSPENDED  CANCELLED                         │
  │          │                               │
  │          ├───────────────────────────────┤
  │          │                               │
  ▼          ▼                               │
EXPIRED   EXPIRED                             │
                                               │
  [TRIAL expired without conversion → EXPIRED] │
  [ACTIVE cancelled → CANCELLED → EXPIRED]     │
  [PAST_DUE unresolved → SUSPENDED → EXPIRED]  │
```

| # | State | Purpose | Entry | Exit |
|---|---|---|---|---|
| 1 | `NONE` | No subscription exists. User has never selected a plan. | User created, no plan. | Plan selected (free or paid). |
| 2 | `TRIAL` | Active trial period. Full or restricted access depending on plan definition. | User selects trial-eligible plan. | Trial ends, or user upgrades to ACTIVE, or user cancels. |
| 3 | `ACTIVE` | Subscription is active and in good standing. | Payment confirmed (or trial started, or free plan). | Cancellation, payment failure, or downgrade to free. |
| 4 | `PAST_DUE` | Payment failed but still within grace period. User retains access. | Invoice payment failure. Billing provider reports `past_due`. | Successful retry → ACTIVE. Grace period expires → SUSPENDED. |
| 5 | `SUSPENDED` | Payment overdue beyond grace period. Access revoked (or severely restricted). | Grace period expired without payment. | User pays outstanding balance → ACTIVE. Prolonged non-payment → CANCELLED. |
| 6 | `CANCELLED` | Subscription cancelled by user or by system. Access continues until period end. | User cancels, or system cancels after prolonged suspension. | Period ends → EXPIRED. User re-subscribes → ACTIVE. |
| 7 | `EXPIRED` | Subscription period has ended. No access. | Cancelled subscription reaches period end. | User starts new subscription → ACTIVE (new plan, new term). |

### Edge Cases

| Scenario | Behavior |
|---|---|
| Free plan — no payment method | Subscription transitions directly from PLAN_SELECTION to ACTIVE with no CHECKOUT_PENDING. No payment method required. |
| Trial → Free downgrade | At trial end, if user has not selected a paid plan, subscription transitions to Free plan ACTIVE. |
| Trial → Paid upgrade mid-trial | Immediate transition to ACTIVE. Remaining trial days are forfeited (or applied as credit — configurable per plan). |
| Payment method expires | Billing provider reports `payment_method.requires_action`. Subscription remains ACTIVE. User notified to update payment method. |
| Multi-cycle payment failure | First failure → PAST_DUE. Second consecutive failure → SUSPENDED. Third → CANCELLED. Notification at each transition. |
| Immediate cancellation | User cancels within hours of subscribing. Full refund policy is separate from billing state machine. Subscription transitions to CANCELLED. |
| Reactivation after EXPIRED | New subscription. Previous data preserved (workspace, contacts, campaigns). New billing cycle starts. |
| Plan change mid-cycle | Subscription remains ACTIVE. Next invoice is prorated. Capabilities update immediately (see ADR-0016). |

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Billing Platform                        │
│                                                            │
│  ┌────────────────┐  ┌────────────────┐  ┌──────────────┐ │
│  │  BillingService │  │  InvoiceService│  │ CheckoutSvc  │ │
│  │  (orchestrator) │  │  (invoicing)   │  │ (sessions)   │ │
│  └───────┬────────┘  └───────┬────────┘  └──────┬───────┘ │
│          │                   │                   │         │
│          └───────────────────┼───────────────────┘         │
│                              │                             │
│                    ┌─────────▼──────────┐                  │
│                    │  BillingProvider   │                  │
│                    │  (interface)       │                  │
│                    └─────────┬──────────┘                  │
│                              │                             │
│                    ┌─────────▼──────────┐                  │
│                    │  StripeProvider    │                  │
│                    │  (implementation)  │                  │
│                    └────────────────────┘                  │
│                                                            │
│  ┌────────────────┐  ┌────────────────┐                    │
│  │  PlanRepository │  │SubscriptionRepo│                   │
│  └────────────────┘  └────────────────┘                    │
│  ┌────────────────┐  ┌────────────────┐                    │
│  │ InvoiceRepository│ │CouponRepository│                   │
│  └────────────────┘  └────────────────┘                    │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  WebhookHandler  (idempotent, retry-safe)             │  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
         │
         │  consumes
         ▼
┌──────────────────────────────────────────────────────────┐
│  Identity Platform   │  Onboarding Service   │  Others    │
│  (customer creation)  │  (checkout lifecycle)  │           │
└──────────────────────────────────────────────────────────┘
```

---

## Domain Models

### Customer

```
Customer {
    id: UUID
    organization_id: UUID
    billing_provider_customer_id: str | None  // Stripe customer ID
    default_payment_method: PaymentMethodType | None
    currency: str                              // ISO 4217
    billing_email: str
    billing_address: Address | None
    tax_id: TaxId | None
    created_at: DateTime
    updated_at: DateTime
}
```

A Customer maps 1:1 to an Organization. An Organization has exactly one Customer record.

### Plan

```
Plan {
    id: PlanId                              // "free", "starter", "growth", "scale", "enterprise"
    name: str
    description: str
    billing_provider_plan_id: str | None    // Stripe Price ID
    billing_provider_product_id: str | None
    price_cents: int
    currency: str
    interval: BillingInterval               // month, year
    trial_days: int
    is_public: bool                         // visible on pricing page
    is_active: bool                         // available for purchase
    sort_order: int
    metadata: Dict
}
```

Plans are defined in the Billing Platform database, not in Stripe. Stripe Price IDs are stored as references. This allows plan definitions to be managed independently of Stripe configuration.

### Subscription

```
Subscription {
    id: UUID
    organization_id: UUID
    plan_id: PlanId
    status: SubscriptionStatus              // NONE, TRIAL, ACTIVE, PAST_DUE, SUSPENDED, CANCELLED, EXPIRED
    billing_provider_subscription_id: str | None
    current_period_start: DateTime
    current_period_end: DateTime
    trial_start: DateTime | None
    trial_end: DateTime | None
    cancelled_at: DateTime | None
    ended_at: DateTime | None
    seats: int                              // number of paid seats
    metadata: Dict
}
```

### Invoice

```
Invoice {
    id: UUID
    organization_id: UUID
    subscription_id: UUID
    billing_provider_invoice_id: str | None
    number: str
    status: InvoiceStatus                   // draft, open, paid, void, uncollectible
    amount_due_cents: int
    amount_paid_cents: int
    amount_remaining_cents: int
    currency: str
    due_date: DateTime
    paid_at: DateTime | None
    invoice_pdf_url: str | None
    hosted_invoice_url: str | None
    line_items: List[InvoiceLineItem]
}
```

### CheckoutSession

```
CheckoutSession {
    id: UUID
    organization_id: UUID
    plan_id: PlanId
    billing_provider_session_id: str | None
    status: CheckoutStatus                  // pending, completed, expired, abandoned
    success_url: str
    cancel_url: str
    expires_at: DateTime
    completed_at: DateTime | None
    metadata: Dict
}
```

### Coupon

```
Coupon {
    id: UUID
    code: str
    discount_percent: int | None
    discount_amount_cents: int | None
    max_redemptions: int | None
    current_redemptions: int
    applies_to_plan_ids: List[PlanId]
    expires_at: DateTime | None
    is_active: bool
}
```

---

## BillingProvider Interface

```
BillingProvider {
    create_customer(organization_id, billing_email, name) -> Customer
    get_customer(customer_id) -> Customer
    update_customer(customer_id, data) -> Customer

    create_checkout_session(customer_id, plan_id, success_url, cancel_url) -> CheckoutSession
    get_checkout_session(session_id) -> CheckoutSession

    create_subscription(customer_id, plan_id) -> Subscription
    get_subscription(subscription_id) -> Subscription
    update_subscription(subscription_id, data) -> Subscription
    cancel_subscription(subscription_id, at_period_end) -> Subscription

    get_invoice(invoice_id) -> Invoice
    list_invoices(customer_id) -> List[Invoice]

    create_payment_intent(customer_id, amount_cents, currency) -> PaymentIntent

    handle_webhook(payload, signature) -> WebhookEvent
    parse_event(event_data) -> BillingEvent

    supports_provider(provider_type) -> bool
}
```

All methods return domain types — never Stripe SDK types. The implementation maps between Stripe types and Billing domain types.

---

## Services

### BillingService

Orchestrates all billing operations. Wraps the BillingProvider with retry, idempotency, and event emission.

```
BillingService {
    // Customer management
    create_customer(org_id, email, name) -> Customer
    get_customer(org_id) -> Customer
    update_customer(org_id, data) -> Customer

    // Subscription lifecycle
    get_subscription(org_id) -> Subscription
    change_plan(org_id, new_plan_id) -> Subscription
    cancel_subscription(org_id, at_period_end) -> Subscription
    reactivate_subscription(org_id) -> Subscription

    // Checkout
    create_checkout_session(org_id, plan_id) -> CheckoutSession

    // Trial
    start_trial(org_id, plan_id) -> Subscription
    convert_trial(org_id, plan_id) -> Subscription
    expire_trials() -> int  // batch process

    // Invoices
    get_invoices(org_id) -> List[Invoice]
    get_invoice_pdf(invoice_id) -> bytes

    // Coupons
    validate_coupon(code, plan_id) -> Coupon
    apply_coupon(org_id, code) -> Coupon

    // Webhooks
    handle_webhook(payload, signature) -> BillingEvent

    // Queries
    is_subscription_active(org_id) -> bool
    get_subscription_status(org_id) -> SubscriptionStatus
    has_payment_method(org_id) -> bool
}
```

### InvoiceService

Handles invoice generation, payment retry, and dunning. Delegates to BillingProvider for actual invoicing but manages local invoice state.

### CheckoutService

Manages checkout session creation and lifecycle. Tracks pending sessions, handles timeout, and communicates completion to OnboardingService.

### WebhookHandler

Single entry point for all billing webhooks. Validates signatures, deduplicates via idempotency key, maps external events to internal events.

---

## Webhook Handling

### Flow

```
Stripe
  │
  │  POST /billing/webhook (signed payload)
  ▼
WebhookHandler.verify_signature(payload, signature)
  │
  ├─ Invalid → 400 (dropped silently)
  │
  └─ Valid
       │
       ▼
  IdempotencyCheck(event_id)
       │
       ├─ Already processed → 200 (acknowledge, skip)
       │
       └─ New event
            │
            ▼
       ParseEvent(raw_payload) → BillingEvent
            │
            ▼
       Dispatch(event)
            │
            ├─ invoice.payment_succeeded → InvoiceService.mark_paid()
            ├─ invoice.payment_failed → BillingService.transition_to(PAST_DUE)
            ├─ customer.subscription.created → SubscriptionService.sync()
            ├─ customer.subscription.updated → SubscriptionService.sync()
            ├─ customer.subscription.deleted → BillingService.transition_to(CANCELLED)
            ├─ checkout.session.completed → CheckoutService.complete_session()
            ├─ payment_method.attached → CustomerService.update_payment_method()
            └─ (unknown) → log and acknowledge
            │
            ▼
       Emit platform event → Event Bus
            │
            ▼
       Return 200 to Stripe
```

### Idempotency

Every webhook event carries a unique `event_id`. The WebhookHandler stores processed `event_id`s in a dedicated store with a TTL of 90 days. Duplicate webhooks within that window are acknowledged with 200 and skipped.

### Retry behavior

| Scenario | Behavior |
|---|---|
| Webhook handler returns 5xx | Stripe retries with exponential backoff (up to 3 days) |
| Webhook handler returns 4xx | Stripe does not retry. Requires manual reconciliation. |
| Webhook handler times out (>30s) | Stripe retries. Handler should process within 5s. |
| Duplicate delivery | Idempotency check returns 200. No side effects. |

### Failure recovery

A periodic reconciliation job runs every hour to compare local subscription state with Stripe state. Mismatches are logged and corrected. This catches missed webhooks regardless of cause.

---

## Events

| Event | Trigger | Payload |
|---|---|---|
| `billing.customer.created` | Customer record created | org_id, customer_id |
| `billing.subscription.activated` | Subscription becomes ACTIVE | org_id, plan_id, period_start, period_end |
| `billing.subscription.trial_started` | Trial begins | org_id, plan_id, trial_end |
| `billing.subscription.trial_expired` | Trial ends | org_id, plan_id |
| `billing.subscription.plan_changed` | Plan changed mid-cycle | org_id, old_plan_id, new_plan_id, effective_date |
| `billing.subscription.past_due` | Payment failed | org_id, invoice_id, amount_due, due_date |
| `billing.subscription.suspended` | Payment overdue beyond grace | org_id, days_overdue |
| `billing.subscription.cancelled` | Subscription cancelled | org_id, cancelled_at, effective_end |
| `billing.subscription.expired` | Period ended after cancellation | org_id, expired_at |
| `billing.subscription.reactivated` | Previously expired/cancelled restarted | org_id, new_subscription_id |
| `billing.invoice.paid` | Invoice paid successfully | org_id, invoice_id, amount_paid |
| `billing.invoice.failed` | Invoice payment failed | org_id, invoice_id, failure_reason |
| `billing.checkout.completed` | Checkout session completed | org_id, plan_id, session_id |
| `billing.checkout.abandoned` | Checkout session abandoned | org_id, plan_id, session_id |
| `billing.coupon.applied` | Coupon applied to subscription | org_id, coupon_code, discount_description |
| `billing.payment_method.updated` | Default payment method changed | org_id, method_type |

---

## Platform Interaction Boundaries

### Billing Platform owns

- Customer records (billing-specific data)
- Plan definitions
- Subscriptions (state machine, lifecycle, status)
- Invoices and payment history
- Checkout session creation and tracking
- Coupon validation and application
- Payment method management
- Webhook handling and idempotency
- Payment retry (dunning)
- Subscription reconciliation

### Billing Platform does NOT own

- User identity lifecycle (Identity Platform)
- Onboarding wizard progression (Onboarding Platform — ADR-0014)
- Capability gating or feature flags (Access Control — ADR-0016)
- Usage metering or credit tracking (Future Usage Platform)
- Organization data (Identity Platform)
- Plan pricing display (Frontend)
- Account deletion or data export (Identity Platform)

### Interaction rules

| Interaction | Owner | Consumer |
|---|---|---|
| Create customer | Billing | Called by Identity after Organization creation |
| Start checkout | Onboarding | Calls Billing to create checkout session |
| Payment succeeded | Billing | Emits event. Onboarding consumes to advance lifecycle. |
| Subscription status check | Billing | Called by Access Control Platform to determine capability evaluation |
| Cancel subscription | User via API | Billing handles cancellation. Emits event. |
| Plan change | User via API | Billing handles plan change. Emits event. Access Control re-evaluates capabilities. |
| Invoice list | User via API | Billing returns invoices. Frontend renders billing history. |

---

## Ownership Decision: Billing vs Identity

### Where does Customer live?

| Aspect | Decision | Rationale |
|---|---|---|
| `Organization` record | Identity Platform | Organization is the identity container for all resources |
| `Customer` record | Billing Platform | Customer is the billing-specific representation of an Organization |
| `billing_email` | Both (Billing is source of truth) | Identity stores `email` for authentication. Billing stores `billing_email` for invoices. They may differ. |
| `default_payment_method` | Billing Platform | Identity has no concept of payment methods |
| `subscription_status` | Billing Platform | Subscription is a billing concept. Access Control reads it via Billing query. |

### Where does subscription status get consumed?

Access Control Platform (ADR-0016) queries `BillingService.is_subscription_active(org_id)` during capability evaluation. It never reads subscription status directly from a Billing database table. This maintains the abstraction boundary.

---

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/billing/checkout` | Create checkout session for a plan |
| GET | `/billing/checkout/{id}` | Get checkout session status |
| POST | `/billing/checkout/{id}/refresh` | Refresh expired checkout session |
| GET | `/billing/subscription` | Get current subscription |
| POST | `/billing/subscription/change` | Change plan |
| POST | `/billing/subscription/cancel` | Cancel subscription |
| POST | `/billing/subscription/reactivate` | Reactivate cancelled subscription |
| GET | `/billing/invoices` | List invoices |
| GET | `/billing/invoices/{id}` | Get invoice detail |
| GET | `/billing/invoices/{id}/pdf` | Download invoice PDF |
| POST | `/billing/webhook` | Stripe webhook endpoint |
| GET | `/billing/plans` | List available plans |
| POST | `/billing/coupon/validate` | Validate coupon code |
| GET | `/billing/payment-method` | Get default payment method |
| POST | `/billing/payment-method` | Update payment method (redirect to provider) |
| GET | `/billing/portal` | Redirect to Stripe Customer Portal |

---

## Repositories

| Repository | Interface | Store |
|---|---|---|
| `CustomerRepository` | `CustomerRepository` | Billing database |
| `PlanRepository` | `PlanRepository` | Billing database |
| `SubscriptionRepository` | `SubscriptionRepository` | Billing database |
| `InvoiceRepository` | `InvoiceRepository` | Billing database |
| `CheckoutSessionRepository` | `CheckoutSessionRepository` | Billing database |
| `CouponRepository` | `CouponRepository` | Billing database |

All repositories use the same pattern established in Identity Platform (Repository interface + InMemoryRepository base class).

---

## Extension Points

| Extension Point | Mechanism |
|---|---|
| New billing provider | Implement `BillingProvider` interface. Register in provider registry. |
| Usage-based billing | Future `UsageProvider` interface. Metered components (AI credits, discovery credits) track usage and report to Billing. |
| Enterprise invoicing (NET-30, PO-based) | `BillingProvider.invoice_customer()` method. Enterprise bypasses checkout entirely. |
| Multi-currency | `Customer.currency` field. `Plan.price_cents` + `currency`. Provider handles conversion. |
| Proration | `BillingService.change_plan()` delegates proration calculation to provider. Local proration for providers that don't support it. |
| Dunning | `InvoiceService.start_dunning()` implements escalation sequence: day 1 → email, day 3 → email, day 7 → SMS, day 14 → SUSPENDED. Configurable per plan. |
| Reseller / white-label | Organization-level `billing_provider` configuration. Each org may use a different billing provider. |
| Grace period | Configurable per plan in `Plan.grace_period_days`. Applied before SUSPENDED transition. |

---

## Tradeoffs

### Approach: Provider-agnostic interface vs direct Stripe coupling

Chosen: Provider-agnostic `BillingProvider` interface with Stripe implementation.

Alternative: Call Stripe SDK directly in all services. Rejected because Stripe types would leak everywhere, changing providers (Paddle, LemonSqueezy, Enterprise invoicing) would require rewriting all billing code, and testing would require Stripe mock infrastructure in non-billing services.

### Approach: Local subscription state vs Stripe-only state

Chosen: Local subscription state with periodic reconciliation.

Alternative: Always read subscription state from Stripe. Rejected because it adds latency to every capability check, breaks when Stripe is unavailable, prevents offline capability evaluation, and couples system availability to an external provider.

### Approach: Webhook-driven state vs poll-driven state

Chosen: Webhook-driven with periodic reconciliation as backup.

Alternative: Poll Stripe on a schedule. Rejected because polling adds latency — a subscription status change may not be reflected for up to the polling interval (potentially minutes). Webhooks provide near-real-time state changes. Reconciliation catches missed webhooks.

### Approach: Dedicated Billing database vs shared database

Chosen: Billing Platform uses its own tables but within the same database as Identity and other platforms.

Alternative: Separate billing database. Rejected for MVP — the operational complexity of multiple databases is not yet justified. The domain models and repository interfaces are designed so that separating to a dedicated database later requires no code changes beyond repository implementations.

---

## Future Considerations

### Usage-based billing

Future `UsageMeter` components track consumption of metered resources (discovery credits, AI generations, API calls). Usage data is reported to the Billing Platform periodically. The BillingProvider maps usage to line items on the next invoice.

### Prepaid credits

Users may purchase credit packs independent of subscriptions. Credit packs are represented as a separate `CreditBalance` entity managed by the Billing Platform. Credit consumption is delegated to a Future Usage Platform.

### Marketplaces (AppSumo, partner resale)

Partner-purchased subscriptions use a separate `PartnerBillingProvider` implementation that validates license keys instead of processing payments.

### Tax automation

Tax calculation (VAT, GST, Sales Tax) is delegated to the BillingProvider. Stripe Tax is the initial implementation. Provider-agnostic tax id validation lives in the Billing Platform.

---

## References

- ADR-0011 — Identity Platform (Organization record, identity boundaries)
- ADR-0014 — User Lifecycle & Onboarding (checkout interaction, lifecycle transitions)
- ADR-0016 — Capability & Commercial Access (subscription status consumed for capability evaluation)
