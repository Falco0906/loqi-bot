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

# Important Project Rule — Server Management

OpenCode must NEVER start or stop development servers (backend or frontend).

This includes:
- killing backend processes
- killing frontend processes
- restarting servers
- launching long-running dev servers
- leaving background processes running

Whenever runtime verification is needed, opencode should assume the user will handle it:
- restart the backend
- restart the frontend
- verify in the browser

OpenCode is only responsible for modifying code.

---

---

# Protected Layers

These layers must never be modified outside their designated phase type.
Violations must be flagged before any edit is made.

| Layer | Owns | Only modified by |
|---|---|---|
| **1. Design System** | Colors, spacing, typography, shadows, elevations, animations, `globals.css`, `tailwind.config.ts`, CSS variables, theme tokens, background/surface classes | UI-focused phases |
| **2. Architecture** | WorkspaceContainer, routing, layouts, providers, registries, context, service boundaries | Architecture phases |
| **3. Intelligence** | Knowledge registry, reasoning pipeline, reply generation engine, AI providers, prompt construction | AI phases |
| **4. Product Features** | Discovery, Campaigns, Conversations, Draft Review, Settings, Copilot, and all page-level components | Feature phases |

When a task spans multiple layers, stop and ask which layer the change belongs to.

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