# Loqi Financial Simulator

**Version:** 1.0
**Status:** FINAL — Specification
**Owner:** Platform Team
**Freeze Date:** 2026-07-19

---

## Document Structure

This document has three layers:

1. **Specification** — the financial model's architecture, calculation rules, and configuration schema. This is permanent.
2. **Example Configuration** — plausible defaults illustrating how the model works. These change when pricing, providers, or cost structures change.
3. **Business Decisions** — current public pricing and founding pricing. The only values frozen in this document.

Every section below that mentions a specific number, provider, or cost is annotated with its status:

| Badge | Meaning |
|---|---|
| `BUSINESS DECISION` | Actual Loqi pricing. Frozen until changed by leadership. |
| `PLACEHOLDER DEFAULT` | Estimated or example value. Must come from configuration, not the document. |
| `EXAMPLE` | Illustrative calculation. Values chosen for clarity, not accuracy. |
| `CONFIGURABLE` | Describes a configuration parameter. No value implied. |

---

## 1. Purpose

The Financial Simulator is Loqi's internal financial model. It exists to answer one question at every level of the business:

> Given our current pricing, provider costs, infrastructure, and customer behavior, are we building a sustainable business?

Concretely, the simulator answers:

| Question | Why it matters |
|---|---|
| Are we profitable at each plan tier? | Determines which plans need repricing |
| What is gross margin per customer? | Measures unit economics health |
| What happens if a Discovery provider doubles pricing? | Quantifies provider dependency risk |
| How many Discovery Credits should each plan include? | Balances usage vs. margin |
| How much AI can we afford per customer under fair use? | Sets AI rate limits |
| What profit do we make per customer per month? | Drives CAC ceiling |
| When should customers upgrade? | Identifies natural growth triggers |
| How do pricing changes affect profitability? | Models before committing |
| How much runway do we have? | Determines hiring and spend decisions |
| What is the probability of negative margin this quarter? | Quantifies financial risk |

The simulator is deliberately provider-agnostic and infrastructure-agnostic. It does not hardcode any provider name, AI model, or cloud vendor. Every cost axis is configurable so the model survives as Loqi's stack evolves.

The simulator may be implemented as:

- A Google Sheet / Excel workbook
- An internal admin dashboard (web)
- A Python financial modeling service
- All three, driven by a shared config file

This document is the specification. Any implementation must derive from it.

---

## Core Principles

The Financial Simulator follows these principles. They are the lens through which all future changes must be judged.

1. **Configuration over hardcoded values.** Every number that can change should be a config parameter. Nothing is constant except the calculation rules.

2. **Examples are illustrative, not business decisions.** Example tables throughout this document demonstrate how calculations work. They are not commitments to specific margins, allocations, or cost structures.

3. **Business decisions belong in configuration, not documentation.** Pricing, allocations, and thresholds are configuration values. The document describes the calculation structure; the config file holds the decisions.

4. **Every calculation must be reproducible.** Given the same configuration and inputs, any implementation (spreadsheet, Python, dashboard) must produce identical outputs.

5. **Every assumption must be measurable.** If an assumption cannot be validated against real data, it should be flagged as `UNVALIDATED` until telemetry exists.

6. **Every estimate should eventually be replaced by telemetry.** The simulator starts with placeholder defaults. Over time, real usage data should replace every estimated value.

7. **The simulator must remain provider-agnostic.** Discovery costs model *actions* and *cost per action*, not vendor names. AI costs model *token consumption* and *provider groups*, not model names. Adding or swapping providers should never require engine changes.

8. **The simulator must remain infrastructure-agnostic.** Infrastructure costs are modeled by function (monitoring, database, cache) not vendor. Changing cloud providers should only change config values.

9. **The simulator should optimize for long-term sustainability, not short-term growth.** The goal is 80%+ gross margins, healthy unit economics, and prudent cash management. Growth is a means, not the metric.

10. **Documentation should change rarely. Configuration should change frequently.** This document should undergo structural changes only when the financial model itself changes. Pricing updates, provider switches, and cost adjustments are configuration changes, not document changes.

---

## 2. Configurable Inputs

All inputs are organized into categories. The specification describes what exists, not what today's value is.

Every parameter below is `CONFIGURABLE` unless marked `BUSINESS DECISION`.

### 2.1 Configuration Schema

The simulator reads a single configuration object. The shape is:

```
config
├── currency           # ISO 4217 code, display symbol
├── plans[]            # Array of plan definitions
│   ├── name           # Unique plan identifier
│   ├── standard_price # BUSINESS DECISION — current public pricing
│   ├── founding_price # BUSINESS DECISION — founding member pricing
│   ├── founding_locked# Whether founding price is locked for life
│   ├── enterprise     # Boolean, custom pricing flag
│   └── allocations    # Plan-level limits (credits, tokens, campaigns, seats, etc.)
├── discovery
│   ├── actions[]      # Each action: name, credits_consumed, provider, provider_action
│   ├── rollover_months
│   ├── empty_result_credit_refund  # Boolean: zero cost for empty results
│   ├── cache_hit_credit_refund     # Boolean: zero cost for cache hits
│   ├── top_up
│   │   ├── price_per_unit
│   │   └── unit_size
│   └── auto_refill
│       ├── threshold
│       └── amount
├── providers[]
│   ├── name
│   ├── category       # "discovery", "ai", "infrastructure"
│   └── actions[]      # Each: name, cost_per_action, unit (e.g., "per_lookup", "per_1k_tokens")
├── ai
│   ├── provider_groups[]  # Named provider groups, each with provider list
│   ├── default_provider_group
│   └── usage_profile
│       ├── average_input_tokens
│       ├── average_output_tokens
│       ├── conversation_turns
│       ├── retry_rate
│       ├── context_growth_per_turn
│       └── rate_limits (per_minute, burst)
├── infrastructure
│   ├── fixed[]        # Each: name, monthly_cost, category
│   └── variable[]     # Each: name, cost_per_customer, cost_per_unit, unit_name, category
├── payment
│   ├── processor (string)
│   ├── card_fee_percent
│   ├── card_fee_fixed
│   ├── invoice_fee_percent
│   ├── chargeback_rate
│   └── chargeback_fee
├── taxes
│   ├── vat_enabled, vat_rate
│   ├── sales_tax_enabled, sales_tax_rate
│   └── other_taxes[]  # Extensible list
├── profiles[]          # Customer usage profiles
│   ├── name
│   └── metrics         # All usage dimensions (lookups, AI prompts, storage, etc.)
├── plan_profile_mapping[]  # Each: plan, expected_profile, upgrade_trigger_profile
├── fixed_costs[]       # Non-infrastructure fixed costs (payroll, office, software, legal)
│   ├── category        # "payroll", "office", "software", "legal", "other"
│   ├── items[]         # Each: name, monthly_cost, count
│   └── burden_rate     # Payroll burden multiplier (e.g., 1.15 for 15% burden)
└── kpi_targets
    ├── gross_margin_healthy, gross_margin_watch, gross_margin_critical
    ├── net_margin_healthy, net_margin_watch, net_margin_critical
    ├── arpu_healthy, arpu_watch, arpu_critical
    └── ... (all KPI thresholds)
```

### 2.2 Public Pricing

`BUSINESS DECISION` — These values may only be changed by leadership.

| Plan | Monthly Price (USD) | Founding Price (USD) | Notes |
|---|---|---|---|
| Free | $0 | — | Always free |
| Starter | $49 | $39 | Founding: lifetime locked |
| Growth | $149 | $119 | Founding: lifetime locked |
| Scale | $299 | $239 | Founding: lifetime locked |
| Enterprise | Custom | — | Negotiated annually |

### 2.3 Plan Allocations

`PLACEHOLDER DEFAULT` — Example allocation values. These are the first configurable assumptions to validate with real usage.

| Parameter | Free | Starter | Growth | Scale | Unit |
|---|---|---|---|---|---|
| `discovery_credits_monthly` | 0 | 500 | 2,000 | 6,000 | credits/mo |
| `discovery_credits_rollover` | 0 | 500 | 2,000 | 6,000 | max rollover credits |
| `ai_tokens_monthly` | 0 | 500K | 2M | 10M | tokens/mo |
| `campaigns_active` | 0 | 5 | 20 | 100 | concurrent campaigns |
| `contacts_per_campaign` | 5 | 500 | 2,000 | 10,000 | max contacts |
| `seats` | 1 | 1 | 3 | 10 | team seats |
| `storage_gb` | 0.1 | 1 | 5 | 25 | GB |
| `automation_nodes` | 0 | 10 | 50 | 200 | workflow nodes |

