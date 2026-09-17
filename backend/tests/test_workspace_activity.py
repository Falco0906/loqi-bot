"""Offline contracts for durable workspace activity and briefing cursors."""
from __future__ import annotations

from pathlib import Path

import pytest

from services.world_model.activity_repository import WorkspaceActivityRepository


class _Result:
    def __init__(self, data):
        self.data = data


class _ActivityQuery:
    def __init__(self, database, table):
        self.database = database
        self.table_name = table
        self.filters = []
        self.greater_than = None

    def select(self, *_args):
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def gt(self, key, value):
        self.greater_than = (key, value)
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, _value):
        return self

    def execute(self):
        rows = self.database.rows.setdefault(self.table_name, [])
        matched = [row for row in rows if all(row.get(key) == value for key, value in self.filters)]
        if self.greater_than is not None:
            key, value = self.greater_than
            matched = [row for row in matched if row.get(key, 0) > value]
        return _Result([dict(row) for row in sorted(matched, key=lambda row: row.get("sequence", 0))])


class _ActivityDatabase:
    def __init__(self):
        self.rows = {"workspace_activity_events": [], "workspace_briefing_cursors": []}
        self._sequences = {}

    def table(self, table_name):
        return _ActivityQuery(self, table_name)

    def rpc(self, name, arguments):
        database = self

        class _Rpc:
            def execute(self):
                if name == "append_workspace_activity_event":
                    workspace_id = arguments["p_workspace_id"]
                    source_key = arguments["p_source_key"]
                    existing = next((row for row in database.rows["workspace_activity_events"] if row["workspace_id"] == workspace_id and row["source_key"] == source_key), None)
                    if existing:
                        return _Result([{"event_id": existing["id"], "event_sequence": existing["sequence"], "occurred_at": existing["occurred_at"], "was_created": False}])
                    sequence = database._sequences.get(workspace_id, 0) + 1
                    database._sequences[workspace_id] = sequence
                    row = {
                        "id": f"event-{workspace_id}-{sequence}",
                        "workspace_id": workspace_id,
                        "actor_user_id": arguments["p_actor_user_id"],
                        "event_type": arguments["p_event_type"],
                        "payload": dict(arguments["p_payload"]),
                        "source_key": source_key,
                        "sequence": sequence,
                        "occurred_at": arguments["p_occurred_at"],
                    }
                    database.rows["workspace_activity_events"].append(row)
                    return _Result([{"event_id": row["id"], "event_sequence": sequence, "occurred_at": row["occurred_at"], "was_created": True}])
                assert name == "acknowledge_workspace_briefing"
                workspace_id = arguments["p_workspace_id"]
                user_id = arguments["p_user_id"]
                delivered = arguments["p_delivered_through_sequence"]
                rows = database.rows["workspace_briefing_cursors"]
                row = next((candidate for candidate in rows if candidate["workspace_id"] == workspace_id and candidate["user_id"] == user_id), None)
                if row is None:
                    row = {"workspace_id": workspace_id, "user_id": user_id, "last_viewed_sequence": delivered}
                    rows.append(row)
                else:
                    row["last_viewed_sequence"] = max(row["last_viewed_sequence"], delivered)
                return _Result([{"last_viewed_sequence": row["last_viewed_sequence"]}])

        return _Rpc()


def _repository(database=None):
    database = database or _ActivityDatabase()
    return WorkspaceActivityRepository(client_provider=lambda: database), database


def _payload(draft_id="draft-1", **extra):
    return {"draft_id": draft_id, "campaign_id": "campaign-1", "lead_id": "lead-1", "batch_job_id": "job-1", "status": "pending", **extra}


def test_activity_migration_has_scoped_sequence_event_and_cursor_contracts():
    sql = (Path(__file__).resolve().parents[1] / "supabase/migrations/039_workspace_activity.sql").read_text()
    for fragment in (
        "create table if not exists workspace_activity_sequences",
        "workspace_id uuid primary key references workspaces(id)",
        "create table if not exists workspace_activity_events",
        "actor_user_id uuid references identity_users(id)",
        "unique (workspace_id, source_key)",
        "unique (workspace_id, sequence)",
        "create table if not exists workspace_briefing_cursors",
        "primary key (workspace_id, user_id)",
        "create or replace function append_workspace_activity_event",
        "pg_advisory_xact_lock",
        "create or replace function acknowledge_workspace_briefing",
        "p_delivered_through_sequence",
    ):
        assert fragment in sql


