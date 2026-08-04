# Launch Database Foundation

**Status:** Implemented (uncommitted working tree)
**Base commit:** `570a343` ("feat: production sprint 1")
**Scope:** Canonical persistence layer, dual-write path, backfill, readiness fixes, tests.

---

## Executive Summary

Loqi's persistence layer previously depended on in-memory repositories (outside production),
a legacy `users` table with `google_*` columns for OAuth tokens, and an append-only
`workflow_events` log as the de facto state store. This work lays the database foundation for
launch:

1. **A canonical persistence module** (`services/persistence/launch/`) with 22 dataclass models
   and 22 Supabase-backed repositories covering identity, workspaces, leads/companies,
   campaigns/drafts, knowledge, and usage/billing.
2. **Globally canonical persons & companies** — `leads` are deduplicated once per normalized
   email and `companies` once per normalized domain; workspace affiliation and state live in
   `workspace_leads` / `workspace_companies`, so the same company is never duplicated across
   workspaces and enrichment performed once is reusable everywhere.
3. **Immutable provider payload archive** — `provider_payloads` stores raw Apollo / PDL /
   Hunter / Clay JSON once per `(provider, entity_type, entity_id)` and is never updated or
   deleted, so new fields (technologies_used, hiring signals, …) can be backfilled later from
   the archive without re-querying and re-paying the provider.
4. **Dual-write semantics** — every campaign/draft/lead mutation now writes both the event log
   and canonical tables; OAuth tokens are mirrored into `connected_accounts`; external identities
   are upserted into `external_identities`.
5. **Backfill** — an idempotent per-workspace replay of `workflow_events` into canonical rows,
   kicked off automatically at startup.
6. **Canonical-first reads with fallback** — `load_workspace_state()` reads canonical tables when
   seeded and falls back to event projection otherwise; `load_all_provider_credentials()` reads
   `connected_accounts` first, legacy columns second.
7. **Workspace auto-provisioning** — onboarding finalize creates a workspace + owner membership
   bound to the organization.
8. **Readiness fixes** — `/ready` no longer 503s in dev/CI when resend email secrets are absent,
   and its DB probe uses a migration-guaranteed table.
9. **Schema review pass (production hardening)** — migrations 004–011 reviewed for long-term
   correctness at 100k+ workspace scale: audit/soft-delete/versioning columns added where they
   make sense, partial unique constraints for soft-delete tables, CHECK-constrained status
   vocabularies, ON DELETE semantics fixed (owner deletion can no longer destroy a workspace;
   campaign lead references repointed from global `leads` to `workspace_leads`), and every
   addition rationalized (see Schema Review).

Full suite: **3707 passed, 7 failed** (all 7 pre-existing branch WIP, down from 8).

---

## Files Modified

| File | Change |
|---|---|
| `backend/main.py` | Lifespan: startup backfill task (`backfill_all` via `asyncio.to_thread`). Dual-write call sites for drafts/campaigns (`persist_draft`/`persist_draft_update` at lines ~995, 1650, 1693, 1761, 1908, 1943, 2397, 2443). `ensure_workspace` on web session creation (~1439). |
| `backend/services/persistence/config.py` | `REPOSITORY_PROVIDER` env override; defaults to `SUPABASE` when `APP_ENV=production`, else `IN_MEMORY`. Identity `users` aggregate always persisted via Supabase regardless. |
| `backend/services/supabase.py` | `sync_connected_account()` (line 266) — canonical `connected_accounts` dual-write of OAuth tokens. `save_google_tokens()` — canonical sync + legacy-column retry, `finally` cleanup. `load_all_provider_credentials()` (line 824) — canonical-first read, legacy `users` fallback, rows flagged `_canonical`. |
| `backend/services/identity/api.py` | OAuth callback: replay-detection cache keyed by `(state, code)`, session cleanup; auth dependency uses Supabase user repository. |
| `backend/services/identity/services/auth_service.py` | `_sync_external_identity()` (line 426) — best-effort canonical upsert into `external_identities` on `oauth_login`. |
| `backend/services/onboarding/services.py` | `create_workspace_and_finalize()` calls `ensure_workspace` (line 528) with org binding. |
| `backend/services/onboarding/api.py` | Wires finalize endpoint to durable completion path. |
| `backend/services/operations/diagnostics.py` | `get_required_vars()` — resend email vars (`EMAIL_API_KEY`, `EMAIL_FROM`, `EMAIL_REPLY_TO`) required only when `ENVIRONMENT=production` **and** `EMAIL_PROVIDER=resend`. |
| `backend/services/operations/router.py` | `GET /ready` probe now targets `workflow_sessions` (migration-guaranteed) instead of `_dummy` (which tripped PGRST205 schema cache). |
| `backend/services/conversation_engine.py`, `conversation_store.py` | Working-tree integration for canonical session/workspace routing. |
| `backend/services/mission_control/briefing.py`, `reasoning/coordinator.py`, `reasoning/recommendation_reasoner.py`, `narrative_engine.py`, `workspace_memory.py`, `workspace_snapshot.py`, `world_model/snapshot_adapter.py`, `world_model/store.py`, `job_engine/manager.py`, `job_engine/storage.py`, `persistence/repositories/user_repository.py`, `services/migration.py` | Same working tree as above — canonical-state awareness in reads/reporting (event-log + canonical). |
| `backend/tests/test_operations.py` | `test_ready_with_no_db` rewritten to simulate no-DB via `SupabaseConnectionManager(url="", key="")` (a lazy real client from env would make `reset_connection_manager()` probes succeed). `test_ready_with_mock_db` covered by the router probe fix. |
| `backend/tests/test_onboarding.py` | New `test_finalize_creates_personal_workspace_in_org` — asserts `ensure_workspace` fires with org id/name/slug. |

