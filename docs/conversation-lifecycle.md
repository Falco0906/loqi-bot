# Conversation Lifecycle

## Overview

Every sent outbound email belongs to exactly one Conversation. Conversations are the primary abstraction for managing ongoing relationships after communication has been sent. They are provider-agnostic (Gmail, LinkedIn, etc.) and replace individual-email management with conversation-level management.

---

## State Diagram

```
                    ┌─────────┐
                    │   NEW   │
                    └────┬────┘
                         │
                    ┌────▼────┐
                    │  SENT   │
                    └────┬────┘
                         │
              ┌──────────┼──────────┐
              │          │          │
         ┌────▼───┐ ┌────▼───┐ ┌────▼───┐
         │BOUNCED │ │DELIVERED│ │REPLIED │
         └───┬────┘ └────┬────┘ └──┬─┬───┘
             │           │         │ │
         ┌───▼────┐     │    ┌────┘ │
         │CLOSED  │     │    │      │
         │_LOST   │     │    │      │
         └────────┘     │    │      │
                   ┌────▼──┐ │ ┌────▼──────┐
                   │OPENED │ │ │FOLLOW_UP  │
                   └───┬───┘ │ │_PENDING   │
                       │     │ └────┬──────┘
                       │     │      │
                       │     │ ┌────▼────┐
                       │     │ │FOLLOW_UP│
                       │     │ │_READY   │
                       │     │ └────┬────┘
                       │     │      │
                       │     │ ┌────▼──────┐
                       │     │ │FOLLOW_UP  │
                       │     │ │_SENT      │
                       │     │ └────┬──────┘
                       │     │      │
                       │     └──┐ ┌─┘
                       │        │ │
                  ┌────▼────────▼─▼──┐
                  │   INTERESTED     │
                  └──┬────────────┬──┘
                     │            │
              ┌──────▼───┐  ┌────▼──────┐
              │MEETING   │  │CLOSED_LOST│
              │_BOOKED   │  └───────────┘
              └──┬───────┘
                 │
          ┌──────▼─────┐
          │ CLOSED_WON │
          └────────────┘
```

### Terminal States
- `CLOSED_WON` — Deal won
- `CLOSED_LOST` — Deal lost / not interested
- `BOUNCED` — Email bounced (can transition to CLOSED_LOST)

---

## State Machine

Defined in `backend/services/conversations/state_machine.py`.

All transitions are explicit. Use `validate_transition(current, target)` to check before transitioning, or `transition(current, target)` to execute with automatic validation.

```python
from services.conversations.state_machine import transition, validate_transition
from services.conversations.conversation_models import ConversationStatus

# Validate without raising
if validate_transition(convo.status, ConversationStatus.REPLIED):
    convo.status = ConversationStatus.REPLIED

# Transition with automatic validation (raises ValueError on invalid)
convo.status = transition(convo.status, ConversationStatus.REPLIED)
```

---

## Domain Models

All models are in `backend/services/conversations/conversation_models.py`.

| Model | Fields | Purpose |
|---|---|---|
| `Conversation` | conversation_id, provider_id, provider_type, external_thread_id, subject, status, participants, summary, campaign_id, workflow_id, lead_id, timestamps, message_count, metadata | Top-level conversation record |
| `ConversationThread` | thread_id, conversation_id, external_thread_id, provider_id, subject, timestamps, message_count | A thread within a conversation |
| `ConversationMessage` | message_id, conversation_id, thread_id, provider_id, external_message_id, direction, from/to, subject, body, classification, timestamps | A single message |
| `ConversationParticipant` | email, name, role, provider_id, external_id | A participant |
| `ConversationSummary` | company, contact_name, contact_email, interest_level, key_points, next_action, last_summary | Evolving AI summary |
| `ConversationStatus` | Enum with 14 states | Lifecycle state |
| `ReplyCategory` | Enum with 10 categories | Reply classification |

---

## Timeline

Every conversation has an ordered, immutable timeline of events. Defined in `backend/services/conversations/timeline.py`.

