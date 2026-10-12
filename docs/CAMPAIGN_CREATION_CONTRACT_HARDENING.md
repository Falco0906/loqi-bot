# Campaign creation authorization and idempotency hardening

This bounded batch preserves Batches 1–11 and the test-runtime safeguards.
No database, provider, SQL execution, migration application, or production
operation is involved. SQL assertions below are structural coverage, not proof
of PostgreSQL transaction or concurrency behavior.

## Authorization policy

Confirmed discrepancy: `services/workspace/access.py` authorizes through ACTIVE
organization membership, while the original 048 RPC accepted workspace owners
and `workspace_members` instead. Those are not interchangeable contracts.

Creation now uses `resolve_selected_workspace_id`, including on replay, rather
than the legacy owner-default fallback. The RPC checks the same `memberships`
table, organization, user and ACTIVE status. Owners and workspace members qualify
when they also satisfy that canonical organization membership boundary; ownership
or a workspace-member row alone is not an independent grant. Other campaign
routes retain their existing compatibility resolver.

Membership statuses `removed`, `left`, and `pending`, and missing membership rows,
deny creation. Migration 025 defines no membership `deleted_at` column: a deleted
membership means the row is absent. No new role or membership semantics were added.
An old owner-only account without organization membership cannot create through
the public endpoint until its membership is established through an authorized
existing lifecycle. This batch does not manufacture membership or bootstrap it.

## Required findings

| Finding | Confirmed and chosen policy | Changes | Offline coverage | PostgreSQL verification still required |
| --- | --- | --- | --- | --- |
| Deleted/inactive workspace | Deleted workspaces are inaccessible. Canonical access currently permits non-deleted suspended/archived workspaces with active organization membership; no mutation-specific restriction is defined. Preserve that policy consistently, rather than inventing a suspension rule. | Strict creation resolver in `campaigns/api.py`; 048 retains `deleted_at IS NULL` and locks the workspace. | Owner/member/organization-member, revoked/missing membership, deleted workspace, suspended and archived workspace cases exercise the actual resolver with a fake client. | Workspace deletion/status changes concurrent with the RPC; actual grants and RLS. Suspended/archived mutation policy remains a product decision. |
| Deleted discovery | A new campaign cannot reference a deleted, missing or foreign-workspace discovery. Replay recovers an already committed campaign; it does not reattach a subsequently deleted discovery. | Service checks returned scope/deletion; 048 checks deletion and locks the matched discovery. | Service tests reject missing/deleted/foreign discovery before persistence. SQL structural assertion checks the predicate/lock. | Actual deleted-discovery rejection, concurrent soft/hard deletion, FK behavior. |
| Concurrent membership revocation | Authorization must be valid at the transaction's membership-lock acquisition and remain stable through commit. A revocation that wins first must reject creation; one that follows the acquired lock waits. | 048 locks workspace, then matching ACTIVE membership with `FOR SHARE`. Database-side authorization remains in place, including RPC replay. | Actual request resolver rejects revoked memberships; replay rechecks request authorization. SQL structural lock assertions only. | Two real connections racing UPDATE/DELETE revocation with creation; READ COMMITTED predicate rechecks, blocking order, deadlocks and transaction boundaries. No offline test proves these guarantees. |
| Lead snapshot consistency | Validate and attach exactly the same locked, workspace-scoped, non-deleted canonical set. Duplicate/null/unavailable requested IDs must not silently pass. | One ordered `FOR SHARE` subquery produces `v_lead_ids`; its cardinality is validated and only that array is inserted. The independent second SELECT count is removed. | Existing selected-ID/duplicate/foreign/missing validation tests; SQL structural assertions verify one lead scan and attachment from its captured array. | Concurrent insert/move/delete/soft-delete of leads, duplicate and null SQL arrays, lock ordering, rollback on FK/attachment failure. |
| Post-commit auxiliary failures | Campaign and links remain authoritative. Hydration, timeline, publication or feedback errors remain visible and same-key replay recovers the campaign. Optional activity and compatibility-event failures are logged without invalidating the commit. Replay is not auxiliary repair. | Existing semantics retained; a compatibility event returning False now emits an explicit unconfirmed warning. | RuntimeError and missing hydration; activity failure; timeline/publication/feedback failure; compatibility-event exception/False; every case verifies the original campaign survives and replay adds no campaign/links or repeats failed effects. | Actual RPC commit followed by transport loss, process death and hydration failure. No exactly-once auxiliary guarantee is claimed. |
| Migration bootstrap | Missing baseline/order dependencies remain unresolved, not silently created. | Documentation only; no bootstrap implemented. | No SQL execution. | Review and execute an approved prerequisite bootstrap in a disposable database before installing 048. |

