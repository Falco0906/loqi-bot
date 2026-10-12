"""Mock-only local harness tests. Native database connection is always replaced."""
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest

from tests.postgres import harness as h
from tests.postgres import schema
from tests.postgres import catalog_contract as catalog
from tests.postgres.ownership import exclusive_suite


def contract_metadata():
    """Synthetic catalog rows; not evidence that the SQL executes in PostgreSQL."""
    data = {name: {} for name in catalog.QUERIES}
    for table, columns in catalog.COLUMNS.items():
        data["relations"][table] = {"kind": "r", "owner": h.OWNER, "rls": False, "force_rls": False}
        data["hooks"][table] = {"trigger_count": 0, "rule_count": 0}
        for name, (kind, not_null) in columns.items():
            data["columns"][table + "." + name] = {"type": kind, "not_null": not_null,
                "default": "gen_random_uuid()" if name == "id" else None, "identity": "", "generated": ""}
        for name, value in catalog.DEFAULTS.get(table, {}).items():
            data["columns"].setdefault(table + "." + name, {"type": "text", "not_null": True,
                "identity": "", "generated": ""})["default"] = value
        def index(columns, predicate=None, primary=False):
            return {"columns": list(columns), "predicate": predicate, "primary": primary,
                "unique": True, "valid": True, "ready": True, "immediate": True,
                "method": "btree", "nulls_not_distinct": False}
        data["indexes"][table] = [index(["id"], primary=True)] + [
            index(columns, "(deleted_at IS NULL)" if table in catalog.PARTIAL_TABLES else None)
            for columns in catalog.UNIQUE_INDEXES.get(table, [])]
        data["foreign_keys"][table] = [{"columns": [col], "referenced_schema": "public", "referenced_table": ref,
            "referenced_columns": [refcol], "delete": deletion, "update": "a", "match": "s", "validated": True,
            "deferrable": False} for col, ref, refcol, deletion in catalog.FOREIGN_KEYS.get(table, [])]
        data["checks"][table] = [{"expression": "(version >= 1)" if values is None else
            "(" + col + " = ANY (ARRAY[" + ", ".join("'" + v + "'::text" for v in values) + "]))",
            "validated": True, "no_inherit": False} for col, values in catalog.CHECKS.get(table, {}).items()]
        data["privileges"][table] = {key: True for key in catalog.PRIVILEGES.get(table, [])}
    return data