---

## New Files Created

| File | Purpose |
|---|---|
| `backend/services/persistence/launch/__init__.py` | Module exports (models + repositories + backfill). |
| `backend/services/persistence/launch/models.py` | 22 dataclasses — global `Lead`/`Company`, `WorkspaceLead`/`WorkspaceCompany` associations, `ProviderPayload` archive. |
| `backend/services/persistence/launch/repositories.py` | Generic `LaunchRepository` base + 22 repositories. |
| `backend/services/persistence/launch/backfill.py` | `backfill_workspace(user_id)`, `backfill_all()`, `_run_to_completion()` (loop-safe sync↔async bridge). |
| `backend/services/workspace_state.py` | `ensure_workspace`, dual-write `persist_*` functions (global aka-upsert in `_normalize_lead`), `load_workspace_state` (canonical-first + projection fallback), `_lead_as_dict`/`_strategy_as_dict` shape contracts. |
| `backend/supabase/migrations/004_identity_platform.sql`, `005_external_identity.sql`, `006_workspaces.sql`, `008_campaigns.sql`, `009_knowledge.sql`, `010_usage_billing.sql` | Canonical schema (see Database Migrations). |
| `backend/supabase/migrations/007_domain.sql` | **Restructured** (unapplied): global companies/leads + workspace association tables. |
| `backend/supabase/migrations/011_provider_payloads.sql` | **New**: immutable provider payload archive. |
| `backend/tests/test_launch_persistence.py` | 14 tests: repo round-trips (datetime/JSONB), identity upserts, projection fallback, canonical flip, lead-shape contract, backfill idempotency. |
| `backend/tests/test_web_session_identity.py`, `backend/tests/test_draft_generation_recovery.py` | Working-tree coverage for web identity and draft recovery. |

---

## Database Migrations

