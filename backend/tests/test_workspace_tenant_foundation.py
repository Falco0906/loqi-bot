"""SaaS-2.1 — Tenant Architecture Foundation regression tests.

Covers the canonical tenant architecture:
    authenticated identity_user -> canonical membership -> canonical
    organization -> canonical durable workspace -> workspace-owned resources

The key property under test: the durable workspace owns a real uuid minted for
itself and is resolved by the durable owner relationship (owner_user_id) —
NEVER from workflow_sessions.id, web-session ids, access tokens, or client
ids. A recreated workflow session or a freshly-recreated repository must not
change the workspace identity.

Also covers: single canonical organization per completed account (onboarding
reuses, never duplicates), idempotent signup, restart/redeploy resolution, the
isolation foundation (workspace lookup is tied to the authenticated owner, an
arbitrary workflow-session id is not accepted as tenant identity), and the
identity membership status <-> durable DB CHECK compatibility mapping.

All persistence is exercised against fake/in-memory PostgREST clients. No
production data is touched.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from services.identity.models import Membership, MembershipStatus, Organization, User
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
from services.onboarding.services import LifecycleService, OnboardingService
from services.onboarding.repositories import (
    InMemoryLifecycleRepository,
    InMemoryOnboardingSessionRepository,
)
from services.persistence import (
    RepositoryProvider,
    reset_connection_manager,
    reset_repository_provider,
    set_connection_manager,
    set_repository_provider,
)
from services.persistence.database import SupabaseConnectionManager
from services.persistence.launch import WorkspaceRepository
from services.persistence.repositories import (
    SupabaseEmailIdentityRepository,
    SupabaseIdentityMembershipRepository,
    SupabaseIdentityOrganizationRepository,
    SupabasePasswordCredentialRepository,
)
from services.persistence.repositories.user_repository import SupabaseUserRepository
from services.security.crypto.crypto_service import get_crypto_service

EMAIL = "tenant-foundation@example.com"
PASSWORD = "StrongPass!123"
ORG_NAME = "Foundation Co"


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


@pytest.fixture(autouse=True)
def _reset():
    reset_repository_provider()
    reset_connection_manager()
    yield
    reset_repository_provider()
    reset_connection_manager()


def _attach_client(db):
    """Point the global launch repos + workspace_state reads at a fake DB."""
    cm = SupabaseConnectionManager(url="http://test", key="test-key")
    cm._client = db
    set_connection_manager(cm)


def _durable_repos(db):
    from services.identity.repositories import (
        InMemoryEmailIdentityRepository,
        InMemoryMembershipRepository,
        InMemoryOrganizationRepository,
        InMemoryPasswordCredentialRepository,
        InMemoryUserRepository,
    )
    return {
        "user_repo": SupabaseUserRepository(),
        "ei_repo": SupabaseEmailIdentityRepository(),
        "pc_repo": SupabasePasswordCredentialRepository(),
        "org_repo": SupabaseIdentityOrganizationRepository(),
        "mem_repo": SupabaseIdentityMembershipRepository(),
        "user_repo_inmem": InMemoryUserRepository(),
        "ei_repo_inmem": InMemoryEmailIdentityRepository(),
        "pc_repo_inmem": InMemoryPasswordCredentialRepository(),
        "org_repo_inmem": InMemoryOrganizationRepository(),
        "mem_repo_inmem": InMemoryMembershipRepository(),
    }


def _supabase_repos(db):
    from services.identity.repositories import (
        InMemoryEmailIdentityRepository,
        InMemoryMembershipRepository,
        InMemoryOrganizationRepository,
        InMemoryPasswordCredentialRepository,
        InMemoryUserRepository,
    )
    durable = {
        "user_repo": SupabaseUserRepository(),
        "ei_repo": SupabaseEmailIdentityRepository(),
        "pc_repo": SupabasePasswordCredentialRepository(),
        "org_repo": SupabaseIdentityOrganizationRepository(),
        "mem_repo": SupabaseIdentityMembershipRepository(),
    }
    for repo in durable.values():
        repo._client = lambda db=db: db
    return durable


def _build_auth_service(db):
    durable = _supabase_repos(db)
    crypto = get_crypto_service()
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


async def _complete_signup(svc):
    result = await svc.begin_registration(EMAIL)
    await svc.verify_email(result.raw_token)
    return await svc.complete_registration(
        result.registration_session.id, "Ada", PASSWORD, ORG_NAME,
    )


# ─── Workspace identity (durable, independent of workflow sessions) ──────

class TestWorkspaceIdentity:

    @pytest.mark.asyncio
    async def test_workspace_gets_own_durable_uuid_not_workflow_session_id(self):
        from services.workspace_state import ensure_workspace
        db = FakeClient({
            "workflow_sessions": [
                {"id": "ws-session-1", "user_id": "u1", "channel": "workspace", "session_key": "u1"},
            ],
        })
        _attach_client(db)
        set_repository_provider(RepositoryProvider.SUPABASE)
        from unittest.mock import patch
        with patch("services.workspace_state.get_supabase_client", return_value=db):
            ws_id = ensure_workspace("u1", organization_id="org-1")
        UUID(ws_id)  # a real uuid
        assert ws_id != "ws-session-1"
        assert db.tables["workspaces"][0]["id"] == ws_id
        assert db.tables["workspaces"][0]["owner_user_id"] == "u1"
        assert db.tables["workspaces"][0]["organization_id"] == "org-1"

    @pytest.mark.asyncio
    async def test_recreating_workflow_session_does_not_change_workspace_id(self):
        from services.workspace_state import ensure_workspace
        db = FakeClient({
            "workflow_sessions": [
                {"id": "ws-old", "user_id": "u1", "channel": "workspace", "session_key": "u1"},
            ],
        })
        _attach_client(db)
        set_repository_provider(RepositoryProvider.SUPABASE)
        from unittest.mock import patch
        with patch("services.workspace_state.get_supabase_client", return_value=db):
            first = ensure_workspace("u1", organization_id="org-1")
        # Simulate a workflow-session recreation (new id) + restart.
        db.tables["workflow_sessions"] = [
            {"id": "ws-new", "user_id": "u1", "channel": "workspace", "session_key": "u1"},
        ]
        reset_connection_manager()
        _attach_client(db)
        with patch("services.workspace_state.get_supabase_client", return_value=db):
            second = ensure_workspace("u1", organization_id="org-1")
        assert second == first
        assert len(db.tables["workspaces"]) == 1

    @pytest.mark.asyncio
    async def test_recreated_repository_resolves_same_workspace(self):
        from services.workspace_state import ensure_workspace
        db = FakeClient()
        _attach_client(db)
        set_repository_provider(RepositoryProvider.SUPABASE)
        from unittest.mock import patch
        with patch("services.workspace_state.get_supabase_client", return_value=db):
            ws_id = ensure_workspace("u1", organization_id="org-1")
        # A brand-new repository instance (restart/redeploy) resolves the same
        # workspace through the durable owner relationship.
        fresh = WorkspaceRepository()
        fresh._client = lambda: db
        found = await fresh.find_active_by_owner("u1")
        assert found is not None
        assert found.id == ws_id


# ─── Organization -> Workspace relationship & onboarding reuse ───────────

class TestOrganizationWorkspaceRelationship:

    @pytest.mark.asyncio
    async def test_canonical_organization_owns_workspace(self):
        from services.workspace_state import ensure_workspace
        db = FakeClient()
        _attach_client(db)
        set_repository_provider(RepositoryProvider.SUPABASE)
        from unittest.mock import patch
        with patch("services.workspace_state.get_supabase_client", return_value=db):
            ws_id = ensure_workspace("u1", organization_id="org-123")
        ws = db.tables["workspaces"][0]
        assert ws["id"] == ws_id
        assert ws["organization_id"] == "org-123"
        assert ws["owner_user_id"] == "u1"
        assert db.tables["workspace_members"][0]["workspace_id"] == ws_id

    @pytest.mark.asyncio
    async def test_workspace_resolves_org_from_membership_when_not_supplied(self):
        from services.workspace_state import ensure_workspace
        db = FakeClient({
            "memberships": [
                {"user_id": "u1", "organization_id": "org-from-membership", "status": "active"},
            ],
        })
        _attach_client(db)
        set_repository_provider(RepositoryProvider.SUPABASE)
        from unittest.mock import patch
        with patch("services.workspace_state.get_supabase_client", return_value=db):
            ws_id = ensure_workspace("u1")
        assert db.tables["workspaces"][0]["organization_id"] == "org-from-membership"
        assert db.tables["workspaces"][0]["id"] == ws_id

    @pytest.mark.asyncio
    async def test_onboarding_reuses_existing_org_never_creates_second(self, monkeypatch):
        from services.organizations.models import (
            Membership as OrgMembership,
            MembershipRole,
            MembershipStatus,
            Organization as OrgOrg,
        )
        from services.organizations.repositories import (
            InMemoryMembershipRepository,
            InMemoryOrganizationRepository,
        )
        from services.organizations.services import OrganizationService as OrgOrgService
        org_repo = InMemoryOrganizationRepository()
        mem_repo = InMemoryMembershipRepository()
        org_svc = OrgOrgService(org_repo, mem_repo)
        # Pre-seed a canonical org + owner membership (as signup completion does).
        existing = OrgOrg(id="org-existing", name="Existing", slug="existing", created_by="u1")
        await org_repo.save(existing)
        await mem_repo.save(OrgMembership(
            organization_id="org-existing", user_id="u1",
            role=MembershipRole.OWNER, status=MembershipStatus.ACTIVE,
        ))

        from services.identity.repositories import InMemoryEmailIdentityRepository, InMemoryUserRepository
        from services.identity.services import UserService
        user_svc = UserService(InMemoryUserRepository(), InMemoryEmailIdentityRepository())
        onboarding = OnboardingService(
            lifecycle_service=LifecycleService(InMemoryLifecycleRepository()),
            session_repo=InMemoryOnboardingSessionRepository(),
            org_service=org_svc,
            user_service=user_svc,
        )
        await user_svc.save_user(User(id="u1", display_name="Ada"))

        calls = []
        monkeypatch.setattr(
            "services.workspace_state.ensure_workspace",
            lambda *a, **kw: calls.append((a, kw)) or "ws-reused",
        )
        result = await onboarding.create_workspace_and_finalize("u1", {
            "workspace_name": "Acme", "slug": "acme",
        })
        # The existing org is reused — no second org row created.
        orgs = await org_repo.find_owned_by("u1")
        assert len(orgs) == 1
        assert result["organization_id"] == "org-existing"
        assert len(calls) == 1
        assert calls[0][1]["organization_id"] == "org-existing"

    @pytest.mark.asyncio
    async def test_repeated_onboarding_reuses_same_org_and_workspace(self, monkeypatch):
        from services.organizations.models import (
            Membership as OrgMembership,
            MembershipRole,
            MembershipStatus,
            Organization as OrgOrg,
        )
        from services.organizations.repositories import (
            InMemoryMembershipRepository,
            InMemoryOrganizationRepository,
        )
        from services.organizations.services import OrganizationService as OrgOrgService
        from services.identity.repositories import InMemoryEmailIdentityRepository, InMemoryUserRepository
        from services.identity.services import UserService
        org_repo = InMemoryOrganizationRepository()
        mem_repo = InMemoryMembershipRepository()
        org_svc = OrgOrgService(org_repo, mem_repo)
        user_svc = UserService(InMemoryUserRepository(), InMemoryEmailIdentityRepository())
        onboarding = OnboardingService(
            lifecycle_service=LifecycleService(InMemoryLifecycleRepository()),
            session_repo=InMemoryOnboardingSessionRepository(),
            org_service=org_svc,
            user_service=user_svc,
        )
        await user_svc.save_user(User(id="u1", display_name="Ada"))
        monkeypatch.setattr(
            "services.workspace_state.ensure_workspace",
            lambda *a, **kw: "ws-1",
        )
        first = await onboarding.create_workspace_and_finalize("u1", {"workspace_name": "Acme"})
        second = await onboarding.create_workspace_and_finalize("u1", {"workspace_name": "Acme"})
        assert first["organization_id"] == second["organization_id"]
        assert len(await org_repo.find_owned_by("u1")) == 1
        assert len(await mem_repo.find_by_user_id("u1")) == 1


# ─── Signup: exactly one org / membership / workspace, idempotent ─────────

class TestSignupCreatesSingleTenant:

    @pytest.mark.asyncio
    async def test_signup_creates_one_org_one_membership_one_workspace(self):
        db = FakeClient()
        _attach_client(db)
        set_repository_provider(RepositoryProvider.SUPABASE)
        from unittest.mock import patch
        with patch("services.workspace_state.get_supabase_client", return_value=db):
            svc = _build_auth_service(db)
            completed = await _complete_signup(svc)

        orgs = db.tables.get("organizations", [])
        mems = db.tables.get("memberships", [])
        wss = db.tables.get("workspaces", [])
        assert len(orgs) == 1
        assert len(mems) == 1
        assert mems[0]["status"] == "active"
        assert len(wss) == 1
        assert wss[0]["owner_user_id"] == completed.user.id
        assert wss[0]["organization_id"] == orgs[0]["id"]

    @pytest.mark.asyncio
    async def test_signup_retry_keeps_single_tenant_and_same_workspace(self):
        db = FakeClient()
        _attach_client(db)
        set_repository_provider(RepositoryProvider.SUPABASE)
        from unittest.mock import patch
        with patch("services.workspace_state.get_supabase_client", return_value=db):
            svc = _build_auth_service(db)
            reg = await svc.begin_registration(EMAIL)
            await svc.verify_email(reg.raw_token)
            await svc.complete_registration(
                reg.registration_session.id, "Ada", PASSWORD, ORG_NAME,
            )
            ws_before = db.tables["workspaces"][0]["id"]
            # Retry completion on the already-completed registration session.
            # Idempotent: recovers the completed account, never duplicates.
            await svc.complete_registration(
                reg.registration_session.id, "Ada", PASSWORD, ORG_NAME,
            )

        assert len(db.tables.get("organizations", [])) == 1
        assert len(db.tables.get("memberships", [])) == 1
        assert len(db.tables.get("workspaces", [])) == 1
        assert db.tables["workspaces"][0]["id"] == ws_before

# ─── Restart/redeploy: user -> membership -> org -> workspace ────────────

class TestRestartResolution:

    @pytest.mark.asyncio
    async def test_resolves_chain_after_recreated_services(self):
        db = FakeClient()
        _attach_client(db)
        set_repository_provider(RepositoryProvider.SUPABASE)
        from unittest.mock import patch
        with patch("services.workspace_state.get_supabase_client", return_value=db):
            completed = await _complete_signup(_build_auth_service(db))
            org_id = db.tables["organizations"][0]["id"]
            ws_id = db.tables["workspaces"][0]["id"]

        # Restart simulation: recreate the service stack over the same DB.
        reset_connection_manager()
        _attach_client(db)
        set_repository_provider(RepositoryProvider.SUPABASE)
        from services.workspace_state import _async_workspace
        with patch("services.workspace_state.get_supabase_client", return_value=db):
            resolved_ws = await _async_workspace(completed.user.id)
        assert resolved_ws == ws_id

        fresh_mem = SupabaseIdentityMembershipRepository()
        fresh_mem._client = lambda: db
        mems = await fresh_mem.find_active_by_user_id(completed.user.id)
        assert len(mems) == 1
        assert mems[0].organization_id == org_id


# ─── Isolation foundation ────────────────────────────────────────────────

class TestIsolationFoundation:

    @pytest.mark.asyncio
    async def test_workspace_lookup_is_tied_to_owner_not_workflow_session(self):
        from services.workspace_state import ensure_workspace
        db = FakeClient({
            "workspaces": [
                {"id": "ws-b-owner", "owner_user_id": "user-b", "organization_id": "org-b"},
            ],
            "workflow_sessions": [
                {"id": "ws-b-owner", "user_id": "user-a", "channel": "workspace", "session_key": "user-a"},
            ],
        })
        _attach_client(db)
        set_repository_provider(RepositoryProvider.SUPABASE)
        from unittest.mock import patch
        with patch("services.workspace_state.get_supabase_client", return_value=db):
            # User A resolves their OWN workspace (a new one), NOT the workspace
            # belonging to user B — even though a workflow_sessions row shares B's
            # workspace id. A workflow-session id is never tenant authority.
            ws_a = ensure_workspace("user-a", organization_id="org-a")
        assert ws_a != "ws-b-owner"
        created = [w for w in db.tables["workspaces"] if w["owner_user_id"] == "user-a"]
        assert created and created[0]["id"] == ws_a


# ─── Canonical membership status <-> durable CHECK agreement ────────────

class TestMembershipStatusCompatibility:

    @pytest.mark.asyncio
    async def test_status_writes_conform_to_db_check(self):
        db = FakeClient()
        mem_repo = SupabaseIdentityMembershipRepository()
        mem_repo._client = lambda: db
        await mem_repo.save(Membership(
            user_id="u1", organization_id="o1", role="owner", status=MembershipStatus.ACTIVE,
        ))
        await mem_repo.save(Membership(
            user_id="u2", organization_id="o1", role="member", status=MembershipStatus.PENDING,
        ))
        await mem_repo.save(Membership(
            user_id="u3", organization_id="o1", role="member", status=MembershipStatus.REMOVED,
        ))
        await mem_repo.save(Membership(
            user_id="u4", organization_id="o1", role="member", status=MembershipStatus.LEFT,
        ))
        statuses = {r["user_id"]: r["status"] for r in db.tables["memberships"]}
        # Canonical values are persisted as-is and all satisfy the 025 CHECK.
        assert statuses["u1"] == "active"
        assert statuses["u2"] == "pending"
        assert statuses["u3"] == "removed"
        assert statuses["u4"] == "left"

    @pytest.mark.asyncio
    async def test_status_reads_round_trip_and_login_gate_respects(self):
        db = FakeClient({"memberships": [
            {"id": str(uuid4()), "user_id": "u1", "organization_id": "o1",
             "role": "owner", "status": "active", "joined_at": _FUTURE, "invited_by": ""},
            {"id": str(uuid4()), "user_id": "u2", "organization_id": "o1",
             "role": "member", "status": "pending", "joined_at": _FUTURE, "invited_by": ""},
            {"id": str(uuid4()), "user_id": "u3", "organization_id": "o1",
             "role": "member", "status": "removed", "joined_at": _FUTURE, "invited_by": ""},
            {"id": str(uuid4()), "user_id": "u4", "organization_id": "o1",
             "role": "member", "status": "left", "joined_at": _FUTURE, "invited_by": ""},
        ]})
        mem_repo = SupabaseIdentityMembershipRepository()
        mem_repo._client = lambda: db
        active = await mem_repo.find_active_by_user_id("u1")
        assert len(active) == 1 and active[0].status == MembershipStatus.ACTIVE
        for uid, expected in (("u2", MembershipStatus.PENDING),
                              ("u3", MembershipStatus.REMOVED),
                              ("u4", MembershipStatus.LEFT)):
            rows = await mem_repo.find_by_user_id(uid)
            assert rows[0].status == expected
            assert rows[0].is_active is False
