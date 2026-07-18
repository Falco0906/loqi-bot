# Reasoning Engine

## Philosophy

The Reasoning Engine is the decision-making layer of Loqi.

It **consumes** structured Conversation Intelligence.
It **produces** reasoned decisions.
It **never** executes actions or generates content.

**The Reasoning Engine answers:**
"Given everything we know, what should happen next?"

**It does not answer:**
"How should the email be written?"

This separation means future AI models, planners, and communication channels can evolve independently while sharing the same decision-making foundation.

## Architectural Principles

1. **Separate understanding from reasoning** — Conversation Intelligence provides structured understanding; Reasoning Engine decides.
2. **Separate reasoning from execution** — The engine produces decisions only; executors act on decisions.
3. **Separate execution from communication** — Email generators, schedulers, and CRM actions are independent consumers.
4. **Every decision is explainable** — No black-box decisions. Every output includes evidence, reasoning, and confidence.

## Decision Pipeline

```
Conversation Intelligence
    │
    ▼
Goal Selection
    │  What are we trying to achieve?
    ▼
Priority Assessment
    │  How urgent is this conversation?
    ▼
Risk Assessment
    │  What are the risks?
    ▼
Confidence Assessment
    │  How certain are we?
    ▼
Policy Evaluation
    │  Are there rules that override?
    ▼
Decision Synthesis
    │
    ▼
Reasoning Result
```

Each stage is independently testable. Failures in one stage do not block others.

## Models

### ReasoningResult (top-level container)

| Field | Type | Description |
|-------|------|-------------|
| `conversation_id` | string | Source conversation |
| `decision` | ReasoningDecision | The synthesized decision |
| `goal` | GoalSelection | Primary + alternative goals |
| `priority` | PriorityAssessment | Numeric + qualitative priority |
| `risk` | RiskAssessment | Numeric + qualitative risk |
| `confidence` | ConfidenceAssessment | Per-component confidence |
| `created_at` | datetime | When reasoning was performed |
| `pipeline_version` | string | Version of the reasoning pipeline |

### ReasoningDecision

| Field | Type | Description |
|-------|------|-------------|
| `type` | DecisionType | One of 10 decision types (see below) |
| `priority` | DecisionPriority | LOW / MEDIUM / HIGH / CRITICAL |
| `risk` | RiskLevel | LOW / MEDIUM / HIGH |
| `confidence` | float | 0-1 overall confidence |
| `primary_goal` | GoalType | What to achieve |
| `alternative_goal` | GoalType | Fallback objective |
| `evidence` | list[str] | Supporting signals |
| `reasoning` | list[str] | Why this decision was made |
| `policy_results` | list[PolicyEvaluation] | Policy check results |

### Decision Types

| Type | Description |
|------|-------------|
| `reply` | Respond to prospect |
| `wait` | Do nothing, monitor |
| `schedule_follow_up` | Queue a follow-up |
| `request_human_review` | Escalate to human |
| `escalate` | Route to senior team |
| `book_meeting` | Schedule a meeting/demo |
| `close_conversation` | End the conversation |
| `stop_outreach` | Cease all contact |
| `continue_nurturing` | Maintain awareness |
| `request_more_information` | Ask clarifying questions |

### Goal Types

| Goal | When selected |
|------|-------------|
| `book_demo` | Demo requested or strong interest |
| `provide_pricing` | Pricing or budget discussion |
| `qualify_needs` | Technical or information request |
| `overcome_objection` | Active objections present |
| `keep_alive` | No clear signal |
| `gather_information` | Insufficient context |
| `confirm_interest` | Interest expressed |
| `schedule_meeting` | Meeting requested |
| `handoff_to_sales` | Enterprise signals |
| `re_engage` | Not interested or stale |

## Components

### Goal Selector (`goal_selector.py`)

Maps intent labels and buying signals to a primary goal and alternative goal. Pure deterministic logic — no AI calls.

| Input Signal | Primary Goal |
|-------------|-------------|
| `demo_request` | book_demo |
| `meeting_request` | schedule_meeting |
| `pricing_discussion` | provide_pricing |
| Active objections | overcome_objection |
| `interested` | confirm_interest |
| `information_request` | qualify_needs |
| `not_interested` | re_engage |
| No intents | gather_info |

### Priority Engine (`priority_engine.py`)

Calculates urgency on a 0-100 scale from:

- **Buying signal strength** — VERY_STRONG → +15 each, VERY_WEAK → -5 each
- **Conversation health** — Health score deviation from 50% midpoint
- **Objections** — HIGH → -10, MEDIUM → -5, LOW → -2
- **Engagement** — Positive intents +8 each, negative -8 each

Mapped to levels:
- 75+ → CRITICAL
- 55-74 → HIGH
- 35-54 → MEDIUM
- 0-34 → LOW

