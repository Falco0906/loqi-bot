"""Workspace-scoped Copilot runner adapters over canonical domain services.

The ordered R7 migration moves runner bodies here from ``main.py``. This
module owns execution adapters only; contracts and orchestrator state remain
in their existing modules.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Request

import services.campaigns.service as campaign_service
import services.conversations.service as conversation_service
import services.drafts.service as draft_service
import services.outbound.service as outbound_service
from services.events_bus import publish_draft_event
from services.outbound.outbound_executor import executor as outbound_executor
from services.rewrite_engine import execute_rewrite


log = logging.getLogger(__name__)


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
    from services.workspace.state import (
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
            from services.copilot.tools import _requested_leads
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
    from services.workspace.state import load_drafts_only, persist_draft_update_awaited

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


async def run_inbox(
    tool_name: str,
    user_id: str,
    workspace_id: str,
    session_token: str,
    decision: dict[str, Any],
    request: Request | None = None,
) -> dict[str, Any]:
    """Copilot adapter over canonical conversation and reply services."""
    from services.buying_signal import detect_signals
    from services.conversation_intelligence.intelligence_pipeline import IntelligencePipeline
    from services.conversation_models import ConversationStage
    from services.conversations.conversation_store import conversation_store
    from services.conversations.conversation_store import conversation_in_workspace, conversation_owned_by
    from services.followup_reasoner import recommend_followup
    from services.intent_detector import detect_intents
    from services.reasoning.reasoning_pipeline import get_pipeline as get_reasoning_pipeline

    page = decision.get("page_context") or {}
    conversation_id = str(
        decision.get("conversation_id")
        or page.get("conversation_id")
        or page.get("active_conversation_id")
        or page.get("thread_id")
        or ""
    ).strip()
    convo = conversation_store.get_conversation(conversation_id) if conversation_id else None
    if not convo and tool_name == "inbox.conversation.recommend":
        attention = []
        for candidate in conversation_store.list_conversations(limit=50):
            if (
                not conversation_owned_by(candidate, user_id)
                or not conversation_in_workspace(candidate, workspace_id)
            ):
                continue
            summary = candidate.summary.to_dict() if candidate.summary else {}
            needs_attention = (
                candidate.status.value in {"replied", "follow_up_pending", "follow_up_ready", "interested"}
                or bool(summary.get("next_action"))
                or bool(summary.get("last_summary"))
            )
            if not needs_attention:
                continue
            attention.append({
                "conversation_id": candidate.conversation_id,
                "subject": candidate.subject,
                "status": candidate.status.value,
                "company": summary.get("company", ""),
                "contact_name": summary.get("contact_name", ""),
                "interest_level": summary.get("interest_level", "unknown"),
                "summary": summary.get("last_summary", ""),
                "next_action": summary.get("next_action", ""),
                "key_points": (summary.get("key_points") or [])[:5],
            })
        return {
            "ok": True,
            "status": "completed",
            "tool": tool_name,
            "result": {"conversations": attention[:10], "count": len(attention[:10])},
        }
    if (
        not convo
        or not conversation_owned_by(convo, user_id)
        or not conversation_in_workspace(convo, workspace_id)
    ):
        return {"ok": False, "status": "unavailable", "tool": tool_name,
                "reason": "No owned Inbox conversation is selected in this workspace."}
    messages = conversation_store.get_messages_for_conversation(conversation_id)
    latest = messages[-1] if messages else None
    latest_text = (latest.body or latest.body_preview or "") if latest else ""
    subject = (latest.subject if latest else "") or convo.subject

    if tool_name == "inbox.conversation.read":
        return {"ok": True, "status": "completed", "tool": tool_name,
                "result": {"conversation": convo.to_dict(), "messages": [m.to_dict() for m in messages]}}
    if tool_name == "inbox.conversation.summary":
        return {"ok": True, "status": "completed", "tool": tool_name,
                "result": {"conversation_id": conversation_id, "summary": convo.summary.to_dict(), "status": convo.status.value}}

    intelligence = None
    if tool_name in {"inbox.conversation.analyze", "inbox.conversation.recommend", "inbox.reply.generate"}:
        intelligence = IntelligencePipeline().analyze_message(
            message_body=latest_text, lead_id=conversation_id, subject=subject,
        )
    if tool_name == "inbox.conversation.analyze":
        reasoning = get_reasoning_pipeline().reason(intelligence)
        return {"ok": True, "status": "completed", "tool": tool_name,
                "result": {"conversation_id": conversation_id, "intelligence": intelligence.to_dict(), "reasoning": reasoning.to_dict()}}
    if tool_name == "inbox.conversation.recommend":
        signals = detect_signals(latest_text)
        recommendation = recommend_followup(
            detect_intents(latest_text), signals, ConversationStage.ENGAGED,
        )
        return {"ok": True, "status": "completed", "tool": tool_name,
                "result": {"conversation_id": conversation_id, "recommendation": recommendation.model_dump()}}
    if tool_name == "inbox.reply.generate":
        from services.reply_generation.generation_models import GenerationStyle
        from services.reply_generation.generation_pipeline import GenerationPipeline

        knowledge_context = {}
        try:
            from services.knowledge.context_adapter import retrieve_knowledge_context

            retrieved = await retrieve_knowledge_context(
                user_id, query=" ".join(part for part in ("reply", subject, latest_text[:500]) if part),
                categories=["company", "messaging", "sales_offer"], limit=8,
                workspace_id=workspace_id,
            )
            knowledge_context = retrieved.to_dict()
        except Exception as error:
            log.warning("Copilot Inbox Knowledge retrieval skipped: %s", error)
        reasoning = get_reasoning_pipeline().reason(intelligence)
        recent = []
        for message in messages[-3:]:
            preview = message.body_preview or (message.body or "")[:200]
            if preview:
                recent.append(f"[{'Prospect' if message.direction == 'inbound' else 'You'}]: {preview}")
        result = await asyncio.to_thread(
            GenerationPipeline().generate,
            intelligence=intelligence, reasoning=reasoning,
            styles=[GenerationStyle.PROFESSIONAL], variant_count=1,
            latest_messages=recent,
            instruction=str(decision.get("edit_request") or "").strip() or None,
            knowledge_context=knowledge_context,
        )
        return {"ok": True, "status": "completed", "tool": tool_name,
                "result": {"conversation_id": conversation_id, "generation": result.to_dict()}}
    if tool_name == "inbox.reply.send":
        if not decision.get("confirmed"):
            return {"ok": False, "status": "confirmation_required", "tool": tool_name,
                    "reason": "Please explicitly confirm before sending this reply."}
        if not decision.get("reply_body"):
            return {"ok": False, "status": "unavailable", "tool": tool_name,
                    "reason": "A reply body is required before sending."}
        if request is None:
            return {"ok": False, "status": "failed", "tool": tool_name, "reason": "Authenticated Inbox send context is unavailable."}
        try:
            sent = await conversation_service.send_reply(
                conversation_id, user_id, {"body": decision["reply_body"]},
            )
        except HTTPException as error:
            return {"ok": False, "status": "failed", "tool": tool_name, "reason": str(error.detail)}
        refreshed = conversation_store.get_conversation(conversation_id)
        sent_message_id = str(sent.get("message_id") or "")
        persisted_messages = conversation_store.get_messages_for_conversation(conversation_id)
        message_persisted = any(
            str(message.message_id or "") == sent_message_id
            for message in persisted_messages
        )
        if (
            not refreshed
            or not conversation_owned_by(refreshed, user_id)
            or not conversation_in_workspace(refreshed, workspace_id)
            or str(getattr(refreshed.status, "value", "")) != "sent"
            or not sent_message_id
            or not message_persisted
        ):
            return {
                "ok": False,
                "status": "verification_failed",
                "tool": tool_name,
                "reason": "The reply provider accepted the request, but Loqi could not verify the durable conversation update.",
            }
        return {
            "ok": True,
            "status": "completed",
            "tool": tool_name,
            "result": {**sent, "conversation": refreshed.to_dict()},
        }
    return {"ok": False, "status": "unsupported", "tool": tool_name}


async def run_knowledge(
    tool_name: str,
    user_id: str,
    workspace_id: str,
    session_token: str,
    decision: dict[str, Any],
) -> dict[str, Any]:
    """Read-only Copilot adapter over the canonical Knowledge service."""
    from services.knowledge.context_adapter import retrieve_knowledge_context
    from services.knowledge.service import KnowledgeService, item_to_dict

    page = decision.get("page_context") or {}
    query = str(decision.get("knowledge_query") or decision.get("user_message") or "").strip()
    context_parts = []
    for key in ("company_name", "company", "lead_name", "lead_company", "campaign_name"):
        value = page.get(key)
        if value and str(value).strip() not in query:
            context_parts.append(str(value).strip())
    if context_parts:
        query = " ".join([query, *context_parts]).strip()
    categories = decision.get("knowledge_categories") or []
    if not isinstance(categories, list):
        categories = []

    if tool_name == "knowledge.read" and decision.get("knowledge_item_id"):
        item = await KnowledgeService().get_item(workspace_id, decision["knowledge_item_id"])
        if item is None:
            return {"ok": False, "status": "failed", "tool": tool_name, "reason": "Knowledge item not found in this workspace."}
        return {"ok": True, "status": "completed", "tool": tool_name,
                "result": {"items": [item_to_dict(item)], "sources": [], "query": query}}

    context = await retrieve_knowledge_context(
        user_id,
        query=query,
        categories=categories,
        limit=8,
        workspace_id=workspace_id,
    )
    result = context.to_dict()
    result["context"] = {"page": page, "workspace_id": workspace_id}
    if not result.get("items") and not result.get("sources"):
        return {"ok": True, "status": "empty", "tool": tool_name, "result": result,
                "reason": "No matching Knowledge was found in this workspace."}
    return {"ok": True, "status": "completed", "tool": tool_name, "result": result}


async def run_analytics(
    tool_name: str,
    user_id: str,
    workspace_id: str,
    session_token: str,
    decision: dict[str, Any],
) -> dict[str, Any]:
    """Read current, workspace-scoped analytics from canonical snapshots."""
    from services.workspace.state import load_campaign_state, load_workspace_state
    from services.workspace_snapshot import build_snapshot, enrich_campaigns

    page = decision.get("page_context") or {}
    campaign_id = str(
        decision.get("campaign_id")
        or page.get("campaign_id")
        or page.get("active_campaign_id")
        or ""
    ).strip()
    state = await asyncio.to_thread(load_workspace_state, user_id, False, workspace_id)
    campaigns = state.get("campaigns") or []
    drafts = state.get("drafts") or []
    enriched = enrich_campaigns(campaigns, drafts)
    total_leads = sum(int(c.get("lead_count") or 0) for c in campaigns)

    if tool_name == "analytics.campaign.summary":
        if not campaign_id:
            return {"ok": False, "status": "unavailable", "tool": tool_name, "reason": "No campaign is selected for this metric."}
        campaign = await asyncio.to_thread(load_campaign_state, user_id, campaign_id, workspace_id=workspace_id)
        if not campaign:
            return {"ok": False, "status": "failed", "tool": tool_name, "reason": "The selected campaign is not available in this workspace."}
        target = next((item for item in enriched if str(item.get("id")) == campaign_id), campaign)
        result = {"campaign": target, "metrics": {
            "lead_count": target.get("lead_count", 0),
            "pending_drafts": target.get("pending_drafts", 0),
            "approved_drafts": target.get("approved_drafts", 0),
            "sent_drafts": target.get("sent_drafts", 0),
            "status": target.get("status", ""),
            "current_step": target.get("current_step", ""),
            "updated_at": target.get("updated_at", ""),
        }}
        return {"ok": True, "status": "completed", "tool": tool_name, "result": result}

    snapshot = await asyncio.to_thread(
        build_snapshot, session_token, campaigns, drafts, total_leads, False, user_id,
    )
    if tool_name == "analytics.leads.summary":
        selected = [c for c in enriched if not campaign_id or str(c.get("id")) == campaign_id]
        if campaign_id and not selected:
            return {"ok": False, "status": "failed", "tool": tool_name, "reason": "The selected campaign is not available in this workspace."}
        return {"ok": True, "status": "completed", "tool": tool_name, "result": {
            "campaign_id": campaign_id,
            "lead_count": sum(int(c.get("lead_count") or 0) for c in selected) if campaign_id else snapshot.get("total_leads", total_leads),
            "campaigns": [{"id": c.get("id"), "name": c.get("name"), "lead_count": c.get("lead_count", 0)} for c in selected],
        }}

    if tool_name == "analytics.workspace.summary":
        return {"ok": True, "status": "completed", "tool": tool_name, "result": {
            "metrics": {
                "total_leads": snapshot.get("total_leads", total_leads),
                "campaign_count": snapshot.get("campaign_count", len(campaigns)),
                "drafts": snapshot.get("drafts", {}),
                "campaigns_ready": snapshot.get("campaigns_ready", 0),
                "campaigns_draft_review": snapshot.get("campaigns_draft_review", 0),
            },
            "campaigns": snapshot.get("campaigns", []),
            "analysis": snapshot.get("analysis", {}),
        }}
    return {"ok": False, "status": "unsupported", "tool": tool_name}
