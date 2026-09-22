"""Outbound draft projection, provider ownership, and campaign dispatch."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Request

from services.communication.communication_store import store as communication_store
from services.communication.provider_registry import get_provider as get_communication_provider
import services.identity.dependencies as identity_dependencies
from services.outbound import outbound_registry
from services.outbound.outbound_executor import executor as outbound_executor
from services.outbound.outbound_registry import (
    get_provider as get_outbound_provider,
    list_providers as outbound_list_providers,
)
import services.workspace.access as workspace_access
import services.workspace.state as workspace_state
from services.world_model import EventType as WMEventType, publish
from services.communication.reply_simulator import maybe_schedule as simulate_reply
from services.events.bus import publish_draft_event

log = logging.getLogger("loqi")

SCHEDULED_SEND_JOB_TYPE = "outbound_send"


def test_recipient_override_enabled() -> bool:
    """Return whether the explicitly test-only recipient override is enabled."""
    return os.getenv("LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE", "").strip().lower() in {"1", "true", "yes"}


def _parse_send_at(send_at: str) -> datetime | None:
    """Parse the existing ISO schedule field into a durable UTC due time."""
    try:
        parsed = datetime.fromisoformat(str(send_at or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _scheduled_job_id(outbound_draft: object) -> str:
    metadata = getattr(outbound_draft, "metadata", None) or {}
    projection = metadata.get("outbound_projection") or {}
    return str(projection.get("scheduled_job_id") or metadata.get("scheduled_job_id") or "")


def register_scheduled_send_workflow() -> None:
    """Register the durable delayed-send workflow with the shared job engine."""
    from services.job_engine.registry import WorkflowRegistration, get_registry

    registry = get_registry()
    if registry.get(SCHEDULED_SEND_JOB_TYPE) is None:
        registry.register(WorkflowRegistration(
            type=SCHEDULED_SEND_JOB_TYPE,
            description="Send one approved outbound draft at its durable due time",
            runner_fn=run_scheduled_outbound_send,
        ))


def find_outbound_gmail_provider_id() -> str:
    """Return the first registered Gmail outbound provider, if any."""
    for provider_id, instance in outbound_list_providers().items():
        if getattr(instance, "provider_type", None) == "gmail":
            return provider_id
    return ""


def resolve_provider_for_conversation(conversation: object) -> str:
    """Resolve the connected provider for a durable Inbox conversation.

    Outbound owns provider selection; Conversations supplies the authorized
    durable conversation.  This keeps reply/follow-up sends off main.py while
    preserving the historical thread, draft, then connected-Gmail priority.
    """
    if conversation is not None:
        from datetime import datetime, timezone

        from services.conversations.conversation_store import conversation_store

        threads = conversation_store.get_threads_for_conversation(conversation.conversation_id)
        if threads:
            threads.sort(key=lambda thread: thread.created_at or datetime.min.replace(tzinfo=timezone.utc))
            provider_id = threads[-1].provider_id
            if provider_id and get_outbound_provider(provider_id):
                return provider_id

        metadata = getattr(conversation, "metadata", {}) or {}
        draft_id = getattr(conversation, "draft_id", "") or metadata.get("draft_id", "")
        owner_id = str(getattr(conversation, "owner_id", "") or "")
        workspace_id = str(metadata.get("workspace_id") or "")
        if draft_id and owner_id and workspace_id:
            canonical = next(
                (
                    draft for draft in workspace_state.load_drafts_only(owner_id, workspace_id=workspace_id)
                    if str(draft.get("id") or "") == str(draft_id)
                ),
                None,
            )
            if canonical:
                outbound_draft = hydrate_outbound_draft(canonical, "", owner_id=owner_id)
                provider_id = resolve_provider_for_draft(outbound_draft, owner_id=owner_id)
                if provider_id:
                    return provider_id
    return find_outbound_gmail_provider_id()


def resolve_owner_gmail_provider(owner_id: str) -> str:
    """Resolve the connected Gmail provider belonging to ``owner_id``."""
    candidates: list[tuple[str, str]] = []
    for provider_id, instance in outbound_list_providers().items():
        if getattr(instance, "provider_type", None) != "gmail":
            continue
        provider = get_communication_provider(provider_id)
        if not provider:
            continue
        user_id = getattr(provider, "_user_id", "") or ""
        if str(user_id) != str(owner_id) or not bool(getattr(provider, "_connected", False)):
            continue
        candidates.append((getattr(provider, "_mailbox_email", "") or "", provider_id))
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1] if candidates else ""


def hydrate_outbound_draft(legacy_draft: dict, session_token: str, owner_id: str = "") -> Any:
    """Build an outbound message from one durable canonical draft.

    This is deliberately a read-only hydration step.  The durable Draft row
    and its ``outbound_projection`` metadata remain the source of truth; the
    legacy in-memory store is not populated here.
    """
    from services.outbound.outbound_models import ApprovalState, DraftMessage, DraftStatus, Recipient

    from services.outbound.outbound_persistence import hydrate_draft_projection

    now = datetime.now(timezone.utc).isoformat()
    lead = legacy_draft.get("lead", {})
    lead_email = lead.get("email", "")
    lead_name = lead.get("name") or f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip() or "Unknown"
    status_map = {
        "pending": DraftStatus.PENDING_APPROVAL,
        "approved": DraftStatus.APPROVED,
        "rejected": DraftStatus.REJECTED,
        "draft": DraftStatus.DRAFT,
        "sent": DraftStatus.SENT,
    }
    provider_id = resolve_owner_gmail_provider(owner_id) if owner_id else find_outbound_gmail_provider_id()
    provider = get_communication_provider(provider_id) if provider_id else None
    projection = (legacy_draft.get("metadata") or {}).get("outbound_projection")
    if projection:
        outbound_draft = hydrate_draft_projection(
            legacy_draft,
            provider_id=provider_id,
            sender_email=getattr(provider, "_mailbox_email", "") or "",
        )
        outbound_draft.metadata.update({"lead": lead, "session_token": session_token})
    else:
        outbound_draft = DraftMessage(
        id=legacy_draft.get("id", ""),
        provider_id=provider_id,
        workflow_id=legacy_draft.get("campaign_id", ""),
        subject=legacy_draft.get("subject", ""),
        body=legacy_draft.get("text", ""),
        recipient=Recipient(email=lead_email, name=lead_name),
        sender=Recipient(email=getattr(provider, "_mailbox_email", "") or "", name=""),
        status=status_map.get(legacy_draft.get("status", "pending"), DraftStatus.PENDING_APPROVAL),
        approval_state=ApprovalState.APPROVED if legacy_draft.get("status") == "approved" else ApprovalState.PENDING,
        created_at=legacy_draft.get("created_at", now),
        updated_at=now,
        metadata={
            "lead": lead,
            "tone": legacy_draft.get("tone"),
            "length": legacy_draft.get("length"),
            "lead_intelligence": legacy_draft.get("lead_intelligence"),
            "company_intelligence": legacy_draft.get("company_intelligence"),
            "session_token": session_token,
        },
        )
    return outbound_draft


def provider_owned_by(provider_id: str, owner_id: str) -> bool:
    """Return whether a connected runtime provider belongs to the owner."""
    if not owner_id:
        return False
    provider = get_communication_provider(provider_id)
    if not provider:
        return False
    return (
        str(getattr(provider, "_user_id", "") or "") == str(owner_id)
        and bool(getattr(provider, "_connected", False))
    )


def provider_record_owned_by(provider_id: str, owner_id: str) -> bool:
    """Return whether the durable communication-provider record belongs to the owner."""
    if not owner_id:
        return False
    provider = communication_store.get_provider(provider_id)
    return provider is not None and str(provider.user_id) == str(owner_id)


def outbound_draft_owned_by(draft: object, owner_id: str) -> bool:
    """Fail closed unless an outbound draft's provider record belongs to the owner."""
    if not owner_id or draft is None:
        return False
    provider_id = getattr(draft, "provider_id", "") or ""
    return bool(provider_id and provider_record_owned_by(provider_id, owner_id))


