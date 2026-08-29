"""Outbound draft projection, provider ownership, and campaign dispatch."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Request

from services.communication.communication_store import store as communication_store
from services.communication.provider_registry import get_provider as get_communication_provider
import services.identity.dependencies as identity_dependencies
from services.outbound import draft_store as outbound_draft_store_module
from services.outbound import outbound_registry
from services.outbound.outbound_executor import executor as outbound_executor
from services.outbound.outbound_registry import (
    get_provider as get_outbound_provider,
    list_providers as outbound_list_providers,
)
import services.workspace_context as workspace_access
import services.workspace_state as workspace_state
from services.world_model import EventType as WMEventType, publish
from services.communication.reply_simulator import maybe_schedule as simulate_reply

log = logging.getLogger("loqi")


def find_outbound_gmail_provider_id() -> str:
    """Return the first registered Gmail outbound provider, if any."""
    for provider_id, instance in outbound_list_providers().items():
        if getattr(instance, "provider_type", None) == "gmail":
            return provider_id
    return ""


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


def sync_draft_to_outbound(legacy_draft: dict, session_token: str, owner_id: str = "") -> None:
    """Project a durable campaign draft into the outbound DraftStore."""
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
    if outbound_draft_store_module.draft_store.get(outbound_draft.id):
        outbound_draft_store_module.draft_store.update(outbound_draft)
    else:
        outbound_draft_store_module.draft_store.create(outbound_draft)


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
    sync_draft_to_outbound(canonical, session_token, owner_id=owner_id)
    outbound_draft = outbound_draft_store_module.draft_store.get(draft_id)
    if outbound_draft is None:
        raise HTTPException(status_code=503, detail="Draft projection could not be loaded")
    if canonical_provider and not outbound_draft_owned_by(outbound_draft, owner_id):
        raise HTTPException(status_code=404, detail="Draft not found")
    return owner_id, workspace_id, canonical, outbound_draft


def outbound_to_legacy_draft(outbound_draft: object) -> dict[str, Any]:
    """Return the existing legacy dictionary representation of an outbound draft."""
    from services.outbound.outbound_models import DraftStatus

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


async def persist_outbound_projection(
    owner_id: str, workspace_id: str, outbound_draft: object, *, change_summary: str = "",
) -> bool:
    """Commit provider-only draft state to the authorized canonical Draft."""
    from services.outbound.outbound_persistence import persist_draft_projection

    return await persist_draft_projection(
        owner_id, workspace_id, outbound_draft, change_summary=change_summary,
    )
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
        outbound_draft_store_module.draft_store.update(outbound_draft)
    return resolved


def create_provider_draft_after_approval(draft_id: str) -> None:
    """Create the existing provider-side Gmail draft after a local approval."""
    from services.outbound.outbound_models import DraftStatus

    try:
        outbound_draft = outbound_draft_store_module.draft_store.get(draft_id)
        if not outbound_draft:
            log.warning("[outbound_adapter] Draft %s not found in outbound store", draft_id)
            return
        if outbound_draft.status in (DraftStatus.APPROVED, DraftStatus.AUTO_APPROVED, DraftStatus.SENT):
            return
        recipient_email = (outbound_draft.recipient.email if outbound_draft.recipient else "") or ""
        if not str(recipient_email).strip():
            log.info("[outbound_adapter] Draft %s has no recipient email — skipping Gmail draft creation", draft_id)
            return
        outbound_draft_store_module.draft_store.approve(draft_id)
        provider_id = resolve_provider_for_draft(outbound_draft)
        if not provider_id:
            log.warning("[outbound_adapter] No Gmail outbound provider registered — cannot create Gmail draft for %s", draft_id)
            return
        provider_result = outbound_registry.create_draft(provider_id, outbound_draft)
        if provider_result and provider_result.external_draft_id:
            updated = outbound_draft_store_module.draft_store.get(draft_id)
            if updated:
                updated.external_draft_id = provider_result.external_draft_id
                if provider_result.thread_id:
                    updated.thread_id = provider_result.thread_id
                updated.provider_id = provider_id
                outbound_draft_store_module.draft_store.update(updated)
    except Exception as error:
        log.warning("[outbound_adapter] approve_draft failed for %s: %s", draft_id, error)


async def update_campaign_launch_progress(
    owner_id: str,
    session_token: str,
    campaign_id: str,
    sent_count: int,
    failed_count: int,
    total_count: int,
) -> None:
    """Persist campaign send progress for the existing polling endpoint."""
    from services.workspace_state import persist_campaign_update_awaited

    if total_count <= 0:
        status = "idle"
    elif failed_count == 0:
        status = "launched" if sent_count >= total_count else "sending"
    elif sent_count == 0:
        status = "failed"
    else:
        status = "partial"
    await persist_campaign_update_awaited(owner_id, campaign_id, {"launch": {
        "total": total_count,
        "sent": sent_count,
        "failed": failed_count,
        "status": status,
    }})


async def dispatch_campaign_sends(
    session_token: str,
    campaign: dict,
    owner_id: str,
    *,
    workspace_id: str,
) -> dict[str, Any]:
    """Send approved campaign drafts through the existing outbound executor."""
    campaign_id = campaign.get("id", "")
    durable = workspace_state.load_drafts_only(owner_id, workspace_id)
    approved_durable = [
        draft for draft in durable
        if draft.get("campaign_id") == campaign_id and draft.get("status") == "approved"
    ]
    for draft in approved_durable:
        sync_draft_to_outbound(draft, session_token, owner_id=owner_id)

    approved_ids = {draft["id"] for draft in approved_durable}
    all_outbound = outbound_draft_store_module.draft_store.list_by_workflow(campaign_id)
    approved = [
        draft for draft in all_outbound.drafts
        if draft.id in approved_ids and draft.status.value in ("approved", "auto_approved")
    ]
    if not approved:
        log.info("[campaign_launch] No approved drafts found for campaign %s", campaign_id)
        return {"ok": False, "error": "No approved drafts to send — approve drafts before launching", "total": 0, "sent": 0, "failed": 0, "results": []}

    provider_id = find_outbound_gmail_provider_id()
    if not provider_id:
        log.warning("[campaign_launch] No Gmail outbound provider registered")
        total = len(approved)
        campaign.update({"total_sends": total, "sent_count": 0, "failed_count": total})
        await update_campaign_launch_progress(owner_id, session_token, campaign_id, 0, total, total)
        return {"ok": False, "error": "No Gmail outbound provider registered", "total": total, "sent": 0, "failed": total, "results": []}

    results = []
    sent_count = 0
    failed_count = 0
    for draft in approved:
        try:
            recipient = draft.recipient
            if not str((recipient.email if recipient else "") or "").strip():
                failed_count += 1
                error = "This lead has no email address"
                results.append({"draft_id": draft.id, "ok": False, "error": error})
                publish(session_token, WMEventType.DRAFT_FAILED, {"draft_id": draft.id, "campaign_id": campaign_id, "error": error}, actor="system")
                await update_campaign_launch_progress(owner_id, session_token, campaign_id, sent_count, failed_count, len(approved))
                continue
            result = await asyncio.to_thread(outbound_executor.execute, "send_reply", {
                "provider_id": provider_id,
                "draft_id": draft.id,
                "conversation_id": draft.conversation_id,
                "thread_id": draft.thread_id,
                "workflow_id": draft.workflow_id,
                "subject": draft.subject,
                "body": draft.body,
                "recipient": {"email": recipient.email, "name": recipient.name},
                "sender": {"email": draft.sender.email, "name": draft.sender.name},
            })
            if result.get("ok"):
                from services.workspace_state import persist_draft_update_awaited
                if not await persist_draft_update_awaited(owner_id, draft.id, {"status": "sent"}, workspace_id=workspace_id):
                    raise RuntimeError("Email was sent but canonical Draft persistence failed")
                sent_count += 1
                outbound_draft_store_module.draft_store.mark_sent(draft.id)
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
                publish(session_token, WMEventType.DRAFT_FAILED, {"draft_id": draft.id, "campaign_id": campaign_id, "error": result.get("error", "Send failed")}, actor="system")
            results.append({"draft_id": draft.id, "ok": result.get("ok", False), "error": result.get("error")})
        except Exception as error:
            failed_count += 1
            results.append({"draft_id": draft.id, "ok": False, "error": str(error)})
            publish(session_token, WMEventType.DRAFT_FAILED, {"draft_id": draft.id, "campaign_id": campaign_id, "error": str(error)}, actor="system")
        await update_campaign_launch_progress(owner_id, session_token, campaign_id, sent_count, failed_count, len(approved))
    total = len(approved)
    campaign.update({"total_sends": total, "sent_count": sent_count, "failed_count": failed_count})
    log.info("[campaign_launch] Complete: %d/%d sent, %d failed", sent_count, total, failed_count)
    return {"ok": True, "total": total, "sent": sent_count, "failed": failed_count, "results": results}
