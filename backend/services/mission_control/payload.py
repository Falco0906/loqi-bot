"""Shared Mission Control payload — one state load + one LLM computation per
workspace state, served to both ``/mission-control`` and ``/briefing``.

Without this, every Mission Control page visit fired the narrative LLM steps
twice (one per endpoint). Durable activity is read with an authorized
workspace/user cursor; the legacy session-keyed World Model is not consulted.

Semantics:
  * Key = (owner, workspace, content fingerprint, delta fingerprint, user timezone,
    greeting period, narrative mode).
  * Content fingerprint covers campaign/draft identity + status — changes only
    when the workspace actually changes.
  * Delta fingerprint includes the durable cursor/delivered event range.
  * Greeting period lets the greeting rotate at the user's local boundaries.
  * In-flight futures dedupe concurrent calls (the frontend fires both
    endpoints in parallel), so the second caller waits on the first instead of
    duplicating the LLM work.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

from services.mission_control.narrative import greeting_for_timezone, normalize_timezone
from services.world_model.activity_repository import WorkspaceActivityEvent, get_activity_repository
from services.world_model.state import CampaignState, DraftState, WorkspaceDelta


_payload_cache: dict[tuple, dict[str, Any]] = {}
_inflight: dict[tuple, asyncio.Future] = {}
_MAX_ENTRIES = 8


def embed_delta_into_snapshot(snapshot: dict, delta: WorkspaceDelta) -> None:
    """Add World Model delta metadata required by the executive brief."""
    snapshot["_delta"] = {
        "first_visit": delta.first_visit,
        "event_count": delta.event_count,
        "event_range": list(delta.event_range),
        "new_campaigns": len(delta.new_campaigns),
        "changed_campaigns": len(delta.changed_campaigns),
        "new_drafts": len(delta.new_drafts),
        "scheduled_drafts": len(delta.scheduled_drafts),
        "sent_outreach": len(delta.sent_outreach),
        "new_leads": len(delta.new_leads),
        "new_providers": len(delta.new_providers),
        "new_conversations": len(delta.new_conversations),
        "escalated_conversations": len(delta.escalated_conversations),
        "completed_jobs": len(delta.completed_jobs),
        "learned_preferences": len(delta.learned_preferences),
        "new_insights": len(delta.new_insights),
        "has_delta": not delta.is_empty(),
    }


def _content_fingerprint(campaigns: list[dict], drafts: list[dict]) -> str:
    campaign_rows = [
        (
            c.get("id"), c.get("status"), c.get("lead_count"),
            c.get("generation", {}).get("status") if isinstance(c.get("generation"), dict) else None,
            c.get("updated_at"),
        )
        for c in campaigns
    ]
    draft_rows = [
        (d.get("id"), d.get("status"), d.get("campaign_id"), d.get("updated_at"))
        for d in drafts
    ]
    payload = json.dumps(
        {"c": campaign_rows, "d": draft_rows},
        sort_keys=True, default=str, separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _delta_fingerprint(delta: WorkspaceDelta) -> str:
    meta = (
        delta.first_visit,
        delta.event_count,
        *delta.event_range,
        len(delta.new_campaigns),
        len(delta.changed_campaigns),
        len(delta.new_drafts),
        len(delta.new_leads),
        len(delta.new_conversations),
        len(delta.completed_jobs),
    )
    return ":".join(str(m) for m in meta)


def _durable_activity_delta(events: list[WorkspaceActivityEvent], cursor: int) -> WorkspaceDelta:
    """Project the bounded durable activity slice into the existing delta type."""
    if not events:
        return WorkspaceDelta(first_visit=cursor == 0, event_range=(0, 0) if cursor == 0 else (cursor + 1, cursor))
    delta = WorkspaceDelta(
        first_visit=cursor == 0,
        event_count=len(events),
        event_range=(events[0].sequence, events[-1].sequence),
    )
    for event in events:
        payload = event.payload
        if event.event_type == "draft_generated":
            delta.new_drafts.append(DraftState(
                id=str(payload.get("draft_id") or ""),
                campaign_id=str(payload.get("campaign_id") or ""),
                lead_id=str(payload.get("lead_id") or ""),
                status=str(payload.get("status") or "pending"),
                created_at=event.occurred_at,
            ))
        elif event.event_type == "campaign_created":
            delta.new_campaigns.append(CampaignState(
                id=str(payload.get("campaign_id") or ""),
                status=str(payload.get("status") or "planning"),
                lead_count=int(payload.get("lead_count") or 0),
                created_at=event.occurred_at,
                updated_at=event.occurred_at,
            ))
        elif event.event_type == "campaign_status_changed":
            delta.changed_campaigns.append(CampaignState(
                id=str(payload.get("campaign_id") or ""),
                status=str(payload.get("status") or "planning"),
                created_at=event.occurred_at,
                updated_at=event.occurred_at,
            ))
    return delta


async def _read_durable_delta(workspace_id: str, actor_user_id: str) -> WorkspaceDelta:
    """Read durable activity after this user's selected-workspace cursor."""
    repository = get_activity_repository()
    try:
        cursor = await asyncio.to_thread(repository.read_cursor, workspace_id, actor_user_id)
        events = await asyncio.to_thread(repository.read_events_after, workspace_id, cursor)
        return _durable_activity_delta(events, cursor)
    except Exception as error:
        # Durable activity enriches an otherwise canonical snapshot. A failed
        # read remains non-fatal, matching the former empty World Model delta.
        import logging
        logging.getLogger(__name__).warning(
            "workspace_activity_read_failed workspace_id=%s error_type=%s",
            workspace_id,
            type(error).__name__,
        )
        return WorkspaceDelta()


