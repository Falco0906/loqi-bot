"""Offline catalog/ownership regressions. No native client is ever permitted."""
from concurrent.futures import ThreadPoolExecutor
import threading
from unittest.mock import Mock

import pytest

from tests.postgres import catalog_contract as c, harness as h, ownership as o
from tests.test_local_postgres_safety import approved, configured_target, native, contract_metadata


@pytest.fixture(autouse=True)
def forbid_native_connection(monkeypatch):
    import psycopg2
    monkeypatch.setattr(psycopg2, "connect", Mock(side_effect=AssertionError("Offline test cannot open a database")))


@pytest.mark.parametrize("category", ["relation", "foreign_server", "foreign_wrapper", "event_trigger", "schema",
    "routine", "type", "extension", "publication", "subscription", "large_object", "default_acl", "database_role_setting", "cast",
    "access_method", "tablespace", "operator", "collation", "conversion", "operator_class", "operator_family",
    "text_search_config", "text_search_dictionary", "text_search_parser", "text_search_template"])
def test_nonfresh_categories_fail_closed(category):
    cursor = Mock()
    cursor.fetchall.return_value = [(category, "synthetic")]
    with pytest.raises(h.UnsafeLocalPostgres, match=category):
        c.verify_fresh_database(cursor)


def test_fresh_system_only_catalog_passes():
    cursor = Mock()
    cursor.fetchall.return_value = []
    c.verify_fresh_database(cursor)
    query, parameters = cursor.execute.call_args.args
    assert query == c.FRESH_QUERY
    assert query.count("%s") == len(parameters)
    assert all(set(value) == set(c.SYSTEM_SCHEMAS) for value in parameters)
    # Foreign relations are not excluded by a relkind allowlist.
    assert "relkind IN" not in query
    assert "pg_foreign_server" in query and "pg_event_trigger" in query


def test_complete_synthetic_contract_passes_without_sql():
    c.verify_contract_metadata(contract_metadata())


@pytest.mark.parametrize("table", list(c.COLUMNS))
def test_missing_required_relations_fail(table):
    data = contract_metadata()
    del data["relations"][table]
    with pytest.raises(h.UnsafeLocalPostgres, match=table):
        c.verify_contract_metadata(data)


@pytest.mark.parametrize("change", ["view", "foreign_table", "partitioned", "owner", "rls", "nullable_id",
    "wrong_type", "generated", "missing_fk", "wrong_fk", "unvalidated_fk", "deferrable_fk",
    "missing_primary", "missing_unique", "wrong_predicate", "invalid_index", "wrong_delete", "missing_check", "wrong_check", "unvalidated_check",
    "missing_privilege", "missing_default", "wrong_default", "unexpected_required_column", "trigger", "rule"])
def test_structural_mismatch_rejected(change):
    data = contract_metadata()
    if change in {"view", "foreign_table", "partitioned"}:
        data["relations"]["campaigns"]["kind"] = {"view": "v", "foreign_table": "f", "partitioned": "p"}[change]
    elif change == "owner": data["relations"]["campaigns"]["owner"] = "other"
    elif change == "rls": data["relations"]["campaigns"]["rls"] = True
    elif change == "nullable_id": data["columns"]["campaigns.id"]["not_null"] = False
    elif change == "wrong_type": data["columns"]["memberships.user_id"]["type"] = "uuid"
    elif change == "generated": data["columns"]["campaigns.name"]["generated"] = "s"
    elif change == "missing_fk": data["foreign_keys"]["campaign_leads"] = []
    elif change == "wrong_fk": data["foreign_keys"]["campaign_leads"][1]["referenced_table"] = "leads"
    elif change == "unvalidated_fk": data["foreign_keys"]["campaign_leads"][1]["validated"] = False
    elif change == "deferrable_fk": data["foreign_keys"]["campaign_leads"][1]["deferrable"] = True
    elif change == "wrong_delete": data["foreign_keys"]["campaigns"][1]["delete"] = "c"
    elif change == "missing_primary": data["indexes"]["campaigns"] = []
    elif change == "missing_unique": data["indexes"]["campaign_leads"].pop()
    elif change == "wrong_predicate": data["indexes"]["campaign_leads"][-1]["predicate"] = "deleted_at IS NOT NULL"
    elif change == "invalid_index": data["indexes"]["campaign_leads"][-1]["valid"] = False
    elif change == "missing_check": data["checks"]["campaigns"] = []
    elif change == "wrong_check": data["checks"]["campaigns"][0]["expression"] += " OR true"
    elif change == "unvalidated_check": data["checks"]["campaigns"][0]["validated"] = False
    elif change == "missing_privilege": data["privileges"]["workspace_leads"]["UPDATE"] = False
    elif change == "missing_default": data["columns"]["strategies.version"]["default"] = None
    elif change == "wrong_default": data["columns"]["strategies.version"]["default"] = "0"
    elif change == "unexpected_required_column": data["columns"]["campaigns.extra"] = {
        "type": "text", "not_null": True, "default": None, "identity": "", "generated": ""}
    elif change == "trigger": data["hooks"]["campaigns"]["trigger_count"] = 1
    elif change == "rule": data["hooks"]["campaigns"]["rule_count"] = 1
    with pytest.raises(h.UnsafeLocalPostgres, match="prerequisite mismatch"):
        c.verify_contract_metadata(data)


