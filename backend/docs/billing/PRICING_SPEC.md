# Loqi Pricing Specification

**Version:** 1.0  
**Status:** Commercial Draft  
**Owner:** Product Team  
**Last Updated:** July 2026

---

# Purpose

This document defines the commercial implementation of Loqi's pricing model.

Unlike the Product Constitution, Feature Matrix, and Billing Principles, this document is expected to evolve as the business grows.

The pricing architecture should remain stable.

Prices, quotas, and limits may change based on customer feedback, provider costs, and platform economics.

---

# Pricing Philosophy

Loqi follows a capability-first pricing model.

Customers purchase platform capabilities through subscriptions.

Variable external infrastructure costs are covered through Discovery Credits.

The objective is to create predictable pricing while maintaining sustainable platform economics.

---

# Pricing Principles

## Principle 1

Plans unlock capabilities.

Plans should never exist solely to remove arbitrary restrictions.

---

## Principle 2

Customers should understand exactly what they are paying for.

Every plan should communicate a clear business outcome.

---

## Principle 3

Discovery Credits exist to recover external provider costs.

They are not premium features.

---

## Principle 4

AI is included in paid plans.

Customers purchase intelligence—not token usage.

---

## Principle 5

Workspace Knowledge should encourage long-term adoption.

Customer-owned knowledge should never become a metered resource.

---

# Plans

---

# Free

## Purpose

Evaluate Loqi.

---

## Target Customer

Prospective customers.

---

## Includes

- Evaluation access
- Limited AI
- Limited campaigns
- Trial Discovery
- One mailbox

---

## Goal

Help customers understand Loqi before making a purchasing decision.

---

# AI Workspace

## Purpose

Bring Your Own Leads.

---

## Target Customer

Businesses that already own prospect data.

---

## Includes

- Workspace Knowledge Base
- Unlimited AI
- Unlimited campaigns
- Persistent memory
- Brand Kit
- CRM imports
- Knowledge search

---

## Does Not Include

- External Discovery
- Discovery Credits

---

# Discovery

## Purpose

Find New Leads.

---

## Target Customer

Businesses requiring continuous lead generation.

---

## Includes

Everything in AI Workspace

plus

- Discovery Engine
- Discovery Credits
- Lead enrichment
- Email verification
- Company discovery

---

# Teams

## Purpose

Collaborate at Scale.

---

## Target Customer

Organizations.

---

## Includes

Everything in Discovery

plus

- Multiple members
- Roles
- Permissions
- Team analytics
- Shared memory
- Administration

---

# Commercial Variables

The following values are intentionally configurable.

## Subscription Prices

| Plan | Status |
|-------|--------|
| Free | Fixed |
| AI Workspace | Configurable |
| Discovery | Configurable |
| Teams | Configurable |

---

## Discovery Credit Allocation

Configurable.

Should reflect provider economics.

---

## AI Usage Limits

Configurable.

May change according to infrastructure costs.

---

## Campaign Limits

Configurable.

---

## Storage Limits

Configurable.

---

## Mailbox Limits

Configurable.

---

## Fair Use Thresholds

Configurable.

---

# Upgrade Rules

Customers upgrade when business requirements evolve.

Examples:

Free

↓

Needs Workspace Knowledge

↓

AI Workspace

---

AI Workspace

↓

Needs new prospects

↓

Discovery

---

Discovery

↓

Needs collaboration

↓

Teams

---

# Downgrade Rules

Customers retain ownership of all Workspace data.

Capabilities unavailable under the downgraded plan become read-only where possible.

Customer data should never be deleted automatically solely because of a downgrade.

---

# Trial Strategy

The Free plan functions as a product evaluation experience.

Its purpose is to demonstrate Loqi's core workflow—not provide a permanent free alternative.

Evaluation capabilities should remain economically sustainable for the platform.

---

# Pricing Review Policy

Commercial values should be reviewed periodically based on:

- Provider pricing changes
- Infrastructure costs
- Customer feedback
- Conversion rates
- Revenue metrics
- Competitive landscape

Architecture should remain stable.

Commercial values may evolve.

---

# Future Expansion

Future pricing options may include:

- Annual billing discounts
- Enterprise contracts
- Discovery Credit Packs
- Team seat expansion
- Marketplace extensions
- Premium AI agents
- Advanced workflow automation

These additions should extend the pricing model without changing its underlying philosophy.

---

# Deferred Commercial Values

The following values are intentionally left undefined until provider research is completed.

- AI Workspace monthly price
- Discovery monthly price
- Teams monthly price
- Discovery Credit allocations
- Discovery Credit pricing
- Trial quotas
- Campaign quotas
- AI quotas
- Storage quotas
- Rate limits

These values should be finalized after:

1. Provider API research
2. Infrastructure cost analysis
3. Credit economy validation
4. Internal testing
5. Beta customer feedback

---

# Guiding Principle

Loqi should grow because customers receive increasing business value.

Pricing should reflect business outcomes—not technical implementation details.

Every pricing decision should strengthen customer trust while ensuring long-term platform sustainability.