### 2.4 Discovery Credits

`PLACEHOLDER DEFAULT` — Credit costs per action should be derived from provider pricing, not set independently.

| Parameter | Example Value | Description |
|---|---|---|
| `credits_per_person_lookup` | 1 | Credit cost for a person data lookup |
| `credits_per_company_lookup` | 1 | Credit cost for a company data lookup |
| `credits_per_email_find` | 2 | Credit cost for an email address find |
| `credits_per_email_verify` | 1 | Credit cost for an email verification |
| `credits_per_cache_hit` | 0 | Cache hits consume zero credits |
| `credits_per_empty_result` | 0 | Empty results consume zero credits |
| `rollover_months` | 1 | Credits roll over for N billing cycles |
| `top_up_price_per_1000` | $5 | Price per 1,000 additional credits |
| `auto_refill_threshold` | 100 | Auto-refill when credits fall below this |
| `auto_refill_amount` | 500 | Credits to auto-refill |

### 2.5 Provider Pricing

`PLACEHOLDER DEFAULT` — Provider costs are per-action. All provider names are examples only.

| Provider Category | Action | Cost per Action (USD) | Notes |
|---|---|---|---|
| Person Data | Person lookup | $0.005 | Example: current PDL pricing |
| Person Data | Company lookup | $0.005 | Example: current PDL pricing |
| Email Discovery | Email find | $0.01 | Example: current Hunter pricing |
| Email Discovery | Email verify | $0.001 | Example: current Hunter pricing |
| Cache | Cache hit | $0.00 | Saved by prior lookup |

**Provider cost structure (CONFIGURABLE):**

```
providers:
  - name: "Person Data Provider"
    category: discovery
    actions:
      - name: person_lookup
        cost_per_action: 0.005
        unit: per_lookup
      - name: company_lookup
        cost_per_action: 0.005
        unit: per_lookup
  - name: "Email Discovery Provider"
    category: discovery
    actions:
      - name: email_find
        cost_per_action: 0.01
        unit: per_lookup
      - name: email_verify
        cost_per_action: 0.001
        unit: per_lookup
```

New providers are added as new entries in the array. No simulator engine changes are required.

### 2.6 AI Pricing

`PLACEHOLDER DEFAULT` — AI costs are multi-provider and token-based. Provider names and model names are examples only.

| Parameter | Example Value | Description |
|---|---|---|
| Primary AI provider category | "fast_reasoning" | Logical category, not vendor name |
| Primary — input token cost (per 1K) | $0.0025 | Example: current GPT-4o pricing |
| Primary — output token cost (per 1K) | $0.01 | Example: current GPT-4o pricing |
| Secondary AI provider category | "deep_reasoning" | For fallback / complex tasks |
| Secondary — input token cost (per 1K) | $0.003 | Example: current Claude 3.5 pricing |
| Secondary — output token cost (per 1K) | $0.015 | Example: current Claude 3.5 pricing |
| Average input tokens per prompt | 2,000 | System prompt + context |
| Average output tokens per response | 500 | Generated content |
| Average conversation turns | 3 | Per research session |
| Live research calls per campaign/day | 2 | Per-contact research |
| Workspace intelligence syncs/month | 50 | Knowledge base updates |
| Retry rate | 5% | Percentage of calls that retry |
| Context growth per turn | 30% | Each turn adds ~30% more tokens |

**AI provider structure (CONFIGURABLE):**

```
ai:
  provider_groups:
    - name: fast_reasoning
      description: "Primary AI provider for most tasks"
      providers:
        - name: "Provider A"
          model: "Model X"
          input_cost_per_1k: 0.0025
          output_cost_per_1k: 0.01
    - name: deep_reasoning
      description: "Fallback for complex reasoning tasks"
      providers:
        - name: "Provider B"
          model: "Model Y"
          input_cost_per_1k: 0.003
          output_cost_per_1k: 0.015
    - name: cheap_bulk
      description: "High-volume, lower-quality tasks"
      providers:
        - name: "Provider A"
          model: "Model Z"
          input_cost_per_1k: 0.00015
          output_cost_per_1k: 0.0006
  default_provider_group: fast_reasoning
  task_provider_mapping:
    live_research: fast_reasoning
    campaign_generation: cheap_bulk
    workspace_intelligence: deep_reasoning
```

### 2.7 Infrastructure Pricing

`CONFIGURABLE` — Infrastructure costs are split by category, not vendor. Vendor names in notes only.

| Category | Item | Cost Category | Scale Unit |
|---|---|---|---|
| Monitoring | Monitoring system (vendor-agnostic) | Fixed: $X/mo | Per business |
| Logging | Logging pipeline (vendor-agnostic) | Fixed: $Y/mo | Per business |
| Network | DNS + CDN (vendor-agnostic) | Fixed: $Z/mo | Per business |
| CI/CD | Build system (vendor-agnostic) | Fixed: $W/mo | Per business |
| Security | Security scanning (vendor-agnostic) | Fixed: $V/mo | Per business |
| Incident | Incident management (vendor-agnostic) | Fixed: $U/mo | Per business |
| Database | Relational database (vendor-agnostic) | Variable: $A/customer | Per customer |
| Storage | Object storage (vendor-agnostic) | Variable: $B/GB | Per GB stored |
| Cache | In-memory cache (vendor-agnostic) | Variable: $C/customer | Per customer |
| Queue | Message queue (vendor-agnostic) | Variable: $D/customer | Per customer |
| Compute | Background workers (vendor-agnostic) | Variable: $E/customer | Per customer |
| Search | Full-text search (vendor-agnostic) | Variable: $F/customer | Per customer |
| Bandwidth | Outbound bandwidth (vendor-agnostic) | Variable: $G/1K | Per 1,000 emails |

**Infrastructure structure (CONFIGURABLE):**

```
infrastructure:
  fixed:
    - name: monitoring
      category: observability
      monthly_cost: 500
    - name: logging
      category: observability
      monthly_cost: 300
    - name: dns_cdn
      category: network
      monthly_cost: 200
    # ...add or remove items freely
  variable:
    - name: database
      category: storage
      cost_per_customer: 0.50
      cost_per_unit: null
      unit_name: null
    - name: object_storage
      category: storage
      cost_per_customer: null
      cost_per_unit: 0.02
      unit_name: per_gb
    - name: bandwidth
      category: network
      cost_per_customer: null
      cost_per_unit: 0.01
      unit_name: per_1000_emails
    # ...add or remove items freely
```

### 2.8 Payment Processing

`CONFIGURABLE` — Default values shown are industry-standard estimates.

| Parameter | Example Default | Notes |
|---|---|---|
| `payment_processor` | "Stripe" | Configurable string |
| `card_fee_percent` | 2.9% | Card transaction fee |
| `card_fee_fixed` | $0.30 | Per transaction |
| `invoice_fee_percent` | 1.5% | ACH/wire fee |
| `chargeback_rate` | 0.5% | Percentage of transactions |
| `chargeback_fee` | $15 | Per chargeback |

### 2.9 Taxes (Optional)

`CONFIGURABLE` — All tax parameters are optional and default to disabled.

| Parameter | Example Default | Notes |
|---|---|---|
| `vat_enabled` | false | Toggle EU VAT |
| `vat_rate` | 20% | Configurable percentage |
| `sales_tax_enabled` | false | Toggle US sales tax |
| `sales_tax_rate` | 0% | Configurable by state |

### 2.10 Currency

`CONFIGURABLE`

| Parameter | Example Default | Notes |
|---|---|---|
| `currency` | USD | ISO 4217 |
| `currency_symbol` | $ | Display |

---

## 3. Customer Usage Profiles

Customer usage determines variable costs. The simulator defines profiles representing realistic behavior at each plan level.

Profiles are `CONFIGURABLE` — the values shown below are `PLACEHOLDER DEFAULT` until validated against real telemetry.

### 3.1 Profile Definitions

