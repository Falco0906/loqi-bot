"""Test-owned row cleanup with a deliberately narrow table/identity scope."""
from __future__ import annotations

from uuid import uuid4

from services.platform.test_runtime import (
    TestDatabaseAuthorization,
    UnsafeTestDatabaseConfiguration,
    authorize_test_database,
    validate_supabase_client,
    validate_test_database_authorization,
)

# Only rows whose primary key is the fresh, per-test identity are eligible.
# Child tables must be individually registered with a future explicit owner
# mapping; arbitrary tables or workspace/user predicates are never accepted.
CLEANUP_OWNER_COLUMN = {"identity_users": "id"}


class OwnedRecordCleanup:
    """Delete only explicitly registered rows owned by this test-run UUID."""

    def __init__(
        self,
        client,
        authorization: TestDatabaseAuthorization,
    ) -> None:
        self._authorization = validate_test_database_authorization(authorization)
        if not validate_supabase_client(client, self._authorization):
            raise UnsafeTestDatabaseConfiguration("Cleanup requires a target-validated integration client")
        self._client = client
        self._test_run_id = str(uuid4())
        self._records: list[tuple[str, str, str]] = []

    @property
    def test_run_id(self) -> str:
        return self._test_run_id

    def create_identity(self) -> str:
        """Track our generated ID before writing, including ambiguous write outcomes.

        There is intentionally no public arbitrary-table/ID registration API.
        Only this creation interface can add rows to cleanup ownership.
        """
        self._validate_client()
        if self._records:
            raise RuntimeError("This test run already attempted identity creation")
        record = ("identity_users", self._test_run_id, CLEANUP_OWNER_COLUMN["identity_users"])
        self._records.append(record)
        self._client.table("identity_users").insert({
            "id": self._test_run_id,
            "display_name": "Loqi isolated integration test",
            "email": f"loqi-test-{self._test_run_id}@example.invalid",
        }).execute()
        return self._test_run_id

    def _validate_client(self) -> None:
        validate_test_database_authorization(self._authorization)
        if not validate_supabase_client(self._client, self._authorization):
            raise UnsafeTestDatabaseConfiguration("Cleanup client is not target-validated")

    def cleanup(self) -> None:
        """Delete only registered primary keys with the registered ownership predicate."""
        self._validate_client()
        # Recheck the allowlist and run ownership even for internal records.
        for table, record_id, owner_column in self._records:
            if CLEANUP_OWNER_COLUMN.get(table) != owner_column or record_id != self._test_run_id:
                raise ValueError("Cleanup record is not owned by this test run")
        while self._records:
            table, record_id, owner_column = self._records[-1]
            query = self._client.table(table).delete().eq("id", record_id)
            query.eq(owner_column, self._test_run_id).execute()
            self._records.pop()


# Compatibility names for existing tests; authorization is still issued only
# by the process-owned validator and cannot be constructed by env naming alone.
SupabaseTestConfiguration = TestDatabaseAuthorization
UnsafeSupabaseTestConfiguration = UnsafeTestDatabaseConfiguration
validate_supabase_test_configuration = authorize_test_database
