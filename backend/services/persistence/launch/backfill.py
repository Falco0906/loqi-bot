"""One-shot backfill of canonical launch tables from the event log.

Idempotent per workspace session: every channel='workspace' session carries a
``backfilled_at`` marker (added by the startup migration). ``backfill_all``
only lists sessions whose marker is still NULL, replays their event log into
canonical tables, and sets the marker immediately after — regardless of
whether the session had events. Startup therefore performs zero replay work
for already-migrated users; only sessions created after the last run are
touched. Callable from startup; a no-op without a Supabase client.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import time
from datetime import datetime, timezone

from services.conversation_store import ensure_workflow_session
from services.supabase import get_supabase_client

logger = logging.getLogger(__name__)

_MARKER_COLUMN = "backfilled_at"
_BACKFILL_WORKERS = 8


def _log(msg: str) -> None:
    logger.info("backfill %s", msg)


def _warn(msg: str) -> None:
    logger.warning("backfill %s", msg)


def _run_to_completion(coro):
    """Run a coroutine from sync code; safe inside a running loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    holder: dict[str, object] = {}

    def runner():
        try:
            holder["value"] = asyncio.run(coro)
        except BaseException as error:
            holder["error"] = error

    thread = threading.Thread(target=runner, daemon=True, name="backfill-coro")
    thread.start()
    thread.join(timeout=60.0)
    if "error" in holder:
        raise holder["error"]
    return holder.get("value")


def _pending_sessions(client) -> list[tuple[str, str]]:
    """Return (session_id, user_id) pairs that have not been backfilled.

    Uses the ``backfilled_at`` marker when the column exists (migration
    applied); falls back to ALL workspace sessions otherwise so startup still
    works on databases that predate the marker column. A marker-filter failure
    is logged (never silently suppressed) and the full-scan fallback runs.
    """
    rows: list[dict] = []
    try:
        result = (
            client.table("workflow_sessions")
            .select("id, user_id")
            .eq("channel", "workspace")
            .is_(_MARKER_COLUMN, None)
            .execute()
        )
        rows = getattr(result, "data", None) or []
    except Exception as error:
        _warn(
            f"marker-filtered session listing failed (type={type(error).__name__}); "
            "falling back to full workspace-session scan"
        )
        try:
            result = (
                client.table("workflow_sessions")
                .select("id, user_id")
                .eq("channel", "workspace")
                .execute()
            )
            rows = getattr(result, "data", None) or []
        except Exception as fallback_error:
            _warn(
                f"full-scan session listing also failed (type={type(fallback_error).__name__})"
            )
            return []
    pending = {
        (str(r["id"]), str(r["user_id"]))
        for r in rows
        if r.get("id") and r.get("user_id")
    }
    return sorted(pending)


def _mark_backfilled(client, session_id: str) -> None:
    try:
        result = (
            client.table("workflow_sessions")
            .update({_MARKER_COLUMN: datetime.now(timezone.utc).isoformat()})
            .eq("id", session_id)
            .execute()
        )
        data = getattr(result, "data", None) or []
        if not data:
            _warn(f"mark session {session_id[:8]} backfilled: empty update response")
    except Exception as error:
        _warn(f"cannot mark session {session_id[:8]} backfilled (type={type(error).__name__})")


def backfill_workspace(user_id: str) -> bool:
    """Backfill canonical rows for one user's workspace from workflow_events.

    Returns True when the workspace was processed (regardless of whether it
    had events to replay). Used by the tests and one-off callers; the startup
    path uses ``backfill_all``, which also persists the backfill marker.
    """
    try:
        session_id = ensure_workflow_session(
            user_id=user_id, channel="workspace", session_key=user_id,
        )
        if not session_id:
            return False
        _run_to_completion(_backfill_session_async(user_id, session_id))
        return True
    except Exception as error:
        _log(f"workspace backfill failed for user {user_id[:8]} (type={type(error).__name__})")
        return False


