# ADR-0014 — User Lifecycle & Onboarding

## Metadata

| Field | Value |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-20 |
| **Status** | **DRAFT** |

---

## Decision

A formal Onboarding Platform is established as the orchestrator of user progression from first visit through activation.

The User Lifecycle is modeled as a state machine. Every user has exactly one lifecycle state at any point in time. The backend owns the lifecycle state machine. The frontend renders the current step and never infers lifecycle state.

The Lifecycle and Onboarding Platform is a thin orchestration layer that sits between Identity and the rest of the product.

---

## Rationale

Loqi currently ships a user through authentication and into an empty dashboard with no guided progression. This creates several problems:

- No distinction between a visitor, a trial user, a paying customer, or a churned user
- No way to resume an interrupted onboarding flow
- No way to determine what step a user should see next without frontend inference
- No centralized state for product-led growth experiments
- No support for enterprise onboarding flows that bypass standard steps

A formal lifecycle state machine with a dedicated OnboardingService provides a single source of truth for user progression, enables product-led growth experiments, and separates onboarding orchestration from both Identity and business logic.

---

## Lifecycle State Machine

### States

```
VISITOR
  │
  ▼
AUTHENTICATED
  │
  ▼
PROFILE_SETUP
  │
  ▼
WORKSPACE_SETUP
  │
  ▼
PLAN_SELECTION
  │
  ▼
CHECKOUT_PENDING
  │
  ▼
SUBSCRIPTION_ACTIVE
  │
  ▼
ONBOARDING_COMPLETE
  │
  ▼
ACTIVE
```

| # | State | Purpose | Entry Criteria | Exit Criteria | Failure / Recovery |
|---|---|---|---|---|---|
| 1 | `VISITOR` | Unauthenticated user on marketing site or landing page. | Browser visit or app open. No session token. | User completes authentication (signup or login). | N/A — visitor has no backend state. |
| 2 | `AUTHENTICATED` | User has authenticated but not completed profile. | Identity Platform returns successful auth result. | User provides display name, avatar, locale. | Abandoned signup → token expires → returns to VISITOR. Recovery: new auth flow. |
| 3 | `PROFILE_SETUP` | Collecting user profile information. | Auth complete, user directed to profile form. | User submits profile data. | Timeout → return to same state with preserved data. User may skip and edit later. |
| 4 | `WORKSPACE_SETUP` | Creating or configuring the user's workspace. | Profile data saved. | Workspace name provided, defaults accepted or customized. | Skip → use defaults (org name = user display name). |
| 5 | `PLAN_SELECTION` | User chooses a plan (Free, Starter, Growth, Scale, or Enterprise flow). | Workspace created. | Plan selected (may be Free — no checkout needed). | No selection → default to Free plan after timeout. |
| 6 | `CHECKOUT_PENDING` | User has initiated paid plan checkout but not completed payment. | User clicked "Subscribe" on a paid plan. | Payment confirmed by Billing Platform webhook. | Payment abandoned → return to PLAN_SELECTION. Payment failed → retry prompt. |
| 7 | `SUBSCRIPTION_ACTIVE` | Paid subscription is active. Free plan users skip CHECKOUT_PENDING and land here directly. | Billing Platform confirms subscription active (or Free plan assigned). | Onboarding wizard or guided tour completed. | Payment failure → transition to Billing state PAST_DUE. See ADR-0015. |
| 8 | `ONBOARDING_COMPLETE` | Guided onboarding has been completed. | User finished onboarding wizard or explicitly dismissed it. | First meaningful action (first campaign created, first contact imported, etc.). | User may revisit onboarding from settings. |
| 9 | `ACTIVE` | Full platform access. Normal operations. | User performed first meaningful action. | — | Cancellation → transition back through lifecycle based on plan status. See ADR-0015 for billing states. |

### Allowed Transitions

