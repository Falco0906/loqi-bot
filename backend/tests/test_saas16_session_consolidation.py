"""SaaS-1.6 — web-session → canonical identity/session consolidation tests.

Verifies the session-authority relationship established in SaaS-1.6:

- an authenticated web-session bootstrap binds the web token to the canonical
  identity session (web_session_bindings)
- a bound web-session resolves the actor to the canonical user, never to a
  client-supplied identity
- a bound web-session is authorized ONLY while the canonical session remains
  valid — revoking or expiring the canonical session invalidates the web
  session (401)
- unbound (anonymous/legacy) web-sessions keep legacy behavior
- the OAuth callback no longer keeps a token-bearing replay cache; a consumed
  state is rejected (401)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.identity.api import (
    reset_auth_service,
    reset_oauth_session_repo,
    set_auth_service,
)
from services.identity.models.oauth_session import OAuthSession
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
    reset_oauth_session_repo()
    from services import web_session_binding
    web_session_binding.reset_store()


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


def _real_resolve():
    from tests.conftest import REAL_RESOLVE_SESSION_CONTEXT
    return REAL_RESOLVE_SESSION_CONTEXT


def _web_request(web_token: str):
    class _Req:
        headers = {"authorization": f"Bearer {web_token}"}

        @property
        def url(self):
            return type("U", (), {"path": "/api/web/session/_"})

    return _Req()


def _fake_engine_summary(monkeypatch, mapping: dict):
    """Make the web-session summary resolvable without hitting Supabase."""
    import main as main_module

    def summary(token):
        return mapping.get(token)

    monkeypatch.setattr(main_module.engine, "get_web_session_summary", summary)


# ─── 1. Bootstrap binds web-session to canonical identity ─────────────


class TestBootstrapBinding:

    def test_authenticated_bootstrap_records_binding(self, client, monkeypatch):
        from services import web_session_binding

        svc, _ = _build_service()
        complete = asyncio.run(_register_user(svc, "bind@example.com"))
        session_id = complete.session.id

        import main as main_module

        def fake_engine_create(display_name=None, *, user_id=None):
            return {
                "ok": True,
                "session_token": "web-tok-bind",
                "user_id": user_id,
                "display_name": display_name,
                "gmail_connected": False,
                "initial_messages": [],
            }

        monkeypatch.setattr(main_module, "engine", type("E", (), {
            "create_web_session": fake_engine_create,
            "get_web_session_summary": lambda t: None,
        }))
        async def fake_current_auth(request):
            from services.identity.dependencies import AuthContext
            return AuthContext(user_id=complete.user.id, session_id=session_id, organization_id="")

        monkeypatch.setattr("services.identity.dependencies.get_current_auth", fake_current_auth)

        resp = client.post(
            "/api/web/session",
            json={"display_name": "Ada"},
            headers={"Authorization": f"Bearer {session_id}"},
        )
        assert resp.status_code == 200

        binding = asyncio.run(web_session_binding.find_binding("web-tok-bind"))
        assert binding is not None
        assert binding.canonical_user_id == complete.user.id
        assert binding.canonical_session_id == session_id

    def test_unauthenticated_bootstrap_no_binding(self, client):
        from services import web_session_binding
        resp = client.post("/api/web/session", json={"display_name": "Anon"})
        assert resp.status_code == 200
        # No canonical session was involved; nothing can be bound.
        assert asyncio.run(web_session_binding.find_binding("")) is None


# ─── 2. Bound web-session resolution + canonical validity gate ────────


class TestSessionAuthority:

    def test_bound_web_session_resolves_to_canonical_user(self, monkeypatch):
        from services import web_session_binding

        svc, _ = _build_service()
        complete = asyncio.run(_register_user(svc, "auth@example.com"))
        session_id = complete.session.id
        web_token = "web-tok-auth"

        asyncio.run(web_session_binding.bind_web_session(
            web_token, complete.user.id, session_id,
        ))
        _fake_engine_summary(monkeypatch, {web_token: {"user_id": "legacy-synthetic"}})

        owner, _ = asyncio.run(_real_resolve()(_web_request(web_token)))
        # The canonical identity is authoritative, not the legacy web user.
        assert owner == complete.user.id

    def test_revoked_canonical_session_invalidates_bound_web_session(self, monkeypatch):
        from services import web_session_binding
        from fastapi import HTTPException as FE

        svc, _ = _build_service()
        complete = asyncio.run(_register_user(svc, "rev@example.com"))
        login = asyncio.run(svc.login("rev@example.com", "StrongPass123!"))
        session_id = login.session.id
        web_token = "web-tok-rev"

        asyncio.run(web_session_binding.bind_web_session(web_token, complete.user.id, session_id))
        _fake_engine_summary(monkeypatch, {web_token: {"user_id": "legacy-synthetic"}})

        # While valid, the bound web session resolves to the canonical user.
        owner, _ = asyncio.run(_real_resolve()(_web_request(web_token)))
        assert owner == complete.user.id

        # Logout revokes the canonical session -> bound web session rejected.
        asyncio.run(svc.logout(login.refresh_token))
        with pytest.raises(FE) as exc_info:
            asyncio.run(_real_resolve()(_web_request(web_token)))
        assert exc_info.value.status_code == 401

    def test_expired_canonical_session_invalidates_bound_web_session(self, monkeypatch):
        from services import web_session_binding
        from fastapi import HTTPException as FE

        svc, repos = _build_service()
        complete = asyncio.run(_register_user(svc, "exp@example.com"))
        session_id = complete.session.id
        web_token = "web-tok-exp"

        asyncio.run(web_session_binding.bind_web_session(web_token, complete.user.id, session_id))
        _fake_engine_summary(monkeypatch, {web_token: {"user_id": "legacy-synthetic"}})

        session = asyncio.run(repos["session_repo"].get(session_id))
        session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        asyncio.run(repos["session_repo"].save(session))

        with pytest.raises(FE) as exc_info:
            asyncio.run(_real_resolve()(_web_request(web_token)))
        assert exc_info.value.status_code == 401

    def test_unbound_web_session_keeps_legacy_resolution(self, monkeypatch):
        web_token = "web-tok-anon"
        _fake_engine_summary(monkeypatch, {web_token: {"user_id": "legacy-synthetic"}})

        owner, _ = asyncio.run(_real_resolve()(_web_request(web_token)))
        assert owner == "legacy-synthetic"

    def test_password_change_keeps_bound_web_session_password_reset_revokes(self, monkeypatch):
        from services import web_session_binding
        from fastapi import HTTPException as FE

        svc, _ = _build_service()
        complete = asyncio.run(_register_user(svc, "pw@example.com"))
        login = asyncio.run(svc.login("pw@example.com", "StrongPass123!"))
        session_id = login.session.id
        web_token = "web-tok-pw"

        asyncio.run(web_session_binding.bind_web_session(web_token, complete.user.id, session_id))
        _fake_engine_summary(monkeypatch, {web_token: {"user_id": "legacy-synthetic"}})

        # Password change with keep_session_id preserves the current session,
        # so the bound web session remains valid.
        asyncio.run(svc.change_password(
            complete.user.id, "StrongPass123!", "NewStrongPass456!",
            keep_session_id=session_id,
        ))
        owner, _ = asyncio.run(_real_resolve()(_web_request(web_token)))
        assert owner == complete.user.id

        # Password reset revokes ALL canonical sessions -> bound web session invalid.
        raw = asyncio.run(_new_reset_token(svc, "pw@example.com"))
        asyncio.run(svc.confirm_password_reset("pw@example.com", raw, "AnotherPass789!"))

        with pytest.raises(FE) as exc_info:
            asyncio.run(_real_resolve()(_web_request(web_token)))
        assert exc_info.value.status_code == 401


async def _new_reset_token(svc, email):
    class _Capture(_DummyEmail):
        def __init__(self):
            self.urls = []
        async def send_password_reset_email(self, to, reset_url):
            self.urls.append(reset_url)

    provider = _Capture()
    svc._email = provider
    await svc.request_password_reset(email)
    assert provider.urls
    return provider.urls[-1].split("token=")[1].split("&")[0]


# ─── 3. OAuth callback: no token replay cache ─────────────────────────


class TestOAuthReplay:

    def test_used_state_rejected_no_token_cache(self, client):
        from services.identity.api import _get_oauth_session_repo

        repo = _get_oauth_session_repo()
        session = OAuthSession(
            state="used-state",
            code_verifier="v",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        session.mark_used()
        asyncio.run(repo.save(session))

        resp = client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"code": "x", "state": "used-state"},
        )
        assert resp.status_code == 401

    def test_module_has_no_callback_result_cache(self):
        import services.identity.api as api
        assert not hasattr(api, "_oauth_callback_results")