| Metric | Light | Typical | Heavy | Power User | Abuse |
|---|---|---|---|---|---|
| **Discovery lookups/month** | 100 | 1,500 | 5,000 | 15,000 | 100,000 |
| **Cache hit rate** | 30% | 40% | 50% | 60% | 20% |
| **Email finds/month** | 50 | 500 | 2,000 | 5,000 | 50,000 |
| **Email verifies/month** | 40 | 400 | 1,500 | 4,000 | 40,000 |
| **AI prompts/month** | 100 | 1,000 | 5,000 | 15,000 | 100,000 |
| **AI conversation turns/prompt** | 2 | 3 | 4 | 5 | 10 |
| **Campaigns active** | 1 | 5 | 20 | 50 | 200 |
| **Contacts per campaign** | 50 | 500 | 2,000 | 5,000 | 10,000 |
| **Automation nodes** | 3 | 20 | 80 | 200 | 500 |
| **Storage (GB)** | 0.2 | 1 | 5 | 15 | 50 |
| **Emails sent/month** | 500 | 5,000 | 25,000 | 75,000 | 500,000 |
| **Confidence** | `LOW` | `LOW` | `LOW` | `UNVALIDATED` | `UNVALIDATED` |

**Profile as configuration:**

```
profiles:
  - name: light
    confidence: low
    metrics:
      discovery_lookups_per_month: 100
      cache_hit_rate: 0.30
      email_finds_per_month: 50
      email_verifies_per_month: 40
      ai_prompts_per_month: 100
      ai_conversation_turns: 2
      campaigns_active: 1
      contacts_per_campaign: 50
      automation_nodes: 3
      storage_gb: 0.2
      emails_sent_per_month: 500
  - name: typical
    confidence: low
    metrics:
      discovery_lookups_per_month: 1500
      # ...
  # Additional profiles follow the same structure
```

### 3.2 Plan-to-Profile Mapping

`CONFIGURABLE` — These mappings determine which margin calculations are most relevant.

| Plan | Expected Profile | Upgrade Trigger |
|---|---|---|
| Free | Light | Light (hard-limited) |
| Starter | Light–Typical | Typical |
| Growth | Typical–Heavy | Heavy |
| Scale | Heavy–Power User | Power User |
| Enterprise | Power User+ | Custom |

A Starter customer on a Heavy profile signals a need to upgrade.

**Mapping as configuration:**

```
plan_profile_mapping:
  - plan: free
    expected_profile: light
    upgrade_trigger: light
  - plan: starter
    expected_profile: light_typical
    upgrade_trigger: typical
  - plan: growth
    expected_profile: typical_heavy
    upgrade_trigger: heavy
  - plan: scale
    expected_profile: heavy_power_user
    upgrade_trigger: power_user
  - plan: enterprise
    expected_profile: power_user_plus
    upgrade_trigger: null
```

---

## 4. Revenue Model

`CONFIGURABLE` — Revenue flows through payment processing before reaching Loqi's bank account.

```
Gross Revenue (subscriptions)
    │
    ├── Payment processing fees (card_fee_percent + card_fee_fixed)
    ├── Chargeback costs (chargeback_rate × chargeback_fee)
    │
    ├── Discovery top-ups (additional credit purchases)
    │       │
    │       └── Payment processing fees apply
    │
    └── Net Revenue
```

### 4.1 Calculation

```
For each subscription:
  gross_mrr = resolve_plan_price(customer)
    # resolve_plan_price checks: enterprise custom → founding → standard

  processing_fee = gross_mrr × config.payment.card_fee_percent
                 + config.payment.card_fee_fixed
  chargeback_cost = gross_mrr × config.payment.chargeback_rate
                  × config.payment.chargeback_fee
  net_mrr = gross_mrr - processing_fee - chargeback_cost

For top-ups:
  top_up_revenue = credits_purchased × (top_up_price_per_unit / unit_size)
  top_up_fee = top_up_revenue × card_fee_percent + card_fee_fixed
  net_top_up = top_up_revenue - top_up_fee

Total net_mrr = Σ(net_mrr per customer) + Σ(net_top_up)

Annual:
  arr = net_mrr × 12
  gross_arr = Σ(gross_mrr per customer) × 12
```

### 4.2 Founding Member Discount

Founding member pricing reduces gross revenue. The simulator must track:

- How many customers are on founding pricing
- The discount magnitude per plan
- The expiration date of founding pricing (public launch)
- The total revenue impact of the founding program

---

## 5. Discovery Cost Model

Discovery costs are Loqi's largest variable cost after AI. The model is provider-agnostic — it operates on *actions* and *cost per action*, not vendor names.

### 5.1 Model Structure

```
discovery_cost_model:
  actions:
    - name: person_lookup
      provider_category: person_data
      credits_consumed: 1
    - name: company_lookup
      provider_category: person_data
      credits_consumed: 1
    - name: email_find
      provider_category: email_discovery
      credits_consumed: 2
    - name: email_verify
      provider_category: email_discovery
      credits_consumed: 1
  empty_result_credit_refund: true    # No cost for empty results
  cache_hit_credit_refund: true       # No cost for cache hits
  cache_hit_rate: 0.40                # PLACEHOLDER DEFAULT — Confidence: LOW
  empty_result_rate: 0.15             # PLACEHOLDER DEFAULT — Confidence: LOW
```

### 5.2 Customer-level Cost

```
For each customer:
  person_lookups  = profile.discovery_lookups_per_month × person_lookup_ratio
  company_lookups = profile.discovery_lookups_per_month × company_lookup_ratio
  email_finds     = profile.email_finds_per_month
  email_verifies  = profile.email_verifies_per_month

  cache_hits = (person_lookups + company_lookups + email_finds) × cache_hit_rate

  total_cost = 0
  for each action in customer_actions:
    action_cost = action_count × lookup_provider_cost(action)
    total_cost += action_cost

  credits_consumed = 0
  for each action in customer_actions:
    action_credits = action_count × action.credits_consumed
    credits_consumed += action_credits

  cache_savings = cache_hits × weighted_average_cost_per_lookup
```

### 5.3 Plan Allocation vs. Actual

| Scenario | Outcome |
|---|---|
| Consumed < Allocated | Healthy margin |
| Consumed ≈ Allocated | At capacity |
| Consumed > Allocated | Heavy user — upgrade prompt |
| Consumed > 2× Allocated | Needs intervention or rate limit |

### 5.4 Top-ups and Auto-refill

```
credits_shortfall = credits_consumed - (allocated_credits + rollover_credits)
top_up_revenue = (credits_shortfall / top_up_unit_size) × top_up_price_per_unit
auto_refill_triggered = remaining_credits <= auto_refill_threshold
```

---

## 6. AI Cost Model

AI costs are the second major variable cost. The model is provider-agnostic — it operates on *tokens*, *provider groups*, and *task routing*.

### 6.1 Provider Group Model

The simulator supports assigning different AI providers to different task categories:

```
task_provider_mapping:
  live_research: fast_reasoning          # e.g., GPT-4o class
  campaign_generation: cheap_bulk        # e.g., GPT-4o-mini class
  workspace_intelligence: deep_reasoning # e.g., Claude class
```

Each provider group has its own token pricing, allowing the simulator to model mixed-provider strategies.

### 6.2 Cost per Prompt

```
For each AI interaction:
  provider_group = task_provider_mapping[task_type]
  provider_cost  = resolve_provider_cost(provider_group)
    # Returns: input_cost_per_1k, output_cost_per_1k

  input_tokens  = config.ai.usage_profile.average_input_tokens
  output_tokens = config.ai.usage_profile.average_output_tokens

  For multi-turn conversations:
    total_input_tokens  = input_tokens × Σ(context_growth^(turn-1)) for each turn
    total_output_tokens = output_tokens × turns

    EXAMPLE (3 turns, 30% context growth):
      Turn 1: 2,000 input + 500 output
      Turn 2: 2,600 input + 500 output
      Turn 3: 3,380 input + 500 output
      Total:  7,980 input tokens + 1,500 output tokens

  cost = (total_input_tokens / 1000) × provider_cost.input_cost_per_1k
       + (total_output_tokens / 1000) × provider_cost.output_cost_per_1k

  With retries:
    cost = cost × (1 + retry_rate)
```

### 6.3 Customer-level AI Cost

```
For each customer:
  For each task type in [live_research, campaign_generation, workspace_intelligence]:
    prompts = calculate_prompts_for_task(task_type, profile)
    cost    = prompts × cost_per_prompt(task_type)

  Total AI cost = Σ(task_costs)
```

### 6.4 Fair Use Model

AI is not billed per-token. It is included in every paid plan under fair use.

`PLACEHOLDER DEFAULT` — Allocation values shown are initial estimates.

