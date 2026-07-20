# ADR-0016 — Capability & Commercial Access

## Metadata

| Field | Value |
|---|---|
| **Version** | v1.0 |
| **Date** | 2026-07-20 |
| **Status** | **DRAFT** |

---

## Decision

A Capability & Commercial Access Platform is established as the centralized decision engine for all plan-based feature gating.

Access control is capability-based, not plan-name-based. Business logic asks "does this context have capability X?" rather than "is this user on the Pro plan?".

The Capability Platform consumes subscription status from the Billing Platform (ADR-0015) and produces an `AccessPolicy` that every platform queries before exposing features or executing actions.

This ADR is NOT about RBAC. Role-based access control (who can do what within an organization) is owned by the Security Platform (ADR-0013). This ADR governs commercial access — what capabilities a subscription unlocks.

---

## Rationale

Hardcoded plan checks create several problems:

- `if plan == "pro"` logic scattered across every platform
- Plan renames or restructuring requires touching every check
- Enterprise overrides require special-casing everywhere
- Trial and promotional access require temporary hacks
- Beta features require ad-hoc feature flag systems
- No audit trail for why a feature was available or denied

A centralized Capability Platform with a capability-based access model solves these problems by providing a single `AccessPolicy.has_capability()` function that any platform can call. Plan definitions become data, not code.

---

## Core Concepts

### Capability

A named, boolean feature that a platform or user action depends on. Capabilities are the atomic unit of commercial access.

Examples:

```
capabilities/discovery/use
capabilities/discovery/credits
capabilities/campaign/active-limit
capabilities/automation/use
capabilities/automation/builder
capabilities/crm/integrations
capabilities/team/seats
capabilities/team/roles
capabilities/api/access
capabilities/enterprise/sso
capabilities/enterprise/audit-log
capabilities/beta/ai-personalization-v2
```

### CapabilityDefinition

```
CapabilityDefinition {
    id: CapabilityId
    name: str
    description: str
    category: CapabilityCategory      // discovery, campaign, automation, team, enterprise, beta, admin
    type: CapabilityType              // boolean (has it or not), limit (numeric quota), rate (per-time quota)
    default_value: Any                // default for plans that don't explicitly define it
    is_beta: bool
    requires_override: bool           // true if only enterprise override or admin grant can enable it
}
```

### PlanDefinition

```
PlanDefinition {
    id: PlanId                        // "free", "starter", "growth", "scale", "enterprise"
    name: str
    capabilities: Dict[CapabilityId, CapabilityValue]
    seat_limit: int | null
    workspace_limit: int | null
    sort_order: int
    metadata: Dict
}
```

### CapabilityValue

The value assigned to a capability for a given plan.

Union type: `bool | int | RateLimit | Dict`.

```
CapabilityValue = bool                // feature on/off
                 | int                // numeric limit (e.g., 5 active campaigns)
                 | RateLimit          // per-time quota (e.g., 1000 requests/hour)
                 | Dict               // structured config (e.g., {"max_seats": 5, "allowed_roles": ["admin", "member"]})
```

---

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│              Capability & Commercial Access Platform        │
│                                                            │
│  ┌────────────────────┐   ┌──────────────────────────────┐ │
│  │   SubscriptionContext │   │      PlanRepository        │ │
│  │   (per-org cache)    │   │  (plan → capability map)    │ │
│  └─────────┬──────────┘   └──────────┬───────────────────┘ │
│            │                         │                     │
│  ┌─────────▼─────────────────────────▼───────────────────┐ │
│  │                    AccessPolicy                        │ │
│  │  has_capability(capability_id) → bool                  │ │
│  │  get_limit(capability_id) → int | None                 │ │
│  │  get_rate_limit(capability_id) → RateLimit | None      │ │
│  └────────────────────┬──────────────────────────────────┘ │
│                       │                                    │
│  ┌────────────────────▼──────────────────────────────────┐ │
│  │                    OverrideService                     │ │
│  │  Enterprise overrides │ Beta grants │ Promotions      │ │
│  │  Admin grants         │ Grandfathering                │ │
│  └────────────────────┬──────────────────────────────────┘ │
│                       │                                    │
│  ┌────────────────────▼──────────────────────────────────┐ │
│  │  PolicyEvaluator (cached, fast-path)                   │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  Event handlers (subscribe to billing/lifecycle)      │ │
│  └──────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────┘
         │                        │
         │  reads                  │  consumes events from
         ▼                        ▼
