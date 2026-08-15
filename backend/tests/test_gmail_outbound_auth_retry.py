"""GmailOutboundProvider refresh-on-401 retry + token persistence tests."""
import requests as real_requests

import pytest

from services.outbound.gmail_outbound import GmailOutboundProvider
from services.outbound.outbound_models import (
    DeliveryStatus,
    DraftMessage,
    Recipient,
    SendRequest,
)


class FakeResp:
    def __init__(self, status_code: int, payload: dict, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or str(payload)

    def json(self) -> dict:
        return self._payload


def _provider(refresh_token="rt1", user_id="u1", access_token="at-old") -> GmailOutboundProvider:
    p = GmailOutboundProvider()
    p.configure(
        provider_id="prov1",
        access_token=access_token,
        refresh_token=refresh_token,
        client_id="cid",
        client_secret="csec",
        token_expiry=9999999999.0,
        user_id=user_id,
    )
    return p


def _send_request() -> SendRequest:
    return SendRequest(
        provider_id="prov1",
        subject="Subj",
        body="Body",
        recipient=Recipient(email="to@x.com", name="To"),
        sender=Recipient(email="from@x.com", name="From"),
        thread_id="thread1",
    )


def _draft() -> DraftMessage:
    return DraftMessage(
        id="d1",
        provider_id="prov1",
        external_draft_id="ext1",
        subject="Subj",
        body="Body",
        recipient=Recipient(email="to@x.com", name="To"),
        sender=Recipient(email="from@x.com", name="From"),
    )


@pytest.fixture
def fake_requests(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, "headers": kwargs.get("headers", {})})
        return FakeResp(401, {"error": {"code": 401, "message": "Invalid Credentials",
                                        "errors": [{"message": "Invalid Credentials",
                                                    "domain": "global", "reason": "authError"}],
                                        "status": "UNAUTHENTICATED"}}, text="Invalid Credentials")

    monkeypatch.setattr(real_requests, "request", fake_request)
    return calls


def _refresh_set_token(provider, calls):
    counter = {"n": 0}

    def fake_refresh():
        counter["n"] += 1
        provider._access_token = f"at-refreshed-{counter['n']}"

    return fake_refresh, counter


def test_send_retries_once_on_401(monkeypatch, fake_requests):
    provider = _provider()
    refresh, counter = _refresh_set_token(provider, calls=None)
    monkeypatch.setattr(provider, "_refresh_auth", refresh)

    def fake_request(method, url, **kwargs):
        fake_requests.append({"method": method, "url": url, "headers": kwargs.get("headers", {})})
        if len(fake_requests) == 1:
            return FakeResp(401, {"error": {"status": "UNAUTHENTICATED"}}, text="Invalid Credentials")
        return FakeResp(200, {"id": "msg123", "threadId": "thread1"})

    monkeypatch.setattr(real_requests, "request", fake_request)

    result = provider.send(_send_request())

    assert result.status == DeliveryStatus.SENT
    assert result.external_message_id == "msg123"
    assert counter["n"] == 1
    assert len(fake_requests) == 2
    assert fake_requests[1]["headers"]["Authorization"] == "Bearer at-refreshed-1"


def test_send_no_refresh_token_no_retry(monkeypatch, fake_requests):
    provider = _provider(refresh_token="")
    refreshed = {"n": 0}
    monkeypatch.setattr(provider, "_refresh_auth", lambda: refreshed.__setitem__("n", refreshed["n"] + 1))

    result = provider.send(_send_request())

    assert refreshed["n"] == 0
    assert result.status == DeliveryStatus.FAILED
    assert len(fake_requests) == 1


def test_401_with_failing_refresh_propagates(monkeypatch, fake_requests):
    provider = _provider()

    def boom():
        raise Exception("Token refresh failed: invalid_grant")

    monkeypatch.setattr(provider, "_refresh_auth", boom)

    with pytest.raises(Exception, match="invalid_grant"):
        provider.send(_send_request())
    assert len(fake_requests) == 1


def test_success_does_not_refresh(monkeypatch, fake_requests):
    provider = _provider()
    refreshed = {"n": 0}
    monkeypatch.setattr(provider, "_refresh_auth", lambda: refreshed.__setitem__("n", refreshed["n"] + 1))

    def fake_request(method, url, **kwargs):
        fake_requests.append({"method": method, "url": url, "headers": kwargs.get("headers", {})})
        return FakeResp(200, {"id": "msg456", "threadId": "t2"})

    monkeypatch.setattr(real_requests, "request", fake_request)

    result = provider.send(_send_request())

    assert result.status == DeliveryStatus.SENT
    assert refreshed["n"] == 0
    assert len(fake_requests) == 1


