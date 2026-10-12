# Local PostgreSQL campaign harness — Batch 5 final audit

## Verdict

**A. READY FOR EXPLICIT LOCAL PROVISIONING APPROVAL**

This means ready for operator review and separate approval of disposable local
provisioning, not permission to provision, execute prerequisites, or execute 048.
No database-backed test was run. Actual PostgreSQL semantics and production
equivalence remain unverified. No authoritative production snapshot was supplied.

## Confirmed blocker and targeted correction

**High — the native connection boundary was weaker than its wrapper.**
`backend/tests/postgres/harness.py:182` previously accepted arbitrary `user` and
`database` arguments and yielded before probing server identity. The normal
`connect_local` wrapper checked identity and role permissions, while provisioning
checked cluster identity separately. A direct native caller could bypass those
checks and request a different database or role. No live reproduction was attempted.

The native boundary now accepts only the approved database/owner pair. Its sole
exception is the fixed provisioning administrator/database pair, gated by the
captured provisioning source and separate exact-byte approval. Server identity,
role checks for ordinary connections, post-connect approval revalidation, and
lease verification occur before exposure. `provision.py:20` owns the read-only
cluster probe; provisioning calls the same guarded native boundary. The existing
probe was moved, not duplicated. No migration, production configuration, hosted
guard, campaign behavior, or application runtime was changed.

Nine new mock-only cases cover arbitrary databases/users, conninfo/URI-shaped
database arguments, wrong server identity, unexpected role privileges, missing
provisioning approval and a nonfresh administrative cluster. Existing revocation,
replacement, immutable migration, provisioning and ownership tests still pass.

## Execution-path audit

| Path | Enforcing code | Static/offline finding |
| --- | --- | --- |
| A. Cluster provisioning | `postgres/cli.py:12`, `provision.py:12`, `provision.py:20`, `provision.py:41`, `harness.py:182` | CLI activates process guard and obtains exclusive lease. Separate target/source approval precedes native creation. Fixed admin pair is verified as PG16, Unix-only, exact data directory, expected admin/owner, no non-template databases or fixture roles before role DDL. Roles commit together; database creation and comment are separate operations. Partial provisioning is observable and requires manual review, not automatic reset/retry. |
| B. Database authorization | `harness.py:101`, `harness.py:115`, `harness.py:152`, `harness.py:162` | Exact private owned nonsymlink target, stable descriptor identity, approved bytes, fixed port, UUID-derived database/root, private socket/data, PG_VERSION16. Server probe checks actual database, session user, owner, run comment, version, transport, data directory, listener and restricted owner flags. No application credential fallback. |
| C. Exclusive ownership | `ownership.py:22`, `ownership.py:39`, `postgres/conftest.py:12` | O_EXCL/O_NOFOLLOW private marker arbitrates cooperative suites; process/run/target/inode/bytes are checked. Existing, corrupted or stale marker fails closed; no dead-PID reclamation. xdist/controller/worker and threaded test-case setup are rejected. Worker connections within the owning process are intentional. |
| D. Native connections | `harness.py:182`, `harness.py:234` | Every harness connection uses the single native factory. Exact allowed arguments, fixed socket/options, blank explicit password, /dev/null passfile, three-second connect limit. PG-prefixed inherited variables are rejected. Approval, server identity and lease are checked before yielding. Mismatch closes the connection. No general DSN/kwargs passthrough. |
| E. Prerequisites | `harness.py:44`, `harness.py:72`, `harness.py:243`, `harness.py:280` | One captured plan includes manifest and all source bytes. Dependency/checksum checks precede connection. Current approval/source bytes are rechecked before each migration; only captured bytes execute. Freshness and roles are checked. Seven prerequisites and explicit local grants commit together. No reset/cleanup on failure. |
| F. Migration 048 | `harness.py:44`, `harness.py:243`, `harness.py:299` | Forbidden in prerequisite list and executed only via separate include-048 approval of exact hash. Strict prerequisite validation precedes its captured SQL. The fixture additionally demands approval before contract-test connections. |
| G. Preflight | `catalog_contract.py:58`, `catalog_contract.py:188`, `catalog_contract.py:233`, `harness.py:256` | Freshness covers documented catalog categories. Structural validation covers relation kinds/owners/RLS/hooks, required column types/nullability/defaults, keys/FK actions, validated CHECKs, canonical partial unique indexes and effective required privileges. PG16 SET permission uses pg_has_role(...,'SET'), not membership alone. Catalog errors propagate. |
| H. Fixtures | `postgres/conftest.py:21`, `postgres/conftest.py:38`, `postgres/conftest.py:47` | Session lease and separate local opt-in; no collection-time connection. Deterministic UUID5 identities derive from run plus test node. Plain INSERTs fail on pre-existing records rather than upserting them. Setup is one transaction. All concurrent test connections use connect_local independently. |
| I. Cleanup/abnormal exit | `ownership.py:39`, `postgres/conftest.py:47`, `test_campaign_contract.py:113`, `test_campaign_contract.py:391` | Committed synthetic rows intentionally remain. No broad row deletion, user-owner cleanup or cascading database reset. Fault/scratch DDL uses unique owned names and exact DROP without CASCADE; temporary grants use rollback. Abrupt death can retain scratch objects/rows/lease marker; operator inspection and a new approved database are required. |
| J. Capture/comparison | `schema.py:146`, `schema.py:175`, `schema.py:193`, `schema.py:210`, `schema.py:272`, `schema.py:297` | Metadata only, bounded table/function scope, single repeatable-read read-only catalog transaction. SQL/default/configuration/policy literals are fingerprinted before export. Table/column/schema/function/default ACLs, owners, role attributes and memberships are captured. Migration history remains unknown. Exact metadata equality, bounded completeness, strict local preflight and production equivalence remain separate. |

