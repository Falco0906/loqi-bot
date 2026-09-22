"""Production Inbox persistence uses Supabase snapshots, never local files."""

import importlib.util
from types import SimpleNamespace
from pathlib import Path

import httpx
import pytest

from services.conversations import persistence
from services.conversations.conversation_models import Conversation, ConversationStatus
from services.conversations.conversation_store import (
    ConversationPersistenceUnavailable,
    ConversationStore,
    ConversationStoreRehydrationState,
)


def test_conversation_snapshot_round_trip_uses_durable_table(monkeypatch):
    rows: list[dict] = []

    class Query:
        def __init__(self):
            self.params = {}
            self._range = (0, len(rows))
        def upsert(self, row, **_kwargs):
            rows[:] = [item for item in rows if item["conversation_id"] != row["conversation_id"]]
            rows.append(row)
            return self
        def select(self, *_args): return self
        def order(self, *_args): return self
        def range(self, start, end):
            self._range = (start, end + 1)
            return self
        def execute(self): return SimpleNamespace(data=list(rows)[slice(*self._range)])

    class RpcQuery:
        def __init__(self, params): self.params = params
        def execute(self):
            conversation_id = self.params["p_conversation_id"]
            existing = next((row for row in rows if row["conversation_id"] == conversation_id), None)
            expected = self.params["p_expected_version"]
            if existing and existing.get("version", 0) != expected:
                raise RuntimeError("conversation snapshot version conflict")
            version = (existing.get("version", 0) if existing else 0) + 1
            row = {
                "conversation_id": conversation_id,
                "owner_id": self.params["p_owner_id"],
                "workspace_id": self.params["p_workspace_id"],
                "snapshot": self.params["p_snapshot"],
                "version": version,
            }
            rows[:] = [item for item in rows if item["conversation_id"] != conversation_id] + [row]
            return SimpleNamespace(data=version)

    class Client:
        def table(self, name):
            assert name == "conversation_snapshots"
            return Query()
        def rpc(self, name, params):
            assert name == "persist_conversation_snapshot"
            return RpcQuery(params)

    monkeypatch.setattr(persistence, "_client", lambda: Client())
    monkeypatch.setattr(persistence.json_file, "atomic_write_json", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("file fallback used")))
    snapshot = {
        "sequence": 3,
        "conversations": [{"conversation_id": "conv-1", "owner_id": "owner-1", "metadata": {"workspace_id": "workspace-1"}}],
        "threads": [{"thread_id": "thread-1", "conversation_id": "conv-1"}],
        "messages": [{"message_id": "msg-1", "conversation_id": "conv-1"}],
        "timeline": {"conv-1": [{"event_id": "event-1"}]},
    }

    persistence.save(snapshot)
    restored, status = persistence.load_state()

    assert status == persistence.json_file.JsonFileStatus.OK
    assert restored is not None
    assert restored["conversations"][0]["conversation_id"] == "conv-1"
    assert restored["messages"][0]["message_id"] == "msg-1"


def test_single_conversation_mutation_persists_only_that_conversation(monkeypatch):
    """One Inbox mutation must not rewrite unrelated durable snapshots."""
    captured: list[dict] = []

    monkeypatch.setattr(
        persistence,
        "load_state",
        lambda: (None, persistence.json_file.JsonFileStatus.ABSENT),
    )

    def save(snapshot):
        captured.append(snapshot)
        return {
            conversation["conversation_id"]: 1
            for conversation in snapshot["conversations"]
        }

    monkeypatch.setattr(persistence, "save", save)

    store = ConversationStore()
    store.reload()
    first = Conversation(owner_id="owner-1", metadata={"workspace_id": "workspace-1"})
    second = Conversation(owner_id="owner-1", metadata={"workspace_id": "workspace-1"})
    store.create_conversation(first)
    store.create_conversation(second)
    captured.clear()

    first.metadata["marker"] = "updated-only-this-conversation"
    store.update_conversation(first)

    assert len(captured) == 1
    snapshot = captured[0]
    assert [row["conversation_id"] for row in snapshot["conversations"]] == [
        first.conversation_id
    ]
    assert second.conversation_id not in snapshot["timeline"]


def test_retryable_durable_read_failure_is_not_classified_as_corrupt(monkeypatch):
    attempts = 0

    class Query:
        def select(self, *_args):
            return self

        def order(self, *_args):
            return self

        def range(self, *_args):
            return self

        def execute(self):
            nonlocal attempts
            attempts += 1
            raise httpx.ReadTimeout("temporary Supabase timeout")

    class Client:
        def table(self, name):
            assert name == "conversation_snapshots"
            return Query()

    monkeypatch.setattr(persistence, "_client", lambda: Client())
    monkeypatch.setattr(persistence.retry, "_sleep_with_jitter", lambda _delay: None)

    with pytest.raises(persistence.DurableConversationPersistenceUnavailable):
        persistence.load_state()

    assert attempts == 3


def test_supabase_api_error_is_explicitly_unavailable_not_corrupt(monkeypatch):
    class APIError(RuntimeError):
        pass

    class Query:
        def select(self, *_args):
            return self

        def order(self, *_args):
            return self

        def range(self, *_args):
            return self

        def execute(self):
            raise APIError("database API rejected the request")

    class Client:
        def table(self, name):
            assert name == "conversation_snapshots"
            return Query()

    with monkeypatch.context() as patch:
        patch.setattr(persistence, "_client", lambda: Client())
        with pytest.raises(persistence.DurableConversationPersistenceUnavailable) as error:
            persistence.load_state()

    assert isinstance(error.value.__cause__, APIError)


