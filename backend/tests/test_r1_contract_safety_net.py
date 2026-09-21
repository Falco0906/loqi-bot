"""R1 characterization guards for externally observable API boundaries.

These tests deliberately cover only boundary contracts not already asserted by
the domain suites.  They are a small safety net for route extraction: public
operations remain public, while legacy session, Discovery, and identity reads
fail closed without a bearer credential.
"""


def test_public_liveness_contract(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_legacy_session_route_requires_bearer_at_http_boundary(client):
    response = client.get("/api/web/session/_/workspaces")

    assert response.status_code == 401
    assert isinstance(response.json().get("detail"), str)


def test_discovery_collection_requires_bearer_at_http_boundary(client):
    response = client.get("/api/discoveries")

    assert response.status_code == 401
    assert isinstance(response.json().get("detail"), str)


def test_identity_me_requires_bearer_at_http_boundary(client):
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert isinstance(response.json().get("detail"), str)
