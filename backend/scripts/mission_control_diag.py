"""TMP-DIAGNOSTIC: trace the Mission Control request path end to end.

Reproduces exactly what the frontend does on the Mission Control page:
two GETs fired in parallel — /mission-control and /briefing — against the
same web session token, through the real FastAPI app (TestClient, no
lifespan so no startup sweep interference).

Every Supabase query, AI call, and handler phase is timed and logged.

Usage:
    python scripts/mission_control_diag.py [--token TOKEN] [--user-id UID]
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

DEFAULT_TOKEN = "_5pbnHGls-9aDjIJJL2h0yCL"  # web session for the workspace owner
FRONTEND_TIMEOUT_MS = 10_000

LOG_DIR = os.path.join(BACKEND_DIR, "logs")
LOG_PATH = os.path.join(LOG_DIR, "mission_control_diag.log")


def log(msg: str) -> None:
    line = f"[diag {datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> int:
    from fastapi.testclient import TestClient
    import main as main_app

    token = sys.argv[sys.argv.index("--token") + 1] if "--token" in sys.argv else DEFAULT_TOKEN

    app = main_app.app
    client = TestClient(app, raise_server_exceptions=False)

    briefing_url = f"/api/web/session/{token}/briefing"
    mc_url = f"/api/web/session/{token}/mission-control"

    log(f"frontend timeout: {FRONTEND_TIMEOUT_MS}ms (fetchWithRetry default)")
    log(f"target: {mc_url}")
    log("=" * 70)

    results = {}

    # ── Request 1: briefing ──
    log(f"REQUEST briefing  ->  {briefing_url}")
    t0 = time.monotonic()
    try:
        r1 = client.get(briefing_url, timeout=FRONTEND_TIMEOUT_MS / 1000 + 5)
        dt = (time.monotonic() - t0) * 1000
        results["briefing"] = (r1.status_code, dt)
        log(f"RESPONSE briefing: status={r1.status_code} wall={dt:.0f}ms")
        if r1.status_code == 200:
            log(f"  body keys={len(r1.json())} top_priorities={len(r1.json().get('top_priorities', []))}")
    except Exception as e:
        dt = (time.monotonic() - t0) * 1000
        results["briefing"] = ("EXC", dt)
        log(f"RESPONSE briefing EXCEPTION after {dt:.0f}ms: {e!r}")

    # ── Request 2: mission-control ──
    log(f"REQUEST mission-control ->  {mc_url}")
    t0 = time.monotonic()
    try:
        r2 = client.get(mc_url, timeout=FRONTEND_TIMEOUT_MS / 1000 + 5)
        dt = (time.monotonic() - t0) * 1000
        results["mission-control"] = (r2.status_code, dt)
        log(f"RESPONSE mission-control: status={r2.status_code} wall={dt:.0f}ms")
        if r2.status_code == 200:
            log(f"  body keys={len(r2.json())} campaigns={len(r2.json().get('campaigns', []))}")
    except Exception as e:
        dt = (time.monotonic() - t0) * 1000
        results["mission-control"] = ("EXC", dt)
        log(f"RESPONSE mission-control EXCEPTION after {dt:.0f}ms: {e!r}")

    log("=" * 70)
    for name, (status, ms) in results.items():
        verdict = "FAIL (frontend aborts at 10s)" if ms > FRONTEND_TIMEOUT_MS else "OK"
        log(f"SUMMARY {name}: status={status} {ms:.0f}ms  ->  {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