## Creation caller inventory and decisions

| Caller | Existing behavior / classification | Decision |
| --- | --- | --- |
| `frontend/app/(dashboard)/campaigns/new/page.tsx` | Stable `creation_key` in URL plus mounted ref; retries reuse it. Original fields are still required to recover the same request. | Preserve; public creation requires the key. |
| `frontend/components/dashboard/DiscoveryCampaignActions.tsx` | Stable `campaign_creation_key` in URL and captured intent; explicit recovery reuses captured fields and key. | Preserve; public creation requires the key. |
| `frontend/lib/api.ts::saveCampaign` | Optional positional key could previously be omitted. | Reject absent/blank/oversized keys before fetch. Do not generate a new key inside a retrying request helper. |
| `campaigns/api.py::save_campaign` | Previously allowed unkeyed requests and legacy owner fallback. | Intentional API tightening: HTTP 422 for missing/invalid key; membership-authorized selected scope, including retry. Same-key changed payload remains 409. |
| `campaigns/service.py::create_campaign` | Previously implicitly chose non-atomic unkeyed compatibility. | Default refuses missing/invalid key. Legacy internal behavior is preserved only behind explicit `allow_legacy_creation=True`; no production caller currently passes it, and it is not exposed in the request model. |
| `strategic/actions.py::_execute_campaign` | Active approved-action path; generated a fresh UUID and separately persisted. Metadata scan did not give database concurrency protection. | Reuse the existing creation identity/RPC, keyed by durable approved action ID and authorized workspace/actor. Recover the original commit on lost response; changed proposal conflicts. No implicit strategy generation added. |
| `copilot/runners.py::run_campaign` | Unkeyed UUID/separate writes. Currently unavailable through Copilot's `PHASE2_MUTATION_TOOLS` gate. | Preserve dormant implementation; must adopt the creation contract before it is enabled. Direct internal invocation is not retry-safe. |
| `workflows/registry.py::_execute_create_campaign` | Placeholder response only; does not persist a campaign. Legacy execution is Beta-disabled. | Preserve; not a creation writer. |
| `workspace/state.py::persist_campaign`, `persist_campaign_row` and backfill/replay | Low-level compatibility persistence; not a user intent-key authority. | Preserve; do not expose as a replacement public creation path. |
| `workspace/state.py::duplicate_campaign` / Duplicate API | Separate existing deep-copy command, fresh UUID, strategy and link copying. | Distinct mutation contract, unchanged in this bounded batch. A lost-response manual retry can still create another copy; it requires a separate duplication-idempotency follow-up. |
| Database integration-test creation requests | Previously omitted the key in round-trip and Discovery job fixtures. | Supply one intent key per creation. Updated but not executed: these require a separately approved disposable database and membership-backed fixture setup. |

No active caller of `create_campaign` is allowed to silently enter unkeyed
compatibility. Keys remain scoped to actor/workspace; fingerprint sorting/default
normalization and conflict checks remain unchanged. The canonical campaign row is
still the durable receipt. No new table, store, client, job or provider was added.

## Auxiliary-effect outcomes

The RPC commit precedes hydration and activity/timeline/publication/feedback.
Hydration failure leaves the committed campaign intact and the same key recovers
it after the read becomes available. Later synchronous effects can fail the HTTP
request after commit; retry returns the original campaign, not another one.
Optional activity failure returns success with a warning. Compatibility-event
work uses the existing client-independent thread task; exception/False is logged,
but process exit can still lose it. Replay does not guarantee repairing missing
effects. Activity has a source key, but that is not an exactly-once guarantee for
all effects or for the full application request.

## Migration prerequisites and order gaps

