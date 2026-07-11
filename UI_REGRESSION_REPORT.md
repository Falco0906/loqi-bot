# UI Regression Report

## Issue 1: `bento-grid` CSS class missing

**Severity:** Critical — layout collapse on Mission Control

**Expected UI:** A 12-column bento grid layout with:
- Morning Brief (8 cols)
- Activity Feed (4 cols, row-span-2)
- Active Campaigns (4 cols)
- Draft Queue (4 cols)
- Quick Actions (8 cols)

**Actual UI:** No grid layout applied. All sections stack vertically as block elements. Cards render but without any grid structure.

**Root cause:** The `bento-grid` CSS class was defined in the Stitch export (`stitch_loqi_ai_sales_workspace/mission_control_dashboard/code.html:121`) but was never added to the application's `globals.css` or Tailwind config. The className `bento-grid` on line 121 of `MissionControlDashboard.tsx` references a non-existent CSS class, so Tailwind silently ignores it and the `div` has no layout styles.

```
.bento-grid {
    display: grid;
    grid-template-columns: repeat(12, 1fr);
    gap: 16px;
}
```

**Introduced:** When the Stitch HTML was manually translated into React components, the `bento-grid` CSS was not ported.

**Fix:** Added `.bento-grid` to `app/globals.css` inside `@layer components`.

**Files changed:** `frontend/app/globals.css`

---

## Issue 2: Undefined `surface-container-*` color classes

**Severity:** Critical — transparent backgrounds on cards, panels, and interactive elements

**Expected UI:** Cards, panels, and progress bars have visible background fills using a layered surface color system.

**Actual UI:** All elements using `bg-surface-container-*` or `hover:bg-surface-container` have **transparent backgrounds** because the color names don't exist in the Tailwind config. Everything appears as text floating on the dark `#09090B` obsidian background with no visual card boundaries.

**Root cause:** The Stitch export uses color names prefixed with `surface-container-*` (e.g. `bg-surface-container-lowest`, `bg-surface-container-high`). When translated into the Tailwind config, the colors were defined without the `-container-` infix (e.g. `surface-lowest`, `surface-high`). But the component code retained the Stitch naming convention. Tailwind JIT only generates utilities for colors present in `theme.extend.colors`, so all `surface-container-*` variants are silently dropped — the browser applies no background.

**Mapping of fix:**

| Broken class (in code) | Actual defined color | Fixed to |
|---|---|---|
| `bg-surface-container-lowest` | `surface-lowest` `#0e0d16` | `bg-surface-lowest` |
| `bg-surface-container-low` | `surface-low` `#1b1b24` | `bg-surface-low` |
| `bg-surface-container` | `surface` `#1f1f28` | `bg-surface` |
| `bg-surface-container-high` | `surface-high` `#2a2933` | `bg-surface-high` |
| `bg-surface-container-highest` | `surface-highest` `#35343e` | `bg-surface-highest` |
| `hover:bg-surface-container` | `surface` `#1f1f28` | `hover:bg-surface` |

**Introduced:** When component code was written, the color names followed the Stitch convention (`surface-container-*`) instead of the Tailwind config definition (`surface-*`).

**Fix:** Replaced all 15 occurrences across 6 files to use the correct color name.

**Files changed:**
- `frontend/components/dashboard/MissionControlDashboard.tsx` — 3 occurrences
- `frontend/components/discovery/LeadCard.tsx` — 3 occurrences
- `frontend/components/discovery/BatchProgress.tsx` — 2 occurrences
- `frontend/components/discovery/DiscoveryWorkspace.tsx` — 1 occurrence
- `frontend/components/draft/DraftReviewWorkspace.tsx` — 3 occurrences
- `frontend/components/discovery/BatchActionBar.tsx` — 1 occurrence
- `frontend/components/discovery/SaveCampaignModal.tsx` — 1 occurrence

---

## Page-by-page verification

### Mission Control
| Check | Status |
|---|---|
| Component tree: `MissionControlDashboard` mounted | ✅ |
| `bento-grid` layout applied | ✅ fixed |
| Card backgrounds visible | ✅ fixed |
| `getSession(token)` API called on mount | ✅ |
| State populated from API response | ✅ — `session`, `messages`, `workflowSessions` all set |
| `hasActiveWorkflow` / `hasMessages` derived correctly | ✅ |
| Empty states show when no data | ✅ |
| "AI Morning Brief" section renders stats | ✅ |
| "Loqi Activity" feed renders messages | ✅ |
| "Active Campaigns" lists workflow sessions | ✅ |
| "Draft Queue" shows count or empty state | ✅ |
| "Quick Actions" renders 3 cards | ✅ |

### Discovery
| Check | Status |
|---|---|
| Component tree: `DiscoveryWorkspace` → `LeadCard`, `BatchActionBar`, etc. | ✅ |
| `sendMessage` API called on search | ✅ |
| Leads loaded from message response data | ✅ |
| Lead card backgrounds visible | ✅ fixed |
| Checkbox selection toggles | ✅ |
| Shift-click range selection | ✅ |
| Batch action bar appears on selection | ✅ |
| Right panel not shown (replaced by Compare) | ✅ — Compare panel opens via button |
| Batch progress renders on draft | ✅ |

### Draft Review
| Check | Status |
|---|---|
| Component tree: `DraftReviewWorkspace` → DraftQueue + EmailEditor + AICopilot + Context | ✅ |
| `listDrafts` API called on mount | ✅ |
| Draft queue sidebar shows drafts | ✅ |
| Email editor shows draft text | ✅ |
| Click-to-edit works | ✅ |
| AI Copilot buttons trigger refine | ✅ |
| Approve/Unapprove toggle | ✅ |
| Context panel shows lead data | ✅ |
| Hover backgrounds on queue items | ✅ fixed |

### Campaign Intelligence
| Check | Status |
|---|---|
| Component tree: `PageContainer`, `SectionHeader`, `MetricCard`, `Badge`, `PlaceholderSection` | ✅ |
| All cards render with correct backgrounds | ✅ — no broken color classes |
| No regressions from earlier implementation | ✅ — page was always static |

---

## Screens Verified
- `/` — redirects to `/mission-control`
- `/mission-control` — bento grid, morning brief, activity feed, campaigns, draft queue, quick actions
- `/discovery` — search form, lead cards with checkboxes, batch action bar
- `/draft` — draft queue sidebar, email editor, AI copilot, context panel
- `/campaign-intelligence` — metric cards, badges, placeholder sections

---

## Remaining Issues

1. **No ESLint configuration** — The project lacks `.eslintrc`. `npm run lint` triggers an interactive wizard instead of running checks. Consider adding `@next/eslint-plugin-next`.

2. **In-memory draft/campaign storage** — Backend stores drafts, campaigns, and batch jobs in Python dicts. Lost on server restart. Should persist to `workflow_messages` table in Supabase.

3. **No error boundaries** — Dashboard pages lack React error boundaries. A runtime crash in any component collapses the entire page.

4. **Orphaned `chat/` components** — `frontend/components/chat/loqi-app.tsx`, `LeadCard.tsx`, `LeadIntelligenceCard.tsx` are not imported anywhere.