| Migration | Tables | Notes |
|---|---|---|
| `003_job_engine.sql` | `jobs`, `search_results` | Pre-existing (also embedded in `services/migration.py`). |
| `004_identity_platform.sql` | `identity_users` | User aggregate of record; always written through Supabase. Review: `email` (partial unique `lower(email)` where `deleted_at is null`), `metadata`, `last_login_at`, `version`, deleted_at index (idempotent alters). |
| `005_external_identity.sql` | `external_identities`, `connected_accounts` | Unique `(provider, provider_subject)` where `deleted_at is null`; canonical OAuth token store. Review: `last_verified_at`, `deleted_at`, `connected_accounts.last_synced_at`/`version`, status CHECK (active/pending/expired/revoked/error), sync index. |
| `006_workspaces.sql` | `organizations`, `workspaces`, `workspace_members` | Unique org slug/name (partial), workspace org-slug, member `(workspace_id, user_id)`. Review: `updated_by`, `metadata`, `version`, status CHECK; `workspaces.owner_user_id` now `on delete set null` (owner leaving no longer destroys the workspace); member role/status CHECKs. |
| `007_domain.sql` | **Global** `companies` (uniq normalized `domain`, `canonical_id`), **global** `leads` (uniq normalized `email`, `canonical_id`), `workspace_companies`, `workspace_leads`, `lead_sources`, `lead_signals` | Review: `source_provider`, `created_by`/`updated_by`, `metadata`, `last_synced_at`, `version`, `deleted_at` + partial uniques where `deleted_at is null` on global tables; sync indexes `(source_provider, last_synced_at)`; `workspace_leads` status/research/verification CHECKs. |
| `008_campaigns.sql` | `campaigns`, `campaign_leads`, `strategies`, `drafts` | **Review fix:** `campaign_leads.lead_id` and `drafts.lead_id` repointed from global `leads` → `workspace_leads` (code wrote workspace-lead ids; FK now matches). Review: `campaigns.updated_by`/`metadata`/`version`/`deleted_at` + status CHECK; draft `metadata`/audit columns + status CHECK; `drafts.lead_id` `on delete set null` (removing a lead keeps its drafts). |
| `009_knowledge.sql` | `knowledge`, `notifications`, `audit_log` | Unique `(owner_type, owner_id, summary_type)` where `deleted_at is null`. Review: `knowledge.created_by`/`version`/`deleted_at`; `notifications.read_at`/`deleted_at` + unread index; `audit_log` confirmed append-only (no update/delete/soft-delete). |
| `010_usage_billing.sql` | `plans`, `plan_features`, `subscriptions`, `usage_records` | Review: `plans.sort_order`/`deleted_at`; subscription `version`/`last_synced_at`, partial unique active-subscription-per-org, status CHECK (Stripe lifecycle); financial tables intentionally **no** `deleted_at`; `usage_records.external_id` for provider reconciliation. |
| `011_provider_payloads.sql` | `provider_payloads` | **Immutable archive**: unique `(provider, entity_type, entity_id)`, `payload jsonb`, append-only — confirmed no `deleted_at`/`updated_at` by design. |

All new migrations use `create table if not exists` — additive and re-runnable.

**Important:** `apply_migrations()` in `services/migration.py` only auto-applies `jobs`/
`search_results`/onboarding columns. **Migrations 004–010 are NOT auto-applied** — see
Manual SQL.

---

## Schema Review

A full hardening pass over the canonical schema, targeting 100k+ workspaces / millions of
leads. Priority was long-term correctness over minimizing migrations. **Deployment note: none
of the review changes below are backward-breaking for the code in this tree** — every new
column is an idempotent `add column if not exists` with a default, so readers that don't set
the field get a sensible value and writers that do are transparently accepted. Columns were
added only where the table will actually accumulate them; join/audit/history tables were left
alone.

### 004 Identity — `identity_users`
- `email` (text, partial unique `lower(email)` where `deleted_at is null`) — logins and dedup
  need a canonical, case-insensitive, soft-delete-aware email key held at the platform level.
- `last_login_at` — cheap security signal (staleness, abuse), avoids joining event logs.
- `metadata`, `version` — avatar/locale/tenant tags + optimistic concurrency for profile edits
  in a multi-admin enterprise.

### 005 External identity
- `external_identities.last_verified_at`, `deleted_at` — OAuth links are verified only at
  sign-in; verify-stamp keeps the record honest. Partial unique `(provider, provider_subject)`
  where `deleted_at is null` lets a user drop then re-link without a hard delete.
- `connected_accounts.status` CHECK (active/pending/expired/revoked/error) — token state is a
  first-class row (used by gmail sync), not ambient. `last_synced_at`, `version`, partial
  unique `(user_id, provider, account_id)` where `deleted_at is null`, and the
  `(provider, last_synced_at)` sync index — provider-reconciliation queries need them.

### 006 Workspaces
- `workspaces.owner_user_id` repointed to `on delete set null` — the original cascade destroyed
  the workspace when the owner account was deleted; a billing + content container should never
  vanish with its owner. (`006` drops the old constraint if present so it upgrades cleanly on
  DBs where 002/legacy already ran.)
- `created_by`/`updated_by` everywhere — multi-user workspaces need accountability; the IDs are
  `text` (works OAuth subject IDs and provider user IDs alike, no FK ceremony).
- `metadata`, `version`, `status` CHECK (active/suspended/archived) — enterprise lifecycle
  (suspended = billing/pause, archived = inactive, distinct from `deleted_at`).
