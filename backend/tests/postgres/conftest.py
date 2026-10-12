"""Explicit local-only fixtures; no connection on collection or default runs."""
import os
import threading
from uuid import NAMESPACE_URL, uuid5

import pytest

from tests.postgres.harness import authorize_local_target, connect_local, require_migration_approval
from tests.postgres.ownership import exclusive_suite, reject_parallel_workers


def pytest_configure(config):
    # Controller and worker both reject xdist, before any fixture opens a DB.
    if os.getenv("LOQI_TEST_POSTGRES_ENABLED") == "1":
        reject_parallel_workers()
        if getattr(config.option, "numprocesses", None) not in (None, 0):
            raise pytest.UsageError("Local PostgreSQL suite must run without parallel workers")


@pytest.fixture(scope="session")
def local_suite_target():
    target = authorize_local_target()
    with exclusive_suite(target):
        yield target


@pytest.fixture(autouse=True)
def _own_local_database(request):
    if request.node.get_closest_marker("requires_local_postgres"):
        if threading.current_thread() is not threading.main_thread():
            raise pytest.UsageError("Parallel local PostgreSQL test-case setup is forbidden")
        if os.getenv("LOQI_TEST_POSTGRES_ENABLED") != "1":
            pytest.skip("Disposable local PostgreSQL tests are explicitly opt-in")
        request.getfixturevalue("local_suite_target")


@pytest.fixture
def local_target(local_suite_target):
    if os.getenv("LOQI_TEST_POSTGRES_ENABLED") != "1":
        pytest.skip("Disposable local PostgreSQL tests are explicitly opt-in")
    # Refuse all connections unless the operator also approved the exact SQL.
    require_migration_approval(include_048=True)
    return local_suite_target


@pytest.fixture
def campaign_case(local_target, request):
    """Synthetic, per-case identities; failed setup rolls back, no cascade cleanup.

    Committed test data stays in this run's database for inspection. A rerun must
    use a new disposable database; teardown never broadens cleanup after errors.
    """
    def identity(label):
        return str(uuid5(NAMESPACE_URL, local_target.run_id + request.node.nodeid + label))
    case = {name: identity(name) for name in ("actor", "workspace", "foreign_workspace", "lead",
        "foreign_lead", "global_lead", "foreign_global_lead", "discovery", "foreign_discovery")}
    case["organization"] = "test-org-" + identity("organization")
    case["foreign_organization"] = "test-org-" + identity("foreign-organization")
    case["target"] = local_target
    with connect_local(local_target) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT to_regprocedure('public.create_workspace_campaign_once(uuid,uuid,text,text,jsonb,uuid[],jsonb)')")
        if cursor.fetchone()[0] is None:
            pytest.fail("Operator must install approved Migration 048 before contract tests")
        cursor.execute("INSERT INTO identity_users(id,email) VALUES (%s,%s)",
            (case["actor"], case["actor"] + "@example.invalid"))
        for foreign in (False, True):
            prefix = "foreign_" if foreign else ""
            organization = case[prefix + "organization"]
            cursor.execute("INSERT INTO organizations(id,name,slug) VALUES (%s,%s,%s)", (organization, organization, organization))
            cursor.execute("INSERT INTO workspaces(id,organization_id,name,slug,owner_user_id) VALUES (%s,%s,%s,%s,%s)",
                (case[prefix + "workspace"], organization, "Synthetic test workspace", prefix + "test", case["actor"]))
            cursor.execute("INSERT INTO leads(id,canonical_id,email) VALUES (%s,%s,%s)",
                (case[prefix + "global_lead"], "test:" + case[prefix + "global_lead"], case[prefix + "global_lead"] + "@example.invalid"))
            cursor.execute("INSERT INTO workspace_leads(id,workspace_id,lead_id,source) VALUES (%s,%s,%s,'test')",
                (case[prefix + "lead"], case[prefix + "workspace"], case[prefix + "global_lead"]))
            cursor.execute("INSERT INTO discoveries(id,workspace_id,query) VALUES (%s,%s,'synthetic test')",
                (case[prefix + "discovery"], case[prefix + "workspace"]))
        cursor.execute("INSERT INTO memberships(id,organization_id,user_id,status) VALUES (%s,%s,%s,'active')",
            (identity("membership"), case["organization"], case["actor"]))
        connection.commit()
    return case
