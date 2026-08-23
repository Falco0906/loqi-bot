"""Minimal backend-owned Copilot tool contract.

Discovery is the first registered capability. This module deliberately owns
tool selection/execution boundaries, not Discovery implementation.
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


def select_copilot_tool(decision: dict[str, Any]) -> str | None:
    """Map an intent decision to a registered tool without executing it."""
    intent = decision.get("intent")
    if intent == "discovery":
        return "discovery.search"
    if intent == "discovery_refinement":
        return "discovery.refine"
    if intent == "read":
        return "discovery.read"
    return None


async def execute_copilot_tool(
    tool_name: str,
    *,
    user_id: str,
    workspace_id: str,
    session_token: str,
    decision: dict[str, Any],
    discovery_runner: Callable[..., Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Execute one validated Discovery tool through existing service boundaries."""
    tool = DISCOVERY_TOOLS.get(tool_name)
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

    active_search = decision.get("active_search") or {}
    discovery_id = str(
        active_search.get("discovery_id")
        or decision.get("discovery_id")
        or ""
    )
    if not discovery_id:
        return {
            "ok": False,
            "status": "unavailable",
            "tool": tool_name,
            "reason": "No active Discovery is available to read.",
        }

    from services.discovery import get_discovery

    discovery = await asyncio.to_thread(
        get_discovery, discovery_id, workspace_id
    )
    if not discovery:
        return {
            "ok": False,
            "status": "failed",
            "tool": tool_name,
            "reason": "The active Discovery could not be retrieved.",
        }

    leads = discovery.get("discovery_leads") or []
    companies = discovery.get("discovery_companies") or []
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
            "leads": [
                {
                    "name": str(
                        (item.get("workspace_lead") or {}).get("lead", {}).get("name")
                        or (item.get("workspace_lead") or {}).get("lead", {}).get("company")
                        or ""
                    ),
                    "rank": item.get("rank"),
                }
                for item in leads[:10]
            ],
        },
    }
