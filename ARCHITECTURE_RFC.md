# Loqi Architecture RFC

**Status:** Draft  
**Scope:** Long-term architecture (2-year horizon)  
**Philosophy Source:** `research/product_design_strategy_conversation.md`  

---

## 0. Executive Summary

Loqi is an AI-native outbound workspace.

This document describes the architecture that delivers the product philosophy:

- **Narrative AI** — Loqi communicates through briefings, not dashboards
- **AI prepares, human decides** — Loqi researches, drafts, recommends; humans approve, reject, redirect
- **Conversational workspace** — the product reads like a report, not a CRUD app
- **Five workspaces, five emotions** — Mission Control (relief), Discovery (confidence), Campaigns (momentum), Inbox (clarity), Knowledge (alignment)

The architecture is organized into four layers:

```
┌──────────────────────────────────────────────────┐
│                  Experience Layer                  │
│     Mission Control │ Discovery │ Campaigns        │
│     Inbox │ Knowledge │ Tell Loqi                  │
├──────────────────────────────────────────────────┤
│               Reasoning Layer                      │
│     World Model │ Briefing Generator               │
│     Recommendation Engine │ Narrative Engine       │
├──────────────────────────────────────────────────┤
│             Intelligence Layer                     │
│     Conversation Pipeline │ Research Pipeline      │
│     Memory System │ Learning System                │
├──────────────────────────────────────────────────┤
│             Execution Layer                        │
│     Workflow Engine │ Adapter Registry             │
│     Provider System │ Scheduler                    │
└──────────────────────────────────────────────────┘
```

Data flows **up** (events → state → reasoning → narrative) and **down** (user decisions → execution → events).

---

## 1. Core Loop

Loqi's product loop is:

```
Goal
  ↓
Research
  ↓
Review
  ↓
Launch
  ↓
Learn
```

The architecture must make this loop **continuous, not linear**. Loqi should always be researching, always learning. The user enters the loop at Review — they set goals and launch decisions, then Loqi carries the rest forward.

```
                  ┌─────────────┐
                  │   Learn     │◄────────────────────┐
                  └──────┬──────┘                     │
                         │                            │
                  ┌──────▼──────┐                     │
                  │    Goal     │  (user sets once)   │
                  └──────┬──────┘                     │
                         │                            │
                  ┌──────▼──────┐             ┌───────┴────────┐
                  │  Research   │             │  Auto-handle   │
                  └──────┬──────┘             │  (routine)     │
                         │                    └────────────────┘
                  ┌──────▼──────┐
                  │   Review    │  ◄── User enters here
                  └──────┬──────┘
                         │
                  ┌──────▼──────┐
                  │   Launch    │
                  └──────┬──────┘
                         │
                         └──► Learn (top)
```

The architecture must support this loop at two speeds:
- **Synchronous** — user opens Mission Control, sees what changed
- **Asynchronous** — Loqi researches overnight, surfaces results in the morning

---

## 2. Major Subsystems

### 2.1 World Model

The World Model is the persistent, unified representation of everything Loqi knows about the user's business at a given moment. It is the single source of truth.

**Concept:**