- `workspace_members`: `role` CHECK (owner/admin/member/viewer) + `status` CHECK
  (active/invited/suspended) with partial unique `(workspace_id, user_id)` where
  `deleted_at is null` — RBAC and invitation lifecycle are schema-level, and revocation uses
  soft-delete so history/audit survives.

### 007 Domain — global `companies` / `leads`, `workspace_leads`
- Global rows gain `source_provider`, `created_by`/`updated_by`, `metadata`, `last_synced_at`,
  `version`, `deleted_at`. Rationale: global rows are shared across workspaces and updated by
  providers — provenance (`source_provider`) and sync state (`last_synced_at`) are what make
  "enrich once, reuse everywhere" trustworthy. Partial uniques on `canonical_id` /
  `lower(domain)` / `lower(email)` where `deleted_at is null` mean a dead (deleted) canonical
  row can be recreated by a later sync without a unique violation — no hard deletes needed.
- `workspace_leads` carries the same audit columns plus CHECKs on `lead_status`
  (new/added/approved/rejected), `research_status` (not_researched/researching/researched/
  failed), `verification_status` (unverified/verified/invalid/bounced) — the decision pipeline
  vocabulary is now canonical SQL, not stringly-typed.
- `lead_sources` / `lead_signals` deliberately unchanged: they are immutable provenance/fact
  logs (append-only) — soft-delete and `updated_at` would be noise against the audit path.

### 008 Campaigns — **FK correction**
- **Bug fixed:** `campaign_leads.lead_id` and `drafts.lead_id` previously FK'd the **global**
  `leads(id)`, but `workspace_state.py` writes **workspace-lead ids** there. Both are repointed
  to `workspace_leads(id)`. This is the schema matching reality: campaigns live in a workspace
  and reference that workspace's lead context, not the global person.
- `campaign_leads.lead_id on delete cascade` — a workspace lead removed with its workspace is
  gone; a global lead soft-delete never touches it.
- `drafts.lead_id on delete set null` — removing a lead from a workspace must never destroy its
  generated drafts (they remain as artifacts).
- `campaigns.updated_by`/`metadata`/`version`/`deleted_at` + status CHECK
  (planning/draft/running/paused/completed/archived/cancelled/failed) — campaign status is used
  by the engine and dashboards; `deleted_at` (removal) is distinct from `archived_at`
  (business state). Partial unique campaign-lead pair where `deleted_at is null`.
- `drafts.metadata`/`created_by`/`updated_by`/`version`/`deleted_at` + status CHECK
  (draft/pending/generating/approved/rejected/sent/delivered/failed) — who generated/edited a
  draft matters for review workflows and audit.

### 009 Knowledge / Notifications / Audit
- `knowledge.created_by`/`version`/`deleted_at` + partial unique `(owner_type, owner_id,
  summary_type)` where `deleted_at is null` — memory is revocable (GDPR) but reversible;
  regeneration after revocation is legal because of the partial unique.
- `notifications.read_at`/`deleted_at` + unread index where `read_at is null and
  deleted_at is null` — read state co-located, and the hot "unread count" query is a straight
  partial-index scan.
- `audit_log` **kept append-only** — no `updated_at`, no `deleted_at`, no soft delete; FKs to
  workspaces/users are `on delete set null` so the log survives entity deletion. It's a pure
  event record and mutability would corrupt it.

### 010 Billing
- `plans.sort_order` (deterministic catalog ordering) + `deleted_at` (retire plans without
  touching subscription history); partial unique `code` where `deleted_at is null`.
- `subscriptions.version`/`last_synced_at` (webhook race safety + sync cadence) and a partial
  unique enforcing **one active subscription per organization** (`status in (active, trialing)`
  and `organization_id <> ''`) — the core billing invariant as a constraint.
- Subscriptions are financial records: **no `deleted_at`** anywhere on them or `usage_records`.
- `usage_records.external_id` + `(provider, external_id)` index — provider-side usage reference
  for reconciliation without payload digging. Append-only (no `updated_at`).
- Status CHECKs use Stripe's lifecycle (incomplete/incomplete_expired/trialing/active/past_due/
  canceled/unpaid/paused).

### 011 Provider payloads
- Confirmed already correct for production: immutable (no update/delete/soft-delete columns),
  partial-unique-free full unique on `(provider, entity_type, entity_id)` (append-only archive
  never re-creates rows), `payload jsonb` variant-free.