| Plan | AI Token Allocation (monthly) | Estimated Prompt Capacity |
|---|---|---|
| Starter | 500K tokens | ~200 multi-turn research sessions |
| Growth | 2M tokens | ~800 multi-turn research sessions |
| Scale | 10M tokens | ~4,000 multi-turn research sessions |

Beyond allocation: rate-limited, not blocked. Rate limiting prevents abuse without interrupting legitimate usage.

**Configurable parameters:**

- `plans[].allocations.ai_tokens_monthly` — monthly token limit
- `ai.rate_limit_per_minute` — max prompts/minute per customer
- `ai.rate_limit_burst` — burst window

---

## 7. Infrastructure Model

Infrastructure costs are the baseline operating cost of the platform. The model categorizes costs by function, not vendor.

### 7.1 Fixed Costs

`PLACEHOLDER DEFAULT` — Example values shown. All costs are `CONFIGURABLE`.

| Category | Item | Monthly Cost (EXAMPLE) |
|---|---|---|
| Observability | Monitoring | $500 |
| Observability | Logging | $300 |
| Network | DNS + CDN | $200 |
| CI/CD | Build system | $200 |
| Security | Vulnerability scanning | $300 |
| Incident | Incident management | $100 |
| **Total Fixed** | | **$1,600** |

### 7.2 Variable Costs

`PLACEHOLDER DEFAULT` — Example values shown. All costs are `CONFIGURABLE`.

| Category | Item | Cost Structure | Unit |
|---|---|---|---|
| Storage | Relational database | $0.50/customer | Per customer |
| Storage | Object storage | $0.02/GB | Per GB stored |
| Cache | In-memory cache | $0.10/customer | Per customer |
| Queue | Message queue | $0.05/customer | Per customer |
| Compute | Background workers | $0.30/customer | Per customer |
| Search | Full-text search | $0.15/customer | Per customer |
| Network | Outbound bandwidth | $0.01/1K | Per 1,000 emails |

**Variable cost per customer by profile (EXAMPLE, based on placeholder defaults):**

| Profile | Database | Storage | Cache | Queue | Compute | Search | Bandwidth | **Total** |
|---|---|---|---|---|---|---|---|---|
| Light | $0.50 | $0.004 | $0.10 | $0.05 | $0.30 | $0.15 | $0.005 | **$1.11** |
| Typical | $0.50 | $0.02 | $0.10 | $0.05 | $0.30 | $0.15 | $0.05 | **$1.17** |
| Heavy | $0.50 | $0.10 | $0.10 | $0.05 | $0.30 | $0.15 | $0.25 | **$1.45** |
| Power User | $0.50 | $0.30 | $0.10 | $0.05 | $0.30 | $0.15 | $0.75 | **$2.15** |

### 7.3 Scaling Model

```
fixed_infra = Σ(config.infrastructure.fixed[].monthly_cost)

variable_infra_per_customer = Σ(
  variable_item.cost_per_customer
  + (profile_usage × variable_item.cost_per_unit)
  for each variable_item
)

total_infra_cost = fixed_infra + (variable_infra_per_customer × customer_count)
infra_cost_per_customer = total_infra_cost / customer_count
```

---

## 8. Plan Profitability

For each plan tier, the simulator calculates per-customer profitability using the expected customer profile.

> **IMPORTANT**: All values in this section are `EXAMPLE` calculations based on `PLACEHOLDER DEFAULT` inputs. They illustrate the calculation structure, not actual Loqi margins. Real margins depend on current configuration.

### 8.1 Starter ($49/month)

`BUSINESS DECISION` price. Margins shown are EXAMPLE only.

| Line Item | Light (EXAMPLE) | Typical (EXAMPLE) |
|---|---|---|
| **Gross Revenue** | $49.00 | $49.00 |
| Payment fee | $1.72 | $1.72 |
| Chargeback cost | $0.04 | $0.04 |
| **Net Revenue** | **$47.24** | **$47.24** |
| Discovery cost | $0.45 | $6.75 |
| AI cost | $0.50 | $5.00 |
| Infrastructure (variable) | $1.11 | $1.17 |
| **Total Variable Cost** | **$2.06** | **$12.92** |
| **Gross Profit** | **$45.18** | **$34.32** |
| **Gross Margin** | **95.6%** | **72.7%** |

### 8.2 Growth ($149/month)

`BUSINESS DECISION` price. Margins shown are EXAMPLE only.

| Line Item | Typical (EXAMPLE) | Heavy (EXAMPLE) |
|---|---|---|
| **Gross Revenue** | $149.00 | $149.00 |
| Payment fee | $4.62 | $4.62 |
| Chargeback cost | $0.11 | $0.11 |
| **Net Revenue** | **$144.27** | **$144.27** |
| Discovery cost | $6.75 | $22.50 |
| AI cost | $5.00 | $25.00 |
| Infrastructure | $1.17 | $1.45 |
| **Total Variable Cost** | **$12.92** | **$48.95** |
| **Gross Profit** | **$131.35** | **$95.32** |
| **Gross Margin** | **91.3%** | **66.2%** |

### 8.3 Scale ($299/month)

`BUSINESS DECISION` price. Margins shown are EXAMPLE only.

| Line Item | Heavy (EXAMPLE) | Power User (EXAMPLE) |
|---|---|---|
| **Gross Revenue** | $299.00 | $299.00 |
| Payment fee | $8.97 | $8.97 |
| Chargeback cost | $0.22 | $0.22 |
| **Net Revenue** | **$289.81** | **$289.81** |
| Discovery cost | $22.50 | $67.50 |
| AI cost | $25.00 | $75.00 |
| Infrastructure | $1.45 | $2.15 |
| **Total Variable Cost** | **$48.95** | **$144.65** |
| **Gross Profit** | **$240.86** | **$145.16** |
| **Gross Margin** | **83.1%** | **50.1%** |

### 8.4 Enterprise (Custom)

Enterprise is quoted individually. The simulator should flag when a customer's usage exceeds Power User profile and calculate what price would be needed to maintain target gross margin.

### 8.5 Founding Member Impact

`EXAMPLE` — Founding member pricing reduces gross revenue by ~20% per plan. Actual impact depends on founding member ratio.

| Plan | Standard GM (EXAMPLE) | Founding GM (EXAMPLE) | Margin Erosion (EXAMPLE) |
|---|---|---|---|
| Starter | 72.7% | 66.1% | −6.6pp |
| Growth | 91.3% | 89.1% | −2.2pp |
| Scale | 83.1% | 78.9% | −4.2pp |

The simulator should track founding member count and project when they convert to standard pricing (after public launch).

---

## 9. Sensitivity Analysis

The simulator must allow instant recalculation when any input changes. The following scenarios illustrate the sensitivity structure.

> All values in this section are `EXAMPLE` only, based on `PLACEHOLDER DEFAULT` inputs.

### 9.1 Provider Pricing Changes

| Scenario | Discovery Cost Change | Margin Impact (EXAMPLE) |
|---|---|---|
| Person data provider +50% | +$3.38 | −2.4pp |
| Person data provider +100% | +$6.75 | −4.8pp |
| Email discovery +50% | +$3.75 | −2.6pp |
| Email discovery +100% | +$7.50 | −5.3pp |
| **Both double** | **+$14.25** | **−10.1pp** |

### 9.2 AI Pricing Changes

| Scenario | AI Cost Change | Margin Impact (EXAMPLE) |
|---|---|---|
| Primary AI 2× cheaper | −$2.50 | +1.8pp |
| Primary AI 2× more expensive | +$5.00 | −3.5pp |
| Switch to cheap bulk (10× cheaper) | −$4.50 | +3.2pp |
| Switch to deep reasoning (+20%) | +$1.00 | −0.7pp |

### 9.3 Infrastructure Scaling

| Customer Count | Fixed per Customer | Variable per Customer | Total per Customer (EXAMPLE) |
|---|---|---|---|
| 100 | $16.00 | $1.17 | $17.17 |
| 500 | $3.20 | $1.17 | $4.37 |
| 1,000 | $1.60 | $1.17 | $2.77 |
| 5,000 | $0.32 | $1.17 | $1.49 |
| 10,000 | $0.16 | $1.17 | $1.33 |

### 9.4 Cache Hit Rate Impact

