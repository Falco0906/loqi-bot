"""Production Inbox persistence uses Supabase snapshots, never local files."""

from types import SimpleNamespace

from services.conversations import persistence


def test_conversation_snapshot_round_trip_uses_durable_table(monkeypatch):
    rows: list[dict] = []

    class Query:
        def __init__(self): self.params = {}
        def upsert(self, row, **_kwargs):
            rows[:] = [item for item in rows if item["conversation_id"] != row["conversation_id"]]
            rows.append(row)
            return self
        def select(self, *_args): return self
        def execute(self): return SimpleNamespace(data=list(rows))

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