┌─────────────────┐    ┌───────────────────┐
│  Billing Platform│    │  Onboarding Svc   │
│  (subscription)  │    │  (lifecycle)      │
└─────────────────┘    └───────────────────┘
```

---

## AccessPolicy

The `AccessPolicy` is the public interface of the Capability Platform. Every platform queries it instead of reading plan names.

```
AccessPolicy {
    // Boolean capabilities
    has_capability(capability_id: CapabilityId) -> bool

    // Numeric limits — returns None if unlimited
    get_limit(capability_id: CapabilityId) -> int | None

    // Rate limits — returns None if no rate limit
    get_rate_limit(capability_id: CapabilityId) -> RateLimit | None

    // Structured capability values
    get_capability_config(capability_id: CapabilityId) -> Dict | None

    // Bulk evaluation (single call for multiple checks)
    evaluate(requirements: Dict[CapabilityId, EvaluationType]) -> EvaluationResult
}

EvaluationType = {
    "type": "boolean" | "limit" | "rate"
    "required_value": Any              // what the caller needs
}

EvaluationResult = {
    "allowed": bool
    "checks": Dict[CapabilityId, CheckResult]
    "denied_reasons": List[str]
}

RateLimit {
    requests: int
    window_seconds: int
    burst: int | None
}
```

---

## Services

### PolicyService

Responsibility: Build `AccessPolicy` for a given org context.

```
PolicyService {
    get_policy(org_id) -> AccessPolicy
    get_policy_for_plan(plan_id) -> AccessPolicy  // for plan comparison UI
    has_capability(org_id, capability_id) -> bool
    get_limit(org_id, capability_id) -> int | None
    evaluate(org_id, requirements) -> EvaluationResult
}
```

### OverrideService

Responsibility: Manage temporary or permanent overrides to base plan capabilities.

```
OverrideService {
    // Enterprise overrides
    set_enterprise_override(org_id, capability_id, value) -> void
    remove_enterprise_override(org_id, capability_id) -> void
    get_overrides(org_id) -> Dict[CapabilityId, CapabilityValue]

    // Beta grants
    grant_beta_access(org_id, capability_id, expires_at) -> void
    revoke_beta_access(org_id, capability_id) -> void
    is_beta_active(org_id, capability_id) -> bool

    // Promotions / temporary unlocks
    grant_temporary_capability(org_id, capability_id, expires_at, reason) -> void

    // Admin grants
    admin_grant(org_id, capability_id, granted_by, reason) -> void

    // Grandfathering
    set_grandfathered_value(org_id, capability_id, value) -> void
    is_grandfathered(org_id, capability_id) -> bool
}
```

### PlanService

Responsibility: Manage plan definitions and capability mappings.

```
PlanService {
    get_plan(plan_id) -> PlanDefinition
    list_plans(include_hidden) -> List[PlanDefinition]
    get_plan_capabilities(plan_id) -> Dict[CapabilityId, CapabilityValue]
    compare_plans(plan_ids) -> Dict[PlanId, Dict[CapabilityId, CapabilityValue]]
    set_capability(plan_id, capability_id, value) -> void
    create_plan(plan_data) -> PlanDefinition
    deactivate_plan(plan_id) -> void
}
```

---

## Policy Evaluation Order

When `AccessPolicy.has_capability(org_id, capability_id)` is called, the evaluation follows this order:

1. **Admin override** — If an admin has explicitly granted or denied this capability for this org, return that value immediately. Used for support escalations and emergency access.
2. **Enterprise override** — If the org has an enterprise override for this capability, return the override value. Enterprise overrides are configured per-org during onboarding.
3. **Grandfathered value** — If the org was on a previous plan version that granted them a permanent value, return that value. Grandfathering persists across plan changes.
4. **Promotional / temporary grant** — If a promotion or temporary unlock is active for this capability, return the grant value.
5. **Beta grant** — If the capability is beta and this org has beta access, return the beta value (typically true).
6. **Base plan capability** — Return the capability value defined for the org's current plan.
7. **Capability default** — If the capability is not defined for any plan, return the capability's `default_value`.

This order ensures that overrides always take precedence over plan defaults without requiring plan modification.

---

## Plan Definitions

Plans are defined as data, loaded at startup and cached. The canonical source is the Billing Platform's `Plan` table, enriched with capability mappings stored in the Capability Platform.

### Free plan capability map (example)

```
"free": {
    "capabilities": {
        "discovery/use": true,
        "discovery/credits": 50,              // 50 credits per month
        "campaign/use": true,
        "campaign/active-limit": 1,           // 1 active campaign
        "campaign/sequence-steps": 10,        // max 10 steps per sequence
        "campaign/contacts-per-campaign": 100,
        "knowledge-base/use": true,
        "knowledge-base/storage-mb": 50,
        "ai/live-research": false,
        "automation/use": false,
        "automation/builder": false,
        "crm/integrations": false,
        "team/seats": 1,
        "team/multi-user": false,
        "api/access": false,
        "enterprise/sso": false,
        "enterprise/audit-log": false,
        "support/type": "community",
    },
    "seat_limit": 1,
}
```

### Enterprise plan capability map (example)

```
"enterprise": {
    "capabilities": {
        "discovery/use": true,
        "discovery/credits": 50000,
        "campaign/use": true,
        "campaign/active-limit": null,         // unlimited
        "campaign/sequence-steps": null,
        "campaign/contacts-per-campaign": null,
        "knowledge-base/use": true,
        "knowledge-base/storage-mb": 10000,
        "ai/live-research": true,
        "automation/use": true,
        "automation/builder": true,
        "crm/integrations": true,
        "team/seats": null,                    // unlimited
        "team/multi-user": true,
        "api/access": true,
        "enterprise/sso": true,
        "enterprise/audit-log": true,
        "support/type": "dedicated",
    },
    "seat_limit": null,
}
```

---

## Consumption Pattern

### How a platform checks capability

```
// Inside CampaignService.create_campaign()