### Cross-cutting rules applied
1. **Enums = `text` + CHECK**, never native enums — adding a state is a one-statement migration,
   no `ALTER TYPE` table lock at scale.
2. **`text` FK targets for creators** (`created_by`/`updated_by`/`added_by`) — accepts OAuth
   subject IDs and composite actor IDs without a users FK dependency.
3. **Partial uniques wherever soft-delete lives** — deleted rows must never block re-creating a
   business key.
4. **`on delete set null` for owner/provider FKs, `cascade` for child-of-content FKs** —
   content dies with its container; an actor/owner never does.
5. **`deleted_at` only on business entities** (users, workspaces, leads, campaigns, drafts,
   knowledge, notifications, plans); **append-only on event/financial/provenance tables**
   (audit_log, usage_records, plan_features, lead_sources, lead_signals, provider_payloads,
   strategies, external_identities).
6. **Legacy overlap documented, not removed** — `services/persistence/migrations/` (e.g.
   `002_organizations.sql`) is an earlier overlapping set (its `organizations` table is defined
   with `created_by`, `metadata`, `settings`); 004–011 remain the canonical launch set and use
   `create table if not exists` + `add column if not exists` so either path deploys safely.

---

## New Tables (25)

`identity_users`, `external_identities`, `connected_accounts`, `organizations`, `workspaces`,
`workspace_members`, `companies` (global), `workspace_companies`, `leads` (global),
`workspace_leads`, `lead_sources`, `lead_signals`, `provider_payloads`, `campaigns`,
`campaign_leads`, `strategies`, `drafts`, `knowledge`, `notifications`, `audit_log`, `plans`,
`plan_features`, `subscriptions`, `usage_records`.

## Existing Tables Modified

- **None structurally** — all new migrations are `create table if not exists`.
- `007_domain.sql` was **rewritten before being applied**: `companies`/`leads` changed from
  workspace-owned (uniq `(workspace_id, …)`) to **global** (uniq normalized domain/email) with
  new `workspace_companies` / `workspace_leads` association tables; `lead_sources` /
  `lead_signals` now reference `workspace_leads`.
- The legacy `users` table (with `google_*` token columns, `onboarding_data`,
  `onboarding_completed_at`) remains as the **compatibility bridge**; canonical tables are
  dual-written, not replacing it in this phase.
- `workflow_sessions` / `workflow_events` (pre-existing) become the backfill source; they
  remain the write log.

---

## API Endpoints Changed

| Endpoint | Change |
|---|---|
| `GET /ready` | Probe switched from `_dummy` → `workflow_sessions` (no PGRST205). No longer 503 in dev/CI when resend email secrets missing (`ENVIRONMENT`-gated required vars). |
| `POST /api/onboarding/finalize` | Now provisions a personal workspace + owner `workspace_members` row bound to the org (`ensure_workspace`). |
| OAuth callback (Google) | Replay-detection cache `(state, code)`; canonical `external_identities` upsert on login; user aggregate via `SupabaseUserRepository`. |

---

## Repository Layer Changes

- `LaunchRepository` (generic, `services/persistence/launch/repositories.py:34`) — shared
  serialization: datetimes → ISO strings, JSONB columns → `json.dumps` (fixes prior
  double-encoding where stored values were JSON-stringified twice).
- **Global identity repos**: `LeadRepository.find_by_email(email)` and
  `CompanyRepository.find_by_domain(domain)` — no workspace filter; workspace-scoped lookups
  moved to the association repos.
- **New**: `WorkspaceLeadRepository` (`find_in_workspace`, `list_for_workspace`,
  `list_by_email`), `WorkspaceCompanyRepository` (`find`, `list_for_workspace`),
  `ProviderPayloadRepository` (`find(provider, entity_type, entity_id)`,
  `list_for_entity`; JSONB `payload` column).
- 22 repositories total: `ExternalIdentity`, `ConnectedAccount`, `Workspace`,
  `WorkspaceMember`, `Company`, `WorkspaceCompany`, `Lead`, `WorkspaceLead`, `LeadSource`,
  `ProviderPayload`, `LeadSignal`, `Campaign`, `CampaignLead`, `Strategy`, `Draft`,
  `Knowledge`, `Notification`, `AuditLog`, `Plan`, `PlanFeature`, `Subscription`,
  `UsageRecord`.
