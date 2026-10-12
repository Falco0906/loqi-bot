"""Local-only target authorization and explicitly approved migration execution.

Nothing connects at import time. No application configuration, Supabase client,
startup graph, process management, database creation or cleanup is used here.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import stat
from threading import RLock
from uuid import UUID

from services.platform.test_runtime import is_test_runtime

MANIFEST = Path(__file__).with_name("migrations.json")
MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"
_AUTHORITY = object()
OWNER = "loqi_test_owner"
ROLES = ("anon", "authenticated", "service_role")
_CONNECT_LOCK = RLock()


class UnsafeLocalPostgres(RuntimeError):
    """Refuse an ambiguous target without revealing connection configuration."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class MigrationPlan:
    manifest_path: Path
    manifest_bytes: bytes
    sources: tuple[tuple[Path, bytes], ...]
    include_048: bool = False


def capture_migration_plan():
    """Validate existing source bytes and dependency order without executing SQL."""
    manifest_bytes = MANIFEST.read_bytes()
    plan = json.loads(manifest_bytes)
    if plan["version"] != 1 or plan["postgres_major"] != 16:
        raise UnsafeLocalPostgres("Unsupported migration manifest")
    if (plan["approval_required"]["file"] != "048_campaign_creation_idempotency.sql"
            or any(entry["file"].startswith("048") for entry in plan["prerequisites"])):
        raise UnsafeLocalPostgres("Migration 048 must remain separately gated")
    seen = set()
    result = []
    for entry in [*plan["prerequisites"], plan["approval_required"]]:
        name = entry["file"]
        if Path(name).name != name or name in seen or not set(entry["requires"]) <= seen:
            raise UnsafeLocalPostgres("Invalid migration dependency order")
        contents = (MIGRATIONS / name).read_bytes()
        if sha256(contents) != entry["sha256"]:
            raise UnsafeLocalPostgres("Migration changed: review and repin the manifest")
        seen.add(name)
        contents.decode()  # Reject invalid SQL encoding before approval.
        result.append((MIGRATIONS / name, contents))
    return MigrationPlan(MANIFEST, manifest_bytes, tuple(result))


def migration_plan():
    return [(path.name, contents.decode()) for path, contents in capture_migration_plan().sources]


def validate_execution_plan(plan):
    """Reject revocation or source replacement; execution uses captured bytes only."""
    if (plan.manifest_path.read_bytes() != plan.manifest_bytes
            or os.getenv("LOQI_TEST_POSTGRES_APPROVED_MANIFEST_SHA256") != sha256(plan.manifest_bytes)
            or any(path.read_bytes() != contents for path, contents in plan.sources)):
        raise UnsafeLocalPostgres("Approved migration plan changed or was revoked")
    if plan.include_048 and os.getenv("LOQI_TEST_POSTGRES_APPROVE_048_SHA256") != sha256(plan.sources[-1][1]):
        raise UnsafeLocalPostgres("Migration 048 requires separate approval of its exact bytes")


@dataclass(frozen=True)
class LocalTarget:
    root: Path
    database: str
    port: int
    run_id: str
    target_file: Path
    digest: str
    file_identity: tuple
    _seal: object = field(repr=False, compare=False)


def _private_owned(path: Path, *, directory: bool):
    info = path.lstat()
    expected = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not expected or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise UnsafeLocalPostgres("Target files must be private, owned and non-symlinked")


def _read_target_file(path):
    """Read and identify the same private non-symlink file descriptor."""
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise UnsafeLocalPostgres("Target file must be private and owned")
        raw = source.read()
        after = os.fstat(source.fileno())
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if identity(info) != identity(after):
            raise UnsafeLocalPostgres("Target changed while being read")
        return raw, identity(after)


