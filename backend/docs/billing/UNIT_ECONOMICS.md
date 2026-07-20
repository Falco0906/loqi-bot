# UNIT_ECONOMICS.md

Version: 1.0

Status: Draft

Owner: Loqi

Confidential

---

# Purpose

The Unit Economics model defines the cost structure of Loqi at the smallest measurable unit.

Rather than reasoning about monthly subscriptions alone, Loqi measures profitability through individual customer actions.

Every subscription, pricing tier, and feature allocation must remain profitable according to this model.

This document acts as the financial source of truth for pricing, forecasting, and long-term sustainability.

---

# Financial Philosophy

Loqi is a premium AI-native outbound platform.

Its pricing strategy prioritizes:

* Sustainable growth
* Premium customer experience
* Predictable pricing
* High gross margins
* Operational efficiency

Target Gross Margin

| Metric  | Value |
| ------- | ----: |
| Ideal   |   80% |
| Healthy |   75% |
| Minimum |   70% |

Margins below the minimum threshold require pricing or allocation adjustments.

---

# Revenue Model

Revenue is generated from:

* Monthly subscriptions
* Enterprise contracts
* Automatic Discovery Refills (optional)

Loqi does **not** monetize:

* AI prompts
* AI tokens
* Individual email generations

AI remains included as part of the platform experience.

---

# Cost Categories

Every customer action contributes to one or more of the following cost categories.

## Provider Costs

External data providers.

Examples

* People Data Labs
* Hunter

Characteristics

* Variable
* Usage based
* Largest operational expense

---

## AI Costs

Language model providers.

Characteristics

* Variable
* Token based

Managed by the AI Routing Engine.

Models are selected dynamically according to plan policies.

---

## Infrastructure Costs

Infrastructure is divided into two classes.

### Fixed Infrastructure

Independent of customer count.

Examples

* Monitoring
* CI/CD
* DNS
* Security
* Observability
* Internal tooling

---

### Variable Infrastructure

Scales with usage.

Examples

* PostgreSQL
* Object Storage
* Redis
* Queue Workers
* Search Indexes
* CDN
* Bandwidth
* File Processing

Infrastructure vendors are implementation details.

The financial model tracks cost categories rather than specific services.

---

## Support Costs

Examples

* Customer Support
* Customer Success
* Enterprise Onboarding

Mostly proportional to plan size.

---

# Cost Hierarchy

```text
Customer Revenue

↓

Provider Costs

↓

AI Costs

↓

Variable Infrastructure

↓

Support

↓

Fixed Infrastructure Allocation

↓

Gross Profit
```

---

# Unit Definitions

The following units form the basis of Loqi's economics.

---

## Company Search

Represents:

Searching for organizations matching customer criteria.

Consumes:

* Discovery Provider
* Cache

Measures:

* Provider Cost
* Credit Consumption

---

## Company Enrichment

Represents:

Retrieving detailed organization information.

Consumes:

* Provider
* Cache

---

## Prospect Discovery

Represents:

Finding decision makers inside organizations.

Consumes:

* Discovery Provider

---

## Prospect Enrichment

Represents:

Retrieving complete contact profiles.

Consumes:

* Discovery Provider

---

## Email Discovery

Represents:

Finding verified email addresses.

Consumes:

* Hunter

---

## Email Verification

Represents:

Verifying email deliverability.

Consumes:

* Hunter

---

## AI Email Generation

Represents:

Creating outbound messages.

Consumes:

* AI Routing Engine

---

## AI Personalization

Represents:

Generating prospect-specific context.

Consumes:

* AI Routing Engine

---

## Campaign Automation

Represents:

Scheduling

Sequencing

Follow-ups

Analytics

Consumes:

Internal compute only.

---

# Cost Variables

Every measurable action has configurable variables.

Example

```yaml
Company Search

Provider Cost:
$

Credits:
1

Cacheable:
Yes

Average Latency:
Configurable
```

Example

```yaml
Email Discovery

Provider:
Hunter

Credits:
1

Provider Cost:
$

Cacheable:
No
```

Example

```yaml
AI Email

Provider:
AI Router

Average Input Tokens:

Average Output Tokens:

Average Cost:
$
```

No values should be hardcoded.

---

# Customer Cost Per Action

The simulator derives:

Cost per Company Search

Cost per Prospect

Cost per Verified Email

Cost per AI Email

Cost per Campaign

Cost per Workspace

These metrics are used internally only.

---

# Workspace Economics

Every workspace has measurable monthly economics.

Metrics

Monthly Revenue

Discovery Cost

AI Cost

Infrastructure Cost

Support Cost

Gross Profit

Gross Margin

Credit Utilization

Average Daily Usage

