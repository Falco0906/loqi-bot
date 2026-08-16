"""SaaS-1 — enforceable identity boundary tests.

Covers the full authentication lifecycle, the canonical auth dependency, and
the isolation fixes (IDOR/BOLA regressions) implemented for the SaaS identity
boundary:

- signup / verification / account activation / login / access token / refresh
  rotation / logout / revocation
- missing / malformed / expired / revoked credentials
- user isolation: a caller can never read or revoke another user's sessions
- organization isolation: a non-member cannot read another organization
- password change invalidates other sessions; password reset revokes all
- regression tests for the previously-unauthenticated /me + /sessions routes
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from services.identity.api import (
    reset_auth_service,
    reset_oauth_session_repo,
    set_auth_service,
)
from services.identity.providers import EmailProvider
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


class CapturingEmailProvider(EmailProvider):
    def __init__(self) -> None:
        self.verification_urls: list[str] = []
        self.reset_urls: list[str] = []

    async def send_verification_email(self, to: str, verification_url: str) -> None:
        self.verification_urls.append(verification_url)

    async def send_password_reset_email(self, to: str, reset_url: str) -> None:
        self.reset_urls.append(reset_url)


@pytest.fixture(autouse=True)
def _reset():
    reset_crypto_service()
    reset_auth_service()
    reset_oauth_session_repo()
    from services.identity.providers.registry import reset_provider_registry
    reset_provider_registry()


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def _build_service(email_provider=None):
    """Build a fresh in-memory AuthService and return (svc, repos)."""
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
        email_provider=email_provider or CapturingEmailProvider(),
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
        external_identity_repo=repos.get("ext_repo"),
        password_reset_repo=repos["pr_repo"],
    )
    set_auth_service(svc)
    return svc, repos


async def _register_user(svc, email: str, *, verify: bool = True, complete: bool = True):
    """Run begin → verify → complete for a fresh user."""
    reg = await svc.begin_registration(email)
    if verify:
        await svc.verify_email(reg.raw_token)
    if complete:
        return await svc.complete_registration(
            reg.registration_session.id, email.split("@")[0], "StrongPass123!",
            f"{email.split('@')[0]} Org",
        )
    return reg


# ═══════════════════════════════════════════════════════════════════════
# 1. Authentication lifecycle
# ═══════════════════════════════════════════════════════════════════════


class TestLifecycle:

    @pytest.mark.asyncio
    async def test_signup_login_logout_roundtrip(self):
        svc, _ = _build_service()
        complete = await _register_user(svc, "alice@test.com")

        login = await svc.login("alice@test.com", "StrongPass123!")
        assert login.session.user_id == complete.user.id

        # Access token validates
        session = await svc.validate_access_token(login.session.id)
        assert session.user_id == complete.user.id

        # Logout revokes the session and refresh family
        await svc.logout(login.refresh_token)
        with pytest.raises(Exception):
            await svc.validate_access_token(login.session.id)

    @pytest.mark.asyncio
    async def test_duplicate_registration_rejected(self):
        svc, _ = _build_service()
        await _register_user(svc, "dup@test.com")
        from services.identity.exceptions import EmailAlreadyExistsException
        with pytest.raises(EmailAlreadyExistsException):
            await svc.begin_registration("dup@test.com")

    @pytest.mark.asyncio
    async def test_verification_expiry_rejected(self):
        svc, repos = _build_service()
        reg = await svc.begin_registration("exp@test.com")
        token = await repos["vt_repo"].get(reg.registration_session.verification_token_id)
        token.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await repos["vt_repo"].save(token)
        from services.identity.exceptions import InvalidCredentialsException
        with pytest.raises(InvalidCredentialsException):
            await svc.verify_email(reg.raw_token)

    @pytest.mark.asyncio
    async def test_login_invalid_credentials_rejected(self):
        svc, _ = _build_service()
        await _register_user(svc, "bob@test.com")
        from services.identity.exceptions import InvalidCredentialsException
        with pytest.raises(InvalidCredentialsException):
            await svc.login("bob@test.com", "WrongPass123!")
        with pytest.raises(InvalidCredentialsException):
            await svc.login("nobody@test.com", "StrongPass123!")

    @pytest.mark.asyncio
    async def test_password_ttl_configuration(self):
        from services.identity.config import IDENTITY_CONFIG
        assert IDENTITY_CONFIG.tokens.session_ttl_seconds == 900
        assert IDENTITY_CONFIG.tokens.refresh_token_ttl_seconds == 2592000

    @pytest.mark.asyncio
    async def test_change_password_revokes_other_sessions(self):
        svc, _ = _build_service()
        complete = await _register_user(svc, "carol@test.com")
        s1 = await svc.login("carol@test.com", "StrongPass123!")
        s2 = await svc.login("carol@test.com", "StrongPass123!")

        await svc.change_password(
            complete.user.id, "StrongPass123!", "NewStrongPass456!",
        )

        # Both prior sessions and refresh tokens are invalidated
        with pytest.raises(Exception):
            await svc.validate_access_token(s1.session.id)
        with pytest.raises(Exception):
            await svc.validate_access_token(s2.session.id)
        with pytest.raises(Exception):
            await svc.refresh(s1.refresh_token)

        # New credentials work
        s3 = await svc.login("carol@test.com", "NewStrongPass456!")
        assert s3.session.user_id == complete.user.id

    @pytest.mark.asyncio
    async def test_refresh_rotation_replay_revokes_family(self):
        svc, _ = _build_service()
        await _register_user(svc, "dave@test.com")
        login = await svc.login("dave@test.com", "StrongPass123!")
        old_raw = login.refresh_token

        rotated = await svc.refresh(old_raw)
        assert rotated.refresh_token != old_raw

        # Old token must be rejected AND the whole family + session revoked
        from services.identity.exceptions import RefreshTokenRevokedException
        with pytest.raises(RefreshTokenRevokedException):
            await svc.refresh(old_raw)

        with pytest.raises(Exception):
            await svc.validate_access_token(rotated.access_token)

    @pytest.mark.asyncio
    async def test_expired_access_token_rejected(self):
        svc, repos = _build_service()
        await _register_user(svc, "erin@test.com")
        login = await svc.login("erin@test.com", "StrongPass123!")
        session = await repos["session_repo"].get(login.session.id)
        session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await repos["session_repo"].save(session)
        from services.identity.exceptions import SessionRevokedException
        with pytest.raises(SessionRevokedException):
            await svc.validate_access_token(login.session.id)

    @pytest.mark.asyncio
    async def test_revoked_session_rejected(self):
        svc, repos = _build_service()
        await _register_user(svc, "frank@test.com")
        login = await svc.login("frank@test.com", "StrongPass123!")
        await repos["session_repo"].get(login.session.id)
        await svc.logout(login.refresh_token)
        from services.identity.exceptions import SessionRevokedException
        with pytest.raises(SessionRevokedException):
            await svc.validate_access_token(login.session.id)


# ═══════════════════════════════════════════════════════════════════════
# 2. Protected routes / canonical auth dependency
# ═══════════════════════════════════════════════════════════════════════


class TestProtectedIdentityRoutes:

    def test_me_requires_auth(self, client):
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    def test_me_with_client_user_id_is_rejected_without_token(self, client):
        resp = client.get("/api/v1/auth/me?user_id=attacker")
        assert resp.status_code == 401

    def test_me_binds_to_token(self, client):
        svc, _ = _build_service()
        complete = asyncio.run(_register_user(svc, "grace@test.com"))
        headers = {"Authorization": f"Bearer {complete.session.id}"}

        # A client-supplied user_id is ignored — the response is the caller's.
        resp = client.get("/api/v1/auth/me?user_id=someone-else", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == complete.user.id
        assert resp.json()["email"] == "grace@test.com"

    def test_malformed_authorization_header_rejected(self, client):
        svc, _ = _build_service()
        complete = asyncio.run(_register_user(svc, "henry@test.com"))
        cases = [
            "Basic abcdef",
            "Bearer",
            "bearer",
            f"Token {complete.session.id}",
            "",
        ]
        for header in cases:
            resp = client.get(
                "/api/v1/auth/me",
                headers={"Authorization": header} if header else {},
            )
            assert resp.status_code == 401

    def test_expired_access_token_401(self, client):
        svc, repos = _build_service()
        complete = asyncio.run(_register_user(svc, "iris@test.com"))
        session = asyncio.run(repos["session_repo"].get(complete.session.id))
        session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        asyncio.run(repos["session_repo"].save(session))
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {complete.session.id}"},
        )
        assert resp.status_code == 401

    def test_revoked_session_401(self, client):
        svc, _ = _build_service()
        complete = asyncio.run(_register_user(svc, "jane@test.com"))
        login = asyncio.run(svc.login("jane@test.com", "StrongPass123!"))
        asyncio.run(svc.logout(login.refresh_token))
        # The revoked session's access token is rejected...
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {login.session.id}"},
        )
        assert resp.status_code == 401
        # ...while an unrelated active session of the same user still works.
        resp2 = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {complete.session.id}"},
        )
        assert resp2.status_code == 200

    def test_password_change_keeps_current_session(self, client):
        svc, _ = _build_service()
        asyncio.run(_register_user(svc, "pwchan@test.com"))
        login = asyncio.run(svc.login("pwchan@test.com", "StrongPass123!"))
        other = asyncio.run(svc.login("pwchan@test.com", "StrongPass123!"))

        headers = {"Authorization": f"Bearer {login.session.id}"}
        resp = client.post(
            "/api/v1/auth/password/change",
            json={"current_password": "StrongPass123!", "new_password": "NewStrongPass456!"},
            headers=headers,
        )
        assert resp.status_code == 200

        # Current session survives; the other session is revoked.
        ok = client.get("/api/v1/auth/me", headers=headers)
        assert ok.status_code == 200

        revoked = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {other.session.id}"},
        )
        assert revoked.status_code == 401

        # Old password no longer valid; new password works.
        from services.identity.exceptions import InvalidCredentialsException
        with pytest.raises(InvalidCredentialsException):
            asyncio.run(svc.login("pwchan@test.com", "StrongPass123!"))
        new = asyncio.run(svc.login("pwchan@test.com", "NewStrongPass456!"))
        assert new.session is not None

    def test_password_change_requires_auth(self, client):
        resp = client.post(
            "/api/v1/auth/password/change",
            json={"current_password": "OldPass123!", "new_password": "NewStrongPass456!"},
        )
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════
# 3. User isolation (IDOR regressions)
# ═══════════════════════════════════════════════════════════════════════


class TestUserIsolation:

    def test_user_a_cannot_list_user_b_sessions(self, client):
        svc, _ = _build_service()
        alice = asyncio.run(_register_user(svc, "alice_iso@test.com", ))
        bob = asyncio.run(_register_user(svc, "bob_iso@test.com", ))

        # Alice lists sessions with Bob's user_id in the query — must be 200
        # and return ONLY Alice's sessions (Bob's ids never appear).
        resp = client.get(
            "/api/v1/auth/sessions?user_id={}".format(bob.user.id),
            headers={"Authorization": f"Bearer {alice.session.id}"},
        )
        assert resp.status_code == 200
        ids = [s["id"] for s in resp.json()["sessions"]]
        assert alice.session.id in ids
        assert bob.session.id not in ids

    def test_user_a_cannot_revoke_user_b_session(self, client):
        svc, _ = _build_service()
        alice = asyncio.run(_register_user(svc, "alice_rev@test.com", ))
        bob = asyncio.run(_register_user(svc, "bob_rev@test.com", ))

        resp = client.delete(
            f"/api/v1/auth/sessions/{bob.session.id}",
            headers={"Authorization": f"Bearer {alice.session.id}"},
        )
        assert resp.status_code == 404

        # Bob's session still works
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {bob.session.id}"},
        )
        assert resp.status_code == 200

    def test_revoke_unknown_session_404(self, client):
        svc, _ = _build_service()
        alice = asyncio.run(_register_user(svc, "alice_unk@test.com", ))
        resp = client.delete(
            "/api/v1/auth/sessions/does-not-exist",
            headers={"Authorization": f"Bearer {alice.session.id}"},
        )
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════
# 4. Organization isolation (BOLA)
# ═══════════════════════════════════════════════════════════════════════


class TestOrganizationIsolation:

    def _org_client(self, client):
        from services.organizations.api import register_deps, OrgDeps
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
        org_repo = InMemoryOrganizationRepository()
        membership_repo = InMemoryMembershipRepository()
        invitation_repo = InMemoryInvitationRepository()
        org_svc = OrganizationService(org_repo, membership_repo)
        membership_svc = MembershipService(membership_repo, org_repo)
        invitation_svc = InvitationService(invitation_repo, membership_repo, membership_svc)
        resolver = CurrentOrganizationResolver(org_repo, membership_repo)
        register_deps(OrgDeps(
            org_service=org_svc,
            membership_service=membership_svc,
            invitation_service=invitation_svc,
            resolver=resolver,
        ))

    def test_non_member_cannot_read_org(self, client):
        svc, _ = _build_service()
        self._org_client(client)
        alice = asyncio.run(_register_user(svc, "alice_org@test.com", ))
        bob = asyncio.run(_register_user(svc, "bob_org@test.com", ))

        # Alice creates an organization (owner membership from the API)
        create = client.post(
            "/api/v1/organizations",
            json={"name": "Alice Org", "slug": "alice-org"},
            headers={"Authorization": f"Bearer {alice.session.id}"},
        )
        assert create.status_code == 201
        org_id = create.json()["id"]

        # Alice can read it
        ok = client.get(
            f"/api/v1/organizations/{org_id}",
            headers={"Authorization": f"Bearer {alice.session.id}"},
        )
        assert ok.status_code == 200

        # Bob (non-member) cannot read it — 404, not 200
        denied = client.get(
            f"/api/v1/organizations/{org_id}",
            headers={"Authorization": f"Bearer {bob.session.id}"},
        )
        assert denied.status_code == 404

        # Bob cannot read members either
        members = client.get(
            f"/api/v1/organizations/{org_id}/members",
            headers={"Authorization": f"Bearer {bob.session.id}"},
        )
        assert members.status_code == 404

        # Bob (member role) cannot invite / admin
        invite = client.post(
            f"/api/v1/organizations/{org_id}/invitations",
            json={"email": "someone@test.com"},
            headers={"Authorization": f"Bearer {bob.session.id}"},
        )
        assert invite.status_code == 404

    def test_unauthenticated_org_read_rejected(self, client):
        svc, _ = _build_service()
        self._org_client(client)
        resp = client.get("/api/v1/organizations/some-org")
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════
# 5. Password reset lifecycle
# ═══════════════════════════════════════════════════════════════════════


class TestPasswordReset:

    @pytest.mark.asyncio
    async def test_password_reset_single_use_and_session_invalidation(self):
        provider = CapturingEmailProvider()
        svc, _ = _build_service(provider)
        await _register_user(svc, "pr@test.com")

        login = await svc.login("pr@test.com", "StrongPass123!")

        await svc.request_password_reset("pr@test.com")
        assert provider.reset_urls
        url = provider.reset_urls[-1]
        token = url.split("token=")[1].split("&")[0]

        await svc.confirm_password_reset("pr@test.com", token, "ResetPass456!")

        # Tokens / sessions invalidated
        from services.identity.exceptions import InvalidCredentialsException
        with pytest.raises(Exception):
            await svc.validate_access_token(login.session.id)
        with pytest.raises(Exception):
            await svc.refresh(login.refresh_token)

        # Token is single use
        with pytest.raises(InvalidCredentialsException):
            await svc.confirm_password_reset("pr@test.com", token, "AnotherPass789!")

        # New password works, old password does not
        new_login = await svc.login("pr@test.com", "ResetPass456!")
        assert new_login.session is not None
        with pytest.raises(InvalidCredentialsException):
            await svc.login("pr@test.com", "StrongPass123!")

    @pytest.mark.asyncio
    async def test_password_reset_no_account_no_enumeration(self):
        provider = CapturingEmailProvider()
        svc, _ = _build_service(provider)
        await svc.request_password_reset("ghost@test.com")
        assert provider.reset_urls == []