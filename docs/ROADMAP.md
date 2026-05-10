# Loqi Roadmap

## Current Stage

Current focus:
- make product reliable enough for first customer/investor
- stabilize core workflows
- improve UX
- improve output quality

Avoid unnecessary infrastructure work.

---

# Immediate Priorities

## 1. Web UI MVP

Goal:
replace Telegram as primary interface.

Requirements:
- chat UI
- conversation history
- lead cards
- draft previews
- Gmail connection
- send flows

Status:
IN PROGRESS

---

## 2. Improve Lead Quality

Current:
- SerpAPI fallback

Target:
- Apollo integration
- better enrichment
- cleaner lead filtering

Importance:
VERY HIGH

---

## 3. Improve AI Draft Quality

Current issue:
- outputs still feel generic sometimes

Need:
- stronger prompts
- better personalization
- shorter natural drafts
- founder-style tone

Importance:
CRITICAL

---

## 4. Gmail Reliability

Need:
- smoother OAuth
- reliable sends
- clear send status
- fewer failures

Importance:
CRITICAL

---

## 5. Reply Detection

Need:
- detect replies
- classify replies
- show reply events in UI

Goal:
make Loqi feel alive and agentic.

---

# Near-Term Features

## Follow-Up Automation

Potential:
- automatic follow-ups
- timing optimization
- response-aware follow-ups

---

## Preference Memory

Store:
- preferred tone
- accepted drafts
- edited drafts
- industries
- reply patterns

Goal:
adaptive personalization.

---

## Workflow Sessions

Move from:
- implicit conversation state

To:
- explicit workflow sessions
- durable orchestration state

---

# Future Features

## WhatsApp Interface

Potential second interface after web UI stabilizes.

---

## Mobile App

Future:
- React Native
- notifications
- inbox monitoring

---

## Team Features

Future:
- organizations
- shared inboxes
- team workflows

NOT needed yet.

---

## Analytics

Future:
- reply rates
- send rates
- lead quality metrics
- workflow analytics

NOT MVP priority.

---

# Infrastructure Plans

## Current

- FastAPI
- Supabase
- OpenAI
- Gmail API
- Telegram
- Next.js web UI

---

## Later

- Stripe
- proper auth
- worker queues
- background jobs
- realtime infra
- feature flags

---

# Product Philosophy

Current goal:
ship a magical workflow experience.

NOT:
build enterprise infrastructure too early.

---

# Important Founder Rules

Prioritize:
- UX
- reliability
- personalization
- workflow smoothness

Avoid:
- overengineering
- rebuilding infra repeatedly
- premature scaling complexity

---

# Success Criteria

Loqi should feel like:
- an outbound copilot
- conversational workflow software
- an AI operator

NOT:
- a form-based SaaS dashboard
- a generic chatbot
- a workflow builder

---

# Current Bottlenecks

1. Lead quality
2. Draft quality
3. Inbox sync
4. Workflow durability
5. Frontend polish

---

# Current Goal

Get:
- first serious customer
OR
- first meaningful investor interest

before heavy scaling infra work.