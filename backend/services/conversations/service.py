"""Durable Inbox reasoning, planning, and reply-preparation use cases."""
from __future__ import annotations

import asyncio
from typing import Any

from services.conversation_intelligence.intelligence_pipeline import IntelligencePipeline
from services.conversations.conversation_store import conversation_owned_by, conversation_store
from services.planner.exceptions import PlanningValidationError
from services.planner.planning_pipeline import get_pipeline as get_planning_pipeline
from services.reasoning.reasoning_pipeline import get_pipeline as get_reasoning_pipeline


def owned_conversation(conversation_id: str, owner_id: str):
    """Load a durable Inbox conversation only when it belongs to the owner."""
    conversation = conversation_store.get_conversation(conversation_id)
    if conversation is None or not conversation_owned_by(conversation, owner_id):
        return None
    return conversation


def _latest_intelligence(conversation_id: str):
    messages = conversation_store.get_messages_for_conversation(conversation_id)
    if not messages:
        return None, messages
    latest = messages[-1]
    intelligence = IntelligencePipeline().analyze_message(
        message_body=latest.body or latest.body_preview or "",
        lead_id=conversation_id,
        subject=latest.subject or "",
    )
    return intelligence, messages


def conversation_reasoning(conversation_id: str) -> dict[str, Any]:
    """Return current reasoning over the durable latest Inbox message."""
    intelligence, _ = _latest_intelligence(conversation_id)
    if intelligence is None:
        return {"ok": True, "reasoning": None}
    return {"ok": True, "reasoning": get_reasoning_pipeline().reason(intelligence).to_dict()}


def _plan_explainability(plan) -> dict[str, Any]:
    from services.planner.planning_models import PlanGoal

    goal = plan.goal or PlanGoal()
    return {
        "goal": {"outcome": goal.outcome, "target_action": goal.target_action, "priority": goal.priority},
        "strategy": plan.strategy,
        "task_chain": [
            {
                "id": task.id,
                "label": task.label,
                "type": task.type.value,
                "reason": task.reasoning_trace,
                "goal": task.reasoning_goal,
                "approval": task.approval.value,
            }
            for task in plan.tasks
        ],
        "total_tasks": len(plan.tasks),
        "strategy_version": plan.version,
    }


def conversation_plan(conversation_id: str) -> dict[str, Any]:
    """Create a validated plan from the latest durable Inbox message."""
    intelligence, _ = _latest_intelligence(conversation_id)
    if intelligence is None:
        return {"ok": True, "plan": None, "validation": None}
    reasoning = get_reasoning_pipeline().reason(intelligence)
    try:
        plan, validation = get_planning_pipeline().plan(reasoning)
    except PlanningValidationError as error:
        return {
            "ok": False,
            "error": error.message,
            "error_type": "PlanningValidationError",
            "validation": {"valid": False, "issues": error.context.get("issues", []), "warnings": []},
        }
    validation_data = None
    if validation:
        validation_data = {
            "valid": validation.valid,
            "issues": [
                {"severity": issue.severity, "code": issue.code, "message": issue.message, "task_id": issue.task_id, "suggested_fix": issue.suggested_fix}
                for issue in validation.issues
            ],
            "warnings": [
                {"severity": warning.severity, "code": warning.code, "message": warning.message, "task_id": warning.task_id, "suggested_fix": warning.suggested_fix}
                for warning in validation.warnings
            ],
        }
    return {
        "ok": True,
        "plan": plan.to_dict(),
        "graph": {
            "nodes": [
                {"id": task.id, "type": task.type.value, "status": task.status.value, "label": task.label, "dependencies": task.dependencies, "approval": task.approval.value}
                for task in plan.tasks
            ],
            "edges": [{"source": source, "target": target} for source, target in plan.get_all_dependency_pairs()],
        },
        "explainability": _plan_explainability(plan),
        "validation": validation_data,
    }


async def generate_reply(conversation_id: str, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Prepare a reply grounded in the durable conversation and owner-scoped knowledge."""
    # Keep these imports at the provider boundary: generation tests replace
    # the production model implementation there, and this service must not
    # capture it before that boundary is configured.
    from services.reply_generation.generation_models import GenerationStyle
    from services.reply_generation.generation_pipeline import GenerationPipeline

    intelligence, messages = _latest_intelligence(conversation_id)
    if intelligence is None:
        return {"ok": True, "generation": None}
    style_names = payload.get("styles", ["professional"])
    styles = []
    for name in style_names:
        try:
            styles.append(GenerationStyle(name))
        except ValueError:
            continue
    if not styles:
        styles = [GenerationStyle.PROFESSIONAL]
    instruction = str(payload.get("instruction") or "").strip()
    follow_up = bool(payload.get("follow_up"))
    latest = messages[-1]
    knowledge_context: dict[str, Any] = {}
    if owner_id:
        from services.knowledge.context_adapter import retrieve_knowledge_context

        query = " ".join(part for part in (
            "follow-up" if follow_up else "reply",
            latest.subject or "",
            (latest.body or latest.body_preview or "")[:500],
        ) if part)
        knowledge_context = (await retrieve_knowledge_context(
            owner_id, query=query, categories=["company", "messaging", "sales_offer"], limit=8,
        )).to_dict()
    recent_messages = []
    source_messages = [message for message in messages if message.direction == "outbound"][-3:] if follow_up else messages[-3:]
    for message in source_messages:
        preview = message.body_preview or (message.body or "")[:200]
        if preview:
            prefix = "You" if follow_up or message.direction != "inbound" else "Prospect"
            recent_messages.append(f"[{prefix}]: {preview}")
    reasoning = get_reasoning_pipeline().reason(intelligence)
    result = await asyncio.to_thread(
        GenerationPipeline().generate,
        intelligence=intelligence,
        reasoning=reasoning,
        styles=styles,
        variant_count=payload.get("variant_count", 1),
        latest_messages=recent_messages,
        instruction=instruction or None,
        follow_up=follow_up,
        knowledge_context=knowledge_context,
    )
    return {"ok": True, "generation": result.to_dict(), "reasoning": reasoning.to_dict()}
