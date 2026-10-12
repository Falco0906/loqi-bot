# Batch 9 — Beta journey verification

Date: 2026-10-11. Scope: current dirty checkout, including Batches 1–8 and
test-safety remediation. No database/provider connections, migrations,
development servers, commits, pushes, or production operations were performed.

## Verdict

The selected-lead backend contracts pass offline integration/regression checks.
The complete browser journey and real database transactions are **not verified**.
Multi-workspace navigation into campaign detail and legacy Draft Review remains
incomplete. This is not a production-readiness sign-off.

## Journey results and state ownership

| Transition | Canonical owner / contract | Verification and limitation |
| --- | --- | --- |
| Workspace selection | `services/workspace/access.py`; membership-authorized workspace; `X-Workspace-Id` is a request, not authority | Existing offline workspace/context tests pass. New ASGI journey uses identity/membership doubles; real login/RLS were not exercised. |
| CSV preview → confirmation | `services/leads/api.py`, `parse_csv_preview`, `import_csv_rows`; existing preview/import POSTs | Actual in-process HTTP routes parse/import/read/analyze successfully with fake repositories. Preview alone makes no writes. Confirmed CSV workspace-header omission fixed. |
| Imported records → Lead Database | `workspace_leads`; `state._normalize_lead`; `list_workspace_leads` | The same saved IDs are returned by listing and used downstream. Duplicate replay skips existing email leads. Existing invalid-row/systemic-failure tests pass. |
| Universal Discovery | `/discovery`, `create_search_run`, existing staged job/finalization path | Offline staged-result, provider-failure, dedupe/provenance and zero-result regressions pass. No real provider search was made. |
| Filters/count/pages | Existing leads GET with `q`, supported filters, `page`, optional `discovery_id` | Composed filters, stable ordering beyond 1,000 canonical rows, bounded projection queries and incomplete-hydration warnings pass. Provider failure is not silently a successful complete empty search. |
| Selection → intelligence/campaign | Stable `workspace_leads.id`; selection scope includes workspace/query/run/filters, excludes page | Existing pure/source/API tests cover pagination preservation, context invalidation and optional analysis. New journey authorizes the actual imported IDs for campaign creation. No mounted-browser checkbox test. |
| Optional analysis | Leads `/analyze` → selected scoped retrieval → deterministic intelligence + explicit Knowledge scope | Real local intelligence functions run on imported facts in the new journey. No model call occurs. Business guidance remains separate from prospect facts. |
| Explicit AI generation | Leads `/generate-strategy` → existing `jobs` leased workflow `lead_strategy` | HTTP request queues, it does not execute a model call inline. Same key/selection replays one job; changed selection conflicts. Worker uses authorized Phase 4B snapshot and checkpoints per-lead results. Model transport is mocked. |
| Timeout/navigation recovery | Generation key/job + workspace/actor + original selected IDs; GET recovery | Existing lost-response, delayed completion, interrupted worker, partial success and stale selection tests pass. Mount recovery only reads; it does not implicitly POST or cancel the durable job. |
| Strategy/outreach review | AI-labelled ephemeral display; durable job result holds generation output | Validated structured output and supported evidence pass. 4C results can be reviewed/copied but are **not canonical Draft Review entities**. No new draft storage/handoff was added. |
| Canonical draft review/edit | Existing `drafts.subject/body/status`; PUT drafts route | Confirmed no-op text persistence fixed and canonical read-back tested. Empty subject clearing and pending-state UI consistency fixed. Legacy review page still drops selected workspace (see blockers). |
| Campaign create/attach | Existing campaign service/repositories; canonical campaign/lead relationships | Creation/replay uses imported IDs in the cross-feature test. Adjacent tests cover attachment retry and rollback only of operation-owned links. No implicit strategy scheduling. Actual RPC transaction remains unverified. |
| Return to Discovery | URL is working-context authority; workspace/user-scoped browser hint restores URL; durable run/results fetched server-side | Existing restoration tests pass for explicit fresh entry, historical context, stale responses, membership changes and ordinary return. Browser back/forward and remount behavior were not exercised in a real browser. |
| Beta restrictions | Existing capability owner and backend boundaries | Offline tests reject delivery, scheduling, automated follow-ups, campaign execution and autonomous workflow/sourcing paths before side effects. Explicit person-initiated provider search remains permitted. |

Selection is not a second durable lead authority. It is scoped client navigation
state. Search/job results, lead IDs, provenance, campaign links and generation
checkpoints remain canonical server-side data. Losing browser storage may lose
the navigation hint; explicit URL/history restoration remains available.

## Confirmed defects fixed

1. **CSV/Lead Database workspace omission.** `contacts/page.tsx` called listing,
   preview and import without the selected workspace while Discover/Intelligence
   used an explicit scope. With multiple memberships the backend refuses an
   ambiguous request. Reused `useIntelligenceWorkspace`, keyed page state by its
   identity/workspace scope, and passed that scope through the existing API.
   No new workspace authority or storage was introduced.
2. **Stale listing and misleading table errors.** Contacts had no obsolete-read
   guard and shared CSV action errors with the table's availability state.
   Superseded/unmounted reads are aborted and their responses ignored;
   preview/import errors now remain separately visible. A ref prevents duplicate
   same-tick confirmation. Search changes clear selection; pagination does not.
3. **Edits reported success without saving the message.** Draft Review submitted
   `text`, but `_update_draft_row` only persisted `body`/`subject`. The edit route
   also omitted selected-workspace resolution. The route now resolves scope,
   service reads/writes that scope strictly and asynchronously, and the canonical
   writer translates the existing subject-prefixed text contract into fields.
   Unexpected persistence errors propagate rather than becoming fake success.
