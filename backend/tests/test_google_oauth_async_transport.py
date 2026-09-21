"""Regression coverage for the legacy Google OAuth requests transport."""

from __future__ import annotations

import threading

import pytest

from services.providers.google.oauth import GoogleOAuthFlow
from services.providers.oauth import OAuthToken


class _Response:
    def __init__(self, payload: dict | None = None) -> None:
        self._payload = payload or {"access_token": "access", "expires_in": 3600}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


@pytest.mark.asyncio
async def test_exchange_code_offloads_requests_transport(monkeypatch):
    """The async OAuth contract must not execute requests.post on its loop."""
    import services.providers.google.oauth as oauth

    call_threads: list[int] = []

    def fake_post(*_args, **_kwargs):
        call_threads.append(threading.get_ident())
        return _Response()

    monkeypatch.setattr(oauth.requests, "post", fake_post)
    caller_thread = threading.get_ident()

    token = await GoogleOAuthFlow(client_id="client", client_secret="secret").exchange_code("code")

    assert token.access_token == "access"
    assert len(call_threads) == 1
    assert call_threads[0] != caller_thread


@pytest.mark.asyncio
async def test_refresh_and_revoke_offload_requests_transport(monkeypatch):
    import services.providers.google.oauth as oauth

    call_threads: list[int] = []

    def fake_post(*_args, **_kwargs):
        call_threads.append(threading.get_ident())
        return _Response()

    monkeypatch.setattr(oauth.requests, "post", fake_post)
    caller_thread = threading.get_ident()
    flow = GoogleOAuthFlow(client_id="client", client_secret="secret")
    current = OAuthToken(access_token="access", refresh_token="refresh")

    refreshed = await flow.refresh_token(current)
    await flow.revoke_token(refreshed)

    assert refreshed.refresh_token == "refresh"
    assert len(call_threads) == 2
    assert all(thread_id != caller_thread for thread_id in call_threads)
