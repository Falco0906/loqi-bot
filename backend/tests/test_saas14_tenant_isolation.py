"""SaaS-1.4 — tenant/user isolation regression tests.

Covers the isolation fixes from the SaaS-1.4 audit:

- capabilities org-scoped routes: authentication + organization membership +
  role boundary (OWNER/ADMIN for mutation)
- billing cross-tenant targeting: actor must be a member of the target
  organization (404 for non-members)
- organization role boundaries: MEMBER cannot perform ADMIN/OWNER actions,
  non-members cannot read/modify orgs, cross-org access rejected
- invitation token not exposed through the members-only list endpoint
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from services.identity.repositories import (
    InMemoryEmailIdentityRepository,
    InMemoryMembershipRepository,
    InMemoryOrganizationRepository,
    InMemoryPasswordCredentialRepository,
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
from services.security.crypto import (
    InMemoryCryptoService,
    reset_crypto_service,
    set_crypto_service,
)


class _DummyEmail:
    async def send_verification_email(self, to, verification_url):
        pass

    async def send_password_reset_email(self, to, reset_url):
        pass


@pytest.fixture(autouse=True)
def _reset():
    reset_crypto_service()


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def _build_service():
    crypto = InMemoryCryptoService()
    set_crypto_service(crypto)
    repos = {
        "reg_session_repo": InMemoryRegistrationSessionRepository(),
        "vt_repo": InMemoryVerificationTokenRepository(),
        "ei_repo": InMemoryEmailIdentityRepository(),
        "user_repo": InMemoryUserRepository(),
        "pc_repo": InMemoryPasswordCredentialRepository(),
        "org_repo": InMemoryOrganizationRepository(),
        "mem_repo": InMemoryMembershipRepository(),
        "session_repo": InMemorySessionRepository(),
        "rt_repo": InMemoryRefreshTokenRepository(),
        "pr_repo": InMemoryPasswordResetRepository(),
    }
    user_svc = UserService(repos["user_repo"], repos["ei_repo"])
    org_svc = OrganizationService(repos["org_repo"], repos["mem_repo"])
    mem_svc = MembershipService(repos["mem_repo"], repos["user_repo"], repos["org_repo"])
    ver_svc = VerificationService(repos["vt_repo"], repos["ei_repo"], crypto)
    pwd_svc = PasswordService(repos["pc_repo"], repos["user_repo"], crypto)
    ses_svc = SessionService(repos["session_repo"], repos["rt_repo"])
    tok_svc = TokenService(repos["rt_repo"], repos["session_repo"], crypto)
    svc = AuthService(
        email_provider=_DummyEmail(),
        crypto=crypto,
        registration_session_repo=repos["reg_session_repo"],
        verification_token_repo=repos["vt_repo"],
        email_identity_repo=repos["ei_repo"],
        refresh_token_repo=repos["rt_repo"],
        user_svc=user_svc,
        org_svc=org_svc,
        membership_svc=mem_svc,
        verification_svc=ver_svc,
        password_svc=pwd_svc,
        session_svc=ses_svc,
        token_svc=tok_svc,
        password_reset_repo=repos["pr_repo"],
    )
    from services.identity.api import set_auth_service
    set_auth_service(svc)
    return svc


async def _register_user(svc, email):
    reg = await svc.begin_registration(email)
    await svc.verify_email(reg.raw_token)
    return await svc.complete_registration(
        reg.registration_session.id, email.split("@")[0], "StrongPass123!",
        f"{email.split('@')[0]} Org",
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class _Fixture:
    """In-memory org + capability deps with orgs and memberships."""

    def __init__(self):
        from services.organizations.api import register_deps as _register_org_deps
        from services.organizations.api import OrgDeps as _OrgDeps
        from services.organizations.repositories import (
            InMemoryInvitationRepository,
            InMemoryMembershipRepository,
            InMemoryOrganizationRepository,
        )
        from services.organizations.resolver import CurrentOrganizationResolver
        from services.organizations.services import (
            InvitationService,
            MembershipService,
            OrganizationService,
        )
        from services.capabilities.api import register_deps as _register_cap_deps
        from services.capabilities.api import CapabilityDeps
        from services.capabilities.services import CapabilityService
        from services.capabilities.repositories import (
            InMemoryCapabilityDefinitionRepository,
            InMemoryOrganizationCapabilityRepository,
            InMemoryCapabilityUsageRepository,
            InMemoryCapabilityLimitsRepository,
        )
        from services.capabilities.config import CapabilityConfig

        self.org_repo = InMemoryOrganizationRepository()
        self.membership_repo = InMemoryMembershipRepository()
        self.invitation_repo = InMemoryInvitationRepository()
        self.org_svc = OrganizationService(self.org_repo, self.membership_repo)
        self.membership_svc = MembershipService(self.membership_repo, self.org_repo)
        self.invitation_svc = InvitationService(
            self.invitation_repo, self.membership_repo, self.membership_svc,
        )
        _register_org_deps(_OrgDeps(
            org_service=self.org_svc,
            membership_service=self.membership_svc,
            invitation_service=self.invitation_svc,
            resolver=CurrentOrganizationResolver(self.org_repo, self.membership_repo),
        ))

        cap_svc = CapabilityService(
            definition_repo=InMemoryCapabilityDefinitionRepository(),
            org_capability_repo=InMemoryOrganizationCapabilityRepository(),
            usage_repo=InMemoryCapabilityUsageRepository(),
            limits_repo=InMemoryCapabilityLimitsRepository(),
            config=CapabilityConfig(),
        )
        asyncio.run(cap_svc.seed_capabilities())
        _register_cap_deps(CapabilityDeps(capability_service=cap_svc))

    async def create_org(self, name: str, owner_id: str) -> str:
        org = await self.org_svc.create_organization(name=name, created_by=owner_id)
        return org.id

    async def add_member(self, org_id: str, user_id: str, role: str) -> None:
        from services.organizations.models import MembershipRole
        await self.membership_svc.add_member(
            org_id, user_id, role=MembershipRole(role),
        )


@pytest.fixture
def fixture():
    return _Fixture()


# ─── 1. Capabilities boundary ─────────────────────────────────────────


class TestCapabilitiesIsolation:

    def test_org_capabilities_require_auth(self, client, fixture):
        resp = client.get("/api/v1/organizations/org-x/capabilities")
        assert resp.status_code == 401

    def test_catalog_remains_public(self, client, fixture):
        resp = client.get("/api/v1/capabilities")
        assert resp.status_code == 200

    def test_non_member_cannot_read_capabilities(self, client, fixture):
        svc = _build_service()
        owner = asyncio.run(_register_user(svc, "cap_owner@example.com"))
        intruder = asyncio.run(_register_user(svc, "cap_intruder@example.com"))
        org_id = asyncio.run(fixture.create_org("Cap Org", owner.user.id))

        resp = client.get(
            f"/api/v1/organizations/{org_id}/capabilities",
            headers=_headers(intruder.session.id),
        )
        assert resp.status_code == 404

    def test_cross_org_capability_access_rejected(self, client, fixture):
        svc = _build_service()
        a = asyncio.run(_register_user(svc, "cap_a@example.com"))
        b = asyncio.run(_register_user(svc, "cap_b@example.com"))
        org_a = asyncio.run(fixture.create_org("Org A", a.user.id))
        org_b = asyncio.run(fixture.create_org("Org B", b.user.id))

        # Member of Org A cannot read Org B capabilities.
        resp = client.get(
            f"/api/v1/organizations/{org_b}/capabilities",
            headers=_headers(a.session.id),
        )
        assert resp.status_code == 404

        # ...or mutate them.
        resp = client.post(
            f"/api/v1/organizations/{org_b}/capabilities/crm/enable",
            headers=_headers(a.session.id),
        )
        assert resp.status_code == 404

    def test_member_cannot_enable_capability(self, client, fixture):
        svc = _build_service()
        owner = asyncio.run(_register_user(svc, "cap_owner2@example.com"))
        member = asyncio.run(_register_user(svc, "cap_member@example.com"))
        org_id = asyncio.run(fixture.create_org("Cap Role", owner.user.id))
        asyncio.run(fixture.add_member(org_id, member.user.id, "member"))

        resp = client.post(
            f"/api/v1/organizations/{org_id}/capabilities/crm/enable",
            headers=_headers(member.session.id),
        )
        assert resp.status_code == 403

    def test_owner_and_admin_can_enable_capability(self, client, fixture):
        svc = _build_service()
        owner = asyncio.run(_register_user(svc, "cap_owner3@example.com"))
        admin = asyncio.run(_register_user(svc, "cap_admin@example.com"))
        org_id = asyncio.run(fixture.create_org("Cap Admin", owner.user.id))
        asyncio.run(fixture.add_member(org_id, admin.user.id, "admin"))

        # Owner enables one capability; admin enables a different one
        # (re-enabling an enabled capability correctly returns 409).
        resp = client.post(
            f"/api/v1/organizations/{org_id}/capabilities/crm/enable",
            headers=_headers(owner.session.id),
        )
        assert resp.status_code == 200
        resp = client.post(
            f"/api/v1/organizations/{org_id}/capabilities/outreach/enable",
            headers=_headers(admin.session.id),
        )
        assert resp.status_code == 200


# ─── 2. Billing cross-tenant targeting ────────────────────────────────


class TestBillingIsolation:

    def test_cross_org_billing_targeting_rejected(self, client, fixture):
        svc = _build_service()
        a = asyncio.run(_register_user(svc, "bill_a@example.com"))
        b = asyncio.run(_register_user(svc, "bill_b@example.com"))
        org_a = asyncio.run(fixture.create_org("Bill A", a.user.id))
        org_b = asyncio.run(fixture.create_org("Bill B", b.user.id))

        # User A cannot read Org B's subscription state.
        resp = client.get(
            "/api/v1/billing/subscription",
            params={"organization_id": org_b},
            headers=_headers(a.session.id),
        )
        assert resp.status_code == 404

        # User A cannot create a checkout for Org B.
        resp = client.post(
            "/api/v1/billing/checkout",
            json={"organization_id": org_b, "plan_id": "plan-1", "email": "a@example.com"},
            headers=_headers(a.session.id),
        )
        assert resp.status_code == 404

        # User A CAN create a checkout for their own org (authorization passes;
        # use a real plan id from the catalog).
        plans = client.get("/api/v1/billing/plans").json()["plans"]
        resp = client.post(
            "/api/v1/billing/checkout",
            json={
                "organization_id": org_a,
                "plan_id": plans[0]["id"],
                "email": "a@example.com",
            },
            headers=_headers(a.session.id),
        )
        assert resp.status_code == 201


# ─── 3. Organization role boundaries ──────────────────────────────────


class TestOrganizationRoleBoundaries:

    def test_member_cannot_manage_roles(self, client, fixture):
        svc = _build_service()
        owner = asyncio.run(_register_user(svc, "org_owner@example.com"))
        member = asyncio.run(_register_user(svc, "org_member@example.com"))
        target = asyncio.run(_register_user(svc, "org_target@example.com"))
        org_id = asyncio.run(fixture.create_org("Roles Org", owner.user.id))
        asyncio.run(fixture.add_member(org_id, member.user.id, "member"))
        asyncio.run(fixture.add_member(org_id, target.user.id, "member"))

        resp = client.post(
            f"/api/v1/organizations/{org_id}/members/role",
            json={"target_user_id": target.user.id, "role": "admin"},
            headers=_headers(member.session.id),
        )
        assert resp.status_code == 403

    def test_admin_cannot_transfer_ownership(self, client, fixture):
        svc = _build_service()
        owner = asyncio.run(_register_user(svc, "org_owner2@example.com"))
        admin = asyncio.run(_register_user(svc, "org_admin@example.com"))
        org_id = asyncio.run(fixture.create_org("Owner Org", owner.user.id))
        asyncio.run(fixture.add_member(org_id, admin.user.id, "admin"))

        resp = client.post(
            f"/api/v1/organizations/{org_id}/transfer-ownership",
            json={"new_owner_id": admin.user.id},
            headers=_headers(admin.session.id),
        )
        assert resp.status_code == 403

    def test_non_member_cannot_list_members(self, client, fixture):
        svc = _build_service()
        owner = asyncio.run(_register_user(svc, "org_owner3@example.com"))
        intruder = asyncio.run(_register_user(svc, "org_intruder@example.com"))
        org_id = asyncio.run(fixture.create_org("Members Org", owner.user.id))

        resp = client.get(
            f"/api/v1/organizations/{org_id}/members",
            headers=_headers(intruder.session.id),
        )
        assert resp.status_code == 404

    def test_owner_can_transfer_ownership(self, client, fixture):
        svc = _build_service()
        owner = asyncio.run(_register_user(svc, "org_owner4@example.com"))
        new_owner = asyncio.run(_register_user(svc, "org_newowner@example.com"))
        org_id = asyncio.run(fixture.create_org("Transfer Org", owner.user.id))
        asyncio.run(fixture.add_member(org_id, new_owner.user.id, "member"))

        resp = client.post(
            f"/api/v1/organizations/{org_id}/transfer-ownership",
            json={"new_owner_id": new_owner.user.id},
            headers=_headers(owner.session.id),
        )
        assert resp.status_code == 200


# ─── 4. Invitation token not exposed on list ──────────────────────────


class TestInvitationTokenRedaction:

    def test_list_invitations_redacts_token(self, client, fixture):
        svc = _build_service()
        owner = asyncio.run(_register_user(svc, "inv_owner@example.com"))
        org_id = asyncio.run(fixture.create_org("Inv Org", owner.user.id))

        resp = client.post(
            f"/api/v1/organizations/{org_id}/invitations",
            json={"email": "invitee@example.com"},
            headers=_headers(owner.session.id),
        )
        assert resp.status_code == 201

        resp = client.get(
            f"/api/v1/organizations/{org_id}/invitations",
            headers=_headers(owner.session.id),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data and data[0]["token"] == ""