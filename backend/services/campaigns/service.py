"""Canonical read access to durable workspace campaigns."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from services.workspace_state import load_workspace_state
from services.world_model import EventType as WMEventType, publish

log = logging.getLogger("loqi")

# Temporary legacy polling projection. Lifecycle metadata remains durable on
# the campaign record; R5-B decides its durable replacement.
STRATEGY_JOBS: dict[str, dict[str, Any]] = {}
strategy_job_tasks: dict[str, asyncio.Task] = {}

VALID_CAMPAIGN_STATUSES = {
    "planning", "active", "paused", "completed",
    "archived", "cancelled", "failed", "deleted",
}


def load_campaigns(
    user_id: str,
    *,
    workspace_id: str = "",
    include_details: bool = True,
) -> list[dict[str, Any]]:
    """Return the caller's durable campaigns for one workspace."""
    state = load_workspace_state(
        user_id,
        workspace_id=workspace_id,
        include_details=include_details,
    )
    return state["campaigns"]


def _feedback():
    """Return the shared learning interpreter used for campaign feedback."""
    from services.learning.behavior_tracker import get_tracker
    from services.learning.feedback_interpreter import FeedbackInterpreter

    return FeedbackInterpreter(get_tracker())


async def create_campaign(
    session_token: str,
    owner_id: str,
    workspace_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Create a durable campaign, selected lead links, and its strategy start."""
    from fastapi import HTTPException
    from services.discovery.service import get_discovery
    from services.workspace_state import (
        append_event,
        delete_campaign_row_awaited,
        load_campaign_state,
        persist_campaign_lead_awaited,
        persist_campaign_row,
    )
    from services.workspace_timeline import record_campaign_created

    discovery_id = str(payload.get("discovery_id") or "")
    if discovery_id:
        discovery = await asyncio.to_thread(get_discovery, discovery_id, workspace_id)
        if discovery is None:
            raise HTTPException(status_code=404, detail="Discovery not found")

    now = datetime.now(timezone.utc).isoformat()
    leads = list(payload.get("leads") or [])
    campaign = {
        "id": str(uuid.uuid4()),
        "name": payload["name"],
        "objective": payload.get("objective") or "",
        "search_query": payload.get("search_query") or "",
        "discovery_id": discovery_id,
        "lead_count": payload.get("lead_count") or len(leads),
        "leads": leads,
        "status": payload.get("status") or "planning",
        "strategy": payload.get("strategy"),
        "created_at": now,
        "updated_at": now,
    }
    if not await persist_campaign_row(owner_id, campaign, workspace_id=workspace_id):
        raise HTTPException(status_code=503, detail="Campaign could not be persisted")

    async def persist_selected_lead(lead: dict[str, Any]) -> bool:
        return await persist_campaign_lead_awaited(
            owner_id, campaign["id"], lead, workspace_id=workspace_id,
        )

    lead_results = await asyncio.gather(*(persist_selected_lead(lead) for lead in leads))
    if any(not persisted for persisted in lead_results):
        compensated = await delete_campaign_row_awaited(
            owner_id, campaign["id"], workspace_id=workspace_id,
        )
        detail = (
            "Campaign lead attachment failed; creation was rolled back"
            if compensated
            else "Campaign lead attachment failed and rollback could not be confirmed"
        )
        raise HTTPException(status_code=503, detail=detail)

    canonical_campaign = await asyncio.to_thread(
        load_campaign_state, owner_id, campaign["id"], workspace_id=workspace_id,
    )
    if canonical_campaign is None or int(canonical_campaign.get("lead_count") or 0) != len(leads):
        await delete_campaign_row_awaited(owner_id, campaign["id"], workspace_id=workspace_id)
        raise HTTPException(
            status_code=503,
            detail="Campaign links could not be verified; creation was rolled back",
        )
    campaign = canonical_campaign

    event_task = asyncio.create_task(asyncio.to_thread(
        append_event, owner_id, "campaign.created", {"campaign": campaign},
    ))

    def report_event_failure(task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("[campaign] compatibility event append failed campaign=%s", campaign["id"])

    event_task.add_done_callback(report_event_failure)
    record_campaign_created(session_token, payload["name"])
    publish(session_token, WMEventType.CAMPAIGN_CREATED, {
        "id": campaign["id"], "name": campaign["name"],
        "status": campaign["status"], "lead_count": campaign["lead_count"],
        "search_query": campaign["search_query"],
    }, actor="user")
    _feedback().on_campaign_created(session_token, campaign["id"])

    strategy_task = asyncio.create_task(maybe_auto_strategy(
        session_token, owner_id, campaign["id"],
        str(payload.get("objective") or "").strip(), campaign,
        workspace_id=workspace_id,
    ))

    def report_strategy_failure(task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            log.exception("[campaign_strategy] auto-start failed campaign=%s", campaign["id"])

    strategy_task.add_done_callback(report_strategy_failure)
    return {"ok": True, "campaign": campaign}


async def update_campaign(
    session_token: str,
    owner_id: str,
    workspace_id: str,
    campaign_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist one selected-workspace campaign update and optional launch."""
    from fastapi import HTTPException
    from services.outbound.service import dispatch_campaign_sends
    from services.workspace_state import load_drafts_only, persist_campaign_update_awaited
    from services.workspace_timeline import record_campaign_launched

    target = next(
        (campaign for campaign in load_campaigns(owner_id, workspace_id=workspace_id)
         if campaign.get("id") == campaign_id),
        None,
    )
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")
    updates: dict[str, Any] = {}
    for field in ("name", "objective", "strategy"):
        if payload.get(field) is not None:
            target[field] = payload[field]
            updates[field] = payload[field]
    status = payload.get("status")
    if status is not None:
        if status not in VALID_CAMPAIGN_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid campaign status: {status}")
        old_status = target.get("status", "")
        target["status"] = status
        updates["status"] = status
        publish(session_token, WMEventType.CAMPAIGN_STATUS_CHANGED, {
            "campaign_id": campaign_id, "status": status, "previous_status": old_status,
        }, actor="user")
        if status == "completed" and old_status != "completed":
            approved = [
                draft for draft in load_drafts_only(owner_id, workspace_id=workspace_id)
                if draft.get("campaign_id") == campaign_id and draft.get("status") == "approved"
            ]
            if not approved:
                raise HTTPException(
                    status_code=400,
                    detail="No approved drafts — approve at least one draft before launching",
                )
            record_campaign_launched(session_token, target.get("name", ""))
            _feedback().on_campaign_launched(session_token, campaign_id)
            launch_result = await dispatch_campaign_sends(
                session_token, target, owner_id, workspace_id=workspace_id,
            )
            target["launch_result"] = {
                key: launch_result[key]
                for key in ("total", "sent", "failed", "error") if key in launch_result
            }
            if not launch_result.get("ok") and launch_result.get("error"):
                raise HTTPException(status_code=400, detail=launch_result["error"])
    elif payload.get("name") is not None:
        publish(session_token, WMEventType.CAMPAIGN_UPDATED, {
            "campaign_id": campaign_id, "name": payload["name"],
        }, actor="user")
    target["updated_at"] = datetime.now(timezone.utc).isoformat()
    if updates and not await persist_campaign_update_awaited(
        owner_id, campaign_id, updates, workspace_id=workspace_id,
    ):
        raise HTTPException(status_code=503, detail="Campaign update could not be persisted")
    return {"ok": True, "campaign": target}


async def add_campaign_lead(
    session_token: str,
    owner_id: str,
    workspace_id: str,
    campaign_id: str,
    lead: dict[str, Any],
    discovery_id: str = "",
) -> dict[str, Any]:
    """Add one unique lead to a campaign through canonical lead links."""
    from fastapi import HTTPException
    from services.workspace_state import persist_campaign_lead_awaited, persist_campaign_update_awaited

    target = next(
        (campaign for campaign in load_campaigns(owner_id, workspace_id=workspace_id)
         if campaign.get("id") == campaign_id),
        None,
    )
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")
    lead = dict(lead)
    candidate_email = str(lead.get("email") or "").strip().lower()
    lead_id = str(lead.get("id") or lead.get("linkedin_url") or candidate_email or uuid.uuid4())
    lead["id"] = lead_id
    leads = target.setdefault("leads", [])
    for existing in leads:
        if not isinstance(existing, dict):
            continue
        if existing.get("id") and str(existing["id"]) == lead_id:
            return {"ok": True, "campaign": target, "added": False}
        if candidate_email and str(existing.get("email") or "").strip().lower() == candidate_email:
            return {"ok": True, "campaign": target, "added": False}
    leads.append(lead)
    target["lead_count"] = len(leads)
    target["updated_at"] = datetime.now(timezone.utc).isoformat()
    if not await persist_campaign_lead_awaited(owner_id, campaign_id, lead, workspace_id=workspace_id):
        raise HTTPException(status_code=503, detail="Lead could not be persisted to the campaign")
    if discovery_id and str(target.get("discovery_id") or "") != discovery_id:
        target["discovery_id"] = discovery_id
        await persist_campaign_update_awaited(
            owner_id, campaign_id, {"discovery_id": discovery_id}, workspace_id=workspace_id,
        )
    if discovery_id:
        await maybe_auto_strategy(
            session_token, owner_id, campaign_id, str(target.get("objective") or "").strip(),
            target, workspace_id=workspace_id,
        )
    publish(session_token, WMEventType.LEAD_DISCOVERED, {
        "id": lead_id, "name": lead.get("name", lead.get("full_name", "")),
        "company": lead.get("company", ""), "title": lead.get("title", lead.get("job_title", "")),
        "campaign_id": campaign_id,
    }, actor="user")
    publish(session_token, WMEventType.CAMPAIGN_UPDATED, {
        "campaign_id": campaign_id, "lead_count": target["lead_count"],
    }, actor="user")
    publish(session_token, WMEventType.LEAD_SELECTED, {
        "lead_id": lead_id, "campaign_id": campaign_id,
        "lead_name": lead.get("name", lead.get("full_name", "")),
    }, actor="user")
    return {"ok": True, "campaign": target, "added": True}


async def delete_campaign(
    session_token: str, owner_id: str, workspace_id: str, campaign_id: str,
) -> dict[str, Any]:
    """Soft-delete one campaign after a scoped durable lookup."""
    from fastapi import HTTPException
    from services.persistence.launch import CampaignRepository
    from services.workspace_state import persist_campaign_update_awaited

    entity = await CampaignRepository().get_for_workspace(campaign_id, workspace_id)
    if entity is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    target = {
        "id": entity.id, "name": entity.name, "objective": entity.objective,
        "status": "deleted", "lead_count": 0,
        "created_at": entity.created_at.isoformat() if entity.created_at else "",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if not await persist_campaign_update_awaited(
        owner_id, campaign_id, {"status": "deleted"}, workspace_id=workspace_id,
    ):
        raise HTTPException(status_code=503, detail="Campaign delete could not be persisted")
    publish(session_token, WMEventType.CAMPAIGN_DELETED, {
        "campaign_id": campaign_id, "name": target["name"],
    }, actor="user")
    return {"ok": True, "campaign": target}


async def duplicate_campaign(
    session_token: str, owner_id: str, workspace_id: str, campaign_id: str,
) -> dict[str, Any]:
    """Duplicate canonical campaign data without runtime or outbound state."""
    from fastapi import HTTPException
    from services.workspace_state import duplicate_campaign as duplicate_workspace_campaign

    copy = await duplicate_workspace_campaign(owner_id, campaign_id, workspace_id=workspace_id)
    if copy is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    publish(session_token, WMEventType.CAMPAIGN_DUPLICATED, {
        "campaign_id": campaign_id, "copy_id": copy.get("id"), "name": copy.get("name"),
    }, actor="user")
    return {"ok": True, "campaign": copy}


async def attach_discovery(
    session_token: str,
    owner_id: str,
    workspace_id: str,
    campaign_id: str,
    discovery_id: str,
) -> dict[str, Any]:
    """Attach Discovery leads to a campaign with compensated durable writes."""
    from fastapi import HTTPException
    from services.discovery.service import get_discovery
    from services.workspace_state import (
        load_campaign_state,
        persist_campaign_lead_id_awaited,
        persist_campaign_update_awaited,
        remove_campaign_lead_links_awaited,
    )

    target = next(
        (campaign for campaign in load_campaigns(owner_id, workspace_id=workspace_id)
         if campaign.get("id") == campaign_id),
        None,
    )
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")
    discovery = await asyncio.to_thread(get_discovery, discovery_id, workspace_id)
    if not discovery:
        raise HTTPException(status_code=404, detail="Discovery not found")
    attached_ids: list[str] = []
    requested = 0
    for link in discovery.get("discovery_leads") or []:
        workspace_lead = link.get("workspace_lead") if isinstance(link, dict) else None
        if not isinstance(workspace_lead, dict) or not workspace_lead.get("id"):
            continue
        requested += 1
        lead = {
            "id": workspace_lead.get("id"), "email": workspace_lead.get("email"),
            "first_name": workspace_lead.get("first_name", ""),
            "last_name": workspace_lead.get("last_name", ""),
            "title": workspace_lead.get("title", ""),
            "company": ((workspace_lead.get("company") or {}).get("name", "")
                        if isinstance(workspace_lead.get("company"), dict) else ""),
            "source": "discovery",
        }
        canonical_id = await persist_campaign_lead_id_awaited(
            owner_id, campaign_id, lead, workspace_id=workspace_id,
        )
        if not canonical_id:
            compensated = await remove_campaign_lead_links_awaited(
                owner_id, campaign_id, attached_ids, workspace_id=workspace_id,
            )
            detail = (
                "Campaign attachment failed and was rolled back" if compensated
                else "Campaign attachment failed and rollback could not be confirmed"
            )
            raise HTTPException(status_code=503, detail=detail)
        attached_ids.append(str(canonical_id))
    if requested != len(attached_ids):
        raise HTTPException(status_code=503, detail="Campaign attachment could not be verified")
    if attached_ids:
        target["updated_at"] = datetime.now(timezone.utc).isoformat()
        if str(target.get("discovery_id") or "") != discovery_id:
            target["discovery_id"] = discovery_id
            await persist_campaign_update_awaited(
                owner_id, campaign_id, {"discovery_id": discovery_id}, workspace_id=workspace_id,
            )
        await maybe_auto_strategy(
            session_token, owner_id, campaign_id, str(target.get("objective") or "").strip(),
            target, workspace_id=workspace_id,
        )
        publish(session_token, WMEventType.CAMPAIGN_UPDATED, {
            "campaign_id": campaign_id,
            "lead_count": (target.get("lead_count") or 0) + len(attached_ids),
            "source_discovery_id": discovery_id,
        }, actor="user")
    campaign = await asyncio.to_thread(
        load_campaign_state, owner_id, campaign_id, workspace_id=workspace_id,
    )
    if campaign is None:
        raise HTTPException(status_code=503, detail="Campaign could not be reloaded after attachment")
    return {"ok": True, "campaign": campaign, "added": len(attached_ids)}


async def persist_strategy_job_meta(owner_id: str, campaign_id: str, meta: dict, *, workspace_id: str) -> bool:
    from services.workspace_state import persist_campaign_update_awaited
    return await persist_campaign_update_awaited(owner_id, campaign_id, {"strategy_job": meta}, workspace_id=workspace_id)


async def load_strategy_job_meta(owner_id: str, campaign_id: str, *, workspace_id: str) -> dict | None:
    from services.workspace_state import load_campaign_state
    try:
        state = await asyncio.to_thread(load_campaign_state, owner_id, campaign_id, workspace_id=workspace_id)
    except Exception:
        return None
    return state.get("strategy_job") if isinstance(state, dict) and isinstance(state.get("strategy_job"), dict) else None


def reconcile_strategy_meta(meta: dict | None) -> tuple[str | None, str | None]:
    if not meta:
        return None, None
    status = str(meta.get("status") or "")
    if status in {"queued", "running"}:
        return "failed", "Generation was interrupted by a server restart — please run it again."
    return ("completed", None) if status == "completed" else ("failed", str(meta.get("error") or "unknown error"))


async def build_strategy_context(target: dict[str, Any]) -> dict[str, Any]:
    context: dict[str, Any] = {}
    leads = [lead for lead in target.get("leads") or [] if isinstance(lead, dict)]
    if leads:
        context["leads"] = [{"name": lead.get("name") or f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip(), "title": lead.get("title", ""), "company": lead.get("company", ""), "domain": lead.get("domain", "")} for lead in leads][:8]
        def top_counts(values: list[str], limit: int) -> dict[str, int]:
            counts: dict[str, int] = {}
            for value in values:
                value = str(value or "").strip()
                if value:
                    counts[value] = counts.get(value, 0) + 1
            return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit])
        companies, industries, locations, sizes = [], [], [], []
        for lead in leads:
            company = str(lead.get("company") or "").strip()
            if company and company.lower() not in {item.lower() for item in companies}:
                companies.append(company)
            industries.append(str(lead.get("industry") or ""))
            location = str(lead.get("city") or "").strip() or str(lead.get("country") or "").strip()
            if location:
                locations.append(location)
            employees = lead.get("employee_count")
            if isinstance(employees, (int, float)) and employees > 0:
                sizes.append("1-50 employees" if employees < 50 else "51-200 employees" if employees < 200 else "201-1000 employees" if employees < 1000 else "1,000+ employees")
        context["audience_profile"] = {"lead_count": len(leads), "companies": companies[:12], "industry_distribution": top_counts(industries, 6), "location_distribution": top_counts(locations, 6), "size_distribution": top_counts(sizes, 4)}
    discovery_id = str(target.get("discovery_id") or "").strip()
    if discovery_id:
        try:
            from services.discovery.service import get_discovery
            discovery = await asyncio.to_thread(get_discovery, discovery_id)
        except Exception:
            discovery = None
        metadata = discovery.get("metadata") if isinstance(discovery, dict) else None
        plan = metadata.get("plan") if isinstance(metadata, dict) else None
        if isinstance(plan, dict) and plan.get("offering"):
            context["discovery_plan"] = plan
        discovered = []
        for item in (discovery.get("discovery_companies") or []) if isinstance(discovery, dict) else []:
            company = item.get("company") if isinstance(item, dict) else None
            if isinstance(company, dict):
                discovered.append({"name": company.get("name") or "", "industry": company.get("industry") or "", "city": company.get("city") or "", "country": company.get("country") or "", "employees": company.get("employee_count") or 0, "description": company.get("description") or ""})
        if discovered:
            industries = [item["industry"] for item in discovered if item["industry"]]
            locations = [item["city"] or item["country"] for item in discovered if item.get("city") or item.get("country")]
            sizes = []
            for item in discovered:
                employees = item.get("employees")
                if isinstance(employees, (int, float)) and employees > 0:
                    sizes.append("1-50 employees" if employees < 50 else "51-200 employees" if employees < 200 else "201-1000 employees" if employees < 1000 else "1,000+ employees")
            context["market_research"] = {"companies": discovered[:10], "industry_distribution": top_counts(industries, 6), "location_distribution": top_counts(locations, 6), "size_distribution": top_counts(sizes, 4)}
    return context