---

# Customer Lifetime Economics

Tracked metrics.

## Monthly Recurring Revenue

MRR

---

## Average Revenue Per Workspace

ARPW

---

## Average Monthly Cost

AMC

---

## Gross Profit

Revenue − Operating Cost

---

## Gross Margin

Gross Profit ÷ Revenue

---

## Customer Lifetime Value

Calculated separately.

---

# Discovery Credit Efficiency

Discovery Credits should correlate with customer value.

Metrics

Average Companies per Credit

Average Prospects per Credit

Average Verified Emails per Credit

Average Revenue Generated per Credit

These metrics help refine allocations over time.

---

# AI Efficiency

Tracked internally.

Metrics

Average Cost per Email

Average Cost per Personalization

Average Cost per Campaign

Average Tokens per Customer

Model Distribution

These values influence routing policies but never customer pricing.

---

# Infrastructure Efficiency

Metrics

Database Cost per Workspace

Storage Cost per Workspace

Bandwidth Cost per Workspace

Worker Cost per Workspace

Search Cost per Workspace

These values help determine scaling strategy.

---

# Break-Even Analysis

The simulator calculates:

Revenue Required

↓

Operating Cost

↓

Break-even Customer Count

↓

Profitability

Questions answered:

* How many Starter customers cover fixed infrastructure?
* When does hiring become sustainable?
* What revenue supports the next infrastructure upgrade?

---

# Sensitivity Analysis

The model supports stress testing.

Examples

## Provider Price Increase

PDL

+10%

+25%

+50%

---

Hunter

+20%

---

## AI Cost Increase

2×

3×

5×

---

## Infrastructure Growth

2×

5×

10×

---

## Cache Efficiency

30%

50%

70%

90%

---

## Customer Behavior

Light

Typical

Heavy

Power

---

# Operational Dashboards

The business should monitor:

Average Margin

Provider Spend

AI Spend

Infrastructure Spend

Discovery Credit Usage

Top Cost Drivers

Customer Mix

Revenue Distribution

MRR Growth

Gross Margin Trend

---

# Success Criteria

The Unit Economics model is considered healthy when:

✓ Gross margins remain above target.

✓ Provider costs scale predictably.

✓ AI costs remain sustainable through routing.

✓ Infrastructure scales proportionally with customer growth.

✓ Discovery Credits remain economically viable.

✓ Premium pricing is justified by customer outcomes.

✓ Growth does not compromise profitability.

---

# Future Enhancements

Future versions may include:

* Regional infrastructure costs
* Multi-currency pricing
* Enterprise SLAs
* Dedicated infrastructure pricing
* Marketplace integrations
* Usage forecasting
* Predictive margin analysis

---

# Version History

## v1.0

* Defined financial philosophy.
* Established cost hierarchy.
* Introduced action-based unit economics.
* Added customer, infrastructure, AI, and provider cost modeling.
* Defined operational metrics and success criteria.
* Prepared the financial foundation for pricing and forecasting.

---

# Appendix A — Core Business KPIs

| KPI                                               | Why it Matters                                  |
| ------------------------------------------------- | ----------------------------------------------- |
| Monthly Recurring Revenue (MRR)                   | Primary revenue metric                          |
| Average Revenue Per Workspace (ARPW)              | Measures customer value                         |
| Gross Margin                                      | Overall financial health                        |
| Discovery Cost per Workspace                      | Tracks external provider efficiency             |
| AI Cost per Workspace                             | Ensures AI remains sustainable                  |
| Infrastructure Cost per Workspace                 | Guides scaling decisions                        |
| Average Discovery Credit Utilization              | Helps tune plan allocations                     |
| Discovery Cache Hit Rate                          | Directly reduces provider spend                 |
| Average Cost per Verified Prospect                | One of Loqi's most important efficiency metrics |
| Customer Lifetime Value (LTV)                     | Long-term profitability                         |
| Churn Rate                                        | Indicates product-market fit                    |
| LTV:CAC Ratio *(when you begin paid acquisition)* | Growth efficiency benchmark                     |
| Monthly Burn Rate                                 | Critical while bootstrapping                    |

---

## One recommendation before we freeze everything

This document intentionally **does not include dollar amounts**.

I would keep it that way.

Think of it as your **financial architecture**, just as your Product Constitution is your product architecture.

The next—and final—business artifact should be a **live financial model** (spreadsheet or internal simulator) where you plug in the actual numbers for PDL, Hunter, AI, infrastructure, subscription prices, and customer behavior. That model will change over time. This document shouldn't.

Once those numbers are plugged into the simulator and the margins look healthy, I'd consider Loqi's business model frozen and shift almost entirely into product and engineering.
