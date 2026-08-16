# Loqi Backend — Rollback & Recovery Runbook

Production alignment: this document is written against what is actually
implemented today — a Railway deployment of the `backend/Dockerfile` image,
Supabase-managed persistence, and the PR10 startup/health/configuration
machinery. It does not describe tooling that does not exist in the repo.

> Rule of thumb during an incident: **read first, act second.** Every
> recovery step below starts with observation (endpoints, logs, variables)
> before any change is made.

---

## 1. Deployment rollback

### 1.1 Identify the currently deployed version/commit

Three independent signals exist:

1. **`GET /version`** (FastAPI, no auth) — returns:
   `application`, `version` (`APP_VERSION`, default `0.2.0`), `commit`,
   `build_timestamp`, `environment`, `repository_provider`.
   ```bash
   curl -s https://<prod-host>/version
   ```
2. **Startup diagnostics log lines** (first lines after boot):
   ```
   Environment:      production
   Repository:       supabase
   Commit:           9c88500...
   Build Timestamp:  2026-08-16T...Z
   ```
   and the tail marker:
   ```
   application_ready duration_ms=NNNN
   ```
3. **Railway UI → project → Deployments**: each deployment row shows the
   source commit/reference and deploy time.

Note: inside the container there is no `.git` checkout, so `diagnostics.py`
falls back to the `GIT_COMMIT` env var. Map Railway's injected
`RAILWAY_GIT_COMMIT_SHA` into `GIT_COMMIT` so `/version` and logs always
show the real commit.

### 1.2 Roll back to the previous known-good deployment

Production deploys from the git branch connected to the Railway service
(container deployment, `backend/Dockerfile`).

- **Roll back a bad deploy (no code change needed):**
  1. Railway → your service → **Deployments**.
  2. Find the last deployment you know was healthy (its `/version` commit
     matches the last known-good commit; `/ready` returned 200).
  3. **Roll back** to that deployment from the deployment's action menu
     (Railway redeploys that exact image).
  4. This uses the same image already built — no rebuild, fastest path.
- **Roll back a bad commit (code fix needed):**
  1. `git revert <bad-commit>` (or `git checkout <known-good>` on a branch)
  2. Push to the deploy branch.
  3. Railway builds and deploys the new image automatically.
  4. Do **not** rush to push a fix on top of a broken deploy — the fastest
     safe path is the image rollback, then fix on the side.

What rollback does NOT do: it does not touch Supabase data and does not
revert applied SQL migrations. Database schema rollback is its own topic →
section 3.

### 1.3 Verify the rollback succeeded

1. `GET /version` → `commit` equals the known-good commit.
2. `GET /ready` → `200 {"status":"ready"}`.
3. `GET /health` → `200`, `"database":"configured"`.
4. Railway logs for the new deploy show `application_ready duration_ms=...`
   and no `ERROR` for configuration validation or Supabase connectivity.
5. Run the section 6 checklist.

---

## 2. Application recovery

### 2.1 If the production application becomes unhealthy

Fail-safe design points that are actually implemented:

- **Config fail-fast (PR10.2).** Invalid/unsafe environment at startup raises
  `RuntimeError("Configuration validation failed: ...")` → the process exits
  → Railway restarts → crash loop. This is *by design*; the remedy is to fix
  the environment variables (section 4), not to "wait it out".
- **Readiness gate (PR10.6).** The app only reports ready after startup work
  completes: `starting → ready → shutting_down`, or `failed` on startup
  failure. `/ready` returns 503 while not ready.
- **Optional integrations never gate readiness.** A missing optional
  integration degrades a feature but does not block `/ready` (degraded-mode
  operation is intentional).

### 2.2 Use the existing health/readiness checks

| Endpoint | Meaning | Expected healthy |
|---|---|---|
| `GET /health` | Liveness — process is up (no external calls, no secrets) | `200 {"status":"healthy", "version":"v2", "database":"configured", "providers":"ready"}` |
| `GET /ready` | Readiness — lifecycle state | `200 {"status":"ready"}`; not ready → `503 {"status":"starting"\|"failed"\|"shutting_down"}` |
| `GET /version` | Build/commit identity | `200` with `commit` + `build_timestamp` |

Note: `/ready` and `/health` make **no** external calls by design — they
verify the process and its startup state, not Supabase/OpenAI/Gmail. The
`"database":"configured"` field only reflects that `SUPABASE_URL` is set, not
that it works. Live dependency health is verified separately (section 3/6).

