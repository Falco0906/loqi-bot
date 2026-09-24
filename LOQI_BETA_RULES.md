1. The Beta’s single purpose

Loqi Beta helps a user turn their existing lead data into prioritized, researched, actionable outbound opportunities.

The beta exists to validate the intelligence layer, not autonomous outbound automation.

The core user journey is:

Bring data
    ↓
Search / filter
    ↓
Select leads
    ↓
Analyze with Loqi
    ↓
Prioritize
    ↓
Understand why
    ↓
Create strategy
    ↓
Generate outreach
    ↓
Human decides what happens next

If a proposed feature does not improve this loop, it is not a beta priority.

⸻

2. User owns the lead supply

This is probably the most important rule.

Beta:

Loqi does not automatically provide leads.

Users provide the lead universe through:

* CSV
* existing lead database
* CRM connection when implemented
* other user-provided sources

The user then searches and selects from that universe.

Therefore:

Lead sourcing ≠ active beta capability
Lead discovery/search = active beta capability

This distinction needs to exist everywhere—in the UI, API behavior, feature flags, and documentation.

⸻

3. Existing autonomous systems are preserved

DO NOT DELETE existing autonomous functionality.

Existing systems such as:

* automatic lead generation
* lead sourcing integrations
* Gmail sending
* automated follow-ups
* autonomous workflows
* existing agents
* existing integrations

remain in the repository.

They are deactivated for Beta.

The purpose is:

Existing code
      │
      ├── Beta-active path
      │
      └── Deferred path
             ↓
       preserved for later

We are putting functionality into hibernation, not destroying it.

⸻

4. No dead-code cleanup during this phase

This one is specifically important given what you said.

During the beta transition:

Do not remove existing backend code merely because Beta doesn’t use it.

Don’t:

* delete old services
* delete old endpoints
* delete integrations
* rewrite working systems
* rename large architectural sections
* consolidate unrelated code
* “clean up” old agents

unless the change is required for the beta to function safely.

This slightly differs from the repo’s normal refactoring guidance because we’re deliberately running a temporary product-mode configuration while preserving future capability. The existing architecture rules already permit backwards-compatible coexistence during migrations.  

⸻

5. Feature disabling must be explicit

We should have one canonical Beta configuration.

Conceptually:

const BETA_FEATURES = {
  // DEFERRED
  automaticLeadGeneration: false,
  automaticEmailSending: false,
  automaticFollowups: false,
  autonomousAgents: false,
  // ACTIVE
  csvImport: true,
  leadDatabase: true,
  leadSearch: true,
  leadFiltering: true,
  leadSelection: true,
  leadAnalysis: true,
  leadScoring: true,
  strategyGeneration: true,
  outreachGeneration: true,
};

But this is a policy object, not necessarily the exact implementation.

Before creating it, we inspect the existing feature/config system and use the existing canonical mechanism if one exists.

No duplicate flag systems.

That follows the repo’s existing rule of searching for canonical implementations before introducing another one.  

⸻

6. Frontend controls what the user can access

If a feature is disabled for Beta:

it should not appear as an actionable feature in the UI.

For example:

Don’t show:

Generate leads automatically

Don’t show:

Send campaign

Don’t show:

Start autonomous campaign

Instead:

Import leads
Discover
Analyze
Prioritize
Create strategy
Generate outreach

We aren’t deleting backend capabilities.

We’re defining the Beta product surface.

⸻

7. Backend is still the authority

The frontend must never be the only protection.

If:

automaticEmailSending = false

the backend must also refuse/disable the corresponding Beta operation.

Because:

Frontend hiding ≠ feature disabling

The frontend controls discoverability.

The backend controls capability.

This is also consistent with Loqi’s existing rule that business logic belongs in the backend rather than React.  

⸻

8. Human approval is mandatory for outbound

This becomes a hard Beta boundary.

Loqi may:

research
↓
score
↓
recommend
↓
generate

Loqi may not:

generate
↓
automatically send

The final action must remain with the user.

So:

Generate outreach
      ↓
Review
      ↓
Copy / export / manually send

No automatic Gmail sending in Beta.

⸻

9. Loqi does not pretend it knows something it doesn’t

This should be a hard intelligence rule.

If Loqi has no evidence for something:

Unknown

is preferable to:

probably
likely
seems like

presented as fact.

For example:

❌

Acme is struggling with operational inefficiency.

If we don’t have evidence.

Better:

Acme is hiring for three operations roles, which may indicate increasing operational workload.

And ideally:

Evidence
→ Acme careers page
→ Operations Manager opening
→ Headcount growth signal

This aligns directly with the existing Loqi rule that LLMs can explain and personalize structured reality but must not invent facts or business state.  

⸻

10. Intelligence is more important than the score

A number alone isn’t useful.

Bad:

Acme
87/100

Good:

