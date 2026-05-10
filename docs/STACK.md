# Loqi Stack

## Backend

### Framework
- FastAPI

### Language
- Python

### Responsibilities
- orchestration
- APIs
- workflows
- integrations
- AI execution

---

# Frontend

## Current
- Telegram bot interface
- Next.js web UI (MVP)

## Planned
- WhatsApp
- Mobile app

---

# AI Layer

## Provider
- OpenAI API

## Responsibilities
- draft generation
- personalization
- rewriting
- intent classification

---

# Database

## Provider
- Supabase

## Stores
- users
- conversations
- workflow sessions
- messages
- leads
- Gmail tokens

---

# Authentication

## Current
- lightweight session model

## Future
- Supabase Auth
- Stripe-linked subscriptions

---

# Email Layer

## Provider
- Gmail API

## Features
- OAuth2
- email sending
- inbox syncing
- reply detection

---

# Lead Sources

## Current
- SerpAPI

## Planned
- Apollo

## Future
- multiple providers
- enrichment layer

---

# Hosting

## Backend
- Render

## Frontend
- Vercel

---

# Realtime

## Current
- REST APIs

## Planned
- SSE or WebSockets

---

# Tooling

## IDE
- VS Code

## Agentic Coding
- OpenCode
- Claude-style workflows

---

# Important Repositories

## loqi-bot
Main product backend + web UI.

## loqi
Landing page + onboarding + access flow.

---

# Architectural Principles

- backend-first architecture
- thin client adapters
- modular services
- avoid no-code workflow dependency
- explicit workflow orchestration

---

# Current MVP Flow

User
→ asks for leads
→ lead search
→ lead selection
→ AI draft generation
→ Gmail send
→ reply handling

---

# Future Direction

Loqi is evolving toward:
- AI outbound operating system
- multi-channel orchestration platform
- conversational outbound infrastructure