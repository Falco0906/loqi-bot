from types import SimpleNamespace

from services.job_engine.models import BatchItem
from services.job_engine.storage import JobStorage


class MemoryTable:
    def __init__(self, rows): self.rows, self.mode, self.filters, self.data = rows, "select", [], None
    def select(self, *_): self.mode = "select"; return self
    def eq(self, key, value): self.filters.append((key, value)); return self
    def in_(self, key, values): self.filters.append((key, set(values))); return self
    def limit(self, *_): return self
    def order(self, *_args, **_kwargs): return self
    def upsert(self, rows, **_): self.mode, self.data = "upsert", rows; return self
    def update(self, data): self.mode, self.data = "update", data; return self
    def execute(self):
        matches = [row for row in self.rows if all(row.get(k) in v if isinstance(v, set) else row.get(k) == v for k, v in self.filters)]
        if self.mode == "upsert":
            for row in self.data:
                if not any(existing["job_id"] == row["job_id"] and existing["idempotency_key"] == row["idempotency_key"] for existing in self.rows): self.rows.append(dict(row))
            return SimpleNamespace(data=self.data)
        if self.mode == "update":
            for row in matches: row.update(self.data)
        return SimpleNamespace(data=matches)


class MemoryClient:
    def __init__(self): self.rows = []
    def table(self, _): return MemoryTable(self.rows)


def test_batch_item_completion_is_idempotent_and_resume_skips_completed(monkeypatch):
    import services.job_engine.storage as storage_module
    client = MemoryClient()
    monkeypatch.setattr(storage_module, "get_supabase_client", lambda: client)
    storage = JobStorage()
    first = BatchItem(job_id="job", workspace_id="ws", campaign_id="campaign", position=0, lead_snapshot={"id": "lead-1"}, idempotency_key="lead-1")
    second = BatchItem(job_id="job", workspace_id="ws", campaign_id="campaign", position=1, lead_snapshot={"id": "lead-2"}, idempotency_key="lead-2")
    assert storage.create_batch_items([first, second])
    assert storage.create_batch_items([first])
    assert len(client.rows) == 2
    assert storage.mark_batch_item_completed("job", "lead-1", "draft-1")
    assert storage.mark_batch_item_completed("job", "lead-1", "draft-1")
    assert not storage.mark_batch_item_completed("job", "lead-1", "draft-other")
    remaining = storage.list_batch_resume_items("job", "ws")
    assert [item.idempotency_key for item in remaining] == ["lead-2"]