```
VISITOR → AUTHENTICATED                    (login or signup)
AUTHENTICATED → PROFILE_SETUP              (first time)
AUTHENTICATED → ACTIVE                     (returning user, onboarding complete)
PROFILE_SETUP → WORKSPACE_SETUP            (profile complete)
PROFILE_SETUP → ACTIVE                     (returning user who skipped, onboarding already complete)
WORKSPACE_SETUP → PLAN_SELECTION           (workspace configured)
WORKSPACE_SETUP → ACTIVE                   (returning user with existing workspace)
PLAN_SELECTION → CHECKOUT_PENDING          (paid plan selected)
PLAN_SELECTION → SUBSCRIPTION_ACTIVE       (Free plan selected)
CHECKOUT_PENDING → SUBSCRIPTION_ACTIVE     (payment confirmed)
CHECKOUT_PENDING → PLAN_SELECTION          (payment abandoned or failed)
SUBSCRIPTION_ACTIVE → ONBOARDING_COMPLETE  (onboarding wizard completed)
SUBSCRIPTION_ACTIVE → ACTIVE               (onboarding skipped, user self-directed)
ONBOARDING_COMPLETE → ACTIVE              (first meaningful action)
ACTIVE → AUTHENTICATED                     (session expired, re-authentication)
```

### Failure States

| Scenario | Behavior | Recovery |
|---|---|---|
| Authentication failure | Stay VISITOR. Increment failure counter. | Clear error message. Rate-limited retry. |
| Email verification timeout | Stay PROFILE_SETUP. | Resend verification email. |
| Payment gateway timeout | Stay CHECKOUT_PENDING. | Background retry with exponential backoff. Notify user. |
| Webhook delivery failure | Stay CHECKOUT_PENDING. | Billing Platform retries webhook. Eventually reconcile via subscription poll. |
| Identity token expired mid-onboarding | Transition to AUTHENTICATED (re-auth required). | Redirect to login. Preserve onboarding context on return. |

---

## Backend Ownership vs Frontend Ownership

### Backend owns

- User lifecycle state machine (the single source of truth)
- OnboardingService — determines next step, evaluates completion criteria
- OnboardingContext — persisted state passed across onboarding steps
- Step completion validation (what constitutes "done" for each step)
- Lifecycle event emission
- Step skipping logic
- Onboarding resumption for returning users
- Enterprise onboarding override logic

### Frontend owns

- Rendering the current step UI
- Collecting user input for the current step
- Calling backend APIs to advance steps
- Handling navigation within the current step (e.g., multi-screen profile form)
- Providing progress indicators based on backend state
- Triggering onboarding entry point detection (is there an active onboarding?)

### Rule

The frontend calls `GET /onboarding/current-step` on app load. The backend returns the current step identifier and any required context. The frontend renders accordingly. The frontend never stores, caches, or infers lifecycle state.

```
Frontend load
  │
  ▼
GET /onboarding/current-step
  │
  ▼
Response: { step: "WORKSPACE_SETUP", context: { ... } }
  │
  ▼
Frontend renders Workspace Setup screen
  │
  ▼
User completes step
  │
  ▼
POST /onboarding/complete-step { step: "WORKSPACE_SETUP", data: {...} }
  │
  ▼
Backend validates, advances state, returns next step
```

---

## OnboardingService

### Responsibilities

1. **Determine current lifecycle state** — Given a user_id, return the current lifecycle state from the persisted store
2. **Determine next onboarding step** — Evaluate current state against completion criteria and return the next incomplete step
3. **Advance to next step** — Validate step completion data, transition state, return new state
4. **Resume onboarding** — For returning users, return to the exact step where they left off
5. **Skip completed steps** — When evaluating next step, skip any step whose completion criteria are met
6. **Handle partial onboarding** — Allow step data to be saved without completing the step (draft state)
7. **Handle interrupted onboarding** — Session expiry, browser close, device switch. Preserve all completed step data
8. **Support returning users** — A user who completed PLAN_SELECTION but not ONBOARDING_COMPLETE returns to SUBSCRIPTION_ACTIVE on next login
9. **Support enterprise onboarding** — Enterprise customers may bypass PLAN_SELECTION and CHECKOUT_PENDING entirely. A `bypass_steps` configuration on the Organization record skips specified states

### Service Interface

```
OnboardingService {
    get_current_state(user_id) -> LifecycleState
    get_current_step(user_id) -> OnboardingStep
    complete_step(user_id, step_id, data) -> OnboardingStep  // returns next step
    skip_step(user_id, step_id) -> OnboardingStep
    save_step_draft(user_id, step_id, data) -> void
    get_completed_steps(user_id) -> List[StepId]
    is_onboarding_complete(user_id) -> bool
    force_transition(user_id, target_state) -> void  // admin only
}
```

---

## OnboardingContext