```
┌─────────────────────────────────────────────────────┐
│                   World Model                        │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │              Current State                    │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────────┐ │   │
│  │  │Business  │ │Pipeline  │ │Relationship  │ │   │
│  │  │Context   │ │State     │ │State         │ │   │
│  │  │          │ │          │ │              │ │   │
│  │  │ • ICP    │ │ • Leads  │ │ • Contacts   │ │   │
│  │  │ • Goals  │ │ • Drafts │ │ • Convos     │ │   │
│  │  │ • Prefs  │ │ • Sent   │ │ • Outcomes   │ │   │
│  │  │ • Prod   │ │ • Perf   │ │ • Signals    │ │   │
│  │  └──────────┘ └──────────┘ └──────────────┘ │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │              Event Log                        │   │
│  │  [e1, e2, e3, ..., en]                       │   │
│  │  • immutable append-only log                  │   │
│  │  • every state change is an event             │   │
│  │  • current state = projection of events       │   │
│  └──────────────────────────────────────────────┘   │
│                                                      │
│  ┌──────────────────────────────────────────────┐   │
│  │              Delta Computation                │   │
│  │  Given: last_viewed_at                       │   │
│  │  Returns: what changed since then             │   │
│  │  Used by: briefing generator                  │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

**Properties:**

- **Immutable event log** — every mutation is an append-only event. No deletes, no updates. Only new events that supersede old ones.
- **Projected state** — current state is derived by replaying events. This enables time-travel ("show me the state from yesterday") and debugging.
- **Delta-aware** — every state projection includes a `last_viewed_at` cursor. The briefing generator receives only what changed since the last view.
- **Persistent** — events are stored in Supabase. State is cached in memory but always recoverable from the event log.
- **Sealed** — external systems (Gmail, Apollo, etc.) feed events *into* the World Model. The World Model never reads from external systems directly during state projection.

**State shape (approximately):**

```
WorkspaceState:
  business_context:
    icp: str
    goals: list[Goal]
    preferences: list[Preference]
    product: ProductDescription
    constraints: list[str]

  pipeline:
    campaigns: list[CampaignState]
    leads: list[LeadState]
    drafts: list[DraftState]

  relationships:
    conversations: list[ConversationSummary]
    contacts: list[ContactState]
    outcomes: list[OutcomeState]

  system:
    providers: list[ProviderState]
    jobs: list[JobState]
    version: int
```

### 2.2 Event System

Every meaningful occurrence in Loqi is an event.

**Event schema:**

```yaml
event:
  id: uuid
  type: EventType    # see below
  timestamp: datetime
  session_id: str
  actor: str          # "system" | "user" | "gmail" | "apollo"
  data: dict          # type-specific payload
  sequence: int       # monotonic per session
  parent_id: uuid?    # causal relationship
```

**Event types (illustrative, not exhaustive):**

| Category | Events |
|---|---|
| **Business** | `campaign_created`, `campaign_status_changed`, `goal_set`, `goal_updated` |
| **Outreach** | `lead_discovered`, `draft_generated`, `draft_approved`, `draft_rejected`, `draft_sent` |
| **Inbox** | `message_received`, `reply_classified`, `reply_auto_handled`, `conversation_escalated` |
| **Knowledge** | `preference_learned`, `icp_updated`, `insight_generated`, `memory_consolidated` |
| **User** | `briefing_viewed`, `recommendation_actioned`, `recommendation_dismissed`, `tell_loqi_instruction` |
| **System** | `provider_connected`, `sync_completed`, `research_completed`, `error_occurred` |

**Causality:** Events carry a `parent_id` to form a causal graph. For example, `draft_approved` has `parent_id` pointing to `draft_generated`, which points to `lead_discovered`. This enables reasoning like: "You approved this draft, which was generated from a lead we found last Tuesday."

### 2.3 Reasoning Layer

The Reasoning Layer transforms World Model state into structured judgments. It has **no access to LLMs** — it is purely deterministic.

**Components:**

| Component | Input | Output |
|---|---|---|
| **Workspace Analyzer** | World Model state | Priorities, attention items, health score |
| **Delta Computer** | World Model state + `last_viewed_at` | What changed since last visit |
| **Opportunity Scorer** | Leads + historical outcomes | Prospect scores |
| **Auto-Handle Decider** | Reply classification + confidence | "Handle" or "Escalate" |
| **Preference Inferrer** | User actions over time | Updated preference weights |

**Design rules:**

- Reasoning is deterministic and fast (<50ms). It answers: *"Given what we know, what should Loqi think?"*
- Reasoning produces structured data (scores, priorities, classifications). It does not produce natural language.
- Reasoning is testable. Every reasoning function has unit tests with known inputs and expected outputs.
- Reasoning is the ground truth. If the narrative says something different from reasoning, the narrative is wrong.

### 2.4 Narrative Engine

The Narrative Engine transforms structured reasoning into natural language. This is where LLMs live.

**Components:**

| Component | Input | Output |
|---|---|---|
| **Briefing Writer** | Delta + Priorities + Health | Greeting + narrative lines + suggestion |
| **Recommendation Writer** | Opportunity scores + evidence | Natural-language recommendations |
| **Insight Writer** | Cross-campaign patterns | Intelligence items |
| **Confidence Phraser** | Confidence score | "I'd recommend moving forward" vs "This looks promising, but I'd like your opinion" |
| **Summary Writer** | Conversation analysis | "Prospect is interested, budget approved, wants timeline" |

**Design rules:**

- The Narrative Engine receives structured data only. It never reads the World Model directly.
- The Narrative Engine is stateless. All state is in the World Model.
- The Narrative Engine is cached by input hash. Same delta + same priorities = same briefing (for a given version).
- The Narrative Engine has a version pin. When the model improves, the version is bumped and caches invalidate.
- The Narrative Engine streams output. The first sentence appears before the last one is generated (enabling the unfolding-briefing experience).

**Separation of concerns:**

```
World Model State
       │
       ▼