- `services/persistence/config.py` — `REPOSITORY_PROVIDER` env override
  (`in_memory`/`supabase`); production default is `supabase` (via `APP_ENV`).
- The identity **User aggregate** (`identity_users`) always persists via Supabase, independent
  of provider selection.

---

## Identity Changes

- OAuth login (`auth_service.py::oauth_login`) upserts the canonical `external_identities` row
  (`_sync_external_identity`), keyed by `(provider, provider_user_id or email)`, with
  avatar/name metadata.
- `sync_connected_account()` mirrors tokens into `connected_accounts` (upsert by
  `(user_id, provider)`); `save_google_tokens()` writes canonical first, retries legacy
  `users.google_*` for compat, and cleans up in `finally`.
- `load_all_provider_credentials()` reads `connected_accounts` first (non-empty refresh
  tokens), returns legacy-shaped rows flagged `_canonical`, falls back to `users` columns.
- Legacy login-path bridge remains best-effort; identity platform is source of truth once
  migration 004–005 are applied.

---

## Workspace Changes

- **`ensure_workspace`** (`workspace_state.py:98`) — idempotent workspace creation per user:
  workflow session lookup, workspace row (owner-bound, optional organization/slug), owner
  membership row.
- **`load_workspace_state`** (`workspace_state.py`) — canonical-first: reads
  campaigns → `campaign_leads` → `workspace_leads` (state) + global `leads` (profile) +
  global `companies`; falls back to `_project_from_events` when tables are empty/unavailable
  (until backfill completes).
- **Global aka-upsert** (`_normalize_lead`) — a lead is persisted once globally by normalized
  email (`canonical_id = email:<email>`), its company once globally by domain
  (`canonical_id = domain:<domain>`), then linked into the workspace via `workspace_leads` /
  `workspace_companies`. The same person/company across workspaces shares global rows.
- `_run_sync`/`_run_to_completion` — loop-safe sync↔async bridges (needed because the
  workflow dispatch chain is still synchronous; see TODOs).

---

## Campaign/Draft Persistence Changes

All of the following dual-write (canonical row **and** `workflow_events`):

- `persist_campaign` / `_write_campaign_row` (upsert, skip-if-exists)
- `persist_campaign_update` / `_update_campaign_row`
- `persist_campaign_lead` / `_persist_campaign_lead_row` / `_normalize_lead` (global aka-upsert
  by email/domain; links lead + company into the workspace; campaign links reference the
  `workspace_leads` row)
- `persist_lead_decision` / `_update_lead_decision` (approved/rejected status + timestamps)
- `persist_draft` / `_write_draft_row` (idempotent; `generation_metadata`/`lead_snapshot`
  JSONB, preview fallback)
- `persist_draft_update` / `_update_draft_row` (status transitions set
  `approved_at`/`sent_at`/`reply_state`)
- Wired into `main.py` draft generation/regeneration/approval/send paths.

---

## Any Manual SQL I Need to Run

**Yes — one-time, required before production use of canonical features.**

`apply_migrations()` does **not** run migrations 004–011. Apply them in the Supabase SQL
Editor (or `psql` with `DATABASE_URL`):

```
Open https://supabase.com/dashboard/project/<ref>/sql/new
Run, in order:
  backend/supabase/migrations/004_identity_platform.sql
  backend/supabase/migrations/005_external_identity.sql
  backend/supabase/migrations/006_workspaces.sql
  backend/supabase/migrations/007_domain.sql
  backend/supabase/migrations/008_campaigns.sql
  backend/supabase/migrations/009_knowledge.sql
  backend/supabase/migrations/010_usage_billing.sql
  backend/supabase/migrations/011_provider_payloads.sql
```

All are `create table if not exists` — safe to re-run. Migrations 004–011 must be applied in
order (FK references).

---

## Environment Variables Required

| Variable | Required | Notes |
|---|---|---|
| `SUPABASE_URL` | Yes | PostgREST base URL. |
| `SUPABASE_KEY` | Yes | Service-role key (server-side). |
| `APP_ENV` | Prod default | `production` → repository provider defaults to `supabase`; else `in_memory` (identity user aggregate still Supabase). |
| `REPOSITORY_PROVIDER` | Optional | Explicit override: `in_memory` or `supabase`. |
| `ENVIRONMENT` | Optional | Used by readiness gate; `production` + `EMAIL_PROVIDER=resend` requires email secrets. |
| `EMAIL_PROVIDER` | Prod | `resend`/`console`; affects required-vars check. |
| `EMAIL_API_KEY`, `EMAIL_FROM`, `EMAIL_REPLY_TO` | Prod only | Required only when `ENVIRONMENT=production` and `EMAIL_PROVIDER=resend`. |
| `DATABASE_URL` | Optional | Legacy auto-migration path only; not needed for 004–010. |
| `OPENAI_API_KEY` | Existing | Pre-existing requirement. |

