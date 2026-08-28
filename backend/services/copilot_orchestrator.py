"""Bounded multi-step orchestration over the existing Copilot tool registry.

This module owns sequencing only.  It does not implement domain operations,
persist state, resolve workspaces, or authorize users: those remain the
responsibility of the existing Copilot tool executor and its domain adapters.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from services.copilot_tools import COPILOT_TOOLS


logger = logging.getLogger(__name__)


MAX_PLAN_STEPS = 3
MAX_TOOL_CALLS = 4  # three planned calls plus one final canonical re-read
MAX_ORCHESTRATION_SECONDS = 12.0

ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class PlannedToolStep:
    tool: str
    inputs: dict[str, Any]
    source: str = "plan"


_STEP_INPUT_FIELDS = frozenset({
    "search_context", "lead_ids", "filters", "sort", "limit",
    "campaign_id", "draft_id", "draft_ids", "conversation_id",
    "knowledge_query", "knowledge_categories", "knowledge_item_id",
    "analytics_scope", "edit_request", "send_at", "reply_body",
    "campaign", "campaign_updates", "force", "reason",
})

_READ_REPLAN_FALLBACKS = {
    # A campaign-specific metric request with no selected/available campaign
    # can truthfully fall back to the workspace aggregate.  No mutation or
    # fabricated campaign selection is involved.
    "analytics.campaign.summary": "analytics.workspace.summary",
    # When a particular conversation is unavailable, the existing inbox
    # recommendation read is the safest grounded alternative.
    "inbox.conversation.analyze": "inbox.conversation.recommend",
    "inbox.conversation.summary": "inbox.conversation.recommend",
}

_MUTATION_VERIFICATION_TOOLS = {
    "lead.save": "lead.read",
    "lead.approve": "lead.read",
    "lead.reject": "lead.read",
    "campaign.refine": "campaign.read",
    "outreach.draft.refine": "outreach.drafts.read",
    "outreach.draft.approve": "outreach.drafts.read",
    "inbox.reply.send": "inbox.conversation.read",
}


def has_multi_step_plan(decision: dict[str, Any]) -> bool:
    """Whether a router-produced plan requests orchestration.

    Normal single-tool turns keep their existing response path untouched.
    """
    return isinstance(decision.get("plan"), list) and len(decision["plan"]) > 1


def build_plan(decision: dict[str, Any]) -> tuple[list[PlannedToolStep], str | None]:
    """Validate untrusted model planning data against the registered tools."""
    raw_plan = decision.get("plan")
    if not isinstance(raw_plan, list):
        return [], "No multi-step plan was supplied."
    if not raw_plan:
        return [], "The plan contains no steps."
    if len(raw_plan) > MAX_PLAN_STEPS:
        return [], f"The plan exceeds the {MAX_PLAN_STEPS}-step limit."

    plan: list[PlannedToolStep] = []
    mutation_count = 0
    for index, raw_step in enumerate(raw_plan):
        if not isinstance(raw_step, dict):
            return [], "The plan contains an invalid step."
        tool_name = str(raw_step.get("action") or raw_step.get("tool") or "").strip()
        tool = COPILOT_TOOLS.get(tool_name)
        if tool is None:
            return [], f"The plan requested an unavailable tool: {tool_name or 'unknown'}."
        if tool_name in {"discovery.search", "discovery.refine"} and index != len(raw_plan) - 1:
            return [], "A Discovery job must be the final planned step because its results are asynchronous."
        inputs = {
            key: value for key, value in raw_step.items()
            if key in _STEP_INPUT_FIELDS
        }
        if not tool.read_only and tool_name not in {"discovery.search", "discovery.refine"}:
            mutation_count += 1
        plan.append(PlannedToolStep(tool=tool_name, inputs=inputs))

    # Phase 4 supports a retrieve/reason/mutate/verify flow. Multiple durable
    # mutations require idempotency/recovery semantics and remain Phase 6.
    if mutation_count > 1:
        return [], "A multi-step Copilot plan may include only one state-changing action."
    return plan, None


def _decision_for_step(base: dict[str, Any], step: PlannedToolStep) -> dict[str, Any]:
    """Merge only allowlisted planner inputs into server-owned turn context."""
    return {
        **base,
        **step.inputs,
        "action": step.tool,
    }


def _apply_authoritative_result(decision: dict[str, Any], result: dict[str, Any]) -> None:
    """Carry canonical identifiers forward; never accept model-invented IDs."""
    payload = result.get("result")
    if not isinstance(payload, dict):
        return

    campaign = payload.get("campaign")
    if isinstance(campaign, dict) and campaign.get("id"):
        decision["campaign_id"] = str(campaign["id"])
    elif payload.get("campaign_id"):
        decision["campaign_id"] = str(payload["campaign_id"])

    draft = payload.get("draft")
    if isinstance(draft, dict) and draft.get("id"):
        decision["draft_id"] = str(draft["id"])
    conversation = payload.get("conversation")
    if isinstance(conversation, dict) and conversation.get("conversation_id"):
        decision["conversation_id"] = str(conversation["conversation_id"])

    discovery_id = payload.get("discovery_id")
    if discovery_id:
        decision["discovery_id"] = str(discovery_id)
    leads = payload.get("leads")
    if isinstance(leads, list) and leads:
        lead_ids = [str(lead.get("id")) for lead in leads if isinstance(lead, dict) and lead.get("id")]
        if lead_ids:
            decision["lead_ids"] = lead_ids


def _replan_after_failure(step: PlannedToolStep, result: dict[str, Any]) -> PlannedToolStep | None:
    """Choose a safe, read-only fallback only from an actual tool result."""
    # A genuine failure remains explicit. Only an unavailable selected
    # resource can be truthfully replaced with a broader read scope.
    if result.get("status") != "unavailable":
        return None
    fallback = _READ_REPLAN_FALLBACKS.get(step.tool)
    if not fallback:
        return None
    return PlannedToolStep(tool=fallback, inputs={}, source=f"fallback:{step.tool}")


async def execute_copilot_plan(
    decision: dict[str, Any],
    execute_tool: ToolExecutor,
    *,
    time_limit_seconds: float = MAX_ORCHESTRATION_SECONDS,
) -> dict[str, Any]:
    """Execute a short, result-aware plan through the existing tool boundary.

    ``execute_tool`` is injected by the API route and retains the authenticated
    user, selected workspace, confirmation, and runner bindings.  This layer
    therefore cannot widen authority by accepting model-supplied identity or
    workspace fields.
    """
    plan, error = build_plan(decision)
    if error:
        logger.info("copilot.plan.rejected reason=%s", error)
        return {"ok": False, "status": "plan_invalid", "reason": error, "steps": []}

    logger.info("copilot.plan.started steps=%s tools=%s", len(plan), ",".join(step.tool for step in plan))

    deadline = time.monotonic() + max(0.01, time_limit_seconds)
    working_decision = dict(decision)
    remaining = list(plan)
    completed: list[dict[str, Any]] = []
    tool_calls = 0

    while remaining:
        if tool_calls >= MAX_TOOL_CALLS:
            logger.warning("copilot.plan.tool_limit_reached calls=%s", tool_calls)
            return {
                "ok": False,
                "status": "tool_limit_reached",
                "reason": "Copilot stopped because the tool-call limit was reached.",
                "steps": completed,
            }
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            logger.warning("copilot.plan.time_limit_reached phase=before_step calls=%s", tool_calls)
            return {
                "ok": False,
                "status": "time_limit_reached",
                "reason": "Copilot stopped because the operation took too long to inspect safely.",
                "steps": completed,
            }

        step = remaining.pop(0)
        step_decision = _decision_for_step(working_decision, step)
        logger.info("copilot.plan.tool_started tool=%s source=%s call=%s", step.tool, step.source, tool_calls + 1)
        try:
            tool_result = await asyncio.wait_for(
                execute_tool(step.tool, step_decision), timeout=remaining_seconds
            )
        except asyncio.TimeoutError:
            logger.warning("copilot.plan.tool_timeout tool=%s", step.tool)
            return {
                "ok": False,
                "status": "time_limit_reached",
                "reason": "Copilot stopped because a tool did not respond in time.",
                "steps": completed,
            }
        except Exception:
            logger.exception("copilot.plan.tool_exception tool=%s", step.tool)
            return {
                "ok": False,
                "status": "failed",
                "reason": "Copilot could not complete a planned tool call.",
                "steps": completed,
            }

        tool_calls += 1
        completed.append({
            "tool": step.tool,
            "source": step.source,
            "status": str(tool_result.get("status") or "unknown"),
            "ok": bool(tool_result.get("ok")),
            "result": tool_result.get("result"),
        })
        logger.info(
            "copilot.plan.tool_finished tool=%s status=%s ok=%s",
            step.tool, tool_result.get("status"), bool(tool_result.get("ok")),
        )

        # A durable job is intentionally asynchronous. The existing Phase 3
        # monitor owns its lifecycle; do not run later steps against a result
        # that does not exist yet.
        if tool_result.get("operation") and tool_result.get("status") == "accepted":
            logger.info("copilot.plan.async_accepted tool=%s", step.tool)
            return {
                "ok": bool(tool_result.get("ok")),
                "status": "accepted",
                "operation": tool_result.get("operation"),
                "result": tool_result.get("result"),
                "steps": completed,
            }

        if not tool_result.get("ok"):
            fallback = _replan_after_failure(step, tool_result)
            if fallback and tool_calls < MAX_TOOL_CALLS:
                logger.info("copilot.plan.replanned from=%s to=%s", step.tool, fallback.tool)
                remaining.insert(0, fallback)
                continue
            return {
                "ok": False,
                "status": str(tool_result.get("status") or "failed"),
                "reason": str(tool_result.get("reason") or "A planned tool failed."),
                "steps": completed,
            }

        _apply_authoritative_result(working_decision, tool_result)

    mutation_steps = [step for step in plan if not COPILOT_TOOLS[step.tool].read_only]
    if mutation_steps:
        mutation = mutation_steps[-1]
        verification_tool = _MUTATION_VERIFICATION_TOOLS.get(mutation.tool)
        if verification_tool:
            if tool_calls >= MAX_TOOL_CALLS or deadline - time.monotonic() <= 0:
                logger.warning("copilot.plan.verification_unavailable tool=%s", mutation.tool)
                return {
                    "ok": False,
                    "status": "verification_failed",
                    "reason": "The change completed but Copilot could not verify its final state in time.",
                    "steps": completed,
                }
            verification_decision = _decision_for_step(
                working_decision,
                PlannedToolStep(tool=verification_tool, inputs={}, source=f"verify:{mutation.tool}"),
            )
            try:
                logger.info("copilot.plan.verification_started mutation=%s tool=%s", mutation.tool, verification_tool)
                verification = await asyncio.wait_for(
                    execute_tool(verification_tool, verification_decision),
                    timeout=deadline - time.monotonic(),
                )
            except (asyncio.TimeoutError, Exception):
                verification = {"ok": False, "status": "verification_failed"}
            tool_calls += 1
            completed.append({
                "tool": verification_tool,
                "source": f"verify:{mutation.tool}",
                "status": str(verification.get("status") or "unknown"),
                "ok": bool(verification.get("ok")),
                "result": verification.get("result"),
            })
            if not verification.get("ok"):
                logger.warning("copilot.plan.verification_failed mutation=%s", mutation.tool)
                return {
                    "ok": False,
                    "status": "verification_failed",
                    "reason": "Copilot could not verify the final workspace state after the change.",
                    "steps": completed,
                }

    final = completed[-1] if completed else {}
    logger.info("copilot.plan.completed steps=%s", len(completed))
    return {
        "ok": True,
        "status": "completed",
        "result": final.get("result") or {},
        "steps": completed,
    }