Reasoning Layer (deterministic)
  ┌──────────────┐
  │  Priorities  │
  │  Attention   │
  │  Scores      │
  │  Health      │
  │  Delta       │
  └──────┬───────┘
         │ structured data only
         ▼
Narrative Engine (LLM)
  ┌──────────────┐
  │  Briefing    │
  │  Recommend   │
  │  Insights    │
  └──────┬───────┘
         │ natural language
         ▼
     Experience Layer (UI)
```

**Why this separation matters:**

- If the LLM produces bad copy, the underlying analysis is still correct. The UI can show structured data as a fallback.
- If the LLM is down, the product still works (structured view).
- Reasoning improvements don't require LLM calls.
- LLM improvements don't change the analysis — only how it's communicated.

### 2.5 Intelligence Layer

The Intelligence Layer is where Loqi learns. It runs asynchronously, outside the request-response path.

**Components:**

| Component | Purpose | Runs |
|---|---|---|
| **Conversation Pipeline** | Analyze every incoming message for intent, signals, stage | On message receipt |
| **Research Pipeline** | Find leads matching ICP, enrich company data | Scheduled + on-demand |
| **Memory System** | Persist structured memories from events | Event-driven |
| **Learning System** | Infer preferences, patterns, and insights from outcomes | Periodic (daily) |
| **Knowledge Builder** | Update organizational memory from accumulated evidence | Periodic (daily) |

**Conversation Pipeline (data flow):**

```
Incoming message (Gmail webhook / sync poll)
       │
       ▼
Intent Detector ───► "meeting_request" | "objection" | "follow_up" | ...
       │
       ▼
Buying Signal Detector ───► [hiring, funding, timing, ...]
       │
       ▼
Stage Classifier ───► "engaged" | "negotiation" | "churned" | ...
       │
       ▼
Followup Reasoner ───► { action, confidence, approval_required }
       │
       ▼
Auto-Handle Decider ───► "auto_reply" | "escalate_to_user"
       │
       ├──► auto_reply → Reply Generator → Gmail → Event Log
       │
       └──► escalate → World Model (inbox updated) → next briefing
```

**Memory System:**

Memory is an event-sourced, typed store. Every memory has:

- **Type** — conversation, contact, preference, outcome, decision
- **Source** — which pipeline created it
- **Confidence** — 0.0 to 1.0
- **Evidence** — links to the events that produced it
- **Relationships** — links to other memories

Memory is **immutable**. When new evidence arrives, a new memory is written with higher confidence. The old memory is not deleted — it's superseded. This enables time-travel and provenance:

```
User: "We now target fintech."

Memory created:
  { preference: "target_industry", value: "fintech",
    confidence: 0.3, source: "tell_loqi", supersedes: null }

Later, after 20 fintech leads perform well:
  { preference: "target_industry", value: "fintech",
    confidence: 0.8, source: "outcome_analysis", supersedes: [id1] }
