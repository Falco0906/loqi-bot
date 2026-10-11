"""Process-owned safeguards for pytest and explicitly authorized DB tests.

The pytest bootstrap activates test runtime before application imports. There
is intentionally no deactivation API: changing an environment variable cannot
restore access to application credentials during that process.
"""
from __future__ import annotations

import hmac
import os
from dataclasses import dataclass, field
from urllib.parse import urlparse


PRODUCTION_PROJECT_REF = "llckvmpwmovhchfpjnsa"
_TEST_RUNTIME_ACTIVE = False
_AUTHORITY = object()


class UnsafeTestDatabaseConfiguration(RuntimeError):
    """A test database target cannot be proven to be an approved test project."""


@dataclass(frozen=True)
class TestDatabaseAuthorization:
    url: str
    key: str = field(repr=False)
    project_ref: str
    _authority: object = field(repr=False, compare=False)


def activate_test_runtime() -> None:
    """Permanently enable offline safeguards for this Python process."""
    global _TEST_RUNTIME_ACTIVE
    _TEST_RUNTIME_ACTIVE = True


def is_test_runtime() -> bool:
    """Return process state, not a mutable environment-variable value."""
    return _TEST_RUNTIME_ACTIVE


def authorize_test_database(env: dict[str, str] | None = None) -> TestDatabaseAuthorization:
    """Validate dedicated integration settings and mint a process-bound capability."""
    if not is_test_runtime():
        raise UnsafeTestDatabaseConfiguration("Test database authorization is available only in test runtime")

    values = os.environ if env is None else env
    url = values.get("LOQI_TEST_SUPABASE_URL", "").strip()
    key = values.get("LOQI_TEST_SUPABASE_KEY", "").strip()
    project_ref = values.get("LOQI_TEST_SUPABASE_PROJECT_REF", "").strip().lower()
    allowed_refs = {
        value.strip().lower()
        for value in values.get("LOQI_ALLOWED_TEST_SUPABASE_PROJECT_REFS", "").split(",")
        if value.strip()
    }
    if not url or not key or not project_ref or not allowed_refs:
        raise UnsafeTestDatabaseConfiguration("Dedicated test database configuration is incomplete")
    if project_ref == PRODUCTION_PROJECT_REF or project_ref not in allowed_refs:
        raise UnsafeTestDatabaseConfiguration("Database project is not an approved test target")

    try:
        parsed = urlparse(url)
    except ValueError:
        raise UnsafeTestDatabaseConfiguration("Test URL is malformed") from None
    labels = (parsed.hostname or "").lower().split(".")
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.netloc.lower() != f"{project_ref}.supabase.co"
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or len(labels) != 3
        or labels[1:] != ["supabase", "co"]
        or labels[0] != project_ref
    ):
        raise UnsafeTestDatabaseConfiguration("Test URL does not match its approved project identity")

    url = f"https://{project_ref}.supabase.co"
    return TestDatabaseAuthorization(url, key, project_ref, (_AUTHORITY, url, key, project_ref))


def validate_test_database_authorization(
    authorization: TestDatabaseAuthorization | None,
    *,
    url: str | None = None,
    key: str | None = None,
) -> TestDatabaseAuthorization:
    """Validate capability provenance and, when provided, exact target binding."""
    if (
        not is_test_runtime()
        or not isinstance(authorization, TestDatabaseAuthorization)
        or not isinstance(authorization._authority, tuple)
        or len(authorization._authority) != 4
        or authorization._authority[0] is not _AUTHORITY
        or authorization._authority[1:] != (
            authorization.url, authorization.key, authorization.project_ref
        )
    ):
        raise UnsafeTestDatabaseConfiguration("A validated test-database capability is required")
    if url is not None and url.rstrip("/") != authorization.url.rstrip("/"):
        raise UnsafeTestDatabaseConfiguration("Client URL differs from its authorized test project")
    if key is not None and not hmac.compare_digest(key, authorization.key):
        raise UnsafeTestDatabaseConfiguration("Client credential differs from its authorized test project")
    return authorization


def create_supabase_client(
    url: str,
    key: str,
    *,
    authorization: TestDatabaseAuthorization | None = None,
):
    """Single Supabase SDK construction boundary for application and tests."""
    if is_test_runtime():
        validate_test_database_authorization(authorization, url=url, key=key)
    from supabase import create_client

    return create_client(url, key)


def validate_supabase_client(client, authorization: TestDatabaseAuthorization | None = None) -> bool:
    """Reject a real SDK client unless its endpoint and key match authorization.

    Plain injected fakes remain valid test doubles; this check governs actual
    Supabase SDK clients installed into shared test persistence paths.
    """
    if not is_test_runtime():
        return False
    from supabase import AsyncClient, Client
    if not isinstance(client, (Client, AsyncClient)):
        return False
    capability = validate_test_database_authorization(authorization)
    actual_url = str(client.supabase_url).rstrip("/")
    validate_test_database_authorization(
        capability,
        url=actual_url,
        key=client.supabase_key,
    )
    return True
