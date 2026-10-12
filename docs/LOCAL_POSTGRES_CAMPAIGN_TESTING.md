# Disposable local PostgreSQL campaign contract tests

## Implementation boundary and current evidence

This harness is test-only. No database was provisioned, no SQL was executed,
and no migration was applied during implementation. Migration 048 remains
unchanged. Mock tests prove control flow and rejection behavior, NOT PostgreSQL
locking, transaction, privilege or production equivalence guarantees.

Environment inspection found Homebrew `psql`/`postgres` **14.18**, Docker CLI
**28.3.2**, and existing `psycopg2-binary` requirements. The harness pins **16**.
No PostgreSQL 16 installation, Docker image download or daemon interaction was
performed. Existing `compose.yaml` starts the real application using backend
`.env` and Supabase: DO NOT use it for these tests. No new Docker service is needed.

No authoritative sanitized production schema snapshot was supplied. Known
facts are repository definitions and application contracts only. Production
PostgreSQL version, migration history, drift, RLS, grants and triggers remain
unknown. Do not describe this environment as production-equivalent yet.

## Safety model

- Hosted Supabase approval remains separate and unchanged. A local capability
  cannot authorize `create_supabase_client` or install a real Supabase client.
- `requires_local_postgres` is skipped unless `LOQI_TEST_POSTGRES_ENABLED=1`.
  The marker is not authorization. Every native-driver connection revalidates
  an exact approved target file and performs read-only server identity probes.
- All configuration uses `LOQI_TEST_POSTGRES_*`. There is no `DATABASE_URL`,
  application `.env`, Supabase, DSN, service-file or password-file fallback.
  Any inherited `PG*` setting is rejected; `passfile=/dev/null` and an empty
  password are explicit. Socket paths cannot be TCP hosts or URLs.
- Root/socket/data directories and target/PG_VERSION files must be private,
  owned by the process user, canonical paths, and not symlinks. Root name binds
  the UUID; database name binds the same UUID; port is exactly 55432.
- The server must report PostgreSQL 16, Unix-socket transport, no TCP listener,
  the exact data directory, expected database owner and run-specific comment.
  The execution owner must not be superuser, create roles/databases or bypass
  RLS. Required roles must be present, nonprivileged and available for SET ROLE.
- Owner's `pg_read_all_settings` membership permits identity inspection only;
  it is a test provision fixture, not a change to production authorization.
- No connection is made at import/collection time. No application startup,
  AI/provider/email calls, recovery workers, process management, database
  reset/drop or automatic record-cleanup path is introduced.
- Python socket blocking stays active for these tests. Since psycopg2 uses
  native libpq, socket monkeypatching alone is NOT claimed to protect this path.
  All local test connections must go through the capability-bound factory.

This prevents ordinary accidental configuration bypass, not malicious Python
code running in the same process or an operator deliberately approving a fake
disposable target. The private dedicated cluster is essential.

## Reviewed manifest and dependencies

`backend/tests/postgres/migrations.json` pins exact SHA-256 source bytes:

| Order | File | Why needed |
| --- | --- | --- |
| 1 | 004_identity_platform.sql | UUID `identity_users`, workspace owner/member FKs |
| 2 | 006_workspaces.sql | Organizations, workspaces and workspace-member projection |
| 3 | 007_domain.sql | Global and canonical workspace leads/companies, provenance, signals and uniqueness |
| 4 | 008_campaigns.sql | Campaigns, canonical attachments, strategies and related drafts |
| 5 | 014_discoveries.sql | Discovery scope plus guarded `campaigns.discovery_id` FK; campaigns MUST exist first |
| 6 | 016_campaign_lifecycle.sql | Lifecycle CHECK used by the current creation contract |
| 7 | 025_organization_persistence.sql | Canonical active organization membership authorization |
| Separate | 048_campaign_creation_idempotency.sql | Requires a second exact-byte approval; never part of prerequisite bootstrap |

### Deliberate exclusion: 005 external identity

This is a deliberately bounded campaign-contract schema, not a replay of the
complete production migration stream. Migration `005_external_identity.sql`
creates `external_identities` and `connected_accounts`; the dependency audit
found no hard SQL dependency on those tables in the bounded migration chain
used by the campaign-creation contract. Migration 004 supplies
`identity_users`, which the bounded schema uses for workspace-related identity
references.

