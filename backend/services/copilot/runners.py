"""Workspace-scoped Copilot runner adapters over canonical domain services.

The ordered R7 migration moves runner bodies here from ``main.py``. This
module owns execution adapters only; contracts and orchestrator state remain
in their existing modules.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

import services.campaigns.service as campaign_service
import services.drafts.service as draft_service
import services.outbound.service as outbound_service
from services.events_bus import publish_draft_event
from services.outbound.outbound_executor import executor as outbound_executor
from services.rewrite_engine import execute_rewrite


def _discovery_query_from_search_context(search_context: dict) -> str:
    industries = [str(value).strip() for value in search_context.get("industry", []) if str(value).strip()]
    roles = [str(value).strip().replace("_", " ") for value in search_context.get("decision_makers", []) if str(value).strip()]
    locations = [str(value).strip() for value in search_context.get("location", []) if str(value).strip()]
    parts = (["industries: " + ", ".join(industries)] if industries else []) + (["decision makers: " + ", ".join(roles)] if roles else []) + (["locations: " + ", ".join(locations)] if locations else [])
    if isinstance(search_context.get("quantity"), int) and search_context["quantity"] > 0:
        parts.append(f"quantity: {search_context['quantity']}")
    return "Find leads matching " + "; ".join(parts) if parts else "Find leads"


def _discovery_title_from_search_context(search_context: dict) -> str:
    def values(key: str) -> list[str]:
        raw = search_context.get(key, [])
        return [str(value).strip() for value in ([raw] if isinstance(raw, str) else raw) if str(value).strip()]
    def natural(items: list[str]) -> str:
        rendered = [item.replace("_", " ").strip() for item in items]
        return (rendered[0][0].upper() + rendered[0][1:]) if len(rendered) == 1 else (", ".join(rendered[:-1]) + " and " + rendered[-1] if rendered else "")
    industries, roles, locations = values("industry"), values("decision_makers"), values("location")
    if roles:
        normalized = []
        for role in roles:
            words = role.replace("_", " ").split()
            if words and words[-1].lower() not in {"s", "ss"}:
                words[-1] += "s"
            normalized.append(" ".join(words))
        label = natural(normalized)
    elif industries:
        label = f"{natural([item[:-1] if item.lower().endswith('s') and not item.lower().endswith('ss') else item for item in industries])} leads"
    else:
        label = "Leads"
    quantity = search_context.get("quantity")
    if isinstance(quantity, int) and quantity > 0:
        label = f"{quantity} {label[0].lower() + label[1:]}"
    return label + (f" in {natural(locations)}" if locations else "")


async def run_discovery(user_id: str, search_context: dict, session_token: str, *, workspace_id: str) -> dict:
    from services.discovery.service import create_search_run
    return await create_search_run(user_id, _discovery_query_from_search_context(search_context), session_token, display_title=_discovery_title_from_search_context(search_context), workspace_id=workspace_id)


async def run_campaign(
    tool_name: str,
    user_id: str,
    workspace_id: str,
    session_token: str,
    decision: dict[str, Any],
) -> dict[str, Any]:
    """Campaign tool adapter over the existing workspace and job services."""
    from services.workspace_state import (
        append_event,
        load_campaign_state,
        load_workspace_state,
        persist_campaign_lead_id_awaited,
        persist_campaign_row,
        persist_campaign_update_awaited,
    )
    from services.workspace_snapshot import enrich_campaigns

    page_context = decision.get("page_context") or {}
    campaign_id = str(
        decision.get("campaign_id")
        or page_context.get("campaign_id")
        or page_context.get("active_campaign_id")
        or ""
    ).strip()

    def enriched(campaigns: list[dict[str, Any]], drafts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return enrich_campaigns(campaigns, drafts)

    if tool_name == "campaign.list":
        state = await asyncio.to_thread(load_workspace_state, user_id, False, workspace_id)
        campaigns = state.get("campaigns") or []
        drafts = state.get("drafts") or []
        return {"ok": True, "status": "completed", "tool": tool_name, "result": {"campaigns": enriched(campaigns, drafts)}}

    if not campaign_id and tool_name != "campaign.create":
        return {"ok": False, "status": "unavailable", "tool": tool_name, "reason": "No active campaign is selected."}

    if tool_name in {"campaign.read", "campaign.drafts"}:
        campaign = await asyncio.to_thread(load_campaign_state, user_id, campaign_id, workspace_id=workspace_id)
        if not campaign:
            return {"ok": False, "status": "failed", "tool": tool_name, "reason": "The selected campaign is not available in this workspace."}
        drafts = await asyncio.to_thread(
            lambda: [d for d in load_workspace_state(user_id, False, workspace_id).get("drafts", []) if d.get("campaign_id") == campaign_id]
        )
        result = {"campaign": enriched([campaign], drafts)[0], "drafts": drafts}
        if tool_name == "campaign.drafts":
            result = {"campaign_id": campaign_id, "drafts": drafts}
        return {"ok": True, "status": "completed", "tool": tool_name, "result": result}

    if tool_name == "campaign.create":
        campaign_input = decision.get("campaign") or {}
        if not isinstance(campaign_input, dict):
            campaign_input = {}
        active_search = decision.get("active_search") or {}
        page_context = decision.get("page_context") or {}
        discovery_id = str(
            campaign_input.get("discovery_id")
            or active_search.get("discovery_id")
            or page_context.get("discovery_id")
            or page_context.get("active_discovery_id")
            or ""
        ).strip()
        leads: list[dict[str, Any]] = []
        if discovery_id:
            from services.copilot_tools import _requested_leads
            from services.discovery.service import get_discovery

            discovery = await asyncio.to_thread(get_discovery, discovery_id, workspace_id)
            if discovery:
                leads = _requested_leads(discovery, decision)
        now = datetime.now(timezone.utc).isoformat()
        campaign = {
            "id": str(uuid.uuid4()),
            "name": str(campaign_input.get("name") or "New campaign").strip(),
            "objective": str(campaign_input.get("objective") or "").strip(),
            "search_query": str(campaign_input.get("search_query") or "").strip(),
            "discovery_id": discovery_id,
            "lead_count": len(leads),
            "leads": leads,
            "status": "planning",
            "strategy": campaign_input.get("strategy") if isinstance(campaign_input.get("strategy"), dict) else None,
            "created_at": now,
            "updated_at": now,
        }
        if not await persist_campaign_row(user_id, campaign, workspace_id=workspace_id):
            return {"ok": False, "status": "failed", "tool": tool_name, "reason": "Campaign could not be persisted."}
        attached_lead_ids: list[str] = []
        for lead in leads:
            lead_id = await persist_campaign_lead_id_awaited(
                user_id, campaign["id"], lead, workspace_id=workspace_id,
            )
            if not lead_id:
                return {
                    "ok": False,
                    "status": "failed",
                    "tool": tool_name,
                    "reason": "Campaign was created but a lead could not be persisted.",
                    "result": {
                        "campaign_id": campaign["id"],
                        "attached_lead_ids": attached_lead_ids,
                    },
                }
            attached_lead_ids.append(str(lead_id))
        append_event(user_id, "campaign.created", {"campaign": campaign})
        await campaign_service.maybe_auto_strategy(
            session_token, user_id, campaign["id"], campaign["objective"], campaign,
            workspace_id=workspace_id,
        )
        saved = await asyncio.to_thread(load_campaign_state, user_id, campaign["id"], workspace_id=workspace_id) or campaign
        return {
            "ok": True,
            "status": "completed",
            "tool": tool_name,
            "result": {
                "campaign": saved,
                "campaign_id": str(saved.get("id") or campaign["id"]),
                "discovery_id": discovery_id or None,
                "attached_lead_ids": attached_lead_ids,
                "active_campaign_id": str(saved.get("id") or campaign["id"]),
            },
        }

    target = await asyncio.to_thread(load_campaign_state, user_id, campaign_id, workspace_id=workspace_id)
    if not target:
        return {"ok": False, "status": "failed", "tool": tool_name, "reason": "The selected campaign is not available in this workspace."}

    if tool_name == "campaign.refine":
        requested = decision.get("campaign_updates") or decision.get("campaign") or {}
        updates = {key: requested[key] for key in ("name", "objective", "strategy") if key in requested}
        if not updates:
            return {"ok": False, "status": "unavailable", "tool": tool_name, "reason": "No campaign changes were specified."}
        if not await persist_campaign_update_awaited(user_id, campaign_id, updates, workspace_id=workspace_id):
            return {"ok": False, "status": "failed", "tool": tool_name, "reason": "Campaign changes could not be persisted."}
        updated = await asyncio.to_thread(
            load_campaign_state,
            user_id,
            campaign_id,
            workspace_id=workspace_id,
        )
        if not updated or any(updated.get(key) != value for key, value in updates.items()):
            return {"ok": False, "status": "verification_failed", "tool": tool_name,
                    "reason": "Campaign changes could not be verified in this workspace."}
        return {"ok": True, "status": "completed", "tool": tool_name, "result": {"campaign": updated}}

    if tool_name == "campaign.plan":
        objective = str(target.get("objective") or "").strip()
        if not objective:
            return {"ok": False, "status": "failed", "tool": tool_name, "reason": "Campaign objective is required before planning."}
        if not (target.get("leads") or []):
            return {"ok": False, "status": "failed", "tool": tool_name, "reason": "Research prospects before planning the campaign."}
        force = bool(decision.get("force"))
        strategy = target.get("strategy") if isinstance(target.get("strategy"), dict) else None
        if strategy and not force and str(strategy.get("objective") or strategy.get("campaign_objective") or "").strip() == objective:
            return {"ok": True, "status": "completed", "tool": tool_name, "result": {"campaign": target, "reused": True}}
        job_id, status = await campaign_service.enqueue_strategy_job(
            session_token, user_id, campaign_id, objective, target,
            workspace_id=workspace_id,
        )
        return {"ok": True, "status": "accepted", "tool": tool_name, "operation": {"kind": tool_name, "campaign_id": campaign_id, "job_id": job_id, "status": status}, "result": {"campaign": target}}

    if tool_name == "campaign.generate_drafts":
        leads = target.get("leads") or []
        if not leads:
            return {"ok": False, "status": "failed", "tool": tool_name, "reason": "No leads found in the campaign."}
        active_job = await draft_service.active_draft_batch(user_id, workspace_id, campaign_id)
        if active_job:
            batch_id = str(active_job["batch_id"])
            total = int(active_job["total"] or len(leads))
        else:
            try:
                batch = await draft_service.schedule_campaign_draft_batch(
                    session_token, user_id, workspace_id, leads, campaign_id,
                )
            except HTTPException:
                return {"ok": False, "status": "failed", "tool": tool_name, "reason": "Draft generation could not be started."}
            batch_id, total = batch["batch_id"], batch["total"]
        return {"ok": True, "status": "accepted", "tool": tool_name, "operation": {"kind": tool_name, "campaign_id": campaign_id, "batch_id": batch_id, "status": "processing", "total": total}, "result": {"campaign": target}}

    return {"ok": False, "status": "unsupported", "tool": tool_name}


async def run_outreach(
    tool_name: str,
    user_id: str,
    workspace_id: str,
    session_token: str,
    decision: dict[str, Any],
) -> dict[str, Any]:
    """Copilot adapter over canonical workspace and outbound draft services."""
    from services.workspace_state import load_drafts_only, persist_draft_update_awaited

    page = decision.get("page_context") or {}
    draft_id = str(decision.get("draft_id") or page.get("draft_id") or page.get("active_draft_id") or "").strip()
    campaign_id = str(decision.get("campaign_id") or page.get("campaign_id") or page.get("active_campaign_id") or "").strip()
    drafts = await asyncio.to_thread(load_drafts_only, user_id, workspace_id)
    if campaign_id:
        drafts = [draft for draft in drafts if str(draft.get("campaign_id") or "") == campaign_id]
    selected_ids = decision.get("draft_ids") or page.get("selected_draft_ids") or []
    if isinstance(selected_ids, list) and selected_ids:
        drafts = [draft for draft in drafts if str(draft.get("id")) in {str(item) for item in selected_ids}]
    if draft_id:
        drafts = [draft for draft in drafts if str(draft.get("id")) == draft_id]

    if tool_name == "outreach.drafts.read":
        return {"ok": True, "status": "completed", "tool": tool_name,
                "result": {"drafts": drafts, "count": len(drafts), "campaign_id": campaign_id}}
    if not drafts and tool_name != "outreach.draft.generate":
        return {"ok": False, "status": "unavailable", "tool": tool_name,
                "reason": "No owned draft matches the current Copilot context."}

    if tool_name == "outreach.draft.refine":
        edit_request = str(decision.get("edit_request") or decision.get("reason") or "").strip()
        if not edit_request:
            return {"ok": False, "status": "unavailable", "tool": tool_name, "reason": "Tell me how to refine the draft."}
        target = drafts[0]
        previous = str(target.get("text") or target.get("body") or "")
        rewrite = await asyncio.to_thread(
            execute_rewrite, previous, "custom", target.get("lead") or {}, edit_request,
        )
        updated_text = str(getattr(rewrite, "text", "") or previous)
        if not await persist_draft_update_awaited(user_id, str(target.get("id")), {"body": updated_text, "text": updated_text, "status": "pending"}, workspace_id=workspace_id):
            return {"ok": False, "status": "failed", "tool": tool_name, "reason": "Draft refinement could not be persisted."}
        verified = next(
            (draft for draft in await asyncio.to_thread(load_drafts_only, user_id, workspace_id)
             if str(draft.get("id") or "") == str(target.get("id") or "")),
            None,
        )
        verified_text = str((verified or {}).get("text") or (verified or {}).get("body") or "")
        if not verified or verified_text != updated_text or verified.get("status") != "pending":
            return {"ok": False, "status": "verification_failed", "tool": tool_name,
                    "reason": "Draft refinement could not be verified in this workspace."}
        await publish_draft_event(user_id, "draft.updated", draft_id=str(verified.get("id")), campaign_id=str(verified.get("campaign_id") or ""))
        return {"ok": True, "status": "completed", "tool": tool_name, "result": {"draft": verified, "drafts": [verified]}}

    if tool_name == "outreach.draft.generate":
        if not campaign_id:
            return {"ok": False, "status": "unavailable", "tool": tool_name, "reason": "Select a campaign before generating drafts."}
        result = await run_campaign(
            "campaign.generate_drafts", user_id, workspace_id, session_token,
            {**decision, "campaign_id": campaign_id},
        )
        return {**result, "tool": tool_name}

    target = drafts[0]
    target_id = str(target.get("id") or "")
    if tool_name in {"outreach.draft.approve", "outreach.draft.schedule", "outreach.draft.send"} and not decision.get("confirmed"):
        return {"ok": False, "status": "confirmation_required", "tool": tool_name,
                "reason": "Please explicitly confirm before approving, scheduling, or sending this draft."}

    outbound = outbound_service.hydrate_outbound_draft(target, session_token, owner_id=user_id)
    if not outbound_service.outbound_draft_owned_by(outbound, user_id):
        return {"ok": False, "status": "failed", "tool": tool_name, "reason": "The draft is not owned by this workspace."}

    if tool_name == "outreach.draft.approve":
        if not await persist_draft_update_awaited(user_id, target_id, {"status": "approved"}, workspace_id=workspace_id):
            return {"ok": False, "status": "failed", "tool": tool_name, "reason": "Draft approval could not be persisted."}
        verified = next(
            (draft for draft in await asyncio.to_thread(load_drafts_only, user_id, workspace_id)
             if str(draft.get("id") or "") == target_id),
            None,
        )
        if not verified or verified.get("status") != "approved":
            return {"ok": False, "status": "verification_failed", "tool": tool_name,
                    "reason": "Draft approval could not be verified in this workspace."}
        from services.outbound.outbound_models import ApprovalState, DraftStatus

        outbound.status = DraftStatus.APPROVED
        outbound.approval_state = ApprovalState.APPROVED
        if not await outbound_service.persist_outbound_projection(
            user_id, workspace_id, outbound, change_summary="approved by Copilot",
        ):
            return {"ok": False, "status": "failed", "tool": tool_name,
                    "reason": "Draft approval projection could not be persisted."}
        await publish_draft_event(user_id, "draft.approved", draft_id=target_id, campaign_id=str(verified.get("campaign_id") or ""))
        return {"ok": True, "status": "completed", "tool": tool_name, "result": {"draft": verified}}

    provider_id = outbound_service.resolve_provider_for_draft(outbound, user_id)
    if not provider_id:
        return {"ok": False, "status": "failed", "tool": tool_name, "reason": "No authorized Gmail provider is available."}
    if tool_name == "outreach.draft.schedule":
        send_at = str(decision.get("send_at") or "").strip()
        result = (
            await outbound_service.enqueue_scheduled_outbound_send(
                user_id, workspace_id, target, outbound, send_at,
            )
            if send_at
            else {"ok": False, "error": "A send time is required."}
        )
        if result.get("ok"):
            await publish_draft_event(user_id, "draft.scheduled", draft_id=target_id, campaign_id=str(target.get("campaign_id") or ""))
    else:
        result = await asyncio.to_thread(
            outbound_executor.send_hydrated_draft,
            outbound,
            provider_id=provider_id,
        )
        if result.get("ok"):
            await persist_draft_update_awaited(user_id, target_id, {"status": "sent"}, workspace_id=workspace_id)
            await publish_draft_event(user_id, "draft.sent", draft_id=target_id, campaign_id=str(target.get("campaign_id") or ""))
    if not result.get("ok"):
        return {"ok": False, "status": "failed", "tool": tool_name, "reason": result.get("error", "Outreach operation failed.")}
    refreshed = outbound
    if tool_name != "outreach.draft.approve":
        refreshed = outbound
    return {"ok": True, "status": "completed", "tool": tool_name,
            "result": {"draft": outbound_service.outbound_to_legacy_draft(refreshed), "operation": result}}
