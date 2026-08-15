# ADR-002: Discoveries as First-Class Entities

**Status:** Accepted
**Date:** 2026-08-05
**Driver:** Discovery was a singleton "latest search" — refresh/back-forward
lost the run, "Found 25 companies" opened a stale page, and campaigns had no
traceable research source.

## Context

Discovery previously rendered the most recent search job: the frontend polled
`listActiveJobs`, preferred any queued/running job ("Research in progress"),
then fell back to a sessionStorage job id. Consequences:

- A new query effectively overwrote the previous one ("latest search" state).
- Refresh, back/forward, or notification clicks could not reopen a specific
  run — there was no durable identity.
- Completed runs were tied to the transient `jobs`/`search_results` staging,
  so provenance and re-review were lost when jobs were purged.
- Campaigns were created from a page state, not from a research record.

## Decision

Introduce **Discovery** as a durable, per-run entity (schema 014). A discovery
owns: the query, lifecycle status, its jobs, surfaced companies/leads (as
links — never copies), provider provenance, a narrative summary, and filters.
Campaigns may reference a discovery as their source (`campaigns.discovery_id`
FK). One query → one new discovery; existing discoveries are never
overwritten.

The relationship to jobs is persisted on the **job side**: a discovery may be
refreshed, rerun, or scheduled many times over its lifetime, so it is
Discovery → many Jobs, Job → one Discovery (`jobs.discovery_id` FK). A
discovery never owns a single source job.

### Data model (ERD)

```
workspaces
  1 ──< discoveries                      (014: workspace_id FK, cascade)
         │  discovery_companies ──> workspace_companies / companies  (007 links)
         │  discovery_leads ────> workspace_leads / leads            (007 links)
         │  <── discovery_id ── jobs     (003: transient, ON DELETE SET NULL)
  1 ──< campaigns ── discovery_id ──> discoveries  (014: ON DELETE SET NULL)
```

- `discoveries` — ownership root: `query`, `status` (queued|searching|
  completed|failed|cancelled), `summary jsonb`, `filters jsonb`,
  `provider_provenance jsonb`, audit columns, soft delete. No job column:
  ownership flows the other way.
- `discoveries` future-proofing columns (schema 015, additive migration on
  top of immutable 014): `title` (user-editable display name, defaults to
  `query` at creation), `description`, `favorite bool`, `archived_at` (soft
  archive), `last_viewed_at` / `last_refreshed_at` (recently viewed / refresh
  & scheduled rediscovery), `metadata jsonb` (reserved for future
  UI/experimental attributes). No tags/folders/sharing/permissions yet —
  those belong to future migrations.
- `jobs.discovery_id` — nullable FK to `discoveries`, set when the job is
  enqueued; one job belongs to at most one discovery, a discovery may have
  many jobs (refresh/rerun/schedule). `ON DELETE SET NULL` so purging a
  discovery never breaks job history.
- `discovery_companies` — per-run link to `workspace_companies` +
  `companies`: `rank`, `match_score`, `source_provider`. Unique
  `(discovery_id, company_id)` where not deleted.
- `discovery_leads` — per-run link to `workspace_leads`: `rank`,
  `match_score`, per-workspace review `status`. Unique `(discovery_id,
  lead_id)` where not deleted.
- `campaigns.discovery_id` — the source discovery of a campaign.

Canonical identity stays in 007 (companies deduped by domain, leads by
email, workspace links for per-workspace state). Link tables only add the
per-run rank/score/provenance — the same pattern as `campaign_leads`.

### API changes

| Endpoint | Change |
|---|---|
| `POST /api/jobs/search` | **Extended** (backward compatible): now also creates the discovery row; response gains `discovery_id`. Job engine, polling, results contract unchanged. |
| `POST /api/discoveries` | **New**: `{query}` → `{ok, job_id, discovery_id, status}`. Always creates a NEW discovery; never overwrites. |
| `GET /api/discoveries` | **New**: recent discoveries for the workspace, newest first, with `company_count`/`lead_count` (list page). |
| `GET /api/discoveries/{id}` | **New**: full detail with joined `discovery_companies` + `discovery_leads` (detail page). Scoped to the workspace (404 otherwise). |
| `POST .../campaigns` | **Extended**: optional `discovery_id` persisted as the campaign source. |

### Backend changes

- `services/discovery.py` — sync row CRUD (`create_discovery`,
  `list_discoveries`, `get_discovery`, `get_discovery_by_job_id`,
  `mark_discovery_status`) plus the async finalizer `finalize_discovery(job)`.
- `runner.py` — new `on_complete` hook awaited after a job is marked
  COMPLETED (generic; job-engine stays discovery-agnostic).
