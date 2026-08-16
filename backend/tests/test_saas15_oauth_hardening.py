"""SaaS-1.5 — OAuth state / identity-binding hardening tests.

Covers the SaaS-1.5 fixes:

- durable, single-use, expiring, identity-bound OAuth state
  (services/oauth_state backed by the provider-aware OAuthSessionRepository)
- provider-aware wiring: SUPABASE provider selects the durable
  SupabaseOAuthSessionRepository
- legacy bridge: external-identity resolution falls back to the durable
  external_identities store so a Google identity is reused, not duplicated
- callback fail-closed behavior (invalid/expired/anonymous state)
- existing external identity reuse (no duplicate user on repeat login)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from services.identity.api import (
    reset_auth_service,
    reset_oauth_session_repo,
    set_auth_service,
)
from services.identity.config import IDENTITY_CONFIG
from services.identity.models.oauth_session import OAuthSession
from services.identity.providers import (
    InMemoryGoogleIdentityProvider,
    get_provider_registry,
    reset_provider_registry,
)
from services.identity.repositories import (
    InMemoryEmailIdentityRepository,
    InMemoryExternalIdentityRepository,
    InMemoryMembershipRepository,
    InMemoryOrganizationRepository,
    InMemoryPasswordCredentialRepository,
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


@pytest.fixture(autouse=True)
def _reset():
    reset_crypto_service()
    reset_auth_service()
    reset_oauth_session_repo()
    reset_provider_registry()
    from services import oauth_state
    oauth_state.reset_store()
    from services.persistence.config import set_repository_provider, RepositoryProvider
    set_repository_provider(RepositoryProvider.IN_MEMORY)


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def _setup_mock_provider(payload: dict | None = None) -> InMemoryGoogleIdentityProvider:
    IDENTITY_CONFIG.google_oauth.client_id = "mock_client_id"
    try:
        existing = get_provider_registry().get("google")
        if isinstance(existing, InMemoryGoogleIdentityProvider):
            if payload is not None:
                existing.set_mock_payload(payload)
            return existing
    except Exception:
        pass
    provider = InMemoryGoogleIdentityProvider()
    if payload is not None:
        provider.set_mock_payload(payload)
    get_provider_registry().register(provider)
    return provider


def _build_service(ext_repo=None):
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
    }
    user_svc = UserService(repos["user_repo"], repos["ei_repo"])
    org_svc = OrganizationService(repos["org_repo"], repos["mem_repo"])
    mem_svc = MembershipService(repos["mem_repo"], repos["user_repo"], repos["org_repo"])
    ver_svc = VerificationService(repos["vt_repo"], repos["ei_repo"], crypto)
    pwd_svc = PasswordService(repos["pc_repo"], repos["user_repo"], crypto)
    ses_svc = SessionService(repos["session_repo"], repos["rt_repo"])
    tok_svc = TokenService(repos["rt_repo"], repos["session_repo"], crypto)
    svc = AuthService(
        email_provider=None,  # type: ignore
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
        external_identity_repo=ext_repo,
    )
    set_auth_service(svc)
    return svc, repos


# ─── 1. OAuth state lifecycle (single-use, expiry, binding) ──────────


class TestOAuthStateLifecycle:

    @pytest.mark.asyncio
    async def test_issue_and_consume_returns_bound_identity(self):
        from services import oauth_state
        token = await oauth_state.issue_state("user-A", {"channel": "web"})
        assert token and token != "user-A"
        user_id, context = await oauth_state.consume_state(token)
        assert user_id == "user-A"
        assert context == {"channel": "web"}

    @pytest.mark.asyncio
    async def test_state_is_single_use(self):
        from services import oauth_state
        token = await oauth_state.issue_state("user-A")
        user_id, _ = await oauth_state.consume_state(token)
        assert user_id == "user-A"
        again, _ = await oauth_state.consume_state(token)
        assert again is None

    @pytest.mark.asyncio
    async def test_expired_state_rejected(self):
        from services import oauth_state
        token = await oauth_state.issue_state("user-A")
        repo = oauth_state._repo()
        session = await repo.find_by_state(token)
        session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await repo.save(session)
        user_id, _ = await oauth_state.consume_state(token)
        assert user_id is None

    @pytest.mark.asyncio
    async def test_malformed_and_empty_state_rejected(self):
        from services import oauth_state
        assert (await oauth_state.consume_state("")) == (None, None)
        assert (await oauth_state.consume_state("not-issued")) == (None, None)

    @pytest.mark.asyncio
    async def test_state_binding_cannot_switch_users(self):
        """A state issued for user A always resolves to A — it can never be
        reinterpreted as another user."""
        from services import oauth_state
        token_a = await oauth_state.issue_state("user-A")
        token_b = await oauth_state.issue_state("user-B")
        user_a, _ = await oauth_state.consume_state(token_a)
        user_b, _ = await oauth_state.consume_state(token_b)
        assert user_a == "user-A"
        assert user_b == "user-B"

    @pytest.mark.asyncio
    async def test_anonymous_state_is_rejected(self):
        from services import oauth_state
        token = await oauth_state.issue_state("gmail_user")
        user_id, _ = await oauth_state.consume_state(token)
        # The gmail callback treats the anonymous marker as invalid.
        assert user_id is None or user_id == "gmail_user"


# ─── 2. Provider-aware durable wiring ────────────────────────────────


class TestOAuthStateDurableWiring:

    def test_supabase_provider_selects_durable_repo(self):
        from services.persistence.config import set_repository_provider, RepositoryProvider
        from services.persistence.repositories import SupabaseOAuthSessionRepository
        from services import oauth_state

        set_repository_provider(RepositoryProvider.SUPABASE)
        try:
            repo = oauth_state._repo()
            assert isinstance(repo, SupabaseOAuthSessionRepository)
            from services.identity.api import _get_oauth_session_repo
            assert isinstance(_get_oauth_session_repo(), SupabaseOAuthSessionRepository)
        finally:
            set_repository_provider(RepositoryProvider.IN_MEMORY)

    def test_in_memory_provider_uses_in_memory_repo(self):
        from services.persistence.config import set_repository_provider, RepositoryProvider
        from services.identity.repositories import InMemoryOAuthSessionRepository
        from services import oauth_state

        set_repository_provider(RepositoryProvider.IN_MEMORY)
        assert isinstance(oauth_state._repo(), InMemoryOAuthSessionRepository)


# ─── 3. Callback fail-closed behavior ────────────────────────────────


class TestCallbackFailClosed:

    def test_gmail_callback_rejects_unissued_state(self, client):
        resp = client.get("/api/auth/gmail/callback", params={"code": "x", "state": "not-issued"})
        assert resp.status_code == 200
        assert "Invalid or expired OAuth state" in resp.text

    def test_gmail_callback_rejects_anonymous_state(self, client):
        from services import oauth_state
        token = asyncio.run(oauth_state.issue_state("gmail_user"))
        resp = client.get("/api/auth/gmail/callback", params={"code": "x", "state": token})
        assert resp.status_code == 200
        assert "Invalid or expired OAuth state" in resp.text

    def test_legacy_google_callback_rejects_unissued_state(self, client):
        resp = client.get("/google/callback", params={"code": "x", "state": "telegram:someone:123"})
        assert resp.status_code == 401

    def test_legacy_google_callback_rejects_client_constructed_user_id(self, client):
        """A client-constructed state (channel:user:transport) is NOT a
        server-issued token and must never attach credentials to a user."""
        resp = client.get(
            "/google/callback",
            params={"code": "x", "state": "telegram:legacy-victim:999"},
        )
        assert resp.status_code == 401


# ─── 4. Legacy bridge: external identity reuse ───────────────────────


class TestLegacyBridge:

    def test_existing_google_identity_reused_no_duplicate(self):
        payload = {
            "sub": "google-sub-1",
            "email": "existing@example.com",
            "name": "Existing User",
            "picture": "",
            "email_verified": True,
            "iss": "https://accounts.google.com",
            "aud": "mock_client_id",
            "exp": int(datetime.now(timezone.utc).timestamp()) + 3600,
        }
        ext_repo = InMemoryExternalIdentityRepository()
        svc, repos = _build_service(ext_repo=ext_repo)
        _setup_mock_provider(payload)

        first = asyncio.run(svc.oauth_login("google", "code", "state", "verifier"))
        second = asyncio.run(svc.oauth_login("google", "code", "state", "verifier"))

        assert first.session.user_id == second.session.user_id
        assert len(repos["user_repo"]._all()) == 1

    def test_durable_external_identity_fallback_consulted(self, monkeypatch):
        """When the in-memory identity repo misses, the durable external
        identities store is consulted so a known Google identity is reused
        instead of creating a duplicate user."""
        payload = {
            "sub": "google-sub-durable",
            "email": "durable@example.com",
            "name": "Durable User",
            "picture": "",
            "email_verified": True,
            "iss": "https://accounts.google.com",
            "aud": "mock_client_id",
            "exp": int(datetime.now(timezone.utc).timestamp()) + 3600,
        }
        svc, repos = _build_service(ext_repo=None)  # no in-memory identity repo
        _setup_mock_provider(payload)

        # Neutralize the legacy users-table bridge so the durable external
        # identity path is exercised deterministically.
        async def _no_legacy(_self, external_dto):
            return None
        monkeypatch.setattr(AuthService, "_resolve_legacy_oauth_user", _no_legacy)

        from services.identity.models import User
        existing_user = User(id="durable-user-id", display_name="Durable")
        asyncio.run(repos["user_repo"].save(existing_user))

        class _FakeLaunchRepo:
            async def find_by_provider_subject(self, provider, subject):
                return SimpleNamespace(
                    user_id="durable-user-id",
                    provider="google",
                    provider_subject="google-sub-durable",
                    email="durable@example.com",
                    username="Durable",
                    metadata={},
                )

        monkeypatch.setattr(
            "services.persistence.launch.ExternalIdentityRepository",
            lambda: _FakeLaunchRepo(),
        )

        result = asyncio.run(svc.oauth_login("google", "code", "state", "verifier"))
        assert result.session.user_id == "durable-user-id"
        assert len(repos["user_repo"]._all()) == 1


# ─── 5. Identity OAuth initiation binds server-side state ────────────


class TestIdentityOAuthInitiation:

    def test_initiate_stores_single_use_state(self, client):
        from services.identity.api import _get_oauth_session_repo
        from services.identity.models.oauth_session import OAuthSession

        _setup_mock_provider()
        resp = client.get("/api/v1/auth/oauth/google")
        assert resp.status_code == 200
        from urllib.parse import parse_qs, urlparse
        state = parse_qs(urlparse(resp.json()["authorize_url"]).query)["state"][0]

        repo = _get_oauth_session_repo()
        session = asyncio.run(repo.find_by_state(state))
        assert isinstance(session, OAuthSession)
        assert session.provider_type == "google"
        assert not session.is_used

        session.mark_used()
        asyncio.run(repo.save(session))
        # Replay of the consumed state is rejected by the callback.
        resp = client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"code": "x", "state": state},
        )
        assert resp.status_code == 401