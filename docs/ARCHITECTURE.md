# Loqi Architecture

## Product Overview

Loqi is an AI-native outbound operating system focused on:
- lead sourcing
- AI personalization
- outbound execution
- conversational workflow management

Current interfaces:
- Web chat UI (primary - MVP complete)
- Telegram (deprecated - interface code still exists but not primary)

Future interfaces:
- WhatsApp
- Mobile app
- Slack
- CRM integrations

The backend is the core product.
Interfaces should remain thin adapters.

---

## Why Web UI Became Primary

Telegram was the initial interface but had limitations:
- No persistent web presence
- Limited UI customization
- Users wanted browser-based experience

Web UI provides:
- Persistent sessions
- Rich UI components
- Better lead display
- Future: analytics dashboard
- Future: team collaboration

---

## Why Telegram Deprecated

1. Single-threaded conversations
2. Limited rich UI elements
3. No analytics/visualization
4. Platform lock-in
5. Hard to build team features

The conversation engine (`services/conversation_engine.py`) is channel-agnostic and could support Telegram again, but web is the priority.

---

# High-Level Architecture

Frontend Clients
(Telegram / Web / Future Channels)
            |
            v
Conversation Engine
            |
            v
Workflow Orchestration Layer
            |
  -------------------------
  |     |      |      |
 AI   Gmail  Leads  Database

---

# Core Stack

## Backend
- FastAPI
- Python

## Database
- Supabase

## AI
- OpenAI API

## Email
- Gmail API
- OAuth2

## Lead Sources
- Apollo (target)
- SerpAPI (current fallback)

## Frontend
- Next.js
- TypeScript
- Tailwind

---

# Backend Structure

## main.py
Main FastAPI entrypoint.

Responsibilities:
- webhook endpoints
- API routes
- OAuth callbacks
- health checks

---

## services/conversation_engine.py

Shared orchestration layer.

Purpose:
- channel-agnostic conversation handling
- workflow routing
- structured responses

This is the future core runtime.

---

## services/channel_adapters/

Interface adapters:
- telegram.py
- future web adapter
- future WhatsApp adapter

Adapters should:
- translate inputs
- render outputs
- avoid business logic

---

## workflows.py

Main workflow orchestration layer.

Responsibilities:
- lead search
- lead selection
- draft generation
- send flows
- workflow transitions

Avoid coupling workflows to UI.

---

## services/ai.py

AI generation layer.

Responsibilities:
- intent classification
- draft generation
- personalization
- rewrite handling

Future:
- preference memory
- adaptive style learning

---

## services/gmail.py

Email execution layer.

Responsibilities:
- send emails
- fetch replies
- sync inbox state

---

## services/google_auth.py

Handles Gmail OAuth.

Responsibilities:
- OAuth URLs
- token exchange
- token refresh

---

## services/supabase.py

Persistence layer.

Responsibilities:
- users
- conversations
- leads
- workflow sessions
- message history

---

# Current Workflow Model

Current Flow:

User
→ asks for leads
→ lead search
→ lead selection
→ draft generation
→ Gmail send
→ follow-up/reply handling

---

# Current Persistence Model

Current state:
- Supabase stores users
- conversations
- leads
- workflow state

Moving toward:
- explicit workflow_sessions
- workflow_messages
- workflow_events

instead of reconstructing state from chat history.

---

# Multi-Client Direction

Goal:
All clients should use the same backend runtime.

Example:

Telegram
   \
    \
     → conversation engine
    /
Web UI

Clients should never own workflow logic.

---

# Product Philosophy

Loqi is:
- conversational outbound infrastructure
- AI-native workflow software
- adaptive outbound orchestration

Loqi is NOT:
- generic chatbot
- no-code automation wrapper
- simple email generator

---

# Current Priorities

1. Reliable lead sourcing
2. Better AI personalization
3. Web UI polish
4. Gmail inbox sync
5. Reply detection
6. Preference memory
7. Workflow durability

---

# Important Constraints

Avoid:
- premature microservices
- excessive infra complexity
- dashboard bloat
- overengineering auth
- workflow-builder dependency

Prefer:
- simplicity
- maintainability
- fast iteration
- modular boundaries

---

# Long-Term Direction

Near-term:
- stabilize web UI
- improve lead quality
- improve draft quality
- add inbox syncing

Mid-term:
- WhatsApp support
- follow-up automation
- analytics
- memory systems

Long-term:
- full outbound operating system
- multi-channel orchestration
- AI-assisted outbound execution platform