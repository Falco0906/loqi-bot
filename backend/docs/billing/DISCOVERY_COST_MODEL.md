# Discovery Cost Model

**Version:** 1.0
**Status:** Draft → Ready for Pricing Finalization
**Owner:** Loqi

---

# Purpose

The Discovery Cost Model defines how Loqi converts external provider costs into a simple, predictable credit economy.

The objective is **not** to expose provider pricing to customers.

Instead, Loqi abstracts multiple external providers behind a unified Discovery Engine while ensuring:

* Sustainable margins
* Predictable pricing
* Provider flexibility
* Excellent user experience

This document serves as the financial foundation of Loqi's Discovery Engine.

---

# Design Principles

## 1. Customers purchase outcomes, not API calls.

Users think in terms of:

* Find companies
* Find prospects
* Find emails

They should never think in terms of:

* PDL Records
* Hunter Credits
* Provider APIs

---

## 2. Discovery Credits represent external infrastructure costs.

Discovery Credits exist solely because external providers charge Loqi for data.

Discovery Credits are **not** used for:

* AI generation
* AI personalization
* Campaign creation
* Analytics
* Workspace features

AI usage is included within subscription plans.

---

## 3. Providers are implementation details.

Customers never know:

* Which provider was used
* How many provider credits were consumed
* What provider pricing is

Provider selection is entirely managed by the Discovery Engine.

---

## 4. One action = One predictable cost.

Customers pay for user actions.

Not provider requests.

Example:

```text
Search Companies

↓

1 Discovery Credit
```

Not:

```text
37 PDL Records
+
4 Hunter Requests
```

---

## 5. Cache before provider.

Loqi should never spend provider credits when equivalent data already exists within the customer's workspace cache.

---

# Discovery Cost Buckets

All provider costs are normalized into five logical buckets.

| Bucket                     | Purpose                          |
| -------------------------- | -------------------------------- |
| Company Data               | Company search & enrichment      |
| People Data                | Prospect search & enrichment     |
| Email Discovery            | Email finding                    |
| Email Verification         | Email validation                 |
| Future Discovery Providers | Reserved for future integrations |

Providers may change over time.

Buckets do not.

---

# Provider Stack

## Primary Discovery

Provider:

**People Data Labs**

Responsibilities:

* Company Search
* Company Enrichment
* Person Search
* Person Enrichment

---

## Email Intelligence

Provider:

**Hunter**

Responsibilities:

* Email Finder
* Email Verification

---

## Deferred Providers

ZeroBounce

Status:

Deferred until Loqi expands into deliverability intelligence.

Possible future responsibilities:

* Inbox Placement
* Deliverability Monitoring
* Spam Analysis
* Domain Health

---

# User Actions

Customers purchase actions.

Each action maps internally to one or more providers.

---

## Search Companies

User Action

```text
Search Companies
```

Internal Workflow

```text
Workspace Cache

↓

PDL Company Search

↓

Normalize

↓

Cache

↓

Return Results
```

Customer Cost

```
1 Discovery Credit
```

---

## View Company

If cached:

```
Free
```

If additional enrichment required:

```
1 Discovery Credit
```

---

## Find Decision Makers

Workflow

```text
PDL Person Search

↓

Normalize

↓

Cache
```

Customer Cost

```
2 Discovery Credits
```

---

## Enrich Prospect

Workflow

```text
PDL Person Enrichment
```

Customer Cost

```
1 Discovery Credit
```

---

## Find Email

Workflow

```text
Hunter Email Finder
```

Customer Cost

```
1 Discovery Credit
```

---

## Verify Email

Workflow

```text
Hunter Verification
```

Customer Cost

```
1 Discovery Credit
```

---

# Discovery Engine Flow

```text
                User Query
                     │
                     ▼
             Workspace Cache
                     │
          ┌──────────┴──────────┐
          │                     │
      Cache Hit            Cache Miss
          │                     │
          ▼                     ▼
     Return Data          PDL Search
                                  │
                                  ▼
                           Normalize
                                  │
                                  ▼
                               Cache
                                  │
                                  ▼
                         Prospect Selected
                                  │
                       Email Available?
                     ┌──────┴──────┐
                     │             │
                    Yes            No
                     │             │
                     ▼             ▼
               Hunter Verify   Hunter Finder
                     │             │
                     └──────┬──────┘
                            ▼
                      Verified Lead
                            │
                            ▼
                    Communication Engine
```

---

# Credit Conversion Philosophy

Discovery Credits intentionally do not map 1:1 with provider costs.

Internal provider costs vary significantly.

Customer pricing remains simple.

| User Action          | Customer Cost |
| -------------------- | ------------: |
| Search Companies     |      1 Credit |
| View Cached Company  |          Free |
| Company Enrichment   |      1 Credit |
| Find Decision Makers |     2 Credits |
| Prospect Enrichment  |      1 Credit |
| Find Email           |      1 Credit |
| Verify Email         |      1 Credit |