@pytest.mark.parametrize("failure", [httpx.ReadTimeout("timeout"), RuntimeError("APIError")])
def test_main_import_never_calls_conversation_persistence(monkeypatch, failure):
    calls = 0

    class Client:
        def table(self, _name):
            nonlocal calls
            calls += 1
            raise failure

    with monkeypatch.context() as patch:
        patch.setattr(persistence, "_client", lambda: Client())
        main_path = Path(__file__).resolve().parents[1] / "main.py"
        spec = importlib.util.spec_from_file_location("main_import_probe", main_path)
        assert spec is not None and spec.loader is not None
        probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe)

    assert calls == 0


def test_store_construction_never_reads_remote_persistence(monkeypatch):
    calls = 0

    def unavailable():
        nonlocal calls
        calls += 1
        raise persistence.DurableConversationPersistenceUnavailable("temporary failure")

    with monkeypatch.context() as patch:
        patch.setattr(persistence, "load_state", unavailable)

        store = ConversationStore()

    assert calls == 0
    assert store.rehydration_state is ConversationStoreRehydrationState.UNINITIALIZED


def test_store_exposes_unavailable_persistence_without_replacing_durable_state(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(
            persistence,
            "load_state",
            lambda: (_ for _ in ()).throw(
                persistence.DurableConversationPersistenceUnavailable("temporary failure")
            ),
        )

        store = ConversationStore()
        assert store.rehydration_state is ConversationStoreRehydrationState.UNINITIALIZED
        assert store.reload() is ConversationStoreRehydrationState.TEMPORARILY_UNAVAILABLE

        assert store.rehydration_state is ConversationStoreRehydrationState.TEMPORARILY_UNAVAILABLE
        with pytest.raises(ConversationPersistenceUnavailable):
            store.list_conversations()
        with pytest.raises(ConversationPersistenceUnavailable):
            store.create_conversation(
                Conversation(owner_id="owner-1", metadata={"workspace_id": "workspace-1"})
            )


def test_store_keeps_corrupt_durable_state_fail_closed(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(
            persistence,
            "load_state",
            lambda: (None, persistence.json_file.JsonFileStatus.CORRUPT),
        )

        store = ConversationStore()
        with pytest.raises(RuntimeError, match="status=corrupt"):
            store.reload()


def test_malformed_durable_snapshot_is_classified_as_corrupt(monkeypatch):
    class Query:
        def select(self, *_args):
            return self

        def order(self, *_args):
            return self

        def range(self, *_args):
            return self

        def execute(self):
            return SimpleNamespace(data=[{"snapshot": "not-json", "owner_id": "owner-1"}])

    class Client:
        def table(self, name):
            assert name == "conversation_snapshots"
            return Query()

    with monkeypatch.context() as patch:
        patch.setattr(persistence, "_client", lambda: Client())
        data, status = persistence.load_state()

    assert data is None
    assert status is persistence.json_file.JsonFileStatus.CORRUPT


def test_store_rehydrates_valid_durable_state_unchanged(monkeypatch):
    conversation = Conversation(
        owner_id="owner-1",
        status=ConversationStatus.DELIVERED,
        subject="Durable subject",
        metadata={"workspace_id": "workspace-1"},
    )
    snapshot = {
        "sequence": 7,
        "conversations": [conversation.to_dict()],
        "threads": [],
        "messages": [],
        "timeline": {},
    }
    with monkeypatch.context() as patch:
        patch.setattr(
            persistence,
            "load_state",
            lambda: (snapshot, persistence.json_file.JsonFileStatus.OK),
        )

        store = ConversationStore()
        store.reload()

        restored = store.get_conversation(conversation.conversation_id)
        assert store.rehydration_state is ConversationStoreRehydrationState.LOADED
        assert restored is not None
        assert restored.subject == "Durable subject"
        assert restored.owner_id == "owner-1"


def test_paginated_durable_read_loads_every_snapshot(monkeypatch):
    rows = [
        {
            "snapshot": {
                "sequence": index,
                "conversations": [],
                "threads": [],
                "messages": [],
                "timeline": {},
            },
            "owner_id": "",
            "workspace_id": "workspace-1",
            "version": 1,
        }
        for index in range(persistence.LOAD_PAGE_SIZE + 1)
    ]
    ranges: list[tuple[int, int]] = []

    class Query:
        def select(self, *_args):
            return self

        def order(self, *_args):
            return self

        def range(self, start, end):
            ranges.append((start, end))
            self._range = (start, end + 1)
            return self

        def execute(self):
            return SimpleNamespace(data=rows[slice(*self._range)])

    class Client:
        def table(self, name):
            assert name == "conversation_snapshots"
            return Query()

    with monkeypatch.context() as patch:
        patch.setattr(persistence, "_client", lambda: Client())
        restored, status = persistence.load_state()

    assert status is persistence.json_file.JsonFileStatus.OK
    assert restored is not None
    assert restored["sequence"] == persistence.LOAD_PAGE_SIZE
    assert ranges == [(0, persistence.LOAD_PAGE_SIZE - 1), (persistence.LOAD_PAGE_SIZE, (2 * persistence.LOAD_PAGE_SIZE) - 1)]
