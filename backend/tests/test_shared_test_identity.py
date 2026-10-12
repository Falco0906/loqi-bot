"""Mock-only coverage of test-owned creation, partial setup, and exact cleanup."""
from types import SimpleNamespace

import pytest

from tests.supabase_test_safety import OwnedRecordCleanup, validate_supabase_test_configuration
from services.platform.test_runtime import UnsafeTestDatabaseConfiguration


@pytest.fixture
def cleanup_client(monkeypatch):
    import supabase

    class Query:
        def __init__(self, client, table):
            self.client, self.table = client, table
            self.filters, self.action, self.payload = [], "", None
        def insert(self, payload):
            self.action, self.payload = "insert", payload
            return self
        def delete(self):
            self.action = "delete"
            return self
        def eq(self, key, value):
            self.filters.append((key, value))
            return self
        def execute(self):
            if self.action == "insert":
                self.client.created.append((self.table, self.payload))
                if self.client.write_error: raise self.client.write_error
            else:
                self.client.deleted.append((self.table, self.filters))
                if self.client.delete_error: raise self.client.delete_error
            return SimpleNamespace(data=[])

    class Client:
        supabase_url = "https://approved-test.supabase.co"
        supabase_key = "sentinel"
        def __init__(self):
            self.created, self.deleted = [], []
            self.write_error = self.delete_error = None
        def table(self, table): return Query(self, table)

    monkeypatch.setattr(supabase, "Client", Client)
    authorization = validate_supabase_test_configuration({
        "LOQI_TEST_SUPABASE_URL": Client.supabase_url,
        "LOQI_TEST_SUPABASE_KEY": Client.supabase_key,
        "LOQI_TEST_SUPABASE_PROJECT_REF": "approved-test",
        "LOQI_ALLOWED_TEST_SUPABASE_PROJECT_REFS": "approved-test",
    })
    return Client(), authorization


def test_cleanup_deletes_only_identity_created_by_this_run(cleanup_client):
    client, authorization = cleanup_client
    cleanup = OwnedRecordCleanup(client, authorization)
    identity = cleanup.create_identity()
    assert client.created[0][1]["id"] == identity == cleanup.test_run_id
    cleanup.cleanup()
    assert client.deleted == [("identity_users", [("id", identity), ("id", identity)])]
    cleanup.cleanup()
    assert len(client.deleted) == 1


def test_new_runs_cannot_share_an_identity(cleanup_client):
    client, authorization = cleanup_client
    first = OwnedRecordCleanup(client, authorization)
    second = OwnedRecordCleanup(client, authorization)
    assert first.create_identity() != second.create_identity()


def test_cleanup_rejects_arbitrary_table_and_id_registration(cleanup_client):
    client, authorization = cleanup_client
    cleanup = OwnedRecordCleanup(client, authorization)
    assert not hasattr(cleanup, "track")
    assert not hasattr(cleanup, "register_before_create")
    with pytest.raises(TypeError): OwnedRecordCleanup(client, authorization, "pre-existing-identity")
    with pytest.raises(TypeError): cleanup.create_identity("users", "arbitrary-id")
    cleanup.cleanup()
    assert client.created == client.deleted == []


def test_cleanup_cannot_be_created_without_validated_target(cleanup_client):
    client, _ = cleanup_client
    with pytest.raises(UnsafeTestDatabaseConfiguration): OwnedRecordCleanup(client, object())
    assert client.deleted == []


def test_ambiguous_write_tracks_generated_id_before_request(cleanup_client):
    client, authorization = cleanup_client
    cleanup = OwnedRecordCleanup(client, authorization)
    client.write_error = TimeoutError("mock response lost")
    with pytest.raises(TimeoutError): cleanup.create_identity()
    cleanup.cleanup()
    assert client.deleted == [("identity_users", [("id", cleanup.test_run_id), ("id", cleanup.test_run_id)])]


def test_partial_setup_without_write_never_issues_cleanup(cleanup_client):
    client, authorization = cleanup_client
    OwnedRecordCleanup(client, authorization).cleanup()
    assert client.deleted == []


def test_teardown_revalidates_client_target_before_delete(cleanup_client):
    client, authorization = cleanup_client
    cleanup = OwnedRecordCleanup(client, authorization)
    cleanup.create_identity()
    client.supabase_url = "https://unknown.supabase.co"
    with pytest.raises(UnsafeTestDatabaseConfiguration): cleanup.cleanup()
    assert client.deleted == []


def test_cleanup_failure_remains_observable_without_broadening_scope(cleanup_client):
    client, authorization = cleanup_client
    cleanup = OwnedRecordCleanup(client, authorization)
    cleanup.create_identity()
    client.delete_error = RuntimeError("mock cleanup failed")
    with pytest.raises(RuntimeError, match="mock cleanup failed"): cleanup.cleanup()
    assert client.deleted == [("identity_users", [("id", cleanup.test_run_id), ("id", cleanup.test_run_id)])]


@pytest.mark.parametrize("table,identity,column", [
    ("users", "this-run", "id"),
    ("identity_users", "someone-else", "id"),
    ("identity_users", "", "id"),
    ("identity_users", "this-run", "user_id"),
])
def test_cleanup_rejects_invalid_tracking_state_before_any_delete(cleanup_client, table, identity, column):
    client, authorization = cleanup_client
    cleanup = OwnedRecordCleanup(client, authorization)
    value = cleanup.test_run_id if identity == "this-run" else identity
    cleanup._records.append((table, value, column))
    with pytest.raises(ValueError, match="not owned"): cleanup.cleanup()
    assert client.deleted == []
