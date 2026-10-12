# Backend test gates

Ordinary tests run offline by default. The shared pytest bootstrap activates a
process-owned guard before application imports. Changing `LOQI_TEST_MODE`
afterward cannot restore access to application credentials. Offline tests also
reject socket connections and skip production startup work and migrations.

Run the offline release gate:

```sh
python -m pytest tests -m "not integration and not requires_db"
```

Database tests are skipped unless explicitly enabled. Before enabling them,
provision a disposable, isolated test project and apply its reviewed migrations
as a separate operator action. Set all four dedicated settings:

- `LOQI_TEST_SUPABASE_URL`
- `LOQI_TEST_SUPABASE_KEY`
- `LOQI_TEST_SUPABASE_PROJECT_REF`
- `LOQI_ALLOWED_TEST_SUPABASE_PROJECT_REFS` (explicit comma-separated allowlist)

The URL must match an allowlisted project. The known production project is
rejected even if allowlisted. Missing settings never use application `.env`
database credentials. Do not allowlist a customer or production project.

Only then run database tests:

```sh
LOQI_RUN_DB_INTEGRATION=1 python -m pytest tests -m requires_db
```

The validated SDK client is installed per database test and removed afterward.
The identity fixture generates its own fresh UUID and tracks it before insert,
so an ambiguous write can be cleaned by its exact known ID. Cleanup accepts no
arbitrary table/ID registration. It supports only fixture-created identities;
other integration data requires a reviewed ownership-specific fixture or manual
cleanup of the disposable project. A failed teardown remains an error. Never
broaden cleanup by user, workspace, or table. If an untracked write's ID is
unknown, manual cleanup is required.

External integration tests are independently opt-in. Their dedicated environment
must use test provider accounts; individual provider fixtures must supply mocks
or reviewed test-only credentials. The marker itself grants no access:

```sh
LOQI_RUN_EXTERNAL_INTEGRATION=1 LOQI_EXTERNAL_INTEGRATION_ENV=dedicated \
  python -m pytest tests -m integration
```

Tests outside `backend/tests` must use the same bootstrap before application
imports. The guard prevents accidental bypass through ordinary environment
changes and application APIs; it does not defend against arbitrary malicious
Python code that modifies internals in the same process.
