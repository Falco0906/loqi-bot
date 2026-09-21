"""Characterization tests for the application's request logging boundary."""

from fastapi.testclient import TestClient

import main


def _client() -> TestClient:
    """Exercise the already-composed app without starting its global workers."""
    return TestClient(main.app)


def test_main_logging_adds_correlation_and_api_headers_to_success_response():
    response = _client().get("/health")

    assert response.status_code == 200
    assert len(response.headers["X-Request-ID"]) == 8
    assert response.headers["X-API-Version"] == "1"


def test_main_logging_adds_correlation_and_api_headers_to_not_found_response():
    response = _client().get("/not-a-real-route")

    assert response.status_code == 404
    assert len(response.headers["X-Request-ID"]) == 8
    assert response.headers["X-API-Version"] == "1"


def test_main_logging_adds_correlation_and_api_headers_to_session_auth_rejection():
    response = _client().get("/api/web/session/no-token/messages")

    assert response.status_code == 401
    assert len(response.headers["X-Request-ID"]) == 8
    assert response.headers["X-API-Version"] == "1"