def test_create_draft_retries_on_401(monkeypatch, fake_requests):
    provider = _provider()
    refresh, counter = _refresh_set_token(provider, calls=None)
    monkeypatch.setattr(provider, "_refresh_auth", refresh)

    def fake_request(method, url, **kwargs):
        fake_requests.append({"method": method, "url": url, "headers": kwargs.get("headers", {})})
        if len(fake_requests) == 1:
            return FakeResp(401, {"error": {"status": "UNAUTHENTICATED"}}, text="Invalid Credentials")
        return FakeResp(200, {"id": "draft123"})

    monkeypatch.setattr(real_requests, "request", fake_request)

    draft = provider.create_draft(_draft())

    assert draft.external_draft_id == "draft123"
    assert counter["n"] == 1
    assert len(fake_requests) == 2


def test_non_401_error_not_retried(monkeypatch, fake_requests):
    provider = _provider()
    refreshed = {"n": 0}
    monkeypatch.setattr(provider, "_refresh_auth", lambda: refreshed.__setitem__("n", refreshed["n"] + 1))

    def fake_request(method, url, **kwargs):
        fake_requests.append({"method": method, "url": url, "headers": kwargs.get("headers", {})})
        return FakeResp(403, {"error": {"message": "nope"}}, text="nope")

    monkeypatch.setattr(real_requests, "request", fake_request)

    result = provider.send(_send_request())

    assert refreshed["n"] == 0
    assert result.status == DeliveryStatus.FAILED
    assert len(fake_requests) == 1


def test_refresh_persists_token_when_user_id_set(monkeypatch):
    provider = _provider()
    captured = {}

    fake_update = lambda user_id, *, access_token, token_expiry: captured.update(
        user_id=user_id, access_token=access_token, token_expiry=token_expiry
    ) or {}

    def fake_token_post(url, data=None, timeout=None, **_kw):
        assert url == "https://oauth2.googleapis.com/token"
        assert data["grant_type"] == "refresh_token"
        return FakeResp(200, {"access_token": "at-new", "expires_in": 3600})

    monkeypatch.setattr(real_requests, "post", fake_token_post)
    monkeypatch.setattr("services.supabase.update_google_access_token", fake_update)

    provider._refresh_auth()

    assert provider._access_token == "at-new"
    assert captured.get("user_id") == "u1"
    assert captured.get("access_token") == "at-new"
    assert captured["token_expiry"]


def test_refresh_no_user_id_skips_persist(monkeypatch):
    provider = _provider(user_id="")
    captured = []

    fake_update = lambda user_id, *, access_token, token_expiry: captured.append((user_id, access_token))

    def fake_token_post(url, data=None, timeout=None, **_kw):
        return FakeResp(200, {"access_token": "at-new", "expires_in": 3600})

    monkeypatch.setattr(real_requests, "post", fake_token_post)
    monkeypatch.setattr("services.supabase.update_google_access_token", fake_update)

    provider._refresh_auth()

    assert provider._access_token == "at-new"
    assert captured == []


class _RecordingResp(FakeResp):
    pass


def _capture_payload(fake_requests, payloads, status=200):
    def fake_request(method, url, **kwargs):
        fake_requests.append({"method": method, "url": url})
        payloads.append(kwargs.get("json", {}))
        return FakeResp(200, {"id": "msg999", "threadId": "t"})

    return fake_request


def test_send_drops_synthetic_thread_id(monkeypatch):
    provider = _provider()
    calls, payloads = [], []
    monkeypatch.setattr(real_requests, "request", _capture_payload(calls, payloads))

    req = _send_request()
    req.thread_id = "thread_abc123"
    result = provider.send(req)

    assert result.status == DeliveryStatus.SENT
    assert len(calls) == 1
    assert "threadId" not in payloads[0], payloads[0]


def test_send_keeps_real_gmail_thread_id(monkeypatch):
    provider = _provider()
    calls, payloads = [], []
    monkeypatch.setattr(real_requests, "request", _capture_payload(calls, payloads))

    req = _send_request()
    req.thread_id = "1938a1b2c3d4e5f6"
    result = provider.send(req)

    assert result.status == DeliveryStatus.SENT
    assert len(calls) == 1
    assert payloads[0].get("threadId") == "1938a1b2c3d4e5f6"


def test_build_message_drops_synthetic_reply_to(monkeypatch):
    provider = _provider()
    calls, payloads = [], []
    monkeypatch.setattr(real_requests, "request", _capture_payload(calls, payloads))

    req = _send_request()
    req.reply_to_message_id = "thread_abc123"
    provider.send(req)

    assert len(calls) == 1
    assert "threadId" not in payloads[0]


def test_create_draft_drops_synthetic_thread_id(monkeypatch):
    provider = _provider()
    calls, payloads = [], []
    monkeypatch.setattr(real_requests, "request", _capture_payload(calls, payloads))

    draft = _draft()
    draft.thread_id = "sim-thread-1"
    provider.create_draft(draft)

    assert len(calls) == 1
    assert "threadId" not in payloads[0].get("message", {}), payloads[0]