- `manager.py` — `create_search_job` passes `on_complete` through.
- `main.py` — `_create_search_run` shared by both create endpoints: create
  job (with hooks) → resolve workspace → create discovery → close the
  create-vs-complete race by finalizing immediately if the job already
  completed. `on_update` moves the discovery to failed/cancelled when the
  job fails.
- `finalize_discovery` — reads `search_results`, normalizes every lead
  through the canonical `workspace_state._normalize_lead` (global dedupe),
  links `discovery_leads`, dedupes companies into `discovery_companies`,
  records `provider_provenance`, writes a deterministic summary, marks
  completed. Idempotent.
- `workspace_state.py` / launch models — `Campaign.discovery_id` field and
  the campaigns table write path; canonical campaign dicts carry
  `discovery_id`.

### Frontend changes (routing)

```
/discovery            DiscoveryHistory (list: Today / Yesterday / Earlier)
/discovery/[id]       DiscoveryDetailWorkspace (that run's companies/leads)
/campaigns/new        accepts ?discovery=<id> and saves campaigns with it
```

- `repositories.ts` — `fetchDiscoveryList()`, `fetchDiscovery(id)`,
  `prefetchDiscovery(id)`, `startDiscoverySearch` → `{jobId, discoveryId}`.
  The sessionStorage "last job id" singleton is removed.
- `CopilotContext.runResearch` — navigates to `/discovery/{discoveryId}` and
  passes the deep link to `completionActions`, so the "View Discovery"
  notification opens the exact run ("Found 25 companies" → that discovery).
- `useData` polling on the detail page while status is queued/searching
  (5s interval) keeps an in-flight run live after refresh.
- The detail page preserves back/forward, refresh, and deep links via the
  URL param — no state-management workaround.

### Migration strategy

- `supabase/migrations/014_discoveries.sql` is the canonical, resumable,
  idempotent migration (CREATE IF NOT EXISTS + guarded ALTER/INDEX blocks,
  mirroring 007). Requires 003 + 006 + 007 first; the `campaigns`
  `discovery_id` link is self-guarding via `to_regclass`.
- `services/migration.py` embeds the identical additive SQL as
  `DISCOVERIES_SQL`, executed in **both** `DATABASE_URL` branches
  (existing-jobs and fresh) of `apply_migrations()`. No follow-up SQL is
  required; existing completed search jobs are left as-is (they predate
  discovery entities — optional backfill can wrap them later).
- Manual application: paste `014_discoveries.sql` into the Supabase SQL
  editor (project `llckvmpwmovhchfpjnsa`).

## Consequences

### Positive

- Refresh, back/forward, and notification clicks always reopen the exact run.
- One query → one discovery; nothing is ever overwritten.
- No duplicated data: discovery links reference the canonical 007 entities.
- Backward compatible: `/api/jobs/search` contract and the job engine are
  unchanged for existing clients.
- Campaigns now have a traceable research source (`discovery_id`).

### Negative

- New schema + new endpoints to maintain; detail joins are deep (nested
  postgrest embeds) and cost a few hundred ms on large runs.
- Discovery creation adds one workspace resolution + insert to the create
  path (~1s; absorbed by the existing 20s job-creation budget).
- Campaign `discovery_id` writes fail on databases that have not applied 014.

## Extension Points

- **AI narrative brief** — `summary jsonb` is shaped for a real AI-generated
  brief; today it holds a deterministic count summary. Swap
  `finalize_discovery`'s summary builder for an LLM call.
- **Pinning / favorites** — add `pinned_at` (or a `discovery_pins` table);
  list ordering already keys off `created_at desc`.
- **Re-runs / series** — add `parent_discovery_id` or `series_id` to
  `discoveries`; serialized re-runs of the same query become one series.
- **Comparisons** — per-run `summary`/`filters`/`provider_provenance` make
  diffing two discoveries a pure read.
- **Per-provider billing** — `provider_provenance` records per-run counts;
  cost attribution is a read away.
- **Queue-ready finalization** — the `on_complete` hook is the single seam
  where Celery/RQ would call `finalize_discovery` instead of the runner.

## Verification queries (after applying 014)

```sql
-- 1. Tables exist
select table_name from information_schema.tables
where table_name in ('discoveries','discovery_companies','discovery_leads');

-- 2. Campaigns column added
select column_name from information_schema.columns
where table_name = 'campaigns' and column_name = 'discovery_id';

-- 3. Smoke test: insert + link a discovery
insert into discoveries (workspace_id, query, status)
values ((select id from workspaces limit 1), '__smoke_test__', 'cancelled');
select id from discoveries where query = '__smoke_test__';

-- 4. Cleanup
delete from discoveries where query = '__smoke_test__';
```