async def run_strategy_job(session_token: str, job: dict[str, Any], target: dict[str, Any], objective: str) -> None:
    job_id, workspace_id = str(job.get("id") or ""), str(job.get("workspace_id") or "")
    job["status"] = "running"
    try:
        await persist_strategy_job_meta(job["owner_id"], job["campaign_id"], {"id": job_id, "status": "running", "started_at": job.get("started_at"), "finished_at": None, "error": None}, workspace_id=workspace_id)
        context = await build_strategy_context(target)
        from services.knowledge.context_adapter import retrieve_knowledge_context
        query = " ".join(str(item).strip() for item in (objective, target.get("search_query"), target.get("name")) if str(item or "").strip())
        context["knowledge_context"] = (await retrieve_knowledge_context(job["owner_id"], query=query, categories=["company", "icp", "messaging", "sales_offer"], limit=8)).to_dict()
        from services.ai import OpenAIError, generate_campaign_strategy
        try:
            strategy = await asyncio.to_thread(generate_campaign_strategy, objective, context)
        except OpenAIError:
            from services.ai import _fallback_playbook
            strategy = _fallback_playbook(objective, context)
        strategy.update({"objective": objective, "generated_at": datetime.now(timezone.utc).isoformat()})
        from services.workspace_state import persist_campaign_update_awaited
        if not await persist_campaign_update_awaited(job["owner_id"], job["campaign_id"], {"strategy": strategy}, workspace_id=workspace_id):
            raise RuntimeError("Strategy could not be persisted")
        job.update({"strategy": strategy, "status": "completed", "finished_at": datetime.now(timezone.utc).isoformat()})
        await persist_strategy_job_meta(job["owner_id"], job["campaign_id"], {"id": job_id, "status": "completed", "started_at": job.get("started_at"), "finished_at": job["finished_at"], "error": None}, workspace_id=workspace_id)
        publish(session_token, WMEventType.CAMPAIGN_UPDATED, {"campaign_id": job["campaign_id"], "objective": objective, "strategy": strategy}, actor="loqi")
    except Exception as error:
        job.update({"error": str(error), "status": "failed", "finished_at": datetime.now(timezone.utc).isoformat()})
        try:
            await persist_strategy_job_meta(job["owner_id"], job["campaign_id"], {"id": job_id, "status": "failed", "started_at": job.get("started_at"), "finished_at": job["finished_at"], "error": str(error)[:200]}, workspace_id=workspace_id)
        except Exception:
            pass