```

**Learning System:**

Learning is periodic, not real-time. Daily consolidation runs:

1. **Outcome Analysis** — compare sent drafts to replied/not-replied. Infer what messaging patterns correlate with positive outcomes.
2. **Preference Reinforcement** — if user consistently approves casual-tone drafts, increase casual-tone preference confidence.
3. **Pattern Detection** — "Healthcare founders reply 2x more than SaaS founders" — detected from cross-campaign outcome data.
4. **Knowledge Update** — if enough evidence accumulates for a new insight, write it to Knowledge.

Learning produces **events** (`insight_generated`, `preference_learned`) which feed the World Model, which feeds the next briefing.

### 2.6 Execution Layer

The Execution Layer is where Loqi acts. It runs the workflows that turn decisions into outcomes.

**Components:**

| Component | Purpose |
|---|---|
| **Workflow Engine** | Execute multi-step plans (research → draft → approve → send) |
| **Adapter Registry** | Bridge between internal actions and external APIs (Gmail, Calendar, CRM) |
| **Provider System** | Registered communication channels (Gmail, future WhatsApp, Slack) |
| **Scheduler** | Time-based execution (send at 9 AM, follow up in 3 days, retry on failure) |
| **Outbound Pipeline** | Draft → approve → send → track lifecycle |

**Workflow types:**

| Workflow | Steps |
|---|---|
| `discover_leads` | Research → Enrich → Score → Present |
| `generate_drafts` | Analyze lead → Personalize → Generate → Store |
| `send_outreach` | Approve → Create Gmail draft → Send → Log → Create conversation |
| `handle_reply` | Analyze → Classify → Auto-reply or escalate |
| `follow_up` | Check timing → Generate → Send |
| `optimize_campaign` | Analyze performance → Suggest changes → Update |

**Event-driven execution:**

The Execution Layer both **consumes** events (a `campaign_launched` event triggers the `send_outreach` workflow) and **produces** events (workflow completion produces `draft_sent`, `campaign_completed`). It does not read the World Model directly — it receives commands through events and returns results through events.

### 2.7 Experience Layer

The Experience Layer is the UI. It is deliberately thin.

**Design rules:**

- The UI never reads from external systems. It reads from the Reasoning Layer.
- The UI never writes to external systems. It writes events to the Event System.
- The UI is stateless. All state is in the World Model.
- The UI is channel-agnostic. The same data model serves Telegram, Web, and future interfaces.

**Data flow for a page load (Mission Control):**

```
1. User opens Mission Control
2. UI sends: GET /briefing
3. Server:
   a. Reads World Model state (from event projection)
   b. Computes delta from last_viewed_at
   c. Runs Workspace Analyzer (priorities, attention, health)
   d. Calls Narrative Engine (briefing + recommendations)
   e. Returns: { brief, recommendations, priorities, health, delta }
   f. Writes event: briefing_viewed { timestamp }
4. UI renders:
   a. Streaming briefing text
   b. Decision cards from recommendations
   c. Sections from analysis
```

**Narrative AI in the Experience Layer:**

The unfolding briefing is a UI pattern, not a data pattern. The API returns the full briefing as structured segments. The UI reveals them progressively:

```
API returns:
  briefing: {
    greeting: "Good morning.",
    segments: [
      "I reviewed 184 companies while you were away.",
      "24 prospects look promising.",
      "One campaign is ready to launch.",
      "I'd recommend starting with Acme AI."
    ]
  }

UI renders:
  [0ms]    "Good morning."
  [300ms]  "I reviewed 184 companies while you were away."
  [600ms]  "24 prospects look promising."
  [900ms]  "One campaign is ready to launch."
  [1200ms] "I'd recommend starting with Acme AI."
  [1500ms] Sections fade in below.
```

The UI never fakes generation. It reveals prepared content at a natural cadence. The effect is the same — the user feels briefed, not displayed to.

---

## 3. Data Flow: A Complete Event Lifecycle

Follow a single Gmail reply from arrival to user action:

```
1. Gmail sends reply via push notification (or sync poll detects it)
       │
