"""Durable campaign creation identity and atomic canonical persistence."""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from fastapi import HTTPException
from services.persistence.launch import CampaignRepository
from services.workspace.state import import_workspace_lead


def creation_identity(workspace_id: str, actor_user_id: str, key: str, payload: dict[str, Any]) -> tuple[str, str]:
    """A key identifies intent; content is fingerprinted separately to reject changes."""
    scope = json.dumps([workspace_id, actor_user_id, key], separators=(",", ":"))
    campaign_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "loqi:campaign-creation:" + scope))
    content = {name: payload.get(name) for name in
               ("name", "objective", "search_query", "discovery_id", "status", "strategy", "leads")}
    # The declared count is not state: canonical attachments determine it.
    content["leads"] = sorted(content["leads"] or [], key=lambda lead: json.dumps(lead, sort_keys=True, allow_nan=False))
    for name in ("objective", "search_query", "discovery_id"):
        content[name] = content[name] or ""
    content["status"] = content["status"] or "planning"
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return campaign_id, digest


async def recover_creation(workspace_id: str, actor_user_id: str, campaign_id: str, request_hash: str):
    existing = await CampaignRepository().get_creation(campaign_id, workspace_id)
    if existing is not None:
        if existing.created_by != actor_user_id or existing.metadata.get("creation_request_hash") != request_hash:
            raise HTTPException(409, "Idempotency key was already used for a different campaign request")
        if existing.deleted_at is not None or existing.status == "deleted":
            raise HTTPException(410, "The original campaign was deleted")
    return existing


async def persist_creation(workspace_id: str, actor_user_id: str, campaign_id: str,
                           request_hash: str, campaign: dict[str, Any]) -> bool:
    """Normalize legacy inline inputs, then commit only workspace-scoped IDs."""
    lead_ids = []
    for lead in campaign["leads"]:
        lead_id = lead.get("workspace_lead_id") or await import_workspace_lead(workspace_id, lead)
        if not lead_id:
            raise HTTPException(422, "Selected lead could not be resolved")
        lead_ids.append(str(lead_id))
    lead_ids = list(dict.fromkeys(lead_ids))
    try:
        _entity, created = await CampaignRepository().create_once(
            campaign_id=campaign_id, workspace_id=workspace_id, actor_user_id=actor_user_id,
            request_hash=request_hash, campaign=campaign, lead_ids=lead_ids)
    except Exception as error:
        code, message = getattr(error, "code", None), getattr(error, "message", "")
        if code == "23514" and message == "Idempotency key belongs to a different request":
            raise HTTPException(409, "Idempotency key was already used for a different campaign request") from error
        if code == "42501" and message in {"Workspace access denied", "Workspace unavailable", "Selected lead unavailable in workspace", "Discovery unavailable in workspace"}:
            raise HTTPException(404, "Campaign inputs are unavailable in the authorized workspace") from error
        if code == "P0002" and message == "Campaign was deleted":
            raise HTTPException(410, "The original campaign was deleted") from error
        raise
    return created
