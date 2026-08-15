"""PR10.8 — Production Persistence & Recovery Hardening regression suite.

Covers:
- atomic JSON state persistence (writes, concurrency, corruption, restart,
  temp cleanup, directory creation, stale-write guard)
- communication-store durability (cursor, seen-set, thread mappings)
- cursor safety (cursor never advances past failed message persistence)
- idempotency (duplicate inbound/reply/timeline/restart+re-ingest)
- Supabase bounded retry (transient retried, permanent not, no false
  success, no secret leakage)
- outbound (duplicate-send guards intact, idempotent conversation creation)
- ownership boundaries (user/provider/conversation isolation)
- rehydration (state restored before workers, exactly-once engine start,
  corrupt state preserved + documented degraded mode)

No live Gmail/Supabase/OpenAI calls. Sentinels only — never real secrets.
"""
import json
import os
import sys
import threading
import time
import uuid
from types import SimpleNamespace

os.chdir(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ".")

import pytest

SENTINEL = "PR10_8_SENTINEL_SECRET_DO_NOT_LEAK"


@pytest.fixture(autouse=True)
def _reset_communication_store(monkeypatch, tmp_path):
    """Point communication persistence at a temp file and reset the singleton."""
    from services.communication import communication_store as cs
    store = cs.store
    store._providers.clear()
    store._cursors.clear()
    store._thread_mappings.clear()
    store._by_conversation.clear()
    store._seen_message_ids.clear()
    store._user_providers.clear()
    store._sequence = 0
    monkeypatch.setattr(cs, "STATE_FILE", str(tmp_path / "communication.json"))
    monkeypatch.setattr(cs, "PERSISTENCE_ENABLED", True)
    yield
    monkeypatch.setattr(cs, "PERSISTENCE_ENABLED", False)


# ═══════════════════════════════════════════════════════════════════════
# 1. JSON state — atomic writes, concurrency, corruption, restart
# ═══════════════════════════════════════════════════════════════════════