References in the table are under `backend/tests/postgres/` unless otherwise
specified. The implementation was inspected, including the prepared SQL tests;
documentation and earlier passing reports were not treated as runtime evidence.

## Migration and schema correctness

All eight current source checksums match the reviewed manifest. Migration 048 is
unchanged in this batch and retains SHA256
`257636cda80141a378b886ef70e900d05c63cc7b13db3f114855a29cb7a335b5`.

The bounded dependency order is:

1. 004 identity_users.
2. 006 organizations/workspaces/workspace_members, referencing identity_users.
3. 007 global and workspace company/lead entities, sources and signals.
4. 008 campaigns, canonical campaign_leads, strategies and drafts.
5. 014 discoveries and related links; campaigns must already exist so its
   guarded campaign discovery column/FK is installed.
6. 016 final campaign status CHECK vocabulary.
7. 025 canonical organization memberships/invitations (TEXT actor/org IDs).
8. 048 separately approved RPC depending on all of the above relevant objects.

PG16 supplies gen_random_uuid; no UUID extension is required by this manifest.
Dedicated owner and Supabase-named restricted roles are local privilege fixtures,
not copies of production roles. PostgreSQL 16 SET ROLE grant semantics and actual
catalog output require execution to confirm. The RPC remains SECURITY INVOKER;
service_role receives explicit local table privileges, not Supabase RLS behavior.

The missing numbered baseline migrations, separate identity-platform definitions,
TEXT-versus-UUID legacy users gap and multi_client_mvp workflow schema are not
silently patched. They are not dependencies of this bounded campaign RPC. Jobs
are intentionally absent; 014 guards its jobs alteration. This manifest is NOT
a full application bootstrap or proof of production schema equivalence.

## Prepared PostgreSQL test quality — not executed

| Contract | Existing prepared test / limits |
| --- | --- |
| Same-key replay and changed-payload race | `test_campaign_contract.py:73` holds first RPC uncommitted, starts second independent connection, observes blocker PID and matching held/waiting advisory-lock identifiers, releases first and checks replay/conflict plus counts and unchanged name. Not just a start barrier. |
| Creation-first revocation/mutation | `:186` holds workspace/membership/lead/discovery transaction locks, observes mutation waiting, then asserts actual committed mutation and prior campaign count. |
| Revocation/mutation-first | `:239` holds UPDATE/DELETE first, observes creation blocked, commits mutation, requires 42501 and no campaign/attachments. Includes lead physical deletion/movement and workspace/discovery soft deletion. Physical workspace/discovery deletion is not covered. |
| Rollback | `:136` and `:144` inject scoped attachment/strategy failures; the second-attachment case demonstrates a prior insert before failure, then requires zero committed campaign/links/strategy and successful retry. |
| Response loss and post-commit failure | `:365` discards a confirmed outcome, then replays with stable identity and no repeated attachment. `:374` tests a separate failed SQL read after commit. These do not simulate PostgREST connection loss. Actual Python hydration/timeline/publication/feedback failures are exercised by the offline creation-safety suite; replay recovers canonical state but does not repair auxiliary effects. |
| Duplicate attachments | `:353` asserts 23505 without changing prior link/count; `:282` rejects duplicate/null/missing/foreign/deleted inputs. |
| Grants/defaults | `:303`, `:328`, `:338` test service execution, anon/auth rejection, absence/detection of PUBLIC execute and explicit revoke of default PUBLIC execute. Temporary privilege/function changes are rolled back. |
| Bootstrap reproducibility | `test_bootstrap.py:15` prepares observations from two independently approved fresh databases. Offline comparison checks distinct identities, same reviewed manifest and observed catalog differences; unknown history prevents an overall verified-equivalence claim. Neither bootstrap was executed. |
| Consistent catalogs during DDL | `:391` prepares an independent ALTER against a uniquely owned scratch table while a reader holds a repeatable-read catalog snapshot, then verifies fresh-reader visibility. This does not establish snapshot consistency of every pg_get_* helper/cache under arbitrary DDL. |

