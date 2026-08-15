"""PR10 — Error handling & observability regression tests.

Confirms the error-handling architecture:

- unexpected exceptions -> safe generic 500 (no stack trace / internal detail
  returned to clients)
- HTTPException 5xx with raw detail -> generic 500 to the client; the real
  detail is logged server-side
- HTTPException 4xx detail is preserved (client-facing validation messages)
- validation errors keep the 422 shape
- Authorization/session tokens and sensitive headers never reach logs
- request/correlation id is present in logs and responses
- background job failures produce a FAILED state

Deterministic sentinels only; no real credentials/tokens.
"""
import asyncio
import logging
import uuid

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import main as main_module
from main import http_exception_handler, unhandled_exception_handler

SENTINEL = "PR10_ERR_SENTINEL_DO_NOT_LEAK"
SENTINEL_TOKEN = "PR10_ERR_BEARER_SENTINEL_TOKEN"


def _make_app():
    """A minimal app with the real exception handlers + request-id middleware."""
    app = FastAPI()
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    from starlette.middleware.base import BaseHTTPMiddleware

    class _ReqIdMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            rid = str(uuid.uuid4())[:8]
            request.state.request_id = rid
            main_module.request_id_var.set(rid)
            response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            return response

    app.add_middleware(_ReqIdMiddleware)

    @app.get("/boom")
    async def boom():
        raise RuntimeError(f"boom-internal-{SENTINEL}")

    @app.get("/http500")
    async def http500():
        raise HTTPException(status_code=500, detail=f"raw-500-{SENTINEL}")

    @app.get("/http400")
    async def http400():
        raise HTTPException(status_code=400, detail="bad-input-value")

    @app.get("/validate")
    async def validate(count: int):
        return {"count": count}

    return app


class TestBackendErrorResponses:
    def test_unexpected_exception_returns_safe_500(self):
        with TestClient(_make_app(), raise_server_exceptions=False) as client:
            resp = client.get("/boom")
        assert resp.status_code == 500
        assert resp.json() == {"detail": "Internal Server Error"}
        assert SENTINEL not in resp.text
        assert "Traceback" not in resp.text

    def test_http500_raw_detail_not_exposed_to_client(self, caplog):
        with caplog.at_level(logging.INFO):
            with TestClient(_make_app(), raise_server_exceptions=False) as client:
                resp = client.get("/http500")
        assert resp.status_code == 500
        assert resp.json() == {"detail": "Internal Server Error"}
        assert SENTINEL not in resp.text
        # The real detail is logged server-side for debugging.
        assert f"raw-500-{SENTINEL}" in caplog.text

    def test_http400_detail_preserved(self):
        with TestClient(_make_app(), raise_server_exceptions=False) as client:
            resp = client.get("/http400")
        assert resp.status_code == 400
        assert resp.json() == {"detail": "bad-input-value"}

    def test_validation_error_shape_preserved(self):
        with TestClient(_make_app(), raise_server_exceptions=False) as client:
            resp = client.get("/validate")
        assert resp.status_code == 422
        assert "detail" in resp.json()

    def test_404_preserved(self):
        with TestClient(_make_app(), raise_server_exceptions=False) as client:
            resp = client.get("/does-not-exist")
        assert resp.status_code == 404

    def test_request_id_in_response_and_logs(self, caplog):
        with caplog.at_level(logging.INFO):
            with TestClient(_make_app(), raise_server_exceptions=False) as client:
                resp = client.get("/http500")
        rid = resp.headers.get("X-Request-ID")
        assert rid
        assert f"http_5xx request_id={rid}" in caplog.text


class TestNoSensitiveLeakage:
    def test_authorization_header_and_token_never_logged(self, caplog):
        with caplog.at_level(logging.INFO):
            with TestClient(_make_app(), raise_server_exceptions=False) as client:
                resp = client.get(
                    "/http500",
                    headers={"Authorization": f"Bearer {SENTINEL_TOKEN}"},
                )
        assert resp.status_code == 500
        assert SENTINEL_TOKEN not in caplog.text
        assert f"Bearer {SENTINEL_TOKEN}" not in caplog.text
        assert SENTINEL not in resp.text


class TestBackgroundJobFailure:
    def test_job_marks_failed_on_exception(self):
        from services.job_engine import runner as runner_mod
        from services.job_engine.models import Job, JobStatus

        class _FakeStorage:
            def __init__(self):
                self.jobs = {}

            def create_job(self, job):
                self.jobs[job.id] = job
                return job

            def get_job(self, job_id):
                return self.jobs.get(job_id)

            def update_job(self, job_id, **fields):
                job = self.jobs.get(job_id)
                if job:
                    for k, v in fields.items():
                        setattr(job, k, v)
                return job

            def store_search_results(self, job_id, leads):
                return True

            def get_search_results(self, job_id):
                return []

            def list_active_jobs(self, user_id):
                return [j for j in self.jobs.values() if j.user_id == user_id]

            def list_recent_jobs(self, user_id, limit=20):
                return [j for j in self.jobs.values() if j.user_id == user_id][:limit]

        def _boom(job, on_progress):
            raise RuntimeError(f"job-failure-{SENTINEL}")

        storage = _FakeStorage()
        runner = runner_mod.BackgroundRunner(storage=storage)
        job = Job(user_id="u-1", type="search", query="q", stage="search", progress=0)
        storage.create_job(job)
        asyncio.run(runner._run_wrapper(job, _boom, on_update=None, on_complete=None))
        assert job.status == JobStatus.FAILED
        assert "job-failure-" in (job.error_message or "")
        assert job.id not in runner._tasks