---

## TODOs Left

1. **Fix 7 pre-existing failing tests** (all confirmed unrelated to this work):
   - `test_copilot_api.py::TestHealth::test_health_contains_expected_keys`
   - `test_email_infrastructure.py::TestConsoleEmailProvider::test_send_subscription_renewed`
   - `test_google_oauth.py` ×3 (`test_replay_detection`, `test_existing_user_by_email_links_and_logs_in`, `test_existing_external_identity_logs_in`)
   - `test_reasoner_integration.py` ×2 (`test_mc_endpoint_returns_campaigns`, `test_mc_recommendations_reference_campaign`)
2. **Async-native workflow path** (AGENTS.md backlog): make `handle_message()`/`run_workflow()`/
   `send_outreach()` async so `_run_async`/`_run_sync`/`ThreadPoolExecutor` bridges in
   `workflows.py`/`workspace_state.py`/`backfill.py` can be removed.
3. **Flip remaining legacy reads** to canonical: `users.google_*` → `connected_accounts`
   (dual-write exists; reads fall back today), mission-control/reasoning reads → canonical
   tables.
4. **Write provider payloads at ingestion**: `provider_payloads` archive + repo exist, but the
   Apollo/SerpAPI/PDL acquisition pipeline doesn't write raw JSON into it yet — wire it once
   sourcing is the priority so the archive is populated from day one (and point
   `lead_sources.payload_id` at it; `lead_sources.raw_payload` is deprecated).
5. **Align env gates**: readiness uses `ENVIRONMENT`; repository provider uses `APP_ENV` —
   consolidate on one.
6. **Web UI consumption** of the canonical lead/draft shapes (frontend `lib/domain.ts`,
   `lib/repositories.ts` are WIP in the same working tree).

---

## Known Issues

- **7 failing tests** (listed above) are pre-existing branch WIP failures at HEAD/working
  tree — none introduced by this work (baseline was 8 failing before the `/ready` fix).
- **PGRST205 on unmigrated DBs**: canonical queries against tables that haven't been applied
  (004–010) will error; callers catch and fall back to legacy/projection paths.
- **Thread-bridge latency**: `asyncio.run` in a worker thread per sync call (backfill,
  `ensure_workspace` from sync context) — acceptable for startup/onboarding frequency, not a
  hot path.
- **`_ScriptedClient`-style test seams**: the test mock honors `eq` filters but ignores
  `neq`/`in` operators; tests script exactly one row per (table, filter) combination.
- **Backfill skips** a workspace if it already has campaign rows (by design, idempotent); if
  canonical rows were partially written by an interrupted run, re-running won't repair gaps —
  `_write_*` functions are individually idempotent, but partial-campaign workspaces will not
  re-replay.

---

## Breaking Changes

1. **`REPOSITORY_PROVIDER` default flips to `supabase` in production** (`APP_ENV=production`).
   Identity repositories (except the User aggregate) will read/write Supabase tables —
   migrations 004–011 **must** be applied first, or those services degrade to fallback paths.
2. **`load_all_provider_credentials()` returns canonical rows first** — same legacy shape, but
   rows carry `_canonical: true` and `google_provider_id` is synthesized as
   `provider-email` when canonical. Code keying on exact `users` row IDs may need adjustment.
3. **`GET /ready` semantics**: dev/CI no longer 503s for missing resend email secrets;
   `ENVIRONMENT=production` + `EMAIL_PROVIDER=resend` still enforces them.
4. **Onboarding finalize now writes `workspaces`/`workspace_members`** — the workspace is the
   canonical container for campaigns/leads/drafts; anything reading only the event log must
   read through `load_workspace_state()` or the projection fallback.
