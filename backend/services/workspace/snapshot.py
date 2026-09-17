import hashlib
import json

from services.job_engine import job_manager
from services.learning import Learner
from services.workspace.memory import get_all as get_memory
from services.workspace.timeline import get_events
from services.workspace.reasoner import WorkspaceReasoner


_cache: dict[str, dict] = {}


def _log(msg: str) -> None:
    print(f"[workspace_snapshot] {msg}")


def _make_cache_key(session_token: str, workspace_id: str, campaigns: list, drafts: list) -> str:
    content = f"{session_token}:{workspace_id}:{len(campaigns)}:{len(drafts)}"
    for c in campaigns:
        content += f"|{c.get('id','')}:{c.get('status','')}:{c.get('lead_count',0)}:{c.get('updated_at','')}"
    for d in drafts:
        content += f"|{d.get('id','')}:{d.get('status','')}:{d.get('campaign_id','')}"
    return f"{session_token}:{workspace_id}:{hashlib.sha256(content.encode()).hexdigest()[:32]}"


def _derive_campaign_step(c: dict) -> str:
    """Derive the workflow step from persisted state, never from lifecycle status.

    research -> strategy -> drafts -> review -> sending. Research is the
    first production step; strategy is generated from the selected audience,
    never before leads exist. Draft gates (review/sending) only apply after
    leads and strategy exist — a campaign cannot be reviewing or sending
    drafts without an audience and messaging. Backward compatible —
    campaigns that already have a strategy keep flowing forward from
    wherever they are. Terminal/removed statuses have no actionable step.
    """
    status = c.get("status")
    if status in ("completed", "archived", "cancelled", "failed", "deleted"):
        return ""
    lead_count = c.get("lead_count", 0) or 0
    pending = c.get("pending_drafts", 0) or 0
    approved = c.get("approved_drafts", 0) or 0
    if lead_count == 0:
        return "research"
    if not c.get("strategy"):
        return "strategy"
    if pending > 0:
        return "review"
    if approved > 0:
        return "sending"
    return "drafts"


def enrich_campaigns(campaigns: list, drafts: list) -> list[dict]:
    """Single source of truth for campaign enrichment.

    Returns enriched campaign dicts with pending_drafts, approved_drafts and
    the derived workflow current_step. All endpoints that display campaigns
    MUST call this instead of duplicating the iteration logic.
    """
    result = []
    for c in campaigns:
        cid = c.get("id", "")
        cdrafts = [d for d in drafts if d.get("campaign_id") == cid]
        pending = sum(1 for d in cdrafts if d.get("status") == "pending")
        approved = sum(1 for d in cdrafts if d.get("status") == "approved")
        sent = sum(1 for d in cdrafts if d.get("status") == "sent")
        enriched = {**c, "pending_drafts": pending, "approved_drafts": approved, "sent_drafts": sent}
        enriched["current_step"] = _derive_campaign_step(enriched)
        result.append(enriched)
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
    workspace_id: str = "",
) -> dict:
    _log(
        f"Canonical snapshot (campaigns={len(campaigns)}, drafts={len(drafts)})"
    )

    ck = _make_cache_key(session_token, workspace_id, campaigns, drafts)
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
            "current_step": c.get("current_step", ""),
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
        if workspace_id:
            all_jobs = [job for job in all_jobs if str(job.get("workspace_id") or "") == workspace_id]
        running_jobs = [j for j in all_jobs if j.get("status") in ("queued", "running")]
        recent_jobs = [j for j in all_jobs if j.get("status") == "completed"][:5]
    except Exception:
        pass

    memory = get_memory(session_token)
    timeline = get_events(session_token, limit=10)

    campaigns_ready = sum(1 for c in campaign_list if c.get("current_step") == "sending")
    campaigns_draft_review = sum(1 for c in campaign_list if c.get("current_step") == "review")

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
        learned_event_ids = learner.run(
            session_token,
            workspace_id=workspace_id,
            actor_user_id=user_id,
        )
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