| Cache Hit Rate | Discovery Cost (EXAMPLE) | Savings (EXAMPLE) |
|---|---|---|
| 0% | $33.75 | Baseline |
| 25% | $25.31 | $8.44 saved |
| 50% | $16.88 | $16.88 saved |
| 75% | $8.44 | $25.31 saved |

### 9.5 Pricing Changes

| Change | Impact on Net Revenue (EXAMPLE: 1K customers, 50/30/20 mix) |
|---|---|
| +10% all plans | +$14,550/mo |
| +$10 on Starter | +$5,000/mo |
| Founding 20% discount ends | +$8,000/mo (EXAMPLE: 40% on founding) |

---

## 10. Break-even Analysis

The break-even model is derived entirely from configuration. There are no hardcoded team assumptions.

### 10.1 Configurable Fixed Costs

Fixed costs are split into payroll and non-payroll categories. The simulator reads:

```
fixed_costs:
  payroll:
    burden_rate: 1.15
    roles:
      - title: "Engineer"
        count: 3
        monthly_salary: 10000
      - title: "Designer"
        count: 1
        monthly_salary: 8000
      - title: "Product Manager"
        count: 1
        monthly_salary: 9000
      # Add or remove roles freely
  non_payroll:
    - category: office
      items:
        - name: "Office space"
          monthly_cost: 2000
        - name: "Equipment"
          monthly_cost: 1000
    - category: software
      items:
        - name: "Tools & SaaS"
          monthly_cost: 1500
    - category: legal
      items:
        - name: "Legal & compliance"
          monthly_cost: 500
```

### 10.2 Calculation

```
total_payroll = Σ(role.count × role.monthly_salary) × burden_rate
total_non_payroll = Σ(non_payroll items)
total_infrastructure = Σ(infrastructure.fixed[].monthly_cost)
total_fixed = total_payroll + total_non_payroll + total_infrastructure

average_contribution_margin = average_net_revenue_per_customer
                            - average_variable_cost_per_customer

customers_to_break_even = ceil(total_fixed / average_contribution_margin)
mrr_at_break_even = total_fixed + (customers_to_break_even × average_variable_cost_per_customer)
arr_at_break_even = mrr_at_break_even × 12
```

### 10.3 Break-even Example

`EXAMPLE` — Based on `PLACEHOLDER DEFAULT` values shown in this document:

| Metric | Value |
|---|---|
| Total monthly fixed costs | $66,600 |
| Average revenue per customer (blended) | $120 |
| Average variable cost per customer | $15 |
| Average contribution margin | $105 |
| **Customers to break even** | **635** |
| MRR at break-even | $76,200 |
| ARR at break-even | $914,400 |

### 10.4 Target Profitability

| Target | Monthly Profit | Required Customers (EXAMPLE) | Required MRR (EXAMPLE) |
|---|---|---|---|
| 20% net margin | $16,650 | 794 | $95,280 |
| 30% net margin | $28,542 | 907 | $108,840 |
| 50% net margin | $66,600 | 1,270 | $152,400 |

---

## 11. KPI Dashboard

The simulator should expose a real-time dashboard of the following metrics. Each metric includes its formula and configurable target thresholds.

### 11.1 KPI Definitions

| KPI | Formula | Significance |
|---|---|---|
| **MRR** | Σ(net_mrr) | Monthly recurring revenue |
| **ARR** | MRR × 12 | Annual run rate |
| **ARPU** | MRR / paying_customers | Average revenue per user |
| **Gross Margin** | (net_revenue − variable_costs) / net_revenue | Unit economics health |
| **Net Margin** | (net_revenue − total_costs) / net_revenue | Overall profitability |
| **LTV** | ARPU × average_lifetime_months | Customer lifetime value |
| **CAC** | sales_marketing_spend / new_customers | Customer acquisition cost |
| **LTV/CAC** | LTV / CAC | Acquisition efficiency |
| **Disc. Cost/Customer** | Σ(discovery_costs) / customers | Discovery cost burden |
| **AI Cost/Customer** | Σ(ai_costs) / customers | AI cost burden |
| **Infra Cost/Customer** | total_infra / customers | Infrastructure cost burden |
| **Avg Discovery Usage** | Σ(credits_consumed) / customers | Per-plan utilization |
| **Avg AI Usage** | Σ(tokens_consumed) / customers | Per-plan utilization |
| **Avg Cache Hit Rate** | cache_hits / total_lookups | Lookup efficiency |
| **Top-up Revenue** | Σ(top_up_charges) | Overage revenue |
| **Churn Rate** | customers_lost / customers | Retention health |
| **Customer Count** | total_customers | Scale indicator |
| **Founding Impact** | discount_amount / gross_revenue | Pricing program cost |
| **Runway** | cash_in_bank / monthly_burn | Liquidity (see Section 14) |
| **Burn Multiple** | net_burn / net_new_arr | Capital efficiency |

### 11.2 Configurable Targets

KPI targets are `CONFIGURABLE`. Example thresholds below are `PLACEHOLDER DEFAULT`:

```
kpi_targets:
  gross_margin:
    healthy: 0.80
    watch: 0.70
    critical: 0.60
  net_margin:
    healthy: 0.20
    watch: 0.0
    critical: -0.10
  arpu:
    healthy: 120
    watch: 100
    critical: 80
  churn_rate:
    healthy: 0.03
    watch: 0.05
    critical: 0.08
  discovery_cost_per_customer:
    healthy: 8
    watch: 12
    critical: 15
  ai_cost_per_customer:
    healthy: 10
    watch: 15
    critical: 20
  cache_hit_rate:
    healthy: 0.50
    watch: 0.30
    critical: 0.20
  top_up_revenue_pct:
    healthy: 0.05
    watch: 0.02
    critical: 0.01
  contribution_margin:
    healthy: 100
    watch: 80
    critical: 60
```

### 11.3 Dashboard Example (at break-even)

`EXAMPLE` — Based on the break-even scenario from Section 10.

| KPI | Value |
|---|---|
| MRR | $76,200 |
| ARR | $914,400 |
| Paying customers | 635 |
| ARPU | $120.00 |
| Gross margin | 79.5% |
| Net margin | 0% (break-even) |
| Discovery cost/customer | $8.50 |
| AI cost/customer | $10.00 |
| Infra cost/customer | $4.37 |
| Cache hit rate | 40% |
| Top-up revenue | $3,810 (5% of MRR) |

---

## 12. Stress Tests

The simulator should model stress scenarios automatically. Each scenario is a set of configuration overrides plus expected output ranges.

> All values in this section are `EXAMPLE` only, based on `PLACEHOLDER DEFAULT` config.

### 12.1 Provider Prices Double

| Before (EXAMPLE) | After (EXAMPLE) |
|---|---|
| Customer cost: $15 avg variable | $25 avg variable |
| Gross margin: 79.5% | 70.8% |
| Net margin: 0% | −8.7% |
| Customers needed: 635 | 847 (+212) |

### 12.2 AI Costs Increase 3×

| Before (EXAMPLE) | After (EXAMPLE) |
|---|---|
| AI cost/customer: $10 | $30 |
| Gross margin: 79.5% | 62.5% |
| Net margin: 0% | −15.8% |
| Customers needed: 635 | 1,115 |

### 12.3 Cache Hit Rate Improves to 70%

| Before (EXAMPLE: 40%) | After (EXAMPLE: 70%) |
|---|---|
| Discovery cost/customer: $8.50 | $4.67 |
| Gross margin: 79.5% | 83.2% |
| Net margin: 0% | +3.7% |
| Customers to break even: 635 | 584 |

### 12.4 Heavy User Cluster (10% of Customer Base)

| Before (all Typical) | After (10% Heavy) |
|---|---|
| Avg variable cost: $15 | $18.50 |
| Gross margin: 79.5% | 76.6% |
| Net margin: 0% | −2.9% |

### 12.5 Enterprise Customer Arrives

| Item | Value (EXAMPLE) |
|---|---|
| Revenue | $2,000 |
| Variable costs | $214.65 |
| Gross profit | $1,785.35 |
| Gross margin | 89.3% |
| Equivalent Starter customers | 40 |

### 12.6 Discovery Usage Spike (3× normal)

| Before (EXAMPLE) | After (3×) |
|---|---|
| Discovery cost/customer: $8.50 | $25.50 |
| Gross margin: 79.5% | 60.8% |
| Net margin: 0% | −10.1% |

### 12.7 Automation Spikes