Migration `006_workspaces.sql` retains its comment directing deployments to
apply it after 005. That migration SQL and comment are unchanged. The fixture's
inspected SQL dependency graph does not establish a hard dependency on 005,
but whether the comment expresses a broader deployment-order requirement
remains unresolved unless clarified by migration ownership or release
documentation. Omitting 005 does not make this a complete application schema
or a verified copy of production Supabase.

No campaign table definitions are copied. Prerequisites run transactionally on
a catalog-checked fresh disposable database; unexpected objects refuse bootstrap rather than
being reset. Role/schema/table grants are explicit LOCAL fixtures because the
function is SECURITY INVOKER. No required extension beyond built-in PL/pgSQL
and PostgreSQL 16 UUID generation was identified for this selected subset.

The numbered stream starts at 003 and lacks the UUID `users` baseline required
by jobs and `multi_client_mvp.sql`. Separate persistence 001 uses TEXT users;
separate persistence 002 uses TEXT membership IDs, unlike numbered 025 UUID
memberships. They are not interchangeable. Those legacy streams are excluded,
not repaired. `lead_sources.job_id` is not a jobs FK, and 014 guards its jobs
alteration; no job table is needed for this bounded RPC bootstrap. No durable
job or full application schema is claimed. Discovery metadata 015 is not
required by this SQL contract; Python discovery hydration needs a later profile.

Changing source files requires re-review and manifest repinning; approval of
an old checksum will stop before connecting for migration execution.

## Operator workflow — NOT executed, approval required

**STOP before provisioning:** explicit operator approval is required to create
the cluster, roles and database or start PostgreSQL. The following are example
commands for an operator after approval, NOT commands an agent ran. Use an
already installed, verified PostgreSQL 16 toolchain; do not use the detected 14.

```sh
LOQI_TEST_POSTGRES_RUN_ID="$(uuidgen | tr '[:upper:]' '[:lower:]')"
LOQI_TEST_POSTGRES_ROOT="/private/tmp/loqi-pg-${LOQI_TEST_POSTGRES_RUN_ID}"
LOQI_TEST_POSTGRES_BIN="/opt/homebrew/opt/postgresql@16/bin"
mkdir -m 700 "$LOQI_TEST_POSTGRES_ROOT"
mkdir -m 700 "$LOQI_TEST_POSTGRES_ROOT/socket"
"$LOQI_TEST_POSTGRES_BIN/initdb" -D "$LOQI_TEST_POSTGRES_ROOT/data" \
  --username=loqi_pg_admin --auth-local=trust --auth-host=reject
"$LOQI_TEST_POSTGRES_BIN/pg_ctl" -D "$LOQI_TEST_POSTGRES_ROOT/data" \
  -l "$LOQI_TEST_POSTGRES_ROOT/server.log" \
  -o "-k $LOQI_TEST_POSTGRES_ROOT/socket -p 55432 -c listen_addresses=''" start
```

Private directories isolate local trust authentication. Never expose this
cluster over TCP, reuse an existing server/data directory, or use real data.

Before provisioning, create `target.json` INSIDE that root using `target.example.json` as the format;
replace example root/database/run UUID with this fresh run's values. Set mode
0600. Do not copy production configuration. Then review and approve exact bytes:

```sh
export LOQI_TEST_POSTGRES_ENABLED=1
export LOQI_TEST_POSTGRES_TARGET="$LOQI_TEST_POSTGRES_ROOT/target.json"
export LOQI_TEST_POSTGRES_APPROVED_TARGET_SHA256="$(shasum -a 256 "$LOQI_TEST_POSTGRES_TARGET" | cut -d ' ' -f 1)"
cd backend
.venv/bin/python -m tests.postgres.cli plan
```

After separately reviewing the target and `tests/postgres/provision_roles.sql`,
approve provisioning explicitly. Do not use a direct psql provisioning path:

```sh
export LOQI_TEST_POSTGRES_APPROVED_PROVISION_TARGET_SHA256='<separately reviewed target digest>'
export LOQI_TEST_POSTGRES_APPROVED_PROVISION_SQL_SHA256='<reviewed provision_roles.sql digest>'
.venv/bin/python -m tests.postgres.cli provision
```