### Risk Assessor (`risk_assessor.py`)

Evaluates risk on a 0-100 scale from:

- **Objections** — HIGH severity → +20, multiple objections → +10
- **Conversation health** — Below 30 → +25, below 50 → +15
- **Buying signals** — Contract/procurement signals reduce risk
- **Decision-maker presence** — No DM identified → +10

Mapped to levels:
- 50+ → HIGH
- 25-49 → MEDIUM
- 0-24 → LOW

### Confidence Engine (`confidence_engine.py`)

Calculates 0-1 confidence from weighted components:

| Component | Weight | Source |
|-----------|--------|--------|
| Intent confidence | 30% | Average of top 3 intent confidences |
| Signal confidence | 25% | Average of top 3 signal confidences |
| Objection confidence | 15% | Inverse of objection confidence (higher objections = lower overall) |
| Entity confidence | 10% | Average of entity confidences |
| Completeness | 20% | Ratio of populated intelligence dimensions |

Each component includes a textual explanation of why confidence is high or low.

### Policy Engine (`policy_engine.py`)

Evaluates configurable business rules that can override decisions.

Default policies:

| Policy | Behavior |
|--------|----------|
| `require_review_first_reply` | First reply to a new prospect requires human review |
| `no_auto_close` | Conversations cannot be auto-closed |
| `confidence_threshold` | Confidence < 0.75 requires human review |
| `escalate_enterprise_signals` | Procurement/contract signals trigger escalation |
| `follow_up_health_threshold` | Follow-up requires health score ≥ 40 |
| `require_review_high_risk` | HIGH risk conversations require human review |

Policies can be registered at runtime:
```python
from services.reasoning.policy_engine import register_policy, Policy

register_policy(Policy(
    name="custom_policy",
    evaluate=my_evaluate_fn,
    config={"enabled": True},
))
```

### Reasoning Pipeline (`reasoning_pipeline.py`)

Orchestrates all stages. Each stage runs independently — failures are caught and logged.

The pipeline:
1. Selects goals from intelligence
2. Assesses priority
3. Assesses risk
4. Assesses confidence
5. Synthesizes the decision
6. Evaluates policies
7. Applies policy overrides (e.g., forces `request_human_review` if policies require it)

## Explainability

Every decision includes:
- **Evidence** — Structured signals that informed the decision
- **Reasoning** — Natural language explanation of the logic
- **Confidence breakdown** — Per-component confidence with explanations
- **Policy results** — Which policies applied and their outcomes
- **Goal reasoning** — Why each goal was selected

```json
{
  "decision": {
    "type": "reply",
    "priority": "high",
    "confidence": 0.91,
    "evidence": [
      "Intent: pricing_discussion (0.85)",
      "Buying signal: mentioned_budget (very_strong)",
      "Objection: budget (high)",
      "Goal: provide_pricing"
    ],
    "reasoning": [
      "Prospect requested pricing",
      "Strong buying signal detected",
      "Active budget objection to overcome"
    ]
  }
}
```

## Frontend Integration

The Reasoning Panel appears on the Conversation Detail page sidebar.

Displays:
- **Recommended Decision** — Type + explanation
- **Goal** — Primary + alternative
- **Priority** — Level badge + numeric score bar
- **Risk** — Level badge
- **Confidence** — Ring visualization + breakdown
- **Policy Results** — Per-policy pass/fail/review status
- **Evidence** — Supporting signals

Read-only — no action buttons, no execution.

## Extension Points

The reasoning engine is designed to be consumed by:

| Consumer | What they use |
|----------|-------------|
| **Planner** | Goals and priority for scheduling |
| **AI Reply Generator** | Decision type + goal for prompt context |
| **Human Approval Queue** | Reasoning + evidence for review |
| **CRM Workflows** | Decision type + risk for routing |
| **Analytics** | Decision types, confidence, priority patterns |
| **Executive Dashboard** | Aggregate reasoning trends |

No consumer should need to re-analyze conversation intelligence.

## Lifecycle

1. Message received → Conversation Intelligence computed
2. Intelligence stored in conversation memory
3. Reasoning engine consumes intelligence → produces decision
4. Decision consumed by executor (in future phases)
5. Human reviews if policy requires
6. Action executed → result fed back into intelligence

The reasoning engine is stateless. It can be re-run at any point with updated intelligence.

## Future Evolution

- **AI-assisted reasoning** — LLMs can provide soft signals that feed into the deterministic engine
- **Multi-model confidence** — Different AI models produce confidence scores that the engine normalizes
- **Learning from outcomes** — Historical decision outcomes can tune weights and policies
- **Behavioral policies** — Policies based on prospect behavior patterns
- **Dynamic weights** — Industry-specific or persona-specific weight profiles