def authorize_local_target(env=None) -> LocalTarget:
    """Only an explicitly approved, private Unix-socket target can be authorized."""
    values = os.environ if env is None else env
    if not is_test_runtime() or values.get("LOQI_TEST_POSTGRES_ENABLED") != "1":
        raise UnsafeLocalPostgres("Local PostgreSQL tests require process test runtime and explicit opt-in")
    if any(key.startswith("PG") for key in values):
        raise UnsafeLocalPostgres("Inherited libpq configuration is forbidden")
    try:
        source = Path(values["LOQI_TEST_POSTGRES_TARGET"])
        if not source.is_absolute() or source != source.resolve():
            raise UnsafeLocalPostgres("An exact absolute target path is required")
        _private_owned(source, directory=False)
        raw, file_identity = _read_target_file(source)
        if sha256(raw) != values.get("LOQI_TEST_POSTGRES_APPROVED_TARGET_SHA256"):
            raise UnsafeLocalPostgres("Exact target approval is required")
        data = json.loads(raw)
        if set(data) != {"version", "postgres_major", "root", "database", "port", "run_id", "owner"}:
            raise UnsafeLocalPostgres("Unexpected target configuration")
        root = Path(data["root"])
        run = str(UUID(data["run_id"]))
        if (data["version"] != 1 or data["postgres_major"] != 16 or data["owner"] != OWNER
                or not root.is_absolute() or root != root.resolve()
                or root.name != "loqi-pg-" + run or source.parent != root
                or data["database"] != "loqi_test_" + run.replace("-", "")
                or type(data["port"]) is not int or data["port"] != 55432):
            raise UnsafeLocalPostgres("Target does not match the disposable local contract")
        for directory in (root, root / "socket", root / "data"):
            _private_owned(directory, directory=True)
        _private_owned(root / "data" / "PG_VERSION", directory=False)
        if (root / "data" / "PG_VERSION").read_text().strip() != "16":
            raise UnsafeLocalPostgres("PostgreSQL major version must be 16")
    except (KeyError, TypeError, ValueError, OSError):
        raise UnsafeLocalPostgres("Missing or invalid dedicated local test configuration") from None
    identity = (root, data["database"], data["port"], run, source, sha256(raw), file_identity)
    return LocalTarget(*identity, (_AUTHORITY, identity))


def validate_target(target: LocalTarget):
    if not isinstance(target, LocalTarget) or target._seal != (_AUTHORITY, (
        target.root, target.database, target.port, target.run_id, target.target_file, target.digest, target.file_identity
    )):
        raise UnsafeLocalPostgres("A locally validated target capability is required")
    current = authorize_local_target()
    if current != target:
        raise UnsafeLocalPostgres("Target changed after authorization")


def _verify_connection(connection, target):
    """Read-only probe; no DDL/DML is allowed before identity verification."""
    with connection.cursor() as cursor:
        cursor.execute("""SELECT current_database(), session_user,
            current_setting('server_version_num')::integer, inet_server_addr(),
            pg_get_userbyid(d.datdba), shobj_description(d.oid, 'pg_database'),
            current_setting('data_directory'), current_setting('listen_addresses'),
            r.rolsuper, r.rolcreatedb, r.rolcreaterole, r.rolbypassrls
            FROM pg_database d JOIN pg_roles r ON r.rolname = session_user
            WHERE d.datname = current_database()""")
        row = cursor.fetchone()
    expected = (target.database, OWNER, None, OWNER, "loqi-disposable:" + target.run_id)
    if (not row or (row[0], row[1], row[3], row[4], row[5]) != expected
            or not 160000 <= row[2] < 170000 or Path(row[6]) != target.root / "data"
            or row[7] != "" or any(row[8:12])):
        raise UnsafeLocalPostgres("Connected server identity or owner privileges do not match approval")
    connection.rollback()


@contextmanager
def native_connection(target, *, user, database, provision_source=None):
    """Serialize harness driver calls; reject PG environment changes before yielding.

    The lock coordinates this harness, not arbitrary os.environ writers. No
    atomicity against unrelated same-process environment mutation is promised.
    """
    from tests.postgres.ownership import require_suite_ownership
    require_suite_ownership(target)
    provisioning = provision_source is not None
    if provisioning:
        from tests.postgres.provision import _approval, verify_cluster
        if (user, database) != ("loqi_pg_admin", "postgres"):
            raise UnsafeLocalPostgres("Provisioning connection must use the fixed local administrator target")
        _approval(target, provision_source)
    elif (user, database) != (OWNER, target.database):
        raise UnsafeLocalPostgres("Connection must use the exact approved disposable database and owner")
    import psycopg2
    with _CONNECT_LOCK:
        validate_target(target)
        connection = psycopg2.connect(
            host=str(target.root / "socket"), hostaddr="", port=target.port, dbname=database,
            user=user, password="", passfile="/dev/null", connect_timeout=3,
            application_name="loqi-disposable-tests", sslmode="disable",
            options="-c statement_timeout=10000 -c lock_timeout=3000 -c idle_in_transaction_session_timeout=15000",
        )
        try:
            validate_target(target)
            require_suite_ownership(target)
            if provisioning:
                verify_cluster(connection, target)
                _approval(target, provision_source)
            else:
                _verify_connection(connection, target)
                validate_target(target)
                with connection.cursor() as cursor:
                    verify_roles(cursor)
                connection.rollback()
            validate_target(target)
            require_suite_ownership(target)
        except BaseException:
            connection.close()
            raise
    try:
        yield connection
    finally:
        try:
            connection.rollback()
        finally:
            connection.close()


