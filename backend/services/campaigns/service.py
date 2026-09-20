"""Canonical read access to durable workspace campaigns."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from services.workspace.state import load_workspace_state
from services.world_model.activity_repository import get_activity_repository
from services.world_model import EventType as WMEventType, publish

log = logging.getLogger("loqi")


_status_projection_locks: dict[str, tuple[asyncio.Lock, int]] = {}
_status_projection_registry_lock = asyncio.Lock()


@asynccontextmanager
async def _status_projection_lock(campaign_id: str):
    """Serialize a campaign's commit and legacy status projections.

    The v2 RPC allocates revisions in commit order. Holding this scoped lock
    through both projections ensures the process-local compatibility log uses
    that same order without retaining slots after the final waiter exits.
    """
    async with _status_projection_registry_lock:
        lock, users = _status_projection_locks.get(campaign_id, (asyncio.Lock(), 0))
        _status_projection_locks[campaign_id] = (lock, users + 1)
    try:
        async with lock:
            yield
    finally:
        async with _status_projection_registry_lock:
            current_lock, users = _status_projection_locks.get(campaign_id, (lock, 1))
            if current_lock is lock and users <= 1:
                _status_projection_locks.pop(campaign_id, None)
            elif current_lock is lock:
                _status_projection_locks[campaign_id] = (lock, users - 1)


async def _persist_and_project_campaign_status(
    *,
    session_token: str,
    owner_id: str,
    campaign_id: str,
    workspace_id: str,
    updates: dict[str, Any],
    persist_update: Any,
) -> Any:
    """Keep the serialized status operation alive after request cancellation."""
    task = asyncio.create_task(_locked_persist_and_project_campaign_status(
        session_token=session_token,
        owner_id=owner_id,
        campaign_id=campaign_id,
        workspace_id=workspace_id,
        updates=updates,
        persist_update=persist_update,
    ))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # The child task owns the lock and must finish its canonical mutation
        # and ordered projections even when its HTTP waiter disconnects.
        def consume_background_result(completed: asyncio.Task) -> None:
            try:
                completed.result()
            except asyncio.CancelledError:
                return
            except Exception:
                log.exception("campaign_status_background_operation_failed campaign_id=%s", campaign_id)

        task.add_done_callback(consume_background_result)
        raise


async def _locked_persist_and_project_campaign_status(
    *,
    session_token: str,
    owner_id: str,
    campaign_id: str,
    workspace_id: str,
    updates: dict[str, Any],
    persist_update: Any,
) -> Any:
    """Commit one status update, then project only its locked transition."""
    async with _status_projection_lock(campaign_id):
        result = await persist_update(owner_id, campaign_id, updates, workspace_id=workspace_id)
        if result is None:
            return None
        revision = result.revision
        if not (revision.was_updated and revision.was_status_changed):
            return result

        campaign = revision.campaign
        legacy_payload = {
            "campaign_id": campaign.id,
            "status": campaign.status,
            "previous_status": revision.previous_status,
            "revision": campaign.version,
        }
        try:
            publish(session_token, WMEventType.CAMPAIGN_STATUS_CHANGED, legacy_payload, actor="user")
        except Exception as projection_error:
            log.warning(
                "campaign_status_projection_failed campaign_id=%s revision=%s error_type=%s",
                campaign.id,
                campaign.version,
                type(projection_error).__name__,
            )

        source_key = f"campaign:{campaign.id}:revision:{campaign.version}:status_changed"
        activity_payload = {
            "campaign_id": campaign.id,
            "status": campaign.status,
            "previous_status": revision.previous_status,
        }
        try:
            await asyncio.to_thread(
                get_activity_repository().append_campaign_status_changed,
                workspace_id=campaign.workspace_id,
                actor_user_id=owner_id,
                source_key=source_key,
                payload=activity_payload,
                occurred_at=campaign.updated_at.isoformat(),
            )
        except Exception as activity_error:
            log.warning(
                "workspace_activity_append_failed workspace_id=%s event_type=campaign_status_changed source_key=%s error_type=%s",
                campaign.workspace_id,
                source_key,
                type(activity_error).__name__,
            )
        return result

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


async def create_campaign_launch(
    *,
    workspace_id: str,
    campaign_id: str,
    actor_user_id: str,
):
    """Create the database-owned identity for one accepted send launch."""
    from services.persistence.launch import CampaignLaunchRepository

    return await CampaignLaunchRepository().create_for_workspace(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
    )


async def create_campaign(
    session_token: str,
    owner_id: str,
    workspace_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Create a durable campaign, selected lead links, and its strategy start."""
    from fastapi import HTTPException
    from services.discovery.service import get_discovery
    from services.workspace.state import (
        append_event,
        delete_campaign_row_awaited,
        load_campaign_state,
        persist_campaign_lead_awaited,
        persist_campaign_row,
    )
    from services.workspace.timeline import record_campaign_created

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

    source_key = f"campaign:{campaign['id']}:created"
    activity_payload = {
        "campaign_id": str(campaign["id"]),
        "status": str(campaign.get("status") or ""),
        "lead_count": int(campaign.get("lead_count") or 0),
    }
    try:
        await asyncio.to_thread(
            get_activity_repository().append_campaign_created,
            workspace_id=workspace_id,
            actor_user_id=owner_id,
            source_key=source_key,
            payload=activity_payload,
            occurred_at=str(campaign.get("created_at") or now),
        )
    except Exception as activity_error:
        # Activity is an optional durable Mission Control projection. A
        # confirmed canonical campaign must remain successful without it.
        log.warning(
            "workspace_activity_append_failed workspace_id=%s event_type=campaign_created source_key=%s error_type=%s",
            workspace_id,
            source_key,
            type(activity_error).__name__,
        )

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
    from services.workspace.state import (
        load_drafts_only,
        persist_campaign_update_with_revision_awaited,
    )
    from services.workspace.timeline import record_campaign_launched

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
            try:
                launch = await create_campaign_launch(
                    workspace_id=workspace_id,
                    campaign_id=campaign_id,
                    actor_user_id=owner_id,
                )
            except Exception as error:
                log.warning(
                    "campaign_launch_creation_failed workspace_id=%s campaign_id=%s error_type=%s",
                    workspace_id,
                    campaign_id,
                    type(error).__name__,
                )
                raise HTTPException(
                    status_code=503,
                    detail="Campaign launch could not be initialized",
                ) from error
            record_campaign_launched(session_token, target.get("name", ""))
            _feedback().on_campaign_launched(session_token, campaign_id)
            launch_result = await dispatch_campaign_sends(
                session_token, target, owner_id,
                workspace_id=workspace_id,
                launch_id=launch.id,
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
    if updates:
        if status is not None:
            persisted = await _persist_and_project_campaign_status(
                session_token=session_token,
                owner_id=owner_id,
                campaign_id=campaign_id,
                workspace_id=workspace_id,
                updates=updates,
                persist_update=persist_campaign_update_with_revision_awaited,
            )
        else:
            persisted = await persist_campaign_update_with_revision_awaited(
                owner_id, campaign_id, updates, workspace_id=workspace_id,
            )
        if persisted is None:
            raise HTTPException(status_code=503, detail="Campaign update could not be persisted")
        revisioned = persisted.revision
        canonical_campaign = revisioned.campaign
        if revisioned.was_updated:
            # The RPC return, rather than the pre-write dict mutation above,
            # is authoritative for the response's canonical campaign fields.
            target.update({
                "id": canonical_campaign.id,
                "name": canonical_campaign.name,
                "objective": canonical_campaign.objective,
                "status": canonical_campaign.status,
                "updated_at": canonical_campaign.updated_at.isoformat(),
            })
        if persisted.strategy_error is not None:
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
    from services.workspace.state import persist_campaign_lead_awaited, persist_campaign_update_awaited

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
    from services.workspace.state import persist_campaign_update_awaited

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
    from services.workspace.state import duplicate_campaign as duplicate_workspace_campaign

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
    from services.workspace.state import (
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
    from services.workspace.state import persist_campaign_update_awaited
    return await persist_campaign_update_awaited(owner_id, campaign_id, {"strategy_job": meta}, workspace_id=workspace_id)


async def load_strategy_job_meta(owner_id: str, campaign_id: str, *, workspace_id: str) -> dict | None:
    from services.workspace.state import load_campaign_state
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


def register_strategy_workflow() -> None:
    """Register the strategy worker before enqueue or restart recovery."""
    from services.job_engine.registry import WorkflowRegistration, get_registry
    registry = get_registry()
    if not registry.has("strategy"):
        registry.register(WorkflowRegistration(type="strategy", description="Campaign strategy generation", runner_fn=run_strategy_job))


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


async def run_strategy_job(job, _on_progress) -> dict[str, Any]:
    """Registered durable ``strategy`` workflow; payload is the recovery input."""
    payload = dict(job.payload or {})
    target, objective = dict(payload.get("target") or {}), str(payload.get("objective") or "")
    job_id, workspace_id = job.id, job.workspace_id
    try:
        await persist_strategy_job_meta(job.user_id, job.campaign_id, {"id": job_id, "status": "running", "started_at": job.created_at.isoformat(), "finished_at": None, "error": None}, workspace_id=workspace_id)
        context = await build_strategy_context(target)
        from services.knowledge.context_adapter import retrieve_knowledge_context
        query = " ".join(str(item).strip() for item in (objective, target.get("search_query"), target.get("name")) if str(item or "").strip())
        context["knowledge_context"] = (await retrieve_knowledge_context(job.user_id, query=query, categories=["company", "icp", "messaging", "sales_offer"], limit=8)).to_dict()
        from services.intelligence.ai import OpenAIError, generate_campaign_strategy
        try:
            strategy = await asyncio.to_thread(generate_campaign_strategy, objective, context)
        except OpenAIError:
            from services.intelligence.ai import _fallback_playbook
            strategy = _fallback_playbook(objective, context)
        strategy.update({"objective": objective, "generated_at": datetime.now(timezone.utc).isoformat()})
        from services.workspace.state import persist_campaign_update_awaited
        if not await persist_campaign_update_awaited(job.user_id, job.campaign_id, {"strategy": strategy}, workspace_id=workspace_id):
            raise RuntimeError("Strategy could not be persisted")
        await persist_strategy_job_meta(job.user_id, job.campaign_id, {"id": job_id, "status": "completed", "started_at": job.created_at.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(), "error": None}, workspace_id=workspace_id)
        return {"ok": True, "result": {"strategy": strategy}}
    except Exception as error:
        try:
            await persist_strategy_job_meta(job.user_id, job.campaign_id, {"id": job_id, "status": "failed", "started_at": job.created_at.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(), "error": str(error)[:200]}, workspace_id=workspace_id)
        except Exception:
            pass
        return {"ok": False, "error": str(error)}


async def enqueue_strategy_job(session_token: str, owner_id: str, campaign_id: str, objective: str, target: dict[str, Any], *, workspace_id: str = "") -> tuple[str, str]:
    from fastapi import HTTPException
    from services.job_engine import Job, job_manager
    register_strategy_workflow()
    active = await asyncio.to_thread(job_manager._storage.list_active_jobs_by_type, "strategy")
    for current in active:
        if current.campaign_id == campaign_id and current.workspace_id == workspace_id:
            return current.id, current.status.value
    job = Job(user_id=owner_id, type="strategy", workspace_id=workspace_id, campaign_id=campaign_id, payload={"objective": objective, "target": target})
    if (await persist_strategy_job_meta(owner_id, campaign_id, {"id": job.id, "status": "queued", "started_at": job.created_at.isoformat(), "finished_at": None, "error": None}, workspace_id=workspace_id)) is False:
        raise HTTPException(status_code=503, detail="Strategy generation could not be persisted")
    created = await job_manager.create_job(job)
    if not created:
        raise HTTPException(status_code=503, detail="Strategy generation could not be scheduled")
    return job.id, "queued"


async def start_strategy_generation(
    session_token: str,
    owner_id: str,
    workspace_id: str,
    campaign_id: str,
    *,
    force: bool,
) -> dict[str, Any]:
    """Reuse or queue one durable strategy job for an authorized campaign."""
    from fastapi import HTTPException

    campaigns = await asyncio.to_thread(load_campaigns, owner_id, workspace_id=workspace_id)
    target = next((campaign for campaign in campaigns if campaign.get("id") == campaign_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Campaign not found")
    objective = str(target.get("objective") or "").strip()
    if not objective:
        raise HTTPException(status_code=400, detail="Campaign objective is required")
    if not (target.get("leads") or []):
        raise HTTPException(status_code=400, detail="Research prospects before generating a strategy")

    current_strategy = target.get("strategy") if isinstance(target.get("strategy"), dict) else None
    if current_strategy and not force:
        stored_objective = str(
            current_strategy.get("objective")
            or current_strategy.get("campaign_objective")
            or ""
        ).strip()
        if stored_objective == objective:
            return {
                "ok": True,
                "job_id": None,
                "status": "completed",
                "reused": True,
                "strategy": current_strategy,
            }

    job_id, status = await enqueue_strategy_job(
        session_token,
        owner_id,
        campaign_id,
        objective,
        target,
        workspace_id=workspace_id,
    )
    return {"ok": True, "job_id": job_id, "status": status}


async def strategy_job_status(
    owner_id: str,
    workspace_id: str,
    campaign_id: str,
    job_id: str,
) -> dict[str, Any] | None:
    """Return a strategy job only when all durable ownership fields match."""
    from services.job_engine import job_manager

    job = await asyncio.to_thread(job_manager.get_job, job_id)
    if (
        not job
        or job.get("type") != "strategy"
        or job.get("campaign_id") != campaign_id
        or job.get("workspace_id") != workspace_id
        or job.get("user_id") != owner_id
    ):
        return None
    return {
        "job_id": job_id,
        "status": job.get("status"),
        "strategy": (job.get("result") or {}).get("strategy"),
        "error": job.get("error_message"),
    }


async def maybe_auto_strategy(session_token: str, owner_id: str, campaign_id: str, objective: str, target: dict[str, Any], *, workspace_id: str) -> str | None:
    if not objective or not campaign_id or not str(target.get("discovery_id") or "").strip() or (isinstance(target.get("strategy"), dict) and target.get("strategy")) or not target.get("leads"):
        return None
    job_id, _ = await enqueue_strategy_job(session_token, owner_id, campaign_id, objective, target, workspace_id=workspace_id)
    log.info("[campaign_strategy] auto-generated from discovery for campaign %s (job %s)", campaign_id, job_id)
    return job_id


async def reconcile_stale_strategy_jobs() -> int:
    """Resume durable queued/running strategy jobs after process restart."""
    from services.job_engine import job_manager
    register_strategy_workflow()
    jobs = await asyncio.to_thread(job_manager._storage.list_active_jobs_by_type, "strategy")
    for job in jobs:
        job_manager.resume_job(job)
    return len(jobs)
