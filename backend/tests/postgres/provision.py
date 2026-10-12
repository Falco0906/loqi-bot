"""Operator-approved cluster provisioning, separate from database/migration approval."""
import os
from pathlib import Path

from tests.postgres.harness import (
    UnsafeLocalPostgres, authorize_local_target, native_connection, sha256, validate_target,
)

SOURCE = Path(__file__).with_name("provision_roles.sql")


def _approval(target, source):
    validate_target(target)
    if (os.getenv("LOQI_TEST_POSTGRES_APPROVED_PROVISION_TARGET_SHA256") != target.digest
            or os.getenv("LOQI_TEST_POSTGRES_APPROVED_PROVISION_SQL_SHA256") != sha256(source)
            or SOURCE.read_bytes() != source):
        raise UnsafeLocalPostgres("Separate exact cluster provisioning approval is required")


def verify_cluster(connection, target):
    """Read-only provisioning probe, enforced before native connection exposure."""
    with connection.cursor() as cursor:
        cursor.execute("""SELECT current_database(), session_user,
                current_setting('server_version_num')::integer, inet_server_addr(),
                current_setting('data_directory'), current_setting('listen_addresses'),
                pg_get_userbyid(d.datdba), r.rolsuper,
                (SELECT count(*) FROM pg_database WHERE datname NOT IN ('postgres','template0','template1')),
                (SELECT count(*) FROM pg_roles WHERE rolname IN
                    ('loqi_test_owner','anon','authenticated','service_role'))
                FROM pg_database d JOIN pg_roles r ON r.rolname=session_user
                WHERE d.datname=current_database()""")
        row = cursor.fetchone()
        if (not row or len(row) != 10 or row[0:2] != ("postgres", "loqi_pg_admin")
                or not 160000 <= row[2] < 170000 or row[3] is not None
                or Path(row[4]) != target.root / "data" or row[5] != ""
                or row[6:10] != ("loqi_pg_admin", True, 0, 0)):
            raise UnsafeLocalPostgres("Provisioning requires the exact fresh approved private cluster")
    connection.rollback()


def provision_cluster():
    """Future explicit operator operation; never called by fixtures or startup.

    Partial provisioning remains observable and is not automatically retried or
    cleaned up: roles commit atomically, CREATE DATABASE is a separate operation.
    """
    target = authorize_local_target()
    source = SOURCE.read_bytes()
    _approval(target, source)
    from tests.postgres.ownership import require_suite_ownership
    require_suite_ownership(target)
    with native_connection(target, user="loqi_pg_admin", database="postgres", provision_source=source) as connection:
        with connection.cursor() as cursor:
            _approval(target, source)
            cursor.execute(source.decode())
        connection.commit()
        _approval(target, source)
        connection.autocommit = True
        from psycopg2 import sql
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {} OWNER loqi_test_owner").format(sql.Identifier(target.database)))
            _approval(target, source)
            cursor.execute(sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                sql.Identifier(target.database), sql.Literal("loqi-disposable:" + target.run_id)))