A persisted data object passed across onboarding steps. Contains all data collected during the onboarding flow regardless of where the user currently is.

```
OnboardingContext {
    user_id: UUID
    current_state: LifecycleState
    completed_steps: List[StepRecord]
    step_data: Dict[StepId, Dict]            // raw data collected per step
    profile_data: ProfileData | None         // from PROFILE_SETUP
    workspace_data: WorkspaceData | None     // from WORKSPACE_SETUP
    selected_plan: PlanId | None             // from PLAN_SELECTION
    checkout_session_id: str | None          // from CHECKOUT_PENDING
    enterprise_bypass: List[StepId]          // steps to skip for enterprise
    created_at: DateTime
    updated_at: DateTime
    completed_at: DateTime | None
}
```

The `OnboardingContext` is persisted alongside the user record. It may be loaded and saved in a single transaction.

---

## Domain Models

### LifecycleState

Enumeration of all possible lifecycle states: `VISITOR`, `AUTHENTICATED`, `PROFILE_SETUP`, `WORKSPACE_SETUP`, `PLAN_SELECTION`, `CHECKOUT_PENDING`, `SUBSCRIPTION_ACTIVE`, `ONBOARDING_COMPLETE`, `ACTIVE`, `CANCELLED`, `EXPIRED`.

### OnboardingStep

Represents a single step in the onboarding wizard:

```
OnboardingStep {
    id: StepId
    label: str
    description: str
    is_required: bool
    is_skippable: bool
    completion_criteria: Dict  // e.g., {"has_profile": true}
}
```

### StepRecord

Immutable record of a completed step:

```
StepRecord {
    step_id: StepId
    completed_at: DateTime
    data: Dict  // snapshot of what was collected
}
```

### OnboardingSession

Tracks a single onboarding session across requests:

```
OnboardingSession {
    id: UUID
    user_id: UUID
    current_step: StepId
    context: OnboardingContext
    is_active: bool
    expires_at: DateTime
    created_at: DateTime
}
```

### UserLifecycle

Root entity tying user to lifecycle state:

```
UserLifecycle {
    user_id: UUID
    state: LifecycleState
    onboarding_context_id: UUID | None
    entered_state_at: DateTime
    last_activity_at: DateTime
    created_at: DateTime
    updated_at: DateTime
}
```

---

## Events

| Event | Trigger | Payload |
|---|---|---|
| `lifecycle.transition` | State machine transition | user_id, from_state, to_state, triggered_by |
| `onboarding.step.completed` | Step completed | user_id, step_id, step_data |
| `onboarding.step.skipped` | Step skipped | user_id, step_id, reason |
| `onboarding.started` | First onboarding step | user_id, context_id |
| `onboarding.completed` | ONBOARDING_COMPLETE reached | user_id, context_id |
| `onboarding.resumed` | Returning user continues | user_id, current_step |
| `onboarding.abandoned` | No activity for N days | user_id, last_step |
| `lifecycle.enterprise.bypass` | Enterprise steps skipped | user_id, org_id, skipped_steps |

---

## Sequence Diagrams

### First-time user flow

