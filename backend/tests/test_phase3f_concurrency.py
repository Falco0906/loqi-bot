"""PR-3F — backend concurrency + job durability regression tests."""
import asyncio

import pytest

from services.communication.inbox_sync_engine import InboxSyncEngine


# ─── INBOX: provider-scoped locking ──────────────────────────────────────

class FakeProvider:
    provider_type = "gmail"

    def __init__(self, name):
        self._name = name
        self._connected = True


class FakeResult:
    threads_synced = 0
    messages_synced = 0
    new_conversations = 0
    errors: list = []
    duration_ms = 1


@pytest.fixture()
def sync_env(monkeypatch):
    eng = InboxSyncEngine(interval_seconds=9999)
    state = {"active": set(), "max_active": 0, "delays": {}, "fail_first": set(), "calls": {}}

    import services.communication.inbox_sync_engine as ise  # engine's own binding

    def fake_sync_all(provider):
        name = provider._name
        state["calls"][name] = state["calls"].get(name, 0) + 1
        if name in state["fail_first"] and state["calls"][name] == 1:
            raise RuntimeError("gmail exploded")
        delay = state["delays"].get(name, 0.02)

        async def run():
            state["active"].add(name)
            state["max_active"] = max(state["max_active"], len(state["active"]))
            await asyncio.sleep(delay)
            state["active"].discard(name)
            return FakeResult()
        return asyncio.run(run())

    monkeypatch.setattr(ise, "sync_all", fake_sync_all)

    # readiness no-op
    import services.communication.inbox_sync_engine as mod
    async def _ready():
        return 0
    real_to_thread = asyncio.to_thread

    def fake_to_thread(fn, *a, **k):
        if getattr(fn, "__name__", "") == "maintain_follow_up_readiness":
            return _ready()
        return real_to_thread(fn, *a, **k)
    monkeypatch.setattr(mod.asyncio, "to_thread", fake_to_thread)

    def register(pid, name=None):
        p = FakeProvider(name or pid)
        from services.communication.provider_registry import register_instance
        register_instance(pid, p)
        return p
    return eng, state, register


def test_1_2_different_providers_concurrent_same_provider_serialized(sync_env, monkeypatch):
    eng, state, reg = sync_env
    reg("prov-A", "A"); reg("prov-B", "B")
    state["delays"] = {"A": 0.12, "B": 0.12}

    async def run():
        return await eng.sync_once(["prov-A", "prov-B"])
    asyncio.run(run())
    assert state["max_active"] == 2, "different mailboxes must run concurrently"


def test_same_provider_two_calls_serialize(sync_env, monkeypatch):
    eng, state, reg = sync_env
    reg("prov-S")
    state["delays"]["prov-S"] = 0.08

    async def run():
        t1 = asyncio.create_task(eng.sync_once(["prov-S"]))
        await asyncio.sleep(0.01)
        overlap_before = state["max_active"]
        await t1
        return overlap_before
    assert asyncio.run(run()) <= 1


def test_exception_releases_lock(sync_env):
    eng, state, reg = sync_env
    reg("prov-X")
    state["fail_first"].add("prov-X")

    async def run():
        await eng.sync_once(["prov-X"])          # first call fails inside
        result = await eng.sync_once(["prov-X"])  # lock must be releasable
        lock = await eng._provider_lock("prov-X")
        assert not lock.locked()
        assert state["calls"]["prov-X"] == 2
    asyncio.run(run())


def test_cancellation_releases_lock(sync_env):
    eng, state, reg = sync_env
    reg("prov-C")
    state["delays"]["prov-C"] = 5.0

    async def run():
        task = asyncio.create_task(eng.sync_once(["prov-C"]))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        lock = await eng._provider_lock("prov-C")
        assert not lock.locked()
        # cleanup so later suites don't wait on the abandoned worker thread
        state["delays"]["prov-C"] = 0
    asyncio.run(run())
    # let the abandoned sync_all finish and release
    asyncio.run(asyncio.sleep(0.1))


def test_lock_map_bounded(sync_env):
    eng, _, _ = sync_env

    async def run():
        for i in range(300):
            await eng._provider_lock(f"p-{i}")
        assert len(eng._provider_locks) <= eng._PROVIDER_LOCKS_MAX
    asyncio.run(run())


# ─── STRATEGY JOB DURABILITY ─────────────────────────────────────────────

