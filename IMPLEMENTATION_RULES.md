# Loqi Implementation Rules

This document defines the architectural rules that every implementation must follow.

These are not suggestions.

Violating them means the implementation is incorrect.

---

# 1. The World Model is the source of truth.

Everything eventually flows through the World Model.

Providers never communicate directly with UI.

Providers emit events.

Events update the World Model.

Reasoning reads the World Model.

Narrative communicates the reasoning.

Experience renders the narrative.

Architecture:

Providers
    ↓
Events
    ↓
World Model
    ↓
Reasoning
    ↓
Narrative
    ↓
Experience

---

# 2. Separate Thinking from Communication.

Never mix reasoning with writing.

Reasoning decides:

- priorities
- recommendations
- risks
- opportunities
- health
- attention

Narrative only communicates those decisions.

LLMs never determine business logic.

---

# 3. Deterministic First.

If something can be computed with code,

do not ask an LLM.

Examples:

✓ campaign ranking

✓ priority scoring

✓ reply detection

✓ health scoring

✓ workflow continuation

✓ bottleneck detection

✗ "Which campaign is most important?"

That belongs in deterministic reasoning.

---

# 4. LLMs Never Invent Reality.

Narrative receives structured data.

It may:

- summarize
- explain
- rewrite
- simplify
- personalize

It may never:

- invent priorities
- invent recommendations
- invent risks
- invent facts
- infer missing business state

---

# 5. Events Are Immutable.

Events are facts.

Never modify history.

Never overwrite events.

Always append.

World Model state is derived from events.

---

# 6. Deltas Drive Narrative.

Mission Control should answer:

"What changed?"

not

"What exists?"

Every briefing should primarily discuss changes since the user's last acknowledgement.

---

# 7. Reasoners Are Small.

Do not create God objects.

Every reasoner has one responsibility.

Examples:

PriorityReasoner

AttentionReasoner

HealthReasoner

RiskReasoner

OpportunityReasoner

RecommendationReasoner

Each must be independently testable.

---

# 8. Signals Describe Reality.

Signals do not make decisions.

Signals expose facts.

Examples:

pending_reviews

launch_ready

reply_rate

lead_quality

stalled_days

Reasoners interpret signals.

---

# 9. UI Never Contains Business Logic.

Frontend renders.

Backend reasons.

Never duplicate business rules in React.

---

# 10. Preserve Contracts.

Prefer adapters over rewrites.

Public APIs should remain stable.

Frontend should not break because architecture improved.

---

# 11. Build Extensible Systems.

Whenever introducing a new component,

ask:

"How will the next five features plug into this?"

Prefer extension over replacement.

---

# 12. Backwards Compatibility During Migration.

During architecture migrations:

Old implementation may coexist.

Fallbacks are acceptable.

Feature regressions are not.

---

# 13. Every Layer Has One Responsibility.

Providers

Acquire information.

Events

Record facts.

World Model

Represent current understanding.

Signals

Describe reality.

Reasoning

Interpret reality.

Narrative

Communicate reality.

Experience

Present reality.

Never violate these boundaries.

---

# 14. Intelligence Before Automation.

Loqi should become smarter

before

it becomes more autonomous.

Correct decisions matter more than automatic decisions.

---

# 15. Automation Must Be Conservative.

The default action is not automation.

The default action is recommendation.

Automation should only occur when confidence is high and user expectations are clear.

Escalate uncertainty to the user.

---

# 16. Every New Feature Must Answer:

Which events does it emit?

How does it affect the World Model?

What signals does it produce?

Which reasoners consume those signals?

How does Narrative communicate it?

Which UI surfaces display it?

If these questions cannot be answered,

the feature is likely being implemented in the wrong place.

---

# 17. Prefer Composition Over Inheritance.

Small modules.

Small services.

Small reasoners.

Composable pipelines.

Avoid large classes.

---

# 18. Minimize LLM Surface Area.

LLMs should receive:

structured data

↓

produce natural language

Nothing more.

---

# 19. Experience Is Editorial.

Mission Control is not a dashboard.

It is a briefing.

Show:

What changed.

Why it matters.

What needs attention.

What should happen next.

Hide everything else until requested.

---

# 20. Architecture Should Disappear.

Once the platform is stable,

future work should primarily improve:

- intelligence
- UX
- integrations
- reliability
- speed

Avoid unnecessary architectural rewrites.

The architecture exists to make feature development easier—not to become the product itself.