```
User         Frontend         Backend          OnboardingSvc   Identity     Billing
 │              │                │                  │             │            │
 │   signup     │                │                  │             │            │
 │─────────────>│  POST /auth    │                  │             │            │
 │              │───────────────>│                  │             │            │
 │              │                │  create_user      │             │            │
 │              │                │──────────────────>│             │            │
 │              │                │  lifecycle.create                    │            │
 │              │                │  state=AUTHENTICATED                 │            │
 │              │                │<──────────────────│             │            │
 │              │  auth result   │                  │             │            │
 │              │<───────────────│                  │             │            │
 │              │                │                  │             │            │
 │              │                │                  │             │            │
 │  GET /onboarding/current-step                    │             │            │
 │─────────────>│────────────────>│                  │             │            │
 │              │                │  get_current_step │             │            │
 │              │                │──────────────────>│             │            │
 │              │                │  PROFILE_SETUP    │             │            │
 │              │<───────────────│<──────────────────│             │            │
 │  render       │                │                  │             │            │
 │<─────────────│                │                  │             │            │
 │              │                │                  │             │            │
 │  profile     │                │                  │             │            │
 │─────────────>│  POST /onboarding/complete-step   │             │            │
 │              │───────────────>│                  │             │            │
 │              │                │  complete_step    │             │            │
 │              │                │──────────────────>│             │            │
 │              │                │  transition       │             │            │
 │              │                │  PROFILE_SETUP→   │             │            │
 │              │                │  WORKSPACE_SETUP  │             │            │
 │              │                │<──────────────────│             │            │
 │              │  return next   │                  │             │            │
 │              │  step          │                  │             │            │
 │              │<───────────────│                  │             │            │
 │              │                │                  │             │            │
 │  workspace   │                │                  │             │            │
 │─────────────>│  (repeat)      │                  │             │            │
 │              │───────────────>│                  │             │            │
 │              │                │──────────────────>│             │            │
 │              │                │<──────────────────│             │            │
 │              │<───────────────│                  │             │            │
 │              │                │                  │             │            │
 │  plan select │                │                  │             │            │
 │─────────────>│────────────────>│                  │             │            │
 │              │                │──────────────────>│             │            │
 │              │                │<──────────────────│             │            │
 │              │<───────────────│                  │             │            │
 │              │                │                  │             │            │
 │  checkout    │                │                  │             │            │
 │─────────────>│────────────────>│                  │             │            │
 │              │                │  create_checkout  │                          │
 │              │                │─────────────────────────────────────────────>│
 │              │                │  checkout_url     │                          │
 │              │<───────────────│<─────────────────────────────────────────────│
 │  redirect    │                │                  │             │            │
 │<─────────────│                │                  │             │            │
 │              │                │                  │             │            │
 │  [Stripe Checkout]            │                  │             │            │
 │              │                │                  │             │            │
 │              │                │  webhook         │                          │
 │              │                │<─────────────────────────────────────────────│
 │              │                │  transition      │                          │
 │              │                │──────────────────>│                          │
 │              │                │  SUBSCRIPTION_   │                          │
 │              │                │  ACTIVE          │                          │
 │              │                │<──────────────────│                          │
 │              │                │                  │             │            │
 │              │  GET /onboarding/current-step     │             │            │
 │─────────────>│────────────────>│                  │             │            │
 │              │                │──────────────────>│             │            │
 │              │                │  ONBOARDING_      │             │            │
 │              │                │  COMPLETE →       │             │            │
 │              │                │  onboarding wizard │            │            │
 │              │<───────────────│<──────────────────│             │            │
 │              │                │                  │             │            │
 │  wizard done │                │                  │             │            │
 │─────────────>│────────────────>│                  │             │            │
 │              │                │──────────────────>│             │            │
 │              │                │<──────────────────│             │            │
 │  dashboard   │                │  ACTIVE           │             │            │
 │<─────────────│<───────────────│                  │             │            │
```

### Returning user flow

```
User         Frontend         Backend          OnboardingSvc
 │              │                │                  │
 │  login       │                │                  │
 │─────────────>│  POST /auth    │                  │
 │              │───────────────>│                  │
 │              │                │  authenticate     │
 │              │                │  return identity  │
 │              │<───────────────│                  │
 │              │                │                  │
 │  GET /onboarding/current-step                    │
 │─────────────>│────────────────>│                  │
 │              │                │  get_current_step │
 │              │                │──────────────────>│
 │              │                │  evaluate_context │
 │              │                │  skip_completed   │
 │              │                │  return WORKSPACE │
 │              │                │  _SETUP           │
 │              │<───────────────│<──────────────────│
 │  render       │                │                  │
 │<─────────────│                │                  │
 │              │                │                  │
 │  [resumes where they left off]                   │
```

### Enterprise bypass flow

```
Admin          Frontend         Backend          OnboardingSvc     Identity
 │              │                │                  │                │
 │  create org  │                │                  │                │
 │  (enterprise)│────────────────>│                  │                │
 │              │                │  org.mark_enterprise()             │
 │              │                │──────────────────>│                │
 │              │                │<──────────────────│                │
 │              │                │                  │                │
 │              │  [user signs up]                  │                │
 │              │────────────────────────────────────────────────────>│
 │              │                │                  │                │
 │              │  GET /onboarding/current-step     │                │
 │              │────────────────>│                  │                │
 │              │                │  detect enterprise│                │
 │              │                │  bypass_steps     │                │
 │              │                │  = [PLAN_SELECTION,               │
 │              │                │     CHECKOUT_PENDING]             │
 │              │                │  return PROFILE_SETUP             │
 │              │<───────────────│                  │                │
 │              │                │                  │                │
 │  [user completes steps until ACTIVE]             │                │
```

