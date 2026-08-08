from services.job_engine import job_manager
from services.workspace_memory import get_all as get_memory
from services.workspace_timeline import get_events
from services.world_model.publisher import get_store
from services.world_model.state import WorkspaceState


_DATA_SOURCE: str | None = None


def get_data_source() -> str | None:
    return _DATA_SOURCE


def _log(msg: str) -> None:
    print(f"[wm_adapter] {msg}")


def _draft_status(s: str) -> str:
    """Normalise DraftState.status values (lowercase) to match legacy."""
    return s.lower() if s else "pending"


def _campaigns_from_wm(state: WorkspaceState, campaigns: list | None = None) -> list[dict]:
    """Build enriched campaign list (with pending/approved counts) from WM.

    Progression is derived by the canonical ``_derive_campaign_step`` — the
    single source of truth shared with the web API path. Strategy presence is
    merged from the canonical campaign rows (the WM event log does not carry
    strategy facts), so every surface derives the same step from the same
    gates: leads -> strategy -> drafts -> review -> sending.
    """
    from services.workspace_snapshot import _derive_campaign_step

    legacy_by_id = {c.get("id"): c for c in (campaigns or [])}
    result = []
    for c in state.pipeline.campaigns:
        cdrafts = [d for d in state.pipeline.drafts if d.campaign_id == c.id]
        pending = sum(1 for d in cdrafts if _draft_status(d.status) == "pending")
        approved = sum(
            1 for d in cdrafts
            if _draft_status(d.status) in ("approved", "auto_approved")
        )
        legacy = legacy_by_id.get(c.id)
        entry = {
            "id": c.id,
            "name": c.name,
            "status": (legacy or {}).get("status", c.status),
            "lead_count": int((legacy or {}).get("lead_count", c.lead_count) or 0),
            "pending_drafts": pending,
            "approved_drafts": approved,
            "strategy": bool(legacy and legacy.get("strategy")),
            "created_at": c.created_at,
            "updated_at": c.updated_at,
        }
        entry["current_step"] = _derive_campaign_step(entry)
        result.append(entry)
    return result


def _draft_summary_from_wm(state: WorkspaceState) -> dict:
    drafts = state.pipeline.drafts
    total = len(drafts)
    pending = sum(1 for d in drafts if _draft_status(d.status) == "pending")
    approved = sum(
        1 for d in drafts
        if _draft_status(d.status) in ("approved", "auto_approved")
    )
    return {"total": total, "pending": pending, "approved": approved}


def build_snapshot_from_wm(
    session_token: str,
    user_id: str | None = None,
    campaigns: list | None = None,
) -> dict | None:
    """Build a snapshot dict from the World Model.

    Returns None when the World Model has no data for this session
    (first visit before any mutation), allowing callers to fall back
    to the legacy in-memory stores.

    Data sources (instrumented):
      - campaigns/drafts/leads → World Model
      - workspace_memory       → legacy (not yet event-sourced)
      - timeline               → legacy (not yet event-sourced)
      - active jobs            → legacy (job_manager)
    """
    global _DATA_SOURCE

    state = get_store().get_state(session_token)
    if not state or not state.pipeline.campaigns:
        _DATA_SOURCE = None
        return None

    campaign_list = _campaigns_from_wm(state, campaigns=campaigns)

    campaigns_ready = sum(
        1 for c in campaign_list
        if c["current_step"] == "sending"
    )
    campaigns_draft_review = sum(
        1 for c in campaign_list if c["current_step"] == "review"
    )

    draft_summary = _draft_summary_from_wm(state)

    total_leads = sum(c.lead_count for c in state.pipeline.campaigns)

    running_jobs = []
    recent_jobs = []
    if user_id:
        try:
            all_jobs = job_manager.list_recent_jobs(user_id)
            running_jobs = [
                j for j in all_jobs if j.get("status") in ("queued", "running")
            ]
            recent_jobs = [
                j for j in all_jobs if j.get("status") == "completed"
            ][:5]
        except Exception:
            pass

    memory = get_memory(session_token)
    timeline = get_events(session_token, limit=10)

    snapshot = {
        "campaigns": campaign_list,
        "campaign_count": len(campaign_list),
        "campaigns_ready": campaigns_ready,
        "campaigns_draft_review": campaigns_draft_review,
        "drafts": draft_summary,
        "total_leads": total_leads,
        "jobs": {
            "running": running_jobs,
            "recently_completed": recent_jobs,
        },
        "memory": memory,
        "timeline": timeline,
    }

    _DATA_SOURCE = "world_model"
    _log(
        "snapshot built from World Model "
        f"(campaigns={len(campaign_list)}, drafts={draft_summary['total']}, "
        f"memory/timeline/jobs from legacy)"
    )
    return snapshot
