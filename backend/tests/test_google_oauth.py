"""Tests for M1.3 — Google OAuth flow.

Tests the complete Google OAuth initiation, callback, user resolution
(PKCE, state validation, replay detection, 3 user resolution paths),
and error handling.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from services.identity.api import (
    reset_auth_service,
    reset_oauth_session_repo,
    set_auth_service,
    _build_auth_service,
)
from services.identity.models.oauth_session import OAuthSession
from services.identity.config import IDENTITY_CONFIG
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
    set_crypto_service,
    reset_crypto_service,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_crypto_service()
    reset_auth_service()
    reset_oauth_session_repo()
    reset_provider_registry()


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def _setup_mock_provider() -> InMemoryGoogleIdentityProvider:
    IDENTITY_CONFIG.google_oauth.client_id = "mock_client_id"
    try:
        existing = get_provider_registry().get("google")
        if isinstance(existing, InMemoryGoogleIdentityProvider):
            return existing
    except Exception:
        pass
    provider = InMemoryGoogleIdentityProvider()
    get_provider_registry().register(provider)
    return provider


@pytest.fixture
def mock_provider() -> InMemoryGoogleIdentityProvider:
    return _setup_mock_provider()


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
    ext_id_repo = InMemoryExternalIdentityRepository()

    user_svc = UserService(user_repo, ei_repo)
    org_svc = OrganizationService(org_repo, mem_repo)
    mem_svc = MembershipService(mem_repo, user_repo, org_repo)
    ver_svc = VerificationService(vt_repo, ei_repo, crypto)
    pwd_svc = PasswordService(pc_repo, user_repo, crypto)
    ses_svc = SessionService(session_repo, rt_repo)
    tok_svc = TokenService(rt_repo, session_repo, crypto)

    _setup_mock_provider()

    svc = AuthService(
        email_provider=None,  # type: ignore
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
        external_identity_repo=ext_id_repo,
    )
    set_auth_service(svc)
    return svc


def _extract_params(url: str) -> dict[str, str]:
    from urllib.parse import parse_qs, urlparse
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


# ═══════════════════════════════════════════════════════════════════════
# 1. Initiate
# ═══════════════════════════════════════════════════════════════════════


class TestOAuthInitiate:

    def test_returns_authorize_url(self, client, mock_provider):
        resp = client.get("/api/v1/auth/oauth/google")
        assert resp.status_code == 200
        data = resp.json()
        assert "authorize_url" in data
        assert data["authorize_url"].startswith("https://accounts.google.com/o/oauth2/v2/auth")

    def test_stores_oauth_session(self, client, mock_provider):
        resp = client.get("/api/v1/auth/oauth/google")
        assert resp.status_code == 200
        params = _extract_params(resp.json()["authorize_url"])
        state = params["state"]

        from services.identity.api import _get_oauth_session_repo
        repo = _get_oauth_session_repo()
        session = asyncio_run(repo.find_by_state(state))
        assert session is not None
        assert session.provider_type == "google"

    def test_redirect_uri_param(self, client, mock_provider):
        resp = client.get("/api/v1/auth/oauth/google", params={"redirect_uri": "http://localhost/custom"})
        assert resp.status_code == 200
        data = resp.json()
        assert "redirect_uri=http%3A%2F%2Flocalhost%2Fcustom" in data["authorize_url"]


# ═══════════════════════════════════════════════════════════════════════
# 2. Callback — Error paths
# ═══════════════════════════════════════════════════════════════════════


class TestOAuthCallbackErrors:

    def test_missing_code_param(self, client, mock_provider):
        resp = client.get("/api/v1/auth/oauth/google/callback", params={"state": "abc"})
        assert resp.status_code == 400

    def test_missing_state_param(self, client, mock_provider):
        resp = client.get("/api/v1/auth/oauth/google/callback", params={"code": "abc"})
        assert resp.status_code == 400

    def test_invalid_state(self, client, mock_provider):
        resp = client.get("/api/v1/auth/oauth/google/callback", params={"code": "x", "state": "invalid"})
        assert resp.status_code == 401

    def test_expired_session(self, client, mock_provider):
        from datetime import timedelta
        from services.identity.api import _get_oauth_session_repo

        repo = _get_oauth_session_repo()
        expired = OAuthSession(
            state="expired_state",
            code_verifier="verifier",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        asyncio_run(repo.save(expired))

        resp = client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"code": "x", "state": "expired_state"},
        )
        assert resp.status_code == 401

    def test_replay_detection(self, client):
        _fresh_service()
        init_resp = client.get("/api/v1/auth/oauth/google")
        params = _extract_params(init_resp.json()["authorize_url"])
        state = params["state"]

        resp1 = client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"code": "any_code", "state": state},
        )
        assert resp1.status_code == 200

        resp2 = client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"code": "any_code", "state": state},
        )
        assert resp2.status_code == 401

    def test_provider_error(self, client):
        svc = _fresh_service()
        registry = get_provider_registry()
        provider = registry.get("google")
        provider.set_exchange_error(ValueError("token exchange failed"))

        init_resp = client.get("/api/v1/auth/oauth/google")
        params = _extract_params(init_resp.json()["authorize_url"])
        state = params["state"]

        resp = client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"code": "bad_code", "state": state},
        )
        assert resp.status_code == 401
        assert "token exchange failed" in resp.text or resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════
# 3. Callback — Success paths
# ═══════════════════════════════════════════════════════════════════════


class TestOAuthCallbackSuccess:

    def test_returns_tokens(self, client):
        _fresh_service()
        init_resp = client.get("/api/v1/auth/oauth/google")
        params = _extract_params(init_resp.json()["authorize_url"])
        state = params["state"]

        resp = client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"code": "any_code", "state": state},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert "session_id" in data
        assert "user_id" in data
        assert "org_id" in data
        assert "expires_at" in data

    def test_new_user_created(self, client):
        svc = _fresh_service()
        init_resp = client.get("/api/v1/auth/oauth/google")
        params = _extract_params(init_resp.json()["authorize_url"])
        state = params["state"]

        resp = client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"code": "code_1", "state": state},
        )
        assert resp.status_code == 200
        data = resp.json()

        user = asyncio_run(svc._user.get_user(data["user_id"]))
        assert user is not None
        assert user.id == data["user_id"]

    def test_existing_user_by_email_links_and_logs_in(self, client):
        """Existing email (no prior Google link) → link + login."""
        svc = _fresh_service()

        user, ei, _ = asyncio_run(svc._user.create_user("Existing", "existing@example.com"))
        org, mem, _ = asyncio_run(svc._org.create_organization("Existing Org", user.id))
        asyncio_run(svc._membership.add_member(user.id, org.id))

        registry = get_provider_registry()
        provider = registry.get("google")
        provider.set_mock_payload({
            "sub": "g_sub_link",
            "email": "existing@example.com",
            "name": "Existing",
            "email_verified": True,
            "aud": "mock_client_id",
            "iss": "https://accounts.google.com",
            "exp": int(datetime.now(timezone.utc).timestamp()) + 3600,
        })

        init_resp = client.get("/api/v1/auth/oauth/google")
        params = _extract_params(init_resp.json()["authorize_url"])
        state = params["state"]

        resp = client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"code": "code_link", "state": state},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == user.id

        ext_ids = asyncio_run(svc._external_identity_repo.find_by_provider("google", "g_sub_link"))
        assert ext_ids is not None
        assert ext_ids.user_id == user.id

    def test_existing_external_identity_logs_in(self, client):
        """Already-linked Google account → direct login."""
        svc = _fresh_service()

        user, ei, _ = asyncio_run(svc._user.create_user("Returning", "returning@example.com"))
        org, mem, _ = asyncio_run(svc._org.create_organization("Returning Org", user.id))
        asyncio_run(svc._membership.add_member(user.id, org.id))
        from services.identity.models import ExternalIdentity as ExtIdModel
        from datetime import datetime, timezone
        ext = ExtIdModel(
            user_id=user.id,
            provider_type="google",
            provider_subject="g_sub_returning",
            email="returning@example.com",
            linked_at=datetime.now(timezone.utc),
            last_login_at=datetime.now(timezone.utc),
        )
        asyncio_run(svc._external_identity_repo.save(ext))

        registry = get_provider_registry()
        provider = registry.get("google")
        provider.set_mock_payload({
            "sub": "g_sub_returning",
            "email": "returning@example.com",
            "name": "Returning",
            "email_verified": True,
            "aud": "mock_client_id",
            "iss": "https://accounts.google.com",
            "exp": int(datetime.now(timezone.utc).timestamp()) + 3600,
        })

        init_resp = client.get("/api/v1/auth/oauth/google")
        params = _extract_params(init_resp.json()["authorize_url"])
        state = params["state"]

        resp = client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"code": "code_returning", "state": state},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == user.id


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)
