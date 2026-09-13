"""Application service for one authenticated, workspace-scoped Copilot turn."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from typing import Any

import services.identity.dependencies as identity_dependencies
import services.workspace.access as workspace_access
from services.workspace import context as workspace_context_service
from services.conversational_response_generator import (
    classify_copilot_read_question,
    decide_copilot_intent,
)
from services.copilot.memory import CopilotMemoryService, merge_turn_history
from services.copilot.executions import CopilotExecutionService
from services.copilot.tools import (
    COPILOT_TOOLS,
    PHASE2_MUTATION_TOOLS,
    execute_copilot_tool,
    mutation_confirmation_state,
    select_copilot_tool,
)
import services.copilot.runners as copilot_runners
from services.copilot_orchestrator import execute_copilot_plan, has_multi_step_plan
from services.conversation_engine import _message
from services.conversational_response_generator import generate_copilot_response
from services.supabase import get_user_preferences


log = logging.getLogger("loqi")


@dataclass
class PreparedCopilotTurn:
    """Trusted context prepared before a Copilot tool or response is selected."""

    user_id: str
    workspace_id: str
    session_token: str
    conversation_key: str
    memory: CopilotMemoryService
    workspace_context: dict[str, Any]
    decision: dict[str, Any]
    message_history: list[dict[str, Any]]


@dataclass
class DirectToolGate:
    """One direct tool's confirmation decision, before HTTP translation."""

    status: str
    tool_name: str
    decision: dict[str, Any]
    reason: str = ""


def _conversation_key(conversation_id: str | None, session_token: str) -> str:
    """Use a client chat id when supplied, otherwise a token-safe legacy key."""
    key = str(conversation_id or "").strip()[:128]
    if key:
        return key
    return "legacy-" + hashlib.sha256(session_token.encode()).hexdigest()[:32]


async def prepare_copilot_turn(
    *,
    request,
    session_token: str,
    text: str,
    current_page: str | None,
    page_context: dict[str, Any] | None,
    message_history: list[dict[str, Any]] | None,
    conversation_id: str | None,
    active_search: dict[str, Any] | None,
) -> PreparedCopilotTurn:
    """Resolve trusted context and intent for a single Copilot request.

    Identity and workspace authority come only from the authenticated request.
    Client page/context values remain conversational inputs, never authority.
    ``execute_prepared_copilot_turn`` owns the subsequent confirmation,
    execution, durable outcome, and response-envelope stages.
    """
    user_id, _canonical_session_id = await identity_dependencies.resolve_web_session(request)
    selected_workspace = await workspace_access.resolve_selected_workspace_context(request, user_id)
    workspace_id = str(selected_workspace.workspace_id or "")
    if not workspace_id:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="No accessible workspace")

    conversation_key = _conversation_key(conversation_id, session_token)
    memory = CopilotMemoryService()
    remembered_context = await memory.retrieve(
        user_id=user_id,
        workspace_id=workspace_id,
        conversation_key=conversation_key,
    )
    try:
        user_preferences = await asyncio.to_thread(get_user_preferences, user_id)
    except Exception:
        user_preferences = None
    if isinstance(user_preferences, dict):
        remembered_context["user_preferences"] = user_preferences

    bounded_history = merge_turn_history(remembered_context, message_history)
    log.info(
        "COPILOT_REQUEST path=post_web_session_message workspace=%s page=%s text_chars=%s",
        workspace_id,
        current_page or "(unset)",
        len(text or ""),
    )
    workspace_context = await asyncio.to_thread(
        workspace_context_service.build_workspace_context,
        session_token,
        current_page=current_page,
        page_context=page_context,
        user_id=user_id,
        workspace_id=workspace_id,
    )
    workspace_context["copilot_memory"] = remembered_context
    analysis = workspace_context.get("analysis", {})
    snapshot = workspace_context.get("snapshot", {})
    current_focus = analysis.get("current_focus", {})
    recommended_action = analysis.get("recommended_next_action", {})
    priorities = analysis.get("campaign_priorities", [])
    health = analysis.get("workspace_health", {})
    print(
        f"[COPILOT_DEBUG] page={current_page} "
        f"message=\"{text[:60]}\" "
        f"campaign_count={snapshot.get('campaign_count', 0)} "
        f"pending_drafts={snapshot.get('drafts', {}).get('pending', 0)} "
        f"campaigns_ready={snapshot.get('campaigns_ready', 0)} "
        f"focus={current_focus.get('focus', 'none')} "
        f"recommended={recommended_action.get('title', 'none')} "
        f"top_priority={priorities[0].get('name', 'none') if priorities else 'none'} "
        f"health={health.get('overall_health', 'unknown')} "
        f"timeline_events={len(snapshot.get('timeline', []))} "
        f"memory_action={snapshot.get('memory', {}).get('last_action', 'none')}"
    )

    decision = classify_copilot_read_question(
        text,
        page_context=page_context,
        active_search=active_search,
        message_history=bounded_history,
    )
    if decision is None:
        decision = await asyncio.to_thread(
            decide_copilot_intent,
            text,
            workspace_context=workspace_context,
            message_history=bounded_history,
            active_search=active_search,
        )
    decision = {
        **decision,
        "user_message": text,
        "message_history": bounded_history,
        "active_search": active_search or {},
        "page_context": page_context or {},
        "current_page": current_page or "",
    }
    await memory.record_turn(
        user_id=user_id,
        workspace_id=workspace_id,
        conversation_key=conversation_key,
        user_text=text,
        intent=str(decision.get("intent") or ""),
        tool=str(decision.get("action") or ""),
    )
    return PreparedCopilotTurn(
        user_id=user_id,
        workspace_id=workspace_id,
        session_token=session_token,
        conversation_key=conversation_key,
        memory=memory,
        workspace_context=workspace_context,
        decision=decision,
        message_history=bounded_history,
    )