async def require_canonical_outbound_draft(
    request: Request,
    session_token: str,
    draft_id: str,
    *,
    provider_id: str = "",
) -> tuple[str, str, dict[str, Any], Any]:
    """Authorize and hydrate one durable draft into its outbound projection."""
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    workspace_id = await workspace_access.resolve_legacy_workspace_id(request, owner_id)
    canonical = next(
        (
            draft for draft in workspace_state.load_drafts_only(owner_id, workspace_id=workspace_id)
            if str(draft.get("id") or "") == str(draft_id)
        ),
        None,
    )
    if canonical is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    canonical_provider = str(canonical.get("provider") or provider_id or "")
    if provider_id and canonical_provider and provider_id != canonical_provider:
        raise HTTPException(status_code=404, detail="Draft not found")
    if canonical_provider and not provider_record_owned_by(canonical_provider, owner_id):
        raise HTTPException(status_code=404, detail="Draft not found")
    outbound_draft = hydrate_outbound_draft(canonical, session_token, owner_id=owner_id)
    if canonical_provider and not outbound_draft_owned_by(outbound_draft, owner_id):
        raise HTTPException(status_code=404, detail="Draft not found")
    return owner_id, workspace_id, canonical, outbound_draft


def outbound_to_legacy_draft(outbound_draft: object) -> dict[str, Any]:
    """Return the existing legacy dictionary representation of an outbound draft."""
    from services.outbound.outbound_models import ApprovalState, DraftStatus

    lead = outbound_draft.metadata.get("lead", {}) if outbound_draft.metadata else {}
    status_map = {
        DraftStatus.DRAFT: "pending",
        DraftStatus.PENDING_APPROVAL: "pending",
        DraftStatus.APPROVED: "approved",
        DraftStatus.AUTO_APPROVED: "approved",
        DraftStatus.REJECTED: "rejected",
        DraftStatus.SENDING: "sending",
        DraftStatus.SENT: "sent",
        DraftStatus.SCHEDULED: "scheduled",
        DraftStatus.FAILED: "failed",
        DraftStatus.CANCELLED: "cancelled",
        DraftStatus.ARCHIVED: "archived",
    }
    return {
        "id": outbound_draft.id,
        "campaign_id": outbound_draft.workflow_id,
        "lead": lead,
        "subject": outbound_draft.subject,
        "text": outbound_draft.body,
        "status": status_map.get(outbound_draft.status, "pending"),
        "tone": outbound_draft.metadata.get("tone") if outbound_draft.metadata else None,
        "length": outbound_draft.metadata.get("length") if outbound_draft.metadata else None,
        "lead_intelligence": outbound_draft.metadata.get("lead_intelligence") if outbound_draft.metadata else None,
        "company_intelligence": outbound_draft.metadata.get("company_intelligence") if outbound_draft.metadata else None,
        "created_at": outbound_draft.created_at,
        "external_draft_id": outbound_draft.external_draft_id,
        "gmail_message_id": outbound_draft.gmail_message_id,
        "gmail_thread_id": outbound_draft.gmail_thread_id,
    }


async def persist_outbound_projection(
    owner_id: str, workspace_id: str, outbound_draft: object, *, change_summary: str = "",
) -> bool:
    """Commit provider-only draft state to the authorized canonical Draft."""
    from services.outbound.outbound_persistence import persist_draft_projection

    return await persist_draft_projection(
        owner_id, workspace_id, outbound_draft, change_summary=change_summary,
    )


def resolve_provider_for_draft(outbound_draft: object, owner_id: str = "") -> str:
    """Resolve a usable, owner-authorized outbound provider for a draft."""
    provider_id = getattr(outbound_draft, "provider_id", "") or ""
    stored_provider = get_outbound_provider(provider_id) if provider_id else None
    if stored_provider and (not owner_id or provider_owned_by(provider_id, owner_id)):
        return provider_id
    resolved = (
        resolve_owner_gmail_provider(owner_id)
        if owner_id
        else find_outbound_gmail_provider_id()
    )
    if resolved and outbound_draft and provider_id != resolved:
        outbound_draft.provider_id = resolved
    return resolved


async def gmail_provider_unavailable_error(owner_id: str) -> str:
    """Explain a missing runtime projection without confusing it with logout.

    ``connected_accounts`` is authoritative. When Gmail has explicitly
    rejected its durable refresh credential, the runtime provider is removed
    from normal selection and Send must ask for reauthorization—not claim the
    account was never connected. A missing durable account remains a separate
    actionable condition.
    """
    if owner_id:
        try:
            from services.platform.supabase import is_connected_account_reauth_required

            if await asyncio.to_thread(is_connected_account_reauth_required, owner_id, "google"):
                return "Gmail authorization expired. Reconnect Gmail to send."
        except Exception as error:
            log.warning(
                "gmail_provider_status_lookup_failed user_id=%s error_type=%s",
                owner_id[:8],
                type(error).__name__,
            )
    return "No Gmail outbound provider registered"