The guarded entry point checks approval before connecting, then probes the
`postgres` database in the exact private PostgreSQL 16 cluster as `loqi_pg_admin`.
It requires the expected data directory, Unix transport, no TCP listener, the
expected administrator/owner, and no existing non-template databases or fixture
roles before any role creation. Database authorization remains a later distinct
step: normal connections require the created database's owner and run comment.
Provisioning is not fully transactional: roles commit together, CREATE DATABASE
and its comment are separate. Any failure leaves an observable partial state;
there is no automatic retry, reset or cleanup. Inspect manually before proceeding.

The `plan` command is offline. **STOP before approving migration execution.**
Only after reviewing its manifest digest:

```sh
export LOQI_TEST_POSTGRES_APPROVED_MANIFEST_SHA256='<reviewed manifest digest>'
# Choose ONE on a fresh database: bootstrap test OR CLI prerequisites.
.venv/bin/python -m pytest tests/postgres/test_bootstrap.py -q
# Alternative: .venv/bin/python -m tests.postgres.cli prerequisites
```

**STOP again before Migration 048.** Separate approval of its reviewed exact
file digest is required, even when prerequisites have been approved:

```sh
export LOQI_TEST_POSTGRES_APPROVE_048_SHA256='<reviewed 048 digest from migrations.json>'
.venv/bin/python -m tests.postgres.cli migration-048
.venv/bin/python -m pytest tests/postgres/test_campaign_contract.py -q
.venv/bin/python -m tests.postgres.cli capture --output /private/tmp/loqi-local-schema.json
```

Do not use xdist or parallel suite execution; the harness enforces this. Race tests
use their own independent connections and bounded thread pools deliberately.
They synchronize with barriers/events and observed PostgreSQL blocking PIDs,
not arbitrary sleep-only assertions. Statements/locks/idle transactions have
bounded timeouts. Do not set hosted/external integration opt-ins for these tests.

## Cleanup and reruns

### Batch 2 catalog preflight and exclusive ownership

Freshness is checked with metadata-only PostgreSQL catalogs, not selected table
counts. The namespace allowlist is exactly `pg_catalog`, `pg_toast`,
`information_schema`, and an empty `public`. All relation kinds outside the three
system schemas are rejected (including foreign tables, indexes, sequences,
views and composite types), as are non-system routines/types, user namespaces,
foreign servers/wrappers, event triggers (even disabled), non-plpgsql extensions,
nonstandard languages, publications/subscriptions, large objects, default ACLs,
global/current-database role configuration (metadata identities only),
user-created casts, custom access methods/tablespaces and non-system operators,
collations, conversions, operator classes/families and text-search objects.
`plpgsql`, the four standard languages, standard access methods and the two
standard tablespaces are explicit bootstrap exceptions. Subscription connection
strings, application rows and role password catalogs are never queried.
Catalog permission errors propagate; no unavailable catalog becomes "fresh".

This is not a cryptographic fingerprint of PostgreSQL's built-in catalogs,
cluster configuration, OS files or template databases. Built-in objects in the
system schemas are trusted under the private freshly initialized cluster model;
it does not defend against a malicious cluster administrator. The normal owner
cannot change those catalogs. Baseline/permission compatibility of these queries
still needs approved PostgreSQL 16 execution.

Before installing 048, `catalog_contract.py` checks the bounded repository
contract: ordinary `public` tables owned by `loqi_test_owner`, no unexpected RLS,
non-internal triggers or rewrite rules; required types/nullability; canonical
primary keys and immediate valid/ready btree unique indexes (including soft-delete
predicates); validated, non-deferrable FKs to the correct canonical tables with
the expected delete actions; canonical CHECK expressions; defaults relied upon
by RPC inserts; and effective service-role/schema privileges. Referenced identity,
global lead and company primary keys are checked without validating their full
application schema. Additional required output columns without defaults fail.
Performance-only indexes and unrelated application tables are not certified.
Finite CHECK/default rendering is deliberately strict: equivalent reordered or
differently rendered definitions may require review rather than being accepted.

`memberships` from 025 is the organization access authority. It has text actor/
organization IDs, an unconditional user/organization unique index and no FKs;
the 006 `workspace_members` projection is structurally checked but does not grant
048 access. Workspace status policy and Migration 048 SQL are unchanged.

Role checks use PostgreSQL 16 `pg_has_role(..., 'SET')`, not `MEMBER`. Each restricted
role must have NOLOGIN, NOINHERIT, NOREPLICATION and none of the privileged flags.
The execution owner must have LOGIN, INHERIT, CONNECT, inherited settings access
and NOREPLICATION, in addition to the existing server/privilege checks. Actual
PostgreSQL 16 membership-option semantics still require database execution.