def gate_direct_tool_execution(
    *,
    tool_name: str,
    decision: dict[str, Any],
    user_text: str,
) -> DirectToolGate:
    """Apply the existing confirmation policy before a direct tool can run."""
    tool = COPILOT_TOOLS.get(tool_name)
    if tool is None:
        return DirectToolGate("unavailable", tool_name, decision)
    guarded_decision = dict(decision)
    if tool.read_only or tool_name in {"discovery.search", "discovery.refine"}:
        return DirectToolGate("execute", tool_name, guarded_decision)
    if tool_name not in PHASE2_MUTATION_TOOLS:
        return DirectToolGate(
            "unavailable",
            tool_name,
            guarded_decision,
            "That operation is not available in Copilot yet because its safe execution path has not been verified.",
        )
    confirmation = mutation_confirmation_state(tool_name, user_text)
    if confirmation == "declined":
        return DirectToolGate("declined", tool_name, guarded_decision, "Understood — no changes were made.")
    if confirmation != "confirmed":
        return DirectToolGate(
            "confirmation_required",
            tool_name,
            guarded_decision,
            f"I have not made any changes. Explicitly confirm this by using the requested action, for example: ‘Confirm {tool_name.replace('.', ' ')}.’",
        )
    guarded_decision["confirmed"] = True
    return DirectToolGate("execute", tool_name, guarded_decision)