Thread pools are bounded; synchronization uses events and observed lock waiters.
Holder transactions release in finally before pool shutdown. Driver statement,
lock and idle transaction timeouts limit operations. Python Future timeout is not
thread cancellation, and ThreadPoolExecutor shutdown itself waits for workers;
runtime confirmation of those combined bounds remains necessary. Lock/deadlock
tests may fail under real catalog/permission behavior; offline fakes do not prove
their SQL is executable. No order-dependent fixture upsert or broad teardown was
found. Fault-setup interruption may leave owned objects; the harness does not
guess cleanup ownership after a lost commit outcome.

## Residual limitations, not hidden guarantees

- Cooperative isolation assumes a trusted operator and private same-UID files.
  It does not defend against arbitrary Python code, malicious same-UID processes,
  or an operator pointing a previously reviewed path at different filesystem
  content. Approval checks cannot atomically prevent every filesystem/env change.
- The connection lock coordinates harness driver creation only. Unrelated code
  can concurrently mutate os.environ; rejecting PG* before/after is not proof
  that a transient libpq setting was never seen during native establishment.
  Use a clean dedicated process with no concurrent environment mutation. Server
  verification precedes caller SQL, but no transient-connect impossibility is
  claimed. Approval revocation does not cancel already-running SQL/transactions.
- Freshness checks cover explicit metadata categories, not arbitrary corruption,
  server plugins/configuration, every system-catalog modification or malicious
  administrator behavior. An unexpected visible category fails closed.
- Fingerprints conceal raw literals but are not complete sanitization or semantic
  equivalence. Low-entropy strings may be guessed; ACLs/object names still require
  operator confidentiality review. Production provenance is not authenticated.
- Unknown migration history remains unknown, not an empty verified ledger. Two
  matching but incomplete snapshots cannot yield complete-contract status. Strict
  local preflight cannot be inferred from snapshot equality.
- Direct PostgreSQL tests do not establish HTTP/PostgREST transport, Supabase
  policies/RLS, background-job recovery, deployment behavior, actual production
  grants or production equivalence. Those require separate authorized testing.
- No unresolved code blocker was identified after the native-boundary fix.
  Real PG16 execution, full helper catalog consistency, two independent bootstrap
  observations and actual concurrency remain explicitly UNVERIFIED.

## Offline validation

These eight inspected suites were run, using fakes/mocks, temporary local
files and the latched process guard. Native psycopg2 factories are mocked for
all local harness cases; hosted SDK construction is fake. No SQL reached a DB.

```sh
LOQI_RUN_DB_INTEGRATION=0 LOQI_RUN_EXTERNAL_INTEGRATION=0 \
LOQI_TEST_POSTGRES_ENABLED=0 REDIS_URL= backend/.venv/bin/python -m pytest \
  backend/tests/test_local_postgres_safety.py \
  backend/tests/test_local_postgres_preflight.py \
  backend/tests/test_local_postgres_schema.py \
  backend/tests/test_supabase_test_safety.py \
  backend/tests/test_campaign_creation_contract.py \
  backend/tests/test_campaign_creation_safety.py \
  backend/tests/test_campaign_attachment_rollback.py \
  backend/tests/test_campaign_execution_safety.py \
  -q --junitxml=/private/tmp/loqi-harness-batch5-final-offline.xml
```

Final per-suite pass counts: safety **85**, preflight **126**, schema **36**,
hosted safety **25**, creation contract **27**, creation safety **25**, attachment
rollback **18**, execution safety **14**. Total **356 passed, 0 failed, 0 skipped**.
The existing Starlette/httpx deprecation warning remains. Backend compileall and
git diff --check passed. No database-backed suite was collected or executed.

Earlier validation in this audit: the first run passed 355/0/0 before the ninth
new case and native role-check relocation. The next run produced 355 passed,
1 failed, 0 skipped: the existing probe-revocation regression exposed a missing
immediate approval recheck before role probes. That check was restored; the final
run above passed without weakening assertions. This was an audit-fix regression,
not a pre-existing baseline failure.

The additional hosted cleanup/partial-setup suite was inspected and executed
separately with a fake SDK/client only:

```sh
LOQI_RUN_DB_INTEGRATION=0 LOQI_RUN_EXTERNAL_INTEGRATION=0 \
LOQI_TEST_POSTGRES_ENABLED=0 REDIS_URL= backend/.venv/bin/python -m pytest \
  backend/tests/test_shared_test_identity.py -q \
  --junitxml=/private/tmp/loqi-harness-batch5-cleanup-offline.xml
backend/.venv/bin/python -m compileall -q backend
git diff --check
```

Cleanup suite: **12 passed, 0 failed, 0 skipped**. Final validation across nine
suites: **368 passed, 0 failed, 0 skipped**. Compileall and diff-check both exited 0.

Files changed only in this audit: `backend/tests/postgres/harness.py`,
`backend/tests/postgres/provision.py`, `backend/tests/test_local_postgres_safety.py`,
`docs/LOCAL_POSTGRES_CAMPAIGN_TESTING.md`, and this report. Existing uncommitted
application work and earlier remediation remain preserved.

No database connection, database SQL/migration execution, provisioning,
installation, process management, external/production access or credential
inspection occurred. No commit, push or deployment occurred.