def test_duplicate_source_key_is_idempotent_and_workspace_sequences_increase():
    repository, _database = _repository()
    first = repository.append_draft_generated(
        workspace_id="workspace-a", actor_user_id="user-a", source_key="draft_batch:job-1:item-1:generated", payload=_payload(), occurred_at="2026-01-01T00:00:00+00:00",
    )
    duplicate = repository.append_draft_generated(
        workspace_id="workspace-a", actor_user_id="user-a", source_key="draft_batch:job-1:item-1:generated", payload=_payload(), occurred_at="2026-01-01T00:00:00+00:00",
    )
    second = repository.append_draft_generated(
        workspace_id="workspace-a", actor_user_id="user-a", source_key="draft_batch:job-1:item-2:generated", payload=_payload("draft-2"), occurred_at="2026-01-01T00:00:01+00:00",
    )
    other_workspace = repository.append_draft_generated(
        workspace_id="workspace-b", actor_user_id="user-b", source_key="draft_batch:job-2:item-1:generated", payload=_payload("draft-3"), occurred_at="2026-01-01T00:00:02+00:00",
    )

    assert (first.id, first.sequence) == (duplicate.id, duplicate.sequence) == ("event-workspace-a-1", 1)
    assert second.sequence == 2
    assert other_workspace.sequence == 1
    assert [event.payload["draft_id"] for event in repository.read_events_after("workspace-a", 0)] == ["draft-1", "draft-2"]
    assert repository.read_events_after("workspace-b", 0)[0].payload["draft_id"] == "draft-3"


def test_cursor_is_user_and_workspace_scoped_and_only_advances_delivered_range():
    repository, _database = _repository()
    first = repository.append_draft_generated(
        workspace_id="workspace-a", actor_user_id="user-a", source_key="draft_batch:job:item:generated", payload=_payload(), occurred_at="2026-01-01T00:00:00+00:00",
    )
    second = repository.append_draft_generated(
        workspace_id="workspace-a", actor_user_id="user-a", source_key="draft_batch:job:item-2:generated", payload=_payload("draft-2"), occurred_at="2026-01-01T00:00:01+00:00",
    )
    assert repository.read_cursor("workspace-a", "user-a") == 0
    # The reader delivered only the first event; event two must remain for
    # the next summary rather than being acknowledged as "current" state.
    assert repository.acknowledge("workspace-a", "user-a", first.sequence) == 1
    assert [event.sequence for event in repository.read_events_after("workspace-a", 1)] == [second.sequence]
    assert repository.read_cursor("workspace-a", "user-b") == 0
    assert repository.read_cursor("workspace-b", "user-a") == 0
    assert repository.acknowledge("workspace-a", "user-a", 0) == 1


def test_activity_payload_rejects_sensitive_or_unsupported_values():
    repository, _database = _repository()
    with pytest.raises(ValueError, match="unsupported"):
        repository.append_draft_generated(
            workspace_id="workspace-a", actor_user_id="user-a", source_key="key", payload=_payload(subject="secret"),
        )
    with pytest.raises(ValueError, match="requires"):
        repository.append_draft_generated(
            workspace_id="workspace-a", actor_user_id="user-a", source_key="key", payload={"draft_id": "draft-1"},
        )


def test_repository_recreation_reads_same_durable_events_after_restart():
    repository, database = _repository()
    repository.append_draft_generated(
        workspace_id="workspace-a", actor_user_id="user-a", source_key="draft_batch:job:item:generated", payload=_payload(), occurred_at="2026-01-01T00:00:00+00:00",
    )
    restarted = WorkspaceActivityRepository(client_provider=lambda: database)
    assert [(event.sequence, event.payload) for event in restarted.read_events_after("workspace-a", 0)] == [(1, _payload())]