| Metric | Before (EXAMPLE) | After (EXAMPLE) |
|---|---|---|
| Variable infra cost | $1.50 | $2.10 |
| AI cost | $10.00 | $18.00 |
| Total variable | $15.00 | $23.60 |
| Gross margin | 79.5% | 71.7% |

---

## 13. Recommendations

### 13.1 Variables with Greatest Impact

Ranked by sensitivity to unit change, based on `PLACEHOLDER DEFAULT` configuration:

| Rank | Variable | Impact | Rationale |
|---|---|---|---|
| 1 | **Customer count** | Extreme | Break-even at ~635 customers. Each adds ~$105 contribution margin. |
| 2 | **Average plan price** | Very High | 10% price increase adds ~$14.5K/mo at 1K customers. Near-zero marginal cost. |
| 3 | **AI cost per token** | High | Largest variable cost. 3× increase makes business unprofitable. |
| 4 | **Discovery provider pricing** | High | Provider cost doubling = ~10pp gross margin loss. Renegotiate annually. |
| 5 | **Cache hit rate** | Medium–High | 40% → 70% saves ~$4/customer/month. Best infra ROI. |
| 6 | **Heavy user ratio** | Medium | 10% heavy users erodes margin ~3pp. Upgrade triggers critical. |
| 7 | **Churn rate** | Medium | 5% → 3% improves LTV significantly. Reduces CAC payback. |
| 8 | **Founding member ratio** | Low–Medium | Temporary discount. Auto-converts at public launch. |

### 13.2 Monthly Metrics to Monitor

| Metric | Healthy | Watch | Critical |
|---|---|---|---|
| Gross margin | >80% | 70–80% | <70% |
| Net margin | >20% | 0–20% | <0% |
| ARPU | >$120 | $100–$120 | <$100 |
| Churn | <3% | 3–5% | >5% |
| Discovery cost/customer | <$8 | $8–$12 | >$12 |
| AI cost/customer | <$10 | $10–$15 | >$15 |
| Cache hit rate | >50% | 30–50% | <30% |
| Top-up revenue % | >5% | 2–5% | <2% |
| Contribution margin | >$100 | $80–$100 | <$80 |
| Runway | >18 months | 12–18 months | <12 months |
| Burn multiple | <1.0× | 1.0–1.5× | >1.5× |

### 13.3 Assumptions to Validate

| Assumption | Current Confidence | Validation Method | Validated At |
|---|---|---|---|
| Cache hit rate of 40% | `LOW` | Measure after 100 customers | After 100 customers |
| Average AI prompts per customer | `LOW` | Instrument and measure | After 100 customers |
| Typical vs. heavy user ratio | `UNVALIDATED` | Segment by plan after launch | After 500 customers |
| Empty result rate (15%) | `LOW` | Measure Discovery API responses | After 100 customers |
| Average conversation turns (3) | `LOW` | Instrument AI sessions | After 100 customers |
| Context growth per turn (30%) | `LOW` | Measure token counts | After 500 customers |
| Founding member conversion rate | `UNVALIDATED` | Track after public launch | After public launch |
| Chargeback rate (0.5%) | `UNVALIDATED` | Measure after 1,000 transactions | After 1,000 txns |
| Infrastructure cost per customer | `MEDIUM` | Cloud billing analysis | Monthly review |
| Discovery-to-AI usage ratio | `UNVALIDATED` | Cross-system telemetry | After 500 customers |

### 13.4 What Should Never Be Hardcoded

These values must always originate from configuration. They are the core assumptions of the financial model:

| Category | Values | Never Hardcode |
|---|---|---|
| **Pricing** | Plan prices, founding prices, allocation limits | Allocation values, credit counts, token limits |
| **Discovery** | Credit costs per action, provider pricing | Provider names, cost-per-action values |
| **AI** | Provider groups, model names, token costs | Provider names, model names, token prices |
| **Infrastructure** | Fixed and variable cost items | Vendor names, cost values, scaling factors |
| **Payment** | Processing fees, chargeback assumptions | Fee percentages, fixed fees |
| **Profiles** | Usage profiles, plan-to-profile mappings | Profile values, mapping decisions |
| **KPIs** | Targets and thresholds | Threshold values, health ranges |
| **Fixed Costs** | Payroll, roles, salaries, burden rate | Team structure, salary values |
| **Cash Flow** | Starting cash, operating expenses | Cash balance, monthly outflow |

The only values that may remain hardcoded are the current public pricing (Section 2.2) as `BUSINESS DECISION`. Everything else is input, not constant.

### 13.5 Implementation Guidance

When implementing the simulator:

1. **Start with a flat config file** (YAML, JSON, or TOML) — not hardcoded constants.
2. **Build calculation functions first** — pure functions that take config + profile + customer count → output.
3. **Add sensitivity as a loop** — iterate over a range of each variable and recompute.
4. **Build the dashboard as a view** — aggregate outputs into KPI cards.
5. **Stress tests are just sensitivity presets** — a set of config overrides + expected outputs.
6. **Cash flow adds time** — extend from single-period to multi-period (monthly projection).
7. **Monte Carlo is just sensitivity × many** — random sampling over configurable distributions.

The model can be implemented in:

- **Python** — as a CLI tool or FastAPI endpoint (recommended for internal tooling)
- **Spreadsheet** — mirror the calculation blocks as sheets (good for ad-hoc exploration)
- **Web dashboard** — React app consuming the Python engine (best for ongoing use)

All three should share the same config format.

---

## 14. Cash Flow Model

The profitability model (Sections 4–12) answers "are we making money?" The cash flow model answers "do we have enough money to operate?"

### 14.1 Core Model

```
starting_cash = config.cash_flow.starting_balance

For each month:
  inflow  = net_mrr + top_up_revenue + one_time_revenue
  outflow = total_fixed_costs + total_variable_costs
           + capital_expenditure + tax_payments
  net_burn = outflow - inflow  (positive = losing cash)

  ending_cash = starting_cash - net_burn
  runway_months = ending_cash / monthly_outflow (if outflow > inflow)
  runway_months = infinite                    (if inflow >= outflow)
```

### 14.2 Configurable Cash Parameters

```
cash_flow:
  starting_balance: 500000              # PLACEHOLDER DEFAULT
  capital_expenditure: 0                # One-time or periodic capex
  tax_rate: 0.21                        # Effective corporate tax rate
  tax_payment_schedule: quarterly       # quarterly, annual
  payment_terms_days: 30                # Days until revenue is received
  accounts_receivable_factor: 1.0       # Fraction of invoiced amount collected
  delay_months_to_revenue: 0            # Months between signup and first payment
```

### 14.3 Cash Conversion

```
cash_conversion_cycle = days_receivable + days_inventory - days_payable

For Loqi (SaaS, no inventory):
  days_receivable = payment_terms_days
  days_payable    = average_vendor_payment_terms (configurable)
  cash_conversion_cycle = days_receivable - days_payable

  Negative cash conversion cycle = collect before paying = working capital advantage
```

### 14.4 Key Cash Metrics

| Metric | Formula | Significance |
|---|---|---|
| **Cash in Bank** | ending_cash | Current liquidity |
| **Monthly Burn** | monthly_outflow | Gross cash spend |
| **Net Burn** | monthly_outflow − monthly_inflow | Cash consumed per month |
| **Runway** | cash_in_bank / monthly_outflow | Months until zero cash |
| **Runway at Break-even** | cash_in_bank / (monthly_outflow − monthly_inflow_at_breakeven) | Months until break-even cash need |
| **Burn Multiple** | net_burn / net_new_arr | Capital efficiency (lower is better) |
| **Months to Profitability** | customers_needed / (new_customers_per_month) | Time from today to break-even |

### 14.5 Runway Scenarios

`EXAMPLE` — Based on `PLACEHOLDER DEFAULT` inputs:

| Scenario | Monthly Burn | Cash | Runway |
|---|---|---|---|
| Current burn | $75,000 | $500,000 | 6.7 months |
| After 200 customers | $65,000 | $500,000 | 7.7 months |
| After break-even (635 customers) | $76,200 (covered) | $500,000 | Infinite |
| Worst case (no growth) | $85,000 | $500,000 | 5.9 months |

---

## 15. Monte Carlo Simulation

The simulator should support probabilistic modeling through Monte Carlo simulation. This section defines the model structure — not implementation code.

### 15.1 Purpose

Deterministic models (Sections 4–14) answer "what happens if X changes?" Monte Carlo answers "what is the probability that we lose money next quarter?"

