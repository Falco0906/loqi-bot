"""Safety tests for the reusable live-integration identity fixture."""
from __future__ import annotations

from tests.conftest import SHARED_TEST_USER_ID, _delete_owned_test_data, _ensure_shared_test_identity


class _Query:
    def __init__(self, client, table):
        self.client = client
        self.table_name = table
        self.action = "select"
        self.column = ""
        self.value = ""

    def select(self, *_args):
        return self

    def eq(self, column, value):
        self.column, self.value = column, value
        return self

    def delete(self):
        self.action = "delete"
        return self

    def insert(self, payload):
        self.action = "insert"
        self.client.inserts.append((self.table_name, payload))
        return self

    def execute(self):
        self.client.operations.append((self.action, self.table_name, self.column, self.value))
        if self.action == "select":
            return type("Response", (), {"data": self.client.rows.get((self.table_name, self.value), [])})()
        return type("Response", (), {"data": []})()


class _Client:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.operations = []
        self.inserts = []

    def table(self, table):
        return _Query(self, table)


def test_shared_identity_cleanup_only_targets_the_fixed_user():
    client = _Client({
        ("workflow_sessions", SHARED_TEST_USER_ID): [{"id": "session-a"}],
    })

    _delete_owned_test_data(client)

    deletes = [operation for operation in client.operations if operation[0] == "delete"]
    assert deletes
    assert all(value in {SHARED_TEST_USER_ID, "session-a"} for _, _, _, value in deletes)
    assert ("delete", "identity_users", "", "") not in deletes
    assert ("delete", "workspaces", "owner_user_id", SHARED_TEST_USER_ID) in deletes


def test_cleanup_rejects_any_identity_other_than_the_fixed_fixture_user():
    client = _Client()

    try:
        _delete_owned_test_data(client, "someone-else")
    except AssertionError as error:
        assert "shared test identity" in str(error)
    else:
        raise AssertionError("cleanup accepted an unsafe user id")


def test_shared_identity_is_created_once_and_then_reused():
    missing = _Client()
    assert _ensure_shared_test_identity(missing) == SHARED_TEST_USER_ID
    assert missing.inserts == [("identity_users", {
        "id": SHARED_TEST_USER_ID,
        "display_name": "Loqi Test Fixture",
        "email": "test-fixture@loqi.internal",
    })]

    existing = _Client({("identity_users", SHARED_TEST_USER_ID): [{"id": SHARED_TEST_USER_ID}]})
    assert _ensure_shared_test_identity(existing) == SHARED_TEST_USER_ID
    assert existing.inserts == []