4. **Cleared subject/local status mismatch.** Review omitted the subject header
   when its value was empty, so the original stored subject remained. Review now
   submits an empty header explicitly and reflects the existing backend pending
   status after an edit. No send lifecycle or automatic generation was added.

## Files changed in this batch

- `backend/services/drafts/api.py`
- `backend/services/drafts/service.py`
- `backend/services/workspace/state.py`
- `backend/tests/test_beta_journey_offline.py` (new)
- `frontend/app/(dashboard)/contacts/page.tsx`
- `frontend/components/draft/DraftReviewWorkspace.tsx`
- `frontend/lib/api.ts`
- `frontend/tests/beta-journey-contracts.test.mts` (new)
- This report.

Other dirty files belong to earlier work; they were preserved. No SQL, test
runtime guard, model/provider configuration or migration was changed in Batch 9.

## Exact validation

Final combined backend run: **233 passed, 0 failed, 0 skipped**. Files under
`backend/tests/`:

```text
test_beta_journey_offline.py
test_search_field_consistency.py
test_lead_csv_import.py
test_beta_lead_intelligence.py
test_discovery_staged_persistence.py
test_campaign_attachment_rollback.py
test_workspace_context_propagation.py
test_discovery_campaign_selection.py
test_campaign_creation_safety.py
test_campaign_execution_safety.py
test_lead_generation_reliability.py
test_draft_generation_truthfulness.py
test_supabase_test_safety.py
test_shared_test_identity.py
test_discovery_context_restoration.py
test_beta_lead_strategy_drafts.py
test_beta_feature_policy.py
test_draft_batch_job_engine.py
```

Final combined frontend run: **74 passed, 0 failed, 0 skipped**, via `node --test`.
Files under `frontend/tests/`:

```text
beta-journey-contracts.test.mts
search-field-consistency.test.mts
discovery-context.test.mts
discovery-campaign-actions.test.mts
beta-lead-flow.test.mts
lead-intelligence.test.mts
lead-generation-recovery.test.mts
discovery-manual-provider-search.test.mts
discovery-job-auth.test.mts
discovery-request.test.mts
discovery-qualification.test.mts
campaign-creation-safety.test.mts
copilot-discovery-layout.test.mts
draft-copy-actions.test.mts
beta-onboarding-gmail-optional.test.mts
draft-lifecycle.test.mts
```

Separate existing baseline `node --test tests/discovery-routing.test.mts`:
**0 passed, 1 failed test file, 0 skipped**. Node rejects the extensionless
`discovery-request` import in `frontend/lib/conversationMachine.ts` before test
assertions run. No unrelated ESM infrastructure change was made.

TypeScript (`tsc --noEmit --incremental false`), production build, backend
`compileall` excluding `.venv`, and `git diff --check`: passed. Warnings:
Starlette/httpx TestClient deprecation, Node module-type detection, and Next's
multiple-lockfile/workspace-root inference. No new dependency installed.

All selected backend tests were inspected for fake/mocked dependencies and run
under the hardened process-owned test runtime/offline network guard. The
unrestricted backend suite and database/provider integration suites were not
run; they are **excluded**, not counted as skipped tests in the totals above.

## Remaining blockers and follow-up

1. **Selected workspace lost on legacy campaign/review navigation.**
   `DiscoveryCampaignActions.tsx:151` links to `/campaigns/<id>` without scope;
   `campaigns/[id]/page.tsx:92` calls `fetchCampaign(campaignId)` and
   `lib/repositories.ts:470` calls `getCampaign(token,id)` without scope.
   `CampaignDraftsSection.tsx:57,159` similarly omits scope in reads/review links.
   `DraftReviewWorkspace.tsx:227,425` lists/edits without a workspace argument;
   its caches are session-scoped, not workspace-scoped. This can reject
   multi-workspace requests or retain stale client content. No live leakage was
   demonstrated. Complete propagation/cache scoping should be a bounded next
   batch, not an unrelated campaign architecture rewrite.
2. **Database transaction/migration contract unverified.** Existing Batch 5
   migration `048_campaign_creation_idempotency.sql` and its RPC must be reviewed
   and verified in an approved disposable test database before claiming durable
   concurrent creation/rollback guarantees. No migration was applied here.
3. **No safe browser E2E framework found.** Repository search found no Playwright,
   Cypress, Puppeteer or Selenium setup. React interactions/layout/clipboard,
   reload, back/forward and navigation were not tested in a browser. Smallest
   follow-up: a separately scoped browser runner with all backend routes mocked,
   delayed/out-of-order fixture responses and no external credentials; then an
   approved disposable-database suite. Do not substitute source-text tests for
   mounted UI assertions.
4. **Real provider/model/auth behavior unverified.** No quality, cost, provider
   latency, membership/RLS or production-health conclusions follow from mocks.
   Worker leases, restart recovery and migration execution need independent
   disposable-environment validation.
5. **4C output vs canonical Draft Review remains a product boundary.** The
   selected-lead result is displayed/copied, not automatically materialized as a
   campaign draft. Canonical editing is separately tested; a persistence/handoff
   feature was intentionally not invented in this reliability batch.

The minimal release gate is: scoped campaign/review navigation, safe browser
journey coverage, approved test-database RPC/lease verification, and repair of
the known standalone routing-test import issue. Existing Beta restrictions and
explicit human action boundaries must remain intact.
