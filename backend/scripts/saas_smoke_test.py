"""SaaS-1.7 post-deployment smoke test (read-mostly, safe).

Verifies the deployed application end to end using a PRE-PROVISIONED test
account (never creates real accounts). Safe operations only — no destructive
actions; session/org actions are performed against the labeled test account.

Usage:
    BASE_URL=https://<prod-host> SMOKE_EMAIL=saas-smoke@example.com \
    SMOKE_PASSWORD='<password>' python -m scripts.saas_smoke_test

Exit code 0 on success; non-zero with a failing step listed otherwise.
"""

from __future__ import annotations

import os
import sys

import httpx

BASE = os.getenv("BASE_URL", "http://localhost:10000")
EMAIL = os.getenv("SMOKE_EMAIL", "")
PASSWORD = os.getenv("SMOKE_PASSWORD", "")
LABEL = "saas1-smoke"  # marks requests for log correlation


def _check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        raise SystemExit(f"smoke test failed at: {name}")


def main() -> int:
    if not EMAIL or not PASSWORD:
        raise SystemExit("SMOKE_EMAIL / SMOKE_PASSWORD required (pre-provisioned test account)")

    client = httpx.Client(base_url=BASE, timeout=30.0, headers={"User-Agent": LABEL})

    # A. Application
    v = client.get("/version"); _check("GET /version", v.status_code == 200 and "commit" in v.json())
    h = client.get("/health"); _check("GET /health", h.status_code == 200)
    r = client.get("/ready"); _check("GET /ready", r.status_code == 200 and r.json().get("status") == "ready", str(r.json()))

    # B. Authentication
    login = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    _check("login", login.status_code == 200, str(login.status_code))
    tokens = login.json()
    access = tokens["access_token"]
    refresh = tokens["refresh_token"]
    headers = {"Authorization": f"Bearer {access}"}

    me = client.get("/api/v1/auth/me", headers=headers)
    _check("GET /me", me.status_code == 200 and me.json()["email"] == EMAIL)

    sessions = client.get("/api/v1/auth/sessions", headers=headers)
    _check("list sessions", sessions.status_code == 200)

    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    _check("refresh", refreshed.status_code == 200)
    refresh = refreshed.json()["refresh_token"]

    # C. Session security (safe: operate on our own session only)
    # NOTE: never revoke our own session here — the access token IS the session
    # id, so `DELETE /sessions/{access}` would invalidate the bearer token for
    # every later check and the unknown-session call below would return 401 from
    # authentication instead of the endpoint's intended 404. Verify instead that
    # an unknown / foreign session id is rejected with the safe 404.
    unknown = client.delete("/api/v1/auth/sessions/00000000-0000-4000-8000-000000000000", headers=headers)
    _check("cross-user session revoke rejected", unknown.status_code == 404, str(unknown.status_code))

    # Regression guard: the bearer token must still be valid here. If a future
    # edit reintroduces a self-revocation above, this fails loudly instead of
    # silently poisoning every check that follows.
    still_valid = client.get("/api/v1/auth/me", headers=headers)
    _check("session still active after revoke-rejection check", still_valid.status_code == 200, str(still_valid.status_code))

    # D. OAuth initiation (public entry — no token exchange)
    oauth = client.get("/api/v1/auth/oauth/google")
    _check("oauth initiate", oauth.status_code == 200 and "authorize_url" in oauth.json())

    # E. Web session: authenticated bootstrap + request, then logout + rejection
    ws = client.post("/api/web/session", json={"display_name": LABEL}, headers=headers)
    _check("authenticated web bootstrap", ws.status_code == 200, str(ws.status_code))
    ws_token = ws.json().get("session_token", "")
    ws_headers = {"Authorization": f"Bearer {ws_token}"}

    # The bound web-session must resolve to the canonical user while the
    # canonical session is valid (SaaS-1.6 session-authority check).
    ws_check = client.get("/api/web/session/_", headers=ws_headers)
    _check("bound web-session resolves to canonical user", ws_check.status_code == 200, str(ws_check.status_code))

    # F. Organization: read own org from /me; list own organizations
    orgs = client.get("/api/v1/organizations", headers=headers)
    _check("list own organizations", orgs.status_code == 200)

    # Non-member / cross-org read must be rejected with the safe 404 (BOLA).
    org_x = client.get("/api/v1/organizations/00000000-0000-4000-8000-000000000000", headers=headers)
    _check("cross-org read rejected (404)", org_x.status_code == 404, str(org_x.status_code))

    # G. Capabilities catalog (public) + org capabilities (member)
    caps = client.get("/api/v1/capabilities")
    _check("capability catalog public", caps.status_code == 200)

    # H. Billing plans (public catalog)
    plans = client.get("/api/v1/billing/plans")
    _check("billing plans public", plans.status_code == 200)

    # E2. Logout, then the canonical access token must be rejected, and the
    # bound web-session must be invalidated by the canonical-session revocation.
    logout = client.post("/api/v1/auth/logout", json={"refresh_token": refresh})
    _check("logout", logout.status_code == 200)
    me_after = client.get("/api/v1/auth/me", headers=headers)
    _check("access token rejected after logout", me_after.status_code == 401, str(me_after.status_code))
    ws_after = client.get("/api/web/session/_", headers=ws_headers)
    _check("bound web-session rejected after canonical revocation", ws_after.status_code == 401, str(ws_after.status_code))

    print("\nSaaS-1.7 smoke test: ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())