async def enqueue_strategy_job(session_token: str, owner_id: str, campaign_id: str, objective: str, target: dict[str, Any], *, workspace_id: str = "") -> tuple[str, str]:
    for current in STRATEGY_JOBS.values():
        if current.get("campaign_id") == campaign_id and current.get("workspace_id") == workspace_id and current.get("status") in {"queued", "running"}:
            return current["id"], current["status"]
    job_id = str(uuid.uuid4())
    job = {"id": job_id, "campaign_id": campaign_id, "owner_id": owner_id, "workspace_id": workspace_id, "status": "queued", "strategy": None, "error": None, "started_at": datetime.now(timezone.utc).isoformat(), "finished_at": None}
    STRATEGY_JOBS[job_id] = job
    if (await persist_strategy_job_meta(owner_id, campaign_id, {"id": job_id, "status": "queued", "started_at": job["started_at"], "finished_at": None, "error": None}, workspace_id=workspace_id)) is False:
        STRATEGY_JOBS.pop(job_id, None)
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Strategy generation could not be persisted")
    task = asyncio.create_task(run_strategy_job(session_token, job, target, objective))
    strategy_job_tasks[job_id] = task
    task.add_done_callback(lambda _: strategy_job_tasks.pop(job_id, None))
    return job_id, "queued"


