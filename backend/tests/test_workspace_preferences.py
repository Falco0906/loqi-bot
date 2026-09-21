"""Offline contracts for durable, workspace-scoped learned preferences."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from types import SimpleNamespace

import pytest

from services.learning.learner import Learner
from services.learning.models import LearnedPreference, PreferenceKey
from services.learning.preference_store import PreferenceStore, WorkspacePreferenceRepository


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, database, table):
        self.database = database
        self.table_name = table
        self.filters: list[tuple[str, object]] = []
        self.action = "select"
        self.payload = None

    def select(self, *_args):
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def limit(self, _value):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def insert(self, payload):
        self.action = "insert"
        self.payload = dict(payload)
        return self

    def update(self, payload):
        self.action = "update"
        self.payload = dict(payload)
        return self

    def execute(self):
        rows = self.database.rows.setdefault(self.table_name, [])
        matching = [row for row in rows if all(row.get(key) == value for key, value in self.filters)]
        if self.action == "select":
            return _Result([dict(row) for row in matching])
        if self.action == "insert":
            row = {"id": f"preference-{len(rows) + 1}", **self.payload}
            rows.append(row)
            return _Result([dict(row)])
        assert len(matching) == 1
        matching[0].update(self.payload)
        return _Result([dict(matching[0])])


class _FakePreferenceDatabase:
    def __init__(self):
        self.rows: dict[str, list[dict]] = {}
        self.rpc_calls: list[tuple[str, dict]] = []
        self.table_calls: list[str] = []
        self._lock = Lock()
        self.fail_after_commit_once = False

    def table(self, table_name):
        self.table_calls.append(table_name)
        return _Query(self, table_name)

    def rpc(self, name, arguments):
        database = self

        class _Rpc:
            def execute(self):
                assert name == "upsert_workspace_preference_if_higher"
                database.rpc_calls.append((name, dict(arguments)))
                with database._lock:
                    rows = database.rows.setdefault("workspace_preferences", [])
                    existing = next((row for row in rows if row["workspace_id"] == arguments["p_workspace_id"] and row["preference_key"] == arguments["p_preference_key"]), None)
                    if existing is None:
                        row = {
                            "id": f"preference-{len(rows) + 1}",
                            "workspace_id": arguments["p_workspace_id"],
                            "preference_key": arguments["p_preference_key"],
                            "preference_value": arguments["p_preference_value"],
                            "confidence": arguments["p_confidence"],
                            "source": arguments["p_source"],
                            "evidence_count": arguments["p_evidence_count"],
                            "first_observed_at": arguments["p_first_observed_at"],
                            "last_observed_at": arguments["p_last_observed_at"],
                            "version": 1,
                            "updated_by": arguments["p_actor_user_id"],
                            "updated_at": arguments["p_last_observed_at"],
                        }
                        rows.append(row)
                        was_updated = True
                    elif float(existing["confidence"]) >= float(arguments["p_confidence"]):
                        row = existing
                        was_updated = False
                    else:
                        existing.update({
                            "preference_value": arguments["p_preference_value"],
                            "confidence": arguments["p_confidence"],
                            "source": arguments["p_source"],
                            "evidence_count": arguments["p_evidence_count"],
                            "last_observed_at": arguments["p_last_observed_at"],
                            "version": existing["version"] + 1,
                            "updated_by": arguments["p_actor_user_id"],
                            "updated_at": arguments["p_last_observed_at"],
                        })
                        row = existing
                        was_updated = True
                    result = {**row, "was_updated": was_updated}
                    should_timeout = database.fail_after_commit_once
                    database.fail_after_commit_once = False
                if should_timeout:
                    raise TimeoutError("response lost after commit")
                return _Result([result])

        return _Rpc()


def _repository(database=None):
    database = database or _FakePreferenceDatabase()
    return WorkspacePreferenceRepository(client_provider=lambda: database), database


def _preference(
    *, value="professional", confidence=0.6, evidence_count=5,
    first_observed="2026-01-01T00:00:00+00:00", last_observed="2026-01-02T00:00:00+00:00",
):
    return LearnedPreference(
        key=PreferenceKey.EMAIL_TONE.value,
        value=value,
        confidence=confidence,
        source="preference_learner",
        evidence_count=evidence_count,
        first_observed=first_observed,
        last_observed=last_observed,
    )


def test_workspace_preferences_migration_has_canonical_scope_and_no_session_columns():
    sql = (Path(__file__).resolve().parents[1] / "supabase/migrations/038_workspace_preferences.sql").read_text()

    for field in (
        "workspace_id uuid not null references workspaces(id)",
        "preference_key text not null",
        "preference_value text not null",
        "confidence numeric not null",
        "evidence_count integer not null",
        "version bigint not null",
        "updated_by uuid references identity_users(id)",
        "unique (workspace_id, preference_key)",
    ):
        assert field in sql
    for forbidden in ("session_token", "bearer", "email", "provider_payload", "message_body"):
        assert forbidden not in sql


def test_preference_upsert_migration_uses_locked_rpc_and_existing_column_types():
    sql = (Path(__file__).resolve().parents[1] / "supabase/migrations/040_workspace_preference_upsert.sql").read_text()
    for fragment in (
        "create or replace function upsert_workspace_preference_if_higher",
        "p_preference_value text",
        "for update",
        "on conflict (workspace_id, preference_key) do nothing",
        "v_current.confidence >= p_confidence",
        "version = v_current.version + 1",
        "was_updated boolean",
    ):
        assert fragment in sql


def test_preference_upsert_ambiguity_fix_qualifies_all_conflicting_table_references():
    sql = (Path(__file__).resolve().parents[1] / "supabase/migrations/043_fix_workspace_preference_upsert_ambiguity.sql").read_text()

    for fragment in (
        "create or replace function upsert_workspace_preference_if_higher",
        "from workspace_preferences as wp",
        "where wp.workspace_id = p_workspace_id",
        "and wp.preference_key = p_preference_key",
        "update workspace_preferences as wp",
        "where wp.id = v_current.id",
        "returning wp.* into v_current",
        "on conflict on constraint workspace_preferences_scope_key_uidx do nothing",
    ):
        assert fragment in sql

    # ``workspace_id``, ``preference_key``, and ``id`` are all RETURN TABLE
    # variables.  They must not be used as unqualified table references.
    assert "on conflict (workspace_id, preference_key)" not in sql
    assert "where id = v_current.id" not in sql


def test_preference_survives_restart_from_durable_workspace_repository():
    repository, database = _repository()
    first = PreferenceStore(
        "session-token-must-not-persist",
        workspace_id="workspace-a",
        actor_user_id="user-a",
        repository=repository,
    )
    preference_id = first.save(_preference())

    restarted = PreferenceStore(
        "different-session-token",
        workspace_id="workspace-a",
        actor_user_id="user-a",
        repository=WorkspacePreferenceRepository(client_provider=lambda: database),
    )

    assert restarted.get(PreferenceKey.EMAIL_TONE) == "professional"
    assert restarted.get_all()[0]["id"] == preference_id
    persisted = database.rows["workspace_preferences"][0]
    assert set(persisted) == {
        "id", "workspace_id", "preference_key", "preference_value", "confidence", "source",
        "evidence_count", "first_observed_at", "last_observed_at", "version", "updated_by", "updated_at",
    }
    assert "session-token-must-not-persist" not in str(persisted)


def test_preference_workspace_isolation_and_higher_confidence_wins():
    repository, _database = _repository()
    workspace_a = PreferenceStore(workspace_id="workspace-a", actor_user_id="user-a", repository=repository)
    workspace_b = PreferenceStore(workspace_id="workspace-b", actor_user_id="user-b", repository=repository)
    preference_id = workspace_a.save(_preference(confidence=0.8, evidence_count=9))

    assert workspace_b.get(PreferenceKey.EMAIL_TONE) is None
    assert workspace_b.get_all() == []
    assert workspace_a.save(_preference(value="casual", confidence=0.5, evidence_count=5)) == preference_id
    assert workspace_a.get(PreferenceKey.EMAIL_TONE) == "professional"
    assert workspace_b.get(PreferenceKey.EMAIL_TONE) is None


def test_concurrent_first_insert_resolves_to_one_canonical_row():
    repository, database = _repository()

    def write(actor):
        return repository.save_if_higher(
            workspace_id="workspace-a", actor_user_id=actor,
            preference=_preference(confidence=0.7),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(write, ["user-a", "user-b"]))

    assert len(database.rows["workspace_preferences"]) == 1
    assert first["id"] == second["id"]
    assert database.rows["workspace_preferences"][0]["version"] == 1


@pytest.mark.parametrize(
    ("first_confidence", "second_confidence", "expected_confidence", "expected_version"),
    [
        (0.6, 0.8, 0.8, 2),
        (0.8, 0.6, 0.8, 1),
    ],
)
def test_competing_confidence_writes_preserve_highest_canonical_value(
    first_confidence, second_confidence, expected_confidence, expected_version,
):
    repository, _database = _repository()
    first = _preference(value="professional", confidence=first_confidence, evidence_count=5)
    second = _preference(value="casual", confidence=second_confidence, evidence_count=11)

    repository.save_if_higher(workspace_id="workspace-a", actor_user_id="user-a", preference=first)
    result = repository.save_if_higher(workspace_id="workspace-a", actor_user_id="user-b", preference=second)

    assert result["confidence"] == expected_confidence
    assert result["version"] == expected_version
    assert result["value"] == ("casual" if second_confidence > first_confidence else "professional")


def test_equal_confidence_preserves_first_durable_winner_without_version_or_evidence_change():
    repository, _database = _repository()
    first = repository.save_if_higher(
        workspace_id="workspace-a", actor_user_id="user-a", preference=_preference(value="professional", confidence=0.7, evidence_count=5),
    )
    second = repository.save_if_higher(
        workspace_id="workspace-a", actor_user_id="user-b", preference=_preference(value="casual", confidence=0.7, evidence_count=12),
    )

    assert first["was_updated"] is True
    assert second["was_updated"] is False
    assert second["value"] == "professional"
    assert second["evidence_count"] == 5
    assert second["version"] == 1


def test_committed_write_timeout_retry_does_not_increment_version_or_evidence():
    repository, database = _repository()
    database.fail_after_commit_once = True
    preference = _preference(confidence=0.7, evidence_count=9)

    with pytest.raises(TimeoutError):
        repository.save_if_higher(workspace_id="workspace-a", actor_user_id="user-a", preference=preference)
    retry = repository.save_if_higher(workspace_id="workspace-a", actor_user_id="user-a", preference=preference)

    assert retry["was_updated"] is False
    assert retry["version"] == 1
    assert retry["evidence_count"] == 9


def test_higher_confidence_replaces_aggregate_evidence_and_preserves_first_observed():
    repository, _database = _repository()
    repository.save_if_higher(
        workspace_id="workspace-a", actor_user_id="user-a", preference=_preference(confidence=0.6, evidence_count=5),
    )
    updated = repository.save_if_higher(
        workspace_id="workspace-a", actor_user_id="user-b", preference=_preference(
            value="casual", confidence=0.85, evidence_count=11,
            first_observed="2026-02-01T00:00:00+00:00",
            last_observed="2026-02-03T00:00:00+00:00",
        ),
    )

    assert updated["evidence_count"] == 11
    assert updated["version"] == 2
    assert updated["first_observed_at"] == "2026-01-01T00:00:00+00:00"
    assert updated["last_observed_at"] == "2026-02-03T00:00:00+00:00"
    assert updated["source"] == "preference_learner"
    assert updated["updated_by"] == "user-b"


def test_rpc_receives_only_canonical_typed_preference_inputs():
    repository, database = _repository()
    repository.save_if_higher(
        workspace_id="workspace-a", actor_user_id="user-a", preference=_preference(),
    )
    name, arguments = database.rpc_calls[0]
    assert name == "upsert_workspace_preference_if_higher"
    assert len(database.rpc_calls) == 1
    assert database.table_calls == []
    assert set(arguments) == {
        "p_workspace_id", "p_actor_user_id", "p_preference_key",
        "p_preference_value", "p_confidence", "p_source",
        "p_evidence_count", "p_first_observed_at", "p_last_observed_at",
    }
    # `preferred_email_tone` is itself a valid typed key; reject only
    # transport/analytical fields, not that vocabulary within a typed key.
    for forbidden in (
        "session_token", "bearer_token", "message_body", "conversation_id",
        "provider_payload", "credential", "email_address",
    ):
        assert forbidden not in arguments


def test_preference_updates_evidence_version_and_timestamps_from_durable_state():
    repository, _database = _repository()
    store = PreferenceStore(workspace_id="workspace-a", actor_user_id="user-a", repository=repository)
    store.save(_preference(confidence=0.6, evidence_count=5))
    store.save(_preference(
        value="casual",
        confidence=0.84,
        evidence_count=11,
        first_observed="2026-02-01T00:00:00+00:00",
        last_observed="2026-02-03T00:00:00+00:00",
    ))

    row = store.get_all()[0]
    assert row["value"] == "casual"
    assert row["confidence"] == 0.84
    assert row["evidence_count"] == 11
    assert row["version"] == 2
    assert row["first_observed_at"] == "2026-01-01T00:00:00+00:00"
    assert row["last_observed_at"] == "2026-02-03T00:00:00+00:00"


def test_learner_passes_d1_b0_workspace_and_actor_scope_to_preference_store(monkeypatch):
    import services.learning.learner as learner_module

    seen = {}
    preference = _preference()

    class CapturingStore:
        def __init__(self, session_id, *, workspace_id, actor_user_id):
            seen.update(session_id=session_id, workspace_id=workspace_id, actor_user_id=actor_user_id)

        def get(self, _key):
            return None

        def get_all(self):
            return []

        def save(self, _preference):
            return "durable-preference-id"

    monkeypatch.setattr(learner_module, "PreferenceStore", CapturingStore)
    learner = Learner()
    learner.preference_learner = SimpleNamespace(evaluate=lambda _session_id: [preference])
    learner.pattern_detector = SimpleNamespace(detect=lambda _session_id: [])

    assert learner.run("legacy-session", workspace_id="workspace-a", actor_user_id="user-a") == ["durable-preference-id"]
    assert seen == {
        "session_id": "legacy-session",
        "workspace_id": "workspace-a",
        "actor_user_id": "user-a",
    }
    assert learner.run("legacy-session") == []


def test_communication_analytical_payload_does_not_call_durable_preference_repository(monkeypatch):
    import services.communication.service as communication_service

    message = SimpleNamespace(id="message-id", text="Interested in a demo")
    memory = SimpleNamespace(model_dump=lambda: {"conversation_id": "message-id"})
    intent = SimpleNamespace(value="demo_request")
    signal = SimpleNamespace(signal=SimpleNamespace(value="buying_intent"))
    stage = SimpleNamespace(value="engaged")
    recommendation = SimpleNamespace(action=SimpleNamespace(value="follow_up"))
    monkeypatch.setattr(communication_service, "ConversationMessage", lambda **_kwargs: message)
    monkeypatch.setattr(communication_service, "detect_intents", lambda _text: [intent])
    monkeypatch.setattr(communication_service, "detect_signals", lambda _text: [signal])
    monkeypatch.setattr(communication_service, "classify_stage", lambda *_args: (stage, "reason"))
    monkeypatch.setattr(communication_service, "recommend_followup", lambda *_args: recommendation)
    monkeypatch.setattr(communication_service, "build_legacy_memory", lambda **_kwargs: memory)
    monkeypatch.setattr(communication_service, "publish", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        WorkspacePreferenceRepository,
        "save_if_higher",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("analytical payload persisted")),
    )

    assert communication_service.update_communication_memory(
        session_token="legacy-session",
        text="Interested in a demo",
        conversation_id="",
        sender="lead@example.test",
        subject="Demo",
    )["ok"] is True
