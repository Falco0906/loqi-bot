"""Tests for M2.2.1 — Production Readiness infrastructure."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.operations import (
    RequestLoggingMiddleware,
    operations_router,
    set_startup_time,
)
from services.operations.diagnostics import (
    _get_version,
    get_build_metadata,
    get_repository_provider,
    startup_diagnostics,
    validate_config,
)
from services.persistence.config import (
    RepositoryProvider,
    reset_repository_provider,
    set_repository_provider,
)
from services.persistence.database import (
    SupabaseConnectionManager,
    reset_connection_manager,
    set_connection_manager,
)


@pytest.fixture
def test_app():
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)
    app.include_router(operations_router)
    set_startup_time()
    return app


@pytest.fixture
def client(test_app):
    with TestClient(test_app) as c:
        yield c


# ═══════════════════════════════════════════════════════════════════════════
# 1. Health endpoint
# ═══════════════════════════════════════════════════════════════════════════

class TestHealthEndpoint:

    def test_health_returns_healthy(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "healthy"}

    def test_health_is_fast(self, client):
        import time
        start = time.monotonic()
        for _ in range(100):
            resp = client.get("/health")
            assert resp.status_code == 200
        elapsed = time.monotonic() - start
        assert elapsed < 5.0


# ═══════════════════════════════════════════════════════════════════════════
# 2. Readiness endpoint
# ═══════════════════════════════════════════════════════════════════════════

class TestReadinessEndpoint:

    def test_ready_with_no_db(self, client):
        reset_connection_manager()
        resp = client.get("/ready")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "unready"
        assert len(data["failures"]) > 0
        assert any("database" in f for f in data["failures"])

    def test_ready_with_mock_db(self, client):
        cm = SupabaseConnectionManager(url="http://test", key="test-key")
        mock_client = MagicMock()
        cm._client = mock_client
        set_connection_manager(cm)
        mock_client.table.return_value = mock_client
        mock_client.select.return_value = mock_client
        mock_client.limit.return_value = mock_client
        mock_client.execute.return_value = MagicMock(data=[])
        resp = client.get("/ready")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ready"}
        reset_connection_manager()

    def test_ready_with_db_failure(self, client):
        cm = SupabaseConnectionManager(url="http://test", key="test-key")
        mock_client = MagicMock()
        cm._client = mock_client
        set_connection_manager(cm)
        mock_client.table.side_effect = Exception("connection refused")
        resp = client.get("/ready")
        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "unready"
        assert any("connection refused" in f for f in data["failures"])
        reset_connection_manager()


# ═══════════════════════════════════════════════════════════════════════════
# 3. Version endpoint
# ═══════════════════════════════════════════════════════════════════════════

class TestVersionEndpoint:

    def test_version_structure(self, client):
        resp = client.get("/version")
        assert resp.status_code == 200
        data = resp.json()
        assert data["application"] == "Loqi"
        assert "version" in data
        assert "commit" in data
        assert "build_timestamp" in data
        assert "environment" in data
        assert "repository_provider" in data

    def test_version_provider_reflects_config(self, client):
        reset_repository_provider()
        set_repository_provider(RepositoryProvider.SUPABASE)
        resp = client.get("/version")
        assert resp.json()["repository_provider"] == "supabase"
        reset_repository_provider()
        resp = client.get("/version")
        assert resp.json()["repository_provider"] == "in_memory"

    def test_version_semver_format(self, client):
        resp = client.get("/version")
        version = resp.json()["version"]
        parts = version.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Config validation
# ═══════════════════════════════════════════════════════════════════════════

class TestConfigValidation:

    def test_validate_config_in_memory(self):
        reset_repository_provider()
        errors = validate_config()
        assert isinstance(errors, list)

    def test_validate_config_returns_list(self):
        reset_repository_provider()
        errors = validate_config()
        assert isinstance(errors, list)

    def test_validate_config_keys_with_env_unset(self, monkeypatch):
        reset_repository_provider()
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        errors = validate_config()
        keys = {e["variable"] for e in errors}
        assert "OPENAI_API_KEY" in keys

    def test_validate_config_clears_when_set(self, monkeypatch):
        reset_repository_provider()
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        errors = validate_config()
        openai_errors = [e for e in errors if e["variable"] == "OPENAI_API_KEY"]
        assert len(openai_errors) == 0

    def test_validate_config_supabase_env(self, monkeypatch):
        reset_repository_provider()
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        set_repository_provider(RepositoryProvider.SUPABASE)
        errors = validate_config()
        keys = {e["variable"] for e in errors}
        assert "SUPABASE_URL" in keys
        assert "SUPABASE_KEY" in keys
        reset_repository_provider()


# ═══════════════════════════════════════════════════════════════════════════
# 5. Build metadata
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildMetadata:

    def test_metadata_has_commit(self):
        meta = get_build_metadata()
        assert "commit" in meta
        assert "build_timestamp" in meta

    def test_metadata_immutable_copy(self):
        meta = get_build_metadata()
        meta["commit"] = "changed"
        assert get_build_metadata()["commit"] != "changed"


# ═══════════════════════════════════════════════════════════════════════════
# 6. Request logging middleware
# ═══════════════════════════════════════════════════════════════════════════

class TestRequestLoggingMiddleware:

    def test_response_has_request_id(self, client):
        resp = client.get("/health")
        assert "X-Request-ID" in resp.headers
        assert len(resp.headers["X-Request-ID"]) == 8

    def test_unique_request_ids(self, client):
        ids = set()
        for _ in range(10):
            resp = client.get("/health")
            ids.add(resp.headers["X-Request-ID"])
        assert len(ids) == 10

    def test_404_has_request_id(self, client):
        resp = client.get("/nonexistent")
        assert resp.status_code == 404
        assert "X-Request-ID" in resp.headers


# ═══════════════════════════════════════════════════════════════════════════
# 7. Error response format
# ═══════════════════════════════════════════════════════════════════════════

class TestErrorResponse:

    def test_unhandled_error_returns_structured(self, test_app, client):
        @test_app.get("/crash")
        async def crash():
            raise RuntimeError("something broke")

        resp = client.get("/crash")
        assert resp.status_code == 500
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == "INTERNAL_ERROR"
        assert "request_id" in data["error"]
        assert "stack trace" not in str(data)


# ═══════════════════════════════════════════════════════════════════════════
# 8. Startup diagnostics
# ═══════════════════════════════════════════════════════════════════════════

class TestStartupDiagnostics:

    def test_diagnostics_runs(self, test_app, caplog):
        import logging
        caplog.set_level(logging.INFO, logger="loqi")
        set_startup_time()
        startup_diagnostics(test_app)
        assert "Loqi Backend Startup Diagnostics" in caplog.text

    def test_diagnostics_reports_routes(self, test_app, caplog):
        import logging
        caplog.set_level(logging.INFO, logger="loqi")
        set_startup_time()
        startup_diagnostics(test_app)
        assert "Routes:" in caplog.text


# ═══════════════════════════════════════════════════════════════════════════
# 9. Helper functions
# ═══════════════════════════════════════════════════════════════════════════

class TestHelpers:

    def test_get_version(self):
        version = _get_version()
        assert isinstance(version, str)
        assert len(version) > 0

    def test_get_repository_provider(self):
        reset_repository_provider()
        provider = get_repository_provider()
        assert provider == RepositoryProvider.IN_MEMORY