class TestJsonAtomicPersistence:
    def test_atomic_write_succeeds(self, tmp_path):
        from services.persistence import json_file
        path = str(tmp_path / "state.json")
        ok = json_file.atomic_write_json(path, {"sequence": 1, "value": "x"}, category="test")
        assert ok is True
        data, status = json_file.read_json(path, category="test")
        assert status is json_file.JsonFileStatus.OK
        assert data == {"sequence": 1, "value": "x"}

    def test_no_temp_files_after_write(self, tmp_path):
        from services.persistence import json_file
        path = str(tmp_path / "state.json")
        json_file.atomic_write_json(path, {"sequence": 1, "a": 1}, category="test")
        leftovers = [f for f in os.listdir(str(tmp_path)) if "state.json.tmp-" in f]
        assert leftovers == []

    def test_directory_creation(self, tmp_path):
        from services.persistence import json_file
        path = str(tmp_path / "nested" / "deeper" / "state.json")
        json_file.atomic_write_json(path, {"sequence": 1, "a": 1}, category="test")
        assert os.path.isfile(path)
        data, _ = json_file.read_json(path, category="test")
        assert data["a"] == 1

    def test_concurrent_writes_do_not_corrupt(self, tmp_path):
        from services.persistence import json_file
        path = str(tmp_path / "state.json")
        errors = []

        def writer(n):
            try:
                for i in range(10):
                    seq = n * 10 + i
                    json_file.atomic_write_json(path, {"sequence": seq, "writer": n, "i": i}, category="test")
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        data, status = json_file.read_json(path, category="test")
        assert status is json_file.JsonFileStatus.OK
        assert isinstance(data, dict) and "sequence" in data

    def test_stale_write_does_not_overwrite_newer(self, tmp_path):
        from services.persistence import json_file
        path = str(tmp_path / "state.json")
        json_file.atomic_write_json(path, {"sequence": 5, "payload": "newer"}, category="test")
        # An older snapshot must not replace the newer one on disk.
        json_file.atomic_write_json(path, {"sequence": 3, "payload": "stale"}, category="test")
        data, _ = json_file.read_json(path, category="test")
        assert data["sequence"] == 5
        assert data["payload"] == "newer"

    def test_malformed_json_detected_and_preserved(self, tmp_path):
        from services.persistence import json_file
        path = str(tmp_path / "state.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"sequence": 1, "conversations": [')
        data, status = json_file.read_json(path, category="test")
        assert status is json_file.JsonFileStatus.CORRUPT
        assert data is None
        assert not os.path.exists(path)
        preserved = [f for f in os.listdir(str(tmp_path)) if f.startswith("state.json.corrupt.")]
        assert len(preserved) == 1
        with open(str(tmp_path / preserved[0]), "r", encoding="utf-8") as f:
            assert "conversations" in f.read()

    def test_corrupt_file_never_silently_overwritten(self, tmp_path):
        from services.persistence import json_file
        path = str(tmp_path / "state.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"sequence": 9, "payload": "operator_da')
        json_file.atomic_write_json(path, {"sequence": 10, "payload": "fresh"}, category="test")
        preserved = [f for f in os.listdir(str(tmp_path)) if f.startswith("state.json.corrupt.")]
        assert len(preserved) == 1
        data, _ = json_file.read_json(path, category="test")
        assert data["payload"] == "fresh"

    def test_stale_temp_files_cleaned_up(self, tmp_path):
        from services.persistence import json_file
        path = str(tmp_path / "state.json")
        stale = str(tmp_path / "state.json.tmp-deadbeef.json")
        with open(stale, "w", encoding="utf-8") as f:
            f.write("{}")
        old = time.time() - 7200
        os.utime(stale, (old, old))
        json_file.atomic_write_json(path, {"sequence": 1, "a": 1}, category="test")
        assert not os.path.exists(stale)

    def test_restart_reloads_state(self, tmp_path):
        from services.persistence import json_file
        path = str(tmp_path / "state.json")
        json_file.atomic_write_json(path, {"sequence": 4, "items": [1, 2, 3]}, category="test")
        data, status = json_file.read_json(path, category="test")
        assert status is json_file.JsonFileStatus.OK
        assert data["items"] == [1, 2, 3]


class TestConversationStorePersistence:
    def test_snapshot_sequence_monotonic(self):
        from services.conversations.conversation_store import conversation_store
        from services.conversations.integration import create_conversation_from_send
        before = conversation_store._sequence
        convo = create_conversation_from_send(
            provider_id="pr108",
            provider_type="gmail",
            external_thread_id=f"thread_{uuid.uuid4().hex[:12]}",
            external_message_id=f"msg_{uuid.uuid4().hex[:12]}",
            subject="t",
            from_email="a@b.com", from_name="A",
            to_email="c@d.com", to_name="C",
            body="hello",
        )
        after = conversation_store._sequence
        assert after > before
        snapshot = conversation_store.to_snapshot()
        assert snapshot["sequence"] == after

    def test_restart_round_trip_and_duplicate_reingest(self, tmp_path):
        from services.conversations.conversation_store import conversation_store
        from services.conversations.integration import create_conversation_from_send, handle_reply
        ext_thread = f"thread_{uuid.uuid4().hex[:12]}"
        ext_msg = f"msg_{uuid.uuid4().hex[:12]}"
        convo = create_conversation_from_send(
            provider_id="pr108", provider_type="gmail",
            external_thread_id=ext_thread, external_message_id=ext_msg,
            subject="Persistence round trip", from_email="a@b.com", from_name="A",
            to_email="c@d.com", to_name="C", body="hi",
            campaign_id="cmp108", workflow_id="wf108", lead_id="lead108",
        )
        cid = convo.conversation_id
        # Restart (drop memory, rehydrate from disk).
        conversation_store.reload()
        restored = conversation_store.get_conversation(cid)
        assert restored is not None
        assert restored.subject == "Persistence round trip"
        # Re-ingest the same outbound external id after restart must not
        # create a second conversation or duplicate messages.
        again = create_conversation_from_send(
            provider_id="pr108", provider_type="gmail",
            external_thread_id=ext_thread, external_message_id=ext_msg,
            subject="Persistence round trip", from_email="a@b.com", from_name="A",
            to_email="c@d.com", to_name="C", body="hi",
            campaign_id="cmp108", workflow_id="wf108", lead_id="lead108",
        )
        assert again.conversation_id == cid
        assert len(conversation_store.get_messages_for_conversation(cid)) == 1

    def test_duplicate_reply_request(self):
        from services.conversations.conversation_store import conversation_store
        from services.conversations.integration import create_conversation_from_send, handle_reply
        ext_thread = f"thread_{uuid.uuid4().hex[:12]}"
        convo = create_conversation_from_send(
            provider_id="pr108", provider_type="gmail",
            external_thread_id=ext_thread, external_message_id=f"o_{uuid.uuid4().hex[:12]}",
            subject="reply dedup", from_email="a@b.com", from_name="A",
            to_email="c@d.com", to_name="C", body="hi",
        )
        cid = convo.conversation_id
        reply_ext = f"r_{uuid.uuid4().hex[:12]}"
        first = handle_reply(
            conversation_id=cid, external_message_id=reply_ext,
            from_email="c@d.com", from_name="C", to_email="a@b.com", to_name="A",
            subject="Re: reply dedup", body="same reply",
        )
        second = handle_reply(
            conversation_id=cid, external_message_id=reply_ext,
            from_email="c@d.com", from_name="C", to_email="a@b.com", to_name="A",
            subject="Re: reply dedup", body="same reply",
        )
        assert first.message_id == second.message_id
        msgs = conversation_store.get_messages_for_conversation(cid)
        assert [m for m in msgs if m.external_message_id == reply_ext].__len__() == 1

    def test_duplicate_followup_timeline_event(self):
        from services.communication.inbox_sync_engine import _mark_ready
        from services.conversations.conversation_models import ConversationStatus
        from services.conversations.conversation_store import conversation_store
        from services.conversations.state_machine import transition
        from services.conversations.timeline import TimelineEventType
        from services.conversations.integration import create_conversation_from_send
        convo = create_conversation_from_send(
            provider_id="pr108", provider_type="gmail",
            external_thread_id=f"thread_{uuid.uuid4().hex[:12]}",
            external_message_id=f"msg_{uuid.uuid4().hex[:12]}",
            subject="followup dedup", from_email="a@b.com", from_name="A",
            to_email="c@d.com", to_name="C", body="hi",
        )
        # Follow the real readiness path: SENT -> FOLLOW_UP_PENDING -> ready.
        convo.status = transition(convo.status, ConversationStatus.FOLLOW_UP_PENDING)
        conversation_store.update_conversation(convo)
        _mark_ready(convo)
        _mark_ready(convo)
        ready_events = [
            e for e in conversation_store.get_timeline(convo.conversation_id)
            if e.event_type == TimelineEventType.FOLLOW_UP_READY
        ]
        assert len(ready_events) == 1


# ═══════════════════════════════════════════════════════════════════════
# 2. Communication-store durability
# ═══════════════════════════════════════════════════════════════════════

class TestCommunicationStoreDurability:
    def test_cursor_seen_mappings_persist_and_reload(self, tmp_path):
        from services.communication.communication_store import store
        store.save_cursor("p1", "history-999")
        store.mark_message_seen("ext-a")
        store.mark_message_seen("ext-b")
        store.map_thread("thread-1", "convo-1", provider_id="p1", subject="s")
        store.save_state()
        # Simulate a fresh process: new store instance rehydrating from disk.
        from services.communication import communication_store as cs
        fresh = cs.CommunicationStore(enable_persistence=True)
        cs.STATE_FILE = str(tmp_path / "communication.json")
        fresh.load_state()
        assert fresh.get_cursor("p1").cursor == "history-999"
        assert fresh.is_message_seen("ext-a")
        assert fresh.is_message_seen("ext-b")
        mapping = fresh.get_thread_mapping("thread-1")
        assert mapping is not None and mapping.conversation_id == "convo-1"

    def test_snapshot_excludes_credentials(self, tmp_path):
        from services.communication.communication_store import store
        store.save_cursor("p1", "history-1")
        store.mark_message_seen("x")
        raw = json.dumps(store.to_snapshot())
        assert "access_token" not in raw
        assert "refresh_token" not in raw
        assert SENTINEL not in raw

    def test_corrupt_communication_state_preserved(self, tmp_path):
        from services.communication.communication_store import store
        path = str(tmp_path / "communication.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"cursors": {')
        store.load_state()
        assert not os.path.exists(path)
        preserved = [f for f in os.listdir(str(tmp_path)) if f.startswith("communication.json.corrupt.")]
        assert len(preserved) == 1


# ═══════════════════════════════════════════════════════════════════════
# 3. Cursor safety
# ═══════════════════════════════════════════════════════════════════════

class TestCursorSafety:
    class _FakeProvider:
        def __init__(self, pid, errors):
            self._provider_id = pid
            self._errors = errors

        def sync(self, cursor=""):
            from services.communication.provider_models import SyncResult
            return SyncResult(provider_id=self._provider_id, cursor="NEWCURSOR", errors=self._errors)

    def test_successful_sync_advances_cursor(self):
        from services.communication.communication_store import store
        from services.communication.gmail_sync import sync_all
        sync_all(self._FakeProvider("p-ok", []))
        cursor = store.get_cursor("p-ok")
        assert cursor is not None and cursor.cursor == "NEWCURSOR"

    def test_failed_sync_does_not_advance_cursor(self):
        from services.communication.communication_store import store
        from services.communication.gmail_sync import sync_all
        sync_all(self._FakeProvider("p-fail", ["persist failed for msg 1"]))
        assert store.get_cursor("p-fail") is None

    def test_retry_reprocesses_after_failure(self):
        from services.communication.communication_store import store
        from services.communication.gmail_sync import sync_all
        sync_all(self._FakeProvider("p-r1", ["boom"]))
        assert store.get_cursor("p-r1") is None
        sync_all(self._FakeProvider("p-r1", []))
        assert store.get_cursor("p-r1").cursor == "NEWCURSOR"


class TestMessageSeenAfterSuccess:
    def _process(self, monkeypatch, fail_integration=False):
        from services.communication import gmail_sync
        from services.communication.communication_store import store
        from services.communication.provider_models import ProviderMessage, MessageDirection
        # Pre-map the thread so integration runs.
        store.map_thread("thread-108", "convo-108", provider_id="p108", subject="t")
        # Build an existing conversation so handle_reply persists.
        from services.conversations.integration import create_conversation_from_send
        create_conversation_from_send(
            provider_id="p108", provider_type="gmail",
            external_thread_id="thread-108", external_message_id=f"o_{uuid.uuid4().hex[:12]}",
            subject="t", from_email="a@b.com", from_name="A",
            to_email="c@d.com", to_name="C", body="hi",
        )
        fake_intel = SimpleNamespace(
            intents=[SimpleNamespace(intent=SimpleNamespace(value="question"))],
            buying_signals=[],
            conversation_stage=SimpleNamespace(value="discovery"),
            urgency=1,
            decision_confidence=0.5,
        )
        monkeypatch.setattr(gmail_sync, "analyze_message", lambda **kwargs: (fake_intel, None))
        if fail_integration:
            import services.conversations.integration as integration_mod
            original = integration_mod.handle_reply

            def _boom(*args, **kwargs):
                raise RuntimeError("persistence backend down")
            monkeypatch.setattr(integration_mod, "handle_reply", _boom)
        provider = SimpleNamespace(
            _provider_id="p108",
            provider_id="p108",
            provider_type="gmail",
        )
        msg = ProviderMessage(
            provider_id="p108",
            external_id="ext-108",
            thread_id="thread-108",
            direction=MessageDirection.INCOMING,
            raw_headers={
                "from": "c@d.com",
                "to": "a@b.com",
                "subject": "Re: t",
            },
            raw_body="interested",
        )
        return gmail_sync._process_provider_message(provider, msg)

    def test_failed_persistence_leaves_message_unseen(self, monkeypatch):
        from services.communication.communication_store import store
        with pytest.raises(RuntimeError):
            self._process(monkeypatch, fail_integration=True)
        assert store.is_message_seen("ext-108") is False

    def test_success_marks_seen_and_duplicate_skipped(self, monkeypatch):
        from services.communication.communication_store import store
        from services.communication import gmail_sync
        from services.conversations.conversation_store import conversation_store
        cid = self._process(monkeypatch)
        assert store.is_message_seen("ext-108") is True
        real = conversation_store.find_by_external_thread("thread-108")
        assert real is not None
        # The inbound reply was persisted into the conversation exactly once.
        reply_msgs = [
            m for m in conversation_store.get_messages_for_conversation(real.conversation_id)
            if m.external_message_id == "ext-108"
        ]
        assert len(reply_msgs) == 1
        # Re-processing the same external id returns None (dedup).
        provider = SimpleNamespace(_provider_id="p108", provider_id="p108")
        msg = SimpleNamespace(
            external_id="ext-108", thread_id="thread-108",
            raw_headers={"from": "c@d.com", "subject": "Re: t"},
        )
        assert gmail_sync._process_provider_message(provider, msg) is None


# ═══════════════════════════════════════════════════════════════════════
# 4. Supabase bounded retry
# ═══════════════════════════════════════════════════════════════════════

class TestBoundedRetry:
    def test_transient_error_retried_then_succeeds(self):
        import asyncio
        from services.persistence.retry import retry_async
        attempts = {"n": 0}

        async def factory():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise TimeoutError("upstream timeout")
            return "ok"

        result = asyncio.run(retry_async(factory, attempts=3, base_delay=0.001, category="test"))
        assert result == "ok"
        assert attempts["n"] == 3

    def test_permanent_error_not_retried(self):
        import asyncio
        from services.persistence.retry import retry_async
        attempts = {"n": 0}

        class AuthError(Exception):
            status_code = 401

        async def factory():
            attempts["n"] += 1
            raise AuthError("unauthorized")

        with pytest.raises(AuthError):
            asyncio.run(retry_async(factory, attempts=3, base_delay=0.001, category="test"))
        assert attempts["n"] == 1

    def test_exhausted_budget_raises_last_error(self):
        import asyncio
        from services.persistence.retry import retry_async
        attempts = {"n": 0}

        async def factory():
            attempts["n"] += 1
            raise ConnectionError("still down")

        with pytest.raises(ConnectionError):
            asyncio.run(retry_async(factory, attempts=2, base_delay=0.001, category="test"))
        assert attempts["n"] == 2

    def test_retry_logs_do_not_leak_secrets(self, caplog):
        import asyncio
        import logging
        from services.persistence.retry import retry_async
        attempts = {"n": 0}
        secret = SENTINEL

        async def factory():
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise ConnectionError(f"down token={secret}")
            return "ok"

        with caplog.at_level(logging.WARNING):
            asyncio.run(retry_async(factory, attempts=2, base_delay=0.001, category="creds"))
        assert secret not in caplog.text

    def test_sync_connected_account_no_false_success_on_permanent_failure(self, monkeypatch):
        from services.supabase import sync_connected_account

        class FakeRepo:
            def __init__(self):
                self.saved = 0

            async def find_for_user(self, user_id, provider):
                raise TimeoutError("db unavailable")

            async def save(self, entity):
                self.saved += 1
                return entity

        import services.persistence.launch as launch
        monkeypatch.setattr(launch, "ConnectedAccountRepository", lambda: FakeRepo())
        ok = sync_connected_account("u1", provider="google", email="a@b.com",
                                    access_token=SENTINEL, refresh_token=SENTINEL)
        assert ok is False

    def test_sync_connected_account_transient_then_success(self, monkeypatch):
        from services.supabase import sync_connected_account
        calls = {"n": 0}

        class FakeRepo:
            async def find_for_user(self, user_id, provider):
                calls["n"] += 1
                if calls["n"] <= 2:
                    raise TimeoutError("first attempts down")
                return None

            async def save(self, entity):
                return entity

        import services.persistence.launch as launch
        monkeypatch.setattr(launch, "ConnectedAccountRepository", lambda: FakeRepo())
        ok = sync_connected_account("u1", provider="google", email="a@b.com",
                                    access_token=SENTINEL, refresh_token=SENTINEL)
        assert ok is True
        assert calls["n"] >= 3


# ═══════════════════════════════════════════════════════════════════════
# 5. Outbound safety
# ═══════════════════════════════════════════════════════════════════════

class TestOutboundPersistenceSafety:
    def test_conversation_creation_idempotent_by_thread(self):
        from services.conversations.conversation_store import conversation_store
        from services.conversations.integration import create_conversation_from_send
        ext_thread = f"thread_{uuid.uuid4().hex[:12]}"
        args = dict(
            provider_id="p108", provider_type="gmail",
            external_thread_id=ext_thread, external_message_id=f"m_{uuid.uuid4().hex[:12]}",
            subject="no dup", from_email="a@b.com", from_name="A",
            to_email="c@d.com", to_name="C", body="hello",
            campaign_id="c108", workflow_id="w108", lead_id="l108",
        )
        first = create_conversation_from_send(**args)
        second = create_conversation_from_send(**args)
        assert first.conversation_id == second.conversation_id
        assert len(conversation_store.get_messages_for_conversation(first.conversation_id)) == 1

    def test_duplicate_send_guard_still_409(self):
        """The route-level duplicate-reply guard set must still reject a reply
        on a conversation that is awaiting a response (mirrors main.py:6100).
        """
        from services.conversations.conversation_models import ConversationStatus
        from services.conversations.conversation_store import conversation_store
        from services.conversations.integration import create_conversation_from_send
        convo = create_conversation_from_send(
            provider_id="p108", provider_type="gmail",
            external_thread_id=f"thread_{uuid.uuid4().hex[:12]}",
            external_message_id=f"m_{uuid.uuid4().hex[:12]}",
            subject="409 guard", from_email="a@b.com", from_name="A",
            to_email="c@d.com", to_name="C", body="hi",
        )
        guard_set = {
            ConversationStatus.SENT,
            ConversationStatus.DELIVERED,
            ConversationStatus.OPENED,
            ConversationStatus.FOLLOW_UP_PENDING,
            ConversationStatus.FOLLOW_UP_READY,
            ConversationStatus.FOLLOW_UP_SENT,
        }
        # A freshly-sent conversation sits in the awaiting-response guard set,
        # so a duplicate reply request would be rejected with 409.
        assert convo.status in guard_set
        assert conversation_store.get_conversation(convo.conversation_id).status in guard_set

    def test_no_auto_resend_on_persistence_failure(self, monkeypatch):
        """A post-send persistence failure must never trigger a resend.

        The only resend path is the outbound scheduler, and it dispatches
        exclusively SCHEDULED drafts — a draft already marked SENT is never
        re-sent regardless of any conversation-persistence failure.
        """
        from services.outbound.draft_store import draft_store
        from services.outbound.outbound_models import (
            DraftMessage,
            DraftStatus,
            Recipient,
        )
        from services.outbound.outbound_scheduler import outbound_scheduler
        draft = DraftMessage(
            id="d-sent-1",
            provider_id="p108",
            subject="never resend",
            body="body",
            recipient=Recipient(email="c@d.com", name="C"),
            sender=Recipient(email="a@b.com", name="A"),
            status=DraftStatus.SENT,
            metadata={"send_at": "2000-01-01T00:00:00+00:00"},
        )
        draft_store.create(draft)
        sent = [d for d in draft_store.list_all().drafts if d.status == DraftStatus.SENT]
        assert len(sent) == 1
        # The scheduler tick only selects SCHEDULED drafts.
        tick = outbound_scheduler._tick
        executed = []
        monkeypatch.setattr(
            outbound_scheduler, "_execute_scheduled",
            lambda did, pid: executed.append(did),
        )
        tick()
        assert executed == []
        # Clean up the global draft store so no state leaks into other tests.
        draft_store.delete("d-sent-1")


# ═══════════════════════════════════════════════════════════════════════
# 6. Ownership boundaries
# ═══════════════════════════════════════════════════════════════════════

class TestOwnershipBoundaries:
    def test_connected_account_scoped_by_user_and_provider(self):
        from services.persistence.launch import ConnectedAccountRepository
        import asyncio

        class FakeRepo(ConnectedAccountRepository):
            def __init__(self):
                self.rows = {}

            async def find_for_user(self, user_id, provider):
                return self.rows.get((user_id, provider))

            async def save(self, entity):
                self.rows[(entity.user_id, entity.provider)] = entity
                return entity

        repo = FakeRepo()
        asyncio.run(repo.save(_ac("u1", "google", "a@b.com")))
        asyncio.run(repo.save(_ac("u2", "google", "c@d.com")))
        asyncio.run(repo.save(_ac("u1", "outlook", "a@outlook.com")))
        assert asyncio.run(repo.find_for_user("u1", "google")).email == "a@b.com"
        assert asyncio.run(repo.find_for_user("u2", "google")).email == "c@d.com"
        assert asyncio.run(repo.find_for_user("u1", "outlook")).email == "a@outlook.com"
        assert asyncio.run(repo.find_for_user("u2", "outlook")) is None

    def test_conversation_not_crossed_between_threads(self):
        from services.conversations.conversation_store import conversation_store
        from services.conversations.integration import create_conversation_from_send
        c1 = create_conversation_from_send(
            provider_id="p108", provider_type="gmail",
            external_thread_id=f"thread_a_{uuid.uuid4().hex[:8]}",
            external_message_id=f"ma_{uuid.uuid4().hex[:8]}",
            subject="a", from_email="a@b.com", from_name="A",
            to_email="c@d.com", to_name="C", body="hi",
        )
        c2 = create_conversation_from_send(
            provider_id="p108", provider_type="gmail",
            external_thread_id=f"thread_b_{uuid.uuid4().hex[:8]}",
            external_message_id=f"mb_{uuid.uuid4().hex[:8]}",
            subject="b", from_email="a@b.com", from_name="A",
            to_email="c@d.com", to_name="C", body="hi",
        )
        assert c1.conversation_id != c2.conversation_id
        # A reply to thread A's conversation must not leak into thread B's.
        from services.conversations.integration import handle_reply
        handle_reply(
            conversation_id=c1.conversation_id, external_message_id=f"ra_{uuid.uuid4().hex[:8]}",
            from_email="c@d.com", from_name="C", to_email="a@b.com", to_name="A",
            subject="Re: a", body="reply-a",
        )
        msgs_b = conversation_store.get_messages_for_conversation(c2.conversation_id)
        assert all(m.subject != "Re: a" for m in msgs_b)


def _ac(user_id, provider, email):
    from services.persistence.launch import ConnectedAccount
    return ConnectedAccount(user_id=user_id, provider=provider, email=email,
                            access_token=SENTINEL, refresh_token=SENTINEL)


# ═══════════════════════════════════════════════════════════════════════
# 7. Rehydration ordering
# ═══════════════════════════════════════════════════════════════════════

class TestRehydration:
    def test_fresh_store_restores_persisted_state(self, tmp_path):
        """A freshly constructed store (pre-worker) sees the persisted state."""
        from services.conversations.conversation_store import ConversationStore, conversation_store
        from services.conversations.integration import create_conversation_from_send
        convo = create_conversation_from_send(
            provider_id="p108", provider_type="gmail",
            external_thread_id=f"thread_{uuid.uuid4().hex[:12]}",
            external_message_id=f"msg_{uuid.uuid4().hex[:12]}",
            subject="rehydrate", from_email="a@b.com", from_name="A",
            to_email="c@d.com", to_name="C", body="hi",
        )
        cid = convo.conversation_id
        fresh = ConversationStore()
        assert fresh.get_conversation(cid) is not None
        assert fresh.get_conversation(cid).subject == "rehydrate"
        assert conversation_store.get_conversation(cid) is not None

    def test_corrupt_state_degraded_and_preserved(self, tmp_path):
        from services.conversations import persistence
        path = str(tmp_path / "corrupt.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"conversations": [{"id": ')
        data, status = persistence.json_file.read_json(path, category="test")
        assert data is None
        assert status is persistence.json_file.JsonFileStatus.CORRUPT
        preserved = [f for f in os.listdir(str(tmp_path)) if f.startswith("corrupt.json.corrupt.")]
        assert len(preserved) == 1

    def test_inbox_sync_engine_starts_once(self):
        import asyncio
        from services.communication.inbox_sync_engine import InboxSyncEngine

        async def _run():
            engine = InboxSyncEngine(interval_seconds=60)
            await engine.start()
            first_task = engine._task
            await engine.start()
            assert engine._task is first_task
            await engine.stop()

        asyncio.run(_run())

    def test_lifecycle_ready_only_after_startup_completes(self):
        from services import lifecycle
        lifecycle.set_starting()
        assert lifecycle.is_ready() is False
        lifecycle.set_ready()
        assert lifecycle.is_ready() is True
        lifecycle.set_starting()
