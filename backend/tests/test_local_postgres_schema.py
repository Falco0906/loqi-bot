"""Pure metadata tests; native connection creation is forbidden in this suite."""
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest

from tests.postgres import schema
from tests.postgres.catalog_contract import COLUMNS, CHECKS, FOREIGN_KEYS, UNIQUE_INDEXES
from tests.test_local_postgres_safety import approved, configured_target, native


@pytest.fixture(autouse=True)
def no_database(monkeypatch):
    import psycopg2
    monkeypatch.setattr(psycopg2, "connect", Mock(side_effect=AssertionError("Offline schema suite")))


def complete_snapshot():
    """Synthetic catalog values prove comparator behavior, not PostgreSQL semantics."""
    result = {"format": 2, "scope": list(schema.TABLES),
        "provenance": {"kind": "operator_supplied", "schema_only": True},
        "sections": {name: [] for name in schema.FIELDS}}
    def add(section, row_id, **values):
        definition = dict.fromkeys(schema.FIELDS[section])
        for field in schema.KNOWN_FIELDS.get(section, []):
            definition[field] = False if field in {"nullable", "validated", "deferrable", "deferred", "unique", "primary", "valid",
                "rls", "force_rls", "security_definer", "superuser", "create_db", "create_role", "bypass_rls", "login", "inherit", "replication"} else "synthetic"
        definition.update(values)
        result["sections"][section].append({"id": row_id, "definition": definition})
    for table, columns in COLUMNS.items():
        add("tables", table, owner="loqi_test_owner", kind="r", rls=False, force_rls=False)
        add("grants", table, acl=None)
        for name, (kind, required) in columns.items():
            add("columns", table + "." + name, type=kind, nullable=not required, position=1, identity="", generated="")
            add("column_grants", table + "." + name, acl=None)
        add("constraints", table + ".pk", kind="p", columns=["id"])
        for column, target, _, _ in FOREIGN_KEYS.get(table, []):
            add("constraints", table + ".fk_" + column, kind="f", columns=[column], referenced_table=target)
        for column in CHECKS.get(table, {}):
            add("constraints", table + ".check_" + column, kind="c", columns=[column])
        for number, columns in enumerate(UNIQUE_INDEXES.get(table, [])):
            add("indexes", table + ".unique_" + str(number), columns=list(columns), unique=True, valid=True)
    for role in ("anon", "authenticated", "service_role", "loqi_test_owner"):
        add("roles", role, connection_limit=-1)
    add("schema_grants", "public", owner="loqi_test_owner", acl=None)
    add("functions", schema.FUNCTION, owner="loqi_test_owner")
    return result


def test_complete_equal_metadata_is_not_production_or_prerequisite_proof():
    a = complete_snapshot()
    report = schema.compare_snapshots(a, deepcopy(a))
    assert report["status"] == "metadata_equal"
    assert report["contract_completeness"][0]["complete"]
    assert report["contract_completeness"][0]["local_prerequisite_validation"] == "not_established_by_snapshot"
    assert not report["production_equivalence_verified"]


@pytest.mark.parametrize("section,identity", [
    ("tables", "campaigns"), ("columns", "campaigns.workspace_id"),
    ("constraints", "campaign_leads.fk_lead_id"), ("constraints", "campaigns.pk"),
    ("constraints", "campaigns.check_status"), ("indexes", "campaign_leads.unique_0"),
    ("roles", "service_role"), ("column_grants", "campaigns.workspace_id"),
    ("grants", "campaigns"), ("functions", schema.FUNCTION), ("schema_grants", "public")])
def test_equally_missing_required_objects_are_not_equivalence(section, identity):
    a = complete_snapshot()
    a["sections"][section] = [r for r in a["sections"][section] if r["id"] != identity]
    report = schema.compare_snapshots(a, deepcopy(a))
    assert report["metadata_equal"] is True
    assert report["status"] == "incomplete"
    assert report["contract_completeness"][0]["missing"]


def test_empty_snapshots_fail_completeness():
    a = complete_snapshot()
    a["sections"] = {name: [] for name in schema.FIELDS}
    assert schema.compare_snapshots(a, a)["status"] == "incomplete"


@pytest.mark.parametrize("section", ["grants", "column_grants", "default_grants",
    "roles", "role_memberships", "schema_grants", "functions", "migration_history"])
def test_unknown_metadata_never_becomes_empty_or_equal(section):
    a, b = complete_snapshot(), complete_snapshot()
    a["sections"][section] = None
    report = schema.compare_snapshots(a, b)
    assert report["status"] == "incomplete"
    assert section in report["unknown_sections"]


@pytest.mark.parametrize("section", ["grants", "column_grants", "default_grants"])
def test_privilege_changes_are_reported_without_exporting_acl(section):
    a, b = complete_snapshot(), complete_snapshot()
    b["sections"][section].append({"id": "synthetic", "definition": {"acl": "service_role=r/owner"}})
    report = schema.compare_snapshots(a, b)
    assert report["status"] == "different"
    assert {"section": section, "id": "synthetic", "kind": "missing_left"} in report["differences"]
    assert "service_role=r/owner" not in json.dumps(report)


def test_wrong_column_shape_is_not_complete():
    a = complete_snapshot()
    row = next(r for r in a["sections"]["columns"] if r["id"] == "campaigns.workspace_id")
    row["definition"]["type"] = "text"
    assert not schema.contract_completeness(a)["complete"]


def test_unknown_role_attribute_is_not_known_metadata_equality():
    a = complete_snapshot()
    a["sections"]["roles"][0]["definition"]["login"] = None
    report = schema.compare_snapshots(a, deepcopy(a))
    assert report["status"] == "incomplete" and not report["metadata_equal"]
    assert "roles:anon.login" in report["contract_completeness"][0]["unknown_fields"]