from services.access import get_policy_service

policy = get_policy_service().get_policy(org_id)

if not policy.has_capability("campaign/use"):
    raise CapabilityRequiredError("campaign/use")

active_count = await campaign_repo.count_active(org_id)
limit = policy.get_limit("campaign/active-limit")

if limit is not None and active_count >= limit:
    raise LimitExceededError("campaign/active-limit", limit)
```

### How the frontend checks capability

```
// React component

const { data: policy } = useQuery({
    queryKey: ["access-policy", orgId],
    queryFn: () => api.get(`/access/policy`),
});

if (!policy.has_capability("automation/builder")) {
    return <UpgradePrompt plan="growth" feature="Automation Builder" />;
}
```

### How the API enforces capability

```
// FastAPI dependency

from services.access import get_policy_service

async def require_capability(capability_id: str):
    policy = get_policy_service().get_policy(org_id)
    if not policy.has_capability(capability_id):
        raise HTTPException(status_code=403, detail=f"Capability required: {capability_id}")
```

---

## Events

| Event | Trigger | Payload |
|---|---|---|
| `access.policy.invalidated` | Capability definitions changed | affected_org_ids (empty = all) |
| `access.override.created` | Enterprise override applied | org_id, capability_id, value, granted_by |
| `access.override.removed` | Enterprise override removed | org_id, capability_id |
| `access.beta.granted` | Beta access granted | org_id, capability_id, expires_at |
| `access.beta.expired` | Beta access expired | org_id, capability_id |
| `access.promotion.activated` | Temporary unlock activated | org_id, capability_id, expires_at, reason |
| `access.grandfather.recorded` | Grandfathered value saved | org_id, capability_id, value |
| `access.capability.denied` | Capability check failed (logged) | org_id, user_id, capability_id, action |

---

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/access/policy` | Get full access policy for current org |
| POST | `/access/check` | Check specific capability (bulk) |
| GET | `/access/plans` | List all plans with capability maps (for pricing page) |
| GET | `/access/plans/{id}/capabilities` | Get capability map for a specific plan |
| POST | `/admin/access/override` | Set enterprise override (admin only) |
| DELETE | `/admin/access/override/{org_id}/{capability_id}` | Remove override (admin only) |
| POST | `/admin/access/beta` | Grant beta access (admin only) |
| POST | `/admin/access/grandfather` | Set grandfathered value (admin only) |
| GET | `/admin/access/audit` | List capability check failures (admin only) |

---

## Event-driven Cache Invalidation

The `AccessPolicy` is cached per org. Cache is invalidated when:

1. Subscription status changes (Billing Platform emits `billing.subscription.*` event)
2. Plan changes (admin modifies plan capabilities)
3. Override changes (admin adds/removes overrides)
4. Beta grant changes
5. Promotion expires
6. Grandfathered value changes

The Capability Platform subscribes to all relevant events and invalidates the cache for affected orgs. Cache is lazily rebuilt on the next `get_policy()` call.

---

## Platform Interaction Boundaries

### Capability Platform owns

- Capability definitions (what capabilities exist)
- Plan → capability mappings (what each plan unlocks)
- Override management (enterprise, beta, promotion, admin, grandfathering)
- Policy evaluation (has_capability, get_limit, evaluate)
- Access policy caching and invalidation
- Capability check audit logging

### Capability Platform does NOT own

- Subscription state machine (Billing Platform — ADR-0015)
- Plan pricing or billing provider configuration (Billing Platform)
- User roles or role-based authorization (Security Platform — ADR-0013)
- User identity or organization membership (Identity Platform — ADR-0011)
- Onboarding lifecycle (Onboarding Platform — ADR-0014)
- Any business logic beyond access evaluation