### 2.3 Restart / redeploy safely

1. Confirm the failure is the app, not a configuration problem — read the
   latest Railway logs first:
   - Crash loop reason is almost always found in the first startup log block
     (config validation error, missing env, `/data` permission).
2. **Soft restart** (no code change): Railway → Deployments → **Redeploy**
   the current deployment.
3. **Privileged restart**: the `entrypoint.py` container setup runs as root
   only to `chown` the mounted `/data` volume to `appuser`, then drops
   privileges (uid=10001) before exec'ing uvicorn. A redeploy re-runs this
   automatically — no manual permission fix is needed.
4. Do not randomly change environment variables "while I'm in here" — each
   variable change is a config change (section 4). Restarts are restart-only
   actions.

### 2.4 Verify recovery

- `/ready` 200, `/health` 200, `/version` shows the intended commit.
- Startup logs: `runtime_user uid=10001 ... name=appuser`,
  `application_ready duration_ms=NNNN`, no `Configuration validation failed`.
- In-memory workflow/backfill state recovers automatically from
  `workflow_sessions` at startup (canonical backfill task) — confirm the
  `backfill startup task completed` log line.
- Run the section 6 checklist.

---

## 3. Database / persistence recovery

### 3.1 Current persistence setup (what is actually implemented)

- **Source of truth: Supabase** (managed Postgres + PostgREST), accessed via
  `SUPABASE_URL` + `SUPABASE_KEY` through the `supabase` Python client.
  Durable tables used in production include `users`, `workflow_sessions`,
  `conversations`, `leads`, `connected_accounts`, `identity_users`, and the
  core/job tables.
- **Local auxiliary state:** the Railway persistent volume mounted at `/data`
  holds `CONVERSATIONS_STATE_FILE=/data/conversations.json` and
  `COMMUNICATION_STATE_FILE=/data/communication.json`. Writes are atomic
  (tmp file → fsync → `os.replace`), guarded against stale writes by a
  monotonic `sequence`, and a corrupt file is *preserved* (renamed to
  `<file>.corrupt.<ts>`) and logged as `persistence_corrupt_state`, never
  silently overwritten. Losing these files is not catastrophic: the durable
  domain state lives in Supabase and in-memory workflow state rehydrates
  from `workflow_sessions`.
- **Schema migrations:**
  - Numbered, additive SQL files in `backend/supabase/migrations/`
    (`003_...` → `021_identity_sessions.sql`), applied by hand via the
    Supabase **SQL Editor** (or `psql`/`DATABASE_URL`).
  - `services/migration.py::apply_migrations()` runs at startup only when
    `DATABASE_URL` is set and applies a separate embedded core bundle
    (`jobs`, `search_results`, `discoveries`, ... plus additive guards).
    When the core tables already exist and `DATABASE_URL` is absent it is a
    no-op. All statements use `IF NOT EXISTS` — re-running is safe.
  - **Migration `021_identity_sessions.sql` is drafted but NOT yet applied**
    to production. It is required for production authentication (identity
    session/token tables); it must not be applied until reviewed (previous
    PR10 step) and applied deliberately after the next release, not as part
    of an incident.

### 3.2 Recovery / rollback capabilities that actually exist

Implemented today:
- **Safe, idempotent, additive migrations** — numbered SQL files and the
  embedded startup bundle can be re-run without destroying data.
- **Atomic local state files with corruption preservation** — a corrupt
  `/data/*.json` is set aside as `.corrupt.<ts>` for operator recovery while
  the app continues on the preserved snapshot path.
- **Automatic rehydration of workflow state** from `workflow_sessions` at
  startup after a restart/deploy.

NOT implemented (do not assume these exist):
- ❌ **No automated database backup/restore tooling in the repo.** There is
  no dump snapshot, no PITR script, no restore procedure committed here.
  Supabase is a managed platform; any backup/PITR capability must be enabled
  in the **Supabase Dashboard** (Backups settings) and is a platform
  feature, not part of this codebase.
- ❌ **No schema rollback tooling.** Migrations are additive-only; rolling
  back a schema change means writing a new corrective migration (as was done
  for identity tables), not re-running old code against an old schema.
- ❌ **No cross-region / disaster-recovery deployment.**

### 3.3 Database incident recovery procedure

