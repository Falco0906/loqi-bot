"""Regression: a completed production account must survive a backend restart.

Production bug: identity organization + owner membership were created only in
in-memory repositories, so login() raised `InvalidCredentialsException("No
active organization membership")` for a completed account after any restart or
redeploy. These tests drive the REAL Supabase-backed identity repositories
against a fake PostgREST client, simulate a restart by re-creating the services
with fresh in-memory lifecycle repositories, and assert that login and
onboarding resume still work from durable storage.

- Test A: completed account logs in after a restart (full register→login).
- Test B: organization + membership rows are durable (recreated repos).
- Test C: onboarding resumes from the durable wizard step after restart.
- Test D: a failed Google Workspace connection stays retryable (same step).
- Test E: an existing durable account logs in without any completion state.
- Test F: cross-user isolation — memberships/orgs never leak between users.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.identity.models import Membership, Organization, User
from services.identity.providers import ConsoleEmailProvider
from services.identity.repositories import (
    InMemoryExternalIdentityRepository,
    InMemoryPasswordResetRepository,
    InMemoryRefreshTokenRepository,
    InMemoryRegistrationSessionRepository,
    InMemorySessionRepository,
    InMemoryVerificationTokenRepository,
)
from services.identity.services import (
    MembershipService,
    OrganizationService,
    PasswordService,
    SessionService,
    TokenService,
    UserService,
    VerificationService,
)
from services.identity.services.auth_service import AuthService
from services.onboarding.services import (
    LifecycleService,
    OnboardingService,
)
from services.onboarding.repositories import (
    InMemoryLifecycleRepository,
    InMemoryOnboardingSessionRepository,
)
from services.persistence.repositories import (
    SupabaseEmailIdentityRepository,
    SupabaseIdentityMembershipRepository,
    SupabaseIdentityOrganizationRepository,
    SupabasePasswordCredentialRepository,
)
from services.persistence.repositories.user_repository import SupabaseUserRepository
from services.security.crypto.crypto_service import get_crypto_service

EMAIL = "durable-owner@example.com"
PASSWORD = "StrongPass!123"
ORG_NAME = "Durable Co"


class _Row:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, db, table):
        self._db = db
        self._table = table
        self._filters: list[tuple[str, str, str]] = []
        self._limit = None
        self._op = "select"
        self._payload = None

    def select(self, *_a):
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, str(val)))
        return self

    def is_(self, col, val):
        self._filters.append(("is", col, str(val)))
        return self

    def gt(self, col, val):
        self._filters.append(("gt", col, str(val)))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def order(self, *_a, **_k):
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def execute(self):
        rows = [dict(r) for r in self._db.tables.get(self._table, [])]
        for kind, col, val in self._filters:
            if kind == "eq":
                rows = [r for r in rows if str(r.get(col, "")) == val]
            elif kind == "is":
                rows = [r for r in rows if r.get(col) is None]
            elif kind == "gt":
                rows = [r for r in rows if str(r.get(col, "")) > val]

        if self._op == "select":
            if self._limit:
                rows = rows[: self._limit]
            return _Row(rows)

        if self._op == "delete":
            ids = {r.get("id") for r in rows}
            self._db.tables[self._table] = [
                r for r in self._db.tables.get(self._table, []) if r.get("id") not in ids
            ]
            return _Row([])

        if self._op == "insert":
            stored = [dict(r) for r in self._db.tables.setdefault(self._table, [])]
            stored.append(self._payload)
            self._db.tables[self._table] = stored
            return _Row([self._payload])

        updated = []
        for r in self._db.tables.get(self._table, []):
            if any(str(r.get(col, "")) == val for kind, col, val in self._filters if kind == "eq"):
                updated.append({**r, **self._payload})
            else:
                updated.append(r)
        self._db.tables[self._table] = updated
        return _Row(updated)


class FakeClient:
    def __init__(self, tables=None):
        self.tables = {k: [dict(r) for r in v] for k, v in (tables or {}).items()}

    def table(self, name):
        return _Query(self, name)


def _iso(dt=None):
    return (dt or datetime.now(timezone.utc)).isoformat()


_FUTURE = _iso(datetime.now(timezone.utc) + timedelta(minutes=5))


def _durable_repos(db):
    """Real Supabase-backed identity repos pointing at the fake durable DB."""
    repos = {
        "user_repo": SupabaseUserRepository(),
        "ei_repo": SupabaseEmailIdentityRepository(),
        "pc_repo": SupabasePasswordCredentialRepository(),
        "org_repo": SupabaseIdentityOrganizationRepository(),
        "mem_repo": SupabaseIdentityMembershipRepository(),
    }
    for repo in repos.values():
        repo._client = lambda db=db: db
    return repos


def _build_auth_service(db=None):
    """Build an AuthService like api._build_auth_service but over the fake DB
    for the durable repositories and fresh in-memory lifecycle repositories."""
    if db is not None:
        durable = _durable_repos(db)
    else:
        from services.identity.repositories import (
            InMemoryEmailIdentityRepository,
            InMemoryMembershipRepository,
            InMemoryOrganizationRepository,
            InMemoryPasswordCredentialRepository,
            InMemoryUserRepository,
        )
        durable = {
            "user_repo": InMemoryUserRepository(),
            "ei_repo": InMemoryEmailIdentityRepository(),
            "pc_repo": InMemoryPasswordCredentialRepository(),
            "org_repo": InMemoryOrganizationRepository(),
            "mem_repo": InMemoryMembershipRepository(),
        }

    crypto = get_crypto_service()
    # Shared in-memory lifecycle repositories (mirrors api._build_auth_service,
    # which wires one instance through verification/session/token services).
    vt_repo = InMemoryVerificationTokenRepository()
    reg_session_repo = InMemoryRegistrationSessionRepository()
    session_repo = InMemorySessionRepository()
    rt_repo = InMemoryRefreshTokenRepository()

    user_svc = UserService(durable["user_repo"], durable["ei_repo"])
    org_svc = OrganizationService(durable["org_repo"], durable["mem_repo"])
    mem_svc = MembershipService(durable["mem_repo"], durable["user_repo"], durable["org_repo"])
    ver_svc = VerificationService(vt_repo, durable["ei_repo"], crypto)
    pwd_svc = PasswordService(durable["pc_repo"], durable["user_repo"], crypto)
    ses_svc = SessionService(session_repo, rt_repo)
    tok_svc = TokenService(rt_repo, session_repo, crypto)

    return AuthService(
        email_provider=ConsoleEmailProvider(),
        crypto=crypto,
        registration_session_repo=reg_session_repo,
        verification_token_repo=vt_repo,
        email_identity_repo=durable["ei_repo"],
        refresh_token_repo=rt_repo,
        user_svc=user_svc,
        org_svc=org_svc,
        membership_svc=mem_svc,
        verification_svc=ver_svc,
        password_svc=pwd_svc,
        session_svc=ses_svc,
        token_svc=tok_svc,
        app_url="http://localhost:3000",
        external_identity_repo=InMemoryExternalIdentityRepository(),
        password_reset_repo=InMemoryPasswordResetRepository(),
    )


async def _complete_account(svc):
    result = await svc.begin_registration(EMAIL)
    await svc.verify_email(result.raw_token)
    return await svc.complete_registration(
        result.registration_session.id, "Ada", PASSWORD, ORG_NAME,
    )


class TestLoginSurvivesRestart:

    @pytest.mark.asyncio
    async def test_completed_account_logs_in_after_restart(self):
        db = FakeClient()
        svc_before = _build_auth_service(db=db)
        completed = await _complete_account(svc_before)
        org_id = completed.organization.id
        assert await _durable_repos(db)["mem_repo"].find_by_user_id(completed.user.id)

        # Simulate a restart: fresh service, fresh in-memory lifecycle repos,
        # but the SAME durable DB. login() must resolve the durable membership.
        svc_after = _build_auth_service(db=db)
        login = await svc_after.login(EMAIL, PASSWORD)
        assert login.session.organization_id == org_id

    @pytest.mark.asyncio
    async def test_login_fails_without_durable_membership(self):
        db = FakeClient()
        svc = _build_auth_service(db=db)
        result = await svc.begin_registration(EMAIL)
        await svc.verify_email(result.raw_token)
        await svc.complete_registration(result.registration_session.id, "Ada", PASSWORD, ORG_NAME)

        # Simulate the pre-fix bug: drop the durable membership rows.
        db.tables["memberships"] = []
        from services.identity.exceptions import InvalidCredentialsException
        with pytest.raises(InvalidCredentialsException) as exc:
            await svc.login(EMAIL, PASSWORD)
        assert "No active organization membership" in str(exc.value)


class TestDurableMembershipRepository:

    @pytest.mark.asyncio
    async def test_organization_survives_repository_recreation(self):
        db = FakeClient()
        org = Organization(name=ORG_NAME, slug="durable-co", owner_id="owner-1")
        saved = await _durable_repos(db)["org_repo"].save(org)
        assert db.tables["organizations"][0]["created_by"] == "owner-1"

        # Recreate the repository (restart) over the same DB.
        fresh = SupabaseIdentityOrganizationRepository()
        fresh._client = lambda: db
        got = await fresh.get(saved.id)
        assert got is not None
        assert got.owner_id == "owner-1"
        assert got.name == ORG_NAME
        by_slug = await fresh.find_by_slug("durable-co")
        assert by_slug is not None and by_slug.id == saved.id
        assert [o.id for o in await fresh.find_by_owner_id("owner-1")] == [saved.id]

    @pytest.mark.asyncio
    async def test_membership_survives_repository_recreation(self):
        db = FakeClient()
        org = Organization(name=ORG_NAME, slug="durable-co", owner_id="owner-1")
        org = await _durable_repos(db)["org_repo"].save(org)
        membership = Membership(
            user_id="owner-1", organization_id=org.id, role="owner",
        )
        membership.activate()
        await _durable_repos(db)["mem_repo"].save(membership)
        row = db.tables["memberships"][0]
        assert row["status"] == "active"
        assert "joined_at" in row
        assert "invited_at" not in row
        assert "accepted_at" not in row

        fresh = SupabaseIdentityMembershipRepository()
        fresh._client = lambda: db
        found = await fresh.find_by_user_id("owner-1")
        assert found and found[0].is_active is True
        assert found[0].organization_id == org.id
        assert found[0].role == "owner"
        active = await fresh.find_active_by_user_id("owner-1")
        assert [m.id for m in active] == [membership.id]

    @pytest.mark.asyncio
    async def test_org_slug_collision_gets_unique_suffix(self):
        db = FakeClient()
        durable = _durable_repos(db)
        org_svc = OrganizationService(durable["org_repo"], durable["mem_repo"])
        org1, _, _ = await org_svc.create_organization("Durable Co", "owner-1")
        org2, _, _ = await org_svc.create_organization("Durable Co", "owner-2")
        assert org1.slug == "durable-co"
        assert org2.slug == "durable-co-1"
        assert org1.id != org2.id
        slugs = {o["slug"] for o in db.tables["organizations"]}
        assert slugs == {"durable-co", "durable-co-1"}


class TestOnboardingResumesAfterRestart:

    def _wired(self, db, user_id):
        from services.identity.repositories import InMemoryEmailIdentityRepository
        durable = _durable_repos(db)
        user_svc = UserService(durable["user_repo"], InMemoryEmailIdentityRepository())
        lifecycle_svc = LifecycleService(InMemoryLifecycleRepository())
        return OnboardingService(
            lifecycle_service=lifecycle_svc,
            session_repo=InMemoryOnboardingSessionRepository(),
            user_service=user_svc,
        )

    def _seed_user(self, db, user_id, step):
        import json
        db.tables.setdefault("identity_users", [])
        db.tables["identity_users"].append({
            "id": user_id,
            "display_name": "Ada",
            "email": EMAIL,
            "onboarding_completed_at": None,
            "onboarding_data": json.dumps({"onboarding_step": step}),
            "created_at": _FUTURE,
            "updated_at": _FUTURE,
        })

    @pytest.mark.asyncio
    async def test_wizard_step_resumes_after_restart(self):
        user_id = "resume-user-1"
        db = FakeClient()
        self._seed_user(db, user_id, "workspace-connection")

        svc = self._wired(db, user_id)
        progress = await svc.get_progress(user_id)
        assert progress["onboarding_complete"] is False
        assert progress["current_step"] == "ONBOARDING_WIZARD"
        assert progress["next_route"] == "/onboarding"
        assert progress["lifecycle_state"] == "ONBOARDING_COMPLETE"
        assert progress["progress_percentage"] == 60
        assert "PROFILE_SETUP" in progress["completed_steps"]
        assert "PLAN_SELECTION" in progress["remaining_steps"]

    @pytest.mark.asyncio
    async def test_failed_gmail_connection_stays_retryable(self):
        user_id = "resume-user-2"
        db = FakeClient()
        self._seed_user(db, user_id, "workspace-connection")

        svc2 = self._wired(db, user_id)
        progress = await svc2.get_progress(user_id)
        assert progress["current_step"] == "ONBOARDING_WIZARD"
        # Durable wizard data still exposes the exact step so the frontend can
        # retry the failed Google Workspace connection at the same step.
        wizard = await svc2.get_wizard_data(user_id)
        assert wizard.get("onboarding_step") == "workspace-connection"

    @pytest.mark.asyncio
    async def test_completed_account_does_not_reset(self):
        import json
        user_id = "resume-user-3"
        db = FakeClient()
        db.tables.setdefault("identity_users", [])
        db.tables["identity_users"].append({
            "id": user_id,
            "display_name": "Ada",
            "email": EMAIL,
            "onboarding_completed_at": _iso(),
            "onboarding_data": json.dumps({"onboarding_step": "completed"}),
            "created_at": _FUTURE,
            "updated_at": _FUTURE,
        })

        svc = self._wired(db, user_id)
        progress = await svc.get_progress(user_id)
        assert progress["onboarding_complete"] is True
        assert progress["next_route"] == "/dashboard"


class TestExistingDurableAccountLogin:

    @pytest.mark.asyncio
    async def test_preprovisioned_account_logs_in(self):
        db = FakeClient()
        user_id = "existing-user"
        crypto = get_crypto_service()
        password_hash = crypto.hash_password(PASSWORD)

        # Durable account rows as they exist after completion + restart.
        db.tables["identity_users"] = [{
            "id": user_id, "display_name": "Ada", "email": EMAIL,
            "onboarding_completed_at": _iso(),
            "onboarding_data": None, "created_at": _FUTURE, "updated_at": _FUTURE,
        }]
        db.tables["email_identities"] = [{
            "id": "00000000-0000-4000-8000-0000000000a1", "user_id": user_id,
            "email": EMAIL, "is_verified": True, "is_primary": True,
            "verified_at": _FUTURE, "created_at": _FUTURE,
        }]
        db.tables["password_credentials"] = [{
            "id": "00000000-0000-4000-8000-0000000000a2", "user_id": user_id,
            "password_hash": str(password_hash),
            "created_at": _FUTURE, "last_changed_at": _FUTURE,
        }]
        org = Organization(name="Existing Org", slug="existing-org", owner_id=user_id)
        org = await _durable_repos(db)["org_repo"].save(org)
        membership = Membership(user_id=user_id, organization_id=org.id, role="owner")
        membership.activate()
        await _durable_repos(db)["mem_repo"].save(membership)

        svc = _build_auth_service(db=db)
        login = await svc.login(EMAIL, PASSWORD)
        assert login.session.organization_id == org.id


class TestCrossUserIsolation:

    @pytest.mark.asyncio
    async def test_memberships_do_not_leak_between_users(self):
        db = FakeClient()
        crypto = get_crypto_service()
        durable = _durable_repos(db)

        orgs = {}
        for idx, (uid, email) in enumerate(
            [("user-a", "a@example.com"), ("user-b", "b@example.com")],
        ):
            db.tables.setdefault("identity_users", []).append({
                "id": uid, "display_name": f"User {idx}", "email": email,
                "onboarding_completed_at": None,
                "onboarding_data": None, "created_at": _FUTURE, "updated_at": _FUTURE,
            })
            db.tables.setdefault("email_identities", []).append({
                "id": f"00000000-0000-4000-8000-00000000000{idx+1}",
                "user_id": uid, "email": email, "is_verified": True,
                "is_primary": True, "verified_at": _FUTURE, "created_at": _FUTURE,
            })
            db.tables.setdefault("password_credentials", []).append({
                "id": f"00000000-0000-4000-8000-00000000000{idx+3}",
                "user_id": uid, "password_hash": str(crypto.hash_password(PASSWORD)),
                "created_at": _FUTURE, "last_changed_at": _FUTURE,
            })
            org = Organization(name=f"Org {idx}", slug=f"org-{idx}", owner_id=uid)
            org = await durable["org_repo"].save(org)
            orgs[uid] = org.id
            membership = Membership(user_id=uid, organization_id=org.id, role="owner")
            membership.activate()
            await durable["mem_repo"].save(membership)

        svc = _build_auth_service(db=db)
        login_a = await svc.login("a@example.com", PASSWORD)
        login_b = await svc.login("b@example.com", PASSWORD)
        assert login_a.session.organization_id == orgs["user-a"]
        assert login_b.session.organization_id == orgs["user-b"]
        assert login_a.session.organization_id != login_b.session.organization_id

        mems_a = await durable["mem_repo"].find_by_user_id("user-a")
        assert [m.organization_id for m in mems_a] == [orgs["user-a"]]
        mems_b = await durable["mem_repo"].find_by_user_id("user-b")
        assert [m.organization_id for m in mems_b] == [orgs["user-b"]]