@pytest.fixture
def configured_target(tmp_path, monkeypatch):
    run = str(uuid4())
    root = tmp_path / ("loqi-pg-" + run)
    root.mkdir(mode=0o700)
    for name in ("socket", "data"):
        (root / name).mkdir(mode=0o700)
    version = root / "data" / "PG_VERSION"
    version.write_text("16\n")
    version.chmod(0o600)
    target = root / "target.json"
    target.write_text(json.dumps({"version": 1, "postgres_major": 16, "root": str(root),
        "database": "loqi_test_" + run.replace("-", ""), "port": 55432, "run_id": run, "owner": h.OWNER}))
    target.chmod(0o600)
    for key in list(__import__("os").environ):
        if key.startswith("PG") or key.startswith("LOQI_TEST_POSTGRES_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("LOQI_TEST_POSTGRES_ENABLED", "1")
    monkeypatch.setenv("LOQI_TEST_POSTGRES_TARGET", str(target))
    monkeypatch.setenv("LOQI_TEST_POSTGRES_APPROVED_TARGET_SHA256", h.sha256(target.read_bytes()))
    return h.authorize_local_target()


@pytest.fixture
def approved(configured_target):
    with exclusive_suite(configured_target):
        yield configured_target


@pytest.fixture
def native(monkeypatch, approved):
    import psycopg2
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value = Mock()
    cursor.fetchone.return_value = (approved.database, h.OWNER, 160010, None, h.OWNER,
        "loqi-disposable:" + approved.run_id, str(approved.root / "data"), "", False, False, False, False)
    roles = [(role, False, False, False, False, True, False, False, False) for role in sorted(h.ROLES)]
    metadata = contract_metadata()
    def fetchone():
        statement = cursor.execute.call_args.args[0]
        if "SELECT rolcanlogin" in statement:
            return (True, True, False, True, True)
        if "has_schema_privilege" in statement:
            return (True, True)
        return (approved.database, h.OWNER, 160010, None, h.OWNER,
            "loqi-disposable:" + approved.run_id, str(approved.root / "data"), "", False, False, False, False)
    cursor.fetchone.side_effect = fetchone
    def fetchall():
        statement = cursor.execute.call_args.args[0]
        if statement in catalog.QUERIES.values():
            name = next(name for name, query in catalog.QUERIES.items() if query == statement)
            return [(key, entry) for key, definition in metadata[name].items()
                for entry in (definition if isinstance(definition, list) else [definition])]
        return [] if "WITH RECURSIVE" in statement or statement == catalog.FRESH_QUERY else roles
    cursor.fetchall.side_effect = fetchall
    factory = Mock(return_value=connection)
    monkeypatch.setattr(psycopg2, "connect", factory)
    return SimpleNamespace(connection=connection, cursor=cursor, factory=factory, metadata=metadata,
        default_fetchone=fetchone, default_fetchall=fetchall)


def test_missing_config_does_not_fall_back_or_construct_client(monkeypatch):
    import psycopg2
    factory = Mock(side_effect=AssertionError("No connection permitted"))
    monkeypatch.setattr(psycopg2, "connect", factory)
    monkeypatch.setenv("DATABASE_URL", "untrusted-application-secret")
    with pytest.raises(h.UnsafeLocalPostgres):
        h.authorize_local_target({})
    factory.assert_not_called()


def test_environment_change_does_not_disable_process_guard(approved, native, monkeypatch):
    monkeypatch.delenv("LOQI_TEST_MODE", raising=False)
    with h.connect_local(approved):
        pass
    assert native.factory.call_count == 1
    kwargs = native.factory.call_args.kwargs
    assert kwargs["host"] == str(approved.root / "socket")
    assert kwargs["passfile"] == "/dev/null" and kwargs["password"] == ""
    assert "dsn" not in kwargs and "service" not in kwargs


@pytest.mark.parametrize("key", ["PGHOST", "PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS", "PGPASSWORD", "PGDATABASE"])
def test_libpq_inheritance_is_rejected_before_connect(approved, native, monkeypatch, key):
    monkeypatch.setenv(key, "secret-value-not-to-log")
    with pytest.raises(h.UnsafeLocalPostgres) as error:
        with h.connect_local(approved):
            pass
    assert "secret-value-not-to-log" not in str(error.value)
    native.factory.assert_not_called()


@pytest.mark.parametrize("field,value", [("root", "https://production.supabase.co"),
    ("root", "127.0.0.1"), ("port", 5432), ("database", "postgres"),
    ("owner", "postgres"), ("postgres_major", 14), ("extra", "credential")])
def test_approved_bytes_cannot_authorize_invalid_target(approved, native, monkeypatch, field, value):
    data = json.loads(approved.target_file.read_text())
    data[field] = value
    approved.target_file.write_text(json.dumps(data))
    monkeypatch.setenv("LOQI_TEST_POSTGRES_APPROVED_TARGET_SHA256", h.sha256(approved.target_file.read_bytes()))
    with pytest.raises(h.UnsafeLocalPostgres):
        h.authorize_local_target()
    native.factory.assert_not_called()


def test_changed_or_forged_capability_cannot_connect(approved, native):
    for target in (replace(approved, database="other"), replace(approved, _seal=object())):
        with pytest.raises(h.UnsafeLocalPostgres):
            with h.connect_local(target):
                pass
    native.factory.assert_not_called()


def test_every_independent_connection_revalidates_target(approved, native):
    with h.connect_local(approved):
        pass
    approved.target_file.write_text("{}")
    with pytest.raises(h.UnsafeLocalPostgres):
        with h.connect_local(approved):
            pass
    assert native.factory.call_count == 1


@pytest.mark.parametrize("index,value", [(0, "production"), (1, "postgres"), (2, 140000),
    (3, "127.0.0.1"), (4, "another-owner"), (5, "another-run"), (6, "/production/data"),
    (7, "*"), (8, True), (9, True), (10, True), (11, True)])
def test_server_probe_mismatch_closes_connection_before_any_writes(approved, native, index, value):
    row = list(native.cursor.fetchone.return_value)
    row[index] = value
    native.cursor.fetchone.return_value = tuple(row)
    native.cursor.fetchone.side_effect = None
    with pytest.raises(h.UnsafeLocalPostgres):
        with h.connect_local(approved):
            pytest.fail("Unverified connection yielded")
    native.connection.close.assert_called_once()
    assert native.cursor.execute.call_count == 1
    assert native.cursor.execute.call_args.args[0].startswith("SELECT")


def test_private_target_and_socket_required(approved, native):
    (approved.root / "socket").chmod(0o755)
    with pytest.raises(h.UnsafeLocalPostgres):
        with h.connect_local(approved):
            pass
    native.factory.assert_not_called()


def test_local_capability_cannot_authorize_supabase(approved, monkeypatch):
    from services.platform.test_runtime import create_supabase_client, UnsafeTestDatabaseConfiguration
    import supabase
    factory = Mock()
    monkeypatch.setattr(supabase, "create_client", factory)
    with pytest.raises(UnsafeTestDatabaseConfiguration):
        create_supabase_client("https://unknown.supabase.co", "sentinel", authorization=approved)
    factory.assert_not_called()


def test_manifest_is_canonical_and_048_has_separate_gate(approved, native, monkeypatch):
    plan = h.migration_plan()
    assert [name[:3] for name, _ in plan] == ["004", "006", "007", "008", "014", "016", "025", "048"]
    with pytest.raises(h.UnsafeLocalPostgres):
        h.apply_prerequisites(approved)
    monkeypatch.setenv("LOQI_TEST_POSTGRES_APPROVED_MANIFEST_SHA256", h.sha256(h.MANIFEST.read_bytes()))
    with pytest.raises(h.UnsafeLocalPostgres):
        h.apply_048(approved)
    native.factory.assert_not_called()


def test_changed_migration_bytes_fail_offline(monkeypatch, tmp_path):
    monkeypatch.setattr(h, "MIGRATIONS", tmp_path)
    (tmp_path / "004_identity_platform.sql").write_text("changed")
    with pytest.raises(h.UnsafeLocalPostgres, match="review and repin"):
        h.migration_plan()


def test_nonfresh_schema_refuses_bootstrap_without_reset(approved, native, monkeypatch):
    monkeypatch.setenv("LOQI_TEST_POSTGRES_APPROVED_MANIFEST_SHA256", h.sha256(h.MANIFEST.read_bytes()))
    original = native.default_fetchall
    native.cursor.fetchall.side_effect = lambda: [("relation", "public.preexisting")] if native.cursor.execute.call_args.args[0] == catalog.FRESH_QUERY else original()
    with pytest.raises(h.UnsafeLocalPostgres, match="fresh"):
        h.apply_prerequisites(approved)
    assert not any("create table" in call.args[0].lower() for call in native.cursor.execute.call_args_list)
    native.connection.commit.assert_not_called()


def test_role_privilege_mismatch_refuses_migrations(approved, native, monkeypatch):
    monkeypatch.setenv("LOQI_TEST_POSTGRES_APPROVED_MANIFEST_SHA256", h.sha256(h.MANIFEST.read_bytes()))
    native.cursor.fetchall.side_effect = None
    native.cursor.fetchall.return_value = [(role, True, False, False, False, True, False, False, False) for role in sorted(h.ROLES)]
    with pytest.raises(h.UnsafeLocalPostgres, match="restricted roles"):
        h.apply_prerequisites(approved)
    native.connection.commit.assert_not_called()


def test_owner_cannot_inherit_unapproved_privileged_roles(approved, native):
    roles = [(role, False, False, False, False, True, False, False, False) for role in sorted(h.ROLES)]
    native.cursor.fetchall.side_effect = lambda: [("pg_write_server_files",)] if "WITH RECURSIVE" in native.cursor.execute.call_args.args[0] else roles
    with pytest.raises(h.UnsafeLocalPostgres, match="Unexpected owner"):
        with h.connect_local(approved):
            pytest.fail("Unapproved inherited role")
    native.connection.close.assert_called_once()


def test_migration_error_rolls_back_without_cleanup(approved, native, monkeypatch):
    monkeypatch.setenv("LOQI_TEST_POSTGRES_APPROVED_MANIFEST_SHA256", h.sha256(h.MANIFEST.read_bytes()))
    failure = RuntimeError("synthetic migration failure")
    def execute(sql, *_args):
        if "create table" in sql.lower():
            raise failure
    native.cursor.execute.side_effect = execute
    with pytest.raises(RuntimeError) as caught:
        h.apply_prerequisites(approved)
    assert caught.value is failure
    native.connection.commit.assert_not_called()
    native.connection.close.assert_called_once()
    assert not any("delete from" in call.args[0].lower() for call in native.cursor.execute.call_args_list)


def test_mocked_prerequisites_exclude_048_and_commit_once(approved, native, monkeypatch):
    monkeypatch.setenv("LOQI_TEST_POSTGRES_APPROVED_MANIFEST_SHA256", h.sha256(h.MANIFEST.read_bytes()))
    h.apply_prerequisites(approved)
    native.connection.commit.assert_called_once()
    statements = [call.args[0] for call in native.cursor.execute.call_args_list]
    assert not any("create_workspace_campaign_once" in statement for statement in statements)
    for _, source in h.migration_plan()[:-1]:
        assert source in statements


def test_048_mocked_execution_requires_exact_separate_approval(approved, native, monkeypatch):
    monkeypatch.setenv("LOQI_TEST_POSTGRES_APPROVED_MANIFEST_SHA256", h.sha256(h.MANIFEST.read_bytes()))
    monkeypatch.setenv("LOQI_TEST_POSTGRES_APPROVE_048_SHA256", "wrong")
    with pytest.raises(h.UnsafeLocalPostgres): h.apply_048(approved)
    native.factory.assert_not_called()
    digest = json.loads(h.MANIFEST.read_text())["approval_required"]["sha256"]
    monkeypatch.setenv("LOQI_TEST_POSTGRES_APPROVE_048_SHA256", digest)
    h.apply_048(approved)
    assert native.cursor.execute.call_args.args[0] == h.migration_plan()[-1][1]
    native.connection.commit.assert_called_once()


@pytest.mark.parametrize("missing", ["table", "discovery_column"])
def test_048_refuses_missing_prerequisites_before_migration(approved, native, monkeypatch, missing):
    monkeypatch.setenv("LOQI_TEST_POSTGRES_APPROVED_MANIFEST_SHA256", h.sha256(h.MANIFEST.read_bytes()))
    monkeypatch.setenv("LOQI_TEST_POSTGRES_APPROVE_048_SHA256", json.loads(h.MANIFEST.read_text())["approval_required"]["sha256"])
    if missing == "table":
        native.metadata["relations"].pop("campaigns")
    else:
        native.metadata["columns"].pop("campaigns.discovery_id")
    with pytest.raises(h.UnsafeLocalPostgres): h.apply_048(approved)
    assert not any("create_workspace_campaign_once" in call.args[0] for call in native.cursor.execute.call_args_list)
    native.connection.commit.assert_not_called()


def test_manifest_cannot_move_048_into_prerequisites(tmp_path, monkeypatch):
    plan = json.loads(h.MANIFEST.read_text())
    plan["prerequisites"].append(plan["approval_required"])
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(plan))
    monkeypatch.setattr(h, "MANIFEST", manifest)
    with pytest.raises(h.UnsafeLocalPostgres, match="separately gated"):
        h.migration_plan()