@contextmanager
def connect_local(target: LocalTarget):
    """Verify server identity and approval before exposing any connection."""
    from tests.postgres.ownership import require_suite_ownership
    with native_connection(target, user=OWNER, database=target.database) as connection:
        validate_target(target)
        require_suite_ownership(target)
        yield connection


def require_migration_approval(*, include_048=False):
    captured = capture_migration_plan()
    plan = MigrationPlan(captured.manifest_path, captured.manifest_bytes, captured.sources, include_048)
    if os.getenv("LOQI_TEST_POSTGRES_APPROVED_MANIFEST_SHA256") != sha256(plan.manifest_bytes):
        raise UnsafeLocalPostgres("Prerequisite migration manifest needs explicit approval")
    if include_048:
        digest = sha256(plan.sources[-1][1])
        if os.getenv("LOQI_TEST_POSTGRES_APPROVE_048_SHA256") != digest:
            raise UnsafeLocalPostgres("Migration 048 requires separate approval of its exact bytes")
    validate_execution_plan(plan)
    return plan


def verify_roles(cursor):
    cursor.execute("""SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolbypassrls,
        pg_has_role(session_user, oid, 'SET'), rolcanlogin, rolinherit, rolreplication FROM pg_roles
        WHERE rolname IN ('anon','authenticated','service_role') ORDER BY rolname""")
    rows = cursor.fetchall()
    if ([row[0] for row in rows] != sorted(ROLES)
            or any(len(row) != 9 or tuple(row[1:5]) != (False, False, False, False)
                or row[5] is not True or tuple(row[6:9]) != (False, False, False) for row in rows)):
        raise UnsafeLocalPostgres("Dedicated restricted roles require SET ROLE permission and NOLOGIN/NOINHERIT/NOREPLICATION")
    cursor.execute("""WITH RECURSIVE inherited(roleid) AS (
        SELECT roleid FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user)
        UNION SELECT m.roleid FROM pg_auth_members m JOIN inherited i ON m.member=i.roleid)
        SELECT r.rolname FROM inherited i JOIN pg_roles r ON r.oid=i.roleid
        WHERE r.rolname NOT IN ('anon','authenticated','service_role','pg_read_all_settings')""")
    if cursor.fetchall():
        raise UnsafeLocalPostgres("Unexpected owner role membership is forbidden")
    cursor.execute("""SELECT rolcanlogin, rolinherit, rolreplication,
        has_database_privilege(session_user,current_database(),'CONNECT'),
        pg_has_role(session_user,'pg_read_all_settings','USAGE')
        FROM pg_roles WHERE rolname=session_user""")
    if cursor.fetchone() != (True, True, False, True, True):
        raise UnsafeLocalPostgres("Execution owner requires LOGIN/INHERIT/CONNECT/settings access and NOREPLICATION")


def apply_prerequisites(target):
    """Explicit future operation; require a fresh schema, commit all prerequisites together."""
    plan = require_migration_approval()
    with connect_local(target) as connection, connection.cursor() as cursor:
        validate_execution_plan(plan)
        verify_roles(cursor)
        from tests.postgres.catalog_contract import verify_fresh_database
        verify_fresh_database(cursor)
        for _, contents in plan.sources[:-1]:
            validate_execution_plan(plan)
            cursor.execute(contents.decode())
        cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        cursor.execute("GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role")
        cursor.execute("GRANT SELECT, UPDATE ON workspaces, memberships, workspace_leads, discoveries, campaigns TO service_role")
        cursor.execute("GRANT INSERT ON campaigns, campaign_leads, strategies TO service_role")
        cursor.execute("GRANT SELECT ON campaign_leads, strategies TO service_role")
        connection.commit()


def apply_048(target):
    """Separate future operator approval; never part of application startup."""
    plan = require_migration_approval(include_048=True)
    with connect_local(target) as connection, connection.cursor() as cursor:
        validate_execution_plan(plan)
        verify_roles(cursor)
        from tests.postgres.catalog_contract import verify_campaign_prerequisites
        verify_campaign_prerequisites(cursor)
        validate_execution_plan(plan)
        cursor.execute(plan.sources[-1][1].decode())
        connection.commit()
