# Batch 10 — Campaign detail and Draft Review workspace context

## Findings verified

The Batch 9 navigation/cache gaps still existed. Discovery's successful campaign
link omitted workspace scope; campaign detail's repository, mutations and job
polls omitted it; campaign lead/draft sections dropped it; Draft Review had no
membership-resolved page scope and used session-only cache/navigation keys.
The actual inline draft component is
`frontend/components/campaigns/CampaignDraftsSection.tsx`, not `dashboard/`.

Already fixed before this batch: backend campaign authorization, draft list/edit
route workspace resolution, canonical text/subject persistence (including empty
subjects), and pending status after editing. Those changes were preserved.
Refinement was an additional verified gap: its route/service still used an
identity-only, default-workspace read/write path.

## Changes

- Discovery campaign links carry `workspace_id`.
- Campaign detail and Draft Review reuse `useIntelligenceWorkspace`. An explicit
  inaccessible workspace is not replaced with another workspace. The existing
  resolver permits an implicit choice only for a single accessible workspace;
  ambiguous/missing choices render an error before feature requests.
- Both page owners key their feature component by authorized identity/workspace
  and campaign ID. A changed scope immediately removes old feature state.
- Campaign cache keys include workspace and campaign; draft/campaign-metadata
  caches include workspace; reviewed-draft navigation keys additionally include
  session and campaign filter. Old SWR callbacks are guarded after unmount.
- Existing API functions accept optional trailing workspace arguments and send
  `X-Workspace-Id`. Existing callers/contracts remain compatible; affected page
  callers supply explicit scope for reads, edits/refinement, approval, campaign
  mutations, strategy/draft start and status reads, and lead attachment.
- Campaign research links retain campaign and workspace through the existing
  Discovery URL helper. Back navigation reuses the existing workspace/identity
  Discovery URL hint, or a scoped Discovery URL when no valid hint exists.
  A hint whose query workspace disagrees with the authorized scope is rejected.
- Campaign drafts link to scoped Draft Review, which has a scoped return link.
- Failed draft/context reads render a recoverable error rather than an empty
  success. Campaign draft listing verifies that the campaign exists in the
  selected workspace; canonical draft reads are strict.
- Refinement resolves membership scope at the route, uses strict canonical
  reads and awaited writes in that scope, and rejects a foreign draft before
  rewrite work. No new model, prompt, storage or workflow was introduced.

Workspace IDs remain requested scopes, not authorization grants. The backend's
existing active-membership checks were not bypassed or weakened. Campaign
idempotency, attachment compensation ownership, generation jobs and Beta
capability gates were not redesigned. No automatic generation, sending,
scheduling or campaign execution was added.

## Files changed in Batch 10

```text
backend/services/drafts/api.py
backend/services/drafts/service.py
backend/tests/test_campaign_draft_workspace_context.py (new)
frontend/app/(dashboard)/campaigns/[id]/page.tsx
frontend/components/dashboard/DiscoveryCampaignActions.tsx
frontend/components/campaigns/CampaignLeadsSection.tsx
frontend/components/campaigns/CampaignDraftsSection.tsx
frontend/components/draft/DraftReviewWorkspace.tsx
frontend/lib/api.ts
frontend/lib/repositories.ts
frontend/lib/discovery-mode.ts
frontend/lib/discovery-context.ts
frontend/tests/campaign-draft-workspace.test.mts (new)
frontend/tests/campaign-creation-safety.test.mts
docs/BATCH10_WORKSPACE_CONTEXT.md (this report)
```

The existing campaign-generation source assertion was updated to require its
workspace argument; no assertions were weakened. Prior dirty application,
migration and test-safety work was preserved.

## Offline validation

- Backend combined regression run: **241 passed, 0 failed, 0 skipped**. This is
  the 18 verified-offline Batch 9 suites listed in its report plus
  `test_campaign_draft_workspace_context.py` (8 cases).
- Frontend combined regression run: **78 passed, 0 failed, 0 skipped**. This is
  the 16 Batch 9 frontend files plus `campaign-draft-workspace.test.mts` (4 tests).
  The final return-hint consistency assertion was also rerun in that 4-test suite.
- TypeScript: passed, `tsc --noEmit --incremental false`.
- Production build: passed, `NEXT_TELEMETRY_DISABLED=1 npm run build`.
- Backend compileall (excluding `.venv`) and `git diff --check`: passed.

New backend tests exercise in-process ASGI routes with the real membership
resolver and fake PostgREST rows. They cover a non-default selected workspace,
wrong/unknown/ambiguous scope, scoped read/edit/empty-subject read-back, scoped
refinement, rejection before rewrite, and read failure not becoming empty
success. Identity lookup and persistence/model boundaries are mocked.
Frontend tests mock fetch, test late cache responses and return hints directly,
and inspect page wiring. They are not mounted React/browser tests.

Database-backed and external-provider suites were excluded, not executed or
counted as skipped. The hardened test-runtime/network protections were unchanged.

Known baseline: the standalone `discovery-routing.test.mts` Node runner fails
on the extensionless `discovery-request` import in `conversationMachine.ts`, as
recorded in Batch 9. It was not rerun or altered here. Non-failing warnings remain
for Starlette/httpx deprecation, Node module-type inference, and Next's multiple
lockfiles/workspace-root inference.

## Remaining risks

- No real browser navigation, render timing, clipboard or layout verification.
  Keyed remount/callback wiring is inspected, not proven through browser E2E.
- No live Supabase/RLS or transaction/lease verification. Batch 5's existing
  migration/RPC contract still needs an approved disposable database; no
  migration was applied.
- This batch covers the requested Discovery → detail → drafts/review path.
  Other application entry points (for example standalone legacy campaign index,
  creation and Copilot surfaces) are not a claim of app-wide workspace coverage.
  Dormant outbound paths remain governed by existing Beta restrictions.
- Real provider/model/auth operational behavior remains unverified. Offline
  passing tests are not a production-readiness sign-off.

No database/provider connections, commits, pushes, deployments, production
changes, migrations or development servers were used.