async def execute_tool_at_boundary(
    *,
    tool_name: str,
    decision: dict[str, Any],
    user_id: str,
    workspace_id: str,
    session_token: str,
    request_id: str | None,
    conversation_key: str,
    request,
) -> dict[str, Any]:
    """Run one validated tool through its canonical idempotency boundary."""
    tool = COPILOT_TOOLS.get(tool_name)
    if tool is None:
        return {"ok": False, "status": "unsupported", "tool": tool_name}

    async def invoke() -> dict[str, Any]:
        return await execute_copilot_tool(
            tool_name,
            user_id=user_id,
            workspace_id=workspace_id,
            session_token=session_token,
            decision=decision,
            discovery_runner=copilot_runners.run_discovery,
            campaign_runner=copilot_runners.run_campaign,
            outreach_runner=copilot_runners.run_outreach,
            inbox_runner=lambda *args: copilot_runners.run_inbox(*args, request=request),
            knowledge_runner=copilot_runners.run_knowledge,
            analytics_runner=copilot_runners.run_analytics,
        )

    if tool.read_only:
        return await invoke()
    return await CopilotExecutionService().execute(
        tool_name=tool_name,
        user_id=user_id,
        workspace_id=workspace_id,
        request_id=request_id,
        conversation_key=conversation_key,
        decision=decision,
        operation=invoke,
    )


async def execute_copilot_plan_turn(
    *,
    decision: dict[str, Any],
    user_text: str,
    user_id: str,
    workspace_id: str,
    session_token: str,
    request_id: str | None,
    conversation_key: str,
    memory: CopilotMemoryService,
    request,
) -> dict[str, Any] | None:
    """Execute a bounded Copilot plan and record its durable outcome.

    The planner never confirms mutations: each planned step repeats the same
    explicit user-text confirmation checks before the shared C2 boundary can
    invoke a canonical domain tool.
    """
    if not has_multi_step_plan(decision):
        return None

    async def execute_planned_tool(
        planned_tool_name: str,
        planned_decision: dict[str, Any],
    ) -> dict[str, Any]:
        tool = COPILOT_TOOLS.get(planned_tool_name)
        if tool is None:
            return {
                "ok": False,
                "status": "unavailable",
                "tool": planned_tool_name,
                "reason": "That planned capability is not available.",
            }
        guarded_decision = dict(planned_decision)
        if not tool.read_only and planned_tool_name not in {"discovery.search", "discovery.refine"}:
            if planned_tool_name not in PHASE2_MUTATION_TOOLS:
                return {
                    "ok": False,
                    "status": "unavailable",
                    "tool": planned_tool_name,
                    "reason": "That operation is not available in Copilot yet because its safe execution path has not been verified.",
                }
            confirmation = mutation_confirmation_state(planned_tool_name, user_text)
            if confirmation == "declined":
                return {
                    "ok": False,
                    "status": "declined",
                    "tool": planned_tool_name,
                    "reason": "Understood — no changes were made.",
                }
            if confirmation != "confirmed":
                return {
                    "ok": False,
                    "status": "confirmation_required",
                    "tool": planned_tool_name,
                    "reason": f"I have not made any changes. Explicitly confirm this by using the requested action, for example: ‘Confirm {planned_tool_name.replace('.', ' ')}.’",
                }
            guarded_decision["confirmed"] = True
        return await execute_tool_at_boundary(
            tool_name=planned_tool_name,
            decision=guarded_decision,
            user_id=user_id,
            workspace_id=workspace_id,
            session_token=session_token,
            request_id=request_id,
            conversation_key=conversation_key,
            request=request,
        )

    orchestration = await execute_copilot_plan(decision, execute_planned_tool)
    await memory.record_outcome(
        user_id=user_id,
        workspace_id=workspace_id,
        conversation_key=conversation_key,
        tool="copilot.orchestration",
        status=str(orchestration.get("status") or ""),
        operation=orchestration.get("operation"),
    )
    return orchestration


def _tool_failure_reason(tool_name: str) -> str:
    """Return the stable user-facing failure contract for a failed tool."""
    return f"{tool_name} could not be completed. Please try again."