048 now additionally depends on `memberships` from
`supabase/migrations/025_organization_persistence.sql`. It also needs 004 identity,
006 workspaces, 007 canonical domain leads, 008 campaigns/attachments/strategies,
014 discoveries plus the guarded `campaigns.discovery_id` alteration, and the
016 campaign lifecycle vocabulary. Supabase roles and applicable table privileges
must exist; the RPC remains SECURITY INVOKER and restricted to service_role.

The numbered Supabase directory starts at 003; that migration expects a UUID
`users.id` baseline absent from that sequence. The separate persistence 001 defines
TEXT `users.id` and is not a compatible automatic substitute. `workflow_sessions`
is supplied by the separate `supabase/multi_client_mvp.sql`, not the numbered
sequence. Applying 014 before campaigns exist skips its guarded campaign column.
The legacy migration helper does not apply all numbered migrations or 048; CI
currently checks the other migration directory's filenames, not SQL execution.
No applied migration history or live schema has been examined here.

## Remaining validation

Disposable PostgreSQL must verify installation, service-role grants, actual
membership/lead/discovery rejection, same-key races, changed-payload races,
revocation ordering, lead mutation races, atomic rollback and response-loss
recovery. Offline tests use mocked/in-memory dependencies and cannot establish
any PostgreSQL concurrency guarantee. Inline lead normalization still occurs
outside the campaign RPC; those canonical lead/company writes can survive a
later campaign failure. Physical campaign deletion removes its idempotency
receipt. Neither limitation was redesigned in this batch.

## Validation actually executed

Backend command (database/external opt-ins explicitly off, Redis unconfigured):

```text
LOQI_RUN_DB_INTEGRATION=0 LOQI_RUN_EXTERNAL_INTEGRATION=0 REDIS_URL= backend/.venv/bin/python -m pytest
  backend/tests/test_campaign_creation_contract.py
  backend/tests/test_campaign_creation_safety.py
  backend/tests/test_campaign_attachment_rollback.py
  backend/tests/test_discovery_campaign_selection.py
  backend/tests/test_manual_campaign_creation.py
  backend/tests/test_campaign_execution_safety.py
  backend/tests/test_beta_journey_offline.py
  backend/tests/test_supabase_test_safety.py
  backend/tests/test_strategic_actions.py
  backend/tests/test_saas27_multi_workspace.py::TestWorkspaceContextResolver
  backend/tests/test_beta_feature_policy.py -q
```

Result: **155 passed, 0 failed, 0 skipped**. Tests were inspected for fake/mocked
dependencies before execution, and the existing process guard/socket block stayed
enabled. The Starlette/httpx deprecation warning is pre-existing.

Frontend command, from `frontend`:

```text
node --test tests/discovery-routing.test.mts tests/campaign-creation-safety.test.mts tests/discovery-campaign-actions.test.mts tests/campaign-draft-workspace.test.mts tests/beta-journey-contracts.test.mts tests/discovery-context.test.mts
```

Result: **31 passed, 0 failed, 0 skipped**. API requests are mocked; no mounted
browser or database integration was run. Node's typeless-package warning remains.

`./node_modules/.bin/tsc --noEmit`, `NEXT_TELEMETRY_DISABLED=1 npm run build`,
`backend/.venv/bin/python -m compileall -q backend`, and `git diff --check` passed.
The build retained the existing multiple-lockfile/workspace-root warning.

Files changed in this batch (not the much larger pre-existing working tree):

- `backend/supabase/migrations/048_campaign_creation_idempotency.sql`
- `backend/services/campaigns/api.py`
- `backend/services/campaigns/service.py`
- `backend/services/strategic/actions.py`
- `backend/tests/test_campaign_creation_contract.py` (new)
- `backend/tests/test_campaign_creation_safety.py`
- `backend/tests/test_discovery_campaign_selection.py`
- `backend/tests/test_manual_campaign_creation.py`
- `backend/tests/test_strategic_actions.py`
- `backend/tests/test_lead_round_trip.py` (database-backed, not executed)
- `backend/tests/test_discovery_jobs.py` (database-backed, not executed)
- `frontend/lib/api.ts`
- `frontend/tests/campaign-creation-safety.test.mts`
- `frontend/tests/discovery-campaign-actions.test.mts`
- `docs/CAMPAIGN_CREATION_CONTRACT_HARDENING.md` (new)