### 15.2 Stochastic Variables

Each variable is modeled with a probability distribution. The simulation engine samples thousands of combinations and aggregates results.

| Variable | Distribution Type | Example Parameters | Confidence |
|---|---|---|---|
| Discovery lookups per customer | Log-normal | μ=7.3, σ=0.8 | `LOW` |
| AI prompts per customer | Log-normal | μ=6.9, σ=1.0 | `LOW` |
| Cache hit rate | Beta | α=8, β=12 | `LOW` |
| Monthly churn rate | Beta | α=2, β=50 | `UNVALIDATED` |
| Upgrade rate (Starter → Growth) | Beta | α=3, β=20 | `UNVALIDATED` |
| Heavy user ratio | Beta | α=2, β=18 | `UNVALIDATED` |
| Top-up purchase rate | Poisson | λ=0.05 per customer | `UNVALIDATED` |
| New customers per month | Poisson | λ=50 | `UNVALIDATED` |
| Empty result rate | Beta | α=3, β=17 | `LOW` |
| Founding member ratio | Fixed distribution | Set by config | `MEDIUM` |

### 15.3 Configuration

```
monte_carlo:
  iterations: 10000            # Number of simulation runs
  random_seed: 42              # Reproducibility
  output_percentiles: [5, 25, 50, 75, 95]
  variables:
    - name: discovery_lookups_per_customer
      distribution: log_normal
      mu: 7.3
      sigma: 0.8
      min: 0
    - name: churn_rate
      distribution: beta
      alpha: 2
      beta: 50
    # ...additional variables follow same structure
```

### 15.4 Outputs

After running N iterations, the simulator should report:

| Output | Description |
|---|---|
| **Margin Distribution** | Histogram of gross margin across all runs |
| **P(Loss)** | Probability that net margin < 0% |
| **P(Critical Margin)** | Probability that gross margin < 60% |
| **Revenue Distribution** | P5, P25, P50, P75, P95 of MRR |
| **Break-even Probability** | Likelihood of reaching break-even within 12/18/24 months |
| **Worst-case Runway** | P5 runway (5th percentile — worst 5% of outcomes) |
| **Expected Infrastructure Cost** | Mean and distribution of infra costs |
| **Heavy User Impact** | Distribution of high-usage customer costs |

### 15.5 Example Output

`EXAMPLE` — Based on `PLACEHOLDER DEFAULT` inputs:

| Metric | P5 | P25 | P50 | P75 | P95 |
|---|---|---|---|---|---|
| Gross margin | 68% | 74% | 79% | 83% | 87% |
| Net margin | −12% | −4% | 0% | 5% | 12% |
| MRR | $52K | $65K | $76K | $88K | $102K |
| Customers | 510 | 575 | 635 | 700 | 780 |

**P(Loss):** 42% (before reaching break-even customer count)

---

## 16. Pricing Optimization

The simulator should support pricing experiments by accepting a modified configuration and instantly recalculating all outputs.

### 16.1 Optimization Variables

| Variable | Experiment Example |
|---|---|
| Plan standard prices | Raise Starter to $59, Growth to $179 |
| Founding prices | Reduce founding discount from 20% to 15% |
| Discovery Credits per plan | Increase Starter from 500 to 750 |
| Top-up pricing | Change from $5/1K to $4/1K |
| AI token allocations | Increase Scale from 10M to 15M |
| Fair-use rate limits | Double rate limit for Growth+ |
| Upgrade thresholds | Lower upgrade trigger for Starter |
| Profile-to-plan mapping | Change Growth expected profile |

### 16.2 Experiment Format

```
experiment:
  name: "Q4 Pricing Optimization"
  description: "Test $10 Starter increase, $30 Growth increase"
  overrides:
    plans:
      starter:
        standard_price: 59
      growth:
        standard_price: 179
  customer_distribution:
    # How existing customers map to new prices
    existing_customers_grandfathered: true
    new_customers_new_pricing: true
    founding_customers_unchanged: true
```

### 16.3 Experiment Outputs

For each experiment, the simulator should instantly compute:

| Output | Purpose |
|---|---|
| **Revenue Impact** | Net MRR change |
| **Margin Impact** | Gross and net margin change per plan and blended |
| **Break-even Shift** | New customers needed to break even |
| **LTV Change** | Per-plan and blended LTV impact |
| **ARPU Change** | Blended ARPU before and after |
| **Upgrade Behavior Model** | Estimated migration based on price elasticity (configurable elasticity coefficient) |

### 16.4 Price Elasticity Model

```
elasticity_coefficient: -0.3   # Default: 10% price increase → 3% demand drop

price_impact = price_change_pct × elasticity_coefficient
demand_change = current_customers × price_impact
net_revenue_impact = (price_change × remaining_customers)
                   - (current_price × lost_customers)
```

The elasticity coefficient is `CONFIGURABLE` and should be refined from real data over time.

---

## 17. Confidence Levels

Every important assumption in the simulator has a confidence rating. This helps readers distinguish between what is based on real data versus educated guesses.

### 17.1 Rating Definitions

| Level | Meaning | Color |
|---|---|---|
| `HIGH` | Derived from actual customer telemetry or contract pricing | Green |
| `MEDIUM` | Estimated from industry benchmarks or limited data | Yellow |
| `LOW` | Educated guess, not yet validated | Orange |
| `UNVALIDATED` | Assumption with no supporting data | Red |

### 17.2 Assumption Confidence Matrix

| Assumption | Confidence | Data Source | Last Updated |
|---|---|---|---|
| Current public pricing | `HIGH` | Published pricing page | Document date |
| Current founding pricing | `HIGH` | Published pricing page | Document date |
| Payment processing fees | `HIGH` | Stripe published pricing | Document date |
| Provider pricing (PDL, Hunter) | `HIGH` | Current contracts | Document date |
| AI provider pricing (OpenAI, Anthropic) | `HIGH` | Published API pricing | Document date |
| Customer usage — Discovery lookups | `LOW` | Estimated from product design | Document date |
| Customer usage — AI prompts | `LOW` | Estimated from product design | Document date |
| Customer usage — Cache hit rate | `LOW` | Estimated from lookup patterns | Document date |
| Customer usage — Conversation turns | `LOW` | Estimated from AI session design | Document date |
| Customer usage — Email volume | `LOW` | Estimated from campaign design | Document date |
| Infrastructure fixed costs | `MEDIUM` | Cloud provider estimates | Document date |
| Infrastructure variable per customer | `MEDIUM` | Cloud provider estimates | Document date |
| Heavy user ratio | `UNVALIDATED` | No data yet | Document date |
| Churn rate | `UNVALIDATED` | No data yet | Document date |
| Upgrade rate | `UNVALIDATED` | No data yet | Document date |
| Top-up purchase behavior | `UNVALIDATED` | No data yet | Document date |
| Price elasticity | `UNVALIDATED` | No data yet | Document date |
| Founding member ratio at launch | `UNVALIDATED` | No data yet | Document date |

### 17.3 Confidence Migration Path

As Loqi gathers real telemetry, assumptions migrate from `UNVALIDATED` → `LOW` → `MEDIUM` → `HIGH`. The simulator should track this migration:

```
assumption_tracking:
  - name: "Cache hit rate"
    current_confidence: LOW
    next_review: "After 100 paying customers"
    validation_query: "SELECT AVG(cache_hit_rate) FROM discovery_usage"
    expected_improvement: "40-50% based on shared customer lookups"
```

---

## 18. Validation Strategy

The simulator must evolve from estimated guesses to data-driven accuracy. This section defines how.

### 18.1 Validation Phases

| Phase | Time | Data Available | Action |
|---|---|---|---|
| **Pre-launch** | Today | None | Use `PLACEHOLDER DEFAULT` values. All assumptions marked `LOW` or `UNVALIDATED`. |
| **Alpha** | First 10 customers | Sparse usage data | Manually override profile values. Compare estimates vs. actuals weekly. |
| **Beta** | 100 customers | Meaningful usage data | Replace profile defaults with real medians. Validate cache hit rate, AI usage, discovery usage. |
| **Growth** | 1,000 customers | Rich telemetry | Replace all `LOW` assumptions with measured values. Start Monte Carlo calibration. |
| **Scale** | 10,000+ customers | Full behavioral data | Continuous recalibration. All core assumptions should reach `HIGH` confidence. |