async def enqueue_scheduled_outbound_send(
    owner_id: str,
    workspace_id: str,
    canonical_draft: dict[str, Any],
    outbound_draft: object,
    send_at: str,
) -> dict[str, Any]:
    """Persist one authorized scheduled send before it can be claimed."""
    from services.job_engine import Job, job_manager
    from services.outbound.outbound_models import DraftStatus
    from services.workspace.state import persist_draft_update_awaited

    run_at = _parse_send_at(send_at)
    if run_at is None:
        return {"ok": False, "error": "Invalid send time"}
    provider_id = resolve_provider_for_draft(outbound_draft, owner_id)
    if not provider_id:
        return {"ok": False, "error": "No Gmail outbound provider registered"}

    register_scheduled_send_workflow()
    job = Job(
        user_id=owner_id,
        type=SCHEDULED_SEND_JOB_TYPE,
        workspace_id=workspace_id,
        campaign_id=str(canonical_draft.get("campaign_id") or ""),
        run_at=run_at,
        payload={
            "draft_id": str(canonical_draft.get("id") or outbound_draft.id),
            "provider_id": provider_id,
        },
    )
    if not await job_manager.create_job(job):
        return {"ok": False, "error": "Scheduled send could not be created"}

    outbound_draft.status = DraftStatus.SCHEDULED
    outbound_draft.metadata["scheduled_job_id"] = job.id
    outbound_draft.metadata["send_at"] = send_at
    draft_id = str(canonical_draft.get("id") or outbound_draft.id)
    if not await persist_draft_update_awaited(
        owner_id, draft_id, {"status": "scheduled"}, workspace_id=workspace_id,
    ):
        await asyncio.to_thread(job_manager.cancel_job, job.id)
        return {"ok": False, "error": "Draft was scheduled but canonical persistence failed"}
    if not await persist_outbound_projection(
        owner_id, workspace_id, outbound_draft, change_summary="scheduled",
    ):
        await asyncio.to_thread(job_manager.cancel_job, job.id)
        return {"ok": False, "error": "Draft schedule projection persistence failed"}
    # schedule_id remains the canonical draft id for the existing cancel URL.
    return {"ok": True, "schedule_id": draft_id, "job_id": job.id}


async def cancel_scheduled_outbound_send(
    owner_id: str,
    workspace_id: str,
    canonical_draft: dict[str, Any],
    outbound_draft: object,
) -> dict[str, Any]:
    """Cancel one queued delayed send without interrupting remote provider work."""
    from services.job_engine import job_manager
    from services.outbound.outbound_models import DraftStatus
    from services.workspace.state import persist_draft_update_awaited

    job_id = _scheduled_job_id(outbound_draft)
    if not job_id:
        return {"ok": False, "error": "Draft is not scheduled"}
    job = await asyncio.to_thread(job_manager.get_job, job_id)
    if (
        job is None
        or job.get("type") != SCHEDULED_SEND_JOB_TYPE
        or job.get("user_id") != owner_id
        or job.get("workspace_id") != workspace_id
        or str((job.get("payload") or {}).get("draft_id") or "") != str(canonical_draft.get("id") or "")
    ):
        return {"ok": False, "error": "Draft is not scheduled"}
    if job.get("status") != "queued":
        # A remote worker may already be inside a provider call. It is safer
        # to report that state than claim cancellation prevented that send.
        return {"ok": False, "error": "Scheduled send is already running"}
    if not await asyncio.to_thread(job_manager.cancel_job, job_id):
        return {"ok": False, "error": "Scheduled send is already running"}

    draft_id = str(canonical_draft.get("id") or outbound_draft.id)
    if not await persist_draft_update_awaited(
        owner_id, draft_id, {"status": "pending"}, workspace_id=workspace_id,
    ):
        return {"ok": False, "error": "Schedule was cancelled but canonical Draft persistence failed"}
    outbound_draft.status = DraftStatus.PENDING_APPROVAL
    outbound_draft.metadata.pop("scheduled_job_id", None)
    outbound_draft.metadata.pop("send_at", None)
    if not await persist_outbound_projection(
        owner_id, workspace_id, outbound_draft, change_summary="schedule cancelled",
    ):
        return {"ok": False, "error": "Draft schedule projection persistence failed"}
    return {"ok": True}


async def run_scheduled_outbound_send(job, on_progress) -> dict[str, Any]:
    """Execute one claimed scheduled send from its canonical Draft state."""
    from services.outbound.outbound_models import DraftStatus
    from services.workspace.state import load_drafts_only, persist_draft_update_awaited

    draft_id = str(job.payload.get("draft_id") or "")
    if not draft_id or not job.user_id or not job.workspace_id:
        return {"ok": False, "error": "Scheduled send is missing canonical draft context"}
    canonical = next(
        (
            draft for draft in await asyncio.to_thread(
                load_drafts_only, job.user_id, workspace_id=job.workspace_id,
            )
            if str(draft.get("id") or "") == draft_id
        ),
        None,
    )
    if canonical is None:
        return {"ok": False, "error": "Scheduled draft no longer exists"}
    if canonical.get("status") != "scheduled":
        return {"ok": False, "error": "Scheduled draft is no longer active"}

    outbound_draft = hydrate_outbound_draft(canonical, "", owner_id=job.user_id)
    if _scheduled_job_id(outbound_draft) != job.id:
        return {"ok": False, "error": "Scheduled draft has been superseded"}
    provider_id = resolve_provider_for_draft(outbound_draft, job.user_id)
    recipient = outbound_draft.recipient
    if not provider_id:
        return {"ok": False, "error": "No Gmail outbound provider registered"}
    if not recipient or not str(recipient.email or "").strip():
        return {"ok": False, "error": "This lead has no email address"}

    # Persist the sending boundary before the provider side effect. If a
    # process dies after this point, recovery refuses to guess and resend.
    if not await persist_draft_update_awaited(
        job.user_id, draft_id, {"status": "sending"}, workspace_id=job.workspace_id,
    ):
        return {"ok": False, "error": "Scheduled send could not enter sending state"}
    outbound_draft.status = DraftStatus.SENDING
    if not await persist_outbound_projection(
        job.user_id, job.workspace_id, outbound_draft, change_summary="scheduled send started",
    ):
        return {"ok": False, "error": "Scheduled send projection persistence failed"}

    on_progress(job.id, "Sending scheduled draft", 50)
    result = await asyncio.to_thread(
        outbound_executor.send_hydrated_draft,
        outbound_draft,
        provider_id=provider_id,
    )
    if not result.get("ok"):
        outbound_draft.status = DraftStatus.FAILED
        await persist_draft_update_awaited(
            job.user_id, draft_id, {"status": "failed"}, workspace_id=job.workspace_id,
        )
        await persist_outbound_projection(
            job.user_id, job.workspace_id, outbound_draft, change_summary="scheduled send failed",
        )
        await publish_draft_event(job.user_id, "draft.failed", draft_id=draft_id)
        return {"ok": False, "error": result.get("error", "Scheduled send failed")}

    outbound_draft.status = DraftStatus.SENT
    outbound_draft.metadata.pop("scheduled_job_id", None)
    outbound_draft.metadata.pop("send_at", None)
    if not await persist_draft_update_awaited(
        job.user_id, draft_id, {"status": "sent"}, workspace_id=job.workspace_id,
    ):
        return {"ok": False, "error": "Email was sent but the canonical Draft could not be updated"}
    if not await persist_outbound_projection(
        job.user_id, job.workspace_id, outbound_draft, change_summary="scheduled send completed",
    ):
        return {"ok": False, "error": "Email was sent but the outbound projection could not be updated"}
    await publish_draft_event(job.user_id, "draft.sent", draft_id=draft_id)
    on_progress(job.id, "Scheduled draft sent", 100)
    return {"ok": True, "result": {"draft_id": draft_id, "send_result": result.get("send_result") or {}}}