2. Communication Provider receives the message
       │
3. Write event: message_received { thread_id, from, subject, body }
       │
4. Conversation Pipeline runs (off the request path):
   a. Intent Detector → "meeting_request"
   b. Buying Signal Detector → [budget_approved, timeline_discussed]
   c. Stage Classifier → "negotiation"
   d. Followup Reasoner → { action: "suggest_demo", confidence: 0.85, approval_required: true }
   e. Write event: reply_analyzed { conversation_id, intents, signals, stage, recommendation }
       │
5. Auto-Handle Decider evaluates:
   - Confidence >= 0.9 and category in [routine_update, thank_you] → auto-reply
   - Otherwise → escalate
   
   In this case: confidence 0.85 or category requires human → escalate
       │
6. Write event: conversation_escalated { conversation_id, reason, recommendation }
       │
7. World Model projects new state:
   - inbox.needs_attention +1
   - conversations[id].summary updated
   - conversations[id].recommended_action = "suggest_demo"
       │
8. Next time user opens Mission Control:
   a. Delta computer detects: new inbox item
   b. Workspace Analyzer includes in attention items
   c. Narrative Engine writes briefing segment:
      "One reply needs your decision. A prospect asked about implementation timeline."
   d. User sees briefing, clicks into Inbox, reads summary
       │
9. User clicks "Approve" on the suggested reply
       │
10. Write event: recommendation_actioned { conversation_id, action: "approve", reply_text }
       │
11. Outbound Scheduler schedules the reply (or sends immediately)
       │
12. Write event: reply_sent { conversation_id, thread_id, message_id }
       │
13. Learning System (next consolidation):
    - Records outcome: user approved meeting-suggestion reply
    - Updates preference: "meeting requests → suggest demo first" confidence += 0.05
```

Everything downstream of step 3 is asynchronous. The user never waits.

---

## 4. How Workspaces Derive from the Architecture

### Mission Control — "Relief"

Mission Control is a **briefing**. It answers:
- What happened? (delta from World Model)
- What matters? (prioritized from Workspace Analyzer)
- What should I do? (recommendations from Narrative Engine)

```
GET /briefing
─► Reasoning Layer:
     Read World Model state
     Compute delta from last_viewed_at
     Run Workspace Analyzer → priorities, attention, health
─► Narrative Engine:
     Briefing Writer → greeting + segments
     Recommendation Writer → decision cards
─► Return structured data + narrative
─► Write event: briefing_viewed
```

### Discovery — "Confidence"

Discovery is a **research review**. It answers:
- What did Loqi find?
- Why does this match?
- What should I do with it?

```
GET /discovery
─► World Model: recent research results, lead scores
─► Reasoning Layer: Opportunity Scorer ranks leads
─► Narrative Engine: research summary
─► Return: scored leads with evidence
```

Discovery is not a search engine. Users direct Loqi through Tell Loqi:
- "Find healthcare companies in Series A"
- "Focus on fintech"
- "Ignore agencies"

These produce events (`tell_loqi_instruction`) that update the World Model's business context, which the Research Pipeline reads on its next run.

### Campaigns — "Momentum"

Campaigns are **goals with execution plans**. A campaign is:

```
CampaignState:
  goal: str                    # "Book meetings with AI startups in the US"
  status: CampaignStatus       # planning → researching → drafting → launching → active → completed
  leads: list[LeadRef]
  drafts: list[DraftRef]
  performance: CampaignMetrics
  history: list[EventRef]      # causal history of this campaign
```

The UI shows:
1. Goal and status
2. Results so far
3. What Loqi changed recently
4. Next decisions needed
5. Performance insights

The email sequence is a supporting view, not the primary one.

### Inbox — "Clarity"

Inbox contains **exceptions only**. Routine replies are auto-handled.

```
GET /inbox
─► World Model: conversations where approval_required = true
─► Narrative Engine:
     "I handled 38 conversations today. Only two need your input."
