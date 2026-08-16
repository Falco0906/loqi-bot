"""SaaS-1.3 — authenticated API surface / canonical identity boundary tests.

Covers the fixes from the SaaS-1.3 audit:

- onboarding production gate honors the canonical production indicator
  (ENVIRONMENT OR APP_ENV), so an unauthenticated user_id can never be
  accepted in production
- strategic-intelligence routes are authenticated and bind the actor identity
  to the token (client-supplied user_id ignored)
- billing `_get_current_user` resolves the actor from the canonical
  dependency (no request.state.user_id reliance)
- canonical AuthContext content + /me & session cross-user guarantees
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from services.identity.api import (
    reset_auth_service,
    set_auth_service,
)
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
    reset_auth_service()


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
    set_auth_service(svc)
    return svc, repos


async def _register_user(svc, email):
    reg = await svc.begin_registration(email)
    await svc.verify_email(reg.raw_token)
    return await svc.complete_registration(
        reg.registration_session.id, email.split("@")[0], "StrongPass123!",
        f"{email.split('@')[0]} Org",
    )


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ─── 1. Onboarding production gate ────────────────────────────────────


class TestOnboardingProductionGate:

    def test_production_requires_auth(self, client, monkeypatch):
        from services import config_validation

        monkeypatch.setattr(config_validation, "is_production", lambda env=None: True)
        svc, _ = _build_service()
        complete = asyncio.run(_register_user(svc, "prod@example.com"))

        # No token -> 401, even with a client-supplied user_id.
        resp = client.get("/api/v1/onboarding?user_id=someone")
        assert resp.status_code == 401

        # Token for A + requested user_id B -> 403 (identity mismatch).
        resp = client.get(
            "/api/v1/onboarding?user_id=other-user",
            headers=_headers(complete.session.id),
        )
        assert resp.status_code == 403

        # Token for A + matching user_id -> 200.
        resp = client.get(
            "/api/v1/onboarding?user_id={}".format(complete.user.id),
            headers=_headers(complete.session.id),
        )
        assert resp.status_code == 200

    def test_development_keeps_legacy_contract(self, client, monkeypatch):
        from services import config_validation

        monkeypatch.setattr(config_validation, "is_production", lambda env=None: False)
        resp = client.get("/api/v1/onboarding?user_id=legacy-user")
        assert resp.status_code == 200


# ─── 2. Strategic-intelligence boundary ───────────────────────────────


class TestStrategicIntelligenceBoundary:

    def _stub_onboarding(self, client):
        from services.onboarding import api as onboarding_api

        class _Stub:
            def __init__(self):
                self.saved_user_ids: list[str] = []
                self.saved_data: list[dict] = []
                self.profile = {
                    "strategicProfile": {"name": "Acme"},
                    "strategicProfileGeneratedAt": "2026-01-01T00:00:00+00:00",
                }

            async def save_wizard_data(self, user_id, data):
                self.saved_user_ids.append(user_id)
                self.saved_data.append(data)

            async def get_wizard_data(self, user_id):
                return self.profile

        stub = _Stub()
        onboarding_api.set_onboarding_service(stub)
        return stub

    def test_generate_requires_auth(self, client):
        resp = client.post(
            "/api/v1/strategic-intelligence/generate",
            json={
                "company_description": "d",
                "ideal_customer": "i",
                "differentiation": "x",
                "annual_goal": "g",
                "biggest_obstacle": "o",
            },
        )
        assert resp.status_code == 401

    def test_generate_binds_actor_ignores_payload_user_id(self, client):
        stub = self._stub_onboarding(client)
        svc, _ = _build_service()
        complete = asyncio.run(_register_user(svc, "strat@example.com"))
        resp = client.post(
            "/api/v1/strategic-intelligence/generate",
            json={
                "company_description": "d",
                "ideal_customer": "i",
                "differentiation": "x",
                "annual_goal": "g",
                "biggest_obstacle": "o",
                "user_id": "victim-user-id",
            },
            headers=_headers(complete.session.id),
        )
        assert resp.status_code == 200
        # Persistence targeted the authenticated actor, not the payload user.
        assert stub.saved_user_ids == [complete.user.id]

    def test_profile_requires_auth(self, client):
        resp = client.get("/api/v1/strategic-intelligence/profile/someone")
        assert resp.status_code == 401

    def test_profile_binds_actor_ignores_path_user_id(self, client):
        stub = self._stub_onboarding(client)
        svc, _ = _build_service()
        complete = asyncio.run(_register_user(svc, "strat2@example.com"))
        resp = client.get(
            "/api/v1/strategic-intelligence/profile/victim-user-id",
            headers=_headers(complete.session.id),
        )
        assert resp.status_code == 200
        assert resp.json()["profile"]["name"] == "Acme"


# ─── 3. Billing canonical actor resolution ────────────────────────────


class TestBillingCanonicalAuth:

    def test_unauthenticated_billing_rejected(self, client):
        resp = client.get("/api/v1/billing/subscription?organization_id=org-1")
        assert resp.status_code == 401

    def test_authenticated_billing_passes_auth(self, client):
        svc, _ = _build_service()
        complete = asyncio.run(_register_user(svc, "bill@example.com"))
        # Auth passes (401 would mean failure); missing org_id -> 400.
        resp = client.get(
            "/api/v1/billing/subscription",
            headers=_headers(complete.session.id),
        )
        assert resp.status_code == 400


# ─── 4. Canonical AuthContext + /me + session isolation ───────────────


class TestCanonicalAuthContext:

    def test_auth_context_derived_from_token(self, client):
        svc, _ = _build_service()
        complete = asyncio.run(_register_user(svc, "ctx@example.com"))

        resp = client.get(
            "/api/v1/auth/me",
            headers=_headers(complete.session.id),
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == complete.user.id

        # Client-supplied user_id cannot override the authenticated identity.
        resp = client.get(
            "/api/v1/auth/me?user_id=attacker",
            headers=_headers(complete.session.id),
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == complete.user.id

    def test_session_list_is_actor_scoped(self, client):
        svc, _ = _build_service()
        alice = asyncio.run(_register_user(svc, "alice_saas13@example.com"))
        bob = asyncio.run(_register_user(svc, "bob_saas13@example.com"))

        resp = client.get(
            "/api/v1/auth/sessions?user_id={}".format(bob.user.id),
            headers=_headers(alice.session.id),
        )
        assert resp.status_code == 200
        ids = [s["id"] for s in resp.json()["sessions"]]
        assert alice.session.id in ids
        assert bob.session.id not in ids

    def test_cannot_revoke_other_users_session(self, client):
        svc, _ = _build_service()
        alice = asyncio.run(_register_user(svc, "alice_rev13@example.com"))
        bob = asyncio.run(_register_user(svc, "bob_rev13@example.com"))

        resp = client.delete(
            "/api/v1/auth/sessions/{}".format(bob.session.id),
            headers=_headers(alice.session.id),
        )
        assert resp.status_code == 404

        # Bob's session still validates.
        resp = client.get(
            "/api/v1/auth/me",
            headers=_headers(bob.session.id),
        )
        assert resp.status_code == 200

    def test_logout_only_affects_presented_session(self, client):
        svc, _ = _build_service()
        asyncio.run(_register_user(svc, "logout13@example.com"))
        s1 = asyncio.run(svc.login("logout13@example.com", "StrongPass123!"))
        s2 = asyncio.run(svc.login("logout13@example.com", "StrongPass123!"))

        resp = client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": s1.refresh_token},
        )
        assert resp.status_code == 200

        # s1 revoked, s2 still valid.
        assert client.get("/api/v1/auth/me", headers=_headers(s1.session.id)).status_code == 401
        assert client.get("/api/v1/auth/me", headers=_headers(s2.session.id)).status_code == 200