def snapshot(kind="operator_supplied"):
    return {"format": 2, "provenance": {"kind": kind, "schema_only": True},
        "scope": list(schema.TABLES), "sections": {name: [] for name in schema.FIELDS}}


def test_comparison_is_offline_and_never_claims_production_equivalence(monkeypatch):
    monkeypatch.setattr(schema, "connect_local", Mock(side_effect=AssertionError("No connection")))
    a, b = snapshot(), snapshot("local_capture")
    assert schema.compare_snapshots(a, b)["status"] == "incomplete"
    assert schema.compare_snapshots(a, b)["production_equivalence_verified"] is False


def test_capture_uses_catalog_queries_only_and_read_only_transaction(approved, native):
    native.cursor.fetchall.side_effect = lambda: (
        [(role, False, False, False, False, True, False, False, False) for role in sorted(h.ROLES)]
        if "pg_has_role" in native.cursor.execute.call_args.args[0] else [])
    result = schema.capture_local(approved)
    assert result["sections"]["migration_history"] is None
    statements = [call.args[0] for call in native.cursor.execute.call_args_list]
    assert "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY" in statements
    assert all(statement.lstrip().startswith(("SELECT", "WITH", "SET TRANSACTION")) for statement in statements)
    native.connection.commit.assert_not_called()