| Event Type | Description |
|---|---|
| `campaign_created` | Campaign created |
| `draft_generated` | Draft generated |
| `email_sent` | Outbound email sent |
| `email_delivered` | Email delivered |
| `email_opened` | Email opened |
| `email_bounced` | Email bounced |
| `reply_received` | Reply received |
| `reply_classified` | Reply classified |
| `follow_up_suggested` | Follow-up suggested |
| `follow_up_ready` | Follow-up ready to send |
| `follow_up_sent` | Follow-up sent |
| `meeting_booked` | Meeting booked |
| `status_changed` | Conversation status changed |
| `summary_updated` | AI summary updated |
| `note_added` | Manual note added |
| `closed_won` | Conversation closed won |
| `closed_lost` | Conversation closed lost |

---

## Classification Architecture

Defined in `backend/services/conversations/classification.py`.

The classifier is AI-independent:

- `BaseClassifier` — abstract base for custom classifiers
- `RuleClassifier` — keyword/pattern-based fallback (always available)
- `ClassifierService` — orchestrates with fallback chain (try AI, fall back to rules)

Categories with confidence scores:

| Category | Description | Default Confidence |
|---|---|---|
| `interested` | Positive interest signal | 0.7 |
| `not_interested` | Explicit disinterest | 0.8 |
| `question` | Asking a question | 0.5 |
| `pricing_request` | Requesting pricing | 0.7 |
| `meeting_request` | Requesting meeting/demo | 0.7 |
| `referral` | Referral request | 0.5 |
| `out_of_office` | Auto OOO reply | 0.9 |
| `bounce` | Email bounced | 0.9 |
| `auto_reply` | Auto-responder | 0.8 |
| `unknown` | Could not classify | 0.0 |

---

## Follow-up Planner

Defined in `backend/services/conversations/followup_planner.py`.

Provider-independent planning. Does NOT generate responses — only plans.

| Component | Description |
|---|---|
| `BaseFollowUpPlanner` | Abstract base |
| `DefaultFollowUpPlanner` | Rule-based planner |
| `FollowUpPlannerService` | Orchestrator with fallback |

Plan properties: `should_follow_up`, `priority`, `objective`, `suggested_timing`, `suggested_template`, `reason`, `confidence`.

---

## Integration Points

The conversation system integrates with the outbound system at these points:

### Send Flow (in `main.py`)
- `send_draft()` route — after successful send, calls `create_conversation_from_send()`
- `_dispatch_campaign_sends()` — after each campaign send, calls `create_conversation_from_send()`

### Event System
- `handle_outbound_event()` — subscribes to outbound events (MESSAGE_SENT, MESSAGE_FAILED, MESSAGE_SCHEDULED) to update conversation state.

### Reply Detection (future)
- When a reply is detected via Gmail sync, `handle_reply()` processes it: classifies the reply, updates conversation state, adds timeline events.

---

## Storage

The current implementation uses an in-memory `ConversationStore`:

```python
from services.conversations.conversation_store import conversation_store
```

Indexes: by provider, campaign, workflow, status, external thread.

Future: migrate to Supabase persistence.

---

## API Endpoints

| Route | Method | Purpose |
|---|---|---|
| `/api/web/session/{token}/conversations` | GET | List conversations |
| `/api/web/session/{token}/conversations/{id}` | GET | Get conversation detail |
| `/api/web/session/{token}/conversations/{id}/timeline` | GET | Get timeline events |
| `/api/web/session/{token}/conversations/{id}/messages` | GET | Get messages |

---

## Future AI Extension Points

### AI Reply Generation
- Extend `ConversationMessage` with generation metadata
- Add a `generate_reply` method to `FollowUpPlannerService`
- Surface generated replies in the Conversation Detail UI

### Multi-Provider Conversations
- Add provider-specific adapters (LinkedIn, WhatsApp, Slack)
- Each adapter maps external threads to the `Conversation` model
- `ConversationMessage.direction` and `provider_id` track provenance

### Voice Conversations
- Add voice-specific `ConversationMessage` extensions (transcript, duration, sentiment)
- Integrate with telephony provider

### CRM Syncing
- Add `external_crm_id` and `external_crm_type` fields to `Conversation`
- Implement sync callbacks for CRM read/write
- Map `ConversationStatus` to CRM pipeline stages

### Meeting Scheduling
- Add `meeting` field to `ConversationSummary` (scheduled_time, meeting_link, platform)
- Wire to calendar API
- Update `FollowUpObjective.SCHEDULE_MEETING` with actual scheduling logic

### Conversation Memory
- Implement persistent memory across conversations with the same contact
- Track preference signals, objection patterns, communication style
- Feed memory into AI classification and planning