@pytest.mark.parametrize("table,privilege", [(table, privilege) for table, privileges in c.PRIVILEGES.items() for privilege in privileges])
def test_each_required_service_privilege_is_checked(table, privilege):
    data = contract_metadata()
    data["privileges"][table][privilege] = False
    with pytest.raises(h.UnsafeLocalPostgres, match=privilege): c.verify_contract_metadata(data)


@pytest.mark.parametrize("column", ["workspace_id", "lead_id"])
def test_canonical_link_identity_columns_are_required(column):
    data = contract_metadata()
    del data["columns"]["workspace_leads." + column]
    with pytest.raises(h.UnsafeLocalPostgres, match=column): c.verify_contract_metadata(data)


@pytest.mark.parametrize("role", h.ROLES)
@pytest.mark.parametrize("position,value", [(5, False), (6, True), (7, True), (8, True)])
def test_restricted_role_set_and_attributes(role, position, value):
    cursor = Mock()
    rows = [(name, False, False, False, False, True, False, False, False) for name in sorted(h.ROLES)]
    altered = list(rows[sorted(h.ROLES).index(role)])
    altered[position] = value
    rows[sorted(h.ROLES).index(role)] = tuple(altered)
    cursor.fetchall.return_value = rows
    with pytest.raises(h.UnsafeLocalPostgres, match="restricted roles"):
        h.verify_roles(cursor)
    assert "'SET'" in cursor.execute.call_args.args[0]


def test_membership_is_not_used_as_set_permission():
    cursor = Mock()
    cursor.fetchall.side_effect = [[(name, False, False, False, False, True, False, False, False) for name in sorted(h.ROLES)], []]
    cursor.fetchone.return_value = (True, True, False, True, True)
    h.verify_roles(cursor)
    assert "pg_has_role(session_user, oid, 'SET')" in cursor.execute.call_args_list[0].args[0]


@pytest.mark.parametrize("index,value", [(0, False), (1, False), (2, True), (3, False), (4, False)])
def test_execution_owner_required_attributes(index, value):
    cursor = Mock()
    cursor.fetchall.side_effect = [[(name, False, False, False, False, True, False, False, False) for name in sorted(h.ROLES)], []]
    row = [True, True, False, True, True]
    row[index] = value
    cursor.fetchone.return_value = tuple(row)
    with pytest.raises(h.UnsafeLocalPostgres, match="Execution owner"): h.verify_roles(cursor)


def test_suite_lease_has_atomic_single_winner(configured_target):
    barrier = threading.Barrier(2)
    attempting = threading.Barrier(2)
    def compete():
        barrier.wait(timeout=3)
        try:
            with o.exclusive_suite(configured_target):
                attempting.wait(timeout=3)
                return "owned"
        except h.UnsafeLocalPostgres:
            attempting.wait(timeout=3)
            return "rejected"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: compete(), range(2)))
    assert sorted(results) == ["owned", "rejected"]
    assert not (configured_target.root / o.MARKER).exists()


@pytest.mark.parametrize("contents", [b"", b"not-json", b'{"pid": -1}', b'{"pid": 99999999}'])
def test_stale_or_ambiguous_marker_is_never_reclaimed(configured_target, contents):
    marker = configured_target.root / o.MARKER
    marker.write_bytes(contents)
    with pytest.raises(h.UnsafeLocalPostgres, match="operator review"):
        with o.exclusive_suite(configured_target): pytest.fail("Stale ownership reclaimed")
    assert marker.read_bytes() == contents


def test_existing_marker_blocks_independent_process_state(approved, monkeypatch):
    # Model a second process (no shared _ACTIVE); the filesystem still denies it.
    with monkeypatch.context() as context:
        context.setattr(o, "_ACTIVE", None)
        with pytest.raises(h.UnsafeLocalPostgres, match="operator review"):
            with o.exclusive_suite(approved): pytest.fail("Independent suite entered")


def test_marker_replacement_is_not_deleted(configured_target):
    with pytest.raises(h.UnsafeLocalPostgres, match="marker changed"):
        with o.exclusive_suite(configured_target):
            marker = configured_target.root / o.MARKER
            marker.write_bytes(b"changed")
    assert marker.read_bytes() == b"changed"


def test_missing_marker_is_ambiguous_not_recreated(configured_target):
    marker = configured_target.root / o.MARKER
    with pytest.raises(h.UnsafeLocalPostgres, match="missing or unreadable"):
        with o.exclusive_suite(configured_target):
            marker.unlink()  # Simulate external removal of this test's marker.
    assert not marker.exists()


def test_nested_suites_rejected_and_worker_connections_share_lease(approved):
    o.require_suite_ownership(approved)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(o.require_suite_ownership, approved).result(timeout=3)
    with pytest.raises(h.UnsafeLocalPostgres, match="already owns"):
        with o.exclusive_suite(approved): pass