async def _backfill_session_async(user_id: str, session_id: str) -> None:
    client = get_supabase_client()
    if client is None:
        return

    from services.workspace_state import (
        _events,
        _persist_campaign_lead_row,
        _update_campaign_row,
        _update_draft_row,
        _update_lead_decision,
        _write_campaign_row,
        _write_draft_row,
        _write_strategy,
    )
    from services.persistence.launch import CampaignRepository

    # Safety net for sessions backfilled before the marker column existed:
    # canonical campaign rows already seeded → nothing left to replay.
    campaign_repo = CampaignRepository()
    try:
        existing = await campaign_repo.list_for_workspace(session_id)
    except BaseException:
        raise
    if existing:
        return

    events = _events(user_id, session_id=session_id)
    if not events:
        return

    replayed = 0
    for event in events:
        kind = event.get("event_type", "")
        payload = event.get("payload") or {}
        try:
            if kind == "campaign.created":
                campaign = payload.get("campaign") or {}
                if campaign.get("id"):
                    await _write_campaign_row(user_id, campaign)
                    if isinstance(campaign.get("strategy"), dict):
                        await _write_strategy(campaign_id=campaign["id"], strategy=campaign["strategy"])
            elif kind == "campaign.updated":
                updates = payload.get("updates") or {}
                if payload.get("campaign_id"):
                    await _update_campaign_row(user_id, payload["campaign_id"], updates)
            elif kind == "campaign.lead_added":
                lead = payload.get("lead")
                if payload.get("campaign_id") and isinstance(lead, dict):
                    await _persist_campaign_lead_row(user_id, payload["campaign_id"], lead)
            elif kind in ("lead.approved", "lead.rejected"):
                lead = payload.get("lead")
                if isinstance(lead, dict):
                    await _update_lead_decision(user_id, lead, kind == "lead.approved")
            elif kind == "draft.created":
                draft = payload.get("draft") or {}
                if draft.get("id"):
                    await _write_draft_row(user_id, draft)
            elif kind == "draft.updated":
                if payload.get("draft_id"):
                    await _update_draft_row(user_id, payload["draft_id"], payload.get("updates") or {})
            replayed += 1
        except Exception as error:
            _log(f"event replay skipped ({kind}) (type={type(error).__name__})")
    _log(f"session {session_id[:8]} replayed {replayed} event(s)")


def backfill_all() -> int:
    """Backfill every pending workspace session; mark each one done.

    Only sessions whose ``backfilled_at`` marker is NULL are processed, so
    subsequent startups perform zero replay work except for sessions created
    since the last run. The marker is persisted per session as it completes,
    so an interrupted pass resumes rather than restarting.
    """
    client = get_supabase_client()
    if client is None:
        return 0
    try:
        pending = _pending_sessions(client)
    except Exception as error:
        _warn(f"cannot list pending workspace sessions (type={type(error).__name__})")
        return 0
    if not pending:
        return 0

    started = time.monotonic()
    done = 0
    try:
        if len(pending) == 1:
            session_id, user_id = pending[0]
            if _process_session(client, session_id, user_id):
                done += 1
        else:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=_BACKFILL_WORKERS,
                thread_name_prefix="backfill",
            ) as pool:
                futures = {
                    pool.submit(_process_session, client, session_id, user_id): session_id
                    for session_id, user_id in pending
                }
                for future in concurrent.futures.as_completed(futures):
                    try:
                        if future.result():
                            done += 1
                    except BaseException as error:
                        _warn(f"backfill worker raised (type={type(error).__name__})")
    except BaseException as error:
        _warn(f"backfill pass aborted (type={type(error).__name__})")
    _log(f"pass complete: {done}/{len(pending)} session(s) marked "
         f"in {time.monotonic() - started:.1f}s")
    return done


def _process_session(client, session_id: str, user_id: str) -> bool:
    """Replay one session and persist its marker on success."""
    try:
        _run_to_completion(_backfill_session_async(user_id, session_id))
        _mark_backfilled(client, session_id)
        return True
    except BaseException as error:
        _warn(f"session {session_id[:8]} backfill failed (type={type(error).__name__})")
        return False