Pytest acquires one session lease before any marked local test fixture; CLI
provisioning, prerequisite/048 execution and capture acquire the same lease.
Every native connection, including test worker connections, requires that lease.
An atomic exclusive creation of private `suite-owner.json` in the approved root
arbitrates independent suites. It binds the run, database, approval, PID and random
nonce; marker bytes/inode/ownership are checked during connection validation and
normal release. Xdist controller options and worker environment are rejected,
as is threaded pytest test-case setup.
Threads deliberately used for a single test's concurrency share the session
lease; no parallel test-case execution is supported.

Normal exit removes only that lease's exact marker. Failed marker writes, abrupt
termination, malformed/dead-PID markers or replacements fail closed; no PID-based
automatic reclamation occurs. **Operator intervention is required** to verify
the exact run, absence of surviving clients/workers and retained data before
removing a stale marker or deciding to use a new disposable target. No automatic
database cleanup, reset or provisioning recovery is added. This cooperative
local-process mechanism does not protect against an operator deleting an active
marker or malicious same-user filesystem races. A normal assertion failure
releases its own lease but retains committed synthetic rows as before.

Offline tests validate catalog-result handling and local marker arbitration,
not real catalog permissions, SQL parsing, lock behavior, PostgREST/RLS or
production equivalence. An authoritative production snapshot remains required
for any production-schema comparison. Subsequent comparison changes are
described in the Batch 3/4 section below.

### Batch 1 approval and connection guarantees

Final-audit correction: the native connection boundary now rejects any database
or user other than the exact approved disposable database/owner pair. The sole
administrative exception is the fixed `loqi_pg_admin`/`postgres` pair, requiring
the separately approved captured provisioning source. Both branches verify the
server before yielding; ordinary connections also verify role privileges there,
not only in the higher-level wrapper. Direct callers cannot bypass these probes
or supply a conninfo string through the database argument. See
`LOCAL_POSTGRES_HARNESS_FINAL_AUDIT.md` for the final audit and offline results.

Migration approval captures one immutable manifest and all source bytes,
including 048. Execution rechecks file bytes and approval before its first SQL
and immediately before each migration, then executes only captured bytes.
048 still requires its own exact-byte approval and cannot enter prerequisites.
A concurrent edit after the last check cannot substitute executable SQL: the
captured bytes, not files reloaded later, are used. Checks do not provide an
atomic filesystem revocation protocol.

Native driver creation is serialized by a harness-owned lock. Every independent
connection rejects inherited `PG*`, uses fixed local connection arguments, and
revalidates configuration/approval immediately after connection creation and
again after server verification before yielding. Rejection closes the connection
without exposing it. The same boundary is used by guarded provisioning.

Environment policy: run these operator commands in a dedicated process without
unrelated environment-mutating threads. The lock coordinates harness calls only;
Python cannot atomically isolate process-global libpq environment from arbitrary
other threads. A concurrent `PG*` change still present after connect is rejected;
a transient change restored during the native call cannot be proven absent by
these checks. Thus no atomicity against arbitrary same-process writers, nor proof
that such a transient native connection never occurred, is claimed. Use a clean
dedicated process; do not embed this harness in a multi-purpose application worker.

Failed fixture setup rolls back atomically. Every test has deterministic
synthetic IDs derived from run UUID and test node ID. Successful committed rows
are retained for inspection; a second full run requires a NEW disposable database.
No shared-identity DELETE, cascading identity cleanup or table-wide reset exists.
Fault-injection triggers/functions use unique names and exact-name cleanup;
failed cleanup propagates and leaves artifacts for inspection, never broadens.

The harness does not stop PostgreSQL, drop databases or delete volumes/directories.
The operator must separately approve disposal of the exact run-owned cluster
after checking its target identity and closing connections. No generic `rm` or
DROP command is provided. Ambiguous ownership means leave it untouched.

## Schema snapshots and comparison