def test_unknown_owner_is_reported_instead_of_crashing():
    a = complete_snapshot()
    a["sections"]["tables"][0]["definition"]["owner"] = None
    report = schema.compare_snapshots(a, deepcopy(a))
    assert report["status"] == "incomplete"
    assert report["contract_completeness"][0]["unknown_fields"]


def test_production_completeness_does_not_require_a_fictional_local_owner():
    a = complete_snapshot()
    for section in ("tables", "functions", "schema_grants"):
        for row in a["sections"][section]:
            row["definition"]["owner"] = "synthetic_production_owner"
    next(r for r in a["sections"]["roles"] if r["id"] == "loqi_test_owner")["id"] = "synthetic_production_owner"
    assert schema.contract_completeness(a)["complete"]


def test_function_execute_acl_change_remains_visible():
    a, b = complete_snapshot(), complete_snapshot()
    b["sections"]["functions"][0]["definition"]["acl"] = "{=X/owner}"
    assert schema.compare_snapshots(a, b)["differences"] == [
        {"section": "functions", "id": schema.FUNCTION, "kind": "changed"}]


def test_unknown_migration_checksum_is_not_a_verified_ledger():
    a = complete_snapshot()
    a["sections"]["migration_history"] = [{"id": "048", "definition": {"version": "048", "checksum": None}}]
    assert schema.compare_snapshots(a, deepcopy(a))["status"] == "incomplete"


def test_sensitive_literals_are_fingerprinted_not_exported():
    a = complete_snapshot()
    literal = "synthetic-private-literal"
    a["sections"]["functions"][0]["definition"].update(definition=literal, configuration=[literal])
    a["sections"]["columns"][0]["definition"]["default"] = literal
    schema.fingerprint_literals(a["sections"])
    assert literal not in json.dumps(a)
    assert a["sections"]["functions"][0]["definition"]["definition"].startswith("sha256:")


def test_unrelated_supplied_function_is_rejected():
    a = complete_snapshot()
    a["sections"]["functions"][0]["id"] = "unrelated_function()"
    with pytest.raises(ValueError, match="bounded campaign"):
        schema.validate_snapshot(a)


def test_capture_is_one_repeatable_read_snapshot_and_never_exports_unrelated_functions(approved, native):
    function_query = schema.QUERIES["functions"]
    native.cursor.fetchall.side_effect = lambda: (
        [(role, False, False, False, False, True, False, False, False) for role in sorted(("anon", "authenticated", "service_role"))]
        if "pg_has_role" in native.cursor.execute.call_args.args[0] else
        [(schema.FUNCTION, {"definition": "synthetic-secret", "owner": "loqi_test_owner",
            "security_definer": False, "configuration": ["search_path=public"], "acl": None})]
        if native.cursor.execute.call_args.args[0] == function_query else [])
    result = schema.capture_local(approved)
    queries = [c.args[0] for c in native.cursor.execute.call_args_list]
    start = queries.index("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
    assert all(q.lstrip().startswith(("SELECT", "WITH RECURSIVE")) for q in queries[start + 1:])
    assert "to_regprocedure(" in function_query and schema.FUNCTION in function_query
    assert [r["id"] for r in result["sections"]["functions"]] == [schema.FUNCTION]
    assert "synthetic-secret" not in json.dumps(result)
    assert result["sections"]["migration_history"] is None
    native.connection.commit.assert_not_called()


def test_catalog_permission_failure_propagates_not_unknown_empty(approved, native):
    native.cursor.fetchall.side_effect = lambda: (
        [(role, False, False, False, False, True, False, False, False) for role in sorted(("anon", "authenticated", "service_role"))]
        if "pg_has_role" in native.cursor.execute.call_args.args[0] else [])
    original = native.cursor.execute.side_effect
    def execute(statement, *args):
        if statement == schema.QUERIES["default_grants"]:
            raise PermissionError("synthetic catalog access denied")
        if original:
            return original(statement, *args)
    native.cursor.execute.side_effect = execute
    with pytest.raises(PermissionError):
        schema.capture_local(approved)


def bootstrap_artifact(run):
    result = complete_snapshot()
    result["provenance"]["kind"] = "local_capture"
    result["sections"]["functions"] = []  # 048 deliberately not installed.
    result["sections"]["migration_history"] = None
    return {"run_id": run, "database": "loqi_test_" + run.replace("-", ""),
        "manifest_sha256": "a" * 64, "snapshot": result}


def test_bootstrap_comparison_requires_independent_observed_databases():
    a = bootstrap_artifact("00000000-0000-4000-8000-000000000011")
    b = bootstrap_artifact("00000000-0000-4000-8000-000000000012")
    report = schema.compare_bootstrap_artifacts(a, b)
    assert not report["differences"]
    assert report["status"] == "incomplete"  # No invented migration ledger.
    assert report["contract_completeness"][0]["missing"] == []
    with pytest.raises(ValueError, match="independent"):
        schema.compare_bootstrap_artifacts(a, a)
    b["snapshot"]["sections"]["columns"].pop()
    assert schema.compare_bootstrap_artifacts(a, b)["status"] == "different"


def test_bootstrap_source_equality_does_not_prove_schema_equality():
    a = bootstrap_artifact("00000000-0000-4000-8000-000000000011")
    b = bootstrap_artifact("00000000-0000-4000-8000-000000000012")
    b["snapshot"]["sections"] = {name: [] for name in schema.FIELDS}
    assert schema.compare_bootstrap_artifacts(a, b)["differences"]