async def maybe_auto_strategy(session_token: str, owner_id: str, campaign_id: str, objective: str, target: dict[str, Any], *, workspace_id: str) -> str | None:
    if not objective or not campaign_id or not str(target.get("discovery_id") or "").strip() or (isinstance(target.get("strategy"), dict) and target.get("strategy")) or not target.get("leads"):
        return None
    job_id, _ = await enqueue_strategy_job(session_token, owner_id, campaign_id, objective, target, workspace_id=workspace_id)
    log.info("[campaign_strategy] auto-generated from discovery for campaign %s (job %s)", campaign_id, job_id)
    return job_id


def reconcile_stale_strategy_jobs() -> int:
    from services.supabase import get_supabase_client
    client = get_supabase_client()
    if client is None:
        return 0
    try: rows = client.table("campaigns").select("id, settings").execute().data or []
    except Exception as error:
        log.warning("[recovery] stale strategy scan failed: %s", error)
        return 0
    recovered, now = 0, datetime.now(timezone.utc).isoformat()
    for row in rows:
        settings = row.get("settings") or {}
        if isinstance(settings, str):
            try: settings = json.loads(settings)
            except (TypeError, ValueError): settings = {}
        meta = settings.get("strategy_job") if isinstance(settings, dict) else None
        if not isinstance(meta, dict) or meta.get("status") not in {"queued", "running"}: continue
        try:
            client.table("campaigns").update({"settings": {**settings, "strategy_job": {**meta, "status": "failed", "finished_at": now, "error": "Strategy generation was interrupted by a server restart — please run it again."}}, "updated_at": now}).eq("id", row["id"]).execute(); recovered += 1
        except Exception as error: log.warning("[recovery] stale strategy reconcile failed campaign=%s error=%s", row.get("id"), error)
    return recovered
