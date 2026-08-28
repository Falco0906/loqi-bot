"""Phase 6 regressions: Copilot mutation idempotency and durable outcomes."""

from __future__ import annotations

import asyncio
import copy
import uuid

import pytest

from services.copilot_execution_ledger import CopilotExecutionService


class InMemoryLedger:
    """Concurrency-safe repository double with the production unique-key rule."""

    def __init__(self):
        self.rows: dict[tuple[str, str, str], dict] = {}
        self.lock = asyncio.Lock()

    async def get(self, *, user_id, workspace_id, idempotency_key):
        row = self.rows.get((user_id, workspace_id, idempotency_key))
        return copy.deepcopy(row) if row else None

    async def claim(self, *, user_id, workspace_id, idempotency_key, fingerprint, tool_name):
        key = (user_id, workspace_id, idempotency_key)
        async with self.lock:
            existing = self.rows.get(key)
            if existing:
                return copy.deepcopy(existing), False
            row = {
                "id": str(uuid.uuid4()), "user_id": user_id,
                "workspace_id": workspace_id, "idempotency_key": idempotency_key,
                "request_fingerprint": fingerprint, "tool_name": tool_name,
                "status": "running", "result": {},
            }
            self.rows[key] = row
            return copy.deepcopy(row), True

    async def finish(self, *, execution_id, user_id, workspace_id, status, result, error_code="", audit_event=""):
        for key, row in self.rows.items():
            if row["id"] == execution_id and row["user_id"] == user_id and row["workspace_id"] == workspace_id:
                row.update({"status": status, "result": copy.deepcopy(result), "error_code": error_code})
                return copy.deepcopy(row)
        raise RuntimeError("missing execution")


class AuditedService(CopilotExecutionService):
    def __init__(self, repository):
        super().__init__(repository)
        self.audit_events: list[dict] = []

    async def _audit(self, **kwargs):
        self.audit_events.append(kwargs)


def args(**extra):
    return {
        "tool_name": "lead.save",
        "user_id": "user-a",
        "workspace_id": "workspace-a",
        "request_id": "turn-00000001",
        "conversation_key": "chat-a",
        "decision": {"lead_ids": ["lead-1"]},
        **extra,
    }


@pytest.mark.asyncio
async def test_duplicate_mutation_replays_authoritative_result_without_second_side_effect():
    service = AuditedService(InMemoryLedger())
    calls = 0

    async def mutate():
        nonlocal calls
        calls += 1
        return {"ok": True, "status": "completed", "tool": "lead.save", "result": {"saved_ids": ["lead-1"]}}

    first = await service.execute(**args(operation=mutate))
    replay = await service.execute(**args(operation=mutate))

    assert first["ok"] is True
    assert replay["ok"] is True
    assert replay["replayed"] is True
    assert calls == 1
    assert [event["event"] for event in service.audit_events] == ["claimed", "finished"]


@pytest.mark.asyncio
async def test_concurrent_mutation_is_claimed_once_and_other_request_is_in_progress():
    service = AuditedService(InMemoryLedger())
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def mutate():
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return {"ok": True, "status": "completed", "tool": "lead.save", "result": {"saved_ids": ["lead-1"]}}

    first_task = asyncio.create_task(service.execute(**args(operation=mutate)))
    await started.wait()
    duplicate = await service.execute(**args(operation=mutate))
    release.set()
    first = await first_task

    assert first["ok"] is True
    assert duplicate["status"] == "in_progress"
    assert calls == 1


@pytest.mark.asyncio
async def test_failed_mutation_is_durable_and_same_request_does_not_retry_unknown_side_effect():
    service = AuditedService(InMemoryLedger())
    calls = 0

    async def mutate():
        nonlocal calls
        calls += 1
        return {"ok": False, "status": "failed", "tool": "lead.save", "reason": "Canonical write failed."}

    failed = await service.execute(**args(operation=mutate))
    replay = await service.execute(**args(operation=mutate))

    assert failed["status"] == "failed"
    assert replay["status"] == "failed"
    assert replay["replayed"] is True
    assert calls == 1


@pytest.mark.asyncio
async def test_verification_failure_is_not_reported_as_success_and_is_recoverable():
    service = AuditedService(InMemoryLedger())

    async def mutate():
        # A legacy adapter must not be able to turn a verification failure
        # into success merely by leaving an optimistic flag behind.
        return {"ok": True, "status": "verification_failed", "tool": "campaign.refine", "reason": "Could not verify."}

    result = await service.execute(**args(tool_name="campaign.refine", operation=mutate))

    assert result["ok"] is False
    assert result["status"] == "verification_failed"
    assert any(event["status"] == "verification_failed" for event in service.audit_events)


@pytest.mark.asyncio
async def test_missing_authenticated_scope_never_executes_mutation():
    service = AuditedService(InMemoryLedger())
    called = False

    async def mutate():
        nonlocal called
        called = True
        return {"ok": True, "status": "completed"}

    result = await service.execute(**args(workspace_id="", operation=mutate))

    assert result["status"] == "authorization_failed"
    assert called is False


@pytest.mark.asyncio
async def test_same_idempotency_key_cannot_cross_workspace_or_change_operation():
    service = AuditedService(InMemoryLedger())

    async def mutate():
        return {"ok": True, "status": "completed", "tool": "lead.save", "result": {}}

    first = await service.execute(**args(operation=mutate))
    other_workspace = await service.execute(**args(workspace_id="workspace-b", operation=mutate))
    conflicting = await service.execute(**args(decision={"lead_ids": ["lead-2"]}, operation=mutate))

    assert first["ok"] is True
    assert other_workspace["ok"] is True
    assert other_workspace.get("replayed") is not True
    assert conflicting["status"] == "idempotency_conflict"