def _evict() -> None:
    while len(_payload_cache) > _MAX_ENTRIES:
        oldest = min(_payload_cache, key=lambda k: _payload_cache[k]["_ts"])
        _payload_cache.pop(oldest, None)


def get_cached_payload(
    owner_id: str,
    workspace_id: str,
    campaigns: list[dict],
    drafts: list[dict],
    delta: WorkspaceDelta,
    user_timezone: str | None = None,
    include_narrative: bool = True,
) -> dict[str, Any] | None:
    resolved_timezone = normalize_timezone(user_timezone)
    key = (
        owner_id,
        workspace_id,
        _content_fingerprint(campaigns, drafts),
        _delta_fingerprint(delta),
        resolved_timezone,
        greeting_for_timezone(resolved_timezone),
        include_narrative,
    )
    return _payload_cache.get(key)


def cache_payload(
    owner_id: str,
    workspace_id: str,
    campaigns: list[dict],
    drafts: list[dict],
    delta: WorkspaceDelta,
    payload: dict[str, Any],
    user_timezone: str | None = None,
    include_narrative: bool = True,
) -> None:
    resolved_timezone = normalize_timezone(user_timezone)
    key = (
        owner_id,
        workspace_id,
        _content_fingerprint(campaigns, drafts),
        _delta_fingerprint(delta),
        resolved_timezone,
        greeting_for_timezone(resolved_timezone),
        include_narrative,
    )
    payload["_ts"] = time.monotonic()
    _payload_cache[key] = payload
    _evict()


async def compute_shared_payload(
    owner_id: str,
    workspace_id: str,
    actor_user_id: str,
    session_token: str,
    include_narrative: bool = True,
    user_timezone: str | None = None,
) -> dict[str, Any]:
    """Load state once and compute {campaigns, drafts, snapshot, analysis,
    recommendations, brief}; dedupe concurrent callers per key."""
    from services.workspace.state import load_workspace_state
    from services.workspace.snapshot import build_snapshot
    from services.mission_control.recommendations import generate_recommendations
    from services.mission_control.narrative import generate_brief

    loop = asyncio.get_running_loop()

    # State load is independent of the key — but on a cache hit we can serve
    # straight from the stored payload without touching Supabase again.
    state = await asyncio.to_thread(
        load_workspace_state,
        owner_id,
        include_details=False,
        workspace_id=workspace_id,
        canonical_only=True,
    )
    campaigns = state["campaigns"]
    drafts = state["drafts"]
    total_leads = sum(c.get("lead_count", 0) or 0 for c in campaigns)

    delta = await _read_durable_delta(workspace_id, actor_user_id)

    resolved_timezone = normalize_timezone(user_timezone)
    greeting = greeting_for_timezone(resolved_timezone)
    key = (
        owner_id,
        workspace_id,
        _content_fingerprint(campaigns, drafts),
        _delta_fingerprint(delta),
        resolved_timezone,
        greeting,
        include_narrative,
    )

    cached = _payload_cache.get(key)
    if cached is not None:
        return cached

    fut = _inflight.get(key)
    if fut is None:
        fut = loop.create_future()
        _inflight[key] = fut
        _payload_cache.pop(key, None)
        try:
            def _build_payload_sync() -> dict[str, Any]:
                """PR-P1.2: snapshot build + brief/recommendation generation are
                synchronous (Supabase + OpenAI, 30s timeouts). Run them on a
                worker thread so a slow LLM cannot stall the event loop."""
                snap = build_snapshot(
                    session_token,
                    campaigns,
                    drafts,
                    total_leads,
                    user_id=actor_user_id,
                    workspace_id=workspace_id,
                )
                embed_delta_into_snapshot(snap, delta)
                recs = generate_recommendations(snap, use_narrative=include_narrative)
                if include_narrative:
                    brf = generate_brief(snap, recs, user_timezone=resolved_timezone)
                else:
                    lines = [
                        f"{campaign.get('name', 'Campaign')} has {campaign.get('lead_count', 0)} leads and is {campaign.get('status', 'active')}."
                        for campaign in campaigns[:3]
                    ]
                    brf = {"greeting": greeting, "lines": lines, "suggestion": ""}
                return {
                    "campaigns": campaigns,
                    "drafts": drafts,
                    "total_leads": total_leads,
                    "snapshot": snap,
                    "analysis": snap.get("analysis", {}),
                    "recommendations": recs,
                    "brief": brf,
                    "delta": delta,
                }

            payload = await asyncio.to_thread(_build_payload_sync)
            _payload_cache[key] = payload
            fut.set_result(payload)
        except Exception as error:
            fut.set_exception(error)
        finally:
            _inflight.pop(key, None)
    return await fut


def invalidate_payload(owner_id: str | None = None) -> None:
    if owner_id is None:
        _payload_cache.clear()
        return
    for k in [k for k in _payload_cache if k[0] == owner_id]:
        _payload_cache.pop(k, None)