async def send_outbound_draft(
    request: Request,
    draft_id: str,
    *,
    test_recipient: str = "",
    test_recipient_name: str = "",
) -> dict[str, Any]:
    """Send one authorized hydrated draft and persist the resulting state."""
    if test_recipient and not test_recipient_override_enabled():
        raise HTTPException(status_code=403, detail="Test recipient override is disabled")
    session_token = identity_dependencies.web_session_token(request)
    owner_id, workspace_id, canonical, draft = await require_canonical_outbound_draft(request, session_token, draft_id)
    from services.outbound.outbound_models import DraftStatus, Recipient

    if canonical.get("status") == "sent" or draft.status in (DraftStatus.SENT, DraftStatus.SENDING):
        return {"ok": False, "error": "Draft already sent"}
    original_status = str(canonical.get("status") or "")
    if original_status not in {"approved", "pending"}:
        return {"ok": False, "error": "Draft is not approved for sending"}
    if owner_id and draft.provider_id:
        provider = communication_store.get_provider(draft.provider_id)
        if provider is not None and str(provider.user_id) != str(owner_id):
            raise HTTPException(status_code=404, detail="Draft not found")
    recipient = draft.recipient
    if not recipient or not str(recipient.email or "").strip():
        return {"ok": False, "error": "This lead has no email address"}
    provider_id = resolve_provider_for_draft(draft, owner_id)
    if not provider_id:
        return {"ok": False, "error": await gmail_provider_unavailable_error(owner_id)}

    claimed = await workspace_state.claim_draft_for_send(
        draft_id,
        workspace_id=workspace_id,
        expected_status=original_status,
    )
    if not claimed:
        # A concurrent request either owns the in-flight send or has already
        # completed it.  Preserve the existing safe retry envelope and never
        # invoke Gmail again.
        return {"ok": False, "error": "Draft already sent"}

    effective_recipient = Recipient(
        email=test_recipient or recipient.email,
        name=(test_recipient_name or "Test Recipient") if test_recipient else recipient.name,
    )
    result = await asyncio.to_thread(
        outbound_executor.send_hydrated_draft, draft, provider_id=provider_id, recipient_override=effective_recipient,
    )
    if not result.get("ok"):
        # Explicit provider failures (for example, a Gmail 4xx/5xx response)
        # are safe to retry.  A transport failure or a history write after
        # provider acceptance is ambiguous, so retain ``sending`` and block a
        # duplicate external send.
        if result.get("retry_safe", True):
            await workspace_state.release_draft_send_claim(
                draft_id,
                workspace_id=workspace_id,
                restore_status=original_status,
            )
        publish(session_token, WMEventType.DRAFT_FAILED, {"draft_id": draft_id, "error": result.get("error", "Unknown error")}, actor="system")
        return {"ok": False, "send_result": result}
    if not await workspace_state.persist_draft_update_awaited(owner_id, draft_id, {"status": "sent"}, workspace_id=workspace_id):
        raise HTTPException(status_code=503, detail="Email was sent but the canonical Draft could not be updated")
    draft.status = DraftStatus.SENT
    if not await persist_outbound_projection(owner_id, workspace_id, draft, change_summary="sent"):
        raise HTTPException(status_code=503, detail="Email was sent but the outbound projection could not be updated")
    await publish_draft_event(owner_id, "draft.sent", draft_id=draft_id, campaign_id=draft.workflow_id or "", lead_name=recipient.name)
    send_data = result.get("send_result", {})
    try:
        from services.conversations.integration import create_conversation_from_send
        conversation = create_conversation_from_send(
            provider_id=provider_id, provider_type="gmail", external_thread_id=send_data.get("thread_id", ""),
            external_message_id=send_data.get("external_message_id", ""), subject=draft.subject,
            from_email=draft.sender.email, from_name=draft.sender.name, to_email=recipient.email, to_name=recipient.name,
            body=draft.body, campaign_id=draft.workflow_id or "", workflow_id=draft.workflow_id or "",
            owner_id=owner_id, workspace_id=workspace_id,
        )
        simulate_reply({"conversation_id": conversation.conversation_id, "external_thread_id": send_data.get("thread_id", ""),
                        "subject": draft.subject, "from_email": draft.sender.email, "from_name": draft.sender.name,
                        "to_email": recipient.email, "to_name": recipient.name, "body": draft.body,
                        "campaign_id": draft.workflow_id or "", "workflow_id": draft.workflow_id or "",
                        "lead": (draft.metadata or {}).get("lead", {}), "objective": ""})
    except Exception as error:
        log.error("persistence_write_failed category=conversation operation=create_from_send draft_id=%s provider_id=%s error_type=%s", draft_id[:12], provider_id[:12], type(error).__name__)
    publish(session_token, WMEventType.DRAFT_SENT, {"draft_id": draft_id, "thread_id": send_data.get("thread_id", ""),
            "external_message_id": send_data.get("external_message_id", ""), "provider_id": provider_id,
            "subject": draft.subject, "recipient_email": recipient.email, "campaign_id": draft.workflow_id or ""}, actor="system")
    return {"ok": True, "send_result": result}