---

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/onboarding/current-step` | Return current step and context |
| POST | `/onboarding/complete-step` | Submit step data, advance to next step |
| POST | `/onboarding/skip-step` | Skip optional step |
| POST | `/onboarding/save-draft` | Save partial step data without advancing |
| GET | `/onboarding/progress` | Return overall progress (completed steps, total steps) |
| GET | `/onboarding/context` | Return full OnboardingContext |
| POST | `/admin/users/{id}/lifecycle` | Force lifecycle transition (admin only) |

---

## Extension Points

| Extension Point | Mechanism |
|---|---|
| New onboarding step | Add `StepId` enum member, define completion criteria, implement step handler |
| Enterprise bypass config | `enterprise_bypass` field on Organization. OnboardingService checks before returning next step |
| Custom onboarding flow per tenant | Organization-level `onboarding_flow` configuration (list of StepIds in order) |
| AI-guided onboarding | Future `OnboardingGuide` provider that recommends next actions instead of fixed steps |
| Multi-user onboarding | When Organization has multiple members, onboarding completes per-user after org-level setup is done |
| Migration from legacy | `force_transition` admin endpoint. `migrate_lifecycle` batch job for bulk imports |
| A/B testing steps | `onboarding_variant` field on User or Organization determines which step sequence to use |
| Post-activation re-onboarding | When major features are released, `ONBOARDING_COMPLETE` → re-trigger for feature-specific onboarding |

---

## Tradeoffs

### Approach: Explicit state machine vs inferred state

Chosen: Explicit state machine. The backend persists lifecycle state and evaluates transitions.

Alternative: Infer state from available data (does user have a profile? workspace? payment method?). Rejected because inference is fragile — it breaks when data is incomplete, when users churn and return, and when enterprise flows bypass standard steps.

### Approach: Standalone OnboardingService vs embedded in Identity

Chosen: Standalone OnboardingService. It references Identity for user data but is a separate service with its own state machine.

Alternative: Embed lifecycle state in the User model. Rejected because lifecycle is orthogonal to identity — a user may have multiple lifecycle episodes (free → paid → churned → re-activated). Identity does not need to know about onboarding progress.

### Approach: Single state machine vs parallel state machines (user + billing)

Chosen: Single user lifecycle state machine. Billing has its own state machine (see ADR-0015). The two interact through events: when Billing transitions to SUBSCRIPTION_ACTIVE, it emits an event that Lifecycle consumes to advance the user state.

Alternative: One combined state machine. Rejected because billing state (ACTIVE, PAST_DUE, SUSPENDED) is independent of onboarding state and must be managed by the Billing Platform.

---

## Future Considerations

### Self-serve plan changes

When a user changes plans mid-cycle, the lifecycle state machine does not regress. The user remains ACTIVE (or ONBOARDING_COMPLETE) with updated capabilities. Plan changes are handled by the Capability & Commercial Access system (see ADR-0016).

### Downgrade handling

A downgrade from a paid plan to Free may cause capability loss but does not change lifecycle state. The user remains ACTIVE. Feature-gating is handled by AccessPolicy (see ADR-0016).

### Re-activation (win-back)

A previously churned user who re-subscribes should not repeat the full onboarding flow. The lifecycle state machine can detect they previously reached ACTIVE and fast-forward to ACTIVE after authentication.

### Multi-org users

A user who belongs to multiple Organizations has one lifecycle per membership. For most users (single org), this is transparent. For multi-org users, the frontend selects which organization context to load, and the backend returns lifecycle state scoped to that organization.

### Offboarding

Account deletion, data export, and permanent deactivation are outside the scope of the lifecycle state machine. They are handled by Identity Platform (account deletion) and Billing Platform (subscription cancellation).

---

## References

- ADR-0011 — Identity Platform (user identity, organization creation)
- ADR-0012 — Authentication Flows (email signup, OAuth authentication)
- ADR-0013 — Security Architecture (rate limiting auth endpoints during onboarding)
- ADR-0015 — Billing Platform (subscription state machine, checkout, webhooks)
- ADR-0016 — Capability & Commercial Access (plan-based feature gating post-activation)
