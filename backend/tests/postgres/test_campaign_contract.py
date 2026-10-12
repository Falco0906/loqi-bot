"""Real SQL contracts, not PostgREST/RLS proof. Skipped without separate approval."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import threading
import time
from uuid import uuid4, uuid5, NAMESPACE_URL

import pytest
import psycopg2
from psycopg2.extras import Json
from psycopg2 import sql

from services.campaigns.creation import creation_identity
from tests.postgres.harness import connect_local

pytestmark = pytest.mark.requires_local_postgres


def request(case, *, key="intent", name="Campaign", leads=None, discovery=None, strategy=None):
    leads = [case["lead"]] if leads is None else leads
    payload = {"name": name, "objective": "Synthetic test", "status": "planning", "search_query": "test",
        "discovery_id": case["discovery"] if discovery is None else discovery,
        "strategy": strategy, "leads": [{"workspace_lead_id": lead} for lead in leads]}
    campaign_id, fingerprint = creation_identity(case["workspace"], case["actor"], key, payload)
    return campaign_id, fingerprint, payload, leads


def call(connection, case, values=None):
    campaign_id, fingerprint, payload, leads = values or request(case)
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE service_role")
        cursor.execute("SELECT public.create_workspace_campaign_once(%s::uuid,%s::uuid,%s,%s,%s::jsonb,%s::uuid[],%s::jsonb)",
            (campaign_id, case["workspace"], case["actor"], fingerprint, Json(payload), leads,
             Json(payload["strategy"]) if payload["strategy"] is not None else None))
        return cursor.fetchone()[0]


def committed(case, values=None):
    with connect_local(case["target"]) as connection:
        result = call(connection, case, values)
        connection.commit()
        return result


def counts(case, campaign_id):
    with connect_local(case["target"]) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT (SELECT count(*) FROM campaigns WHERE id=%s),"
            "(SELECT count(*) FROM campaign_leads WHERE campaign_id=%s),"
            "(SELECT count(*) FROM strategies WHERE campaign_id=%s)", (campaign_id,) * 3)
        return cursor.fetchone()


def workspace_campaign_state(case, workspace_ids):
    """Snapshot contract-relevant campaign rows and their links/strategies."""
    workspace_ids = list(dict.fromkeys(workspace_ids))
    with connect_local(case["target"]) as connection, connection.cursor() as cursor:
        cursor.execute("""SELECT id::text, workspace_id::text, organization_id, name,
                objective, status, search_query, discovery_id::text, settings, created_by,
                updated_by, metadata, version, created_at, updated_at, archived_at, deleted_at
            FROM campaigns WHERE workspace_id = ANY(%s::uuid[]) ORDER BY id""", (workspace_ids,))
        campaigns = tuple(cursor.fetchall())
        cursor.execute("""SELECT cl.id::text, cl.campaign_id::text, cl.lead_id::text,
                cl.added_by, cl.status, cl.deleted_at, cl.created_at, cl.updated_at
            FROM campaign_leads cl JOIN campaigns c ON c.id=cl.campaign_id
            WHERE c.workspace_id = ANY(%s::uuid[]) ORDER BY cl.id""", (workspace_ids,))
        attachments = tuple(cursor.fetchall())
        cursor.execute("""SELECT s.id::text, s.campaign_id::text, s.version, s.is_current,
                s.objective, s.audience, s.channel, s.messaging_angle, s.sequence, s.tone,
                s.persona, s.offer, s.objections, s.raw, s.generated_at, s.generated_by,
                s.model_used, s.created_at
            FROM strategies s JOIN campaigns c ON c.id=s.campaign_id
            WHERE c.workspace_id = ANY(%s::uuid[]) ORDER BY s.id""", (workspace_ids,))
        strategies = tuple(cursor.fetchall())
    return {"campaigns": campaigns, "attachments": attachments, "strategies": strategies}


def test_create_and_replay_canonical_attachments(campaign_case):
    case = campaign_case
    first, replay = committed(case), committed(case)
    assert first["created"] is True and replay["created"] is False
    assert first["campaign"]["id"] == replay["campaign"]["id"] == request(case)[0]
    assert counts(case, request(case)[0]) == (1, 1, 0)
    with connect_local(case["target"]) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT lead_id::text FROM campaign_leads WHERE campaign_id=%s", (request(case)[0],))
        assert cursor.fetchall() == [(case["lead"],)]


def test_changed_payload_conflicts(campaign_case):
    committed(campaign_case)
    with pytest.raises(psycopg2.Error) as caught:
        committed(campaign_case, request(campaign_case, name="Changed"))
    assert caught.value.pgcode == "23514"
    assert counts(campaign_case, request(campaign_case)[0]) == (1, 1, 0)


@pytest.mark.parametrize("changed", [False, True])
def test_concurrent_same_key(campaign_case, changed):
    case = campaign_case
    ready = threading.Event()
    worker_pid = []
    def submit():
        with connect_local(campaign_case["target"]) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                worker_pid.append(cursor.fetchone()[0])
            ready.set()
            try:
                result = call(connection, case, request(case, name="Different" if changed else "Campaign"))
                connection.commit()
                return result["created"]
            except psycopg2.Error as error:
                return error.pgcode
    with connect_local(case["target"]) as holder:
        first = call(holder, case)  # Hold the exact RPC advisory lock through commit.
        with holder.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            holder_pid = cursor.fetchone()[0]
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(submit)
            try:
                assert ready.wait(3), "Second independent connection never became ready"
                with connect_local(case["target"]) as observer:
                    wait_for_blocker(observer, worker_pid[0], holder_pid, advisory=True)
                assert not future.done(), "Second call did not overlap the held transaction"
            finally:
                holder.commit()
            outcome = future.result(timeout=5)
    assert first["created"] is True
    assert outcome == ("23514" if changed else False)
    assert counts(campaign_case, request(campaign_case)[0]) == (1, 1, 0)
    with connect_local(case["target"]) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT name FROM campaigns WHERE id=%s", (request(case)[0],))
        assert cursor.fetchone() == ("Campaign",)


@contextmanager
def insertion_failure(case, table, *, after_first_attachment=False):
    """A named, test-owned fault trigger; exact cleanup, never a table reset."""
    name = "test_failure_" + uuid4().hex
    campaign_id = request(case)[0]
    after_first = (f" AND EXISTS(SELECT 1 FROM campaign_leads WHERE campaign_id='{campaign_id}'::uuid)"
        if after_first_attachment else "")
    with connect_local(case["target"]) as connection, connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE FUNCTION public.{}() RETURNS trigger LANGUAGE plpgsql AS {}")
            .format(sql.Identifier(name), sql.Literal(
                f"BEGIN IF NEW.campaign_id = '{campaign_id}'::uuid{after_first} THEN RAISE EXCEPTION 'synthetic failure'; END IF; RETURN NEW; END;")))
        cursor.execute(sql.SQL("CREATE TRIGGER {} BEFORE INSERT ON public.{} FOR EACH ROW EXECUTE FUNCTION public.{}()")
            .format(sql.Identifier(name), sql.Identifier(table), sql.Identifier(name)))
        connection.commit()
    try:
        yield
    finally:
        with connect_local(case["target"]) as connection, connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP TRIGGER {} ON public.{}").format(sql.Identifier(name), sql.Identifier(table)))
            cursor.execute(sql.SQL("DROP FUNCTION public.{}()").format(sql.Identifier(name)))
            connection.commit()


@pytest.mark.parametrize("table", ["campaign_leads", "strategies"])
def test_atomic_rollback_on_later_insert_failure(campaign_case, table):
    values = request(campaign_case, strategy={"objective": "Explicit existing strategy"} if table == "strategies" else None)
    with insertion_failure(campaign_case, table), pytest.raises(psycopg2.Error):
        committed(campaign_case, values)
    assert counts(campaign_case, values[0]) == (0, 0, 0)
    assert committed(campaign_case, values)["created"] is True


def test_failure_after_first_attachment_rolls_back_entire_creation(campaign_case):
    case = campaign_case
    second = str(uuid5(NAMESPACE_URL, case["lead"] + ":second-attachment"))
    with connect_local(case["target"]) as connection, connection.cursor() as cursor:
        cursor.execute("INSERT INTO workspace_leads(id,workspace_id,lead_id,source) VALUES (%s,%s,%s,'test')",
            (second, case["workspace"], case["foreign_global_lead"]))
        connection.commit()
    values = request(case, leads=[case["lead"], second])
    with insertion_failure(case, "campaign_leads", after_first_attachment=True), pytest.raises(psycopg2.Error) as error:
        committed(case, values)
    assert error.value.pgcode == "P0001"
    assert counts(case, values[0]) == (0, 0, 0)
    assert committed(case, values)["created"] is True
    assert counts(case, values[0]) == (1, 2, 0)


def wait_for_blocker(connection, pid, blocker, *, advisory=False):
    """Observe PostgreSQL lock state with a deadline; no timing-only race assertion."""
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_blocking_pids(%s)", (pid,))
            blocked = blocker in cursor.fetchone()[0]
            if blocked:
                if advisory:
                    cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_locks w JOIN pg_locks h"
                        " ON h.locktype=w.locktype AND h.database IS NOT DISTINCT FROM w.database"
                        " AND h.classid=w.classid AND h.objid=w.objid AND h.objsubid=w.objsubid"
                        " WHERE w.pid=%s AND h.pid=%s AND w.locktype='advisory'"
                        " AND NOT w.granted AND h.granted)", (pid, blocker))
                    if not cursor.fetchone()[0]:
                        connection.rollback()
                        continue
                return
        connection.rollback()
        threading.Event().wait(0.01)
    pytest.fail(f"PID {pid} did not wait for PID {blocker} on the expected "
        + ("advisory" if advisory else "row/transaction") + " lock within two seconds")


@pytest.mark.parametrize("mutation", ["membership_update", "membership_delete", "lead_delete_marker",
    "lead_move", "workspace_delete_marker", "discovery_delete_marker"])
def test_mutations_wait_for_creation_commit(campaign_case, mutation):
    case = campaign_case
    ready = threading.Event()
    worker_pid = []
    with connect_local(case["target"]) as holder:
        with holder.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            holder_pid = cursor.fetchone()[0]
        call(holder, case)  # SQL finished, row locks deliberately held until commit.
        def mutate():
            with connect_local(case["target"]) as connection, connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                worker_pid.append(cursor.fetchone()[0])
                ready.set()
                if mutation == "membership_update":
                    cursor.execute("UPDATE memberships SET status='removed' WHERE organization_id=%s AND user_id=%s", (case["organization"], case["actor"]))
                elif mutation == "membership_delete":
                    cursor.execute("DELETE FROM memberships WHERE organization_id=%s AND user_id=%s", (case["organization"], case["actor"]))
                elif mutation == "lead_delete_marker":
                    cursor.execute("UPDATE workspace_leads SET deleted_at=now() WHERE id=%s", (case["lead"],))
                elif mutation == "lead_move":
                    cursor.execute("UPDATE workspace_leads SET workspace_id=%s WHERE id=%s", (case["foreign_workspace"], case["lead"]))
                else:
                    table, identity = ("workspaces", case["workspace"]) if mutation == "workspace_delete_marker" else ("discoveries", case["discovery"])
                    cursor.execute(sql.SQL("UPDATE {} SET deleted_at=now() WHERE id=%s").format(sql.Identifier(table)), (identity,))
                connection.commit()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(mutate)
            try:
                assert ready.wait(3)
                with connect_local(case["target"]) as observer:
                    wait_for_blocker(observer, worker_pid[0], holder_pid)
            finally:
                holder.commit()
            future.result(timeout=5)
    assert counts(case, request(case)[0]) == (1, 1, 0)
    with connect_local(case["target"]) as connection, connection.cursor() as cursor:
        if mutation.startswith("membership"):
            cursor.execute("SELECT status FROM memberships WHERE organization_id=%s AND user_id=%s", (case["organization"], case["actor"]))
            assert cursor.fetchall() == ([] if mutation == "membership_delete" else [("removed",)])
        elif mutation == "lead_move":
            cursor.execute("SELECT workspace_id::text FROM workspace_leads WHERE id=%s", (case["lead"],))
            assert cursor.fetchone() == (case["foreign_workspace"],)
        else:
            table, identity = {"lead_delete_marker": ("workspace_leads", case["lead"]),
                "workspace_delete_marker": ("workspaces", case["workspace"]),
                "discovery_delete_marker": ("discoveries", case["discovery"])}[mutation]
            cursor.execute(sql.SQL("SELECT deleted_at IS NOT NULL FROM {} WHERE id=%s").format(sql.Identifier(table)), (identity,))
            assert cursor.fetchone() == (True,)


@pytest.mark.parametrize("mutation", ["membership_update", "membership_delete", "workspace_delete_marker",
    "discovery_delete_marker", "lead_delete_marker", "lead_move", "lead_physical_delete"])
def test_mutation_winning_first_denies_creation(campaign_case, mutation):
    case = campaign_case
    ready, worker_pid = threading.Event(), []
    def create():
        with connect_local(case["target"]) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                worker_pid.append(cursor.fetchone()[0])
            ready.set()
            try:
                call(connection, case)
                connection.commit()
                return "unexpected_success"
            except psycopg2.Error as error:
                return error.pgcode
    with connect_local(case["target"]) as holder, holder.cursor() as cursor:
        cursor.execute("SELECT pg_backend_pid()")
        holder_pid = cursor.fetchone()[0]
        if mutation.startswith("membership"):
            statement = "DELETE FROM memberships" if mutation.endswith("delete") else "UPDATE memberships SET status='removed'"
            cursor.execute(statement + " WHERE organization_id=%s AND user_id=%s", (case["organization"], case["actor"]))
        elif mutation == "lead_move":
            cursor.execute("UPDATE workspace_leads SET workspace_id=%s WHERE id=%s", (case["foreign_workspace"], case["lead"]))
        elif mutation == "lead_physical_delete":
            cursor.execute("DELETE FROM workspace_leads WHERE id=%s", (case["lead"],))
        else:
            table, identity = {"workspace_delete_marker": ("workspaces", case["workspace"]),
                "discovery_delete_marker": ("discoveries", case["discovery"]),
                "lead_delete_marker": ("workspace_leads", case["lead"])}[mutation]
            cursor.execute(sql.SQL("UPDATE {} SET deleted_at=now() WHERE id=%s").format(sql.Identifier(table)), (identity,))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(create)
            try:
                assert ready.wait(3), "Creation connection never became ready"
                with connect_local(case["target"]) as observer:
                    wait_for_blocker(observer, worker_pid[0], holder_pid)
            finally:
                holder.commit()
            assert future.result(timeout=5) == "42501"
    assert counts(case, request(case)[0]) == (0, 0, 0)


@pytest.mark.parametrize("invalid", ["foreign_lead", "foreign_discovery", "deleted_workspace", "deleted_discovery", "deleted_lead", "duplicate_lead", "missing_lead", "null_lead"])
def test_unavailable_inputs_are_rejected(campaign_case, invalid):
    case = campaign_case
    values = request(case)
    if invalid == "foreign_lead": values = request(case, leads=[case["foreign_lead"]])
    elif invalid == "foreign_discovery": values = request(case, discovery=case["foreign_discovery"])
    elif invalid == "duplicate_lead": values = request(case, leads=[case["lead"], case["lead"]])
    elif invalid == "missing_lead": values = request(case, leads=[str(uuid4())])
    elif invalid == "null_lead": values = request(case, leads=[None])
    else:
        table, identity = {"deleted_workspace": ("workspaces", case["workspace"]),
            "deleted_discovery": ("discoveries", case["discovery"]),
            "deleted_lead": ("workspace_leads", case["lead"])}[invalid]
        with connect_local(case["target"]) as connection, connection.cursor() as cursor:
            cursor.execute(sql.SQL("UPDATE {} SET deleted_at=now() WHERE id=%s").format(sql.Identifier(table)), (identity,))
            connection.commit()
    with pytest.raises(psycopg2.Error) as caught:
        committed(case, values)
    assert caught.value.pgcode == "42501"
    assert counts(case, values[0]) == (0, 0, 0)


def test_actual_function_privileges(campaign_case):
    signature = "public.create_workspace_campaign_once(uuid,uuid,text,text,jsonb,uuid[],jsonb)"
    with connect_local(campaign_case["target"]) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT has_function_privilege('service_role',%s,'EXECUTE'),"
            "has_function_privilege('anon',%s,'EXECUTE'),has_function_privilege('authenticated',%s,'EXECUTE')", (signature,) * 3)
        assert cursor.fetchone() == (True, False, False)
        cursor.execute("SELECT count(*) FROM pg_proc p, LATERAL aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) a"
            " WHERE p.oid=to_regprocedure(%s) AND a.grantee=0 AND a.privilege_type='EXECUTE'", (signature,))
        assert cursor.fetchone() == (0,), "PUBLIC must not inherit default function EXECUTE"
    for role in ("anon", "authenticated"):
        with connect_local(campaign_case["target"]) as connection, connection.cursor() as cursor:
            cursor.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
            with pytest.raises(psycopg2.Error) as caught:
                cursor.execute("SELECT public.create_workspace_campaign_once(NULL,NULL,NULL,NULL,NULL,NULL,NULL)")
            assert caught.value.pgcode == "42501"
    assert committed(campaign_case)["created"] is True


def public_can_execute(cursor, signature):
    cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_proc p,"
        " LATERAL aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) a"
        " WHERE p.oid=to_regprocedure(%s) AND a.grantee=0 AND a.privilege_type='EXECUTE')", (signature,))
    return cursor.fetchone()[0]


def test_unexpected_public_function_grant_is_detected_without_persisting_it(campaign_case):
    signature = "public.create_workspace_campaign_once(uuid,uuid,text,text,jsonb,uuid[],jsonb)"
    with connect_local(campaign_case["target"]) as connection, connection.cursor() as cursor:
        assert public_can_execute(cursor, signature) is False
        cursor.execute("GRANT EXECUTE ON FUNCTION public.create_workspace_campaign_once(uuid,uuid,text,text,jsonb,uuid[],jsonb) TO PUBLIC")
        assert public_can_execute(cursor, signature) is True
        connection.rollback()  # No shared privilege mutation survives this test.
        assert public_can_execute(cursor, signature) is False


def test_default_public_execute_requires_an_explicit_revoke(campaign_case):
    name = "test_default_acl_" + uuid4().hex
    signature = "public." + name + "()"
    with connect_local(campaign_case["target"]) as connection, connection.cursor() as cursor:
        cursor.execute("ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO PUBLIC")
        cursor.execute(sql.SQL("CREATE FUNCTION public.{}() RETURNS integer LANGUAGE sql AS 'SELECT 1'")
            .format(sql.Identifier(name)))
        assert public_can_execute(cursor, signature) is True
        cursor.execute(sql.SQL("REVOKE ALL ON FUNCTION public.{}() FROM PUBLIC").format(sql.Identifier(name)))
        assert public_can_execute(cursor, signature) is False
        connection.rollback()  # Both test function and default-ACL change disappear.
        cursor.execute("SELECT to_regprocedure(%s)", (signature,))
        assert cursor.fetchone() == (None,)


def test_repeated_attachment_constraint_does_not_change_original(campaign_case):
    case = campaign_case
    committed(case)
    with connect_local(case["target"]) as connection, connection.cursor() as cursor:
        with pytest.raises(psycopg2.Error) as caught:
            cursor.execute("INSERT INTO campaign_leads(campaign_id,lead_id,added_by) VALUES (%s,%s,%s)",
                (request(case)[0], case["lead"], case["actor"]))
        assert caught.value.pgcode == "23505"
    assert counts(case, request(case)[0]) == (1, 1, 0)
    assert committed(case)["created"] is False


def test_response_loss_recovery_does_not_repeat_attachments(campaign_case):
    # An ambiguous caller outcome is modeled by discarding a confirmed commit,
    # not by pretending that a thread timeout cancels the transaction.
    committed(campaign_case)
    assert counts(campaign_case, request(campaign_case)[0]) == (1, 1, 0)
    assert committed(campaign_case)["created"] is False
    assert counts(campaign_case, request(campaign_case)[0]) == (1, 1, 0)


def test_postcommit_hydration_error_does_not_rollback_creation(campaign_case):
    committed(campaign_case)
    with connect_local(campaign_case["target"]) as connection, connection.cursor() as cursor:
        with pytest.raises(psycopg2.Error):
            cursor.execute("SELECT 1/0")
    recovered = committed(campaign_case)
    assert recovered["created"] is False
    assert counts(campaign_case, request(campaign_case)[0]) == (1, 1, 0)


def test_explicit_strategy_and_zero_attachment_creation(campaign_case):
    values = request(campaign_case, leads=[], strategy={"objective": "Supplied strategy"})
    assert committed(campaign_case, values)["created"] is True
    assert committed(campaign_case, values)["created"] is False
    assert counts(campaign_case, values[0]) == (1, 0, 1)


def test_repeatable_read_catalog_visibility_during_independent_ddl(campaign_case):
    """Prepared PG16 check of the capture assumption, not an offline proof.

    Only a uniquely named, test-created scratch table changes; no campaign
    relation is altered and no CASCADE cleanup is permitted.
    """
    case = campaign_case
    name = "test_catalog_" + uuid4().hex
    with connect_local(case["target"]) as connection, connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE TABLE public.{} (original integer)").format(sql.Identifier(name)))
        connection.commit()
    try:
        with connect_local(case["target"]) as reader, reader.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            query = "SELECT attname FROM pg_attribute WHERE attrelid=to_regclass(%s) AND attnum>0 AND NOT attisdropped ORDER BY attnum"
            cursor.execute(query, ("public." + name,))
            assert cursor.fetchall() == [("original",)]
            def alter():
                with connect_local(case["target"]) as writer, writer.cursor() as ddl:
                    ddl.execute(sql.SQL("ALTER TABLE public.{} ADD COLUMN later integer").format(sql.Identifier(name)))
                    writer.commit()
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(alter).result(timeout=5)
            cursor.execute(query, ("public." + name,))
            assert cursor.fetchall() == [("original",)], "Catalog transaction mixed old and newly committed DDL"
        with connect_local(case["target"]) as observer, observer.cursor() as cursor:
            cursor.execute(query, ("public." + name,))
            assert cursor.fetchall() == [("original",), ("later",)]
    finally:
        with connect_local(case["target"]) as connection, connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP TABLE public.{}").format(sql.Identifier(name)))
            connection.commit()


def test_campaign_id_collision_across_actor_and_workspace(campaign_case):
    """An authorized different scope cannot replay another campaign UUID."""
    case = campaign_case
    values = request(case)
    campaign_id = values[0]

    def identity(label):
        return str(uuid5(NAMESPACE_URL, case["actor"] + ":" + label))

    other_actor = identity("collision-actor")
    with connect_local(case["target"]) as connection, connection.cursor() as cursor:
        cursor.execute("INSERT INTO identity_users(id,email) VALUES (%s,%s)",
            (other_actor, other_actor + "@example.invalid"))
        cursor.execute("INSERT INTO memberships(id,organization_id,user_id,status) VALUES (%s,%s,%s,'active')",
            (identity("collision-actor-membership"), case["organization"], other_actor))
        cursor.execute("INSERT INTO memberships(id,organization_id,user_id,status) VALUES (%s,%s,%s,'active')",
            (identity("collision-workspace-membership"), case["foreign_organization"], case["actor"]))
        connection.commit()

    committed(case, values)
    involved_workspaces = [case["workspace"], case["foreign_workspace"]]
    before = workspace_campaign_state(case, involved_workspaces)
    assert len(before["campaigns"]) == 1
    original_campaign = before["campaigns"][0]
    assert original_campaign[0] == campaign_id
    assert (
        original_campaign[1], original_campaign[2], original_campaign[3],
        original_campaign[4], original_campaign[5], original_campaign[6],
        original_campaign[7], original_campaign[9], original_campaign[10],
        original_campaign[12], original_campaign[15], original_campaign[16],
    ) == (
        case["workspace"], case["organization"], "Campaign", "Synthetic test", "planning",
        "test", case["discovery"], case["actor"], case["actor"], 1, None, None,
    )
    assert original_campaign[11]["creation_request_hash"] == values[1]
    assert len(before["attachments"]) == 1
    assert before["attachments"][0][1:5] == (campaign_id, case["lead"], case["actor"], "added")
    assert before["attachments"][0][5] is None
    assert before["strategies"] == ()

    actor_case = dict(case, actor=other_actor)
    with pytest.raises(psycopg2.Error) as actor_error:
        committed(actor_case, values)
    assert actor_error.value.pgcode == "23514"
    assert actor_error.value.diag.message_primary == "Idempotency key belongs to a different request"
    assert workspace_campaign_state(case, involved_workspaces) == before

    workspace_case = dict(case, workspace=case["foreign_workspace"])
    with pytest.raises(psycopg2.Error) as workspace_error:
        committed(workspace_case, values)
    assert workspace_error.value.pgcode == "23514"
    assert workspace_error.value.diag.message_primary == "Idempotency key belongs to a different request"
    assert workspace_campaign_state(case, involved_workspaces) == before
    assert counts(case, campaign_id) == (1, 1, 0)


@pytest.mark.parametrize("access", ["owner-only", "workspace-member-only"])
def test_workspace_owner_or_member_without_active_org_membership_is_denied(campaign_case, access):
    case = campaign_case
    attempted = dict(case, workspace=case["foreign_workspace"],
        discovery=case["foreign_discovery"], lead=case["foreign_lead"])

    if access == "workspace-member-only":
        identity = str(uuid5(NAMESPACE_URL, case["actor"] + ":workspace-member"))
        with connect_local(case["target"]) as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE workspaces SET owner_user_id=NULL WHERE id=%s", (case["foreign_workspace"],))
            cursor.execute("INSERT INTO workspace_members(id,workspace_id,user_id,role,status) "
                "VALUES (%s,%s,%s,'member','active')",
                (identity, case["foreign_workspace"], case["actor"]))
            connection.commit()

    involved_workspaces = [case["workspace"], case["foreign_workspace"]]
    before = workspace_campaign_state(case, involved_workspaces)
    values = request(attempted)
    with pytest.raises(psycopg2.Error) as caught:
        committed(attempted, values)
    assert caught.value.pgcode == "42501"
    assert counts(attempted, values[0]) == (0, 0, 0)
    assert workspace_campaign_state(case, involved_workspaces) == before


@pytest.mark.parametrize("order", ["valid-first", "invalid-first"])
def test_mixed_valid_invalid_lead_batch_is_atomic(campaign_case, order):
    case = campaign_case
    selected = ([case["lead"], case["foreign_lead"]] if order == "valid-first"
        else [case["foreign_lead"], case["lead"]])
    values = request(case, leads=selected)
    involved_workspaces = [case["workspace"], case["foreign_workspace"]]
    before = workspace_campaign_state(case, involved_workspaces)
    with pytest.raises(psycopg2.Error) as caught:
        committed(case, values)
    assert caught.value.pgcode == "42501"
    assert counts(case, values[0]) == (0, 0, 0)
    assert workspace_campaign_state(case, involved_workspaces) == before


def test_replay_after_campaign_soft_delete(campaign_case):
    case = campaign_case
    values = request(case)
    committed(case, values)
    campaign_id = values[0]
    with connect_local(case["target"]) as connection, connection.cursor() as cursor:
        cursor.execute("UPDATE campaigns SET status='deleted', deleted_at=now() WHERE id=%s", (campaign_id,))
        connection.commit()
    before = workspace_campaign_state(case, [case["workspace"]])
    assert len(before["campaigns"]) == 1
    assert before["campaigns"][0][5] == "deleted" and before["campaigns"][0][16] is not None
    assert before["campaigns"][0][11]["creation_request_hash"] == values[1]
    assert len(before["attachments"]) == 1
    assert before["strategies"] == ()

    with pytest.raises(psycopg2.Error) as caught:
        committed(case, values)
    assert caught.value.pgcode == "P0002"
    assert counts(case, campaign_id) == (1, 1, 0)
    assert workspace_campaign_state(case, [case["workspace"]]) == before


def test_campaign_rpc_catalog_security_contract(local_target):
    """Read-only checks of the installed RPC signature, ownership and ACLs."""
    signature = "public.create_workspace_campaign_once(uuid,uuid,text,text,jsonb,uuid[],jsonb)"
    with connect_local(local_target) as connection, connection.cursor() as cursor:
        cursor.execute("""SELECT n.nspname, p.proname, p.pronargs,
                pg_get_userbyid(p.proowner), p.prosecdef, p.proconfig
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE p.oid=to_regprocedure(%s)""", (signature,))
        rows = cursor.fetchall()
        assert len(rows) == 1
        schema, name, arg_count, owner, security_definer, configuration = rows[0]
        assert (schema, name, arg_count, owner, security_definer) == (
            "public", "create_workspace_campaign_once", 7, "loqi_test_owner", False)
        assert configuration is not None and "search_path=public" in configuration

        cursor.execute("SELECT has_function_privilege('service_role',%s,'EXECUTE'),"
            "has_function_privilege('anon',%s,'EXECUTE'),"
            "has_function_privilege('authenticated',%s,'EXECUTE')", (signature,) * 3)
        assert cursor.fetchone() == (True, False, False)

        # Inspect only the function's stored ACL. Do not coalesce a NULL ACL
        # with acldefault(): that would answer an effective/default question,
        # not whether PUBLIC has an explicit grant recorded on this function.
        cursor.execute("""SELECT COALESCE(bool_or(acl.grantee=0 AND acl.privilege_type='EXECUTE'), false)
            FROM pg_proc p
            LEFT JOIN LATERAL aclexplode(p.proacl) AS acl ON true
            WHERE p.oid=to_regprocedure(%s)""", (signature,))
        assert cursor.fetchone() == (False,)
