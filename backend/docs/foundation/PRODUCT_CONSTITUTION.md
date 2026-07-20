# Loqi Product Constitution

**Version:** 1.0  
**Status:** Active  
**Owner:** Product Team  
**Last Updated:** July 2026

---

# Purpose

This document defines the core principles that guide every product, design, engineering, and business decision made for Loqi.

It exists to ensure that as Loqi grows, every feature, workflow, and architectural decision remains consistent with the product's long-term vision.

If a proposed feature conflicts with this constitution, the feature should be reconsidered before implementation.

---

# Vision

Build the world's most intelligent outbound sales workspace.

Loqi should not be another lead generation tool or another email automation platform.

It should become the operating system for modern outbound sales—bringing together discovery, knowledge, AI, communication, and automation into one seamless workspace.

---

# Mission

Help businesses find, understand, and reach the right people with less manual work and better outcomes.

Loqi should remove repetitive work, not create more complexity.

---

# Core Philosophy

Loqi is built around one simple idea:

> Sales teams should spend their time talking to people, not managing software.

Every feature should reduce friction.

Every workflow should eliminate manual effort.

Every interaction should feel intelligent.

---

# Product Principles

## 1. AI Should Feel Invisible

AI is not the product.

AI is the capability behind the product.

Users should focus on achieving outcomes—not choosing models, prompts, or technical settings.

Whenever possible:

- AI should make decisions automatically.
- AI should explain important decisions.
- AI should reduce configuration.

Never expose complexity simply because it exists.

---

## 2. Users Own Their Data

All customer data belongs to the customer.

Loqi stores, organizes, indexes, and helps users understand their data—but never claims ownership of it.

Users should always be able to:

- Export their data
- Delete their data
- Control integrations
- Disconnect providers

Data portability should always exist.

---

## 3. The Workspace Is The Source Of Truth

Everything belongs to a Workspace.

Examples:

- Contacts
- Companies
- Campaigns
- Templates
- Brand Kits
- Knowledge Sources
- AI Memory
- Mailboxes
- Analytics
- Credit Wallets

Nothing should exist outside a Workspace unless absolutely necessary.

---

## 4. Search Local Before Searching External

Loqi should always prefer user-owned knowledge.

Search order:

1. Workspace Knowledge Base
2. Workspace Cache
3. Previous Discoveries
4. External Providers

If information already exists inside the Workspace, external providers should never be queried.

This improves speed, reduces costs, and respects customer-owned knowledge.

---

## 5. Providers Are Infrastructure

Apollo.

Hunter.

People Data Labs.

Proxycurl.

Future providers.

These are implementation details.

Users interact with Loqi—not with providers.

The UI should never expose unnecessary provider-specific complexity.

---

## 6. Credits Represent External Cost

Credits should only exist when Loqi incurs an external variable cost.

Examples:

- Lead discovery
- Email verification
- Company enrichment
- Phone enrichment

Credits should never be consumed for:

- Searching Workspace Knowledge
- AI writing
- Campaign creation
- Email generation
- Templates
- Memory
- Internal automation

Credits are a cost model—not a product feature.

---

## 7. AI Should Not Feel Metered

Customers purchase productivity.

Not tokens.

Paid plans should feel generous.

Whenever economically possible:

- AI writing should be unlimited.
- Campaign generation should be unlimited.
- Knowledge search should be unlimited.

Users should think about business outcomes—not API usage.

---

## 8. Plans Unlock Capabilities

Pricing plans should unlock engines—not arbitrary restrictions.

Every paid plan should feel complete for its intended customer.

Users should upgrade because their business grows—not because the product becomes artificially unusable.

---

## 9. Every Feature Must Have A Home

Every new capability must belong to one product engine.

Current engines:

- Workspace Engine
- Knowledge Engine
- Discovery Engine
- Campaign Engine
- Intelligence Engine
- Communication Engine
- Analytics Engine
- Integration Engine
- Billing Engine

If a feature does not clearly belong to one of these engines, the architecture should be reconsidered before implementation.

---

## 10. Simplicity Beats Configuration

Loqi should make intelligent decisions by default.

Avoid adding settings that only exist to compensate for poor defaults.

Good software requires fewer decisions.

Great software makes the right decisions automatically.

---

## 11. Automation Should Feel Natural

Automation should be a consequence of good workflows—not a separate product.

Users should automate tasks because they are already working inside Loqi.

Automation should enhance existing workflows rather than forcing users to build them from scratch.

---

## 12. Everything Should Be Explainable

AI decisions should never feel random.

Whenever Loqi performs an important action, users should understand:

- What happened
- Why it happened
- What data was used
- What can be changed

Trust comes from transparency.

---

## 13. Build For Scale From Day One

Architecture should assume:

- Multiple workspaces
- Millions of contacts
- Multiple providers
- Multiple communication channels
- Multiple AI models

Avoid designs that require complete rewrites as the company grows.

---

## 14. Minimize Vendor Lock-In

Loqi should never depend entirely on a single:

- AI provider
- Lead provider
- Email provider
- Infrastructure provider

Every external dependency should be replaceable through abstraction layers.

The platform should remain adaptable as technologies evolve.

---

## 15. User Experience Comes Before Internal Convenience

Internal architecture exists to support great user experience.

Never expose technical limitations directly to users.

Instead:

- Abstract complexity
- Provide sensible defaults
- Guide users toward successful outcomes

The product should feel simple even if the implementation is sophisticated.

---

# Product Values

Loqi values:

- Intelligence over automation
- Outcomes over features
- Simplicity over complexity
- Ownership over lock-in
- Transparency over hidden behavior
- Consistency over novelty
- Reliability over shortcuts

---

# Decision Framework

Before implementing any feature, ask:

### Does it reduce manual work?

If not, reconsider.

---

### Does it belong to an existing engine?

If not, rethink the architecture.

---

### Does it make the product simpler?

If not, redesign it.

---

### Does it strengthen the Workspace?

If not, question whether it belongs in Loqi.

---

### Does it preserve user trust?

If not, do not ship it.

---

# Long-Term Vision

Loqi should evolve into an intelligent sales operating system—not just another SaaS tool.

The end goal is a platform where businesses can:

- Build their knowledge base
- Discover prospects
- Understand companies
- Generate personalized outreach
- Manage communication
- Measure outcomes
- Automate repetitive work

—all from a single intelligent workspace.

The product should continuously reduce the amount of software users need while increasing the amount of work Loqi performs on their behalf.

---

# Final Principle

Every release should make Loqi feel **smarter**, **simpler**, and **more valuable** than the release before it.

If a feature increases complexity without meaningfully improving outcomes, it should not be built.