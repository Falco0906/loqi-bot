"""PR10.6 — health / readiness / graceful lifecycle tests."""
from __future__ import annotations

import os
import sys

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

from services import lifecycle
import main as main_module  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_lifecycle():
    lifecycle.set_starting()
    yield
    lifecycle.set_starting()


class TestLiveness:
    def test_health_returns_200_and_is_dependency_free(self, monkeypatch):
        from fastapi.testclient import TestClient

        calls = []
        import services.supabase as supabase_module
        monkeypatch.setattr(supabase_module, "get_supabase_client", lambda: calls.append("client") or object())
        client = TestClient(main_module.app)
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        # Liveness must not touch external dependencies.
        assert calls == []

    def test_health_does_not_expose_secrets(self, monkeypatch):
        from fastapi.testclient import TestClient
        monkeypatch.setenv("SUPABASE_KEY", "PR10_6_SENTINEL")
        client = TestClient(main_module.app)
        assert "PR10_6_SENTINEL" not in client.get("/health").text


class TestReadiness:
    def test_not_ready_before_startup(self):
        from fastapi.testclient import TestClient
        lifecycle.set_starting()
        client = TestClient(main_module.app)
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "starting"}

    def test_ready_after_startup(self):
        from fastapi.testclient import TestClient
        lifecycle.set_ready()
        client = TestClient(main_module.app)
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready"}

    def test_not_ready_during_shutdown(self):
        from fastapi.testclient import TestClient
        lifecycle.set_shutting_down()
        client = TestClient(main_module.app)
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "shutting_down"}

    def test_startup_failure_prevents_ready(self):
        from fastapi.testclient import TestClient
        lifecycle.set_failed()
        client = TestClient(main_module.app)
        assert client.get("/ready").status_code == 503

    def test_readiness_does_not_expose_secrets(self, monkeypatch):
        from fastapi.testclient import TestClient
        monkeypatch.setenv("SUPABASE_KEY", "PR10_6_SENTINEL")
        lifecycle.set_ready()
        client = TestClient(main_module.app)
        assert "PR10_6_SENTINEL" not in client.get("/ready").text


class TestLifecycleState:
    def test_state_transitions(self):
        assert lifecycle.get_state() == "starting"
        lifecycle.set_ready()
        assert lifecycle.is_ready() is True
        lifecycle.set_shutting_down()
        assert lifecycle.is_shutting_down() is True
        assert lifecycle.is_ready() is False
        # shutdown cannot transition back to ready via lifecycle API accidentally
        lifecycle.set_starting()
        assert lifecycle.get_state() == "starting"

    def test_startup_not_performed_twice(self):
        # set_ready is idempotent and does not spawn workers.
        lifecycle.set_ready()
        lifecycle.set_ready()
        assert lifecycle.get_state() == "ready"


class TestHealthReadinessBypassRateLimit:
    def test_health_and_ready_bypass_rate_limiter(self):
        from services.rate_limit import classify_rate_limit
        assert classify_rate_limit("/health") == "health"
        assert classify_rate_limit("/ready") == "health"


class TestGracefulShutdown:
    def test_cancel_and_wait_bounded_timeout(self):
        import asyncio

        async def never_stops():
            await asyncio.Event().wait()

        async def run():
            task = asyncio.create_task(never_stops())
            await asyncio.sleep(0)
            await main_module._cancel_and_wait([task], timeout=0.1)
            return task.done()

        assert asyncio.run(run()) is True

    def test_cancel_and_wait_ignores_finished_tasks(self):
        import asyncio

        async def run():
            done = asyncio.create_task(asyncio.sleep(0))
            await done
            await main_module._cancel_and_wait([done], timeout=0.1)
            return done.done()

        assert asyncio.run(run()) is True