─► Return: exception list with AI summaries
```

Each exception card includes:
- AI summary of the conversation so far
- Recommended action (with confidence expressed as language)
- Evidence (key signals, intents)
- Decision buttons (Approve / Refine / Investigate)

### Knowledge — "Alignment"

Knowledge is **organizational memory with provenance**. It answers:
- What does Loqi know?
- How does it know it?
- How confident is it?

```
GET /knowledge
─► World Model: learned preferences, insights, patterns
─► Narrative Engine:
     "You've been running outbound for 3 weeks. Here's what I've learned."
─► Return: knowledge items with evidence
```

Every knowledge item shows:
- The belief ("Healthcare founders prefer shorter emails")
- Confidence (expressed as language, not percentage)
- Evidence ("Based on 84 conversations, 26 meetings, 3 campaigns")
- How it was learned (source events)

---

## 5. Where Memory Lives

Memory is not a single system. It's three systems with different characteristics:

| Memory Type | Storage | Retention | Query Pattern |
|---|---|---|---|
| **Event Log** | Supabase (append-only) | Forever | Scan by session + time range |
| **World Model State** | Supabase + in-memory cache | Current version + hourly snapshots | Direct key access |
| **Learned Patterns** | Supabase (consolidated) | Forever, with confidence decay | Semantic search |

**Event Log** — the source of truth. Immutable. Every state change is here. Used for debugging, auditing, and replaying state.

**World Model State** — the current projection. Derived from the event log. The only system that reasoning and generation read from.

**Learned Patterns** — what Loqi has inferred. Preferences, insights, correlations. Updated by the Learning System during consolidation.

The three systems form a hierarchy:

```
Event Log ──► State Projection ──► Learned Patterns
(source)       (current view)      (inferred knowledge)
```

---

## 6. Where Learning Lives

Learning lives in the **Learning System**, a set of periodic (not real-time) processes:

**Daily consolidation:**

```
1. Outcome Analyzer
   In: sent_drafts[] with reply_status
   Out: correlations between messaging patterns and outcomes
   Effect: updates Learned Patterns

2. Preference Reinforcer
   In: user actions (approve/reject/redirect)
   Out: updated preference confidence scores
   Effect: updates Learned Patterns

3. Pattern Detector
   In: cross-campaign performance data
   Out: detected patterns ("healthcare replies 2x more")
   Effect: writes insight_generated events

4. Knowledge Builder
   In: accumulated evidence + current Knowledge state
   Out: updated Knowledge state
   Effect: writes knowledge_updated events
```

**Design rules:**

- Learning never happens in the request path.
- Learning is idempotent. Running it twice produces the same result.
- Learning produces events, which feed the World Model, which feed the next briefing.
- Learning has a confidence threshold. Below 0.6 confidence, patterns are tracked but not surfaced.

---

## 7. Where Automation Lives

Automation lives in the **Auto-Handle Decider**, a deterministic subsystem of the Intelligence Layer.

**Decision flow:**

```
Message arrives
       │
       ▼
Conversation Pipeline produces:
  { intents: [...], signals: [...], stage: "...",
    followup: { action, confidence, approval_required } }
       │
       ▼
Auto-Handle Decider evaluates:

  if approval_required == false and confidence >= 0.9:
    → auto-reply (generate reply, send, log event)
  
  elif approval_required == false and confidence >= 0.7:
    → auto-draft (generate reply, save as draft, notify user, log event)
  
  elif category in [spam, out_of_office, unsubscribe]:
    → auto-archive (log event, no notification)
  
  else:
    → escalate to inbox (log event, appears in next briefing)