async def schedule_outbound_draft(request: Request, draft_id: str, send_at: str) -> dict[str, Any]:
    """Schedule one authorized draft through the durable outbound job flow."""
    session_token = identity_dependencies.web_session_token(request)
    owner_id, workspace_id, canonical, draft = await require_canonical_outbound_draft(request, session_token, draft_id)
    if not draft.recipient or not str(draft.recipient.email or "").strip():
        return {"ok": False, "error": "This lead has no email address"}
    provider_id = resolve_provider_for_draft(draft, owner_id)
    if not provider_id:
        return {"ok": False, "error": await gmail_provider_unavailable_error(owner_id)}
    result = await enqueue_scheduled_outbound_send(owner_id, workspace_id, canonical, draft, send_at)
    if result.get("ok"):
        await publish_draft_event(owner_id, "draft.scheduled", draft_id=draft_id)
        publish(session_token, WMEventType.DRAFT_SCHEDULED, {"draft_id": draft_id, "send_at": send_at,
                "provider_id": provider_id, "campaign_id": draft.workflow_id or ""}, actor="user")
    if result.get("error") in {"Draft was scheduled but canonical persistence failed", "Draft schedule projection persistence failed"}:
        raise HTTPException(status_code=503, detail=result["error"])
    result.pop("job_id", None)
    return result


async def cancel_outbound_draft_schedule(request: Request | None, draft_id: str, provider_id: str = "") -> dict[str, Any]:
    """Cancel one authorized durable scheduled-send job."""
    if request is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    session_token = identity_dependencies.web_session_token(request)
    owner_id, workspace_id, canonical, draft = await require_canonical_outbound_draft(request, session_token, draft_id, provider_id=provider_id)
    result = await cancel_scheduled_outbound_send(owner_id, workspace_id, canonical, draft)
    if result.get("ok"):
        await publish_draft_event(owner_id, "draft.updated", draft_id=draft_id)
        publish(session_token, WMEventType.DRAFT_UPDATED, {"draft_id": draft_id, "status": "pending", "previous_status": "scheduled"}, actor="user")
    if result.get("error") in {"Schedule was cancelled but canonical Draft persistence failed", "Draft schedule projection persistence failed"}:
        raise HTTPException(status_code=503, detail=result["error"])
    return result


