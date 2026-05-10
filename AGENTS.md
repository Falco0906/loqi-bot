# Loqi Backend Architecture

## Product Overview

Loqi is an AI-native outbound operating system.

Current interfaces:
- Telegram bot
- Web chat UI (in progress)

Future interfaces:
- WhatsApp
- Mobile app
- Slack

The backend is the core product.
Interfaces are adapters only.

---

# Core Stack

- FastAPI backend
- Supabase persistence
- OpenAI API
- Gmail API
- Apollo/SerpAPI lead sourcing
- Conversation orchestration engine

---

# Architectural Principles

- Keep business logic in backend
- Interfaces must remain thin
- Telegram/web should share same orchestration layer
- Avoid workflow builders like n8n
- Prefer explicit workflow/session state
- Preserve modular service boundaries

---

# Important Services

## workflows.py
Core orchestration layer.
DO NOT tightly couple to interfaces.

## ai.py
OpenAI generation/personalization layer.

## gmail.py
Email sending/inbox interaction layer.

## conversation_engine.py
Shared multi-client conversation orchestration.

## channel_adapters/
Client-specific adapters:
- Telegram
- Web
- future WhatsApp

---

# Current Priorities

1. Reliable lead sourcing
2. Better personalization quality
3. Web UI polish
4. Gmail inbox sync
5. Reply detection
6. Preference memory

---

# Avoid

- overengineering infra
- unnecessary auth complexity
- premature microservices
- dashboard bloat
- excessive abstractions

---

# Product Direction

Loqi is evolving toward:
- AI-native outbound infrastructure
- conversational outbound workflows
- adaptive personalization memory
- multi-client orchestration platform

NOT:
- a generic chatbot
- a no-code workflow wrapper
- a simple cold email generator