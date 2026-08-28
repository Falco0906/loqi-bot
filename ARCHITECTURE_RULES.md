# Loqi Backend Architecture Rules

> **Core standard:** A competent engineer should be able to open any file in Loqi and understand why it exists, what it owns, and what it does without a 3-hour archaeology session.

These rules govern all new backend code and backend refactors. Prefer simple, explicit, human-readable code over clever abstractions.

## 1. Every file has one clear purpose

Every source file must have an obvious reason to exist. An engineer opening it should be able to answer why it exists, what it owns, what it depends on, and which code calls it.

Do not create files merely to move code around. If two files own the same responsibility, consolidate them or establish a clear boundary.

## 2. One function, one responsibility

A function should perform one coherent operation.

Do not combine authentication, workspace resolution, validation, persistence, job creation, event emission, and HTTP response construction into one function. Split genuinely separate responsibilities into explicit operations.

If a function needs a paragraph to explain all the different things it does, it probably does too much.

## 3. `main.py` is the composition root

`backend/main.py` should primarily own:
- application startup/lifespan
- middleware
- exception handling
- route declarations
- HTTP request/response translation
- dependency wiring

Business logic belongs in the appropriate application/domain service.

A route should generally be:

```text
request → parse/validate → call application service → HTTP response
```

Do not turn `main.py` into a second service layer.

## 4. One canonical owner per responsibility

Each important behavior must have one canonical implementation: identity, workspaces, discovery, jobs, campaigns, strategy, inbox, outbound, Mission Control, Copilot, knowledge, etc.

Do not implement the same business operation in `main.py`, a service, and a legacy module.

When duplicate implementations exist, choose the canonical owner and remove obsolete paths once safe.

## 5. Dependencies flow downward

Prefer:

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

Lower layers must not depend upward on HTTP routes or `main.py`. A service importing business logic from `main.py` is an architectural violation.

## 6. No duplicate state without an explicit reason

Important state needs a canonical source of truth.

Do not maintain multiple writable representations of the same entity unless there is a documented reason. If a cache, projection, compatibility layer, or migration copy exists, document its source of truth, writer, staleness behavior, and recovery/disposal.

## 7. Prefer existing canonical code

Before creating a helper, service, repository, adapter, or abstraction:

1. Search for an existing implementation.
2. Identify its owner.
3. Reuse it if it already owns the responsibility.
4. Extend it if the responsibility genuinely belongs there.
5. Create something new only when a genuinely new responsibility exists.

**Do not solve duplication by adding another abstraction.**

## 8. No speculative abstractions

Do not create generic layers such as `BaseManager`, `UniversalHelper`, `GenericProcessor`, `CommonService`, or `ThingCoordinator` without a demonstrated need.

Abstractions should emerge from repeated, understood behavior. Simple code is preferred over framework-like architecture.

## 9. Helpers must have an owner

Helpers do not belong in `main.py` merely because they are convenient.

Put a helper with the responsibility it supports:
- campaign formatting → campaign module
- workspace authorization → identity/workspace module
- job state → job module
- Copilot planning → Copilot module

Only genuinely cross-domain, pure utilities belong in shared utility modules, which must remain small and dependency-light.

## 10. Keep boundaries explicit

Cross-domain operations should make their boundaries visible.

Prefer explicit inputs and outputs over hidden global state, implicit imports, or side effects reaching through unrelated internal modules.

## 11. Side effects must be obvious

Database writes, external API calls, job creation, email sending, and event emission are side effects.

Keep them visible in the layer that owns them. A function named like a read or formatter must not unexpectedly mutate production state.

## 12. Persistence must be deliberate

For every persistent entity, the codebase should make clear where it is stored, how it is created/updated/read, what identifies it, and what happens after process restart.

Avoid process-local state for durable application state. Temporary in-memory state is acceptable only when its lifecycle and failure behavior are explicit.

## 13. Async work is a first-class boundary

Long-running operations must not be disguised as synchronous request work.

```text
request → create durable job → return job identity
        → worker performs work → state/progress persists
        → client observes state
```

Timeouts must not leave the system ambiguous about whether an operation completed. Retries must be safe and bounded.

## 14. Mutations need explicit safety

Consequential operations require:
- explicit authorization
- clear workspace scope
- validation
- idempotency where retries are possible
- observable outcomes
- verification where appropriate

Never rely on frontend state or model output for user/workspace authority.

## 15. Errors belong at the right boundary

Application/domain code should produce meaningful domain failures. The HTTP layer should translate them into HTTP responses.

Do not scatter generic exception swallowing through business logic. Unexpected exceptions must remain observable through structured logging and request IDs.

## 16. Logging should explain behavior, not spam

Logs should make clear what operation happened, safe identifiers/context, success/failure, duration, and failure reason.

Never log secrets, tokens, cookies, authorization headers, or sensitive payloads.

## 17. Legacy code must be identified, not duplicated

Compatibility code is acceptable during migration, but it must be clearly marked and have an exit path.

Do not build new features on legacy paths merely because they already exist.

## 18. Tests protect boundaries

Tests should verify behavior and architectural boundaries, especially authorization, workspace isolation, canonical persistence, job lifecycle, idempotency, failure recovery, external side effects, and critical user flows.

When moving code between modules, preserve behavior while changing ownership.

## 19. Refactoring means deleting

A refactor is incomplete if the old implementation remains active without a reason.

Move the behavior → update callers → test → remove obsolete implementation → verify no references remain.

Do not leave dead code “just in case.”

## 20. Human readability is a feature

Prefer descriptive names, short functions, explicit control flow, obvious data flow, small modules, and predictable conventions.

Avoid clever one-liners, deep indirection, magic global state, and abstractions that hide simple behavior.

The goal is not the fewest lines or fewest files. The goal is the **least cognitive load required to understand and safely change the system.**

# Before Writing Code

An agent must determine:

1. What behavior is changing?
2. Who currently owns it?
3. Does an implementation already exist?
4. Is there duplicate or legacy behavior?
5. What is the canonical source of truth?
6. What dependencies will this introduce?
7. Can this be done without another abstraction?
8. What existing behavior could regress?

If these cannot be answered, investigate before editing.

# Before Finishing

Verify:
- every changed file has one clear purpose
- every changed function has one coherent responsibility
- no duplicate implementation was introduced
- no unnecessary abstraction was introduced
- dependency direction remains valid
- obsolete code was removed where appropriate
- state ownership remains clear
- tests cover the changed boundary
- compile/type/build checks pass
- no secrets or sensitive data were introduced into logs

If a change makes the architecture harder to explain, stop and reconsider it.

# The Standard

When two implementations are valid, prefer the one a competent engineer can understand **without knowing the history of Loqi**.

> **Readable code is not a luxury. It is the architecture.**