`schema.py` captures only catalog metadata for the declared relevant table set:
columns/types/defaults/nullability, PK/FK/CHECK definitions, unique/partial indexes,
triggers, the exact 048 function signature/owner/ACL, roles/memberships,
schema/table/column grants, relevant global/public default ACLs, RLS flags/policies
and extensions. It uses one REPEATABLE READ, READ ONLY transaction after the
connection's identity probes have rolled back. Catalog permission failures
propagate; unavailable metadata is not an empty collection. Migration history
remains UNKNOWN unless supplied independently. No application rows or password
catalogs are queried. Cross-database/catalog behavior and concurrent-DDL handling
still require real PG16 execution; this does not lock DDL or create a snapshot
across independent databases or external migration ledgers.

An operator-supplied production snapshot must use the same format/scope:
`format: 2`, `provenance: {kind: operator_supplied, schema_only: true}`,
`scope` equal to `schema.TABLES`, and `sections` keys/entry fields from
`schema.FIELDS`. Entries are `{id: <stable catalog identity>, definition: {...}}`.
Use `null` for unknown sections, not an empty array. Optional migration-history
entries contain version/checksum metadata ONLY, never SQL/application rows.

Version 1 exports must be recaptured/reviewed: they lack the new privilege and
constraint metadata and are rejected rather than silently upgraded. Capture
includes only `create_workspace_campaign_once(uuid,uuid,text,text,jsonb,uuid[],jsonb)`;
048 uses builtin routines and needs no other public function body. Unrelated
function bodies are excluded. Raw SQL-bearing definitions, defaults, predicates,
policy expressions and function configuration are replaced with SHA-256 of their
JSON encoding, using `fingerprint_literals`. This preserves exact change detection,
not readable semantic inspection. Apply the same fingerprinting to a reviewed
operator export before comparison. Hashes of low-entropy literals may be guessed;
these artifacts remain private. Identifier/ACL strings still need operator review.
Automated secret detection or complete sanitization is NOT claimed. A trusted
operator must review source metadata confidentially and attest the supplied
snapshot's authority; this tool does not authenticate that attestation.
No production export
command or production connection is implemented. Local capture is exclusive
creation, mode 0600, not printed to console.

Offline comparison (no connection/opt-in needed):

```sh
cd backend
.venv/bin/python -m tests.postgres.schema \
  /path/to/sanitized-operator-production.json /private/tmp/loqi-local-schema.json
```

Definitions/owners/ACLs are compared exactly; differences are not silently
normalized away. Report exposes identities and difference categories, not SQL
definitions. Unknown sections produce `incomplete`, never equality. `metadata_equal`
reports only known exact equality; overall status additionally requires bounded
contract completeness. Empty/equally incomplete snapshots cannot pass. Missing
tables, typed columns, PK/FK/CHECK/unique-index shapes, role/schema/table/column
ACL entries and the 048 function are reported separately from unknown sections.
This is presence/type coverage, NOT strict local prerequisite validation:
`verify_campaign_prerequisites` remains authoritative for local FK actions,
CHECK/default semantics, partial-index predicates and effective privileges.
Production equivalence always remains unverified by this CLI. Local role
owners and grants intentionally differ from Supabase; review these differences,
do not erase them. Repository manifest = expected inputs; local capture = observed
local metadata; supplied snapshot = operator-reported production facts. No current
snapshot exists, and even metadata equality does not prove runtime equivalence.

## Prepared tests and limitations

Prepared database tests cover fresh prerequisite bootstrap, canonical attachments,
same-key replay/conflict, two-connection key races, attachment/strategy fault
rollback, both membership UPDATE/DELETE races, lead mutation blocking, earlier
revocation, foreign/deleted/missing/duplicate/null inputs, real role grants,
response-loss/post-commit read-error recovery, and explicit supplied strategy with
zero attachments. They have NOT been executed against PostgreSQL.

Post-commit read failure is a SQL read-error simulation, not full Python HTTP
hydration. Existing offline campaign tests cover Python hydration and auxiliary
effects; direct SQL does not establish PostgREST error/JSON transport or Supabase
RLS. Durable job recovery needs a separately reviewed legacy baseline/profile.
Inline lead normalization outside the RPC, physical receipt deletion, and
non-exactly-once auxiliary effects remain existing limitations. No application
business behavior or production migration history is changed here.

## Validation executed in this implementation

Only inspected offline suites were run; every new native-client test uses a
mock, and hosted/provider/local database opt-ins were explicitly disabled:

