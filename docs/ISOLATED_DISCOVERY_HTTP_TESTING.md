# Isolated Discovery HTTP integration

This is a **test-only, process-local synthetic backend**, not PostgreSQL,
Supabase, RLS or production equivalence. It runs real FastAPI Discovery/lead
routes, canonical session validation/workspace membership resolution,
repositories, job creation, the background runner, prospect matching, staging,
finalization and lead links. Table operations use the narrow thread-safe fixture
adapter. Data persists across requests/refresh, not process restarts.

The application composition root is not imported or started. Only reviewed
route/method pairs are available. OAuth, migration execution, provider sourcing,
delivery and startup recovery are unavailable. Optional Knowledge/Strategic
readers are empty fixture adapters; World Model publication is suppressed.
The synthetic refresh endpoint is fixture convenience, not OAuth/refresh proof.

## Review before starting

No server is automatically started by tests. The operator must approve and run
this command in a **new terminal**, without changing the existing frontend or
production-connected backend. Do not use port 10000. Port 19876 is fixed; a
collision is a blocker, not permission to stop another process or choose a port.

```sh
cd /Users/macbookair/Downloads/project-loqi/loqi-bot/backend
env -i PATH=/usr/bin:/bin LANG=C LOQI_ISOLATED_DISCOVERY_ENABLED=1 \
  .venv/bin/python -m tests.discovery_backend.bootstrap
```

The command does not inherit service configuration or load `.env`. The bootstrap
rejects inherited Supabase/PostgreSQL/OpenAI/Google/Gmail/Redis settings before
application imports. It activates the existing irreversible process-owned test
guard, installs only explicit offline doubles, and never authorizes a hosted
client. A process audit hook rejects outbound socket connections, unapproved DNS,
UDP sends and subprocess execution. Lifespan additionally blocks Python socket
connection APIs. Uvicorn uses one asyncio worker, no reload, numeric loopback only.
These controls prevent accidental application/network bypass, not malicious
native code running in the process. There is no native SQL driver execution path.

Startup prints a safe marker and fresh run UUID. HTTP requests must carry that
approved UUID and the fixed synthetic session, except the read-only identity/
health probes. Unknown tokens, stale run approvals, foreign workspaces and
unapproved Host headers are rejected. Fixtures contain 58 Alpha leads, one Beta
lead and one inaccessible foreign lead. No real credentials or customer rows.
There is no reset/delete/cleanup API. Shutdown discards only in-memory fixtures.

## Browser verification after approval

Use the already-running local frontend. In another terminal, copy only the
printed synthetic run UUID into the command below:

```sh
cd /Users/macbookair/Downloads/project-loqi/loqi-bot/frontend
LOQI_BROWSER_BASE_URL=http://127.0.0.1:3000 LOQI_BROWSER=firefox \
LOQI_RUN_DISCOVERY_HTTP=1 LOQI_ISOLATED_BACKEND_URL=http://127.0.0.1:19876 \
LOQI_ISOLATED_BACKEND_RUN_ID='<printed synthetic run UUID>' TMPDIR=/private/tmp \
  ./node_modules/.bin/playwright test tests/browser/isolated-discovery.spec.ts
```

The separate fixture verifies the backend marker/run before navigation, then
forwards approved browser API requests via real HTTP to exactly 127.0.0.1:19876.
**No request reaches port 10000** even if that origin is compiled into the UI.
No environment/configuration change to the existing frontend is necessary.
Only fixed synthetic credentials and reviewed headers are forwarded. No redirects
are followed. Other destinations fail closed; service workers are blocked and
WebSockets closed. Existing mocks handle only unrelated shell UI. Discovery,
leads, workspace listing, auth/me and capability responses come from the backend.

This transport bridge exercises mounted UI and backend HTTP/worker behavior,
but does not establish native browser CORS behavior against a direct backend
origin or production composition-root middleware. No traces or stored auth state.
Tests are serial, with no retries; backend restart requires a new run approval.

Prepared tests verify 56 prospect matches over two pages, role synonyms, no
engineers/foreign leads, strict London filtering (54), persisted links/refresh,
workspace navigation, and failed/truncated staging never showing Research complete.
Failure injection affects only the next synthetic staging write.

## Offline checks (no server)

```sh
cd backend
LOQI_RUN_DB_INTEGRATION=0 LOQI_RUN_EXTERNAL_INTEGRATION=0 LOQI_TEST_POSTGRES_ENABLED=0 \
  .venv/bin/python -m pytest tests/test_discovery_backend.py -q
cd ../frontend
./node_modules/.bin/playwright test tests/browser/isolated-discovery-safety.spec.ts
```

The mounted acceptance test remains unverified until the operator starts the
reviewed isolated backend and the Firefox tests actually pass. These checks
cannot establish database durability, transaction semantics, RLS or PostgREST.
