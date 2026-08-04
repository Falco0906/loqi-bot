"""One-shot backfill of canonical launch tables from the event log.

Idempotent per workspace: once a workspace has canonical campaign rows, its
replay is skipped. Callable from startup; a no-op without a Supabase client.
"""

from __future__ import annotations

import asyncio
import inspect
import threading

from services.conversation_store import ensure_workflow_session
from services.supabase import get_supabase_client


def _log(msg: str) -> None:
    print(f"[backfill] {msg}")


def _run_to_completion(coro):
    """Run a coroutine from sync code; safe inside a running loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    holder: dict[str, object] = {}

    def runner():
        holder["value"] = asyncio.run(coro)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(timeout=60.0)
    return holder.get("value")


def backfill_workspace(user_id: str) -> bool:
    """Backfill canonical rows for one user's workspace from workflow_events."""
    try:
        _run_to_completion(_backfill_workspace_async(user_id))
        return True
    except Exception as error:
        _log(f"backfill failed for user {user_id}: {error}")
        return False


async def _backfill_workspace_async(user_id: str) -> None:
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

    workspace_id = ensure_workflow_session(
        user_id=user_id, channel="workspace", session_key=user_id,
    )
    if not workspace_id:
        return

    # Idempotency: workspace already seeded → skip replay.
    campaign_repo = CampaignRepository()
    if await campaign_repo.list_for_workspace(workspace_id):
        return

    events = _events(user_id)
    if not events:
        return

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
        except Exception as error:
            _log(f"event replay skipped ({kind}): {error}")


def backfill_all() -> int:
    """Backfill every workspace-channel user found in workflow_sessions."""
    client = get_supabase_client()
    if client is None:
        return 0
    try:
        result = (
            client.table("workflow_sessions")
            .select("user_id")
            .eq("channel", "workspace")
            .execute()
        )
        rows = getattr(result, "data", None) or []
        user_ids = sorted({str(r["user_id"]) for r in rows if r.get("user_id")})
    except Exception as error:
        _log(f"cannot list workspace users: {error}")
        return 0
    done = 0
    for user_id in user_ids:
        if backfill_workspace(user_id):
            done += 1
    if user_ids:
        _log(f"backfill complete: {done}/{len(user_ids)} workspaces")
    return done