```sh
LOQI_RUN_DB_INTEGRATION=0 LOQI_RUN_EXTERNAL_INTEGRATION=0 \
LOQI_TEST_POSTGRES_ENABLED=0 REDIS_URL= backend/.venv/bin/python -m pytest \
  backend/tests/test_local_postgres_safety.py \
  backend/tests/test_supabase_test_safety.py \
  backend/tests/test_campaign_creation_contract.py \
  backend/tests/test_campaign_creation_safety.py \
  backend/tests/test_campaign_attachment_rollback.py \
  backend/tests/test_campaign_execution_safety.py -q
```

Result: **170 passed, 0 failed, 0 skipped**. The existing Starlette/httpx
deprecation warning remains. Backend compileall and `git diff --check` passed.
Database integration files were not executed, even in default-skipped mode.
No frontend files or dependencies changed; frontend checks were not applicable.

Batch 1 audit remediation reran the same six offline suites with the new
approval-race, captured-plan and provisioning regressions: **183 passed,
0 failed, 0 skipped**, one existing Starlette/httpx deprecation warning.
Harness Python compilation and `git diff --check` passed. All native connection
factories in these harness tests are mocked; no provisioning entry point was
executed against a real server. Provisioning and real SQL guarantees remain
unverified until separately approved disposable-database execution. Remaining
audit batches (schema completeness, privilege checks, parallel isolation and
comparison coverage) are not resolved by this batch.

### Batch 2 offline validation

After the catalog, role and ownership remediation, the exact final command was:

```sh
LOQI_RUN_DB_INTEGRATION=0 LOQI_RUN_EXTERNAL_INTEGRATION=0 \
LOQI_TEST_POSTGRES_ENABLED=0 REDIS_URL= backend/.venv/bin/python -m pytest \
  backend/tests/test_local_postgres_safety.py \
  backend/tests/test_local_postgres_preflight.py \
  backend/tests/test_supabase_test_safety.py \
  backend/tests/test_campaign_creation_contract.py \
  backend/tests/test_campaign_creation_safety.py \
  backend/tests/test_campaign_attachment_rollback.py \
  backend/tests/test_campaign_execution_safety.py -q
```

**309 passed, 0 failed, 0 skipped**, with one pre-existing Starlette/httpx
deprecation warning. `backend/.venv/bin/python -m compileall -q backend` and
`git diff --check` passed. The first focused attempt found an obsolete repeated
revocation mock path after adding the owner-attribute query; revalidation directly
after the server probe now rejects revocation before additional queries, and
the unchanged revocation assertion passes in the final suite.

New tests cover unexpected catalog categories, bounded structural/default/CHECK
validation, every required service privilege, SET/role attributes, marker races,
stale/missing/replaced/partial markers, independent-process-state denial, worker
lease sharing, xdist/threaded-case rejection and direct native-path ownership.
Native clients are mocks; filesystem lease checks operate only on test-owned
temporary files. No database-backed suite was run, no real SQL was executed, no
server was installed/provisioned/started/stopped and no production access occurred.
The prerequisite SQL, Migration 048, manifest checksums and hosted safeguards
remain unchanged. Batch 3 has not been started.

## Batches 3 and 4 remediation (offline implementation only)

Batch 3 extends snapshot metadata and comparison as described above. Unavailable
migration history remains `null`; an empty ledger is never manufactured. Ordinary
offline tests use fake catalogs/native factories, not a database. Catalog snapshots
do not prove effective RLS/PostgREST access or production authority.

Batch 4's prepared same-key test holds the first RPC transaction open, obtains
the second independent backend PID, observes `pg_blocking_pids` plus a matching
ungranted/granted advisory lock in `pg_locks`, and only then releases the first
transaction. It checks replay/conflict, exact campaign/link counts and unchanged
campaign name. Both row-lock orderings are prepared for UPDATE/DELETE revocation,
lead soft-delete/movement and workspace/discovery soft-delete; lead physical
deletion is also tested when deletion wins first. Bounded connection/statement/
lock and observer deadlines remain in force. Creation-first mutation outcomes
and mutation-first authorization outcomes are checked separately.

Prepared tests distinguish failure after the first attachment (a fault trigger
requires an already inserted link), strategy insertion rollback, post-commit
read failure, discarded response recovery and repeated-link uniqueness. PUBLIC
EXECUTE and default-function ACL behavior have real-catalog tests, with temporary
privilege/function changes rolled back. Committed fault triggers remain exact-name
cleaned. No parallel suites/workers are enabled. Physical workspace/discovery
deletion cascades are not exercised here; soft-delete races are covered and
hard-delete semantics remain a separately reviewed follow-up.