### Interaction rules

| Interaction | Owner | Consumer | Mechanism |
|---|---|---|---|
| Subscription status | Billing Platform | Capability Platform | Event: `billing.subscription.*` → cache invalidation |
| Plan definition | Billing Platform | Capability Platform | Plan ID shared. Capability Platform stores capability mappings keyed by Plan ID. |
| Capability check | Any platform | Capability Platform | `PolicyService.get_policy(org_id).has_capability(id)` |
| Admin override | Capability Platform | — | `OverrideService` API (admin-only) |
| Feature-flag UI | Frontend | Capability Platform | `GET /access/policy` returns full policy for rendering decisions |
| Usage limit | Capability Platform | Business logic | `get_limit(id)` returns numeric cap. Business logic enforces. |

---

## Extension Points

| Extension Point | Mechanism |
|---|---|
| New capability | Add `CapabilityId` enum member, define `CapabilityDefinition`, add value to each plan's capability map |
| New plan | Add `PlanDefinition` with full capability map. No code changes to consumers. |
| Usage-based capability | `CapabilityType.rate` with `RateLimit` value. Metered usage decrements available count. |
| AI credit capability | Future `capability/ai/credits` with numeric limit. Deducted per AI operation. |
| Promotional upgrade | `OverrideService.grant_temporary_capability()` with expiry. No plan changes needed. |
| Enterprise trial | `OverrideService.grant_temporary_capability()` for enterprise-only capabilities during evaluation. |
| Plan comparison page | `PlanService.compare_plans()` returns full capability diff. Frontend renders comparison table. |
| Feature announcement | When a new capability is launched, `is_beta: true` is set. Select orgs granted beta via `OverrideService`. |
| Marketplace purchases | External capability grants (e.g., bought via AppSumo) create `OverrideService` entries keyed by license. |

---

## Tradeoffs

### Approach: Capability-based model vs plan-name checks

Chosen: Capability-based access model. Business logic queries `has_capability("discovery/use")` rather than `if plan == "pro"`.

Alternative: Plan-name checks scattered throughout code. Rejected because plan restructuring requires editing every check, enterprise overrides require special-casing in every location, and the system cannot distinguish between "cannot use discovery because of plan" vs "cannot use discovery because of trial expiry" vs "cannot use discovery because of credit exhaustion".

### Approach: Cached policy vs live evaluation

Chosen: Cached `AccessPolicy` per org, invalidated on relevant events.

Alternative: Read subscription + plan + overrides from the database on every check. Rejected because capability checks are on the hot path — a single page load may check 20+ capabilities. Database reads for each check would add unacceptable latency.

### Approach: Unified capability store vs per-platform capability logic

Chosen: Unified Capability Platform with central capability definitions. All platforms query the same policy.

Alternative: Each platform defines its own capabilities and checks. Rejected because it creates inconsistent access rules, duplicate override logic, and no single view of what capabilities a customer has.

### Approach: Plan definitions as data vs plan definitions as code

Chosen: Plan definitions stored as data in the capability repository, loaded at startup.

Alternative: Hardcoded plan definitions in Python. Rejected because changing plan capability mappings requires code deployment. Data-driven plans allow product teams to update plan structures without engineering involvement.

---

## Future Considerations

### Usage-based credit exhaustion

When a usage-based capability (e.g., `discovery/credits`) reaches zero, the capability evaluation returns `has_capability = false` for that specific capability without affecting other capabilities. The user is prompted to purchase more credits or upgrade.

### Per-seat capability gating

Team plans with seat-based billing need per-user capability evaluation within the same org. Future `UserAccessPolicy` extends `AccessPolicy` with per-user seat allocation. A user without an allocated seat cannot access team features even if the org has the capability.

### Self-serve plan upgrades

When a user upgrades via the billing portal, the Capability Platform receives a `billing.subscription.plan_changed` event, invalidates the cache, and the next policy evaluation returns capabilities for the new plan immediately.

### Metered feature enforcement

Future metered capabilities (e.g., `ai/generations/month`) integrate with a Usage Platform that decrements the allowance. When the allowance reaches zero, the capability check returns `false` until the next billing period or until a top-up is purchased.

### AI-based capability recommendations

The Capability Platform could analyze which capabilities a customer uses and recommend plan upgrades based on usage patterns. This is a product-level feature that consumes capability check data but does not require architectural changes.

---

## References

- ADR-0011 — Identity Platform (org context, identity boundaries)
- ADR-0013 — Security Architecture (RBAC is not capability gating — they are separate systems)
- ADR-0014 — User Lifecycle & Onboarding (trial vs active capability evaluation)
- ADR-0015 — Billing Platform (subscription state consumed by Capability Platform)
