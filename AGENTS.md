# Loqi Backend Architecture

## Product Overview

Loqi is an AI-native outbound operating system.

Current interfaces:
- Telegram bot
- Web chat UI
- Future: WhatsApp, mobile app, Slack

The backend is the core product. Interfaces are adapters only.

---

## Core Stack

- FastAPI backend
- Supabase persistence
- OpenAI API
- Gmail API
- Apollo/SerpAPI lead sourcing
- Conversation orchestration
- Shared backend services used by all interfaces

---

# Mandatory Engineering Standard

**Before making any backend change, read `ARCHITECTURE_RULES.md`.**

`ARCHITECTURE_RULES.md` is the canonical engineering standard for Loqi's backend architecture.

The core standard is:

> **A competent engineer should be able to open any file in Loqi and understand why it exists, what it owns, and what it does without a 3-hour archaeology session.**

Agents must not trade readability and clear ownership for convenience.

### Mandatory rules

- One file should have one clear purpose.
- One function should perform one coherent responsibility.
- `main.py` is the composition root, not a business-logic dumping ground.
- Every domain responsibility has one canonical owner.
- Search for existing implementations before creating new ones.
- Do not create speculative abstractions or generic helper layers without a demonstrated need.
- Helpers belong with the responsibility they support; do not put business helpers in `main.py`.
- Dependencies must flow downward; services must not reach upward into `main.py`.
- Important state must have a clear canonical source of truth.
- Side effects must be explicit.
- Long-running work must use an appropriate durable async/job boundary.
- Consequential mutations require explicit authorization, scope, and safe retry/idempotency behavior where applicable.
- Unexpected failures must remain observable; do not hide them behind generic exception handling.
- Legacy code may exist during migration, but new features must not create additional parallel implementations.
- A refactor is incomplete when the old implementation remains active without a reason.
- Prefer boring, explicit, human-readable code over clever or deeply abstract code.

### Before editing

An agent must first determine:

1. What behavior is changing?
2. Who currently owns it?
3. Does an implementation already exist?
4. Is there duplicate or legacy behavior?
5. What is the canonical source of truth?
6. What dependencies will the change introduce?
7. Can the change be made without another abstraction?
8. What existing behavior could regress?

If ownership or architecture is unclear, investigate before editing.

### After editing

Verify that:

- changed files still have clear purposes
- changed functions have coherent responsibilities
- no unnecessary duplicate implementation was introduced
- no unnecessary abstraction was introduced
- dependency direction remains valid
- obsolete code was removed where appropriate
- state ownership remains clear
- relevant tests and validation pass

If a change makes the system harder to explain, stop and reconsider it.

---

# Architectural Principles

- Keep business logic in the backend.
- Interfaces must remain thin adapters.
- Telegram, web, and future clients should share the same application/domain capabilities.
- Do not tightly couple business logic to a specific interface.
- Prefer explicit workflow/session state.
- Preserve clear service/domain boundaries.
- Prefer consolidation over adding another layer.
- Prefer incremental, behavior-preserving refactors over blind rewrites.
- Do not introduce microservices or infrastructure complexity without a demonstrated need.

---

# Backend Layering

Prefer this dependency direction:

```text
API / routes
      ↓
Application services
      ↓
Domain logic
      ↓
Repositories / integrations
      ↓
Infrastructure
```

`main.py` should primarily compose these pieces and translate HTTP concerns.

Lower-level services must not import business logic from `main.py`.

---

# Important Services

These are the intended responsibilities. Before changing one of these areas, search the repository for existing implementations and verify the actual current owner.

## workflows.py

Workflow/application orchestration.

Do not tightly couple workflows to Telegram, web, or another interface.

## ai.py

OpenAI generation and personalization integration.

## gmail.py

Gmail sending and inbox interaction integration.

## conversation_engine.py

Shared multi-client conversation orchestration.

## channel_adapters/

Client-specific adapters:

- Telegram
- Web
- Future WhatsApp
- Future Slack

## Copilot

Copilot should remain a bounded, workspace-scoped intelligence and action layer over canonical Loqi capabilities.

It must not become a second implementation of campaign, discovery, inbox, or outbound business logic.

---

# Product Direction

Loqi is evolving toward:

- AI-native outbound infrastructure
- conversational outbound workflows
- adaptive personalization memory
- multi-client orchestration

Loqi is not:

- a generic chatbot
- a no-code workflow wrapper
- a simple cold-email generator

---

# Current Priorities

Priorities may change. Treat this list as product context, not permission to bypass architecture rules.

1. Reliable lead sourcing
2. Personalization quality
3. Web UI quality
4. Gmail inbox sync
5. Reply detection
6. Preference memory

---

# Backlog

## Async-native workflow execution

The legacy workflow/dispatch path may still contain synchronous-to-async bridges.

Goal: progressively make long-running workflow and adapter calls async-native where appropriate, without introducing unnecessary thread bridges.

Scope and implementation must be verified against the current repository before editing. Do not assume the historical file ownership described here is still accurate.

---

# Server Management Rule

Agents must **never start, stop, kill, restart, or leave development servers running**.

This includes:

- backend servers
- frontend servers
- background development processes

When runtime verification requires a server restart or browser verification, the user handles it.

Agents are responsible for code changes and non-server validation only.

---

# Protected Layers

These boundaries prevent unrelated work from casually changing architecture or UI foundations.

| Layer | Owns | Normally modified by |
|---|---|---|
| **1. Design System** | Colors, spacing, typography, shadows, elevations, animations, `globals.css`, `tailwind.config.ts`, CSS variables, theme tokens, background/surface classes | UI/design work |
| **2. Architecture** | WorkspaceContainer, routing, layouts, providers, registries, context, service boundaries, backend structure | Architecture/refactor work |
| **3. Intelligence** | Knowledge registry, reasoning pipeline, reply generation, AI providers, prompt construction | AI/intelligence work |
| **4. Product Features** | Discovery, Campaigns, Conversations, Draft Review, Settings, Copilot, page-level components | Feature work |

### Cross-layer changes

If a task crosses layers, identify the affected layers before editing.

Do not modify protected architecture casually during a feature task.

Architecture/refactor work is explicitly allowed to modify architecture when that is the purpose of the task.

---

# Refactoring Standard

When refactoring existing backend code:

```text
understand
    ↓
identify canonical owner
    ↓
move/consolidate behavior
    ↓
update callers
    ↓
test
    ↓
remove obsolete implementation
    ↓
verify references
```

Do not:

- duplicate the implementation “temporarily” without an exit plan
- create wrappers around wrappers
- move code without clarifying ownership
- preserve dead code just because it might be useful someday
- optimize for file-count reduction instead of clarity

The goal is not “fewer Python files.”

The goal is **clear ownership, low coupling, low cognitive load, and code a human can safely maintain.**

---

# Change Safety

For production-facing changes:

- preserve existing API contracts unless the task explicitly changes them
- preserve workspace/user isolation
- preserve authorization boundaries
- prefer small, verifiable changes
- run focused tests first, then broader validation where practical
- never claim production safety from static checks alone
- do not apply production migrations or make production changes unless explicitly requested
- clearly distinguish code-complete from production-verified

When a proposed fix could affect multiple domains, inspect those boundaries before editing.

---

# Final Standard

Loqi's architecture is successful when an engineer can enter an unfamiliar module and quickly understand:

- why the module exists
- what it owns
- what it does
- what it depends on
- what depends on it
- where its state comes from
- how its behavior is tested

**Readable code is not a luxury. It is the architecture.**
