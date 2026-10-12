"""Offline tests for per-state Google OAuth callback URI binding."""

import asyncio
import base64
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from services.identity import api as identity_api
from services.identity.config import (
    IDENTITY_CONFIG,
    resolve_google_oauth_redirect_uri,
)
from services.identity.models.oauth_session import OAuthSession
from services.identity.providers import GoogleIdentityProvider, get_provider_registry
from services.identity.providers.registry import reset_provider_registry


@pytest.fixture(autouse=True)
def reset_oauth_state(monkeypatch):
    identity_api.reset_oauth_session_repo()
    reset_provider_registry()
    monkeypatch.setattr(
        IDENTITY_CONFIG.google_oauth,
        "redirect_uri",
        "https://app.example.test/auth/google/callback",
    )
    monkeypatch.setattr(
        IDENTITY_CONFIG.google_oauth,
        "local_redirect_uris",
        ("http://localhost:3000/auth/google/callback",),
    )
    yield
    identity_api.reset_oauth_session_repo()
    reset_provider_registry()


def _params(authorize_url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlparse(authorize_url).query).items()}


@pytest.mark.parametrize(
    "callback_uri",
    [
        "http://localhost:3000/auth/google/callback",
        "http://127.0.0.1:3000/auth/google/callback",
    ],
)
def test_allowlisted_local_callback_is_used_and_bound_to_state(callback_uri, monkeypatch):
    allowed = tuple(set(IDENTITY_CONFIG.google_oauth.local_redirect_uris) | {callback_uri})
    monkeypatch.setattr(IDENTITY_CONFIG.google_oauth, "local_redirect_uris", allowed)
    provider = GoogleIdentityProvider()
    get_provider_registry().register(provider)

    response = asyncio.run(identity_api.oauth_google(callback_uri))
    params = _params(response.authorize_url)
    session = asyncio.run(identity_api._get_oauth_session_repo().find_by_state(params["state"]))

    assert params["redirect_uri"] == callback_uri
    assert session is not None
    assert session.redirect_uri == callback_uri


@pytest.mark.parametrize(
    "callback_uri",
    [
        "https://attacker.example/auth/google/callback",
        "http://localhost:3001/auth/google/callback",
        "http://localhost:3000/other",
        "http://localhost:3000/auth/google/callback/",
        "http://127.0.0.1:3000/auth/google/callback",
        "//localhost:3000/auth/google/callback",
    ],
)
def test_unapproved_callback_overrides_are_rejected_before_session_creation(callback_uri):
    with pytest.raises(identity_api.HTTPException) as error:
        asyncio.run(identity_api.oauth_google(callback_uri))

    assert error.value.status_code == 400
    assert identity_api._oauth_session_repo is None


def test_no_override_preserves_configured_production_callback():
    get_provider_registry().register(GoogleIdentityProvider())

    response = asyncio.run(identity_api.oauth_google())
    params = _params(response.authorize_url)
    session = asyncio.run(identity_api._get_oauth_session_repo().find_by_state(params["state"]))

    assert params["redirect_uri"] == IDENTITY_CONFIG.google_oauth.redirect_uri
    assert session is not None
    assert session.redirect_uri == IDENTITY_CONFIG.google_oauth.redirect_uri
    assert resolve_google_oauth_redirect_uri() == IDENTITY_CONFIG.google_oauth.redirect_uri


def test_authorization_and_code_exchange_use_the_same_callback_uri(monkeypatch):
    callback_uri = "http://localhost:3000/auth/google/callback"
    provider = GoogleIdentityProvider()
    authorization = _params(asyncio.run(provider.initiate_auth(callback_uri)).authorize_url)
    payload = {
        "sub": "subject",
        "email": "user@example.test",
        "email_verified": True,
        "iss": "https://accounts.google.com",
        "aud": "test-client",
        "exp": int(datetime.now(timezone.utc).timestamp()) + 600,
    }
    encoded_payload = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id_token": f"header.{encoded_payload}.signature"}

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, *, data):
            captured.update(data)
            return FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(IDENTITY_CONFIG.google_oauth, "client_id", "test-client")

    asyncio.run(provider.handle_callback("offline-code", authorization["state"], "pkce-verifier", callback_uri))

    assert authorization["redirect_uri"] == callback_uri
    assert captured["redirect_uri"] == callback_uri


def test_callback_uses_stored_uri_and_state_remains_single_use(monkeypatch):
    callback_uri = "http://localhost:3000/auth/google/callback"
    repo = identity_api._get_oauth_session_repo()
    session = OAuthSession(
        provider_type="google",
        state="opaque-test-state",
        code_verifier="stored-verifier",
        redirect_uri=callback_uri,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    asyncio.run(repo.save(session))
    calls = []

    class Service:
        async def oauth_login(self, **kwargs):
            calls.append(kwargs)
            raise RuntimeError("offline test stop")

    monkeypatch.setattr(identity_api, "_get_service", lambda: Service())
    with pytest.raises(identity_api.HTTPException) as first:
        asyncio.run(identity_api.oauth_google_callback("offline-code", "opaque-test-state"))
    assert first.value.status_code == 401
    assert calls[0]["redirect_uri"] == callback_uri
    assert calls[0]["code_verifier"] == "stored-verifier"

    with pytest.raises(identity_api.HTTPException) as replay:
        asyncio.run(identity_api.oauth_google_callback("offline-code", "opaque-test-state"))
    assert replay.value.status_code == 401
    assert len(calls) == 1