async def _grounded_response_text(
    user_message: str,
    decision: dict[str, Any],
    workspace_context: dict[str, Any],
    tool_name: str,
    result: dict[str, Any],
) -> str:
    """Explain an authoritative result without inventing workspace facts."""
    return await asyncio.to_thread(
        generate_copilot_response,
        user_message=user_message,
        copilot_context={
            "intent": decision.get("intent"),
            "current_page": decision.get("current_page", ""),
            "page_context": decision.get("page_context") or {},
            "message_history": decision.get("message_history") or [],
            "workspace_context": workspace_context,
            "authoritative_tool": tool_name,
            "authoritative_result": result,
            "mvp_read_only": True,
        },
        context={"user_id": "", "service": "", "target": ""},
    )


def _tool_failure_response(
    *,
    intent: str | None,
    tool_name: str,
    reason: str,
    data_status: Any = "failed",
    operation_status: Any = "failed",
    operation_error: Any = None,
    message_type: str = "tool",
) -> dict[str, Any]:
    """Build the frozen HTTP envelope for a failed domain tool."""
    return {
        "ok": False,
        "intent": intent,
        "messages": [_message(
            role="assistant", message_type=message_type, text=reason,
            data={"tool": tool_name, "status": data_status},
        )],
        "events": [{"type": "tool.failed", "tool": tool_name}],
        "operation": {"kind": tool_name, "status": operation_status, "error": operation_error},
    }


