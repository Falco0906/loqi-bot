import hashlib
import json

from services.job_engine import job_manager
from services.workspace_memory import get_all as get_memory
from services.workspace_timeline import get_events
from services.workspace_reasoner import WorkspaceReasoner


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
    ck = _make_cache_key(session_token, campaigns, drafts)
    if not force_refresh and _cache.get(ck):
        _log("returning cached snapshot")
        return _cache[ck]

    _log(f"building new snapshot (campaigns={len(campaigns)}, drafts={len(drafts)})")

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
        all_jobs = job_manager.list_active_jobs(user_id)
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

    _cache[ck] = snapshot
    if len(_cache) > 50:
        oldest = min(_cache.keys(), key=lambda k: _cache[k].get("_cached_at", 0))
        del _cache[oldest]
    snapshot["_cached_at"] = 0

    return snapshot
