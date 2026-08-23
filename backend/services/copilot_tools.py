"""Backend-owned Copilot tool contract.

Tools in this module are adapters around existing domain services. They do not
implement Discovery or lead persistence themselves; they only validate the
resource context and invoke the existing service boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass
import asyncio
from typing import Any, Awaitable, Callable


@dataclass(frozen=True)
class CopilotTool:
    name: str
    input_schema: dict[str, Any]
    read_only: bool


DISCOVERY_TOOLS: dict[str, CopilotTool] = {
    "discovery.search": CopilotTool(
        name="discovery.search",
        input_schema={"search_context": "structured search context"},
        read_only=False,
    ),
    "discovery.refine": CopilotTool(
        name="discovery.refine",
        input_schema={"search_context": "structured refined search context"},
        read_only=False,
    ),
    "discovery.read": CopilotTool(
        name="discovery.read",
        input_schema={"discovery_id": "owned Discovery ID"},
        read_only=True,
    ),
}


LEAD_TOOLS: dict[str, CopilotTool] = {
    "lead.read": CopilotTool(
        name="lead.read",
        input_schema={"discovery_id": "owned Discovery ID", "lead_ids": "optional lead IDs"},
        read_only=True,
    ),
    "lead.filter": CopilotTool(
        name="lead.filter",
        input_schema={"discovery_id": "owned Discovery ID", "filters": "lead field filters"},
        read_only=True,
    ),
    "lead.rank": CopilotTool(
        name="lead.rank",
        input_schema={"discovery_id": "owned Discovery ID", "sort": "rank or score", "limit": "optional result limit"},
        read_only=True,
    ),
    "lead.save": CopilotTool(
        name="lead.save",
        input_schema={"discovery_id": "owned Discovery ID", "lead_ids": "lead IDs"},
        read_only=False,
    ),
    "lead.approve": CopilotTool(
        name="lead.approve",
        input_schema={"discovery_id": "owned Discovery ID", "lead_ids": "lead IDs"},
        read_only=False,
    ),
    "lead.reject": CopilotTool(
        name="lead.reject",
        input_schema={"discovery_id": "owned Discovery ID", "lead_ids": "lead IDs"},
        read_only=False,
    ),
    "lead.attach": CopilotTool(
        name="lead.attach",
        input_schema={"discovery_id": "owned Discovery ID", "campaign_id": "owned campaign ID", "lead_ids": "lead IDs"},
        read_only=False,
    ),
}


CAMPAIGN_TOOLS: dict[str, CopilotTool] = {
    "campaign.list": CopilotTool(
        name="campaign.list",
        input_schema={"workspace_id": "authorized workspace"},
        read_only=True,
    ),
    "campaign.read": CopilotTool(
        name="campaign.read",
        input_schema={"campaign_id": "owned campaign ID"},
        read_only=True,
    ),
    "campaign.drafts": CopilotTool(
        name="campaign.drafts",
        input_schema={"campaign_id": "owned campaign ID"},
        read_only=True,
    ),
    "campaign.create": CopilotTool(
        name="campaign.create",
        input_schema={"campaign": "structured campaign fields", "lead_ids": "selected lead IDs"},
        read_only=False,
    ),
    "campaign.refine": CopilotTool(
        name="campaign.refine",
        input_schema={"campaign_id": "owned campaign ID", "campaign_updates": "structured updates"},
        read_only=False,
    ),
    "campaign.plan": CopilotTool(
        name="campaign.plan",
        input_schema={"campaign_id": "owned campaign ID", "force": "optional regeneration flag"},
        read_only=False,
    ),
    "campaign.generate_drafts": CopilotTool(
        name="campaign.generate_drafts",
        input_schema={"campaign_id": "owned campaign ID"},
        read_only=False,
    ),
}


OUTREACH_TOOLS: dict[str, CopilotTool] = {
    "outreach.drafts.read": CopilotTool(
        name="outreach.drafts.read",
        input_schema={"draft_id": "optional owned draft ID", "campaign_id": "optional owned campaign ID"},
        read_only=True,
    ),
    "outreach.draft.generate": CopilotTool(
        name="outreach.draft.generate",
        input_schema={"campaign_id": "owned campaign ID"},
        read_only=False,
    ),
    "outreach.draft.refine": CopilotTool(
        name="outreach.draft.refine",
        input_schema={"draft_id": "owned draft ID", "edit_request": "requested draft change"},
        read_only=False,
    ),
    "outreach.draft.approve": CopilotTool(
        name="outreach.draft.approve",
        input_schema={"draft_id": "owned draft ID", "confirmed": "explicit approval"},
        read_only=False,
    ),
    "outreach.draft.schedule": CopilotTool(
        name="outreach.draft.schedule",
        input_schema={"draft_id": "owned draft ID", "send_at": "ISO datetime", "confirmed": "explicit confirmation"},
        read_only=False,
    ),
    "outreach.draft.send": CopilotTool(
        name="outreach.draft.send",
        input_schema={"draft_id": "owned draft ID", "confirmed": "explicit confirmation"},
        read_only=False,
    ),
}


INBOX_TOOLS: dict[str, CopilotTool] = {
    "inbox.conversation.read": CopilotTool(
        name="inbox.conversation.read",
        input_schema={"conversation_id": "owned conversation ID"},
        read_only=True,
    ),
    "inbox.conversation.summary": CopilotTool(
        name="inbox.conversation.summary",
        input_schema={"conversation_id": "owned conversation ID"},
        read_only=True,
    ),
    "inbox.conversation.analyze": CopilotTool(
        name="inbox.conversation.analyze",
        input_schema={"conversation_id": "owned conversation ID"},
        read_only=True,
    ),
    "inbox.conversation.recommend": CopilotTool(
        name="inbox.conversation.recommend",
        input_schema={"conversation_id": "owned conversation ID"},
        read_only=True,
    ),
    "inbox.reply.generate": CopilotTool(
        name="inbox.reply.generate",
        input_schema={"conversation_id": "owned conversation ID", "instruction": "optional reply instruction"},
        read_only=True,
    ),
    "inbox.reply.send": CopilotTool(
        name="inbox.reply.send",
        input_schema={"conversation_id": "owned conversation ID", "body": "reply body", "confirmed": "explicit confirmation"},
        read_only=False,
    ),
}


KNOWLEDGE_TOOLS: dict[str, CopilotTool] = {
    "knowledge.search": CopilotTool(
        name="knowledge.search",
        input_schema={"query": "grounded Knowledge query", "categories": "optional Knowledge categories"},
        read_only=True,
    ),
    "knowledge.read": CopilotTool(
        name="knowledge.read",
        input_schema={"item_id": "optional owned Knowledge item ID", "query": "optional Knowledge query"},
        read_only=True,
    ),
}


ANALYTICS_TOOLS: dict[str, CopilotTool] = {
    "analytics.workspace.summary": CopilotTool(
        name="analytics.workspace.summary",
        input_schema={"workspace_id": "authorized workspace"},
        read_only=True,
    ),
    "analytics.campaign.summary": CopilotTool(
        name="analytics.campaign.summary",
        input_schema={"campaign_id": "owned campaign ID"},
        read_only=True,
    ),
    "analytics.leads.summary": CopilotTool(
        name="analytics.leads.summary",
        input_schema={"campaign_id": "optional owned campaign ID"},
        read_only=True,
    ),
}


COPILOT_TOOLS = {**DISCOVERY_TOOLS, **LEAD_TOOLS, **CAMPAIGN_TOOLS, **OUTREACH_TOOLS, **INBOX_TOOLS, **KNOWLEDGE_TOOLS, **ANALYTICS_TOOLS}

_LEAD_READ_TOOLS = {"lead.read", "lead.filter", "lead.rank"}
_LEAD_MUTATION_TOOLS = {"lead.save", "lead.approve", "lead.reject", "lead.attach"}
_CAMPAIGN_READ_TOOLS = {"campaign.list", "campaign.read", "campaign.drafts"}
_CAMPAIGN_MUTATION_TOOLS = {"campaign.create", "campaign.refine", "campaign.plan", "campaign.generate_drafts"}
_OUTREACH_READ_TOOLS = {"outreach.drafts.read"}
_OUTREACH_MUTATION_TOOLS = {
    "outreach.draft.generate", "outreach.draft.refine", "outreach.draft.approve",
    "outreach.draft.schedule", "outreach.draft.send",
}
_INBOX_READ_TOOLS = {
    "inbox.conversation.read", "inbox.conversation.summary", "inbox.conversation.analyze",
    "inbox.conversation.recommend", "inbox.reply.generate",
}
_INBOX_MUTATION_TOOLS = {"inbox.reply.send"}
_KNOWLEDGE_READ_TOOLS = {"knowledge.search", "knowledge.read"}
_ANALYTICS_READ_TOOLS = set(ANALYTICS_TOOLS)


def select_copilot_tool(decision: dict[str, Any]) -> str | None:
    """Map an intent decision to a registered tool without executing it."""
    intent = decision.get("intent")
    if intent == "discovery":
        return "discovery.search"
    if intent == "discovery_refinement":
        return "discovery.refine"
    if intent == "read":
        action = str(decision.get("action") or "").strip()
        if action in _LEAD_READ_TOOLS:
            return action
        if action in _CAMPAIGN_READ_TOOLS:
            return action
        if action in _OUTREACH_READ_TOOLS:
            return action
        if action in _INBOX_READ_TOOLS:
            return action
        if action in _KNOWLEDGE_READ_TOOLS:
            return action
        if action in _ANALYTICS_READ_TOOLS:
            return action
        return "discovery.read"
    if intent == "action":
        action = str(decision.get("action") or "").strip()
        if action in _LEAD_MUTATION_TOOLS:
            return action
        if action in _CAMPAIGN_MUTATION_TOOLS:
            return action
        if action in _OUTREACH_MUTATION_TOOLS:
            return action
        if action in _INBOX_MUTATION_TOOLS:
            return action
    return None


def _discovery_leads(discovery: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the canonical Discovery join into safe lead representations."""
    flattened: list[dict[str, Any]] = []
    for item in discovery.get("discovery_leads") or []:
        if not isinstance(item, dict):
            continue
        workspace_lead = item.get("workspace_lead") or {}
        lead = workspace_lead.get("lead") or {}
        flattened.append({
            **lead,
            **workspace_lead,
            "id": str(workspace_lead.get("id") or item.get("lead_id") or lead.get("id") or ""),
            "rank": item.get("rank"),
            "match_score": item.get("match_score"),
        })
    return flattened