async def create_outbound_draft(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    """Create a canonical draft and its provider projection."""
    from services.outbound.outbound_models import DraftMessage, Recipient

    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    provider_id = str(payload.get("provider_id") or "")
    if not provider_owned_by(provider_id, owner_id):
        raise HTTPException(status_code=404, detail="Provider not found")
    draft = DraftMessage(
        provider_id=provider_id, conversation_id=str(payload.get("conversation_id") or ""),
        thread_id=str(payload.get("thread_id") or ""), workflow_id=str(payload.get("workflow_id") or ""),
        subject=str(payload.get("subject") or ""), body=str(payload.get("body") or ""),
        recipient=Recipient(email=str(payload.get("recipient_email") or ""), name=str(payload.get("recipient_name") or "")),
        sender=Recipient(email=str(payload.get("sender_email") or ""), name=str(payload.get("sender_name") or "")),
        cc=[Recipient(**item) for item in (payload.get("cc") or [])],
        bcc=[Recipient(**item) for item in (payload.get("bcc") or [])],
        reply_to_message_id=str(payload.get("reply_to_message_id") or ""),
        in_reply_to=str(payload.get("in_reply_to") or ""), references=str(payload.get("references") or ""),
    )
    canonical = {
        "id": draft.id, "campaign_id": draft.workflow_id, "provider": provider_id,
        "subject": draft.subject, "body": draft.body, "status": "draft",
        "lead": {"email": draft.recipient.email, "name": draft.recipient.name},
    }
    if not await workspace_state.persist_draft_awaited(owner_id, canonical):
        raise HTTPException(status_code=503, detail="Draft could not be persisted")
    workspace_id = await workspace_access.resolve_legacy_workspace_id(request, owner_id)
    try:
        result = await asyncio.to_thread(outbound_registry.create_draft, provider_id, draft)
        if not result:
            raise RuntimeError("Provider did not return a draft projection")
        draft = result
        if not await persist_outbound_projection(owner_id, workspace_id, draft, change_summary="provider draft created"):
            raise RuntimeError("Provider draft projection could not be persisted")
    except Exception as error:
        await workspace_state.persist_draft_update_awaited(owner_id, draft.id, {"status": "failed"})
        raise HTTPException(status_code=502, detail="Draft was persisted but provider projection failed") from error
    publish(session_token, WMEventType.DRAFT_GENERATED, {
        "id": draft.id, "campaign_id": draft.workflow_id, "subject": draft.subject,
        "body_preview": draft.body[:200], "recipient_email": draft.recipient.email, "provider_id": provider_id,
    }, actor="user")
    return {"ok": True, "draft": draft.model_dump()}


async def update_outbound_draft(request: Request, draft_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Update one authorized canonical draft and its provider projection."""
    from services.outbound.outbound_models import Recipient

    session_token = identity_dependencies.web_session_token(request)
    provider_id = str(payload.get("provider_id") or "")
    owner_id, workspace_id, _canonical, existing = await require_canonical_outbound_draft(
        request, session_token, draft_id, provider_id=provider_id,
    )
    update_data: dict[str, Any] = {}
    if payload.get("subject"):
        update_data["subject"] = payload["subject"]
    if payload.get("body"):
        update_data["body"] = payload["body"]
    if payload.get("recipient_email"):
        update_data["recipient"] = Recipient(email=payload["recipient_email"], name=str(payload.get("recipient_name") or ""))
    canonical_updates = {key: value for key, value in update_data.items() if key in {"subject", "body"}}
    if canonical_updates and not await workspace_state.persist_draft_update_awaited(
        owner_id, draft_id, canonical_updates, workspace_id=workspace_id,
    ):
        raise HTTPException(status_code=503, detail="Draft update could not be persisted")
    updated = existing.model_copy(update=update_data)
    if payload.get("external_draft_id"):
        updated = await asyncio.to_thread(outbound_registry.update_draft, provider_id, updated)
        if not updated:
            raise HTTPException(status_code=502, detail="Provider draft update failed")
    if not await persist_outbound_projection(owner_id, workspace_id, updated, change_summary="provider draft updated"):
        raise HTTPException(status_code=503, detail="Draft projection could not be persisted")
    publish(session_token, WMEventType.DRAFT_UPDATED, {
        "draft_id": draft_id, "provider_id": provider_id, "subject": payload.get("subject") or existing.subject,
    }, actor="user")
    return {"ok": True, "draft": updated.model_dump()}


async def delete_outbound_draft(request: Request | None, draft_id: str, provider_id: str = "") -> dict[str, Any]:
    """Reject an authorized draft and remove its provider-side projection."""
    if request is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    session_token = identity_dependencies.web_session_token(request)
    owner_id, workspace_id, _canonical, draft = await require_canonical_outbound_draft(
        request, session_token, draft_id, provider_id=provider_id,
    )
    if draft and draft.external_draft_id and provider_id:
        await asyncio.to_thread(outbound_registry.delete_draft, provider_id, draft.external_draft_id)
    if not await workspace_state.persist_draft_update_awaited(owner_id, draft_id, {"status": "rejected"}, workspace_id=workspace_id):
        raise HTTPException(status_code=503, detail="Draft deletion could not be persisted")
    from services.outbound.outbound_models import DraftStatus

    draft.status = DraftStatus.REJECTED
    if not await persist_outbound_projection(owner_id, workspace_id, draft, change_summary="provider draft deleted"):
        raise HTTPException(status_code=503, detail="Draft deletion projection could not be persisted")
    publish(session_token, WMEventType.DRAFT_REJECTED, {"draft_id": draft_id, "provider_id": provider_id}, actor="user")
    from services.learning.behavior_tracker import get_tracker
    from services.learning.feedback_interpreter import FeedbackInterpreter

    FeedbackInterpreter(get_tracker()).on_draft_rejected(session_token, draft_id)
    return {"ok": True}


async def approve_outbound_draft(request: Request | None, draft_id: str, auto: bool = False) -> dict[str, Any]:
    """Approve an authorized draft and create its provider-side draft."""
    if request is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    session_token = identity_dependencies.web_session_token(request)
    owner_id, workspace_id, _canonical, draft = await require_canonical_outbound_draft(request, session_token, draft_id)
    from services.outbound.outbound_models import ApprovalState, DraftStatus

    draft.approval_state = ApprovalState.AUTO_APPROVED if auto else ApprovalState.APPROVED
    draft.status = DraftStatus.AUTO_APPROVED if auto else DraftStatus.APPROVED
    try:
        updated = await asyncio.to_thread(outbound_registry.create_draft, draft.provider_id, draft)
        if not updated:
            raise HTTPException(status_code=502, detail="No provider registered for " + draft.provider_id)
        if not updated.external_draft_id:
            raise HTTPException(status_code=502, detail="Provider created draft but returned no external_draft_id")
        updated.status = draft.status
        updated.approval_state = draft.approval_state
        if not await workspace_state.persist_draft_update_awaited(owner_id, draft_id, {"status": "approved"}, workspace_id=workspace_id):
            raise HTTPException(status_code=503, detail="Provider draft was created but canonical Draft persistence failed")
        if not await persist_outbound_projection(owner_id, workspace_id, updated, change_summary="provider draft created"):
            raise HTTPException(status_code=503, detail="Provider draft projection persistence failed")
        publish(session_token, WMEventType.DRAFT_APPROVED, {
            "draft_id": draft_id, "provider_id": draft.provider_id, "auto": auto, "campaign_id": draft.workflow_id or "",
        }, actor="user")
        return {"ok": True, "draft": updated.model_dump()}
    except HTTPException:
        raise
    except Exception as error:
        publish(session_token, WMEventType.DRAFT_FAILED, {"draft_id": draft_id, "error": str(error)}, actor="system")
        raise HTTPException(status_code=502, detail=str(error))


async def reject_outbound_draft(request: Request | None, draft_id: str) -> dict[str, Any]:
    """Reject one authorized outbound draft and persist its projection."""
    if request is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    session_token = identity_dependencies.web_session_token(request)
    owner_id, workspace_id, _canonical, draft = await require_canonical_outbound_draft(request, session_token, draft_id)
    from services.outbound.outbound_models import ApprovalState, DraftStatus

    draft.approval_state = ApprovalState.REJECTED
    draft.status = DraftStatus.REJECTED
    if not await workspace_state.persist_draft_update_awaited(owner_id, draft_id, {"status": "rejected"}, workspace_id=workspace_id):
        raise HTTPException(status_code=503, detail="Canonical Draft persistence failed")
    if not await persist_outbound_projection(owner_id, workspace_id, draft, change_summary="rejected"):
        raise HTTPException(status_code=503, detail="Draft rejection projection persistence failed")
    publish(session_token, WMEventType.DRAFT_REJECTED, {
        "draft_id": draft_id, "provider_id": draft.provider_id, "campaign_id": draft.workflow_id or "",
    }, actor="user")
    return {"ok": True, "draft": draft.model_dump()}


async def approve_all_outbound_drafts(request: Request | None, auto: bool = False) -> dict[str, Any]:
    """Approve every pending canonical draft in the selected workspace."""
    if request is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    session_token = identity_dependencies.web_session_token(request)
    owner_id = await identity_dependencies.authenticated_user_id(request, session_token)
    workspace_id = await workspace_access.resolve_legacy_workspace_id(request, owner_id)
    pending = [draft for draft in workspace_state.load_drafts_only(owner_id, workspace_id=workspace_id)
               if str(draft.get("status") or "") in ("draft", "pending_approval")]
    if not pending:
        return {"ok": True, "total": 0, "created": 0, "failed": 0, "results": []}
    results = []
    from services.outbound.outbound_models import ApprovalState, DraftStatus

    for canonical in pending:
        draft_id = str(canonical.get("id") or "")
        try:
            _owner, _workspace, _canonical, draft = await require_canonical_outbound_draft(request, session_token, draft_id)
            draft.approval_state = ApprovalState.AUTO_APPROVED if auto else ApprovalState.APPROVED
            draft.status = DraftStatus.AUTO_APPROVED if auto else DraftStatus.APPROVED
            updated = await asyncio.to_thread(outbound_registry.create_draft, draft.provider_id, draft)
            if not updated or not updated.external_draft_id:
                results.append({"draft_id": draft.id, "ok": False, "error": "No provider or no external_draft_id"})
                continue
            updated.status = draft.status
            updated.approval_state = draft.approval_state
            if not await workspace_state.persist_draft_update_awaited(owner_id, draft.id, {"status": "approved"}, workspace_id=workspace_id):
                raise RuntimeError("canonical Draft persistence failed")
            if not await persist_outbound_projection(owner_id, workspace_id, updated, change_summary="provider draft created"):
                raise RuntimeError("Provider draft projection persistence failed")
            results.append({"draft_id": draft.id, "ok": True})
        except Exception as error:
            results.append({"draft_id": draft_id, "ok": False, "error": str(error)})
    created = sum(1 for result in results if result["ok"])
    failed = sum(1 for result in results if not result["ok"])
    publish(session_token, WMEventType.CAMPAIGN_STATUS_CHANGED, {
        "campaign_id": "approve_all", "status": "approved", "draft_count": created, "failed_count": failed,
    }, actor="user")
    return {"ok": True, "total": len(pending), "created": created, "failed": failed, "results": results}


async def create_provider_draft_after_approval(
    canonical_draft: dict[str, Any],
    session_token: str,
    owner_id: str,
    workspace_id: str,
) -> None:
    """Create and durably record a provider-side draft after approval."""
    from services.outbound.outbound_models import ApprovalState, DraftStatus

    draft_id = str(canonical_draft.get("id") or "")
    try:
        outbound_draft = hydrate_outbound_draft(canonical_draft, session_token, owner_id=owner_id)
        draft_id = outbound_draft.id
        # Canonical approval is persisted before this adapter runs.  Status
        # alone therefore cannot distinguish the first approval from a
        # later re-approval of a draft already created at the provider.
        if outbound_draft.status == DraftStatus.SENT or outbound_draft.external_draft_id:
            return
        recipient_email = (outbound_draft.recipient.email if outbound_draft.recipient else "") or ""
        if not str(recipient_email).strip():
            log.info("[outbound_adapter] Draft %s has no recipient email — skipping Gmail draft creation", draft_id)
            return
        outbound_draft.status = DraftStatus.APPROVED
        outbound_draft.approval_state = ApprovalState.APPROVED
        provider_id = resolve_provider_for_draft(outbound_draft, owner_id)
        if not provider_id:
            log.warning("[outbound_adapter] No Gmail outbound provider registered — cannot create Gmail draft for %s", draft_id)
            return
        provider_result = await asyncio.to_thread(outbound_registry.create_draft, provider_id, outbound_draft)
        if provider_result and provider_result.external_draft_id:
            outbound_draft.external_draft_id = provider_result.external_draft_id
            if provider_result.thread_id:
                outbound_draft.thread_id = provider_result.thread_id
            outbound_draft.provider_id = provider_id
            if not await persist_outbound_projection(
                owner_id, workspace_id, outbound_draft, change_summary="provider draft created",
            ):
                raise RuntimeError("Provider draft projection persistence failed")
    except Exception as error:
        log.warning("[outbound_adapter] approve_draft failed for %s: %s", draft_id, error)


async def update_campaign_launch_progress(
    owner_id: str,
    session_token: str,
    campaign_id: str,
    sent_count: int,
    failed_count: int,
    total_count: int,
    *,
    launch_id: str,
) -> bool:
    """Persist campaign send progress for the existing polling endpoint."""
    from services.workspace.state import persist_campaign_update_awaited

    if not launch_id:
        raise ValueError("A durable campaign launch ID is required")

    if total_count <= 0:
        status = "idle"
    elif failed_count == 0:
        status = "launched" if sent_count >= total_count else "sending"
    elif sent_count == 0:
        status = "failed"
    else:
        status = "partial"
    return bool(await persist_campaign_update_awaited(owner_id, campaign_id, {"launch": {
        "total": total_count,
        "sent": sent_count,
        "failed": failed_count,
        "status": status,
    }}))


async def persist_campaign_launch_failure(
    *,
    workspace_id: str,
    campaign_id: str,
    launch_id: str,
    draft_id: str,
    outbound_history_id: str = "",
) -> None:
    """Persist a safe fallback failure only when this attempt lacks history.

    ``OutboundExecutor`` already records provider failures in canonical outbound
    history. Its returned history ID identifies that exact attempt, avoiding a
    broad draft-level lookup that could hide a later launch's separate failure.
    """
    from services.persistence.launch import (
        CampaignLaunchFailureRepository,
        OutboundMessageRepository,
    )

    if outbound_history_id:
        history = await OutboundMessageRepository().get_for_workspace(
            outbound_history_id, workspace_id,
        )
        history_status = getattr(history.status, "value", history.status) if history else ""
        if history and history.draft_id == draft_id and str(history_status).lower() == "failed":
            return
    await CampaignLaunchFailureRepository().record_for_launch(
        campaign_launch_id=launch_id,
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        draft_id=draft_id,
    )


async def _persist_campaign_launch_failure_after_progress(
    *,
    progress_persisted: bool,
    workspace_id: str,
    campaign_id: str,
    launch_id: str,
    draft_id: str,
    outbound_history_id: str = "",
) -> None:
    """Keep non-fatal safe failure persistence after canonical progress."""
    if not progress_persisted:
        log.warning(
            "campaign_launch_failure_not_recorded workspace_id=%s campaign_id=%s launch_id=%s draft_id=%s reason=progress_not_persisted",
            workspace_id, campaign_id, launch_id, draft_id,
        )
        return
    try:
        await persist_campaign_launch_failure(
            workspace_id=workspace_id,
            campaign_id=campaign_id,
            launch_id=launch_id,
            draft_id=draft_id,
            outbound_history_id=outbound_history_id,
        )
    except Exception as error:  # Best-effort timeline projection; launch remains canonical.
        log.warning(
            "campaign_launch_failure_persistence_failed workspace_id=%s campaign_id=%s launch_id=%s draft_id=%s error_type=%s",
            workspace_id, campaign_id, launch_id, draft_id, type(error).__name__,
        )


async def dispatch_campaign_sends(
    session_token: str,
    campaign: dict,
    owner_id: str,
    *,
    workspace_id: str,
    launch_id: str,
) -> dict[str, Any]:
    """Send approved campaign drafts through the existing outbound executor."""
    if not launch_id:
        raise ValueError("A durable campaign launch ID is required")
    campaign_id = campaign.get("id", "")
    durable = workspace_state.load_drafts_only(owner_id, workspace_id)
    approved_durable = [
        draft for draft in durable
        if draft.get("campaign_id") == campaign_id and draft.get("status") == "approved"
    ]
    approved = [
        hydrate_outbound_draft(draft, session_token, owner_id=owner_id)
        for draft in approved_durable
    ]
    if not approved:
        log.info("[campaign_launch] No approved drafts found for campaign %s", campaign_id)
        return {"ok": False, "error": "No approved drafts to send — approve drafts before launching", "total": 0, "sent": 0, "failed": 0, "results": []}

    provider_id = find_outbound_gmail_provider_id()
    if not provider_id:
        log.warning("[campaign_launch] No Gmail outbound provider registered")
        total = len(approved)
        campaign.update({"total_sends": total, "sent_count": 0, "failed_count": total})
        await update_campaign_launch_progress(
            owner_id, session_token, campaign_id, 0, total, total, launch_id=launch_id,
        )
        return {"ok": False, "error": "No Gmail outbound provider registered", "total": total, "sent": 0, "failed": total, "results": []}

    results = []
    sent_count = 0
    failed_count = 0
    for draft in approved:
        failure_occurred = False
        failure_history_id = ""
        try:
            recipient = draft.recipient
            if not str((recipient.email if recipient else "") or "").strip():
                failed_count += 1
                error = "This lead has no email address"
                results.append({"draft_id": draft.id, "ok": False, "error": error})
                publish(session_token, WMEventType.DRAFT_FAILED, {"draft_id": draft.id, "campaign_id": campaign_id, "error": error}, actor="system")
                progress_persisted = await update_campaign_launch_progress(
                    owner_id, session_token, campaign_id, sent_count, failed_count,
                    len(approved), launch_id=launch_id,
                )
                await _persist_campaign_launch_failure_after_progress(
                    progress_persisted=progress_persisted,
                    workspace_id=workspace_id,
                    campaign_id=campaign_id,
                    launch_id=launch_id,
                    draft_id=draft.id,
                )
                continue
            result = await asyncio.to_thread(
                outbound_executor.send_hydrated_draft,
                draft,
                provider_id=provider_id,
            )
            if result.get("ok"):
                from services.workspace.state import persist_draft_update_awaited
                if not await persist_draft_update_awaited(owner_id, draft.id, {"status": "sent"}, workspace_id=workspace_id):
                    raise RuntimeError("Email was sent but canonical Draft persistence failed")
                from services.outbound.outbound_models import DraftStatus
                draft.status = DraftStatus.SENT
                if not await persist_outbound_projection(
                    owner_id, workspace_id, draft, change_summary="sent",
                ):
                    raise RuntimeError("Email was sent but the outbound projection could not be persisted")
                sent_count += 1
                send_data = result.get("send_result", {})
                publish(session_token, WMEventType.DRAFT_SENT, {
                    "draft_id": draft.id,
                    "thread_id": send_data.get("thread_id", ""),
                    "external_message_id": send_data.get("external_message_id", ""),
                    "provider_id": provider_id,
                    "campaign_id": campaign_id,
                    "recipient_email": recipient.email,
                }, actor="system")
                try:
                    from services.conversations.integration import create_conversation_from_send
                    conversation = create_conversation_from_send(
                        provider_id=provider_id,
                        provider_type="gmail",
                        external_thread_id=send_data.get("thread_id", ""),
                        external_message_id=send_data.get("external_message_id", ""),
                        subject=draft.subject,
                        from_email=draft.sender.email,
                        from_name=draft.sender.name,
                        to_email=recipient.email,
                        to_name=recipient.name,
                        body=draft.body,
                        campaign_id=campaign_id,
                        workflow_id=draft.workflow_id or campaign_id,
                        owner_id=owner_id,
                        workspace_id=workspace_id,
                    )
                    simulate_reply({
                        "conversation_id": conversation.conversation_id,
                        "external_thread_id": send_data.get("thread_id", ""),
                        "subject": draft.subject,
                        "from_email": draft.sender.email,
                        "from_name": draft.sender.name,
                        "to_email": recipient.email,
                        "to_name": recipient.name,
                        "body": draft.body,
                        "campaign_id": campaign_id,
                        "workflow_id": draft.workflow_id or campaign_id,
                        "lead": draft.metadata.get("lead", {}) if draft.metadata else {},
                        "objective": campaign.get("objective", ""),
                    })
                except Exception as conversation_error:
                    log.error("persistence_write_failed category=conversation operation=create_from_send draft_id=%s campaign_id=%s provider_id=%s error_type=%s", draft.id[:12], campaign_id[:12], provider_id[:12], type(conversation_error).__name__)
            else:
                failed_count += 1
                failure_occurred = True
                publish(session_token, WMEventType.DRAFT_FAILED, {"draft_id": draft.id, "campaign_id": campaign_id, "error": result.get("error", "Send failed")}, actor="system")
                failure_history_id = str((result.get("send_result") or {}).get("id") or "")
            results.append({"draft_id": draft.id, "ok": result.get("ok", False), "error": result.get("error")})
        except Exception as error:
            failed_count += 1
            failure_occurred = True
            results.append({"draft_id": draft.id, "ok": False, "error": str(error)})
            publish(session_token, WMEventType.DRAFT_FAILED, {"draft_id": draft.id, "campaign_id": campaign_id, "error": str(error)}, actor="system")
            failure_history_id = ""
        progress_persisted = await update_campaign_launch_progress(
            owner_id, session_token, campaign_id, sent_count, failed_count,
            len(approved), launch_id=launch_id,
        )
        if failure_occurred:
            await _persist_campaign_launch_failure_after_progress(
                progress_persisted=progress_persisted,
                workspace_id=workspace_id,
                campaign_id=campaign_id,
                launch_id=launch_id,
                draft_id=draft.id,
                outbound_history_id=failure_history_id,
            )
    total = len(approved)
    campaign.update({"total_sends": total, "sent_count": sent_count, "failed_count": failed_count})
    log.info("[campaign_launch] Complete: %d/%d sent, %d failed", sent_count, total, failed_count)
    return {"ok": True, "total": total, "sent": sent_count, "failed": failed_count, "results": results}
