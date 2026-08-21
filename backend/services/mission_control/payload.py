"""Shared Mission Control payload — one state load + one LLM computation per
workspace state, served to both ``/mission-control`` and ``/briefing``.

Without this, every Mission Control page visit fired the narrative LLM steps
twice (one per endpoint) AND re-ran them on the next visit because the World
Model acknowledgement consumes the delta that the brief caches key on.

Semantics:
  * Key = (owner, content fingerprint, delta fingerprint, 4h hour bucket).
  * Content fingerprint covers campaign/draft identity + status — changes only
    when the workspace actually changes.
  * Delta fingerprint covers the "what's new since last view" counts — changes
    once when new events arrive, and once when they are acknowledged, then
    stabilises (no ack-churn).
  * Hour bucket lets the greeting rotate without recomputing per hour.
  * In-flight futures dedupe concurrent calls (the frontend fires both
    endpoints in parallel), so the second caller waits on the first instead of
    duplicating the LLM work.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any

from services.world_model.store import WorkspaceDelta


_payload_cache: dict[tuple, dict[str, Any]] = {}
_inflight: dict[tuple, asyncio.Future] = {}
_MAX_ENTRIES = 8


def _hour_bucket() -> int:
    return datetime.now(timezone.utc).hour // 4


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
        delta.event_count,
        len(delta.new_campaigns),
        len(delta.changed_campaigns),
        len(delta.new_drafts),
        len(delta.new_leads),
        len(delta.new_conversations),
        len(delta.completed_jobs),
    )
    return ":".join(str(m) for m in meta)


def _evict() -> None:
    while len(_payload_cache) > _MAX_ENTRIES:
        oldest = min(_payload_cache, key=lambda k: _payload_cache[k]["_ts"])
        _payload_cache.pop(oldest, None)


def get_cached_payload(
    owner_id: str,
    campaigns: list[dict],
    drafts: list[dict],
    delta: WorkspaceDelta,
) -> dict[str, Any] | None:
    key = (owner_id, _content_fingerprint(campaigns, drafts), _delta_fingerprint(delta), _hour_bucket())
    return _payload_cache.get(key)


def cache_payload(
    owner_id: str,
    campaigns: list[dict],
    drafts: list[dict],
    delta: WorkspaceDelta,
    payload: dict[str, Any],
) -> None:
    key = (owner_id, _content_fingerprint(campaigns, drafts), _delta_fingerprint(delta), _hour_bucket())
    payload["_ts"] = time.monotonic()
    _payload_cache[key] = payload
    _evict()


async def compute_shared_payload(
    owner_id: str,
    session_token: str,
    db_user_id: str | None,
) -> dict[str, Any]:
    """Load state once and compute {campaigns, drafts, snapshot, analysis,
    recommendations, brief}; dedupe concurrent callers per key."""
    from main import _embed_delta_into_snapshot
    from services.workspace_state import load_workspace_state
    from services.workspace_snapshot import build_snapshot
    from services.recommendation_engine import generate_recommendations
    from services.executive_brief import generate_brief
    from services.world_model import get_store as get_wm_store

    loop = asyncio.get_running_loop()

    # State load is independent of the key — but on a cache hit we can serve
    # straight from the stored payload without touching Supabase again.
    state = await asyncio.to_thread(load_workspace_state, owner_id, include_details=False)
    campaigns = state["campaigns"]
    drafts = state["drafts"]
    total_leads = sum(c.get("lead_count", 0) or 0 for c in campaigns)

    wm = get_wm_store()
    delta = wm.compute_delta(session_token)

    key = (
        owner_id,
        _content_fingerprint(campaigns, drafts),
        _delta_fingerprint(delta),
        _hour_bucket(),
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
                    session_token, campaigns, drafts, total_leads, user_id=db_user_id,
                )
                _embed_delta_into_snapshot(snap, delta)
                recs = generate_recommendations(snap)
                brf = generate_brief(snap, recs)
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