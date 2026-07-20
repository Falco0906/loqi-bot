PRICING_SIMULATOR.md
# Pricing Simulator

Version: 1.0

Status: Internal

Owner: Loqi
Purpose

The Pricing Simulator models the economics of Loqi subscriptions.

Its purpose is to validate that every pricing tier remains profitable under realistic customer behavior while maintaining a simple user experience.

The simulator is never customer-facing.

It is used to:

Design subscription tiers
Validate Discovery Credit allocations
Measure provider spend
Measure AI spend
Forecast gross margins
Test pricing changes before launch
Economic Philosophy

Every customer interaction belongs to one of four cost categories.

Revenue

↓

Provider Costs

↓

AI Costs

↓

Infrastructure

↓

Gross Margin

The simulator evaluates every plan through this pipeline.

Cost Categories
1. Provider Costs

External infrastructure.

Examples

People Data Labs
Hunter

Charged per lookup.

2. AI Costs

LLM usage.

Examples

Email generation
Personalization
Follow-up writing

Included within subscription.

Never billed separately.

3. Infrastructure

Internal costs.

Examples

PostgreSQL
Vector database
Storage
Queue workers
Email rendering
Monitoring

Mostly fixed.

4. Support

Human cost.

Examples

Support
Onboarding
Customer success

Mostly plan-dependent.

Revenue

Revenue is calculated from:

Subscription Price

Credit Pack Purchases

Enterprise Add-ons

Customer Profiles

The simulator evaluates four customer profiles.

1. Light User

Represents:

Small founders

Consultants

Freelancers

Monthly Activity
Action	Quantity
Company Searches	100
Companies Opened	50
People Found	150
Prospect Enrichments	100
Emails Found	80
Emails Verified	80
AI Emails Generated	300
Campaigns	5
2. Typical User

Represents:

Growing startups

Sales teams

Monthly Activity
Action	Quantity
Company Searches	500
Companies Opened	250
People Found	800
Prospect Enrichments	500
Emails Found	600
Emails Verified	600
AI Emails	2,000
Campaigns	30
3. Heavy User

Represents:

Agencies

Outbound teams

Monthly Activity
Action	Quantity
Company Searches	2,000
Companies Opened	1,200
People Found	5,000
Prospect Enrichments	4,000
Emails Found	4,000
Emails Verified	4,000
AI Emails	15,000
Campaigns	150
4. Power User

Represents:

Largest non-enterprise customers.

Stress test.

Action	Quantity
Company Searches	5,000
Companies Opened	3,000
People Found	12,000
Prospect Enrichments	10,000
Emails Found	8,000
Emails Verified	8,000
AI Emails	40,000
Campaigns	500
Provider Cost Inputs

The simulator uses configurable provider pricing.

PDL

Company Record

$X

Person Record

$Y
Hunter

Email Finder

$A

Verification

$B

Changing provider pricing should require changing these variables only.

AI Cost Inputs

Examples

Average prompt tokens

Average completion tokens

Average cost per email

Average cost per personalization

These values should be configurable.

Infrastructure Inputs

Monthly cost estimates.

Examples

Database

Storage

Workers

Logging

Monitoring

Authentication

Email delivery

All configurable.

Simulator Formula
Revenue

-

Provider Cost

-

AI Cost

-

Infrastructure Allocation

-

Support Allocation

=

Gross Profit

Gross Margin

Gross Profit

/

Revenue
Margin Targets
Metric	Target
Absolute Minimum	60%
Healthy	70%
Excellent	80%+

Plans falling below target should be redesigned.

Sensitivity Tests

The simulator should support:

Provider Price Increase

PDL

+10%

+20%

+50%

Hunter

+10%

+20%

AI Cost Increase

2×

3×

5×

Cache Efficiency

Best Case

90%

Average

70%

Worst

30%

This measures how much caching affects profitability.

Abuse Simulation

Example

Customer

↓

Consumes every credit

↓

Generates maximum AI

↓

Runs every automation

↓

Uses every mailbox

↓

Maximum API usage

Question:

Can Loqi still make money?

If not,

the plan needs adjustment.

Upgrade Trigger Simulation

Questions

When should users:

Buy more credits?

Upgrade?

Stay?

The simulator should estimate:

Discovery Credits Remaining

↓

Monthly Usage Trend

↓

Recommendation

Upgrade

OR

Buy Credit Pack
Final Output

For every plan the simulator reports:

Monthly Revenue

Provider Spend

AI Spend

Infrastructure

Support

Gross Profit

Gross Margin

Margin %

Credit Consumption

Average Cost Per Customer

Upgrade Risk

Profitability Status

Success Criteria

The Pricing Simulator is complete when:

✓ Every plan exceeds target margin.

✓ Discovery Credits cover provider costs.

✓ Unlimited AI remains sustainable.

✓ Worst-case users remain profitable.

✓ Pricing can adapt without changing product behavior.


---

# One thing I would change from the draft above

I **wouldn't use fixed activity numbers** (100 searches, 500 searches, etc.) as the source of truth.

Instead, I'd make the simulator **credit-driven**.

For example:

| Plan | Included Discovery Credits | Expected Usage | Revenue |
|------|---------------------------:|---------------:|---------:|
| Starter | 500 | 60–80% | $X |
| Growth | 2,500 | 70–90% | $Y |
| Scale | 10,000 | 80–95% | $Z |

Then the simulator derives provider calls from how those credits are typically spent (company search vs. people search vs. email finding, etc.). That's much closer to how the product will actually be sold and managed.

---

## I think we should do one more thing

Once this document is in place, I'd like to build a **real spreadsheet with actual PDL and Hunter costs**, realistic usage distributions, and different subscription prices. That will let us answer questions like:

- Should Starter be **$29 or $39?**
- Should it include **500 or 750 Discovery Credits?**
- What's the expected gross margin for each plan?

That spreadsheet will let us **freeze Loqi's pricing with confidence**, rather than relying on intuition. 