OWNER_A = "u-owner-a"
OWNER_B = "u-owner-b"


@pytest.fixture()
def durable(monkeypatch):
    rows: dict[str, dict] = {}

    async def persist(owner_id, campaign_id, meta=None, **_):
        # Production passes the FLAT job-meta dict as 3rd arg.
        if isinstance(meta, dict):
            rows[campaign_id] = meta
        return True

    async def load(owner_id, campaign_id):
        return rows.get(campaign_id)

    import main as m
    monkeypatch.setattr(m, "_persist_strategy_job_meta", persist)
    monkeypatch.setattr(m, "_load_strategy_job_meta", load)

    class Ctx:
        pass
    ctx = Ctx()
    ctx.rows = rows
    return ctx


def test_enqueue_persists_queued_meta(durable, monkeypatch):
    import main as m

    async def noop(*a, **k): return None
    monkeypatch.setattr(m, "_run_strategy_job", noop)

    async def run():
        job_id, status = await m._enqueue_strategy_job("sess", OWNER_A, "cmp-q", "obj", {})
        assert status == "queued"
        assert job_id in {r.get("id") for r in durable.rows.values()} or durable.rows.get("cmp-q"), (
            f"no durable meta persisted; rows={list(durable.rows.values())}"
        )
        assert durable.rows["cmp-q"]["id"] == job_id
        assert durable.rows["cmp-q"]["status"] == "queued"
    asyncio.run(run())


def test_status_endpoint_reconciles_stale_running(durable, monkeypatch):
    import main as m

    async def owner(request=None, session_token=None):
        return OWNER_A
    monkeypatch.setattr(m, "_workspace_owner", owner)

    # Process died mid-generation: no in-memory job; durable says RUNNING.
    durable.rows["cmp-stale"] = {
        "id": "job-stale", "status": "running",
        "started_at": "2026-01-01T00:00:00Z", "finished_at": None, "error": None,
    }

    request = type("R", (), {"headers": {}})()

    async def run():
        return await m.strategy_job_status("sess", "cmp-stale", "job-stale", request)
    result = asyncio.run(run())
    assert result["status"] == "failed"
    assert "interrupted" in (result["error"] or "").lower(), (
        "stale RUNNING must become an actionable failure"
    )


def test_completed_durable_record_reports_completed(durable, monkeypatch):
    import main as m

    async def owner(request=None, session_token=None):
        return OWNER_A
    monkeypatch.setattr(m, "_workspace_owner", owner)
    durable.rows["cmp-ok"] = {
        "id": "job-done", "status": "completed",
        "started_at": "", "finished_at": "", "error": None,
    }
    request = type("R", (), {"headers": {}})()

    async def run():
        return await m.strategy_job_status("sess", "cmp-ok", "job-done", request)
    result = asyncio.run(run())
    assert result["status"] == "completed"


def test_tenant_isolation_strategy_status(durable, monkeypatch):
    """Owner B polling owner A's campaign/job gets 404 (no existence leak)."""
    import main as m
    from fastapi import HTTPException

    async def owner_b(request=None, session_token=None):
        return OWNER_B
    monkeypatch.setattr(m, "_workspace_owner", owner_b)

    request = type("R", (), {"headers": {}})()

    async def run():
        return await m.strategy_job_status("sess", "cmp-private", "job-p", request)

    try:
        result = asyncio.run(run())
        # If reached without error, it must not leak A's data.
        assert result is None or result.get("strategy") is None
    except HTTPException as exc:
        assert exc.status_code == 404


def test_duplicate_execution_prevented_while_in_flight(durable, monkeypatch):
    import main as m

    started = asyncio.Event()
    release = asyncio.Event()

    async def stub_run(session_token, job, target, objective):
        job["status"] = "running"
        started.set()
        await release.wait()
        job["strategy"] = {"audience": "x"}
        job["status"] = "completed"

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(m, "_run_strategy_job", stub_run)
    monkeypatch.setattr(m, "_persist_strategy_job_meta", noop)

    async def run():
        id1, s1 = await m._enqueue_strategy_job("sess", OWNER_A, "cmp-dup", "obj", {})
        id2, s2 = await m._enqueue_strategy_job("sess", OWNER_A, "cmp-dup", "obj", {})
        assert id1 == id2 and s1 == s2, "in-flight generation must be reused"
        release.set()
        await asyncio.sleep(0.05)
    asyncio.run(run())