### 18.2 Telemetry Requirements

To validate the simulator, the product must instrument:

| Telemetry Signal | Feeds Into | Priority |
|---|---|---|
| Discovery lookups per customer per month | Profile validation | Critical |
| Cache hit rate | Discovery cost model | Critical |
| AI prompts per customer per month | AI cost model | Critical |
| AI tokens per prompt | AI cost model | Critical |
| AI conversation turns per session | AI cost model | High |
| AI retry rate | AI cost model | High |
| Top-up purchases | Revenue model | High |
| Empty result rate | Discovery cost model | Medium |
| Campaign volume per customer | Profile validation | Medium |
| Storage usage per customer | Infrastructure model | Medium |
| Email volume per customer | Infrastructure model | Medium |
| Churn events | LTV model | Critical |
| Upgrade events | Pricing optimization | High |

### 18.3 Calibration Process

```
Before launch:
  config.profiles[].metrics = estimated values
  config.profiles[].confidence = LOW

After 100 customers:
  actual_medians = query_telemetry(last_30_days)
  for each metric:
    if abs(actual - estimated) / estimated > threshold:
      override config value
      set confidence = MEDIUM

After 1,000 customers:
  repeat calibration
  set confidence = HIGH for validated metrics
  begin Monte Carlo calibration

Continuous:
  monthly_validation = compare_simulator_to_actuals()
  if monthly_validation.error > threshold:
    flag for review
```

### 18.4 Automated Validation

The simulator should support a validation mode that compares its predictions against actuals:

```
validation:
  mode: compare
  period: last_30_days
  actuals:
    total_discovery_cost: 12500       # From provider bills
    total_ai_cost: 8500               # From AI provider bills
    total_infra_cost: 3200            # From cloud provider
    total_revenue: 45200              # From payment processor
    customer_count: 380
    churned_customer_count: 12
  expected: # From simulator with current config
    total_discovery_cost: 11800
    total_ai_cost: 9000
  tolerance: 0.15  # 15% acceptable error
```

---

## 19. Versioning and Evolution

### 19.1 What Changes vs. What Stays

| Layer | Change Frequency | Who Changes |
|---|---|---|
| **This document** | Almost never | Platform team. Only structural changes to the model. |
| **Configuration values** | Frequently (weekly/monthly) | Operations, finance, leadership |
| **Simulation engine** | Rarely | Engineering. Only if calculation rules change. |
| **Reports / dashboards** | Sometimes | Engineering, data team. New views, new KPIs. |

### 19.2 Configuration Lifecycle

```
Configuration File (YAML/JSON/TOML)
  │
  ├── v1.0 — Pre-launch estimates
  │   All values: PLACEHOLDER DEFAULT
  │   Confidence: LOW / UNVALIDATED
  │
  ├── v1.1 — After 100 customers
  │   Override: cache_hit_rate, discovery_lookups, ai_prompts
  │   Confidence: MEDIUM for overridden values
  │
  ├── v2.0 — After 1,000 customers
  │   Override: all core usage metrics
  │   Confidence: HIGH for validated values
  │   New: Monte Carlo calibrated distributions
  │
  └── vN — Continuous
      Config values evolve. Document does not change.
```

### 19.3 Versioning the Simulator

```
simulator_version: 1.0           # Tracks the engine version
config_version: 1.0              # Tracks the configuration version
last_calibrated: 2026-07-19      # Date of last assumption validation
calibration_customer_count: 0    # Customers at last calibration
```

### 19.4 Document Maintenance

- This document should not require modification for configuration changes. That is what the config file is for.
- If a new section is needed (e.g., "Partner Revenue Model"), add it to this document as a new section.
- If a calculation rule changes (e.g., how founding member discounts compound with multi-year commitments), update the relevant section and bump the document version.
- If a provider is added or removed, only the configuration changes — never this document.

### 19.5 What Triggers a Document Update

| Event | Action |
|---|---|
| Pricing change | Update Section 2.2 (`BUSINESS DECISION`). No structural changes. |
| New Discovery provider | Update provider config. Add note in Section 2.5. |
| New AI provider | Update provider group config. Add note in Section 2.6. |
| Infrastructure vendor change | Update infra config. No document changes. |
| New KPI needed | Add to Section 11 configuration. Expand table if new metric class. |
| New stress scenario | Add to Section 12 configuration. No document changes for simple parameter shifts. |
| Calculation rule change | Update relevant section + bump version. |
| New business model (e.g., marketplace) | Add new section. Bump version. |

---

## Appendix A: Confidence Dashboard

A quick-reference summary of all assumption confidence levels at document freeze:

| Category | Count HIGH | Count MEDIUM | Count LOW | Count UNVALIDATED |
|---|---|---|---|---|
| Pricing | 2 | 0 | 0 | 0 |
| Discovery | 2 | 0 | 3 | 0 |
| AI | 2 | 0 | 4 | 0 |
| Infrastructure | 0 | 2 | 0 | 0 |
| Payment | 1 | 0 | 0 | 0 |
| Customer Profiles | 0 | 0 | 5 | 3 |
| Behavioral (churn, upgrade, elasticity) | 0 | 0 | 0 | 5 |
| **Total** | **7** | **2** | **12** | **8** |

**Current signal-to-noise ratio:** 7 HIGH + 2 MEDIUM out of 29 assumptions = **31% confidence coverage**.

Target after 1,000 customers: >80% confidence coverage.

---

## Appendix B: Calculation Dependency Graph

```
config
  │
  ├── plan prices → Revenue Model
  ├── provider costs × profile usage → Discovery Cost Model
  ├── AI pricing × profile usage → AI Cost Model
  ├── infrastructure config × customer count → Infrastructure Model
  │
  ├── Revenue + Costs → Plan Profitability
  │       │
  │       ├── × customer distribution → KPI Dashboard
  │       ├── × fixed costs → Break-even Analysis
  │       ├── × time + starting cash → Cash Flow Model
  │       │
  │       └── Override config → Sensitivity Analysis
  │       └── Override config → Stress Tests
  │       └── Random distributions → Monte Carlo
  │       └── Modified config → Pricing Optimization
```

The simulator should compute from leaves to root. Any config change should recompute only the affected branches.

---

## Future Financial Modules

The following modules are intentionally outside the scope of v1.0. They are documented here to prevent future contributors from attempting to cram them into the current model. Each will become a separate specification when the time is right.

| Module | Why it is not in v1.0 | Planned Window |
|---|---|---|
| **Revenue Recognition** (ASC 606) | Requires multi-period deferred revenue, contract modifications, and performance obligation tracking. Out of scope until Loqi has multi-year contracts. | After Enterprise tier launches |
| **Multi-currency Modeling** | Loqi bills in USD only at launch. Multi-currency adds FX risk, settlement timing, and regional pricing complexity not needed for v1.0. | After international expansion |
| **Regional Tax Engine** | Sales tax and VAT are toggled off by default. A full regional tax engine requires nexus tracking, automated rate lookup, and filing support. | After 5+ countries have paying customers |
| **Enterprise Contract Forecasting** | Enterprise pricing is custom and negotiated. Forecasting ramp, renewals, and expansion for enterprise deals requires a separate pipeline model. | After first 10 enterprise customers |
| **Customer Cohort Analysis** | Cohort analysis requires time-series data (months since signup) that the static single-period simulator does not model. Will be a separate dashboard. | After 500 customers |
| **Churn Prediction** | Predictive churn requires ML model integration, behavioral feature engineering, and historical churn data. This is an analytics system, not a financial model. | After 1,000 customers and observed churn |
| **Expansion Revenue Forecasting** | Expansion (upsells, cross-sells, seat growth) requires per-customer contract history. Not applicable at launch when all customers are on fixed plans. | After 12 months of customer history |
| **Headcount Planning** | Headcount is currently a fixed-cost input. A full headcount planning module would model hiring pipelines, ramp time, attrition, and role-based compensation bands. | After Series A |
| **Board Reporting** | Board packs combine financial simulator outputs with narrative, OKR tracking, and competitive analysis. This is a presentation layer on top of the simulator. | After Series A |
| **Scenario Planning** | Multi-branch scenario planning (optimistic / base / pessimistic with distinct config sets) is supported by the sensitivity engine but a full scenario planner with version comparison UI is future work. | After core simulator is implemented |

These modules are not forgotten. They are deferred by design. Each will get its own specification document when the preceding dependencies are met.