def _lead_matches(lead: dict[str, Any], filters: dict[str, Any]) -> bool:
    for key, expected in filters.items():
        if expected in (None, "", []):
            continue
        actual = str(lead.get(key) or lead.get({"role": "title"}.get(key, key)) or "").lower()
        values = expected if isinstance(expected, list) else [expected]
        if not any(str(value).lower() in actual for value in values):
            return False
    return True


def _requested_leads(discovery: dict[str, Any], decision: dict[str, Any]) -> list[dict[str, Any]]:
    leads = _discovery_leads(discovery)
    active_search = decision.get("active_search") or {}
    page_context = decision.get("page_context") or {}
    selected = page_context.get("selected_leads") or page_context.get("selected_lead_ids")
    if isinstance(selected, list) and selected and isinstance(selected[0], dict):
        selected = [item.get("id") for item in selected]
    requested = (
        decision.get("lead_ids")
        or active_search.get("lead_ids")
        or active_search.get("selected_lead_ids")
        or selected
        or []
    )
    requested_ids = {str(value) for value in requested if str(value).strip()}
    if requested_ids:
        leads = [lead for lead in leads if str(lead.get("id")) in requested_ids]
    return leads


async def _load_owned_discovery(discovery_id: str, workspace_id: str) -> dict[str, Any] | None:
    from services.discovery import get_discovery
    return await asyncio.to_thread(get_discovery, discovery_id, workspace_id)


