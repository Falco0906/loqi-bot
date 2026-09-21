"""Regression coverage for synchronous provider projection isolation."""
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services.outbound import service as outbound_service
from services.outbound.outbound_models import DraftMessage, Recipient


def _draft(draft_id: str = "draft-1") -> DraftMessage:
    return DraftMessage(
        id=draft_id,
        provider_id="provider-1",
        subject="Subject",
        body="Body",
        recipient=Recipient(email="lead@example.com", name="Lead"),
        sender=Recipient(email="sender@example.com", name="Sender"),
    )


async def _true(*_args, **_kwargs):
    return True


async def _workspace_id(*_args, **_kwargs):
    return "workspace-1"


def _patch_create_dependencies(monkeypatch, calls: list[str]) -> None:
    monkeypatch.setattr(outbound_service.identity_dependencies, "web_session_token", lambda _request: "token-1")
    monkeypatch.setattr(outbound_service.identity_dependencies, "authenticated_user_id", _owner_id)
    monkeypatch.setattr(outbound_service, "provider_owned_by", lambda *_args: True)
    monkeypatch.setattr(outbound_service.workspace_access, "resolve_legacy_workspace_id", _workspace_id)

    async def persist_draft(*_args, **_kwargs):
        calls.append("canonical")
        return True

    async def persist_projection(*_args, **_kwargs):
        calls.append("projection")
        return True

    monkeypatch.setattr(outbound_service.workspace_state, "persist_draft_awaited", persist_draft)
    monkeypatch.setattr(outbound_service, "persist_outbound_projection", persist_projection)
    monkeypatch.setattr(outbound_service, "publish", lambda *_args, **_kwargs: None)


async def _owner_id(*_args, **_kwargs):
    return "owner-1"


@pytest.mark.asyncio
async def test_create_projection_runs_in_thread_without_blocking_event_loop(monkeypatch):
    """A blocking provider must not stall other work on the route's event loop."""
    calls: list[str] = []
    _patch_create_dependencies(monkeypatch, calls)
    entered = threading.Event()
    release = threading.Event()
    progressed = asyncio.Event()

    def blocking_create(_provider_id, draft):
        calls.append("provider")
        entered.set()
        assert release.wait(timeout=1)
        return draft.model_copy(update={"external_draft_id": "external-1"})

    monkeypatch.setattr(outbound_service.outbound_registry, "create_draft", blocking_create)
    payload = {
        "provider_id": "provider-1", "subject": "Subject", "body": "Body",
        "recipient_email": "lead@example.com", "sender_email": "sender@example.com",
    }
    operation = asyncio.create_task(outbound_service.create_outbound_draft(SimpleNamespace(), payload))
    assert await asyncio.to_thread(entered.wait, 1), "provider stub was not invoked"

    async def other_coroutine():
        await asyncio.sleep(0)
        progressed.set()

    await other_coroutine()
    assert progressed.is_set(), "blocking provider call stalled the event loop"
    release.set()
    result = await operation

    assert result["ok"] is True
    assert result["draft"]["external_draft_id"] == "external-1"
    assert calls == ["canonical", "provider", "projection"]


@pytest.mark.asyncio
async def test_create_projection_failure_preserves_existing_error_and_compensation(monkeypatch):
    calls: list[str] = []
    _patch_create_dependencies(monkeypatch, calls)

    async def mark_failed(*_args, **_kwargs):
        calls.append("failed")
        return True

    monkeypatch.setattr(outbound_service.workspace_state, "persist_draft_update_awaited", mark_failed)
    monkeypatch.setattr(
        outbound_service.outbound_registry,
        "create_draft",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
    )

    with pytest.raises(HTTPException) as error:
        await outbound_service.create_outbound_draft(SimpleNamespace(), {
            "provider_id": "provider-1", "subject": "Subject", "body": "Body",
            "recipient_email": "lead@example.com", "sender_email": "sender@example.com",
        })

    assert error.value.status_code == 502
    assert error.value.detail == "Draft was persisted but provider projection failed"
    assert calls == ["canonical", "failed"]