@pytest.mark.parametrize("section", list(schema.FIELDS))
def test_unknown_metadata_is_not_equality(section):
    a, b = snapshot(), snapshot()
    a["sections"][section] = None
    report = schema.compare_snapshots(a, b)
    assert report["status"] == "incomplete" and report["unknown_sections"] == [section]


def test_changed_grants_and_definitions_are_not_hidden():
    a, b = snapshot(), snapshot()
    a["sections"]["grants"] = [{"id": "campaigns", "definition": {"acl": "owner-only"}}]
    b["sections"]["grants"] = [{"id": "campaigns", "definition": {"acl": "public-write"}}]
    report = schema.compare_snapshots(a, b)
    assert report["differences"] == [{"section": "grants", "id": "campaigns", "kind": "changed"}]


def test_snapshot_rejects_rows_credentials_and_duplicate_entries():
    a = snapshot()
    a["rows"] = []
    with pytest.raises(ValueError): schema.validate_snapshot(a)
    a = snapshot()
    a["sections"]["grants"] = [{"id": "campaigns", "definition": {"acl": None, "password": "secret"}}]
    with pytest.raises(ValueError): schema.validate_snapshot(a)
    a = snapshot()
    a["sections"]["grants"] = [{"id": "campaigns", "definition": {"acl": None}}] * 2
    with pytest.raises(ValueError): schema.validate_snapshot(a)


