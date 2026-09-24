"""Durable Inbox reasoning, planning, and reply-preparation use cases."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from services.conversations.legacy_engine import ConversationEngine
from services.conversation_intelligence.intelligence_pipeline import IntelligencePipeline
from services.conversations.conversation_models import ConversationMessage, ConversationStatus
from services.conversations.conversation_store import conversation_owned_by, conversation_store
from services.conversations.compatibility import record_workflow_message
from services.conversations.legacy_responses import _get_after_draft_variation
from services.enrichment.enrichment_factory import get_enricher
from services.intelligence.lead_intelligence import generate_lead_intelligence
from services.conversations.state_machine import transition as state_transition
from services.conversations.timeline import TimelineEventType, build_timeline_event
from services.outbound.outbound_executor import executor as outbound_executor
from services.outbound.outbound_models import Recipient, SendRequest
from services.outbound.service import resolve_provider_for_conversation
from services.planner.exceptions import PlanningValidationError
from services.planner.planning_pipeline import get_pipeline as get_planning_pipeline
from services.reasoning.reasoning_pipeline import get_pipeline as get_reasoning_pipeline
from services.platform.supabase import (
    get_pending_leads,
    get_session_context,
    get_user_preferences,
    log_conversation,
    select_lead,
)
from services.workflows.service import run_workflow
from services.world_model import EventType as WorldModelEventType, publish


log = logging.getLogger("loqi")


async def _optional_web_session_auth(request) -> tuple[str | None, str]:
    """Resolve optional bootstrap auth without changing anonymous fallback behavior."""
    from services.identity import dependencies as identity_dependencies

    if not request.headers.get("authorization", ""):
        return None, ""
    try:
        auth = await identity_dependencies.get_current_auth(request)
        return auth.user_id, auth.session_id
    except HTTPException:
        return None, ""


async def _bind_authenticated_web_session(
    *,
    session_token: str,
    user_id: str | None,
    canonical_session_id: str,
) -> None:
    """Bind a newly-created legacy web session only when canonical auth exists."""
    if not user_id or not canonical_session_id:
        return
    from services.identity.web_session_binding import bind_web_session

    await bind_web_session(session_token, user_id, canonical_session_id)


async def create_legacy_web_session(
    *,
    request,
    display_name: str | None,
    engine: ConversationEngine,
) -> dict[str, Any]:
    """Create a web compatibility session, optionally bound to canonical auth."""
    from services.identity import dependencies as identity_dependencies
    from services.workspace.state import ensure_workspace

    user_id, canonical_session_id = await _optional_web_session_auth(request)
    if user_id:
        await identity_dependencies.ensure_legacy_user_bridge(user_id)

    result = await asyncio.to_thread(
        engine.create_web_session,
        display_name=display_name,
        user_id=user_id,
    )
    if user_id and canonical_session_id:
        await _bind_authenticated_web_session(
            session_token=result.get("session_token", ""),
            user_id=user_id,
            canonical_session_id=canonical_session_id,
        )
        await asyncio.to_thread(ensure_workspace, user_id)
    return result


async def read_legacy_web_session(*, request, engine: ConversationEngine) -> dict[str, Any]:
    """Return the request-bound web-session summary or its frozen 404 error."""
    from services.identity import dependencies as identity_dependencies

    session_token = identity_dependencies.web_session_token(request)
    data = await asyncio.to_thread(engine.get_web_session_summary, session_token)
    if data is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return data


async def read_legacy_web_session_messages(*, request, engine: ConversationEngine) -> dict[str, Any]:
    """Return legacy web messages for the request-bound web-session token."""
    from services.identity import dependencies as identity_dependencies

    session_token = identity_dependencies.web_session_token(request)
    return {
        "ok": True,
        "messages": await asyncio.to_thread(
            engine.list_messages,
            channel="web",
            external_user_id=session_token,
        ),
    }


async def resolve_legacy_web_message_session(
    *,
    request,
    engine: ConversationEngine,
) -> tuple[str, dict[str, Any], bool]:
    """Resolve or implicitly create the legacy web session for one message.

    The boolean reports whether this request created the session. The legacy
    message path uses it to preserve its historical no-outer-event behavior
    for a bootstrap message; Copilot uses the same authenticated bridge and
    canonical session binding before it prepares a turn.
    """
    from services.identity import dependencies as identity_dependencies

    session_token = identity_dependencies.web_session_token(request)
    summary = await asyncio.to_thread(engine.get_web_session_summary, session_token)
    if summary is not None:
        return session_token, summary, False

    user_id, canonical_session_id = await _optional_web_session_auth(request)
    if user_id:
        await identity_dependencies.ensure_legacy_user_bridge(user_id)
    created = await asyncio.to_thread(
        engine.create_web_session,
        display_name="web-user",
        user_id=user_id,
    )
    if created is None:
        raise HTTPException(status_code=500, detail="Unable to create session")
    await _bind_authenticated_web_session(
        session_token=created["session_token"],
        user_id=user_id,
        canonical_session_id=canonical_session_id,
    )
    summary = await asyncio.to_thread(engine.get_web_session_summary, created["session_token"])
    if summary is None:
        raise HTTPException(status_code=500, detail="Session creation failed")
    return created["session_token"], summary, True


async def handle_legacy_web_message(
    *,
    request,
    text: str,
    engine: ConversationEngine,
) -> dict[str, Any]:
    """Handle the non-Copilot web message path through ConversationEngine.

    This retains the legacy implicit-session bootstrap and its intentional
    early-return behavior: a bootstrap message is not followed by the outer
    MESSAGE_RECEIVED publication, while a message to an existing session is.
    """
    session_token, summary, created = await resolve_legacy_web_message_session(
        request=request,
        engine=engine,
    )
    if created:
        return await asyncio.to_thread(
            engine.handle_message,
            channel="web",
            external_user_id=session_token,
            text=text,
            username=summary.get("display_name"),
        )

    result = await asyncio.to_thread(
        engine.handle_message,
        channel="web",
        external_user_id=session_token,
        text=text,
        username=summary.get("display_name"),
    )
    publish(
        session_token,
        WorldModelEventType.MESSAGE_RECEIVED,
        {
            "from": summary.get("display_name", "web-user"),
            "text_preview": text[:200],
            "channel": "web",
        },
        actor="user",
    )
    return result


def _legacy_message(*, message_type: str, text: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build one legacy web-workflow assistant message with its frozen shape."""
    return {
        "id": str(uuid4()),
        "role": "assistant",
        "type": message_type,
        "text": text,
        "data": data or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _record_legacy_assistant_message(
    workflow_session_id: str,
    *,
    message_type: str,
    text: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist and return one legacy web-workflow assistant message."""
    message = _legacy_message(message_type=message_type, text=text, data=data)
    record_workflow_message(
        session_id=workflow_session_id,
        role="assistant",
        message_type=message_type,
        content=text,
        metadata=data or {},
    )
    return message


def _legacy_selected_lead_text(lead: dict[str, Any]) -> str:
    name = str(lead.get("name") or "Unknown").strip()
    title = str(lead.get("title") or "").strip()
    company = str(lead.get("company") or "Unknown Company").strip()
    return f"Selected: {name}{f' — {title}' if title else ''} @ {company}"


def _legacy_draft_body(message: str) -> str | None:
    if "Draft ready:" not in message or "---" not in message:
        return None
    parts = message.split("---")
    return parts[1].strip() if len(parts) >= 3 else None


def select_legacy_workflow_lead_and_draft(
    *,
    user_id: str,
    lead_index: int,
    workflow_session_id: str,
    session_token: str,
) -> dict[str, Any]:
    """Select a legacy workflow lead and return its typed draft-generation messages.

    This preserves the pre-workspace web-chat lead-card contract. The legacy
    lead and conversation rows remain its source of truth until that product
    flow is deliberately migrated to canonical workspace state.
    """
    context = get_session_context(user_id)
    assistant_messages = list(context.get("assistant_messages") or [])
    selected_lead = select_lead(
        user_id,
        str(lead_index),
        since_timestamp=context.get("started_at"),
    )
    if selected_lead is None:
        error_message = _legacy_message(
            message_type="error",
            text="Could not find that lead. Try searching again.",
        )
        return {"ok": False, "messages": [error_message]}

    messages = [
        _record_legacy_assistant_message(
            workflow_session_id,
            message_type="lead_selected",
            text=_legacy_selected_lead_text(selected_lead),
            data={"lead": selected_lead},
        )
    ]
    workflow_result = run_workflow({
        "type": "draft_message",
        "service": context.get("service"),
        "target": context.get("target"),
        "lead": selected_lead,
        "conversation_context": (list(context.get("user_messages") or []) + assistant_messages)[-10:],
    })
    draft_text = str(workflow_result.get("message") or "")
    if not workflow_result.get("ok", True):
        messages.append(
            _record_legacy_assistant_message(
                workflow_session_id,
                message_type="error",
                text=draft_text or "Operation failed. Please try again.",
                data={"error": workflow_result.get("error")},
            )
        )
    else:
        draft_body = _legacy_draft_body(draft_text)
        messages.append(
            _record_legacy_assistant_message(
                workflow_session_id,
                message_type="draft_preview" if draft_body else "send_confirmation",
                text=draft_text,
                data={
                    "lead": workflow_result.get("lead"),
                    "draft": draft_body,
                    "tone": workflow_result.get("tone"),
                    "length": workflow_result.get("length"),
                    "lead_intelligence": workflow_result.get("lead_intelligence"),
                    "company_intelligence": workflow_result.get("company_intelligence"),
                },
            )
        )
    next_text = _get_after_draft_variation(
        assistant_messages[-3:],
        str(selected_lead.get("name") or ""),
        get_user_preferences(user_id) or {},
    )
    messages.append(
        _record_legacy_assistant_message(
            workflow_session_id,
            message_type="status",
            text=next_text,
        )
    )
    for message in messages:
        text = str(message.get("text") or "").strip()
        if text:
            log_conversation(user_id, "assistant", text)
    publish(
        session_token,
        WorldModelEventType.LEAD_SELECTED,
        {
            "lead_id": str(selected_lead.get("id") or ""),
            "lead_index": lead_index,
            "lead_name": str(selected_lead.get("name") or ""),
        },
        actor="user",
    )
    return {"ok": True, "messages": messages}


def preview_legacy_workflow_lead_intelligence(*, user_id: str, lead_index: int) -> dict[str, Any]:
    """Return best-effort intelligence for one pending legacy workflow lead."""
    pending_leads = get_pending_leads(user_id, since_timestamp=None, limit=5)
    if lead_index < 1 or lead_index > len(pending_leads):
        return {"ok": False, "error": "Invalid lead index"}
    lead = pending_leads[lead_index - 1]
    company_intelligence = None
    try:
        enricher = get_enricher()
        if enricher.health_check().get("ok"):
            company_intelligence = enricher.enrich_lead(lead)
    except Exception:
        pass
    return {
        "ok": True,
        "lead_intelligence": generate_lead_intelligence(lead, company_intelligence),
    }


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


def _test_recipient_override_enabled() -> bool:
    return os.getenv("LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE", "").strip().lower() in {"1", "true", "yes"}


def _owned_conversation_or_404(conversation_id: str, owner_id: str):
    conversation = owned_conversation(conversation_id, owner_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def _send_payload_value(payload: object, name: str) -> str:
    if isinstance(payload, dict):
        return str(payload.get(name, "") or "").strip()
    return str(getattr(payload, name, "") or "").strip()


def _reply_recipient(conversation: object, conversation_id: str, payload: object, *, allow_inbound_fallback: bool) -> tuple[str, str]:
    contact = next((participant for participant in conversation.participants if participant.role == "contact"), None)
    contact_email = _send_payload_value(payload, "to_email") or (contact.email if contact else "") or ""
    contact_name = (contact.name if contact else "") or ""
    if not contact_email and allow_inbound_fallback:
        inbound = [message for message in conversation_store.get_messages_for_conversation(conversation_id) if message.direction == "inbound"]
        if inbound:
            contact_email = inbound[-1].from_email
            contact_name = inbound[-1].from_name
    if not contact_email:
        raise HTTPException(status_code=400, detail="No recipient email available for this conversation")
    return contact_email, contact_name


async def _send_conversation_message(
    conversation_id: str,
    owner_id: str,
    payload: object,
    *,
    follow_up: bool,
) -> dict[str, Any]:
    """Send one authorized conversation message and durably record it."""
    body = _send_payload_value(payload, "body")
    body_label = "Follow-up" if follow_up else "Reply"
    if not body:
        raise HTTPException(status_code=400, detail=f"{body_label} body is required")

    test_recipient = _send_payload_value(payload, "test_recipient")
    if test_recipient and not _test_recipient_override_enabled():
        raise HTTPException(status_code=403, detail="Test recipient override is disabled")

    conversation = _owned_conversation_or_404(conversation_id, owner_id)
    if follow_up:
        if conversation.status not in {ConversationStatus.FOLLOW_UP_PENDING, ConversationStatus.FOLLOW_UP_READY}:
            raise HTTPException(status_code=409, detail="Conversation is not waiting for a follow-up — follow-up already sent or not due")
    elif conversation.status in {
        ConversationStatus.SENT,
        ConversationStatus.DELIVERED,
        ConversationStatus.OPENED,
        ConversationStatus.FOLLOW_UP_PENDING,
        ConversationStatus.FOLLOW_UP_READY,
        ConversationStatus.FOLLOW_UP_SENT,
    }:
        raise HTTPException(status_code=409, detail="Conversation is already awaiting a response — reply already sent")

    threads = conversation_store.get_threads_for_conversation(conversation_id)
    thread = threads[-1] if threads else None
    external_thread_id = _send_payload_value(payload, "thread_id") or getattr(thread, "external_thread_id", "") or ""
    provider_id = resolve_provider_for_conversation(conversation)
    if not provider_id:
        detail = "No connected Gmail provider available to send the follow-up" if follow_up else "No connected Gmail provider available to send the reply"
        raise HTTPException(status_code=503, detail=detail)

    contact_email, contact_name = _reply_recipient(
        conversation, conversation_id, payload, allow_inbound_fallback=not follow_up,
    )
    sender = next((participant for participant in conversation.participants if participant.role == "sender"), None)
    sender_email = _send_payload_value(payload, "from_email") or (sender.email if sender else "") or ""

    reply_to_message_id = ""
    if not follow_up:
        reply_to_message_id = _send_payload_value(payload, "reply_to_message_id")
        if not reply_to_message_id and external_thread_id:
            for message in conversation_store.get_messages_for_conversation(conversation_id):
                if message.external_message_id and message.thread_id == (thread.thread_id if thread else ""):
                    reply_to_message_id = message.external_message_id
                    break

    envelope_email, envelope_name = contact_email, contact_name
    if test_recipient:
        envelope_email = test_recipient
        envelope_name = _send_payload_value(payload, "test_recipient_name") or "Test Recipient"
        log.info("[TEST RECIPIENT] original_recipient=%s effective_recipient=%s", contact_email, test_recipient)

    result = await asyncio.to_thread(
        outbound_executor.send_request,
        SendRequest(
            provider_id=provider_id,
            body=body,
            conversation_id=conversation_id,
            subject="Re: " + ((thread.subject if thread else conversation.subject) or ""),
            thread_id=external_thread_id,
            reply_to_message_id=reply_to_message_id,
            recipient=Recipient(email=envelope_email, name=envelope_name),
            sender=Recipient(email=sender_email, name=""),
        ),
        original_recipient_email=contact_email,
    )
    if not result or not result.get("ok"):
        message = "Failed to send follow-up" if follow_up else "Failed to send reply"
        raise HTTPException(status_code=502, detail=(result or {}).get("error") or message)

    send_result = result.get("send_result") or {}
    external_message_id = str(send_result.get("external_message_id") or send_result.get("id") or "")
    sent_message = ConversationMessage(
        conversation_id=conversation_id,
        thread_id=thread.thread_id if thread else "",
        provider_id=provider_id,
        external_message_id=external_message_id,
        direction="outbound",
        from_email=sender_email,
        from_name="You",
        to_email=contact_email,
        to_name=contact_name,
        subject="Re: " + ((thread.subject if thread else conversation.subject) or ""),
        body=body,
    )
    conversation_store.add_message(sent_message)
    event_type = TimelineEventType.FOLLOW_UP_SENT if follow_up else TimelineEventType.EMAIL_SENT
    title = "Follow-up sent" if follow_up else "Reply sent"
    metadata = {
        "conversation_id": conversation_id,
        "direction": "outbound",
        "external_thread_id": external_thread_id,
        "provider_id": provider_id,
    }
    if not follow_up:
        metadata["reply_to_message_id"] = reply_to_message_id
    conversation_store.add_timeline_event(build_timeline_event(
        conversation_id=conversation_id,
        event_type=event_type,
        title=title,
        description=f"To: {contact_name or contact_email} | Provider: {provider_id[:8]}…",
        metadata=metadata,
    ))
    target = ConversationStatus.FOLLOW_UP_SENT if follow_up else ConversationStatus.SENT
    try:
        conversation.status = state_transition(conversation.status, target)
        conversation_store.update_conversation(conversation)
    except ValueError:
        detail = "Conversation status no longer allows a follow-up send" if follow_up else "Conversation status no longer allows a reply send"
        raise HTTPException(status_code=409, detail=detail)
    return {
        "ok": True,
        "conversation_id": conversation_id,
        "status": conversation.status.value,
        "message_id": sent_message.message_id,
        "external_message_id": external_message_id,
    }


async def send_reply(conversation_id: str, owner_id: str, payload: object) -> dict[str, Any]:
    """Send a reply only for the authenticated conversation owner."""
    return await _send_conversation_message(conversation_id, owner_id, payload, follow_up=False)


async def send_follow_up(conversation_id: str, owner_id: str, payload: object) -> dict[str, Any]:
    """Send a follow-up only for the authenticated conversation owner."""
    from fastapi import HTTPException
    from services.capabilities.beta import beta_feature_enabled, beta_feature_unavailable_message

    if not beta_feature_enabled("automated_followups"):
        raise HTTPException(
            status_code=403,
            detail=beta_feature_unavailable_message("automated_followups"),
        )
    return await _send_conversation_message(conversation_id, owner_id, payload, follow_up=True)
