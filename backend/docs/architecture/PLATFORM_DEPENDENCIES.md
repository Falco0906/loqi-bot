# Platform Dependency Architecture

## Diagram

```mermaid
graph TB
    subgraph Interfaces["Interface Layer"]
        TG[Telegram Adapter]
        WB[Web Chat UI]
        API[Public API]
        WA[WhatsApp Adapter<br/>Future]
        MO[Mobile App<br/>Future]
        SL[Slack Adapter<br/>Future]
    end

    subgraph Product["Product Platforms"]
        SP[Sales Intelligence<br/>Platform]
        MP[Memory Platform]
        CP[Communication<br/>Platform]
        MP[Multi-Agent<br/>Platform]
    end

    subgraph Execution["Execution Platform"]
        EP[Execution Engine]
        AR[Adapter Registry]
        EV[Event Bus]
        PR[Planner Router]
        DS[Dispatcher]
        SM[State Machine]
    end

    subgraph Foundation["Identity & Security Foundation"]
        IP[Identity Platform]
        SEC[Security Platform]
    end

    subgraph Infra["Infrastructure"]
        DB[(Supabase)]
        AI[(OpenAI API)]
        GM[(Gmail API)]
        AD[External Adapters<br/>Apollo, SerpAPI]
    end

    %% Interface → Product Platform flow
    TG --> CP
    WB --> CP
    API --> CP
    WA --> CP
    MO --> CP
    SL --> CP

    %% Interface → Identity
    TG --> IP
    WB --> IP
    API --> IP
    WA --> IP
    MO --> IP
    SL --> IP
    TG --> SEC
    WB --> SEC
    API --> SEC
    WA --> SEC
    MO --> SEC
    SL --> SEC

    %% Product → Execution
    CP --> EP
    SP --> EP
    MP --> EP
    MP --> EP

    %% Identity & Security → Everything
    IP -.-> EP
    IP -.-> CP
    IP -.-> SP
    IP -.-> MP
    IP -.-> MP
    SEC -.-> EP
    SEC -.-> CP
    SEC -.-> SP
    SEC -.-> MP
    SEC -.-> MP

    %% Identity → Security
    IP -->|produces IdentityContext| SEC

    %% Execution → Infrastructure
    EP --> DB
    EP --> AI
    EP --> GM
    EP --> AD

    %% Event bus
    EV -.-> CP
    EV -.-> SP
    EV -.-> MP
    EV -.-> IP
    EV -.-> SEC

    %% Styling
    classDef foundation fill:#1a1a2e,stroke:#e94560,stroke-width:3,color:#fff
    classDef product fill:#16213e,stroke:#0f3460,stroke-width:2,color:#fff
    classDef execution fill:#0f3460,stroke:#533483,stroke-width:2,color:#fff
    classDef interface fill:#533483,stroke:#e94560,stroke-width:1,color:#fff
    classDef infra fill:#2d2d2d,stroke:#666,stroke-width:1,color:#ccc

    class IP,SEC foundation
    class SP,MP,CP product
    class EP,AR,EV,PR,DS,SM execution
    class TG,WB,API,WA,MO,SL interface
    class DB,AI,GM,AD infra
```

## Legend

| Line style | Meaning |
|---|---|
| `───` solid | Direct dependency / integration |
| `- - -` dashed | Cross-cutting concern (auth, authorization, audit) |
| `►` arrow | Direction of dependency |

## Layer description

### Foundation Layer (Identity & Security)

The Identity and Security platforms sit **underneath all other platforms**. Every request from every interface passes through both:

1. **Identity Platform** authenticates the request, producing an `IdentityContext`
2. **Security Platform** authorizes the request, enforces rate limits, and audits decisions
3. The authorized `IdentityContext` is forwarded to business logic

No product platform or execution component bypasses Identity or Security.

### Interface Layer

Interface adapters (Telegram, Web, WhatsApp, Mobile, Slack) authenticate through Identity before reaching business logic. Interfaces are thin — they translate protocol to API calls and delegate all business logic downstream.

### Product Platforms

- **Communication Platform** — conversation engine, message routing, reply detection
- **Sales Intelligence Platform** — CRM adapters, contact intelligence, pipeline strategies
- **Memory Platform** — organizational memory, explainability, consolidation
- **Multi-Agent Platform** — specialist agents, coordinator, pipeline orchestration

Each product platform receives an authenticated `IdentityContext` and operates within an Organization boundary.

### Execution Platform

The execution engine schedules, dispatches, and monitors all tasks. It does not authenticate — it receives pre-authenticated tasks from product platforms. The execution engine integrates with:

- Supabase for persistence
- OpenAI for generation
- Gmail for email
- External adapters for lead sourcing

The Event Bus cross-cuts all platforms, including Identity and Security, for event-driven integration.

### Infrastructure

External services accessed through adapters. All infrastructure access is mediated by the Execution Platform.

## Dependency rules

| Rule | Description |
|---|---|
| **Identity first** | Every request is authenticated before any business logic executes |
| **Authorization second** | Every authenticated request is authorized before accessing resources |
| **Foundation stability** | Identity and Security platforms are foundational — no circular dependencies from product platforms into Identity or Security internals |
| **Product isolation** | Product platforms depend on Identity and Security, not vice versa |
| **Interface thinness** | Interfaces authenticate through Identity but do not implement auth logic |
| **Event bus cross-cutting** | Any platform may publish or subscribe to events, including Identity and Security |
