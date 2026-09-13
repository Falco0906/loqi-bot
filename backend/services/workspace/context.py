"""Build the workspace-scoped read model used by Copilot and provider views."""
from __future__ import annotations

import logging

from fastapi import HTTPException

from services.communication.communication_store import store as communication_store
from services.communication.provider_registry import get_provider
from services.conversation_memory import memory_store
from services.conversation_models import BuyingSignal
from services.conversations.compatibility import read_legacy_timeline_events
from services.conversations.conversation_store import (
    conversation_in_workspace,
    conversation_owned_by,
    conversation_store,
)
from services.workspace.state import load_workspace_state
from services.workspace_reasoner import WorkspaceReasoner
from services.workspace_snapshot import enrich_campaigns


log = logging.getLogger("loqi")


def build_workspace_context(
    session_token: str,
    current_page: str | None = None,
    page_context: dict | None = None,
    conversation_id: str | None = None,
    user_id: str = "",
    workspace_id: str = "",
) -> dict:
    """Return bounded canonical context for one authenticated workspace.

    ``session_token`` remains an input for compatibility with the legacy web
    and Copilot callers. Authority is the explicit authenticated user and
    membership-authorized workspace supplied by the API boundary.
    """
    if not user_id or not workspace_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    campaigns = []
    drafts = []
    try:
        state = load_workspace_state(
            user_id,
            include_details=False,
            workspace_id=workspace_id,
            canonical_only=True,
        )
        campaigns = state.get("campaigns") or []
        drafts = state.get("drafts") or []
    except Exception as error:
        log.warning("Copilot canonical workspace context unavailable: %s", error)

    page_context = page_context or {}
    active_campaign_id = str(
        page_context.get("campaign_id") or page_context.get("active_campaign_id") or ""
    ).strip()
    active_draft_id = str(
        page_context.get("draft_id") or page_context.get("active_draft_id") or ""
    ).strip()
    if active_campaign_id:
        campaigns = [campaign for campaign in campaigns if str(campaign.get("id") or "") == active_campaign_id]
        drafts = [draft for draft in drafts if str(draft.get("campaign_id") or "") == active_campaign_id]
    if active_draft_id:
        drafts = [draft for draft in drafts if str(draft.get("id") or "") == active_draft_id]
    campaigns = campaigns[:20]
    drafts = drafts[:50]

    enriched_campaigns = enrich_campaigns(campaigns, drafts)
    total_leads = sum(int(campaign.get("lead_count") or 0) for campaign in enriched_campaigns)
    pending_drafts = sum(1 for draft in drafts if str(draft.get("status") or "") == "pending")
    approved_drafts = sum(1 for draft in drafts if str(draft.get("status") or "") == "approved")
    prompt_campaigns = [
        {
            "id": str(campaign.get("id") or ""),
            "name": str(campaign.get("name") or ""),
            "status": str(campaign.get("status") or "planning"),
            "current_step": str(campaign.get("current_step") or ""),
            "lead_count": int(campaign.get("lead_count") or 0),
            "pending_drafts": int(campaign.get("pending_drafts") or 0),
            "approved_drafts": int(campaign.get("approved_drafts") or 0),
            "created_at": campaign.get("created_at") or "",
            "updated_at": campaign.get("updated_at") or "",
        }
        for campaign in enriched_campaigns
    ]
    snapshot = {
        "campaigns": prompt_campaigns,
        "campaign_count": len(prompt_campaigns),
        "campaigns_ready": sum(1 for campaign in prompt_campaigns if campaign["current_step"] == "sending"),
        "campaigns_draft_review": sum(1 for campaign in prompt_campaigns if campaign["current_step"] == "review"),
        "drafts": {"total": len(drafts), "pending": pending_drafts, "approved": approved_drafts},
        "total_leads": total_leads,
        "jobs": {"running": [], "recently_completed": []},
        "memory": {},
        "timeline": [],
    }
    analysis = WorkspaceReasoner(snapshot).analyze().to_dict()
    result = {
        "snapshot": {
            "campaigns": snapshot.get("campaigns", []),
            "campaign_count": snapshot.get("campaign_count", 0),
            "campaigns_ready": snapshot.get("campaigns_ready", 0),
            "campaigns_draft_review": snapshot.get("campaigns_draft_review", 0),
            "drafts": snapshot.get("drafts", {}),
            "total_leads": snapshot.get("total_leads", 0),
            "jobs": snapshot.get("jobs", {}),
            "memory": snapshot.get("memory", {}),
            "timeline": snapshot.get("timeline", []),
            "active_workflows": [],
        },
        "analysis": {
            "current_focus": analysis.get("current_focus"),
            "recommended_next_action": analysis.get("recommended_next_action"),
            "campaign_priorities": analysis.get("campaign_priorities", []),
            "workspace_health": analysis.get("workspace_health"),
            "cross_campaign_insights": analysis.get("cross_campaign_insights", []),
            "workflow_continuation": analysis.get("workflow_continuation"),
            "attention_items": analysis.get("attention_items", []),
        },
    }

    if current_page == "Draft Review" and page_context:
        selected_index = page_context.get("selected_index")
        if selected_index is not None and drafts:
            try:
                index = int(selected_index)
                if 0 <= index < len(drafts):
                    draft = drafts[index]
                    result["current_draft"] = {
                        "id": draft.get("id"),
                        "subject": draft.get("subject", ""),
                        "text_preview": draft.get("text", "")[:300],
                        "lead_name": draft.get("lead", {}).get("name", ""),
                        "lead_company": draft.get("lead", {}).get("company", ""),
                        "lead_title": draft.get("lead", {}).get("title", ""),
                        "campaign_name": draft.get("campaign_name", ""),
                        "tone": draft.get("tone"),
                        "length": draft.get("length"),
                        "status": draft.get("status"),
                    }
                    intelligence = draft.get("draft_intelligence")
                    if intelligence:
                        result["current_draft"]["draft_intelligence"] = intelligence
                    draft_text = draft.get("text", "")
                    try:
                        from services.draft_intelligence import analyze_draft
                        result["current_draft"]["draft_intelligence"] = analyze_draft(draft_text, {
                            "campaign_name": draft.get("campaign_name"),
                            "company": draft.get("lead", {}).get("company"),
                            "contact": draft.get("lead", {}).get("name"),
                            "role": draft.get("lead", {}).get("title"),
                        }).to_dict()
                    except Exception:
                        pass
            except (ValueError, IndexError):
                pass

    providers = [
        provider for provider in communication_store.list_providers()
        if str(getattr(provider, "user_id", "")) == str(user_id)
    ]
    if providers:
        provider_list = []
        for provider in providers:
            instance = get_provider(provider.id)
            health = instance.health().value if instance else provider.status.value
            provider_list.append({
                "id": provider.id,
                "provider_type": provider.provider_type.value,
                "status": health,
                "email": provider.metadata.get("email", ""),
                "last_sync": provider.last_sync,
            })
        result["providers"] = provider_list
        result["provider_summary"] = {
            "total": len(providers),
            "healthy": sum(1 for provider in provider_list if provider["status"] == "healthy"),
            "offline": sum(1 for provider in provider_list if provider["status"] == "offline"),
            "last_sync": max((provider["last_sync"] for provider in provider_list if provider["last_sync"]), default=""),
        }

    if conversation_id:
        conversation = conversation_store.get_conversation(conversation_id)
        if (
            conversation is not None
            and conversation_owned_by(conversation, user_id)
            and conversation_in_workspace(conversation, str(workspace_id or ""))
        ):
            memory = memory_store.get(conversation_id)
            if memory:
                events = read_legacy_timeline_events(conversation_id)
                signals = [
                    BuyingSignal(signal=signal, strength="medium", confidence=50, reason="")
                    for signal in memory.buying_signals
                ] if memory.buying_signals else []
                signal_payloads = [signal.model_dump() for signal in signals] if signals else []
                result["conversation_intelligence"] = {
                    "conversation_id": conversation_id,
                    "current_stage": memory.current_stage.value,
                    "summary": memory.summary,
                    "open_questions": memory.open_questions,
                    "outstanding_objections": memory.outstanding_objections,
                    "pain_points": memory.pain_points,
                    "business_goals": memory.business_goals,
                    "competitor_mentioned": memory.competitor_mentioned,
                    "decision_makers": memory.decision_makers,
                    "buying_signals": memory.buying_signals,
                    "last_recommendation": memory.last_recommendation,
                    "last_followup": memory.last_followup,
                    "key_risks": memory.key_risks,
                    "key_opportunities": memory.key_opportunities,
                    "urgency": memory.urgency,
                    "decision_confidence": memory.decision_confidence,
                    "top_objection": memory.top_objection,
                    "timeline_events": [event.model_dump() for event in events],
                }

    return result
