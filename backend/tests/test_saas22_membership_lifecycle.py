"""SaaS-2.2 — Canonical Membership Lifecycle & Unification.

Establishes that there is ONE canonical membership lifecycle vocabulary
(pending / active / removed / left) shared by the identity model, the durable
organizations/memberships persistence model, and the 025 DB CHECK constraint.
The pre-SaaS-2.2 identity enum (active/invited/suspended) is reconciled onto
this model: invited -> pending, suspended -> removed; the SaaS-2.1 status
compatibility adapter is removed (no longer needed because the enum and the
DB now agree).

Covers (per the SaaS-2.2 brief):
  A. canonical status model / round-trip agreement
  B. lifecycle transitions + invalid-transition rejection
  C. login authorization by canonical active state
  D. owner membership invariant (exactly one active owner)
  E. invitation acceptance converges on the canonical membership row
  F. restart durability
  G. tenant/organization isolation
  H. repository contract (domain models, no raw dict escapes)
  I. regression (existing suites run separately)

All persistence uses fake/in-memory clients; no production data is touched.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from services.identity.exceptions import (
    InvalidMembershipTransitionException,
    MembershipAlreadyExistsException,
)
from services.identity.models import Membership, MembershipStatus, Organization, User
from services.identity.providers import ConsoleEmailProvider
from services.identity.repositories import (
    InMemoryExternalIdentityRepository,
    InMemoryMembershipRepository,
    InMemoryOrganizationRepository,
    InMemoryPasswordResetRepository,
    InMemoryRefreshTokenRepository,
    InMemoryRegistrationSessionRepository,
    InMemorySessionRepository,
    InMemoryUserRepository,
    InMemoryVerificationTokenRepository,
)
from services.identity.services import (
    AuthService,
    MembershipService,
    OrganizationService,
    PasswordService,
    SessionService,
    TokenService,
    UserService,
    VerificationService,
)
from services.persistence.repositories import (
    SupabaseEmailIdentityRepository,
    SupabaseIdentityMembershipRepository,
    SupabaseIdentityOrganizationRepository,
    SupabasePasswordCredentialRepository,
)
from services.persistence.repositories.user_repository import SupabaseUserRepository
from services.security.crypto.crypto_service import get_crypto_service

EMAIL = "member@example.com"
PASSWORD = "StrongPass!123"


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


# ─── Service harness (in-memory identity repos) ─────────────────────────

def _service():
    from services.identity.repositories import InMemoryEmailIdentityRepository
    user_repo = InMemoryUserRepository()
    ei_repo = InMemoryEmailIdentityRepository()
    org_repo = InMemoryOrganizationRepository()
    mem_repo = InMemoryMembershipRepository()
    user_svc = UserService(user_repo, ei_repo)
    org_svc = OrganizationService(org_repo, mem_repo)
    mem_svc = MembershipService(mem_repo, user_repo, org_repo)
    return user_svc, org_svc, mem_svc, mem_repo, org_repo


def _supabase_repos(db):
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


def _seed_login_account(db, status: str, user_id="u-1"):
    """Seed a completed durable account whose membership is in ``status``."""
    password_hash = get_crypto_service().hash_password(PASSWORD)
    db.tables["identity_users"] = [{
        "id": user_id, "display_name": "Member", "email": EMAIL,
        "onboarding_completed_at": None, "onboarding_data": None,
        "created_at": _FUTURE, "updated_at": _FUTURE,
    }]
    db.tables["email_identities"] = [{
        "id": str(uuid4()), "user_id": user_id, "email": EMAIL,
        "is_verified": True, "is_primary": True, "verified_at": _FUTURE,
        "created_at": _FUTURE,
    }]
    db.tables["password_credentials"] = [{
        "id": str(uuid4()), "user_id": user_id,
        "password_hash": str(password_hash),
        "created_at": _FUTURE, "last_changed_at": _FUTURE,
    }]
    org = Organization(name="Org", slug="org", owner_id=user_id)
    _save_org(db, org)
    db.tables.setdefault("memberships", []).append({
        "id": str(uuid4()), "user_id": user_id, "organization_id": org.id,
        "role": "owner", "status": status, "joined_at": _FUTURE, "invited_by": "",
    })


def _save_org(db, org):
    row = {"id": org.id, "name": org.name, "slug": org.slug,
           "created_by": org.owner_id, "created_at": _FUTURE, "updated_at": _FUTURE,
           "deleted_at": None}
    db.tables.setdefault("organizations", []).append(row)
    return org.id


# ─── A. Canonical status model ──────────────────────────────────────────

class TestCanonicalStatusModel:

    def test_canonical_enum_matches_db_check(self):
        assert {s.value for s in MembershipStatus} == {
            "pending", "active", "removed", "left",
        }

    @pytest.mark.asyncio
    async def test_all_states_round_trip_through_repo(self):
        db = FakeClient()
        mem_repo = SupabaseIdentityMembershipRepository()
        mem_repo._client = lambda: db
        for status in MembershipStatus:
            m = await mem_repo.save(Membership(
                user_id=f"u-{status.value}", organization_id="o1",
                status=status,
            ))
            got = await mem_repo.get(m.id)
            assert got is not None
            assert got.status == status
            # Only ACTIVE reports as active for the login gate.
            assert got.is_active == (status == MembershipStatus.ACTIVE)

    @pytest.mark.asyncio
    async def test_no_invalid_db_status_becomes_active(self):
        db = FakeClient({"memberships": [
            {"id": str(uuid4()), "user_id": "u1", "organization_id": "o1",
             "role": "member", "status": "pending", "joined_at": _FUTURE, "invited_by": ""},
            {"id": str(uuid4()), "user_id": "u2", "organization_id": "o1",
             "role": "member", "status": "removed", "joined_at": _FUTURE, "invited_by": ""},
            {"id": str(uuid4()), "user_id": "u3", "organization_id": "o1",
             "role": "member", "status": "left", "joined_at": _FUTURE, "invited_by": ""},
        ]})
        mem_repo = SupabaseIdentityMembershipRepository()
        mem_repo._client = lambda: db
        for uid in ("u1", "u2", "u3"):
            rows = await mem_repo.find_by_user_id(uid)
            assert rows[0].is_active is False


# ─── B. Lifecycle transitions ───────────────────────────────────────────

class TestLifecycleTransitions:

    @pytest.mark.asyncio
    async def test_supported_transitions(self):
        user_svc, _, mem_svc, mem_repo, org_repo = _service()
        await user_svc.save_user(User(id="u1", display_name="u1"))
        await user_svc.save_user(User(id="u2", display_name="u2"))
        await org_repo.save(Organization(id="o1", name="Org", slug="org"))

        # pending -> active (activate)
        m = await mem_repo.save(Membership(
            user_id="u1", organization_id="o1", status=MembershipStatus.PENDING,
        ))
        await mem_svc.activate_membership(m.id)
        assert (await mem_repo.get(m.id)).status == MembershipStatus.ACTIVE

        # active -> removed (remove)
        await mem_svc.remove_member(m.id)
        assert (await mem_repo.get(m.id)).status == MembershipStatus.REMOVED

        # removed -> active (reactivation via add_member)
        m2 = await mem_svc.add_member("u1", "o1")
        assert m2.id == m.id
        assert m2.status == MembershipStatus.ACTIVE

        # active -> left (leave)
        await mem_svc.leave_organization(m2.id)
        assert (await mem_repo.get(m2.id)).status == MembershipStatus.LEFT

        # left -> active (rejoin via add_member)
        m3 = await mem_svc.add_member("u1", "o1")
        assert m3.status == MembershipStatus.ACTIVE

        # pending -> removed
        p = await mem_repo.save(Membership(
            user_id="u2", organization_id="o1", status=MembershipStatus.PENDING,
        ))
        await mem_svc.remove_member(p.id)
        assert (await mem_repo.get(p.id)).status == MembershipStatus.REMOVED

    @pytest.mark.asyncio
    async def test_invalid_transitions_rejected(self):
        user_svc, _, mem_svc, mem_repo, org_repo = _service()
        await user_svc.save_user(User(id="u1", display_name="u1"))
        await org_repo.save(Organization(id="o1", name="Org", slug="org"))

        # active -> active duplicate add is rejected
        await mem_svc.add_member("u1", "o1")
        with pytest.raises(MembershipAlreadyExistsException):
            await mem_svc.add_member("u1", "o1")

        # active -> pending is rejected
        active = await mem_repo.find_by_user_id("u1")
        with pytest.raises(InvalidMembershipTransitionException):
            await mem_svc.assert_valid_transition(active[0], "pending")

        # removed -> left is rejected
        r = await mem_repo.save(Membership(
            user_id="u2", organization_id="o1", status=MembershipStatus.REMOVED,
        ))
        with pytest.raises(InvalidMembershipTransitionException):
            await mem_svc.leave_organization(r.id)

        # pending -> left is rejected
        p = await mem_repo.save(Membership(
            user_id="u3", organization_id="o1", status=MembershipStatus.PENDING,
        ))
        with pytest.raises(InvalidMembershipTransitionException):
            await mem_svc.leave_organization(p.id)

        # left -> removed is rejected (must rejoin)
        l = await mem_repo.save(Membership(
            user_id="u4", organization_id="o1", status=MembershipStatus.LEFT,
        ))
        with pytest.raises(InvalidMembershipTransitionException):
            await mem_svc.remove_member(l.id)

    @pytest.mark.asyncio
    async def test_same_state_is_idempotent(self):
        user_svc, _, mem_svc, mem_repo, org_repo = _service()
        await user_svc.save_user(User(id="u1", display_name="u1"))
        await org_repo.save(Organization(id="o1", name="Org", slug="org"))
        m = await mem_svc.add_member("u1", "o1")
        assert m.status == MembershipStatus.ACTIVE
        # Removing an already-removed membership is a safe no-op.
        await mem_svc.remove_member(m.id)
        assert (await mem_repo.get(m.id)).status == MembershipStatus.REMOVED
        await mem_svc.remove_member(m.id)
        assert (await mem_repo.get(m.id)).status == MembershipStatus.REMOVED


# ─── C. Login authorization ─────────────────────────────────────────────

class TestLoginAuthorization:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status,expect_success", [
        ("active", True),
        ("pending", False),
        ("removed", False),
        ("left", False),
    ])
    async def test_login_requires_active(self, status, expect_success):
        from services.identity.exceptions import InvalidCredentialsException
        db = FakeClient()
        _seed_login_account(db, status)
        svc = _build_auth_service(db)
        if expect_success:
            result = await svc.login(EMAIL, PASSWORD)
            assert result.session is not None
        else:
            with pytest.raises(InvalidCredentialsException) as exc:
                await svc.login(EMAIL, PASSWORD)
            assert "No active organization membership" in str(exc.value)


# ─── D. Owner membership invariant ──────────────────────────────────────

class TestOwnerMembership:

    @pytest.mark.asyncio
    async def test_signup_creates_exactly_one_active_owner(self):
        user_svc, org_svc, _, mem_repo, _ = _service()
        user = await user_svc.save_user(User(id="owner-1", display_name="Owner"))
        org, membership, _ = await org_svc.create_organization("Acme", user.id)
        assert membership.role == "owner"
        assert membership.is_active
        memberships = await mem_repo.find_by_user_id(user.id)
        assert len(memberships) == 1
        assert memberships[0].role == "owner"
        assert memberships[0].status == MembershipStatus.ACTIVE

    @pytest.mark.asyncio
    async def test_owner_membership_does_not_duplicate(self):
        user_svc, org_svc, mem_svc, mem_repo, _ = _service()
        user = await user_svc.save_user(User(id="owner-2", display_name="Owner"))
        org, _, _ = await org_svc.create_organization("Acme", user.id)
        # Re-adding the owner is rejected (already active), never duplicated.
        with pytest.raises(MembershipAlreadyExistsException):
            await mem_svc.add_member(user.id, org.id, role="owner")
        memberships = await mem_repo.find_by_user_id(user.id)
        assert len(memberships) == 1


# ─── E. Invitation convergence ──────────────────────────────────────────

class TestInvitationConvergence:

    @pytest.mark.asyncio
    async def test_acceptance_converges_on_canonical_membership_row(self):
        from services.identity.services.invitation_service import InvitationService
        from services.identity.repositories import InMemoryInvitationRepository
        from services.security.crypto.crypto_service import get_crypto_service
        user_repo = InMemoryUserRepository()
        org_repo = InMemoryOrganizationRepository()
        mem_repo = InMemoryMembershipRepository()
        inv_repo = InMemoryInvitationRepository()
        org_svc = OrganizationService(org_repo, mem_repo)
        mem_svc = MembershipService(mem_repo, user_repo, org_repo)
        inv_svc = InvitationService(inv_repo, mem_repo, org_repo, user_repo, get_crypto_service())

        owner = await user_repo.save(User(id="o-1", display_name="Owner"))
        invitee = await user_repo.save(User(id="m-1", display_name="Member"))
        org, _, _ = await org_svc.create_organization("Acme", owner.id)

        invitation, _ = await inv_svc.create_invitation(
            org.id, owner.id, "member@acme.com", role="member",
        )
        await inv_svc.accept_invitation(invitation.id, invitee.id)
        memberships = await mem_repo.find_by_user_id(invitee.id)
        assert len(memberships) == 1
        assert memberships[0].status == MembershipStatus.ACTIVE

        # Repeated acceptance does not create a duplicate membership — an
        # already-active member is rejected explicitly (never duplicated).
        invitation2, _ = await inv_svc.create_invitation(
            org.id, owner.id, "member@acme.com", role="member",
        )
        from services.identity.exceptions import MembershipAlreadyExistsException
        with pytest.raises(MembershipAlreadyExistsException):
            await inv_svc.accept_invitation(invitation2.id, invitee.id)
        assert len(await mem_repo.find_by_user_id(invitee.id)) == 1


# ─── F. Restart durability ──────────────────────────────────────────────

class TestRestartDurability:

    @pytest.mark.asyncio
    async def test_membership_survives_repository_recreation(self):
        db = FakeClient()
        mem_repo = SupabaseIdentityMembershipRepository()
        mem_repo._client = lambda: db
        m = await mem_repo.save(Membership(
            user_id="u1", organization_id="o1", role="owner",
            status=MembershipStatus.ACTIVE,
        ))
        # Recreate the repository (restart/redeploy) over the same DB.
        fresh = SupabaseIdentityMembershipRepository()
        fresh._client = lambda: db
        rows = await fresh.find_active_by_user_id("u1")
        assert len(rows) == 1
        assert rows[0].id == m.id
        assert rows[0].status == MembershipStatus.ACTIVE
        assert rows[0].is_active

    @pytest.mark.asyncio
    async def test_login_interprets_state_after_restart(self):
        from services.identity.exceptions import InvalidCredentialsException
        db = FakeClient()
        _seed_login_account(db, "removed")
        # Fresh service (restart) over the same DB.
        svc = _build_auth_service(db)
        with pytest.raises(InvalidCredentialsException):
            await svc.login(EMAIL, PASSWORD)


# ─── G. Tenant / organization isolation ─────────────────────────────────

class TestIsolation:

    @pytest.mark.asyncio
    async def test_user_scoped_membership_queries(self):
        db = FakeClient({"memberships": [
            {"id": str(uuid4()), "user_id": "user-a", "organization_id": "org-a",
             "role": "owner", "status": "active", "joined_at": _FUTURE, "invited_by": ""},
            {"id": str(uuid4()), "user_id": "user-b", "organization_id": "org-b",
             "role": "member", "status": "active", "joined_at": _FUTURE, "invited_by": ""},
        ]})
        mem_repo = SupabaseIdentityMembershipRepository()
        mem_repo._client = lambda: db
        a = await mem_repo.find_by_user_id("user-a")
        assert [m.organization_id for m in a] == ["org-a"]
        b = await mem_repo.find_by_user_id("user-b")
        assert [m.organization_id for m in b] == ["org-b"]

    @pytest.mark.asyncio
    async def test_org_a_membership_does_not_grant_org_b_access(self):
        db = FakeClient({"memberships": [
            {"id": str(uuid4()), "user_id": "user-a", "organization_id": "org-a",
             "role": "member", "status": "active", "joined_at": _FUTURE, "invited_by": ""},
        ]})
        mem_repo = SupabaseIdentityMembershipRepository()
        mem_repo._client = lambda: db
        # user-a has no membership in org-b.
        assert await mem_repo.find_by_user_and_org("user-a", "org-b") is None


# ─── H. Repository contract ─────────────────────────────────────────────

class TestRepositoryContract:

    @pytest.mark.asyncio
    async def test_identity_membership_repo_returns_domain_models(self):
        db = FakeClient({"memberships": [
            {"id": str(uuid4()), "user_id": "u1", "organization_id": "o1",
             "role": "owner", "status": "active", "joined_at": _FUTURE, "invited_by": ""},
        ]})
        mem_repo = SupabaseIdentityMembershipRepository()
        mem_repo._client = lambda: db
        for rows in [
            await mem_repo.find_by_user_id("u1"),
            await mem_repo.find_by_org_id("o1"),
            await mem_repo.find_active_by_user_id("u1"),
        ]:
            assert rows and isinstance(rows[0], Membership)
            assert not isinstance(rows[0], dict)
        got = await mem_repo.find_by_user_and_org("u1", "o1")
        assert isinstance(got, Membership)
        assert not isinstance(got, dict)
        assert got.is_active is True

    @pytest.mark.asyncio
    async def test_org_platform_membership_repo_returns_domain_models(self):
        from services.organizations.models import Membership as OrgMembership
        from services.persistence.repositories import SupabaseMembershipRepository
        db = FakeClient({"memberships": [
            {"id": str(uuid4()), "organization_id": "o1", "user_id": "u1",
             "role": "owner", "status": "active", "joined_at": _FUTURE, "invited_by": ""},
        ]})
        repo = SupabaseMembershipRepository()
        repo._client = lambda: db
        for rows in [
            await repo.find_by_user_id("u1"),
            await repo.find_by_org_id("o1"),
            await repo.find_active_by_user_id("u1"),
        ]:
            assert rows and isinstance(rows[0], OrgMembership)
            assert not isinstance(rows[0], dict)
        got = await repo.find_by_user_and_org("u1", "o1")
        assert isinstance(got, OrgMembership)
        assert got.is_active is True