@pytest.mark.parametrize("name", ["PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_XDIST_TESTRUNUID"])
def test_xdist_rejected_before_marker_creation(configured_target, monkeypatch, name):
    monkeypatch.setenv(name, "synthetic")
    with pytest.raises(h.UnsafeLocalPostgres, match="Parallel"):
        with o.exclusive_suite(configured_target): pass
    assert not (configured_target.root / o.MARKER).exists()


def test_no_lease_no_connection(configured_target):
    import psycopg2
    with pytest.raises(h.UnsafeLocalPostgres, match="suite lease"):
        with h.connect_local(configured_target): pass
    psycopg2.connect.assert_not_called()


def test_catalog_queries_only_return_metadata():
    assert all(query.startswith("SELECT") for query in c.QUERIES.values())
    assert all("FROM pg_" in query for query in c.QUERIES.values())
    assert all("subconninfo" not in query for query in [c.FRESH_QUERY, *c.QUERIES.values()])


@pytest.mark.parametrize("category", ["relation", "foreign_server", "event_trigger"])
def test_nonfresh_bootstrap_never_executes_captured_migrations(approved, native, monkeypatch, category):
    monkeypatch.setenv("LOQI_TEST_POSTGRES_APPROVED_MANIFEST_SHA256", h.sha256(h.MANIFEST.read_bytes()))
    original = native.default_fetchall
    native.cursor.fetchall.side_effect = lambda: [(category, "synthetic")] if native.cursor.execute.call_args.args[0] == c.FRESH_QUERY else original()
    with pytest.raises(h.UnsafeLocalPostgres, match=category): h.apply_prerequisites(approved)
    statements = [call.args[0] for call in native.cursor.execute.call_args_list]
    assert all(statement.lstrip().startswith(("SELECT", "WITH")) for statement in statements)
    native.connection.commit.assert_not_called()


@pytest.mark.parametrize("privileges", [(False, True), (True, False)])
def test_schema_privileges_reject_048_before_execution(approved, native, monkeypatch, privileges):
    monkeypatch.setenv("LOQI_TEST_POSTGRES_APPROVED_MANIFEST_SHA256", h.sha256(h.MANIFEST.read_bytes()))
    monkeypatch.setenv("LOQI_TEST_POSTGRES_APPROVE_048_SHA256", h.sha256(h.capture_migration_plan().sources[-1][1]))
    original = native.default_fetchone
    native.cursor.fetchone.side_effect = lambda: privileges if "has_schema_privilege" in native.cursor.execute.call_args.args[0] else original()
    with pytest.raises(h.UnsafeLocalPostgres, match="schema"): h.apply_048(approved)
    assert not any("create_workspace_campaign_once" in call.args[0] for call in native.cursor.execute.call_args_list)
    native.connection.commit.assert_not_called()


def test_partial_lease_setup_retains_marker_without_database_calls(configured_target, monkeypatch):
    def failed_sync(_descriptor): raise OSError("synthetic write failure")
    monkeypatch.setattr(o.os, "fsync", failed_sync)
    with pytest.raises(OSError, match="synthetic"):
        with o.exclusive_suite(configured_target): pytest.fail("Incomplete lease entered")
    assert (configured_target.root / o.MARKER).exists()
    assert o._ACTIVE is None


def test_other_process_cannot_reuse_lease_capability(approved, monkeypatch):
    with monkeypatch.context() as context:
        context.setattr(o.os, "getpid", lambda: -1)
        with pytest.raises(h.UnsafeLocalPostgres, match="suite lease"):
            o.require_suite_ownership(approved)


def test_direct_native_path_requires_suite_ownership(configured_target):
    import psycopg2
    with pytest.raises(h.UnsafeLocalPostgres, match="suite lease"):
        with h.native_connection(configured_target, user=h.OWNER, database=configured_target.database): pass
    psycopg2.connect.assert_not_called()


@pytest.mark.parametrize("replacement", ["'Planning'", "'plan ning'", "'plan(ning)'"])
def test_check_normalization_never_changes_string_literals(replacement):
    data = contract_metadata()
    data["checks"]["campaigns"][0]["expression"] = data["checks"]["campaigns"][0]["expression"].replace("'planning'", replacement)
    with pytest.raises(h.UnsafeLocalPostgres, match="CHECK"):
        c.verify_contract_metadata(data)


def test_parallel_pytest_controller_is_rejected_before_fixtures(monkeypatch):
    from tests.postgres import conftest
    monkeypatch.setenv("LOQI_TEST_POSTGRES_ENABLED", "1")
    config = Mock()
    config.option.numprocesses = 2
    with pytest.raises(pytest.UsageError, match="parallel"):
        conftest.pytest_configure(config)


def test_threaded_case_setup_is_rejected_before_database_fixture():
    from tests.postgres import conftest
    request = Mock()
    request.node.get_closest_marker.return_value = True
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(conftest._own_local_database.__wrapped__, request)
        with pytest.raises(pytest.UsageError, match="Parallel"):
            future.result(timeout=3)
    request.getfixturevalue.assert_not_called()