def test_local_tests_skip_by_default_without_opening_connection(monkeypatch):
    from tests import conftest
    item = Mock()
    item.get_closest_marker.side_effect = lambda name: True if name == "requires_local_postgres" else None
    monkeypatch.delenv("LOQI_TEST_POSTGRES_ENABLED", raising=False)
    conftest.pytest_collection_modifyitems(None, [item])
    assert item.add_marker.call_args.args[0].name == "skip"


@pytest.mark.parametrize("change", ["revoke", "replace", "same_bytes_replacement", "libpq"])
def test_connection_establishment_revalidates_before_any_sql(approved, native, monkeypatch, change):
    def connecting(**kwargs):
        if change == "revoke":
            monkeypatch.delenv("LOQI_TEST_POSTGRES_APPROVED_TARGET_SHA256")
        elif change == "replace":
            approved.target_file.write_text("{}")
        elif change == "same_bytes_replacement":
            replacement = approved.root / "replacement.json"
            replacement.write_bytes(approved.target_file.read_bytes())
            replacement.chmod(0o600)
            replacement.replace(approved.target_file)
        else:
            monkeypatch.setenv("PGHOSTADDR", "unapproved")
        return native.connection
    native.factory.side_effect = connecting
    with pytest.raises(h.UnsafeLocalPostgres):
        with h.connect_local(approved):
            pytest.fail("Revoked connection yielded")
    native.cursor.execute.assert_not_called()
    native.connection.close.assert_called_once()


