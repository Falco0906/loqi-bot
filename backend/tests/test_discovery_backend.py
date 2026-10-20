"""Offline HTTP validation of the isolated backend; does not start a server."""
import time

import pytest
from fastapi.testclient import TestClient

from tests.discovery_backend.bootstrap import create_app, prepare_runtime, MARKER
from tests.discovery_backend.store import A, B, FOREIGN, SESSION


@pytest.fixture
def isolated(monkeypatch, request):
    monkeypatch.delenv("REDIS_URL", raising=False)
    app = create_app(profile=getattr(request, "param", "small"))
    with TestClient(app) as client:
        client.headers["authorization"] = f"Bearer {SESSION}"
        client.headers["x-workspace-id"] = A
        client.headers["x-loqi-test-run-id"] = app.state.synthetic.run_id
        yield client, app


def completed(client, identity):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        reply = client.get(f"/api/discoveries/{identity}")
        assert reply.status_code == 200, reply.text
        row = reply.json()["discovery"]
        if row["status"] in {"completed", "failed"}:
            return row
        time.sleep(.01)
    pytest.fail("Synthetic worker did not reach a terminal state within five seconds")


def search(client, filters=None):
    reply = client.post("/api/discoveries", json={"query": "operations leaders at e commerce companies",
                                               "initiation": "manual", "filters": filters or {}})
    assert reply.status_code == 200, reply.text
    return completed(client, reply.json()["discovery_id"])


def test_real_routes_worker_persistence_and_pagination(isolated):
    client, app = isolated
    assert client.get("/__loqi_test/identity").json()["marker"] == MARKER
    row = search(client)
    assert row["status"] == "completed"
    assert row["summary"]["lead_count"] == 56
    counts = row["summary"]["candidate_outcomes"]
    assert counts["retrieved_count"] == 58
    assert counts["exclusions"]["role"] == counts["exclusions"]["industry"] == 1
    assert counts["retrieved_count"] == counts["matched_count"] + sum(counts["exclusions"].values())
    result = []
    for page in (1, 2):
        response = client.get("/api/web/session/_/leads", params={"q": row["query"], "discovery_id": row["id"], "page": page})
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 56
        result.extend(response.json()["leads"])
    assert len({lead["id"] for lead in result}) == len(result) == 56
    assert {lead["title"] for lead in result} == {"Head of Operations", "Operations Manager", "COO"}
    # Persisted links/staging/jobs are written by real application code.
    assert len(app.state.synthetic.tables["discovery_leads"]) == 56
    assert len(app.state.synthetic.tables["search_results"]) == 56
    assert app.state.synthetic.tables["jobs"][0]["status"] == "completed"
    assert app.state.blocked == []


def test_explicit_filters_and_canonical_membership_scope(isolated):
    client, _ = isolated
    row = search(client, {"location": "London"})
    assert row["summary"]["lead_count"] == 54
    assert row["summary"]["candidate_outcomes"]["exclusions"]["explicit_filter"] == 2
    reply = client.get("/api/web/session/_/leads", headers={"x-workspace-id": B})
    assert reply.status_code == 200 and reply.json()["total"] == 1
    assert client.get("/api/web/session/_/leads", headers={"x-workspace-id": FOREIGN}).status_code == 404
    assert client.post("/api/discoveries", json={"query": "COO", "initiation": "automated"}).status_code == 403


@pytest.mark.parametrize("mode", ["fail-staging", "truncate-staging"])
def test_incomplete_search_is_not_completed(isolated, mode):
    client, app = isolated
    assert client.post("/__loqi_test/fault", json={"mode": mode}).status_code == 200
    row = search(client)
    assert row["status"] == "failed"
    assert row["summary"]["error_kind"] in {"execution", "persistence"}
    assert app.state.synthetic.tables["jobs"][0]["status"] == "failed"
    assert app.state.synthetic.tables["jobs"][0]["result_ready"] is False