The Discovery Engine determines the actual provider usage.

---

# Internal Cost Engine

Every provider operation maintains internal metadata.

Example

```typescript
Operation {
    provider: "PDL",
    operation: "Person Search",

    providerCostUSD: 0.28,

    loqiCredits: 2,

    marginMultiplier: configurable,

    cacheable: true
}
```

Provider pricing should never be hardcoded throughout the application.

All mappings should exist inside the Discovery Cost Engine.

---

# Workspace Cache Policy

## Rule 1

Always check cache first.

```
Workspace Cache

↓

Provider
```

Never the opposite.

---

## Rule 2

Never charge twice.

If identical data already exists inside the customer's workspace,

No provider request should be made.

No Discovery Credits should be deducted.

---

## Rule 3

Cache is workspace scoped.

Customer A's cached discovery results should never be served directly to Customer B without ensuring compliance with provider licensing.

---

## Rule 4

Provider freshness

Discovery data may be refreshed when:

* User explicitly requests refresh
* Cached record exceeds freshness threshold
* Email verification has expired
* Provider metadata changes

---

# Internal Ledger

Each workspace owns its own Discovery Credit balance.

Example

```
Workspace Credits

500

↓

Search Companies

-1

↓

Find Email

-1

↓

Verify Email

-1

↓

Remaining

497
```

Ledger entries should contain:

* Timestamp
* User
* Workspace
* Action
* Provider(s)
* Credits deducted
* Provider cost
* Status

---

# Failed Requests

## Provider Error

If provider request fails before data is returned:

```
Refund Discovery Credits
```

---

## Partial Success

If one provider succeeds and another fails:

Only successful operations consume credits.

---

## Cache Hit

Cache hits never consume Discovery Credits.

---

# Cost Simulator

Pricing decisions must always be validated against simulated customer behavior.

---

## Light User

Example

| Action           | Quantity |
| ---------------- | -------: |
| Company Searches |      100 |
| Companies Opened |       50 |
| People Found     |      150 |
| Emails Found     |      100 |
| Emails Verified  |      100 |

---

## Growth User

| Action           | Quantity |
| ---------------- | -------: |
| Company Searches |      500 |
| Companies Opened |      250 |
| People Found     |      800 |
| Emails Found     |      600 |
| Emails Verified  |      600 |

---

## Power User

| Action           | Quantity |
| ---------------- | -------: |
| Company Searches |    2,500 |
| Companies Opened |    1,500 |
| People Found     |    8,000 |
| Emails Found     |    6,000 |
| Emails Verified  |    6,000 |

The simulator calculates:

* Provider spend
* AI spend
* Infrastructure cost
* Gross margin
* Net margin

Plans should remain profitable across all expected customer profiles.

---

# Margin Targets

Pricing should satisfy the following targets:

| Metric                  |                       Target |
| ----------------------- | ---------------------------: |
| Minimum Gross Margin    |                          60% |
| Target Gross Margin     |                       70–80% |
| Enterprise Margin       |                   Negotiated |
| Discovery Cost Variance | <10% across comparable users |

---

# Subscription Integration

Subscription plans determine:

* Included Discovery Credits
* Mailbox limits
* Team limits
* Automation limits

Discovery Credits refill through:

* Monthly renewal
* Credit packs
* Enterprise allocations

AI usage remains included within plan limits and is not billed through Discovery Credits.

---

# Future Provider Strategy

The Discovery Engine must remain provider-agnostic.

Future providers (e.g., Proxycurl, Prospeo, Clearbit, ZoomInfo OEM) can be added by implementing a new adapter without changing the Discovery Credit economy.

The Discovery Cost Model should remain stable even as underlying providers evolve.

---

# Success Criteria

The Discovery Cost Model is successful if:

* Customers understand Discovery Credits without needing provider knowledge.
* Provider changes do not require pricing changes.
* Cache utilization minimizes unnecessary provider spend.
* Discovery actions remain predictable and transparent.
* Subscription plans achieve target gross margins while delivering a simple user experience.

---

# Version History

**v1.0**

* Established Discovery Credit philosophy.
* Defined provider responsibilities (PDL + Hunter).
* Standardized user action → credit mapping.
* Introduced cache-first strategy and workspace ledger.
* Added simulator and margin framework.

---

## One improvement I'd make before freezing it

I'd add a final appendix called **"Discovery Credit Schedule"** that is intentionally short and product-facing:

| User Action          | Credits |
| -------------------- | ------: |
| Search Companies     |       1 |
| Enrich Company       |       1 |
| Find Decision Makers |       2 |
| Enrich Prospect      |       1 |
| Find Email           |       1 |
| Verify Email         |       1 |

This becomes the canonical schedule referenced by both the product and billing system. The detailed cost engine above can evolve as provider pricing changes, while this schedule remains the stable contract with your users.
