import hashlib
import json

from services.job_engine import job_manager
from services.learning import Learner
from services.workspace_memory import get_all as get_memory
from services.workspace_timeline import get_events
from services.workspace_reasoner import WorkspaceReasoner
from services.world_model.snapshot_adapter import (
    build_snapshot_from_wm as _build_wm_snapshot,
    get_data_source as _wm_data_source,
)


_cache: dict[str, dict] = {}


def _log(msg: str) -> None:
    print(f"[workspace_snapshot] {msg}")


def _make_cache_key(session_token: str, campaigns: list, drafts: list) -> str:
    content = f"{session_token}:{len(campaigns)}:{len(drafts)}"
    for c in campaigns:
        content += f"|{c.get('id','')}:{c.get('status','')}:{c.get('lead_count',0)}:{c.get('updated_at','')}"
    for d in drafts:
        content += f"|{d.get('id','')}:{d.get('status','')}:{d.get('campaign_id','')}"
    return hashlib.sha256(content.encode()).hexdigest()[:32]


def enrich_campaigns(campaigns: list, drafts: list) -> list[dict]:
    """Single source of truth for campaign enrichment.

    Returns enriched campaign dicts with pending_drafts and approved_drafts
    computed from the drafts list. All endpoints that display campaigns
    MUST call this instead of duplicating the iteration logic.
    """
    result = []
    for c in campaigns:
        cid = c.get("id", "")
        cdrafts = [d for d in drafts if d.get("campaign_id") == cid]
        pending = sum(1 for d in cdrafts if d.get("status") == "pending")
        approved = sum(1 for d in cdrafts if d.get("status") == "approved")
        result.append({**c, "pending_drafts": pending, "approved_drafts": approved})
    return result


def invalidate_cache(session_token: str) -> None:
    keys = [k for k in _cache if k.startswith(session_token)]
    for k in keys:
        del _cache[k]
    _log(f"invalidated {len(keys)} cache entr{'ies' if len(keys) != 1 else 'y'} for {session_token}")


def build_snapshot(
    session_token: str,
    campaigns: list[dict],
    drafts: list[dict],
    total_leads: int = 0,
    force_refresh: bool = False,
    user_id: str | None = None,
) -> dict:
    # ── Phase 3: try World Model first ──
    wm_snapshot = _build_wm_snapshot(session_token, user_id=user_id)
    if wm_snapshot is not None:
        reasoner = WorkspaceReasoner(wm_snapshot)
        analysis = reasoner.analyze()
        wm_snapshot["analysis"] = analysis.to_dict()
        wm_snapshot["_cached_at"] = 0
        _log(
            "World Model snapshot (campaigns/drafts/leads from WM, "
            "memory/timeline/jobs from legacy) "
            f"[source={_wm_data_source()}]"
        )
        return wm_snapshot

    # ── Legacy fallback ──
    _log(
        f"Legacy snapshot (campaigns={len(campaigns)}, drafts={len(drafts)}) "
        "[source=legacy]"
    )

    ck = _make_cache_key(session_token, campaigns, drafts)
    if not force_refresh and _cache.get(ck):
        _log("returning cached snapshot")
        return _cache[ck]

    if user_id is None:
        user_id = f"web:{session_token}"

    enriched = enrich_campaigns(campaigns, drafts)

    campaign_list = []
    pending_drafts = 0
    approved_drafts = 0
    for c in enriched:
        pending = c.get("pending_drafts", 0)
        approved = c.get("approved_drafts", 0)
        pending_drafts += pending
        approved_drafts += approved
        campaign_list.append({
            "id": c.get("id", ""),
            "name": c.get("name", ""),
            "status": c.get("status", "planning"),
            "lead_count": c.get("lead_count", 0),
            "pending_drafts": pending,
            "approved_drafts": approved,
            "created_at": c.get("created_at", ""),
            "updated_at": c.get("updated_at", ""),
        })

    running_jobs = []
    recent_jobs = []
    try:
        all_jobs = job_manager.list_recent_jobs(user_id)
        running_jobs = [j for j in all_jobs if j.get("status") in ("queued", "running")]
        recent_jobs = [j for j in all_jobs if j.get("status") == "completed"][:5]
    except Exception:
        pass

    memory = get_memory(session_token)
    timeline = get_events(session_token, limit=10)

    campaigns_ready = sum(1 for c in campaign_list if c["status"] in ("ready", "ready_to_send"))
    campaigns_draft_review = sum(1 for c in campaign_list if c["status"] == "draft_review")

    snapshot = {
        "campaigns": campaign_list,
        "campaign_count": len(campaign_list),
        "campaigns_ready": campaigns_ready,
        "campaigns_draft_review": campaigns_draft_review,
        "drafts": {
            "total": len(drafts),
            "pending": pending_drafts,
            "approved": approved_drafts,
        },
        "total_leads": total_leads,
        "jobs": {
            "running": running_jobs,
            "recently_completed": recent_jobs,
        },
        "memory": memory,
        "timeline": timeline,
    }

    reasoner = WorkspaceReasoner(snapshot)
    analysis = reasoner.analyze()
    snapshot["analysis"] = analysis.to_dict()

    # ── Phase 8: deterministic learning from user behavior ──
    try:
        learner = Learner()
        learned_event_ids = learner.run(session_token)
        if learned_event_ids:
            _log(f"learned {len(learned_event_ids)} new preference(s)")
    except Exception:
        _log("learning run failed (non-fatal)")

    _cache[ck] = snapshot
    if len(_cache) > 50:
        oldest = min(_cache.keys(), key=lambda k: _cache[k].get("_cached_at", 0))
        del _cache[oldest]
    snapshot["_cached_at"] = 0

    return snapshot