1. Diagnose from logs/endpoints — do not mutate anything yet.
   - Connectivity errors (`PGRST…`, timeouts, `get_supabase_client` failure)
     → check `SUPABASE_URL`/`SUPABASE_KEY` (section 4) before assuming data
     loss.
   - `PGRST205 … could not find the table 'public.<x>'` → a required table is
     missing (e.g., `sessions` before `021` is deliberately applied). Treat
     this as a pending migration and schedule it with the next controlled
     release — do not apply migrations as an emergency incident action. After
     the migration is applied, refresh PostgREST if needed:
     `NOTIFY pgrst, 'reload schema';`.
2. `/data` corruption: the app already preserves the corrupt file. Look for
   `persistence_corrupt_state` logs; the `.corrupt.<ts>` files in `/data`
   can be handed to the operator/reviewed manually.
3. Verify persistence after any recovery: run a read-only probe of the
   critical tables (see section 6, "database connectivity/persistence").

Future improvements (documented, not built): automated Supabase backups +
restore runbook, a migration-status/version table check, and a DR plan.

---

## 4. Configuration / secrets recovery

### 4.1 What happens when an env var or secret is wrong/missing

Startup validation (`services/config_validation.py` + `services/operations/
diagnostics.py`) is fail-fast **and redundant** at startup:

- **Required in production** (missing → startup error → crash loop):
  `SUPABASE_URL`, `SUPABASE_KEY`, `OPENAI_API_KEY`, `GOOGLE_CLIENT_ID`,
  `GOOGLE_CLIENT_SECRET`, `LOQI_CREDENTIAL_ENCRYPTION_KEY` (64 hex,
  placeholder rejected).
- **Conditional requirements:**
  - `EMAIL_PROVIDER=resend` in production → `RESEND_API_KEY` required.
  - `TELEGRAM_BOT_TOKEN` set → `TELEGRAM_WEBHOOK_SECRET` required (the
    `/webhook` endpoint is otherwise unauthenticated).
  - `BILLING_PROVIDER_MODE=mock` → rejected in production.
  - `RATE_LIMIT_ENABLED` → must be enabled (truthy) in production.
  - `LOG_LEVEL=DEBUG` → rejected in production.
  - Dev/test flags (`SIMULATE_*`, `LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE`,
    `MOCK_TOKEN`) → rejected in production.
- `ENVIRONMENT`/`APP_ENV=production` also flips the repository provider to
  **Supabase** (`services/persistence/config.py`) — a silent in-memory
  fallback is no longer possible in production.
- **Error messages are key-only** — errors, warnings and logs reference the
  variable name and never the value. Never place a real secret in a config
  error, a log line, or this document.

### 4.2 Restore configuration safely

1. Identify the failing key from the startup error (never paste the value).
2. Open Railway → service → **Variables** and correct only that variable.
3. Redeploy (variable changes require a redeploy).
4. Confirm with `GET /ready` (200) and the startup diagnostics block.
5. If `LOQI_CREDENTIAL_ENCRYPTION_KEY` changed (rotation/restore):
   - Existing `connected_accounts` credentials were AES-256-GCM encrypted
     under the **old** key.
   - Rotation (supported): set the old key as
     `LOQI_CREDENTIAL_ENCRYPTION_KEY_PREVIOUS`, keep the new key as
     `LOQI_CREDENTIAL_ENCRYPTION_KEY`, redeploy. Decryption falls back to the
     previous key automatically.
   - If the current key is wrong and there is no previous key, encrypted
     credentials cannot be decrypted (decrypt failures are tolerated —
     provider marked for reauth, tokens skipped). The safe restore is to put
     the original key back (or rotate properly), then re-connect affected
     accounts via the Gmail OAuth flow (section 5).

---

## 5. OAuth / integration recovery

### 5.1 Gmail OAuth production configuration to verify

- Env keys: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
  `GOOGLE_REDIRECT_URI` (validated as an http(s) URL at startup).
- Endpoints: `GET /api/auth/gmail/url` (starts the OAuth flow),
  `GET /api/auth/gmail/callback` (exchanges the code, replaces the existing
  provider row / clears a reauth-required state).
- Credentials are stored in `connected_accounts` (encrypted at rest with the
  key from section 4). Status `auth_failed` marks a connection as
  reauth-required; startup provider restoration re-surfaces it rather than
  silently retrying.

### 5.2 What to check if authentication/integration breaks after a deploy

