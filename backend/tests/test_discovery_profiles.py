"""Offline startup-profile validation: no listener, credentials or database."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.discovery_backend.datasets import build_workspace_leads, lead_id, validate_profile
from tests.discovery_backend.store import A, B, FOREIGN
from tests.test_discovery_backend import isolated


@pytest.mark.parametrize("isolated,counts", [
    ("small", {"workspace_a": 58, "workspace_b": 1, "foreign": 1, "total": 60}),
    ("large", {"workspace_a": 604, "workspace_b": 2, "foreign": 1, "total": 607}),
], indirect=["isolated"])
def test_profile_identity_and_workspace_selection(isolated, counts):
    client, app = isolated
    identity = client.get("/__loqi_test/identity").json()
    assert identity["fixture_counts"] == counts
    assert identity["profile"] == app.state.synthetic.profile
    assert identity["persistence"] == "synthetic-memory"
    assert identity["outbound_blocked"] is True
    response = client.post("/api/web/session/_/workspaces/select", headers={"x-workspace-id": B})
    assert response.status_code == 200 and response.json()["workspace"]["id"] == B
    assert client.post("/api/web/session/_/workspaces/select", headers={"x-workspace-id": FOREIGN}).status_code == 404
    assert client.post("/__loqi_test/profile", json={"profile": "large"}).status_code == 403
    assert client.post("/api/web/session/_/leads/csv-import", json={"rows": []}).status_code == 403
    # Dashboard's event stream is explicitly unavailable, not a real worker.
    assert client.get("/api/events/stream").status_code == 403
    assert client.get("/__loqi_test/identity").json()["fixture_counts"] == counts
    assert app.state.synthetic.tables["jobs"] == app.state.synthetic.tables["discoveries"] == []
    assert app.state.blocked == []


def test_large_builder_exact_ids_roles_and_facts():
    rows = build_workspace_leads("large", A, B, FOREIGN)
    by_id = {row["id"]: row for row in rows}
    assert len(by_id) == len(rows) == 607
    assert {row["id"] for row in rows if row["workspace_id"] == A} == {lead_id(i) for i in range(1, 605)}
    assert {row["id"] for row in rows if row["workspace_id"] == B} == {lead_id(605), lead_id(606)}
    for start, title in ((1, "Head of Operations"), (201, "Operations Manager"), (401, "COO")):
        assert all(by_id[lead_id(i)]["title"] == title for i in range(start, start + 200))
    assert by_id[lead_id(601)]["metadata"]["csv_import"]["location"] == "Toronto"
    assert by_id[lead_id(602)]["metadata"]["csv_import"]["industry"] == ""
    assert by_id[lead_id(602)]["metadata"]["csv_import"]["location"] == ""
    assert by_id[lead_id(603)]["title"] == "Software Engineer"
    assert by_id[lead_id(604)]["metadata"]["csv_import"]["industry"] == "Retail"
    assert all(row["email"].endswith("@example.invalid") for row in rows)
    rows[0]["metadata"]["csv_import"]["company"] = "Mutated private copy"
    assert build_workspace_leads("large", A, B, FOREIGN)[0]["metadata"]["csv_import"]["company"] == "Synthetic Shop"


@pytest.mark.parametrize("profile", ["", "LARGE", " large", "unknown"])
def test_unknown_profile_fails_closed(profile):
    with pytest.raises(ValueError, match="Unknown isolated Discovery profile"):
        validate_profile(profile)


@pytest.mark.parametrize("profile", [None, "small", "large", "unknown"])
def test_clean_startup_captures_profile_before_application_imports(profile):
    code = """
import os, sys
from tests.discovery_backend.bootstrap import prepare_runtime, create_app
requested = os.environ.get('LOQI_ISOLATED_DISCOVERY_PROFILE', 'small')
try:
    approved = prepare_runtime()
except ValueError:
    assert requested == 'unknown'
    assert 'services.discovery.api' not in sys.modules
else:
    assert approved == requested
    os.environ['LOQI_ISOLATED_DISCOVERY_PROFILE'] = 'unknown-after-approval'
    app = create_app(profile=approved)
    assert app.state.synthetic.profile == approved
    assert app.state.synthetic.fixture_counts['workspace_a'] == (604 if approved == 'large' else 58)
print('profile-startup-safe')
"""
    env = {"PATH": os.defpath, "LANG": "C", "LOQI_ISOLATED_DISCOVERY_ENABLED": "1"}
    if profile is not None:
        env["LOQI_ISOLATED_DISCOVERY_PROFILE"] = profile
    result = subprocess.run([sys.executable, "-B", "-c", code], env=env,
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "profile-startup-safe" in result.stdout