@pytest.mark.parametrize("change", ["manifest", "prerequisite", "048"])
def test_captured_migration_plan_rejects_changes_before_sql(approved, native, monkeypatch, tmp_path, change):
    from contextlib import contextmanager
    original = h.capture_migration_plan()
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(original.manifest_bytes)
    for path, contents in original.sources:
        (tmp_path / path.name).write_bytes(contents)
    monkeypatch.setattr(h, "MANIFEST", manifest)
    monkeypatch.setattr(h, "MIGRATIONS", tmp_path)
    monkeypatch.setenv("LOQI_TEST_POSTGRES_APPROVED_MANIFEST_SHA256", h.sha256(original.manifest_bytes))
    @contextmanager
    def delayed_connection(_target):
        changed = manifest if change == "manifest" else tmp_path / original.sources[-1 if change == "048" else 0][0].name
        changed.write_bytes(changed.read_bytes() + b"\n-- replacement")
        yield native.connection
    monkeypatch.setattr(h, "connect_local", delayed_connection)
    with pytest.raises(h.UnsafeLocalPostgres, match="changed or was revoked"):
        h.apply_prerequisites(approved)
    native.cursor.execute.assert_not_called()
    native.factory.assert_not_called()


def test_provisioning_requires_separate_approval_before_connect(approved, native):
    from tests.postgres.provision import provision_cluster
    with pytest.raises(h.UnsafeLocalPostgres, match="Separate exact"):
        provision_cluster()
    native.factory.assert_not_called()


@pytest.mark.parametrize("mismatch", ["server", "revoked", "source"])
def test_guarded_provisioning_rejects_before_ddl(approved, native, monkeypatch, tmp_path, mismatch):
    from tests.postgres import provision as p
    source = tmp_path / "roles.sql"
    source.write_bytes(p.SOURCE.read_bytes())
    monkeypatch.setattr(p, "SOURCE", source)
    monkeypatch.setenv("LOQI_TEST_POSTGRES_APPROVED_PROVISION_TARGET_SHA256", approved.digest)
    monkeypatch.setenv("LOQI_TEST_POSTGRES_APPROVED_PROVISION_SQL_SHA256", h.sha256(source.read_bytes()))
    row = ("postgres", "loqi_pg_admin", 160010, None, str(approved.root / "data"), "", "loqi_pg_admin", True, 0, 0)
    def probe():
        if mismatch == "revoked":
            monkeypatch.delenv("LOQI_TEST_POSTGRES_APPROVED_PROVISION_TARGET_SHA256")
        if mismatch == "source":
            source.write_bytes(b"changed")
        return ("unexpected", *row[1:]) if mismatch == "server" else row
    native.cursor.fetchone.side_effect = probe
    with pytest.raises(h.UnsafeLocalPostgres):
        p.provision_cluster()
    assert native.cursor.execute.call_count == 1
    assert native.cursor.execute.call_args.args[0].startswith("SELECT")
    native.connection.commit.assert_not_called()


def test_guarded_provisioning_uses_captured_source_after_identity_probe(approved, native, monkeypatch):
    from tests.postgres import provision as p
    source = p.SOURCE.read_bytes()
    monkeypatch.setenv("LOQI_TEST_POSTGRES_APPROVED_PROVISION_TARGET_SHA256", approved.digest)
    monkeypatch.setenv("LOQI_TEST_POSTGRES_APPROVED_PROVISION_SQL_SHA256", h.sha256(source))
    native.cursor.fetchone.return_value = ("postgres", "loqi_pg_admin", 160010, None,
        str(approved.root / "data"), "", "loqi_pg_admin", True, 0, 0)
    native.cursor.fetchone.side_effect = None
    p.provision_cluster()
    assert native.factory.call_args.kwargs["dbname"] == "postgres"
    assert native.factory.call_args.kwargs["user"] == "loqi_pg_admin"
    assert native.cursor.execute.call_args_list[1].args[0] == source.decode()
    assert native.cursor.execute.call_count == 4
    native.connection.commit.assert_called_once()


