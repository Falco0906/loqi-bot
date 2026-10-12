# Batch 11 — Safe mounted browser testing

## Tooling decision (before installation)

The frontend has no declared browser runner. Add only `@playwright/test` as a
development dependency: it provides mounted browser interactions, browser
navigation and request interception in one package. Existing local Chromium
cache can be used; do not download a browser or install another framework.

No application/backend behavior or test-runtime safeguards need changing.
Tests use synthetic identities and fixtures, never application credentials.
The runner requires a user-managed local frontend: AGENTS.md prohibits agents
from starting/stopping servers. There is deliberately no Playwright webServer.

## Isolation contract

Require an explicit loopback frontend URL. Intercept every browser request;
only local frontend documents/static assets may pass through. API requests are
fulfilled from fixtures; unknown requests fail closed. Block service workers
and WebSockets. Never use Playwright APIRequestContext against the backend.
Do not save traces/storage state containing application data or credentials.

Browser mocks verify client behavior, not Supabase/RLS, migration transactions,
real authentication, provider/model quality, or production readiness.

## Known setup limitation

The visible WorkspaceSwitcher is a placeholder, not a membership picker.
Workspace tests select the existing requested scope through workspace_id URLs
and verify mocked membership enforcement. This is not verification of a usable
workspace-switching control.

## Commands

In a separate terminal, the user starts the frontend with no backend running:

```sh
cd frontend
NEXT_TELEMETRY_DISABLED=1 npm run dev -- --hostname 127.0.0.1 --port 3000
```

Then run the isolated journey (the runner never starts a server):

```sh
cd frontend
LOQI_BROWSER_BASE_URL=http://127.0.0.1:3000 npm run test:browser
npm run test:browser:safety
```

The runner defaults to Firefox. Use Playwright's matching Firefox build (the
system Firefox binary is not compatible with Playwright's driver). Do not point
it at a logged-in browser profile. The runner creates a fresh disposable context for each test.
Without an explicit loopback URL, mounted tests fail before page navigation.
Remote targets, URL credentials and arbitrary base paths are rejected.

External fonts are stubbed with empty local responses. Next's local dev HMR
socket is closed without connecting; all other sockets fail the test. HTTP API
mocks handle CORS preflight locally too. Firefox uses a fresh Playwright-managed
profile. Firefox startup required `TMPDIR=/private/tmp` on this machine.

## Validation so far

- Network safety: **2 passed, 0 failed, 0 skipped** in Playwright Firefox. The
  tests use `about:blank` and verify that unknown production, Supabase and AI
  URLs are blocked while fixture-backed API requests are fulfilled locally.
- Existing verified-offline backend regressions: **151 passed, 0 failed,
  0 skipped** (10 selected suites, including safety, journey, workspace,
  rollback/idempotency, generation, staged persistence and normalization).
- Existing frontend regressions: **51 passed, 0 failed, 0 skipped** (10 suites).
- Mounted journey: **7 passed, 0 failed, 0 skipped** against the user-managed
  frontend at `http://127.0.0.1:3000` in Firefox. The per-test browser console
  and page-error guard passed with no console errors.
- TypeScript, production frontend build, backend compileall and diff-check:
  passed. The seven mounted tests also collect successfully; collection is not
  execution. Existing Next multiple-lockfile inference, Node module-type and
  Starlette TestClient warnings remain.

Executed frontend regression files:

```text
campaign-draft-workspace.test.mts
beta-journey-contracts.test.mts
discovery-context.test.mts
discovery-campaign-actions.test.mts
lead-generation-recovery.test.mts
beta-lead-flow.test.mts
lead-intelligence.test.mts
campaign-creation-safety.test.mts
draft-copy-actions.test.mts
draft-lifecycle.test.mts
```

Executed backend regression files:

```text
test_supabase_test_safety.py
test_shared_test_identity.py
test_beta_journey_offline.py
test_campaign_draft_workspace_context.py
test_campaign_attachment_rollback.py
test_campaign_creation_safety.py
test_lead_generation_reliability.py
test_discovery_staged_persistence.py
test_workspace_context_propagation.py
test_search_field_consistency.py
```

The known standalone discovery-routing Node ESM failure remains documented in
Batch 9; that unrelated suite was not rerun or changed here. Database/provider
integration suites were excluded, not counted as skipped in these totals.

## Changes and remaining work

Changed only frontend package.json/package-lock.json; added playwright.config.ts,
tests/browser/fixtures.ts, beta-journey.spec.ts, network-safety.spec.ts and this
report. @playwright/test is the sole direct development dependency addition
(three installed packages total). No app code, SQL, CI or backend safety guard
was changed; Batches 1–10 remain intact.

Mounted verification covered CSV preview/confirm/read-back; explicit Discover
search, filter and pagination selection, selection reset, reload/history and
browser back/forward; explicit Intelligence analysis and strategy generation,
read-only recovery and copy; existing/new campaign actions; Draft Review edit
and clearing subject/body; requested workspace changes and inaccessible scope;
out-of-order results; and a failed result read with retry. The tests asserted
canonical selected IDs, scoped API headers, and absence of send/schedule/launch
requests. They do not verify server-side CSV parsing or duplicate handling;
existing offline backend tests cover those functions. Real login/workspace-picker
UI, database/RLS, idempotency RPC/transactions and real durable-worker restart
behavior require separate dedicated-environment verification. Mocked API gates
cannot establish backend enforcement; offline backend capability tests remain
regression coverage, not production proof.

CI currently has no frontend browser job. The harness deliberately does not
add automatic server management; a reviewed CI orchestration follow-up can
start an isolated frontend with no backend credentials and run the same mocks.

Do not interpret implementation or collection as mounted browser verification.