1. **Redirect URI mismatch** — the value of `GOOGLE_REDIRECT_URI` must match
   the "Authorized redirect URIs" configured in the **Google Cloud Console**
   OAuth client **exactly** (scheme, host, port, path). After any deploy,
   verify the variable matches the console; mismatch → `redirect_uri_mismatch`
   at `/callback`.
2. **Client credentials** — `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` still
   match the console client (wrong secret → 401 at token exchange).
3. **Credential decryption** — if `LOQI_CREDENTIAL_ENCRYPTION_KEY` changed
   without rotation, connected accounts fail to decrypt; look for
   decryption-skip logs and providers flipping to reauth-required. Fix the
   key (section 4.2), then reconnect.
4. **One account per user** — reconnecting replaces the existing provider in
   `connected_accounts`; a stale `auth_failed` copy does not shadow the new
   one (partial unique active index). Reconnect rather than hand-editing
   rows.
5. **Log signals** to grep in Railway: `gmail_auth_reauth_required`,
   `connected account marked auth_failed`, credential-decryption failures,
   `get_google_credentials error`.

---

## 6. Recovery verification checklist

After any rollback or recovery, confirm each item before calling it done:

1. **Application reachable** — `GET /health` returns 200.
2. **Health/readiness healthy** — `GET /ready` returns `200 {"status":"ready"}`
   (not 503).
3. **Version correctness** — `GET /version` shows the intended `commit` and
   `environment: production`.
4. **Critical API endpoints respond** — exercise a real request path, e.g.
   `GET /api/auth/gmail/url` (no auth), a web-session bootstrap, or the
   `/docs` + one authenticated endpoint, expecting a valid response, not 500/
   connection errors.
5. **Database connectivity/persistence works** — run the read-only table
   probe (existence of `identity_users`, `workflow_sessions`, `jobs`,
   `connected_accounts`) and confirm a read-only query returns data with no
   `PGRST…` error. (Example probe: SELECT-only calls to those tables.)
6. **Authentication/OAuth works** — a real login/refresh round-trip
   succeeds; connected Gmail account is `active` (not `auth_failed`); a
   provider `/health` endpoint returns healthy.
7. **Logs show no critical errors** — Railway logs: no `Configuration
   validation failed`, no `persistence_* error`, no unhandled Supabase/
   OpenAI/Gmail exceptions, and the `application_ready` marker present.

---

## 7. Failure scenarios — concise recovery procedures

### S1. Crash loop right after deploy (most common)
1. Railway logs → read the first startup block.
2. `Configuration validation failed:` → fix that variable (section 4.2) and
   redeploy. → skip to step 5.
3. Permission error on `/data` → redeploy (entrypoint re-chowns). If the
   image predates `entrypoint.py`, deploy the current image.
4. Any other exception → roll back to the previous known-good deployment
   (section 1.2), then investigate the bad deploy offline.
5. Verify: section 6.

### S2. App up (`/health` 200) but `/ready` 503
1. `set_failed()` or long `starting` state → read startup logs for the
   blocking provider/backfill step.
2. A slow backfill is transient — wait one window; otherwise roll back the
   deployment (section 1.2).
3. Verify: section 6.

### S3. Supabase unreachable / wrong credentials
1. Check `SUPABASE_URL`/`SUPABASE_KEY` and the startup validation errors, and confirm the Supabase project itself
   is not down (Supabase Status page).
2. Restore correct variables (section 4.2), redeploy.
3. Verify connectivity with the read-only probe and section 6.

### S4. Authentication fails with `PGRST205 … 'public.sessions'`
1. Confirm whether `021_identity_sessions.sql` has been deliberately applied
   to the current production database.
2. If it has **NOT** been applied, do not apply it as an emergency rollback
   action. Treat this as a pending release/migration issue and follow the
   migration procedure for the next controlled release.
3. If the migration has already been applied but PostgREST reports the table
   as unknown, run `NOTIFY pgrst, 'reload schema';`.
4. Verify a login round-trip succeeds.

### S5. OAuth / Gmail integrations broken after deploy
1. Section 5.2 checks (redirect URI, client id/secret, encryption key).
2. Re-run `/api/auth/gmail/url` → complete flow → provider returns `active`.
3. Verify section 6 items 5–6.

### S6. `/data` state file corrupt
1. The app already preserved it (`.corrupt.<ts>` + `persistence_corrupt_state`
   log); no data loss concern for durable domain state.
2. Confirm the app continued or restarted cleanly (`backfill startup task
   completed`).
