"""TEMP-DIAGNOSTIC: trace the startup backfill end-to-end against Supabase.

Mimics main.py startup exactly: backfill_all() offloaded to a worker thread.
Logs every phase, before/after marker counts, and total wall time so the
root cause of unmarked sessions can be proven from logs alone.

Usage:
    python scripts/backfill_diagnose.py --list-only   # counts only, no writes
    python scripts/backfill_diagnose.py               # full traced pass

All output also appended to backend/logs/backfill_diagnose.log
"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

LOG_DIR = os.path.join(BACKEND_DIR, "logs")
LOG_PATH = os.path.join(LOG_DIR, "backfill_diagnose.log")


def log(msg: str) -> None:
    line = f"[diag {datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def snapshot(client, tag: str) -> None:
    try:
        rows = (
            client.table("workflow_sessions")
            .select("id, backfilled_at")
            .eq("channel", "workspace")
            .execute()
        )
    except Exception as error:
        log(f"[{tag}] COUNT QUERY FAILED: {error!r}\n{traceback.format_exc()}")
        return
    data = getattr(rows, "data", None) or []
    null_count = sum(1 for r in data if r.get("backfilled_at") is None)
    log(
        f"[{tag}] workspace sessions total={len(data)} "
        f"null={null_count} marked={len(data) - null_count}"
    )
    marked_sample = [
        str(r.get("id"))[:8] for r in data if r.get("backfilled_at") is not None
    ][:10]
    log(f"[{tag}] marked sample ids: {marked_sample}")


def main() -> int:
    from services.supabase import SUPABASE_URL, get_supabase_client

    log(f"target supabase: {SUPABASE_URL}")
    client = get_supabase_client()
    if client is None:
        log("FATAL: no supabase client (missing SUPABASE_URL/SUPABASE_KEY)")
        return 2

    snapshot(client, "before")

    if "--list-only" in sys.argv:
        log("list-only mode: no backfill run")
        return 0

    from services.persistence.launch import backfill_all

    started = time.monotonic()

    def run() -> None:
        try:
            result = backfill_all()
            log(f"[run] backfill_all returned {result}")
        except BaseException as error:
            log(f"[run] backfill_all RAISED: {error!r}\n{traceback.format_exc()}")

    thread = threading.Thread(target=run, name="diag-backfill", daemon=False)
    thread.start()
    while thread.is_alive():
        thread.join(timeout=30.0)
        if thread.is_alive():
            log(f"[watchdog] still running after {time.monotonic() - started:.0f}s")

    log(f"[run] thread finished; total wall time {time.monotonic() - started:.1f}s")

    snapshot(client, "after")
    log("diagnostic pass complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
