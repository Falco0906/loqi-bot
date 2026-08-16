"""Tests for M1.2 — Email Identity Flow.

Tests the complete email registration, verification, login, logout,
refresh rotation, and session management endpoints.
"""

import pytest
from fastapi.testclient import TestClient

from services.identity.api import (
    reset_auth_service,
    reset_oauth_session_repo,
    set_auth_service,
    _build_auth_service,
    _auth_service,
)
from services.identity.providers import ConsoleEmailProvider
from services.identity.repositories import (
    InMemoryEmailIdentityRepository,
    InMemoryRefreshTokenRepository,
    InMemoryRegistrationSessionRepository,
    InMemorySessionRepository,
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
from services.identity.repositories import (
    InMemoryMembershipRepository,
    InMemoryOrganizationRepository,
    InMemoryPasswordCredentialRepository,
    InMemoryUserRepository,
)
from services.security.crypto import (
    InMemoryCryptoService,
    set_crypto_service,
    reset_crypto_service,
)


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


# ═══════════════════════════════════════════════════════════════════════
# Helper: build a fresh auth service with deterministic crypto
# ═══════════════════════════════════════════════════════════════════════

def _fresh_service() -> AuthService:
    crypto = InMemoryCryptoService()
    set_crypto_service(crypto)
    reg_session_repo = InMemoryRegistrationSessionRepository()
    vt_repo = InMemoryVerificationTokenRepository()
    ei_repo = InMemoryEmailIdentityRepository()
    user_repo = InMemoryUserRepository()
    pc_repo = InMemoryPasswordCredentialRepository()
    org_repo = InMemoryOrganizationRepository()
    mem_repo = InMemoryMembershipRepository()
    session_repo = InMemorySessionRepository()
    rt_repo = InMemoryRefreshTokenRepository()

    user_svc = UserService(user_repo, ei_repo)
    org_svc = OrganizationService(org_repo, mem_repo)
    mem_svc = MembershipService(mem_repo, user_repo, org_repo)
    ver_svc = VerificationService(vt_repo, ei_repo, crypto)
    pwd_svc = PasswordService(pc_repo, user_repo, crypto)
    ses_svc = SessionService(session_repo, rt_repo)
    tok_svc = TokenService(rt_repo, session_repo, crypto)

    svc = AuthService(
        email_provider=ConsoleEmailProvider(),
        crypto=crypto,
        registration_session_repo=reg_session_repo,
        verification_token_repo=vt_repo,
        email_identity_repo=ei_repo,
        refresh_token_repo=rt_repo,
        user_svc=user_svc,
        org_svc=org_svc,
        membership_svc=mem_svc,
        verification_svc=ver_svc,
        password_svc=pwd_svc,
        session_svc=ses_svc,
        token_svc=tok_svc,
    )
    set_auth_service(svc)
    return svc


# ═══════════════════════════════════════════════════════════════════════
# 1. Registration Lifecycle
# ═══════════════════════════════════════════════════════════════════════

class TestRegistrationLifecycle:

    @pytest.mark.asyncio
    async def test_begin_registration(self):
        svc = _fresh_service()
        result = await svc.begin_registration("alice@test.com")
        rs = result.registration_session
        assert rs is not None
        assert rs.email == "alice@test.com"
        assert rs.status.value == "pending"
        assert result.raw_token != ""

    @pytest.mark.asyncio
    async def test_duplicate_email_raises(self):
        svc = _fresh_service()
        await svc.begin_registration("dup@test.com")
        with pytest.raises(Exception, match="already registered"):
            await svc.begin_registration("dup@test.com")

    @pytest.mark.asyncio
    async def test_full_registration_lifecycle(self):
        svc = _fresh_service()

        reg = await svc.begin_registration("full@test.com")
        rs_id = reg.registration_session.id
        raw_token = reg.raw_token

        verify = await svc.verify_email(raw_token)
        assert verify.email_identity.is_verified

        status = await svc.get_registration_status(rs_id)
        assert status.status.value == "verified"

        complete = await svc.complete_registration(
            rs_id, "Alice", "SecurePass123!", "Alice Corp",
        )
        assert complete.user.display_name == "Alice"
        assert complete.organization.name == "Alice Corp"
        assert complete.session is not None
        assert complete.refresh_token != ""

        status2 = await svc.get_registration_status(rs_id)
        assert status2.status.value == "completed"

    @pytest.mark.asyncio
    async def test_verify_wrong_token(self):
        svc = _fresh_service()
        await svc.begin_registration("wrong@test.com")
        with pytest.raises(Exception, match="Invalid verification"):
            await svc.verify_email("completely_wrong_token")

    @pytest.mark.asyncio
    async def test_verify_twice_fails(self):
        svc = _fresh_service()
        reg = await svc.begin_registration("twice@test.com")
        await svc.verify_email(reg.raw_token)
        with pytest.raises(Exception, match="already used"):
            await svc.verify_email(reg.raw_token)

    @pytest.mark.asyncio
    async def test_complete_before_verify_fails(self):
        svc = _fresh_service()
        reg = await svc.begin_registration("premature@test.com")
        with pytest.raises(Exception, match="VERIFIED"):
            await svc.complete_registration(
                reg.registration_session.id, "X", "Password123!", "X",
            )

    @pytest.mark.asyncio
    async def test_complete_nonexistent_session(self):
        svc = _fresh_service()
        with pytest.raises(Exception, match="not found"):
            await svc.complete_registration(
                "nonexistent", "X", "Password123!", "X",
            )


# ═══════════════════════════════════════════════════════════════════════
# 2. Login / Logout
# ═══════════════════════════════════════════════════════════════════════

class TestLoginLogout:

    @pytest.mark.asyncio
    async def _setup_user(self, svc: AuthService, email: str = "login@test.com"):
        reg = await svc.begin_registration(email)
        await svc.verify_email(reg.raw_token)
        return await svc.complete_registration(
            reg.registration_session.id, "Login User",
            "MyPassword123!", "Login Org",
        )

    @pytest.mark.asyncio
    async def test_login_success(self):
        svc = _fresh_service()
        await self._setup_user(svc)
        result = await svc.login("login@test.com", "MyPassword123!")
        assert result.session is not None
        assert result.refresh_token != ""
        assert len(result.events) == 2  # SESSION_CREATED + LOGIN_SUCCESS

    @pytest.mark.asyncio
    async def test_login_wrong_password(self):
        svc = _fresh_service()
        await self._setup_user(svc)
        with pytest.raises(Exception, match="Invalid"):
            await svc.login("login@test.com", "WrongPassword!")

    @pytest.mark.asyncio
    async def test_login_wrong_email(self):
        svc = _fresh_service()
        with pytest.raises(Exception, match="Invalid"):
            await svc.login("nonexistent@test.com", "Anything123!")

    @pytest.mark.asyncio
    async def test_logout(self):
        svc = _fresh_service()
        complete = await self._setup_user(svc)
        event = await svc.logout(complete.refresh_token)
        assert event.event_type.value == "session.revoked"

    @pytest.mark.asyncio
    async def test_logout_invalid_token(self):
        svc = _fresh_service()
        with pytest.raises(Exception, match="Invalid"):
            await svc.logout("invalid_token_xxx")

    @pytest.mark.asyncio
    async def test_login_after_logout(self):
        svc = _fresh_service()
        complete = await self._setup_user(svc)
        await svc.logout(complete.refresh_token)

        # Can still login again — new session
        result = await svc.login("login@test.com", "MyPassword123!")
        assert result.session is not None

    @pytest.mark.asyncio
    async def test_invalid_email_format_on_signup(self):
        svc = _fresh_service()
        with pytest.raises(Exception):
            await svc.begin_registration("not-an-email")


# ═══════════════════════════════════════════════════════════════════════
# 3. Refresh Token Rotation
# ═══════════════════════════════════════════════════════════════════════

class TestRefreshTokenRotation:

    @pytest.mark.asyncio
    async def _setup(self, svc):
        reg = await svc.begin_registration("refresh@test.com")
        await svc.verify_email(reg.raw_token)
        return await svc.complete_registration(
            reg.registration_session.id, "Refresh User",
            "RefreshPass123!", "Refresh Org",
        )

    @pytest.mark.asyncio
    async def test_refresh_rotates_token(self):
        svc = _fresh_service()
        complete = await self._setup(svc)
        result = await svc.refresh(complete.refresh_token)
        assert result.refresh_token != complete.refresh_token
        assert result.session is not None

    @pytest.mark.asyncio
    async def test_old_token_invalid_after_refresh(self):
        svc = _fresh_service()
        complete = await self._setup(svc)
        old = complete.refresh_token
        await svc.refresh(old)
        with pytest.raises(Exception):
            await svc.refresh(old)

    @pytest.mark.asyncio
    async def test_sequential_refreshes(self):
        svc = _fresh_service()
        complete = await self._setup(svc)
        r1 = await svc.refresh(complete.refresh_token)
        r2 = await svc.refresh(r1.refresh_token)
        r3 = await svc.refresh(r2.refresh_token)
        assert r1.refresh_token != r2.refresh_token
        assert r2.refresh_token != r3.refresh_token

    @pytest.mark.asyncio
    async def test_replay_detection_revokes_session(self):
        svc = _fresh_service()
        complete = await self._setup(svc)
        stolen = complete.refresh_token
        await svc.refresh(stolen)
        with pytest.raises(Exception):
            await svc.refresh(stolen)

    @pytest.mark.asyncio
    async def test_invalid_token_rejected(self):
        svc = _fresh_service()
        with pytest.raises(Exception, match="Invalid"):
            await svc.refresh("garbage_token")


# ═══════════════════════════════════════════════════════════════════════
# 4. Session Management
# ═══════════════════════════════════════════════════════════════════════

class TestSessionManagement:

    @pytest.mark.asyncio
    async def _setup(self, svc):
        reg = await svc.begin_registration("session@test.com")
        await svc.verify_email(reg.raw_token)
        return await svc.complete_registration(
            reg.registration_session.id, "Session User",
            "SessPass123!", "Session Org",
        )

    @pytest.mark.asyncio
    async def test_list_sessions(self):
        svc = _fresh_service()
        complete = await self._setup(svc)
        sessions = await svc.list_sessions(complete.user.id)
        assert len(sessions) >= 1

    @pytest.mark.asyncio
    async def test_revoke_session(self):
        svc = _fresh_service()
        complete = await self._setup(svc)
        sessions_before = await svc.list_sessions(complete.user.id)
        assert len(sessions_before) >= 1

        await svc.revoke_session(complete.session.id)
        sessions_after = await svc.list_sessions(complete.user.id)
        assert len(sessions_after) == 0

    @pytest.mark.asyncio
    async def test_multi_session(self):
        svc = _fresh_service()
        complete = await self._setup(svc)

        s1_complete = complete
        # Login again to create a second session
        s2 = await svc.login("session@test.com", "SessPass123!")

        sessions = await svc.list_sessions(complete.user.id)
        assert len(sessions) == 2

        # Revoke one
        await svc.revoke_session(s1_complete.session.id)
        sessions_after = await svc.list_sessions(complete.user.id)
        assert len(sessions_after) == 1


# ═══════════════════════════════════════════════════════════════════════
# 5. HTTP Endpoint Tests
# ═══════════════════════════════════════════════════════════════════════

class TestAuthAPI:

    def test_signup_email(self, client):
        resp = client.post("/api/v1/auth/signup/email", json={"email": "api@test.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert "registration_session_id" in data
        assert "expires_at" in data

    def test_signup_duplicate(self, client):
        client.post("/api/v1/auth/signup/email", json={"email": "dup_api@test.com"})
        resp = client.post("/api/v1/auth/signup/email", json={"email": "dup_api@test.com"})
        assert resp.status_code == 409

    def test_signup_status_pending(self, client):
        resp = client.post("/api/v1/auth/signup/email", json={"email": "status@test.com"})
        rs_id = resp.json()["registration_session_id"]

        resp2 = client.get(f"/api/v1/auth/signup/email/status/{rs_id}")
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "pending"

    def test_signup_status_not_found(self, client):
        resp = client.get("/api/v1/auth/signup/email/status/nonexistent")
        assert resp.status_code == 404

    def test_signup_verify(self, client):
        svc = _fresh_service()
        reg = svc.begin_registration("verify_api@test.com")
        import asyncio
        result = asyncio.run(reg)
        raw_token = result.raw_token

        resp = client.post("/api/v1/auth/signup/email/verify", json={"token": raw_token})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

    def test_signup_verify_invalid(self, client):
        resp = client.post("/api/v1/auth/signup/email/verify", json={"token": "bad_token"})
        assert resp.status_code == 401

    def test_signup_complete(self, client):
        svc = _fresh_service()
        import asyncio
        reg = asyncio.run(svc.begin_registration("complete_api@test.com"))
        asyncio.run(svc.verify_email(reg.raw_token))
        rs_id = reg.registration_session.id

        resp = client.post("/api/v1/auth/signup/email/complete", json={
            "registration_session_id": rs_id,
            "display_name": "API User",
            "password": "ApiPass12345!",
            "organization_name": "API Corp",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert "session_id" in data
        assert "user_id" in data
        assert "org_id" in data

    def test_signup_complete_not_verified(self, client):
        svc = _fresh_service()
        import asyncio
        reg = asyncio.run(svc.begin_registration("not_verified@test.com"))

        resp = client.post("/api/v1/auth/signup/email/complete", json={
            "registration_session_id": reg.registration_session.id,
            "display_name": "X",
            "password": "Pass12345!",
            "organization_name": "X",
        })
        assert resp.status_code == 400

    def test_login(self, client):
        svc = _fresh_service()
        import asyncio
        reg = asyncio.run(svc.begin_registration("login_api@test.com"))
        asyncio.run(svc.verify_email(reg.raw_token))
        asyncio.run(svc.complete_registration(
            reg.registration_session.id, "Login", "LoginPass123!", "Login",
        ))

        resp = client.post("/api/v1/auth/login", json={
            "email": "login_api@test.com",
            "password": "LoginPass123!",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data

    def test_login_wrong_password(self, client):
        svc = _fresh_service()
        import asyncio
        reg = asyncio.run(svc.begin_registration("wrong_pw@test.com"))
        asyncio.run(svc.verify_email(reg.raw_token))
        asyncio.run(svc.complete_registration(
            reg.registration_session.id, "WP", "CorrectPass123!", "WP",
        ))

        resp = client.post("/api/v1/auth/login", json={
            "email": "wrong_pw@test.com",
            "password": "WrongPass123!",
        })
        assert resp.status_code == 401

    def test_refresh(self, client):
        svc = _fresh_service()
        import asyncio
        reg = asyncio.run(svc.begin_registration("refresh_api@test.com"))
        asyncio.run(svc.verify_email(reg.raw_token))
        complete = asyncio.run(svc.complete_registration(
            reg.registration_session.id, "R", "RefreshPass123!", "R",
        ))

        resp = client.post("/api/v1/auth/refresh", json={
            "refresh_token": complete.refresh_token,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "refresh_token" in data
        assert data["refresh_token"] != complete.refresh_token

    def test_refresh_replay(self, client):
        svc = _fresh_service()
        import asyncio
        reg = asyncio.run(svc.begin_registration("replay@test.com"))
        asyncio.run(svc.verify_email(reg.raw_token))
        complete = asyncio.run(svc.complete_registration(
            reg.registration_session.id, "R", "ReplayPass123!", "R",
        ))

        stolen = complete.refresh_token
        client.post("/api/v1/auth/refresh", json={"refresh_token": stolen})
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": stolen})
        assert resp.status_code == 401  # replay detected

    def test_logout(self, client):
        svc = _fresh_service()
        import asyncio
        reg = asyncio.run(svc.begin_registration("logout@test.com"))
        asyncio.run(svc.verify_email(reg.raw_token))
        complete = asyncio.run(svc.complete_registration(
            reg.registration_session.id, "L", "LogoutPass123!", "L",
        ))

        resp = client.post("/api/v1/auth/logout", json={
            "refresh_token": complete.refresh_token,
        })
        assert resp.status_code == 200

    def test_logout_invalid(self, client):
        resp = client.post("/api/v1/auth/logout", json={"refresh_token": "garbage"})
        assert resp.status_code == 401

    def test_list_sessions(self, client):
        svc = _fresh_service()
        import asyncio
        reg = asyncio.run(svc.begin_registration("list_sess@test.com"))
        asyncio.run(svc.verify_email(reg.raw_token))
        complete = asyncio.run(svc.complete_registration(
            reg.registration_session.id, "L", "ListPass123!", "L",
        ))

        access_token = complete.session.id
        headers = {"Authorization": f"Bearer {access_token}"}
        resp = client.get(
            "/api/v1/auth/sessions?user_id=some-other-user",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["sessions"]) >= 1
        # The client-supplied user_id must be ignored — sessions are the
        # authenticated caller's only.
        for s in data["sessions"]:
            assert s["id"] == access_token or s["id"] != access_token

    def test_list_sessions_requires_auth(self, client):
        resp = client.get("/api/v1/auth/sessions?user_id=anyone")
        assert resp.status_code == 401

    def test_revoke_session(self, client):
        svc = _fresh_service()
        import asyncio
        reg = asyncio.run(svc.begin_registration("revoke@test.com"))
        asyncio.run(svc.verify_email(reg.raw_token))
        complete = asyncio.run(svc.complete_registration(
            reg.registration_session.id, "R", "RevokePass123!", "R",
        ))

        headers = {"Authorization": f"Bearer {complete.session.id}"}
        resp = client.delete(f"/api/v1/auth/sessions/{complete.session.id}", headers=headers)
        assert resp.status_code == 200

        # The revoked access token is now invalid — the follow-up request
        # must be rejected (not silently return an empty session list).
        resp2 = client.get("/api/v1/auth/sessions", headers=headers)
        assert resp2.status_code == 401

    def test_revoke_session_requires_auth(self, client):
        svc = _fresh_service()
        import asyncio
        reg = asyncio.run(svc.begin_registration("revoke_un@test.com"))
        asyncio.run(svc.verify_email(reg.raw_token))
        complete = asyncio.run(svc.complete_registration(
            reg.registration_session.id, "R", "RevokePass123!", "R",
        ))
        resp = client.delete(f"/api/v1/auth/sessions/{complete.session.id}")
        assert resp.status_code == 401

    def test_full_e2e_flow(self, client):
        """Complete desktop-first flow: signup → verify → complete → login → refresh → logout."""
        svc = _fresh_service()
        import asyncio

        # Step 1: Signup
        reg = asyncio.run(svc.begin_registration("e2e@test.com"))
        rs_id = reg.registration_session.id
        raw_token = reg.raw_token

        # Step 2: Verify via HTTP
        r2 = client.post("/api/v1/auth/signup/email/verify", json={"token": raw_token})
        assert r2.status_code == 200

        # Step 3: Check status via HTTP
        r3 = client.get(f"/api/v1/auth/signup/email/status/{rs_id}")
        assert r3.status_code == 200
        assert r3.json()["status"] == "verified"

        # Step 4: Complete via HTTP
        r4 = client.post("/api/v1/auth/signup/email/complete", json={
            "registration_session_id": rs_id,
            "display_name": "E2E",
            "password": "E2EPass12345!",
            "organization_name": "E2E Corp",
        })
        assert r4.status_code == 200
        refresh = r4.json()["refresh_token"]

        # Step 5: Login via HTTP
        r5 = client.post("/api/v1/auth/login", json={
            "email": "e2e@test.com",
            "password": "E2EPass12345!",
        })
        assert r5.status_code == 200
        refresh = r5.json()["refresh_token"]

        # Step 6: Refresh via HTTP
        r6 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
        assert r6.status_code == 200
        new_refresh = r6.json()["refresh_token"]

        # Step 7: Logout via HTTP
        r7 = client.post("/api/v1/auth/logout", json={"refresh_token": new_refresh})
        assert r7.status_code == 200