Acme
87/100
Why?
• ICP matches
• Target role matches
• Relevant hiring signal
• Company size fits
• Product appears relevant
Recommended angle:
Operational automation
Evidence:
...

The beta must always answer:

Why did Loqi reach this conclusion?

⸻

11. Scoring must be explainable

Every lead score must have an underlying structured basis.

Conceptually:

ICP Fit
Role Fit
Company Fit
Signal Strength
Data Quality
────────────────
Overall Priority

The exact scoring model comes later.

But the rule is:

No opaque “AI says 93/100” scoring.

And ideally the actual scoring logic should be deterministic wherever possible, consistent with the repository’s existing deterministic-first rule.  

⸻

12. Research only happens when the user asks for it

This is how we control API costs.

If a user uploads:

10,000 leads

Loqi does not immediately research 10,000.

Instead:

10,000 leads
     ↓
Search/filter
     ↓
User selects 20
     ↓
Analyze 20

This is a foundational Beta cost rule.

⸻

13. Lead database and lead analysis are separate concepts

This distinction should exist in the architecture.

Lead Database

Stores:

Name
Email
Company
Title
Website
LinkedIn
Location
Industry
...

Loqi Intelligence

Produces:

ICP fit
Signals
Research
Pain hypotheses
Priority
Strategy
Outreach

Don’t mix the two.

The database is the input universe.

Loqi intelligence is the interpretation layer.

⸻

14. Discover does not mean “Loqi automatically discovers”

The Discover page is a user-controlled search interface over available data.

Its job is:

Search
Filter
Categorize
Sort
Select

Not:

"Go find me 10,000 leads."

This is where the Hunter inspiration fits.

The UI can feel like Hunter:

Search
│
├── Location
├── Industry
├── Keywords
├── Company size
├── Company
├── Job title
├── Company type
├── Job openings
├── Technology
├── Funding
└── Year founded

But the underlying database is the user’s available lead data, not Loqi’s autonomous lead supply.

⸻

15. Suggested searches are allowed

This is a nice intelligence feature.

Loqi can use company context to suggest searches:

Suggested for you
Find SaaS companies with 50–500 employees
Find companies hiring operations leaders
Find companies expanding their sales teams

But clicking a suggestion should still result in:

query/filter
     ↓
user sees results
     ↓
user selects

Not automatic lead acquisition.

⸻

16. CRM integration is an input, not an automation engine

When we add CRM integrations:

CRM
 ↓
Loqi Lead Database
 ↓
User searches/selects
 ↓
Loqi intelligence

Not:

CRM
 ↓
Loqi autonomously contacts everyone

The CRM is simply another source of user-owned lead data.

⸻

17. CSV is the first-class import mechanism

For Beta v0.1:

CSV should be the guaranteed path.

CRM connectors can be added incrementally.

If we don’t have a connector implemented yet:

HubSpot
Coming soon

rather than pretending it’s functional.

⸻

18. One canonical lead

We should not create separate competing lead representations.

A lead imported through:

CSV

and a lead coming from:

CRM

should ultimately become the same canonical Loqi lead entity.

This follows the existing architecture requirement for one canonical source of truth.  

⸻

19. Don’t build the future yet

Explicitly out of scope:

❌ Automatic lead generation
❌ Automatic email sending
❌ Autonomous followups
❌ Full campaign automation
❌ Complex agent orchestration
❌ Massive lead marketplace
❌ 15 CRM integrations
❌ Advanced analytics
❌ Billing
❌ Enterprise permissions
❌ Huge workflow builder

Unless something becomes necessary for the Beta loop.

⸻

20. The Beta has one success criterion

Not:

“Did we ship all the features?”

Not:

“Does the architecture look impressive?”

Not:

“Can Loqi autonomously run outbound?”

The Beta question is:

Does Loqi provide enough intelligence on a user’s existing leads that they would use it for their real outbound work?

Everything we’re building should help answer that.

⸻

The actual foundation

I’d condense all of that into this:

                    LOQI BETA
                       │
              ┌────────┴────────┐
              │                 │
           USER DATA        LOQI INTELLIGENCE
              │                 │
          CSV / CRM             │
              │                 │
              ▼                 ▼
       ┌─────────────┐   ┌──────────────┐
       │ Lead Database│──▶│   Analysis   │
       └─────────────┘   └──────┬───────┘
                                │
                         ┌──────┴──────┐
                         ▼             ▼
                      Priority      Strategy
                         │             │
                         └──────┬──────┘
                                ▼
                           Outreach
                                │
                                ▼
                          HUMAN DECISION

And the philosophical rule at the very top:

Loqi Beta is intelligence-first, user-controlled, evidence-based, and non-autonomous.

That’s the foundation.

The existing repo actually already has “Intelligence Before Automation” and “Automation Must Be Conservative” as implementation principles, so we’re not fighting the architecture we’re inheriting—we’re making the current product direction obey those principles much more aggressively for this experiment.  