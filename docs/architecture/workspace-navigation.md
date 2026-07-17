# Workspace Navigation Architecture

## Vision

Loqi's primary outbound workflow should feel like one continuous AI workspace rather than a collection of separate dashboard pages. Users navigate by clicking the sidebar (primary) or scrolling naturally between full-screen workspaces (secondary, future).

This document describes the architectural foundation for that vision.

---

## Navigation Philosophy

- **Sidebar is primary navigation.** Always present, always clickable, always functional.
- **Scroll navigation is additive.** A future convenience method — never a replacement.
- **Only Core Workflow pages participate.** Utility pages remain conventional.
- **The App Shell never reloads.** Sidebar, Topbar, theme, notifications stay mounted across all route changes.
- **Each workspace is independently routable.** Browser history, direct links, and sidebar clicks all work normally.

---

## Core Workflow

These four pages form the primary outbound workflow pipeline:

| Page | Route | Component | Future Workspace Flow Position |
|------|-------|-----------|-------------------------------|
| Mission Control | `/mission-control` | `MissionControlDashboard` | 1 — Entry / Overview |
| Discovery | `/discovery` | `DiscoveryWorkspace` | 2 — Lead Discovery |
| Campaigns | `/campaigns` | `CampaignsPage` | 3 — Campaign Management |
| Draft Review | `/draft` | `DraftReviewWorkspace` | 4 — Draft Approval / Send |

In the future, these will occupy the full viewport and scroll smoothly between one another.

---

## Utility Pages

These pages must never become part of Workspace Flow. They remain conventional navigation:

- Settings — `/settings`
- Billing — `/billing` (future)
- Integrations — `/integrations` (future)
- Team — `/team` (future)
- Notifications — `/notifications` (future)
- API Keys — `/api-keys` (future)
- Logs — `/logs` (future)
- Future admin pages

---

## App Shell Architecture

The following components remain persistently mounted across all route changes:

```
App Shell (always mounted)
├── CopilotProvider (context)
├── Sidebar (fixed left, 256px)
│   ├── Logo / Branding
│   ├── Navigation (Core Workflow + Utility Pages)
│   └── Status indicator
├── Content Area (ml-64)
│   ├── Topbar (fixed top, h-16, left: 256px)
│   ├── main (pt-16, flex-1, overflow-y-auto)
│   │   └── WorkspaceContainer (wraps children)
│   │       └── Page content
│   ├── ToastContainer (global notifications)
│   └── CopilotPanel (except /draft)
```

**Persistence guarantees:**
- `CopilotProvider` wraps the entire layout — context survives route changes.
- `Sidebar` and `Topbar` are rendered in the layout — they never unmount between dashboard routes.
- `ToastContainer` stays mounted — toasts persist across navigations.
- Only the `children` inside `<main>` change when the route changes.
- `CopilotPanel` mounts/unmounts based on pathname (hidden on `/draft`).

---

## WorkspaceContainer

`WorkspaceContainer` is the future home of:

- Route transition management
- Scroll snap controller (full-viewport workspaces)
- Motion orchestration
- Workspace caching and state preservation
- Page prefetching
- Intersection observation for active workspace detection

**Current behavior:** Simply renders `children` with consistent viewport sizing.

**Future contract:** Each workspace page renders inside `WorkspaceContainer`, occupies `100vh`, uses consistent padding, and avoids custom navigation wrappers.

See `frontend/components/layout/WorkspaceContainer.tsx` for implementation and extension points.

---

## Workspace Contract

Every Core Workflow page must:

1. Render inside `WorkspaceContainer`
2. Occupy the full viewport (`h-full`, flex column)
3. Use consistent horizontal padding (`px-6`)
4. Avoid custom wrappers that interfere with layout
5. Support independent routing (no cross-page dependencies)
6. Use `overflow-y-auto` on its own content area when scrolling is needed
7. Not include its own `<header>`, `<nav>`, or layout chrome
8. Load its own data independently (no shared workspace state)

---

## Performance Principles

The future Workspace Navigation system must:

| Requirement | Constraint |
|---|---|
| Frame rate | Maintain 60 FPS during scroll transitions |
| Navigation blocking | Never block route changes — always respond within 100ms |
| App Shell | Never reload Sidebar, Topbar, or global context |
| Workspace state | Preserve scroll position and form state when scrolling between workspaces |
| Prefetching | Support route prefetching on idle / hover |
| Responsiveness | Keep sidebar navigation responsive during transitions |
| Scalability | Architecture must support up to dozens of pages without degradation |

---

## Future Implementation Strategy

When scroll-based navigation is implemented, follow this order:

1. **Install Framer Motion** — for `AnimatePresence` and layout animations.
2. **Extend `WorkspaceContainer`** — add `AnimatePresence` wrapping children, implement scroll snap container with `scroll-snappoints-y`.
3. **Add scroll controller** — detect scroll position, map to active workspace index, update route via `router.replace` (no full navigation).
4. **Add workspace cache** — keep up to 3 workspaces mounted at all times (prev + current + next) to preserve state.
5. **Add prefetching** — prefetch adjacent workspace data on idle.
6. **Verify Sidebar still works** — clicking a sidebar link scrolls to the correct workspace.
7. **Verify browser history** — scrolling creates history entries, back/forward scrolls to workspace.
8. **Remove CopilotPanel special case** — ensure it works across all workspaces.

---

## Extension Points

The following extension points are documented inside `WorkspaceContainer.tsx`:

- Route transition manager
- Scroll snap controller
- Workspace prefetching
- Shared animation context
- Workspace cache
- Motion orchestration
- Intersection observer

These are `TODO` comments only — no implementation yet.

---

## File Map

```
frontend/
├── app/
│   └── (dashboard)/
│       ├── layout.tsx              ← App Shell (Sidebar + Topbar + WorkspaceContainer)
│       ├── mission-control/
│       │   └── page.tsx             ← Wraps in WorkspaceContainer
│       ├── discovery/
│       │   └── page.tsx             ← Wraps in WorkspaceContainer
│       ├── campaigns/
│       │   └── page.tsx             ← Wraps in WorkspaceContainer
│       ├── draft/
│       │   └── page.tsx             ← Wraps in WorkspaceContainer
│       └── settings/
│           └── page.tsx             ← Utility — no WorkspaceContainer
├── components/
│   └── layout/
│       ├── Sidebar.tsx              ← Core Workflow + Utility Pages with separator
│       ├── Topbar.tsx               ← Persistent shell
│       └── WorkspaceContainer.tsx   ← Future navigation hub
```

---

## Glossary

| Term | Definition |
|---|---|
| Workspace Flow | The four-page pipeline (Mission Control → Discovery → Campaigns → Draft Review) |
| Utility Pages | Non-workflow pages (Settings, Billing, etc.) with conventional navigation |
| App Shell | Persistently mounted layout: Sidebar + Topbar + global context |
| WorkspaceContainer | Component wrapping workspace content, future home of transitions and scroll logic |
| Workspace Contract | Shared conventions every workspace page must follow |
