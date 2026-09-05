"""Characterization tests for Gmail inbound-to-outbound runtime projection."""

from __future__ import annotations

from services.communication import provider_startup


class _CommunicationProvider:
    _access_token = "access-token"
    _refresh_token = "refresh-token"
    _client_id = "client-id"
    _client_secret = "client-secret"
    _token_expiry = 123.0
    _user_id = "user-1"


def test_register_outbound_gmail_instance_copies_connected_provider_credentials(monkeypatch):
    registered: dict[str, object] = {}
    monkeypatch.setattr(provider_startup, "get_provider", lambda provider_id: _CommunicationProvider())
    monkeypatch.setattr(
        provider_startup,
        "register_outbound_instance",
        lambda provider_id, provider: registered.update({provider_id: provider}),
    )

    provider_startup.register_outbound_gmail_instance("provider-1")

    outbound = registered["provider-1"]
    assert outbound._provider_id == "provider-1"
    assert outbound._access_token == "access-token"
    assert outbound._refresh_token == "refresh-token"
    assert outbound._client_id == "client-id"
    assert outbound._client_secret == "client-secret"
    assert outbound._token_expiry == 123.0
    assert outbound._user_id == "user-1"


def test_register_outbound_gmail_instance_skips_provider_without_credentials(monkeypatch, caplog):
    class _NoCredentials:
        _access_token = ""
        _refresh_token = ""

    registered: list[str] = []
    monkeypatch.setattr(provider_startup, "get_provider", lambda provider_id: _NoCredentials())
    monkeypatch.setattr(
        provider_startup,
        "register_outbound_instance",
        lambda provider_id, provider: registered.append(provider_id),
    )

    with caplog.at_level("WARNING", logger="loqi"):
        provider_startup.register_outbound_gmail_instance("provider-1")

    assert registered == []
    assert "No tokens available for provider provider-1" in caplog.text
