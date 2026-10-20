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

## Startup-only large profile (separate operator approval required)

The default remains `small`: 58 Alpha candidates, one Beta control, one foreign
control. The shared pure builder in `tests/discovery_backend/datasets.py` also
provides `large`: 604 Alpha candidates, two Beta controls, one foreign control.
The backend regression and startup store use the same builder. All IDs and facts
are deterministic and synthetic. Each store owns fresh rows.

Only the guarded startup reads `LOQI_ISOLATED_DISCOVERY_PROFILE`. It validates
the exact value `small` or `large` after opt-in/configuration checks, captures it
before application construction, and rejects unknown values. There is no HTTP
reseed/reset/import endpoint. Identity reports `profile` and `fixture_counts`.
The currently running small process is unchanged by these source edits.

For a later, separately approved operator-managed restart only:

```sh
cd /Users/macbookair/Downloads/project-loqi/loqi-bot/backend
env -i PATH=/usr/bin:/bin LANG=C LOQI_ISOLATED_DISCOVERY_ENABLED=1 \
  LOQI_ISOLATED_DISCOVERY_PROFILE=large \
  .venv/bin/python -m tests.discovery_backend.bootstrap
```

Do not stop an unidentified listener or start a second server on the fixed port.
Record and approve the **new** printed UUID; old UUIDs are invalid. Read-only
identity must show `profile: large` and counts Alpha 604, Beta 2, foreign 1,
total 607, alongside the existing memory/outbound-blocked markers.

### Actual UI with native HTTP, not the legacy bridge

`large-discovery-ui.fixture.ts` mounts the real `/discovery` page. It requires a
separately operator-configured frontend at `http://127.0.0.1:3000` whose
`NEXT_PUBLIC_LOQI_API_BASE_URL` is explicitly `http://127.0.0.1:19876` at frontend
build/start time. Merely setting this variable in the test command does **not**
reconfigure an existing frontend. Preparing/replacing that frontend requires
separate approval; no server is managed by this test. A possible operator start
command, only after approving that frontend setup, is:

```sh
cd /Users/macbookair/Downloads/project-loqi/loqi-bot/frontend
NEXT_PUBLIC_LOQI_API_BASE_URL=http://127.0.0.1:19876 \
  npm run dev -- --hostname 127.0.0.1 --port 3000
```

The fixture rejects a small-profile identity before mounting the UI. API requests
and OPTIONS use Firefox HTTP directly: no API route fulfillment, URL rewriting,
or Node forwarding. Only frontend navigation HTML is relayed with unchanged body
and a restrictive CSP to suppress external fonts/preconnects. Destination guards
abort unexpected API paths, port 10000 and external hosts; service workers and
WebSockets are blocked. Synthetic auth/refresh, capability, workspace listing and
membership-checked selection support the shell. Event streaming remains rejected
with 403; no unrelated workers start. Search, filters and pagination remain real
application behavior.

After both processes and the new UUID are separately approved:

```sh
cd /Users/macbookair/Downloads/project-loqi/loqi-bot/frontend
NEXT_PUBLIC_LOQI_API_BASE_URL=http://127.0.0.1:19876 \
LOQI_BROWSER_BASE_URL=http://127.0.0.1:3000 LOQI_BROWSER=firefox \
LOQI_RUN_DISCOVERY_HTTP=1 LOQI_ISOLATED_BACKEND_URL=http://127.0.0.1:19876 \
LOQI_ISOLATED_BACKEND_RUN_ID='<new approved large-profile UUID>' TMPDIR=/private/tmp \
  ./node_modules/.bin/playwright test tests/browser/large-discovery-ui.spec.ts
```

Prepared assertions cover exact canonical IDs/order across 13 broad-query pages
(12 × 50 + 2), strict London 600/ecommerce 601, completed CTO zero, refresh without
another POST, workspace navigation, and truthful failed/truncated staging.
This mounted large-profile suite has **not** been executed by preparing it;
browser pagination is unverified until all assertions actually pass. Existing
58-candidate suites remain unchanged and must run only against the small profile.

### Restoration and workspace round-trip evidence

The large UI fixture records a request ordinal and only the workspace header
(not credentials) for each native API request. Successful lead responses retain
that ordinal, workspace, HTTP status and canonical IDs. Restoration checks require
a GET initiated after the navigation/reload boundary for the same discovery ID;
an older request completing late cannot satisfy the assertion.

The broad case checks a fresh page-13 GET after reload, reopens the original
page-one URL and traverses all 13 pages again with exact IDs. It then switches
A → B through the real picker, verifies B's two controls through Lead Database,
returns to blank Discovery, and switches B → A. The picker intentionally clears
search context; Search history reopens the exact completed A run, followed by
another fresh GET and full 13-page traversal. Every captured lead response is
checked against its workspace's canonical ID set. None of these restoration or
switching actions may add a Discovery POST. Reserve the backend exclusively:
staging fault injection remains process-global, not a per-client lease.

OPTIONS observation is intentionally deferred for this mounted large suite.
The existing native small-profile fixture's observer is embedded in its fixture
and patches private process-global Playwright diagnostics, pinned to 1.64.0.
Reusing it here would require changing the protected small-profile file or
duplicating that fragile machinery. This change does neither, installs no global
logging hooks, and does not intercept API traffic. The dedicated native suite
retains its explicit preflight checks; these large tests do not independently
assert OPTIONS status/headers. New restoration/round-trip assertions remain
unverified until the separately approved large-profile browser run.
