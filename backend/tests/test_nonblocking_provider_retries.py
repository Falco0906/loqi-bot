"""Regression coverage for retry backoff at provider integration boundaries."""

import asyncio

import pytest


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected HTTP status {self.status_code}")

    def json(self):
        return self._payload


class _AsyncClient:
    def __init__(self, responses, **_kwargs):
        self._responses = iter(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, *_args, **_kwargs):
        return next(self._responses)


@pytest.mark.parametrize(
    ("module_name", "provider_name", "payload", "success_payload"),
    [
        (
            "services.reply_generation.providers.openai_provider",
            "OpenAIProvider",
            {"input": "test"},
            {
                "model": "gpt-test",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
            },
        ),
        (
            "services.reply_generation.providers.anthropic_provider",
            "AnthropicProvider",
            {"messages": []},
            {"model": "claude-test", "content": [{"type": "text", "text": "ok"}]},
        ),
    ],
)
def test_reply_provider_retries_with_async_sleep(
    monkeypatch, module_name, provider_name, payload, success_payload
):
    module = __import__(module_name, fromlist=[provider_name])
    pauses = []

    async def fake_sleep(delay):
        pauses.append(delay)

    monkeypatch.setattr(module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: _AsyncClient([_Response(429, {}), _Response(200, success_payload)], **kwargs),
    )

    result = asyncio.run(getattr(module, provider_name)()._request_data(payload))

    assert result == success_payload
    assert pauses == [1.0]


def test_lead_provider_retry_offloads_sync_provider_and_uses_async_sleep(monkeypatch):
    from services.providers import base_provider

    pauses = []

    class FlakyProvider:
        def __init__(self):
            self.calls = 0

        def search_leads(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"ok": False, "error": "temporary timeout"}
            return {"ok": True, "leads": []}

    async def fake_sleep(delay):
        pauses.append(delay)

    monkeypatch.setattr(base_provider.asyncio, "sleep", fake_sleep)
    provider = FlakyProvider()

    result = asyncio.run(
        base_provider.search_leads_with_retry_async(
            provider, icp={}, search_expansion={}, max_retries=1
        )
    )

    assert result["ok"] is True
    assert provider.calls == 2
    assert len(pauses) == 1