@pytest.mark.asyncio
async def test_approve_all_keeps_sequential_partial_failure_contract(monkeypatch):
    first = _draft("draft-1")
    second = _draft("draft-2")
    calls: list[str] = []
    monkeypatch.setattr(outbound_service.identity_dependencies, "web_session_token", lambda _request: "token-1")
    monkeypatch.setattr(outbound_service.identity_dependencies, "authenticated_user_id", _owner_id)
    monkeypatch.setattr(outbound_service.workspace_access, "resolve_legacy_workspace_id", _workspace_id)
    monkeypatch.setattr(
        outbound_service.workspace_state,
        "load_drafts_only",
        lambda *_args, **_kwargs: [{"id": "draft-1", "status": "draft"}, {"id": "draft-2", "status": "draft"}],
    )

    async def require(_request, _token, draft_id, **_kwargs):
        draft = first if draft_id == "draft-1" else second
        return "owner-1", "workspace-1", {"id": draft_id}, draft

    async def persist_draft(*_args, **_kwargs):
        calls.append("canonical")
        return True

    async def persist_projection(*_args, **_kwargs):
        calls.append("projection")
        return True

    def create(_provider_id, draft):
        calls.append(draft.id)
        if draft.id == "draft-2":
            raise RuntimeError("provider unavailable")
        return draft.model_copy(update={"external_draft_id": "external-1"})

    monkeypatch.setattr(outbound_service, "require_canonical_outbound_draft", require)
    monkeypatch.setattr(outbound_service.workspace_state, "persist_draft_update_awaited", persist_draft)
    monkeypatch.setattr(outbound_service, "persist_outbound_projection", persist_projection)
    monkeypatch.setattr(outbound_service.outbound_registry, "create_draft", create)
    monkeypatch.setattr(outbound_service, "publish", lambda *_args, **_kwargs: None)

    result = await outbound_service.approve_all_outbound_drafts(SimpleNamespace())

    assert result == {
        "ok": True,
        "total": 2,
        "created": 1,
        "failed": 1,
        "results": [
            {"draft_id": "draft-1", "ok": True},
            {"draft_id": "draft-2", "ok": False, "error": "provider unavailable"},
        ],
    }
    assert calls == ["draft-1", "canonical", "projection", "draft-2"]


@pytest.mark.asyncio
async def test_approve_denies_unowned_draft_before_provider_projection(monkeypatch):
    """The threaded boundary must not weaken the canonical ownership gate."""
    monkeypatch.setattr(outbound_service.identity_dependencies, "web_session_token", lambda _request: "token-1")

    async def denied(*_args, **_kwargs):
        raise HTTPException(status_code=404, detail="Draft not found")

    provider_called = False

    def create(*_args, **_kwargs):
        nonlocal provider_called
        provider_called = True
        return _draft()

    monkeypatch.setattr(outbound_service, "require_canonical_outbound_draft", denied)
    monkeypatch.setattr(outbound_service.outbound_registry, "create_draft", create)

    with pytest.raises(HTTPException) as error:
        await outbound_service.approve_outbound_draft(SimpleNamespace(), "foreign-draft")

    assert error.value.status_code == 404
    assert provider_called is False


@pytest.mark.asyncio
async def test_update_delete_and_approve_keep_existing_response_shapes(monkeypatch):
    """Thread isolation changes no lifecycle response envelope."""
    draft = _draft()
    deleted: list[tuple[str, str]] = []
    monkeypatch.setattr(outbound_service.identity_dependencies, "web_session_token", lambda _request: "token-1")

    async def require(_request, _token, _draft_id, **_kwargs):
        return "owner-1", "workspace-1", {"id": draft.id}, draft

    monkeypatch.setattr(outbound_service, "require_canonical_outbound_draft", require)
    monkeypatch.setattr(outbound_service.workspace_state, "persist_draft_update_awaited", _true)
    monkeypatch.setattr(outbound_service, "persist_outbound_projection", _true)
    monkeypatch.setattr(outbound_service, "publish", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        outbound_service.outbound_registry,
        "update_draft",
        lambda _provider_id, updated: updated.model_copy(update={"external_draft_id": "external-1"}),
    )
    monkeypatch.setattr(
        outbound_service.outbound_registry,
        "create_draft",
        lambda _provider_id, approved: approved.model_copy(update={"external_draft_id": "external-2"}),
    )
    monkeypatch.setattr(
        outbound_service.outbound_registry,
        "delete_draft",
        lambda provider_id, external_draft_id: deleted.append((provider_id, external_draft_id)) or True,
    )
    from services.learning import behavior_tracker, feedback_interpreter

    monkeypatch.setattr(behavior_tracker, "get_tracker", lambda: object())
    monkeypatch.setattr(
        feedback_interpreter,
        "FeedbackInterpreter",
        lambda _tracker: SimpleNamespace(on_draft_rejected=lambda *_args: None),
    )

    updated = await outbound_service.update_outbound_draft(SimpleNamespace(), draft.id, {
        "provider_id": "provider-1", "external_draft_id": "external-1", "subject": "Updated",
    })
    assert updated["ok"] is True
    assert updated["draft"]["subject"] == "Updated"

    draft.external_draft_id = "external-1"
    deleted_result = await outbound_service.delete_outbound_draft(SimpleNamespace(), draft.id, "provider-1")
    assert deleted_result == {"ok": True}
    assert deleted == [("provider-1", "external-1")]

    approved = await outbound_service.approve_outbound_draft(SimpleNamespace(), draft.id)
    assert approved["ok"] is True
    assert approved["draft"]["external_draft_id"] == "external-2"