def test_approval_revoked_during_server_probe_is_not_yielded(approved, native, monkeypatch):
    row = native.cursor.fetchone.return_value
    def probe():
        monkeypatch.delenv("LOQI_TEST_POSTGRES_APPROVED_TARGET_SHA256")
        return row
    native.cursor.fetchone.side_effect = probe
    with pytest.raises(h.UnsafeLocalPostgres):
        with h.connect_local(approved):
            pytest.fail("Revoked connection yielded")
    native.connection.close.assert_called_once()


@pytest.mark.parametrize("user,database", [
    (h.OWNER, "postgres"), ("loqi_pg_admin", "postgres"),
    (h.OWNER, "host=unapproved dbname=other"),
    (h.OWNER, "postgresql://unapproved/other"), ("unapproved", None),
])
def test_native_boundary_rejects_arbitrary_targets_before_driver(approved, native, user, database):
    with pytest.raises(h.UnsafeLocalPostgres, match="exact approved"):
        with h.native_connection(approved, user=user, database=database):
            pytest.fail("Unapproved native target yielded")
    native.factory.assert_not_called()


def test_native_boundary_checks_server_before_yield(approved, native):
    native.cursor.fetchone.side_effect = None
    native.cursor.fetchone.return_value = ("other", *native.cursor.fetchone.return_value[1:])
    with pytest.raises(h.UnsafeLocalPostgres, match="server identity"):
        with h.native_connection(approved, user=h.OWNER, database=approved.database):
            pytest.fail("Unverified server yielded")
    native.connection.close.assert_called_once()
    native.connection.commit.assert_not_called()


def test_native_admin_requires_exact_provisioning_approval(approved, native):
    from tests.postgres import provision as p
    with pytest.raises(h.UnsafeLocalPostgres, match="Separate exact"):
        with h.native_connection(approved, user="loqi_pg_admin", database="postgres",
                provision_source=p.SOURCE.read_bytes()):
            pytest.fail("Unapproved administrative connection yielded")
    native.factory.assert_not_called()


def test_native_boundary_checks_role_privileges_before_yield(approved, native):
    native.cursor.fetchall.side_effect = None
    native.cursor.fetchall.return_value = [
        (role, True, False, False, False, True, False, False, False) for role in sorted(h.ROLES)
    ]
    with pytest.raises(h.UnsafeLocalPostgres, match="restricted roles"):
        with h.native_connection(approved, user=h.OWNER, database=approved.database):
            pytest.fail("Unverified role privileges yielded")
    native.connection.close.assert_called_once()
    native.connection.commit.assert_not_called()


def test_native_admin_checks_cluster_before_yield(approved, native, monkeypatch):
    from tests.postgres import provision as p
    source = p.SOURCE.read_bytes()
    monkeypatch.setenv("LOQI_TEST_POSTGRES_APPROVED_PROVISION_TARGET_SHA256", approved.digest)
    monkeypatch.setenv("LOQI_TEST_POSTGRES_APPROVED_PROVISION_SQL_SHA256", h.sha256(source))
    native.cursor.fetchone.side_effect = None
    native.cursor.fetchone.return_value = ("postgres", "loqi_pg_admin", 160010, None,
        str(approved.root / "data"), "", "loqi_pg_admin", True, 1, 0)
    with pytest.raises(h.UnsafeLocalPostgres, match="fresh approved"):
        with h.native_connection(approved, user="loqi_pg_admin", database="postgres", provision_source=source):
            pytest.fail("Non-fresh administrative connection yielded")
    native.connection.close.assert_called_once()
    assert native.cursor.execute.call_count == 1
    native.connection.commit.assert_not_called()
