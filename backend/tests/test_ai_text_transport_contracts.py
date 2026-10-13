"""Characterization tests for the shared OpenAI text-transport contracts."""
from __future__ import annotations

import pytest

from services.intelligence import ai


_REAL_SEND_OPENAI_REQUEST = ai._send_openai_request
_REAL_TRY_SEND_OPENAI_REQUEST = ai.try_send_openai_request


class _Response:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"output": [{"content": [{"text": "  generated text  "}]}]}


def test_raising_text_transport_keeps_legacy_default_timeout(monkeypatch):
    captured = {}
    monkeypatch.setattr(ai, "_send_openai_request", _REAL_SEND_OPENAI_REQUEST)
    monkeypatch.setattr(ai, "OPENAI_API_KEY", "test-key")

    def post(*_args, **kwargs):
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr(ai.requests, "post", post)

    assert ai._send_openai_request("system", "user") == "generated text"
    assert captured["timeout"] == (5, 30)
    assert "text" not in captured["json"]


def test_profile_structured_format_is_sent_without_changing_other_callers(monkeypatch):
    captured = {}
    monkeypatch.setattr(ai, "OPENAI_API_KEY", "test-key")

    def post(*_args, **kwargs):
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr(ai.requests, "post", post)
    response_format = {"type": "json_schema", "name": "test_profile", "strict": True,
                       "schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}}
    assert ai._request_openai_text("system", "user", timeout=30, response_format=response_format) == "generated text"
    assert captured["json"]["text"]["format"] == response_format
    assert captured["timeout"] == (5, 30)


def test_try_text_transport_preserves_none_failure_contract_and_timeout(monkeypatch):
    captured = {}
    monkeypatch.setattr(ai, "try_send_openai_request", _REAL_TRY_SEND_OPENAI_REQUEST)
    monkeypatch.setattr(ai, "OPENAI_API_KEY", "test-key")

    def post(*_args, **kwargs):
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr(ai.requests, "post", post)

    assert ai.try_send_openai_request("system", "user", timeout=15) == "generated text"
    assert captured["timeout"] == (5, 15)


def test_try_text_transport_returns_none_for_raising_transport_failure(monkeypatch):
    monkeypatch.setattr(ai, "_send_openai_request", _REAL_SEND_OPENAI_REQUEST)
    monkeypatch.setattr(ai, "try_send_openai_request", _REAL_TRY_SEND_OPENAI_REQUEST)
    monkeypatch.setattr(ai, "OPENAI_API_KEY", "")

    with pytest.raises(ai.OpenAIError):
        ai._send_openai_request("system", "user")

    assert ai.try_send_openai_request("system", "user", timeout=20) is None
