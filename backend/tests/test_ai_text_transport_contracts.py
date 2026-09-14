"""Characterization tests for the shared OpenAI text-transport contracts."""
from __future__ import annotations

import importlib

import pytest

from services import ai


class _Response:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"output": [{"content": [{"text": "  generated text  "}]}]}


def test_raising_text_transport_keeps_legacy_default_timeout(monkeypatch):
    captured = {}
    importlib.reload(ai)
    monkeypatch.setattr(ai, "OPENAI_API_KEY", "test-key")

    def post(*_args, **kwargs):
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr(ai.requests, "post", post)

    assert ai._send_openai_request("system", "user") == "generated text"
    assert captured["timeout"] == 30


def test_try_text_transport_preserves_none_failure_contract_and_timeout(monkeypatch):
    captured = {}
    importlib.reload(ai)
    monkeypatch.setattr(ai, "OPENAI_API_KEY", "test-key")

    def post(*_args, **kwargs):
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr(ai.requests, "post", post)

    assert ai.try_send_openai_request("system", "user", timeout=15) == "generated text"
    assert captured["timeout"] == 15


def test_try_text_transport_returns_none_for_raising_transport_failure(monkeypatch):
    importlib.reload(ai)
    monkeypatch.setattr(ai, "OPENAI_API_KEY", "")

    with pytest.raises(ai.OpenAIError):
        ai._send_openai_request("system", "user")

    assert ai.try_send_openai_request("system", "user", timeout=20) is None