async def execute_prepared_copilot_turn(
    *,
    prepared: PreparedCopilotTurn,
    user_text: str,
    copilot_context: dict[str, Any],
    legacy_user_id: str | None,
    request_id: str | None,
    request,
) -> dict[str, Any]:
    """Execute one prepared Copilot turn and return the frozen web envelope.

    This is the canonical Copilot application boundary: trusted identity and
    workspace scope have already been resolved by ``prepare_copilot_turn``;
    this operation performs planning, confirmation, execution, durable outcome
    recording, and response translation for every tool family.
    """
    decision = prepared.decision
    workspace_context = prepared.workspace_context
    tool_name = select_copilot_tool(decision)

    orchestration = await execute_copilot_plan_turn(
        decision=decision,
        user_text=user_text,
        user_id=prepared.user_id,
        workspace_id=prepared.workspace_id,
        session_token=prepared.session_token,
        request_id=request_id,
        conversation_key=prepared.conversation_key,
        memory=prepared.memory,
        request=request,
    )
    if orchestration is not None:
        if orchestration.get("status") == "accepted":
            started = orchestration.get("operation") or {}
            search_context = decision.get("search_context") or {}
            active_context = {
                **search_context,
                "discovery_id": started.get("discovery_id"),
                "job_id": started.get("job_id"),
            }
            return {
                "ok": bool(orchestration.get("ok")),
                "intent": decision.get("intent"),
                "messages": [_message(
                    role="assistant", message_type="tool",
                    text="I’m starting a Discovery search and will report back when the results are persisted.",
                    data={"operation": "search_discovery", "tool": "copilot.orchestration", "search_context": active_context, **started},
                )],
                "events": [{"type": "tool.started", "tool": "copilot.orchestration", "operation": "search_discovery", **started}],
                "operation": {"kind": "search_discovery", "tool": "copilot.orchestration", "search_context": active_context, **started},
            }
        if not orchestration.get("ok"):
            reason = str(orchestration.get("reason") or "Copilot could not complete the planned steps.")
            return {
                "ok": False,
                "intent": decision.get("intent"),
                "messages": [_message(
                    role="assistant", message_type="tool", text=reason,
                    data={"tool": "copilot.orchestration", "status": orchestration.get("status"), "steps": orchestration.get("steps") or []},
                )],
                "events": [{"type": "tool.failed", "tool": "copilot.orchestration", "status": orchestration.get("status")}],
                "operation": {"kind": "copilot.orchestration", "status": orchestration.get("status"), "error": orchestration.get("reason")},
            }
        steps = orchestration.get("steps") or []
        completed_tools = [str(step.get("tool") or "") for step in steps if step.get("ok")]
        verified = any(str(step.get("source") or "").startswith("verify:") for step in steps)
        text = "Retrieved the requested current workspace data."
        if completed_tools:
            text = f"{'Completed and verified' if verified else 'Retrieved'}: {', '.join(completed_tools)}."
        return {
            "ok": True,
            "intent": decision.get("intent"),
            "messages": [_message(
                role="assistant", message_type="text", text=text,
                data={"tool": "copilot.orchestration", "result": orchestration.get("result") or {}, "steps": steps, "verified": verified},
            )],
            "events": [{"type": "tool.completed", "tool": "copilot.orchestration", "steps": steps}],
        }

    if (
        tool_name is None
        and decision.get("intent") in {"read", "clarification"}
        and (decision.get("knowledge_categories") or str(decision.get("knowledge_query") or "").strip())
    ):
        try:
            from services.knowledge.context_adapter import retrieve_knowledge_context

            knowledge = await retrieve_knowledge_context(
                prepared.user_id,
                query=str(decision.get("knowledge_query") or user_text),
                categories=decision.get("knowledge_categories") or None,
                workspace_id=prepared.workspace_id,
            )
            workspace_context["knowledge_context"] = knowledge.to_dict()
        except Exception as error:
            log.warning("Copilot semantic Knowledge retrieval unavailable: %s", error)

    if tool_name:
        gate = gate_direct_tool_execution(tool_name=tool_name, decision=decision, user_text=user_text)
        if gate.status != "execute":
            event_type = {
                "unavailable": "tool.unavailable",
                "declined": "tool.declined",
                "confirmation_required": "tool.confirmation_required",
            }[gate.status]
            status = gate.status
            return {
                "ok": False,
                "intent": decision.get("intent"),
                "messages": [_message(
                    role="assistant", message_type="text", text=gate.reason or "That operation is not available in Copilot yet because its safe execution path has not been verified.",
                    data={"tool": tool_name, "status": status},
                )],
                "events": [{"type": event_type, "tool": tool_name}],
                "operation": {"kind": tool_name, "status": status},
            }

        decision = gate.decision
        log.info(
            "COPILOT_DECISION workspace=%s intent=%s tool=%s mode=%s",
            prepared.workspace_id, decision.get("intent"), tool_name, decision.get("mode"),
        )
        try:
            tool_result = await execute_tool_at_boundary(
                tool_name=tool_name,
                decision=decision,
                user_id=prepared.user_id,
                workspace_id=prepared.workspace_id,
                session_token=prepared.session_token,
                request_id=request_id,
                conversation_key=prepared.conversation_key,
                request=request,
            )
        except Exception:
            log.exception("Copilot tool failed tool=%s", tool_name)
            tool_result = {
                "ok": False,
                "status": "failed",
                "tool": tool_name,
                "reason": _tool_failure_reason(tool_name),
            }
        await prepared.memory.record_outcome(
            user_id=prepared.user_id,
            workspace_id=prepared.workspace_id,
            conversation_key=prepared.conversation_key,
            tool=tool_name,
            status=str(tool_result.get("status") or ""),
            operation=tool_result.get("operation"),
        )
        if tool_name.startswith("campaign."):
            if tool_result.get("ok"):
                result = tool_result.get("result") or {}
                campaign = result.get("campaign") or {}
                if tool_name in {"campaign.list", "campaign.drafts"}:
                    text = await _grounded_response_text(user_text, decision, workspace_context, tool_name, result)
                elif campaign:
                    text = f"Campaign “{campaign.get('name') or 'Untitled campaign'}” was updated and verified in your workspace."
                else:
                    text = f"{tool_name.replace('.', ' ').capitalize()} completed."
                response: dict[str, Any] = {
                    "ok": True, "intent": decision.get("intent"),
                    "messages": [_message(role="assistant", message_type="text", text=text, data={"tool": tool_name, "result": result, "operation": tool_result.get("operation")})],
                    "events": [{"type": "tool.completed", "tool": tool_name, "result": result}],
                }
                if tool_result.get("operation"):
                    response["operation"] = tool_result["operation"]
                return response
            return _tool_failure_response(intent=decision.get("intent"), tool_name=tool_name, reason=str(tool_result.get("reason") or "Campaign operation failed."), data_status=tool_result.get("status", "failed"), operation_status=tool_result.get("status", "failed"), operation_error=tool_result.get("reason"), message_type="text")

        if tool_name.startswith("outreach."):
            if tool_result.get("ok"):
                result = tool_result.get("result") or {}
                if tool_name == "outreach.drafts.read":
                    text = await _grounded_response_text(user_text, decision, workspace_context, tool_name, result)
                elif tool_name == "outreach.draft.generate":
                    text = "Draft generation has started for this campaign."
                elif tool_name == "outreach.draft.refine":
                    text = "The draft was updated and verified in your workspace."
                elif tool_name == "outreach.draft.approve":
                    text = "The draft was approved and verified in your workspace."
                else:
                    text = f"{tool_name.replace('.', ' ').capitalize()} completed."
                response = {
                    "ok": True, "intent": decision.get("intent"),
                    "messages": [_message(role="assistant", message_type="text", text=text, data={"tool": tool_name, "result": result, "operation": result.get("operation")})],
                    "events": [{"type": "tool.completed", "tool": tool_name, "result": result}],
                }
                if result.get("operation"):
                    response["operation"] = result["operation"]
                return response
            return _tool_failure_response(intent=decision.get("intent"), tool_name=tool_name, reason=str(tool_result.get("reason") or "Outreach operation failed."), data_status=tool_result.get("status", "failed"), operation_status=tool_result.get("status", "failed"), operation_error=tool_result.get("reason"))

        if tool_name.startswith("inbox."):
            if tool_result.get("ok"):
                result = tool_result.get("result") or {}
                if tool_name != "inbox.reply.send":
                    text = await _grounded_response_text(user_text, decision, workspace_context, tool_name, result)
                else:
                    conversation = result.get("conversation") or {}
                    text = f"The reply was sent and the conversation is now {conversation.get('status') or result.get('status') or 'updated'}."
                return {
                    "ok": True, "intent": decision.get("intent"),
                    "messages": [_message(role="assistant", message_type="text", text=text, data={"tool": tool_name, "result": result})],
                    "events": [{"type": "tool.completed", "tool": tool_name, "result": result}],
                }
            return _tool_failure_response(intent=decision.get("intent"), tool_name=tool_name, reason=str(tool_result.get("reason") or "Inbox operation failed."), data_status=tool_result.get("status", "failed"), operation_status=tool_result.get("status", "failed"), operation_error=tool_result.get("reason"))

        if tool_name.startswith("knowledge."):
            if tool_result.get("ok"):
                result = tool_result.get("result") or {}
                found = len(result.get("items") or []) + len(result.get("sources") or [])
                text = await _grounded_response_text(user_text, decision, workspace_context, tool_name, result) if found else "I couldn't find matching Knowledge in your workspace, so I won't infer an answer."
                return {
                    "ok": True, "intent": decision.get("intent"),
                    "messages": [_message(role="assistant", message_type="text", text=text, data={"tool": tool_name, "result": result, "grounded": bool(found)})],
                    "events": [{"type": "tool.completed", "tool": tool_name, "result": result}],
                }
            return _tool_failure_response(intent=decision.get("intent"), tool_name=tool_name, reason=str(tool_result.get("reason") or "Knowledge retrieval failed."), data_status=tool_result.get("status", "failed"), operation_status=tool_result.get("status", "failed"), operation_error=tool_result.get("reason"))

        if tool_name.startswith("analytics."):
            if tool_result.get("ok"):
                result = tool_result.get("result") or {}
                metrics = result.get("metrics") or {}
                text = await _grounded_response_text(user_text, decision, workspace_context, tool_name, result) if metrics else "The analytics result contains no metric fields for this context."
                return {
                    "ok": True, "intent": decision.get("intent"),
                    "messages": [_message(role="assistant", message_type="text", text=text, data={"tool": tool_name, "result": result, "authoritative": True})],
                    "events": [{"type": "tool.completed", "tool": tool_name, "result": result}],
                }
            return _tool_failure_response(intent=decision.get("intent"), tool_name=tool_name, reason=str(tool_result.get("reason") or "Analytics are unavailable for this context."), data_status=tool_result.get("status", "failed"), operation_status=tool_result.get("status", "failed"), operation_error=tool_result.get("reason"))

        if tool_name == "discovery.read" or tool_name.startswith("lead."):
            if tool_result.get("ok"):
                result = tool_result.get("result") or {}
                if tool_name == "discovery.read" or tool_name in {"lead.read", "lead.filter", "lead.rank"}:
                    text = await _grounded_response_text(user_text, decision, workspace_context, tool_name, result)
                else:
                    text = f"{tool_name.replace('.', ' ').capitalize()} was completed and verified for {len(result.get('leads') or [])} lead(s)."
                return {
                    "ok": True, "intent": decision.get("intent"),
                    "messages": [_message(role="assistant", message_type="text", text=text, data={"tool": tool_name, "result": result})],
                    "events": [{"type": "tool.completed", "tool": tool_name, "result": result}],
                    "read_result": result,
                }
            return _tool_failure_response(intent=decision.get("intent"), tool_name=tool_name, reason=str(tool_result.get("reason") or "I couldn't retrieve that Discovery."), data_status=tool_result.get("status", "failed"), operation_status="failed", operation_error=tool_result.get("reason"))

        if not tool_result.get("ok"):
            reason = str(tool_result.get("reason") or "Discovery operation failed.")
            return _tool_failure_response(intent=decision.get("intent"), tool_name=tool_name, reason=reason, operation_error=reason)

        started = tool_result.get("operation") or {}
        search_context = tool_result.get("search_context") or {}
        active_context = {
            **search_context,
            "discovery_id": started.get("discovery_id"),
            "job_id": started.get("job_id"),
        }
        return {
            "ok": True,
            "intent": decision.get("intent"),
            "messages": [_message(
                role="assistant", message_type="tool",
                text="I’m starting a Discovery search and will report back when the results are persisted.",
                data={"operation": "search_discovery", "tool": tool_name, "search_context": active_context, **started},
            )],
            "events": [{"type": "tool.started", "tool": tool_name, "operation": "search_discovery", **started}],
            "operation": {"kind": "search_discovery", "tool": tool_name, "search_context": active_context, **started},
        }

    if decision.get("intent") == "action":
        requested_action = str(decision.get("action") or "")
        message = "That action is understood, but the corresponding Loqi capability is not available yet."
        return {
            "ok": False,
            "intent": decision.get("intent"),
            "messages": [_message(role="assistant", message_type="tool", text=message, data={"status": "unsupported", "action": requested_action})],
            "events": [{"type": "tool.unsupported", "action": requested_action}],
            "operation": {"kind": "action", "status": "unsupported", "action": requested_action},
        }

    response_text = await asyncio.to_thread(
        generate_copilot_response,
        user_message=user_text,
        copilot_context={
            **copilot_context,
            "intent": decision.get("intent"),
            "message_history": prepared.message_history,
            "workspace_context": workspace_context,
            "mvp_read_only": True,
        },
        context={"user_id": legacy_user_id, "service": "", "target": ""},
    )
    print(f"[COPILOT_TRACE] page={copilot_context.get('current_page') or '(unset)'} message={user_text[:60]} history_len={len(copilot_context.get('message_history') or [])}")
    return {
        "ok": True,
        "intent": decision.get("intent"),
        "messages": [_message(role="assistant", message_type="text", text=response_text)],
        "events": [],
    }