### Independent bootstrap observations (operator approval required)

After separately approving/provisioning **two independent fresh targets**, run
the existing bootstrap test in two separate clean processes. Each process needs
its own existing exact target/manifest approvals and suite lease; do NOT swap
targets inside a session. Migration 048 remains unapproved/uninstalled. Set a
distinct absolute output path for each run:

```sh
# Future operator-only commands; NOT executed during implementation.
LOQI_TEST_POSTGRES_BOOTSTRAP_SNAPSHOT=/private/tmp/loqi-bootstrap-a.json \
  .venv/bin/python -m pytest tests/postgres/test_bootstrap.py -q
# In a separately configured/approved process for target B:
LOQI_TEST_POSTGRES_BOOTSTRAP_SNAPSHOT=/private/tmp/loqi-bootstrap-b.json \
  .venv/bin/python -m pytest tests/postgres/test_bootstrap.py -q
.venv/bin/python -m tests.postgres.schema --bootstrap-artifacts \
  /private/tmp/loqi-bootstrap-a.json /private/tmp/loqi-bootstrap-b.json
```

Bootstrap verifies actual bounded prerequisites and exports exclusive mode-0600
observations with distinct run/database identities and the reviewed manifest hash.
Offline comparison requires different runs of the same manifest, compares
observed schemas (not only source hashes) and does not require uninstalled 048.
Unknown migration history still produces `incomplete`/nonzero exit; inspect
`differences`, `missing` and `unknown` separately. Artifacts are not authenticated.
No reproducibility assertion is made until both real bootstraps run and their
known contract metadata agrees.

Existing offline `test_campaign_creation_safety.py` exercises Python service
hydration and activity/timeline/publication/feedback failures using fakes. Replay
recovers the canonical commit but does NOT repair auxiliary effects or guarantee
exactly-once publication. Direct SQL tests remain separate from service/transport
coverage. No real PostgREST, RLS, transport-loss, concurrent-DDL, locking or PG16
privilege behavior is verified here. A prepared independent-DDL test checks
repeatable-read `pg_attribute` visibility on a uniquely named scratch table;
cleanup drops only that table without CASCADE. It has not been executed and does
not by itself certify every `pg_get_*` helper/catalog cache under concurrent DDL.
Production equivalence remains unknown without an authoritative sanitized
snapshot. Batch 5 is not started.

### Batch 3/4 offline validation

All database/provider opt-ins were disabled. The final eight-suite command was:

```sh
LOQI_RUN_DB_INTEGRATION=0 LOQI_RUN_EXTERNAL_INTEGRATION=0 \
LOQI_TEST_POSTGRES_ENABLED=0 REDIS_URL= backend/.venv/bin/python -m pytest \
  backend/tests/test_local_postgres_schema.py \
  backend/tests/test_local_postgres_safety.py \
  backend/tests/test_local_postgres_preflight.py \
  backend/tests/test_supabase_test_safety.py \
  backend/tests/test_campaign_creation_contract.py \
  backend/tests/test_campaign_creation_safety.py \
  backend/tests/test_campaign_attachment_rollback.py \
  backend/tests/test_campaign_execution_safety.py -q
```

| Offline suite | Pass | Fail | Skip |
| --- | ---: | ---: | ---: |
| test_local_postgres_schema | 36 | 0 | 0 |
| test_local_postgres_safety | 76 | 0 | 0 |
| test_local_postgres_preflight | 126 | 0 | 0 |
| test_supabase_test_safety | 25 | 0 | 0 |
| test_campaign_creation_contract | 27 | 0 | 0 |
| test_campaign_creation_safety | 25 | 0 | 0 |
| test_campaign_attachment_rollback | 18 | 0 | 0 |
| test_campaign_execution_safety | 14 | 0 | 0 |
| Total | 347 | 0 | 0 |

The existing Starlette/httpx deprecation warning remains. Initial iterations
exposed two defects in new test doubles (catalog response routing and a fixture
helper argument colliding with the column `identity` field); both were fixed,
not skipped or weakened. Backend compileall and diff-check pass. No database
integration test was collected/executed. No real connection, SQL execution,
provisioning, external request or production access occurred.
