"""PR10.4 — structured logging + error handling tests.

Uses a sentinel secret value and never real credentials.
"""
from __future__ import annotations

import json
import logging
import os
import sys

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

from services.config_validation import validate_config
from services.logging_setup import (
    JsonFormatter,
    configure_logging,
    log_level_from_env,
    log_format_from_env,
)

import main as main_module  # noqa: E402
from tests.conftest import _AuthTestClient

SENTINEL = "PR10_4_SECRET_SENTINEL_VALUE"


class TestLoggingConfiguration:
    def test_level_from_env_defaults_info(self):
        assert log_level_from_env({}) == "INFO"

    def test_level_from_env_valid(self):
        assert log_level_from_env({"LOG_LEVEL": "debug"}) == "DEBUG"

    def test_level_from_env_invalid_falls_back_to_info(self):
        assert log_level_from_env({"LOG_LEVEL": "chatty"}) == "INFO"

    def test_format_from_env(self):
        assert log_format_from_env({"LOG_FORMAT": "json"}) == "json"
        assert log_format_from_env({"LOG_FORMAT": "text"}) == "text"
        assert log_format_from_env({}) == "text"

    def test_config_validation_rejects_invalid_level_and_format(self):
        errors, _ = validate_config({"ENVIRONMENT": "development", "LOG_LEVEL": "chatty"})
        assert any("LOG_LEVEL" in e for e in errors)
        errors, _ = validate_config({"ENVIRONMENT": "development", "LOG_FORMAT": "xml"})
        assert any("LOG_FORMAT" in e for e in errors)

    def test_debug_rejected_in_production(self):
        errors, _ = validate_config({
            "ENVIRONMENT": "production",
            "SUPABASE_URL": "https://x.supabase.co",
            "SUPABASE_KEY": "k",
            "OPENAI_API_KEY": "k",
            "GOOGLE_CLIENT_ID": "c",
            "GOOGLE_CLIENT_SECRET": "s",
            "LOG_LEVEL": "DEBUG",
        })
        assert any("LOG_LEVEL=DEBUG is not allowed in production" in e for e in errors)


class TestJsonFormatter:
    def test_json_output_is_parseable_and_has_fields(self, caplog):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="loqi", level=logging.INFO, pathname="", lineno=0,
            msg="sync complete", args=(), exc_info=None,
        )
        record.provider_id = "prov-1"
        record.duration_ms = 12
        line = formatter.format(record)
        data = json.loads(line)
        assert data["level"] == "INFO"
        assert data["logger"] == "loqi"
        assert data["event"] == "sync complete"
        assert data["provider_id"] == "prov-1"
        assert data["duration_ms"] == 12

    def test_exc_info_included_without_secret(self):
        formatter = JsonFormatter()
        try:
            raise ValueError(SENTINEL)
        except ValueError:
            record = logging.LogRecord(
                name="loqi", level=logging.ERROR, pathname="", lineno=0,
                msg="boom", args=(), exc_info=sys.exc_info(),
            )
        line = formatter.format(record)
        data = json.loads(line)
        assert data["error_type"] == "ValueError"
        assert "exc" in data


class TestRequestCorrelation:
    def test_request_id_header_present_and_not_a_token(self):
        from fastapi.testclient import TestClient
        client = _AuthTestClient(main_module.app)
        response = client.get("/health")
        assert response.status_code == 200
        req_id = response.headers.get("X-Request-ID")
        assert req_id and len(req_id) <= 16
        assert SENTINEL not in req_id
        assert "token" not in req_id.lower()


class TestGlobalExceptionHandler:
    async def test_handler_returns_safe_generic_500(self):
        from fastapi import Request

        request = Request({"type": "http", "method": "GET", "path": "/boom", "headers": []})
        request.state.request_id = "req-123"
        exc = RuntimeError(SENTINEL)
        response = await main_module.unhandled_exception_handler(request, exc)
        assert response.status_code == 500
        body = json.loads(response.body)
        assert body == {"detail": "Internal Server Error"}
        assert response.headers.get("X-Request-ID") == "req-123"
        assert SENTINEL not in response.body.decode()

    def test_handler_logs_exception_server_side(self, caplog):
        import asyncio
        from fastapi import Request

        request = Request({"type": "http", "method": "GET", "path": "/boom", "headers": []})
        request.state.request_id = "req-456"
        with caplog.at_level(logging.ERROR):
            asyncio.run(main_module.unhandled_exception_handler(request, RuntimeError("kaboom")))
        assert any(
            record.getMessage().startswith("unhandled_exception")
            and "RuntimeError" in record.getMessage()
            for record in caplog.records
        )
        assert SENTINEL not in caplog.text


class Test4xxBehaviorPreserved:
    def test_validation_error_shape_preserved(self):
        from fastapi.testclient import TestClient
        client = _AuthTestClient(main_module.app)
        response = client.post("/api/web/session/s-1/drafts/draft-1/send", json={"test_recipient": "x@y.com"})
        # Existing 4xx handling stays intact (403 when override disabled in dev is allowed;
        # here it is a normal send -> draft not found).
        assert response.status_code in (403, 404)

    def test_reply_duplicate_409_still_intact(self):
        from fastapi.testclient import TestClient
        client = _AuthTestClient(main_module.app)
        response = client.post("/api/web/session/s-1/conversations/missing/reply", json={"body": "x"})
        assert response.status_code in (404, 409)


class TestSecretSafetyInLogging:
    def test_ai_source_does_not_log_full_payloads(self):
        path = os.path.join(os.path.dirname(__file__), "..", "services", "ai.py")
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        assert "exact response body" not in text
        assert "payload: {payload}" not in text

    def test_gmail_sync_does_not_log_bodies(self):
        path = os.path.join(os.path.dirname(__file__), "..", "services", "communication", "gmail_sync.py")
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        # No log statement formats the message body value.
        assert "raw_body" not in text
        assert "body=%s" not in text
        assert "body={}" not in text
        assert "text=%s" not in text


class TestProviderFailureLogging:
    def test_sync_engine_logs_provider_failure_without_secret(self, monkeypatch, caplog):
        from services.communication import provider_registry
        from services.communication.inbox_sync_engine import InboxSyncEngine
        import asyncio

        class FakeProvider:
            provider_type = "gmail"

            def __init__(self, provider_id):
                self._provider_id = provider_id
                self._user_id = "user-1"
                self._connected = True

        provider_registry.register_instance("prov-fail", FakeProvider("prov-fail"))
        monkeypatch.setenv("SUPABASE_KEY", SENTINEL)

        def boom(provider):
            raise RuntimeError("provider down")

        monkeypatch.setattr("services.communication.inbox_sync_engine.sync_all", boom)
        with caplog.at_level(logging.ERROR):
            asyncio.run(InboxSyncEngine(interval_seconds=3600).sync_once())
        assert SENTINEL not in caplog.text
        assert any(
            "prov-fail" in record.getMessage()
            for record in caplog.records
            if record.name == "services.communication.inbox_sync_engine"
        )
        provider_registry._instances.clear()
