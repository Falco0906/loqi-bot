"""Email execution guards over canonical draft state."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

import main as main_module
import services.outbound.service as outbound_service
from services.outbound.api import send_draft
from services.outbound.outbound_models import ApprovalState, DraftMessage, DraftStatus, Recipient


def _draft(email: str):
    return DraftMessage(
        id="draft-no-email", provider_id="provider-1", subject="Subject", body="Body",
        recipient=Recipient(email=email, name="Lead"), sender=Recipient(email="me@example.com", name="Me"),
        status=DraftStatus.APPROVED, approval_state=ApprovalState.APPROVED,
    )


async def _canonical(_request, _token, _draft_id, **_kwargs):
    draft = _draft("")
    return "owner-1", "workspace-1", {"id": draft.id, "status": "approved"}, draft


def test_send_draft_without_email_never_invokes_executor(monkeypatch):
    monkeypatch.setattr(outbound_service, "require_canonical_outbound_draft", _canonical)
    monkeypatch.setattr(outbound_service, "outbound_executor", MagicMock())

    result = asyncio.run(send_draft("token", "draft-no-email", MagicMock()))

    assert result == {"ok": False, "error": "This lead has no email address"}
    outbound_service.outbound_executor.send_hydrated_draft.assert_not_called()


async def test_campaign_dispatch_marks_no_email_draft_failed(monkeypatch):
    drafts = [{
        "id": "draft-no-email", "campaign_id": "campaign-1", "status": "approved",
        "lead": {"email": "", "name": "Lead"}, "subject": "Subject", "text": "Body",
    }]
    monkeypatch.setattr(outbound_service.workspace_state, "load_drafts_only", lambda *_args, **_kwargs: drafts)
    monkeypatch.setattr(outbound_service, "find_outbound_gmail_provider_id", lambda: "provider-1")
    monkeypatch.setattr(outbound_service, "publish", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(outbound_service, "update_campaign_launch_progress", lambda *_args, **_kwargs: asyncio.sleep(0))

    result = await outbound_service.dispatch_campaign_sends(
        "token", {"id": "campaign-1"}, "owner-1",
        workspace_id="workspace-1", launch_id="launch-1",
    )

    assert result["failed"] == 1
    assert result["results"][0]["error"] == "This lead has no email address"