5. **Leads and companies are now globally canonical**: `leads`/`companies` rows are shared
   across workspaces (identity by normalized email/domain); per-workspace state (status,
   source, company link) moved to `workspace_leads`/`workspace_companies`. Any consumer that
   assumed lead/company rows were workspace-owned must read through the association tables or
   `_lead_as_dict`-shaped output. `campaign_leads.lead_id` and draft `lead_id` now reference
   `workspace_leads(id)` (schema review corrected these FKs to match what the code already
   wrote).
6. **Duplicate-draft suppression**: `persist_draft` is now idempotent per draft id — re-sends
   of the same payload no longer create duplicate canonical rows (event log still records
   every append).
7. **Schema review column additions** (004–010): `email`/`metadata`/`last_login_at`/`version`
   on `identity_users`; `last_verified_at`/`deleted_at` on `external_identities`;
   `status`/`last_synced_at`/`version`/`deleted_at` on `connected_accounts`;
   `updated_by`/`metadata`/`version`/status CHECKs on `organizations`/`workspaces`/
   `workspace_members`; `source_provider`/`created_by`/`updated_by`/`metadata`/
   `last_synced_at`/`version`/`deleted_at` on global `leads`/`companies` + `workspace_leads`
   status/research/verification CHECKs; `updated_by`/`metadata`/`version`/`deleted_at` +
   status CHECKs on `campaigns`/`drafts`; `created_by`/`version`/`deleted_at` on `knowledge`;
   `read_at`/`deleted_at` on `notifications`; `sort_order`/`deleted_at` on `plans`;
   `version`/`last_synced_at` on `subscriptions`; `external_id` on `usage_records`. **Not
   breaking**: all additions are idempotent `add column if not exists` with defaults; the
   dataclass models now carry them. `audit_log`, `usage_records`, `plan_features`,
   `lead_sources`, `lead_signals`, `provider_payloads` remain append-only by design.

---

## Test Results

| Suite | Result |
|---|---|
| `tests/test_launch_persistence.py` (new) | **18 passed** (repo round-trips, global dedup, cross-workspace sharing, provider archive, canonical flip, lead-shape contract, backfill) |
| `tests/test_operations.py` | **23 passed** (readiness fix verified) |
| `tests/test_onboarding.py` | **53 passed** |
| `tests/test_persistence.py` + `test_web_session_identity.py` + `test_mission_control.py` + `test_draft_generation_recovery.py` | **203 passed** (combined run) |
| `tests/test_copilot_api.py` | 20 passed, **1 pre-existing failure** (health keys) |
| **Full suite (with schema review)** | **3707 passed, 7 failed** (all pre-existing — same 7 failures; schema review added no regressions) |

Baseline before this work: 3698 passed, 8 failed → readiness fix + new tests net +4 passed,
−1 failed (then +6 for the global-entity/archive tests). Schema review: same 7 pre-existing
failures, no regressions.

---

## Step-by-Step Deployment Order

1. **Apply migrations 004–011** in Supabase SQL Editor (order matters; see Manual SQL).
2. **Set env vars** on the server: `SUPABASE_URL`, `SUPABASE_KEY`, `APP_ENV=production`,
   `ENVIRONMENT=production`, `EMAIL_PROVIDER`, `EMAIL_API_KEY`, `EMAIL_FROM`,
   `EMAIL_REPLY_TO` (email secrets only if using resend in prod).
3. **Deploy backend code** (this working tree). Startup logs will show
   `[backfill] backfill complete: N/M workspaces` — the startup task replays
   `workflow_events` into canonical tables idempotently.
4. **Verify `/health`, `/ready`, `/version`** — `/ready` should be 200 with no PGRST205
   errors; confirm `workflow_sessions` probe is used.
5. **Spot-check dual-write**: run a draft-generation or campaign action; confirm rows appear
   in `drafts`/`campaigns`/`campaign_leads`, plus global `leads`/`companies` with
   `workspace_leads`/`workspace_companies` links, and OAuth tokens in `connected_accounts`.
6. **Verify global dedup**: add the same lead (same email/domain) to two different workspaces
   and confirm a single `leads` row and single `companies` row with two workspace links.
7. **Verify onboarding**: complete onboarding for a new user → `workspaces` +
   `workspace_members` (owner) rows appear; workspace loads via canonical path.
8. **Run the backend test suite** (`./venv/bin/python -m pytest tests/ -q`) — expect the 7
   known pre-existing failures only.
9. **Monitor**: watch logs for `canonical read failed, falling back` (indicates a missing
   table or RLS issue) and `[backfill]` lines.