def test_target_auth_and_outbound_guards(isolated):
    import socket
    client, app = isolated
    assert client.get("/api/web/session/_/leads", headers={"authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/__loqi_test/identity", headers={"host": "app.tryloqi.com"}).status_code == 400
    assert client.post("/api/v1/onboarding/workspace/create", json={}).status_code == 403
    assert client.get("/api/web/session/_/leads", headers={"x-loqi-test-run-id": "old-run"}).status_code == 412
    with pytest.raises(RuntimeError, match="Outbound connections"):
        socket.create_connection(("production.invalid", 443))
    assert app.state.blocked == ["outbound connection"]


@pytest.mark.parametrize("origin", ["http://127.0.0.1:3000", "http://localhost:3000"])
def test_cors_allows_run_header_only_for_approved_origins(isolated, origin):
    client, app = isolated
    headers = {"origin": origin, "access-control-request-method": "POST",
               "access-control-request-headers": "authorization,content-type,x-workspace-id,x-loqi-test-run-id"}
    response = client.options("/api/discoveries", headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == origin
    allowed = {value.strip().lower() for value in response.headers["access-control-allow-headers"].split(",")}
    assert allowed == {"accept", "accept-language", "content-language", "content-type",
                       "authorization", "x-workspace-id", "x-loqi-test-run-id"}
    # CORS permission to send the header does not authorize its value.
    for approval in ("", "unapproved-run"):
        rejected = client.get("/api/web/session/_/leads", headers={
            "origin": origin, "x-loqi-test-run-id": approval,
        })
        assert rejected.status_code == 412
        assert rejected.headers["access-control-allow-origin"] == origin
    invalid_header = client.options("/api/discoveries", headers={
        **headers, "access-control-request-headers": "x-unapproved-header",
    })
    assert invalid_header.status_code == 400
    for foreign_origin in ("http://127.0.0.1:3001", "https://unapproved.invalid"):
        rejected = client.options("/api/discoveries", headers={**headers, "origin": foreign_origin})
        assert rejected.status_code == 400
        assert "access-control-allow-origin" not in rejected.headers
    assert app.state.synthetic.tables["jobs"] == []
    assert app.state.synthetic.tables["discoveries"] == []
    assert app.state.blocked == []


def test_opt_in_and_inherited_configuration_fail_before_bootstrap(monkeypatch):
    monkeypatch.delenv("LOQI_ISOLATED_DISCOVERY_ENABLED", raising=False)
    with pytest.raises(RuntimeError, match="opt-in"):
        prepare_runtime()
    monkeypatch.setenv("LOQI_ISOLATED_DISCOVERY_ENABLED", "1")
    monkeypatch.setenv("SUPABASE_URL", "must-not-be-used")
    with pytest.raises(RuntimeError, match="inherited service configuration"):
        prepare_runtime()


def test_sendmsg_allowed_but_outbound_audit_events_rejected_before_application_imports():
    """Exercise the installed hook without creating a socket or sending a packet."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    code = """
import sys
from tests.discovery_backend.bootstrap import prepare_runtime
prepare_runtime()
assert 'fastapi' not in sys.modules
assert 'services.discovery.api' not in sys.modules
# Emit audit events only: no socket, native send or child process is invoked.
# Buffered TCP response writes must not be rejected merely for using sendmsg.
sys.audit('socket.sendmsg', object(), None)
for event in ('socket.connect', 'socket.sendto', 'subprocess.Popen', 'os.system', 'os.posix_spawn'):
    try:
        sys.audit(event, object(), ('192.0.2.1', 9))
    except RuntimeError as error:
        assert str(error) == 'Outbound connections and child processes are forbidden in the isolated backend'
    else:
        raise AssertionError(event + ' must be rejected before native dispatch')
assert 'fastapi' not in sys.modules
assert 'services.discovery.api' not in sys.modules
print('response-sendmsg-allowed-outbound-events-blocked-before-startup')
"""
    result = subprocess.run([sys.executable, "-B", "-c", code], cwd=Path(__file__).resolve().parents[1],
        env={"PATH": os.defpath, "LANG": "C", "LOQI_ISOLATED_DISCOVERY_ENABLED": "1"},
        capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "response-sendmsg-allowed-outbound-events-blocked-before-startup" in result.stdout


def test_clean_bootstrap_audit_guards_before_lifespan():
    """Fresh process, no listener: validate the exact pre-import startup boundary."""
    import os
    import subprocess
    import sys
    from pathlib import Path
    code = """
from tests.discovery_backend.bootstrap import prepare_runtime, create_app
prepare_runtime()
import socket
try:
    socket.getaddrinfo('production.invalid', 443)
except RuntimeError:
    pass
else:
    raise AssertionError('External DNS must be rejected')
from fastapi.testclient import TestClient
from tests.discovery_backend.store import A, SESSION
app = create_app()
with TestClient(app) as client:
    client.headers.update({'authorization': 'Bearer ' + SESSION, 'x-workspace-id': A,
                           'x-loqi-test-run-id': app.state.synthetic.run_id})
    response = client.post('/api/discoveries', json={'query': 'operations leaders', 'initiation': 'manual'})
    assert response.status_code == 200, response.text
print('clean-bootstrap-ok')
"""
    result = subprocess.run([sys.executable, "-B", "-c", code], cwd=Path(__file__).resolve().parents[1],
        env={"PATH": os.defpath, "LANG": "C", "LOQI_ISOLATED_DISCOVERY_ENABLED": "1"},
        capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "clean-bootstrap-ok" in result.stdout
