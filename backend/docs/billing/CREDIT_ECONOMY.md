# Loqi Credit Economy

**Version:** 1.0  
**Status:** Architecture Frozen  
**Owner:** Product Team  
**Last Updated:** July 2026

---

# Purpose

This document defines the Discovery Credit economy used throughout Loqi.

It establishes:

- What Discovery Credits represent.
- When credits are consumed.
- When credits are not consumed.
- How credits flow through the platform.
- How credits should behave under failure scenarios.
- How future platform capabilities integrate with the credit system.

This document intentionally excludes pricing, credit amounts and subscription quotas.

Those are defined separately in the Pricing Specification.

---

# Philosophy

Discovery Credits exist for one purpose:

> Recover the external variable costs incurred by Loqi.

Credits are **not** a monetization strategy.

Credits are **not** premium features.

Credits are simply an abstraction of external infrastructure costs.

Customers purchase Loqi.

Discovery Credits allow Loqi to sustainably provide expensive third-party capabilities without exposing provider complexity.

---

# Guiding Principles

## Principle 1

Credits represent external cost.

If Loqi does not incur an external cost, Discovery Credits should not be consumed.

---

## Principle 2

Customer-owned data is always free to search.

Workspace Knowledge belongs to the customer.

Searching it should never consume credits.

---

## Principle 3

Provider complexity is invisible.

Customers never purchase Apollo credits.

Customers never purchase Hunter credits.

Customers never purchase People Data Labs credits.

Customers purchase Discovery Credits.

Loqi manages provider selection internally.

---

## Principle 4

Credits should be predictable.

Users should always know:

- why credits were used
- how many credits remain
- which action consumed them

Credit consumption should never feel random.

---

## Principle 5

Credits should be recoverable.

If Loqi fails before completing an operation, credits should be refunded automatically whenever technically possible.

---

# Credit Lifecycle

```
Credits Granted

↓

Credits Available

↓

Operation Requested

↓

Cost Estimated

↓

Operation Executed

↓

Credits Deducted

↓

Usage Recorded

↓

Remaining Balance Updated
```

Every credit transaction must be auditable.

---

# Credit Wallet

Every Workspace owns a Credit Wallet.

The wallet is responsible for:

- Current Balance
- Reserved Credits
- Consumed Credits
- Transaction History
- Credit Source
- Expiration Rules (if applicable)

Credits belong to the Workspace.

They are never tied to individual users.

---

# Credit Sources

Credits may originate from:

- Subscription Allocation
- Purchased Credit Packs
- Promotional Credits
- Trial Credits
- Manual Administrative Credits

Regardless of origin, all credits behave identically once issued unless explicitly specified otherwise.

---

# Credit Consumption

Credits are consumed only for operations that require external paid infrastructure.

Examples include:

- External Lead Discovery
- Contact Discovery
- Company Discovery
- Company Enrichment
- Contact Enrichment
- Email Verification
- Phone Discovery
- Future paid provider integrations

The exact credit cost per operation is defined in the Pricing Specification.

---

# Non-Credit Operations

The following operations must never consume Discovery Credits.

## Workspace

- Workspace creation
- Workspace configuration
- Team management

---

## Knowledge

- CSV imports
- CRM imports
- Google Sheets synchronization
- Searching Workspace Knowledge
- Contact management
- Company management
- Deduplication

---

## Intelligence

- AI email generation
- AI personalization
- AI summaries
- AI campaign generation
- AI recommendations

---

## Campaigns

- Campaign creation
- Scheduling
- Templates
- Draft generation
- Sequence creation

---

## Communication

- Sending emails
- Tracking replies
- Attachments
- Mailbox management

---

## Analytics

- Reports
- Dashboards
- Campaign analytics

These capabilities are covered by subscriptions rather than credits.

---

# Discovery Workflow

Every Discovery request follows the same execution flow.

```
User Request

↓

Workspace Knowledge

↓

Workspace Cache

↓

Previous Discoveries

↓

External Providers

↓

Merge Results

↓

Deduplicate

↓

AI Ranking

↓

Return Results
```

Discovery Credits are consumed **only** if Loqi reaches the External Providers stage.

If results are returned entirely from Workspace Knowledge or cache, no credits should be consumed.

---

# Cache Policy

Previously discovered information should be reused whenever possible.

The platform should avoid paying external providers multiple times for identical information.

If valid cached information already exists:

- Return cached data.
- Do not query providers.
- Do not consume credits.

Caching improves:

- customer experience
- platform performance
- operating margins

---

# Credit Estimation

Whenever possible, Loqi should estimate credit consumption before executing an operation.

Customers should understand:

- expected cost
- remaining balance
- available credits

before committing to expensive operations.

---

# Credit Transactions

Every credit deduction should generate an immutable transaction record.

Each record should include:

- Workspace
- Timestamp
- Operation
- Credit Amount
- Provider (internal only)
- Result
- Status
- Refund Status

Users should only see customer-friendly information.

Internal provider details remain hidden.

---

# Failure Handling

Credits should only be permanently deducted after a successful external operation.

Possible outcomes:

## Success

Credits deducted.

---

## Partial Success

Deduct only the credits corresponding to successful provider operations.

---

## Failure

Refund credits automatically whenever technically possible.

---

## Timeout

Retry according to provider policy.

If no successful result is returned, credits should not be permanently consumed.

---

# Fair Use

Discovery Credits exist to recover infrastructure costs.

Loqi may implement reasonable protections against:

- automated abuse
- excessive retries
- scripted exploitation
- fraudulent activity

These protections should never interfere with legitimate customer workflows.

---

# Future Compatibility

The credit economy should remain independent from specific providers.

New providers should integrate into the Discovery Engine without requiring changes to the customer experience.

Adding or replacing providers must never require customers to learn a new billing model.

---

# Non-Goals

Discovery Credits are **not** intended to:

- Meter AI usage
- Charge for customer-owned data
- Monetize every platform interaction
- Expose provider-specific pricing
- Encourage unnecessary purchases

The purpose of Discovery Credits is sustainability—not complexity.

---

# Long-Term Vision

As Loqi expands its Discovery Network, customers should continue interacting with a single, unified credit system.

Regardless of how many providers power the platform internally, customers should always experience one consistent Discovery Engine.

Discovery Credits should remain a simple abstraction over an increasingly sophisticated infrastructure.

---

# Guiding Principle

Every credit consumed should correspond to measurable customer value.

Customers should never feel like they are paying for system operations.

They should feel like they are paying for successful outcomes.