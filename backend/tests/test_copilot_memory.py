"""Phase 5 regressions for bounded, durable Copilot memory."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.copilot_memory import (
    MAX_TURNS,
    MEMORY_MAX_AGE,
    UNFINISHED_TASK_MAX_AGE,
    CopilotMemoryService,
    merge_turn_history,
)


class FakeCopilotMemoryRepository:
    """Durable-repository test double keyed exactly like the production table."""

    def __init__(self, now):
        self.now = now
        self.rows: dict[tuple[str, str, str], dict] = {}

    async def get(self, *, user_id: str, workspace_id: str, conversation_key: str):
        row = self.rows.get((user_id, workspace_id, conversation_key))
        return dict(row) if row else None

    async def save(self, *, user_id: str, workspace_id: str, conversation_key: str, memory: dict):
        self.rows[(user_id, workspace_id, conversation_key)] = {
            "memory": memory,
            "updated_at": self.now().isoformat(),
        }


@pytest.mark.asyncio
async def test_memory_persists_compact_conversation_context_across_service_instances():
    now = lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)
    repository = FakeCopilotMemoryRepository(now)
    writer = CopilotMemoryService(repository, now=now)
    await writer.record_turn(
        user_id="user-a", workspace_id="workspace-a", conversation_key="chat-a",
        user_text="Focus on restaurant owners in Hyderabad.", intent="discovery_refinement",
    )

    reader = CopilotMemoryService(repository, now=now)
    restored = await reader.retrieve(
        user_id="user-a", workspace_id="workspace-a", conversation_key="chat-a",
    )

    assert restored["conversation_turns"] == [{
        "role": "user", "text": "Focus on restaurant owners in Hyderabad.",
    }]


@pytest.mark.asyncio
async def test_memory_isolated_by_authenticated_user_workspace_and_conversation_key():
    now = lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)
    repository = FakeCopilotMemoryRepository(now)
    service = CopilotMemoryService(repository, now=now)
    await service.record_turn(
        user_id="user-a", workspace_id="workspace-a", conversation_key="chat-a",
        user_text="Private workspace A context.",
    )

    assert await service.retrieve(user_id="user-b", workspace_id="workspace-a", conversation_key="chat-a") == {}
    assert await service.retrieve(user_id="user-a", workspace_id="workspace-b", conversation_key="chat-a") == {}
    assert await service.retrieve(user_id="user-a", workspace_id="workspace-a", conversation_key="chat-b") == {}


@pytest.mark.asyncio
async def test_stale_memory_is_not_injected_as_current_context():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    repository = FakeCopilotMemoryRepository(lambda: base)
    repository.rows[("user-a", "workspace-a", "chat-a")] = {
        "memory": {"turns": [{"role": "user", "text": "Old context"}]},
        "updated_at": (base - MEMORY_MAX_AGE - timedelta(seconds=1)).isoformat(),
    }
    service = CopilotMemoryService(repository, now=lambda: base)

    assert await service.retrieve(
        user_id="user-a", workspace_id="workspace-a", conversation_key="chat-a",
    ) == {}


@pytest.mark.asyncio
async def test_stale_unfinished_task_is_not_reused_as_live_operation_state():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    repository = FakeCopilotMemoryRepository(lambda: base)
    repository.rows[("user-a", "workspace-a", "chat-a")] = {
        "memory": {
            "turns": [{"role": "user", "text": "Find leads"}],
            "unfinished_task": {
                "job_id": "job-old",
                "status": "accepted",
                "updated_at": (base - UNFINISHED_TASK_MAX_AGE - timedelta(seconds=1)).isoformat(),
            },
        },
        "updated_at": base.isoformat(),
    }
    service = CopilotMemoryService(repository, now=lambda: base)

    restored = await service.retrieve(
        user_id="user-a", workspace_id="workspace-a", conversation_key="chat-a",
    )
    assert restored["unfinished_task"] is None
    assert restored["conversation_turns"]


@pytest.mark.asyncio
async def test_memory_limits_turns_and_untrusted_client_history():
    now = lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)
    repository = FakeCopilotMemoryRepository(now)
    service = CopilotMemoryService(repository, now=now)
    for index in range(MAX_TURNS + 5):
        await service.record_turn(
            user_id="user-a", workspace_id="workspace-a", conversation_key="chat-a",
            user_text=f"turn-{index}",
        )

    restored = await service.retrieve(
        user_id="user-a", workspace_id="workspace-a", conversation_key="chat-a",
    )
    assert len(restored["conversation_turns"]) == MAX_TURNS
    assert restored["conversation_turns"][0]["text"] == "turn-5"

    merged = merge_turn_history(restored, [
        {"role": "user", "text": f"client-{index}"} for index in range(MAX_TURNS + 5)
    ])
    assert len(merged) == MAX_TURNS
    assert merged[-1]["text"] == f"client-{MAX_TURNS + 4}"


@pytest.mark.asyncio
async def test_unfinished_task_and_completed_history_are_derived_from_actual_outcomes():
    now = lambda: datetime(2026, 1, 1, tzinfo=timezone.utc)
    repository = FakeCopilotMemoryRepository(now)
    service = CopilotMemoryService(repository, now=now)
    kwargs = {"user_id": "user-a", "workspace_id": "workspace-a", "conversation_key": "chat-a"}
    await service.record_turn(**kwargs, user_text="Find new leads", intent="discovery")
    await service.record_outcome(
        **kwargs,
        tool="discovery.search",
        status="accepted",
        operation={"kind": "search_discovery", "job_id": "job-a", "discovery_id": "discovery-a"},
    )
    pending = await service.retrieve(**kwargs)
    assert pending["unfinished_task"]["job_id"] == "job-a"

    await service.record_outcome(
        **kwargs,
        tool="discovery.search",
        status="completed",
        operation={"kind": "search_discovery", "job_id": "job-a", "discovery_id": "discovery-a"},
    )
    completed = await service.retrieve(**kwargs)
    assert completed["unfinished_task"] is None
    assert completed["workspace_history"][-1]["status"] == "completed"


def test_generated_response_labels_memory_as_context_not_workspace_authority(monkeypatch):
    from services import conversational_response_generator as generator

    captured: dict[str, str] = {}

    def fake_openai(system: str, _user: str, timeout: int = 20):
        captured["system"] = system
        return "Fact: no current campaign data was supplied. Recommendation: retrieve it before deciding."

    monkeypatch.setattr(generator, "_send_openai_request", fake_openai)
    result = generator.generate_copilot_response(
        "What should I do next?",
        copilot_context={
            "mvp_read_only": True,
            "workspace_context": {
                "copilot_memory": {
                    "conversation_turns": [{"role": "user", "text": "I prefer concise drafts."}],
                    "workspace_history": [{"tool": "discovery.search", "status": "completed"}],
                    "unfinished_task": {"job_id": "job-a"},
                    "user_preferences": {"tone": "concise"},
                },
            },
        },
    )

    assert result.startswith("Fact:")
    assert "not current workspace truth" in captured["system"]
    assert "User preferences" in captured["system"]
