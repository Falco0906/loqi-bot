"""Real session-expiry enforcement with isolated, in-process HTTP only."""
from datetime import datetime, timedelta, timezone

import pytest

from services.identity import api as identity_api, dependencies
from services.identity.models import Session
from tests.conftest import REAL_RESOLVE_WEB_SESSION
from tests.discovery_backend.store import SESSION, USER, ORG
from tests.test_discovery_backend import isolated, search


def set_session(client, *, expired):
    repository = identity_api._get_service()._session_svc._session_repo
    session = Session(id=SESSION, user_id=USER, organization_id=ORG,
                      expires_at=datetime.now(timezone.utc) + timedelta(hours=-1 if expired else 1))
    client.portal.call(repository.save, session)


@pytest.mark.parametrize("when", ["before-post", "after-completion"])
def test_expired_synthetic_session_does_not_authorize_discovery(isolated, monkeypatch, when):
    client, app = isolated
    # Do not let conftest's permissive legacy-token shim conceal a real 401.
    monkeypatch.setattr(dependencies, "resolve_web_session", REAL_RESOLVE_WEB_SESSION)
    run = search(client) if when == "after-completion" else None
    before = {table: len(app.state.synthetic.tables[table])
              for table in ("jobs", "discoveries", "search_results", "discovery_leads")}
    set_session(client, expired=True)
    if run:
        response = client.get("/api/web/session/_/leads", params={"q": run["query"], "discovery_id": run["id"]})
        assert client.get(f"/api/discoveries/{run['id']}").status_code == 401
    else:
        response = client.post("/api/discoveries", json={"query": "COO", "initiation": "manual"})
    assert response.status_code == 401, response.text
    assert "session" in response.json()["detail"].lower()
    assert {table: len(app.state.synthetic.tables[table]) for table in before} == before
    set_session(client, expired=False)  # Explicit synthetic re-authentication, not automatic recovery.
    if run:
        assert client.get(f"/api/discoveries/{run['id']}").json()["discovery"]["status"] == "completed"
        response = client.get("/api/web/session/_/leads", params={"q": run["query"], "discovery_id": run["id"]})
        assert response.status_code == 200 and response.json()["total"] == 56
    else:
        assert search(client)["status"] == "completed"
    assert app.state.blocked == []