```

**Graduated autonomy:**

The thresholds adjust based on user behavior:
- User consistently approves auto-drafts → confidence threshold decreases
- User frequently modifies auto-replies before sending → confidence threshold increases
- User never opens a certain category → that category's threshold decreases

**Design rules:**

- Automation is conservative by default. Escalate when uncertain.
- Automation logs everything. Every auto-reply is auditable.
- Automation is tunable per user. Power users can increase autonomy.
- Automation never handles: objections, pricing questions, legal inquiries, cancellations.

---

## 8. System Boundaries

```
                    ┌──────────────────────────────┐
                    │        External World          │
                    │  Gmail │ Apollo │ LinkedIn     │
                    │  Calendar │ CRM │ SerpAPI      │
                    └──────────┬───────────────────┘
                               │
                    ┌──────────▼───────────────────┐
                    │      Provider Layer            │
                    │  (Adapters + Credentials)      │
                    │                                │
                    │  Input: external API calls     │
                    │  Output: internal events       │
                    └──────────┬───────────────────┘
                               │ events
                    ┌──────────▼───────────────────┐
                    │       Event System             │
                    │  (immutable append-only log)   │
                    └──────────┬───────────────────┘
                               │ events
                    ┌──────────▼───────────────────┐
                    │      World Model               │
                    │  (projected state + delta)    │
                    └──────────┬───────────────────┘
                               │ state
                    ┌──────────▼───────────────────┐
                    │     Reasoning Layer            │
                    │  (deterministic analysis)     │
                    └──────────┬───────────────────┘
                               │ structured data
                    ┌──────────▼───────────────────┐
                    │     Narrative Engine           │
                    │  (LLM generation)             │
                    └──────────┬───────────────────┘
                               │ narrative + cards
                    ┌──────────▼───────────────────┐
                    │     Experience Layer           │
                    │  (UI rendering)               │
                    └──────────────────────────────┘
```

Data flows in one direction across layers. Lower layers never read from higher layers. The Event System is the only bidirectional boundary — it receives events from all layers and provides events to all layers.

---

## 9. Consistency Model

Loqi is **eventually consistent** by design.

- **Strong consistency** — World Model state is strongly consistent within a single session. Events within a session are ordered.
- **Eventual consistency** — The Narrative Engine may be slightly behind the World Model (cached briefings). The Inference Layer runs minutes/hours behind events.
- **No distributed transactions** — Every subsystem writes events and moves on. If a downstream system fails, events are retried.

**User-visible implications:**

1. Opening Mission Control shows the state as of the last event projection (typically <1s old).
2. After taking an action (approving a draft), the next API call reflects the change.
3. Learning insights appear the next day, not immediately.
4. Auto-replies may take 30-60 seconds from message receipt to send.

---

## 10. Architectural Invariants

These must never be violated:

1. **The Event Log is the source of truth.** No system writes state directly. State is always a projection of events.
2. **Reasoning is deterministic.** No LLM calls in the reasoning layer. Reasoning must be unit-testable.
3. **The Narrative Engine is stateless.** All state comes from the World Model. The Narrative Engine has no memory.
4. **The UI is a thin client.** It reads from the Reasoning Layer. It writes events. It has no business logic.
5. **External systems are accessed only through providers.** No direct API calls outside the Provider Layer.
6. **Learning is never synchronous.** The request path never waits for learning.
7. **Automation is conservative.** When uncertain, escalate.
8. **Confidence is calibrated.** Every output has a confidence, and confidence is expressed through language, not numbers.
9. **Channels are interchangeable.** The same data model serves Telegram, Web, and future interfaces.
10. **The product is usable without LLMs.** If OpenAI is down, reasoning and structured data still work. Narrative degrades but the product functions.

---

## 11. What This Architecture Is Not

- It is not microservices. This is a modular monolith with clean internal boundaries.
- It is not event-sourcing in the CQRS sense. Events are append-only, but the projection is simple — replay all events for a session, in order.
- It is not an AI agent framework. The architecture distinguishes between automation (deterministic rules) and generation (LLM). Loqi does not have "agents" in the GPT-4-with-tools sense — it has deterministic pipelines that use LLMs for specific, bounded tasks.
- It is not real-time. Loqi is eventually consistent. The briefing is always slightly behind. This is intentional — it makes the product feel fresh rather than cached.