def _lead_result(discovery: dict[str, Any], leads: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "discovery_id": str(discovery.get("id") or ""),
        "status": str(discovery.get("status") or ""),
        "lead_count": len(leads),
        "leads": leads[:50],
    }


async def execute_copilot_tool(
    tool_name: str,
    *,
    user_id: str,
    workspace_id: str,
    session_token: str,
    decision: dict[str, Any],
    discovery_runner: Callable[..., Awaitable[dict[str, Any]]],
    campaign_runner: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    outreach_runner: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    inbox_runner: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    knowledge_runner: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    analytics_runner: Callable[..., Awaitable[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Execute one validated Discovery tool through existing service boundaries."""
    tool = COPILOT_TOOLS.get(tool_name)
    if tool is None:
        return {"ok": False, "status": "unsupported", "tool": tool_name}

    if tool_name in {"discovery.search", "discovery.refine"}:
        context = decision.get("search_context") or {}
        return {
            "ok": True,
            "status": "accepted",
            "tool": tool_name,
            "search_context": context,
            "operation": await discovery_runner(
                user_id,
                context,
                session_token,
            ),
        }

    if tool_name in CAMPAIGN_TOOLS:
        if campaign_runner is None:
            return {
                "ok": False,
                "status": "unavailable",
                "tool": tool_name,
                "reason": "Campaign operations are not available in this session.",
            }
        return await campaign_runner(
            tool_name,
            user_id,
            workspace_id,
            session_token,
            decision,
        )

    if tool_name in OUTREACH_TOOLS:
        if outreach_runner is None:
            return {
                "ok": False,
                "status": "unavailable",
                "tool": tool_name,
                "reason": "Outreach operations are not available in this session.",
            }
        return await outreach_runner(
            tool_name,
            user_id,
            workspace_id,
            session_token,
            decision,
        )

    if tool_name in INBOX_TOOLS:
        if inbox_runner is None:
            return {
                "ok": False,
                "status": "unavailable",
                "tool": tool_name,
                "reason": "Inbox operations are not available in this session.",
            }
        return await inbox_runner(
            tool_name,
            user_id,
            workspace_id,
            session_token,
            decision,
        )

    if tool_name in KNOWLEDGE_TOOLS:
        if knowledge_runner is None:
            return {
                "ok": False,
                "status": "unavailable",
                "tool": tool_name,
                "reason": "Knowledge retrieval is not available in this session.",
            }
        return await knowledge_runner(
            tool_name,
            user_id,
            workspace_id,
            session_token,
            decision,
        )

    if tool_name in ANALYTICS_TOOLS:
        if analytics_runner is None:
            return {
                "ok": False,
                "status": "unavailable",
                "tool": tool_name,
                "reason": "Analytics are not available in this session.",
            }
        return await analytics_runner(
            tool_name,
            user_id,
            workspace_id,
            session_token,
            decision,
        )

    active_search = decision.get("active_search") or {}
    page_context = decision.get("page_context") or {}
    discovery_id = str(
        active_search.get("discovery_id")
        or decision.get("discovery_id")
        or page_context.get("discovery_id")
        or ""
    )
    if not discovery_id:
        return {
            "ok": False,
            "status": "unavailable",
            "tool": tool_name,
            "reason": "No active Discovery is available to read.",
        }

    discovery = await _load_owned_discovery(discovery_id, workspace_id)
    if not discovery:
        return {
            "ok": False,
            "status": "failed",
            "tool": tool_name,
            "reason": "The active Discovery could not be retrieved.",
        }

    leads = _requested_leads(discovery, decision)
    companies = discovery.get("discovery_companies") or []
    if tool_name in _LEAD_READ_TOOLS:
        if tool_name == "lead.filter":
            leads = [lead for lead in leads if _lead_matches(lead, decision.get("filters") or {})]
        elif tool_name == "lead.rank":
            sort = str(decision.get("sort") or "rank")
            leads = sorted(
                leads,
                key=lambda lead: float(lead.get("match_score") or lead.get("confidence") or 0),
                reverse=sort in {"score", "match_score", "confidence", "best"},
            )
            limit = decision.get("limit")
            if isinstance(limit, int) and limit > 0:
                leads = leads[:limit]
        return {
            "ok": True,
            "status": "completed",
            "tool": tool_name,
            "result": _lead_result(discovery, leads),
        }

    if tool_name == "discovery.read":
        return {
            "ok": True,
            "status": "completed",
            "tool": tool_name,
            "result": {
                "discovery_id": str(discovery.get("id") or discovery_id),
                "status": str(discovery.get("status") or ""),
                "title": str(discovery.get("title") or discovery.get("query") or ""),
                "lead_count": len(leads),
                "company_count": len(companies),
                "summary": discovery.get("summary") or {},
                "leads": leads[:10],
            },
        }

    if not leads:
        return {
            "ok": False,
            "status": "unavailable",
            "tool": tool_name,
            "reason": "No authorized leads were selected from the active Discovery.",
        }

    if not bool(decision.get("confirmed")):
        return {
            "ok": False,
            "status": "confirmation_required",
            "tool": tool_name,
            "reason": f"Please confirm {tool_name.replace('lead.', '').replace('_', ' ')} for {len(leads)} lead(s).",
            "result": _lead_result(discovery, leads),
        }

    if tool_name == "lead.save":
        from services.workspace_state import _normalize_lead
        saved_ids = [
            saved for saved in await asyncio.gather(*[
                _normalize_lead(workspace_id, lead) for lead in leads
            ]) if saved
        ]
        return {"ok": True, "status": "completed", "tool": tool_name, "result": {**_lead_result(discovery, leads), "saved_ids": saved_ids}}

    if tool_name in {"lead.approve", "lead.reject"}:
        from services.workspace_state import persist_lead_decision
        approved = tool_name == "lead.approve"
        updated = [
            persist_lead_decision(user_id, lead, approved) for lead in leads
        ]
        if not all(updated):
            return {"ok": False, "status": "failed", "tool": tool_name, "reason": "Lead decision could not be persisted."}
        return {"ok": True, "status": "completed", "tool": tool_name, "result": {**_lead_result(discovery, leads), "approved": approved}}

    if tool_name == "lead.attach":
        campaign_id = str(decision.get("campaign_id") or (decision.get("page_context") or {}).get("campaign_id") or "")
        if not campaign_id:
            return {"ok": False, "status": "unavailable", "tool": tool_name, "reason": "A campaign must be selected before attaching leads."}
        from services.workspace_state import load_campaign_state, persist_campaign_lead_id_awaited
        campaign = await asyncio.to_thread(load_campaign_state, user_id, campaign_id, workspace_id=workspace_id)
        if not campaign:
            return {"ok": False, "status": "failed", "tool": tool_name, "reason": "The selected campaign is not available in this workspace."}
        attached = []
        for lead in leads:
            lead_id = await persist_campaign_lead_id_awaited(
                user_id, campaign_id, lead, workspace_id=workspace_id,
            )
            if lead_id:
                attached.append(str(lead_id))
        if len(attached) != len(leads):
            return {"ok": False, "status": "failed", "tool": tool_name, "reason": "One or more leads could not be attached."}
        return {"ok": True, "status": "completed", "tool": tool_name, "result": {**_lead_result(discovery, leads), "campaign_id": campaign_id, "attached_ids": attached, "attached_lead_ids": attached}}