3. Optionally back up the `.corrupt.*` file out of the container for
   offline review.

### S7. Webhook appears unauthenticated
1. If `TELEGRAM_BOT_TOKEN` is set, production requires
   `TELEGRAM_WEBHOOK_SECRET`; a `webhook_unauth` warning means it's unset.
2. Set the secret in Railway variables, redeploy, re-register the webhook
   with the same `secret_token`.
3. Verify a webhook POST with an invalid header returns 403.

---

## 8. Current gaps to address in a future phase

The following are **not implemented** today and must not be assumed during an
incident:
- Automated Supabase backup/restore (enable platform backups; no repo-level
  dump/PITR tooling).
- Schema migration version/status tracking (independent of the rope of
  numbered `.sql` files and the runtime core bundle).
- Automated deploy-gate health probe (rolling back on failed readiness).
- DR/multi-region deployment.
- Mapping Railway's `RAILWAY_GIT_COMMIT_SHA` into `GIT_COMMIT` (currently
  optional) so `/version` is always accurate in-container.

---

## 9. SaaS-1.7 production-closure rollback/recovery (APPLY-GATED)

This section is only relevant during/after the human-controlled SaaS-1.7
migration application. Distinguish the three recovery classes explicitly.

### 9.1 Application rollback vs database schema rollback vs data reconciliation

- **APPLICATION ROLLBACK**: Railway → Deployments → roll back to the previous
  known-good image (section 1). This **preserves the schema** — the migrated
  database stays migrated, and the older application image must tolerate the
  newer schema (all SaaS-1.7 migrations are additive and additive-only, so a
  previous image reading the new tables/columns is safe).
- **DATABASE SCHEMA ROLLBACK**: all SaaS-1.7 migrations are **additive and
  irreversible-by-rollback** (they create tables/indexes only; no destructive
  operations, no data alteration). There is **no supported schema rollback** —
  "rollback" means restore the previous application deployment while the
  schema remains applied. Do not drop the new tables to "roll back": that is
  an irreversible, manual action with no repo-level tooling.
- **DATA RECONCILIATION RECOVERY**: the synthetic-user reconciliation
  (`scripts/reconcile_web_sessions.py`) is idempotent and re-keying is the
  only mutation (UPDATE of owner/user ids). It never deletes. Recovery from a
  bad reconciliation is a **manual data fix** (restore the original ids from
  the dry-run report); it is not reversible by the script.

### 9.2 Migration failure response

1. Stop applying further migrations.
2. `NOTIFY pgrst, 'reload schema';` only if PostgREST reports stale tables.
3. Re-run the same migration file (all are `IF NOT EXISTS`/idempotent — safe
   to re-run after a partial failure).
4. If an index build is expensive on large tables (e.g. `memberships`,
   `billing_*`), it completes asynchronously on Postgres; verify via
   `pg_indexes` before proceeding.
5. Confirm with the read-only table probe; then continue the operator
   checklist (section 9.3).

### 9.3 Operator execution checklist (mirrors the SaaS-1.7 report)

1. Verify Supabase backup/PITR is enabled and take a manual backup.
2. Apply migrations **021 → 022 → 023 → 024 → 025 → 026** in order (each
   additive/idempotent; re-run safe).
3. `NOTIFY pgrst, 'reload schema';`.
4. Run the read-only table probe (all required tables EXIST).
5. Run `python -m scripts.reconcile_web_sessions --dry-run` → review the plan
   and orphan report.
6. Run `python -m scripts.reconcile_web_sessions` (apply) if the plan is clean.
7. Re-run the dry-run → must report zero remaining re-keyable rows.
8. Set production env (ENVIRONMENT=production, identity secrets, redirect URI)
   and deploy the image.
9. Verify `/version` (commit), `/health`, `/ready`.
10. Run `python -m scripts.saas_smoke_test` with a pre-provisioned test account.
11. On any smoke failure: application rollback (9.1) first; if schema-related,
    verify migrations + schema reload, then re-run smoke.
12. Escalate to manual data recovery only if reconciliation orphaned rows need
    attention (documented in the dry-run report).

### 9.4 Known-good deployment identification

The last deployment whose `/version` `commit` matches the pre-migration image
and whose `/ready` returned 200 is the known-good application deployment.
Migrations 021–026 are backward-compatible with the pre-SaaS-1.7 image (all
additive), so the known-good image can be restored without schema reverts.