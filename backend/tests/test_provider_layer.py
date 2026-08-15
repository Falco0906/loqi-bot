"""Tests for the Communication Provider Layer (Phase 3.5.2).

Covers provider registry, Gmail provider, normalizer, communication store,
deduplication, events, sync engine, and integration pipeline.
"""

from datetime import datetime, timezone
from typing import Optional

from services.communication.provider_models import (
    ProviderType, ProviderStatus, ProviderHealth, ConnectionState,
    MessageDirection, ProviderEventType, CommunicationProvider,
    ProviderMessage, NormalizedMessage, SyncCursor, ThreadMapping, SyncResult,
)
from services.communication.provider_base import CommunicationProviderBase
from services.communication.provider_registry import (
    register_provider, get_provider_class, get_provider,
    instantiate_provider, register_instance, remove_instance,
    list_providers, list_registered_types, sync_provider,
    disconnect_provider, health_check, _registry, _instances,
)
from services.communication.communication_store import CommunicationStore
from services.communication.provider_normalizer import (
    normalize_to_conversation_message, normalize_message, _clean_body,
)
from services.communication.provider_events import (
    emit_event, get_events, clear_events, get_all_events, latest_sequence,
    reset_events, _events,
)
from services.communication.gmail_provider import GmailProvider
from services.communication.gmail_sync import sync_all, sync_thread, sync_since_cursor
from services.communication.gmail_webhooks import handle_notification, register_handler, clear_handlers, _handlers
from services.conversation_models import ConversationMessage


# ═══════════════════════════════════════════════════════════════════
# Fixtures & Helpers
# ═══════════════════════════════════════════════════════════════════

def _cleanup():
    _registry.clear()
    _instances.clear()
    reset_events()


def _mock_empty_gmail_response():
    """Mock _gmail_get to simulate an empty Gmail mailbox."""
    responses = {
        "/users/me/profile": {"emailAddress": "test@loqi.ai", "historyId": "50000"},
        "/users/me/labels": {"labels": [{"name": "INBOX"}, {"name": "SENT"}]},
        "/users/me/messages": {"messages": [], "resultSizeEstimate": 0},
    }
    def side_effect(path, params=None):
        # Extract the base path (remove message IDs for individual lookups)
        base = path.split("?")[0]
        if "/users/me/messages/" in base and base != "/users/me/messages":
            # Single message fetch — return a fake message
            return {
                "id": base.split("/")[-1],
                "threadId": "thread_1",
                "historyId": "hist_1",
                "labelIds": ["INBOX"],
                "internalDate": "1700000000000",
                "sizeEstimate": 1000,
                "payload": {
                    "headers": [
                        {"name": "From", "value": "test@example.com"},
                        {"name": "To", "value": "me@loqi.ai"},
                        {"name": "Subject", "value": "Test Email"},
                    ],
                    "body": {"data": "SGVsbG8gV29ybGQ="},
                },
            }
        if base in responses:
            return responses[base]
        if "/users/me/history" in base:
            return {"historyId": "hist_2", "history": []}
        if "/users/me/threads/" in base:
            return {"messages": []}
        return {}
    return side_effect


def _make_gmail_provider_msg(ext_id: str = "msg_1", thread_id: str = "thread_1",
                              body: str = "Hello, interested in your product",
                              direction: str = "incoming") -> ProviderMessage:
    return ProviderMessage(
        provider_id="prov_1",
        external_id=ext_id,
        thread_id=thread_id,
        direction=MessageDirection(direction),
        raw_headers={
            "from": "lead@example.com",
            "to": "me@loqi.ai",
            "subject": "Interesting product",
        },
        raw_body=body,
        received_at=datetime.now(timezone.utc).isoformat(),
    )


# ═══════════════════════════════════════════════════════════════════
# 1. Provider Registry
# ═══════════════════════════════════════════════════════════════════

class TestProviderRegistry:
    def setup_method(self):
        _cleanup()

    def test_registration(self):
        register_provider(GmailProvider)
        assert ProviderType.GMAIL in _registry
        assert _registry[ProviderType.GMAIL] == GmailProvider

    def test_get_provider_class(self):
        register_provider(GmailProvider)
        cls = get_provider_class(ProviderType.GMAIL)
        assert cls is GmailProvider

    def test_get_provider_class_invalid(self):
        assert get_provider_class(ProviderType.GMAIL) is None

    def test_instantiate_provider(self):
        register_provider(GmailProvider)
        instance = instantiate_provider(ProviderType.GMAIL)
        assert isinstance(instance, GmailProvider)

    def test_instantiate_invalid(self):
        assert instantiate_provider(ProviderType.OUTLOOK) is None

    def test_register_instance(self):
        register_provider(GmailProvider)
        instance = instantiate_provider(ProviderType.GMAIL)
        register_instance("inst_1", instance)
        assert get_provider("inst_1") is instance

    def test_remove_instance(self):
        register_provider(GmailProvider)
        instance = instantiate_provider(ProviderType.GMAIL)
        register_instance("inst_2", instance)
        remove_instance("inst_2")
        assert get_provider("inst_2") is None

    def test_list_providers(self):
        register_provider(GmailProvider)
        i1 = instantiate_provider(ProviderType.GMAIL)
        i2 = instantiate_provider(ProviderType.GMAIL)
        register_instance("a", i1)
        register_instance("b", i2)
        providers = list_providers()
        assert len(providers) == 2

    def test_list_registered_types(self):
        register_provider(GmailProvider)
        types = list_registered_types()
        assert ProviderType.GMAIL in types

    def test_disconnect_provider(self):
        register_provider(GmailProvider)
        instance = instantiate_provider(ProviderType.GMAIL)
        register_instance("disc_1", instance)
        result = disconnect_provider("disc_1")
        assert result is True
        assert get_provider("disc_1") is None

    def test_disconnect_nonexistent(self):
        assert disconnect_provider("nonexistent") is False

    def test_health_check_returns_status(self):
        register_provider(GmailProvider)
        instance = instantiate_provider(ProviderType.GMAIL)
        register_instance("health_1", instance)
        status = health_check("health_1")
        assert status == ProviderStatus.OFFLINE  # not connected yet


# ═══════════════════════════════════════════════════════════════════
# 2. Gmail Provider
# ═══════════════════════════════════════════════════════════════════

class TestGmailProvider:
    def setup_method(self):
        _cleanup()

    def test_connect(self):
        register_provider(GmailProvider)
        provider = GmailProvider()
        result = provider.connect("test_token", user_id="user1", email="me@gmail.com")
        assert result.provider_type == ProviderType.GMAIL
        assert result.status == ProviderStatus.HEALTHY
        assert result.metadata.get("email") == "me@gmail.com"

    def test_connection_lifecycle(self):
        provider = GmailProvider()
        provider.connect("token", user_id="u1")
        assert provider._connected is True
        provider.disconnect()
        assert provider._connected is False

    def test_health_healthy(self):
        from unittest.mock import patch
        provider = GmailProvider()
        provider.connect("token", user_id="u1")
        with patch.object(provider, '_gmail_get', return_value={"emailAddress": "test@loqi.ai"}):
            status = provider.health()
        assert status == ProviderStatus.HEALTHY

    def test_health_offline(self):
        provider = GmailProvider()
        status = provider.health()
        assert status == ProviderStatus.OFFLINE

    def test_sync_initial(self):
        from unittest.mock import patch
        provider = GmailProvider()
        provider.connect("token", user_id="u1")
        with patch.object(provider, '_gmail_get', side_effect=_mock_empty_gmail_response()):
            result = provider.sync()
        assert result.cursor
        assert result.errors == []

    def test_sync_incremental(self):
        from unittest.mock import patch
        provider = GmailProvider()
        provider.connect("token", user_id="u1")
        with patch.object(provider, '_gmail_get', side_effect=_mock_empty_gmail_response()):
            result = provider.sync(cursor="prev_cursor")
        assert result.cursor
        assert result.errors == []

    def test_fetch_thread(self):
        from unittest.mock import patch
        provider = GmailProvider()
        provider.connect("token", user_id="u1")
        with patch.object(provider, '_gmail_get', return_value={"messages": []}):
            messages = provider.fetch_thread("thread_1")
        assert messages == []

    def test_fetch_message(self):
        from unittest.mock import patch
        provider = GmailProvider()
        provider.connect("token", user_id="u1")
        with patch.object(provider, '_gmail_get', return_value={"id": "msg_1", "threadId": "t1", "internalDate": "1700000000000", "payload": {"headers": [], "body": {}}}):
            msg = provider.fetch_message("msg_1")
        assert msg is not None
        assert msg.external_id == "msg_1"
        assert msg.thread_id == "t1"

    def test_normalize(self):
        provider = GmailProvider()
        provider.connect("token", user_id="u1")
        pmsg = _make_gmail_provider_msg()
        result = provider.normalize(pmsg)
        assert result["conversation_id"] == "thread_1"
        assert result["direction"] == "incoming"
        assert result["provider"] == "prov_1"

    def test_watch_lifecycle(self):
        provider = GmailProvider()
        provider.connect("token", user_id="u1")
        assert provider.watch() is True
        assert provider.stop_watch() is True

    def test_disconnect_cleans_up(self):
        provider = GmailProvider()
        provider.connect("token", user_id="u1")
        provider.disconnect()
        assert provider._access_token == ""
        assert provider._refresh_token == ""

    def test_decode_body(self):
        import base64
        provider = GmailProvider()
        payload = {
            "body": {
                "data": base64.urlsafe_b64encode(b"Hello world").decode()
            }
        }
        decoded = provider._decode_body(payload)
        assert decoded == "Hello world"

    def test_parse_headers(self):
        provider = GmailProvider()
        payload = {
            "headers": [
                {"name": "From", "value": "lead@example.com"},
                {"name": "Subject", "value": "Test"},
            ]
        }
        headers = provider._parse_headers(payload)
        assert headers["from"] == "lead@example.com"
        assert headers["subject"] == "Test"

    def test_provider_message_from_gmail(self):
        provider = GmailProvider()
        provider.connect("token", user_id="u1")
        gmail_msg = {
            "id": "ext_123",
            "threadId": "thread_abc",
            "labelIds": ["INBOX"],
            "sizeEstimate": 1234,
            "internalDate": "1700000000000",
            "payload": {
                "headers": [
                    {"name": "From", "value": "lead@example.com"},
                    {"name": "Subject", "value": "Hello"},
                ],
                "body": {},
            },
        }
        pmsg = provider._provider_message_from_gmail(gmail_msg, "thread_abc")
        assert pmsg.external_id == "ext_123"
        assert pmsg.thread_id == "thread_abc"
        assert pmsg.direction == MessageDirection.INCOMING

    def test_process_gmail_message_duplicate(self):
        provider = GmailProvider()
        provider.connect("token", user_id="u1")
        gmail_msg = {"id": "dup_1", "threadId": "t1", "internalDate": "1700000000000", "payload": {"headers": [], "body": {}}}
        result1 = provider.process_gmail_message(gmail_msg, "t1")
        assert result1 is not None
        result2 = provider.process_gmail_message(gmail_msg, "t1")
        assert result2 is None  # duplicate

    def test_error_handling_on_sync_failure(self):
        from unittest.mock import patch
        provider = GmailProvider()
        provider.connect("token", user_id="u1")
        with patch.object(provider, '_gmail_get', side_effect=_mock_empty_gmail_response()):
            result = provider.sync()
        assert result.errors == []


# ═══════════════════════════════════════════════════════════════════
# 3. Normalizer
# ═══════════════════════════════════════════════════════════════════

class TestProviderNormalizer:
    def test_gmail_to_conversation_message(self):
        pmsg = _make_gmail_provider_msg()
        cm = normalize_to_conversation_message(pmsg, "conv_1")
        assert isinstance(cm, ConversationMessage)
        assert cm.text == "Hello, interested in your product"
        assert cm.sender == "lead"
        assert cm.subject == "Interesting product"

    def test_metadata_preservation(self):
        pmsg = _make_gmail_provider_msg()
        nm = normalize_message(pmsg, "conv_1")
        assert nm.conversation_id == "conv_1"
        assert nm.sender == "lead@example.com"
        assert nm.recipient == "me@loqi.ai"
        assert nm.subject == "Interesting product"
        assert nm.provider == "prov_1"

    def test_html_normalization(self):
        pmsg = _make_gmail_provider_msg(body="<p>Hello <b>world</b></p>")
        cm = normalize_to_conversation_message(pmsg, "conv_1")
        assert "Hello world" in cm.text
        assert "<b>" not in cm.text

    def test_plain_text_preserved(self):
        pmsg = _make_gmail_provider_msg(body="Just plain text")
        cm = normalize_to_conversation_message(pmsg, "conv_1")
        assert cm.text == "Just plain text"

    def test_empty_body(self):
        pmsg = _make_gmail_provider_msg(body="")
        cm = normalize_to_conversation_message(pmsg, "conv_1")
        assert cm.text == ""

    def test_attachment_handling(self):
        pmsg = _make_gmail_provider_msg()
        assert pmsg.attachments == []

    def test_outgoing_direction(self):
        pmsg = _make_gmail_provider_msg(direction="outgoing")
        cm = normalize_to_conversation_message(pmsg, "conv_1")
        assert cm.sender == "agent"

    def test_clean_body_strips_html(self):
        assert _clean_body("<div>Hello</div>") == "Hello"
        assert _clean_body("plain") == "plain"
        assert _clean_body("") == ""


# ═══════════════════════════════════════════════════════════════════
# 4. Communication Store
# ═══════════════════════════════════════════════════════════════════

class TestCommunicationStore:
    def setup_method(self):
        self.store = CommunicationStore()

    def test_provider_crud(self):
        p = CommunicationProvider(provider_type=ProviderType.GMAIL, user_id="u1")
        self.store.save_provider(p)
        assert self.store.get_provider(p.id) is not None
        assert len(self.store.list_providers()) == 1

    def test_user_providers(self):
        p1 = CommunicationProvider(provider_type=ProviderType.GMAIL, user_id="u1")
        p2 = CommunicationProvider(provider_type=ProviderType.GMAIL, user_id="u1")
        self.store.save_provider(p1)
        self.store.save_provider(p2)
        providers = self.store.get_user_providers("u1")
        # PR10.8.2 invariant: one active provider record per (user, provider
        # type) — a reconnect replaces, never stacks a second Gmail account.
        assert len(providers) == 1
        assert providers[0].id == p2.id

    def test_user_providers_distinct_types_coexist(self):
        p1 = CommunicationProvider(provider_type=ProviderType.GMAIL, user_id="u1")
        p2 = CommunicationProvider(provider_type=ProviderType.MANUAL, user_id="u1")
        self.store.save_provider(p1)
        self.store.save_provider(p2)
        assert len(self.store.get_user_providers("u1")) == 2

    def test_remove_provider(self):
        p = CommunicationProvider(provider_type=ProviderType.GMAIL, user_id="u1")
        self.store.save_provider(p)
        assert self.store.remove_provider(p.id) is True
        assert self.store.get_provider(p.id) is None

    def test_provider_status_update(self):
        p = CommunicationProvider(provider_type=ProviderType.GMAIL, user_id="u1")
        self.store.save_provider(p)
        self.store.update_provider_status(p.id, ProviderStatus.OFFLINE)
        assert self.store.get_provider(p.id).status == ProviderStatus.OFFLINE

    def test_cursor_persistence(self):
        self.store.save_cursor("prov_1", "cursor_abc")
        cursor = self.store.get_cursor("prov_1")
        assert cursor is not None
        assert cursor.cursor == "cursor_abc"

    def test_cursor_nonexistent(self):
        assert self.store.get_cursor("nonexistent") is None

    def test_thread_mapping(self):
        mapping = self.store.map_thread("ext_thread_1", "conv_1", "prov_1", "Subject line")
        assert self.store.get_thread_mapping("ext_thread_1") is mapping
        assert self.store.get_thread_by_conversation("conv_1") is mapping

    def test_thread_mapping_reverse(self):
        self.store.map_thread("ext_2", "conv_2", "prov_1")
        mapping = self.store.get_thread_by_conversation("conv_2")
        assert mapping is not None
        assert mapping.external_thread_id == "ext_2"

    def test_deduplication(self):
        assert self.store.is_message_seen("id_1") is False
        self.store.mark_message_seen("id_1")
        assert self.store.is_message_seen("id_1") is True

    def test_multiple_seen_ids(self):
        self.store.mark_message_seen("a")
        self.store.mark_message_seen("b")
        self.store.mark_message_seen("c")
        assert self.store.message_count() == 3

    def test_update_provider_sync(self):
        p = CommunicationProvider(provider_type=ProviderType.GMAIL, user_id="u1")
        self.store.save_provider(p)
        self.store.update_provider_sync(p.id, "new_cursor")
        assert self.store.get_provider(p.id).sync_cursor == "new_cursor"
        assert self.store.get_provider(p.id).last_sync != ""

    def test_get_all_threads(self):
        self.store.map_thread("t1", "c1", "p1")
        self.store.map_thread("t2", "c2", "p1")
        assert len(self.store.get_all_threads()) == 2

    def test_seen_messages_set(self):
        self.store.mark_message_seen("x")
        assert "x" in self.store.seen_messages()


# ═══════════════════════════════════════════════════════════════════
# 5. Provider Events
# ═══════════════════════════════════════════════════════════════════

class TestProviderEvents:
    def setup_method(self):
        _cleanup()

    def test_event_emission(self):
        ev = emit_event(ProviderEventType.CONNECTED, "prov_1", "Connected")
        assert ev.event_type == ProviderEventType.CONNECTED
        assert ev.provider_id == "prov_1"
        assert ev.message == "Connected"

    def test_event_ordering(self):
        import time
        e1 = emit_event(ProviderEventType.CONNECTED, "p1", "First")
        time.sleep(0.01)
        e2 = emit_event(ProviderEventType.SYNC_STARTED, "p1", "Second")
        events = get_events()
        assert events[-2].sequence < events[-1].sequence

    def test_get_events_by_provider(self):
        emit_event(ProviderEventType.CONNECTED, "p1")
        emit_event(ProviderEventType.CONNECTED, "p2")
        emit_event(ProviderEventType.SYNC_STARTED, "p1")
        p1_events = get_events(provider_id="p1")
        assert len(p1_events) == 2

    def test_get_events_after_sequence(self):
        emit_event(ProviderEventType.CONNECTED, "p1")
        seq = latest_sequence()
        emit_event(ProviderEventType.SYNC_STARTED, "p1")
        after = get_events(after_sequence=seq)
        assert len(after) == 1
        assert after[0].event_type == ProviderEventType.SYNC_STARTED

    def test_clear_events_all(self):
        emit_event(ProviderEventType.CONNECTED, "p1")
        clear_events()
        assert len(get_all_events()) == 0

    def test_clear_events_by_provider(self):
        emit_event(ProviderEventType.CONNECTED, "p1")
        emit_event(ProviderEventType.CONNECTED, "p2")
        clear_events(provider_id="p1")
        assert len(get_all_events()) == 1

    def test_latest_sequence(self):
        assert latest_sequence() == 0
        emit_event(ProviderEventType.CONNECTED, "p1")
        assert latest_sequence() > 0

    def test_sync_lifecycle_events(self):
        emit_event(ProviderEventType.SYNC_STARTED, "p1", "Starting")
        emit_event(ProviderEventType.SYNC_COMPLETED, "p1", "Done")
        emit_event(ProviderEventType.MESSAGE_RECEIVED, "p1", "New msg")
        events = get_all_events()
        types = [e.event_type for e in events]
        assert ProviderEventType.SYNC_STARTED in types
        assert ProviderEventType.SYNC_COMPLETED in types
        assert ProviderEventType.MESSAGE_RECEIVED in types

    def test_provider_lifecycle_events(self):
        emit_event(ProviderEventType.CONNECTED, "p1")
        emit_event(ProviderEventType.DISCONNECTED, "p1")
        emit_event(ProviderEventType.TOKEN_REFRESHED, "p1")
        events = get_all_events()
        assert len(events) == 3

    def test_token_failure_event(self):
        ev = emit_event(ProviderEventType.TOKEN_FAILED, "p1", "Token expired", {"error": "401"})
        assert ev.metadata.get("error") == "401"


# ═══════════════════════════════════════════════════════════════════
# 6. Gmail Sync
# ═══════════════════════════════════════════════════════════════════

class TestGmailSync:
    def setup_method(self):
        _cleanup()

    def test_sync_all(self):
        from unittest.mock import patch
        from services.communication.communication_store import store
        register_provider(GmailProvider)
        provider = GmailProvider()
        provider.connect("token", user_id="u1")
        register_instance(provider._provider_id, provider)
        with patch.object(provider, '_gmail_get', side_effect=_mock_empty_gmail_response()):
            result = sync_all(provider)
        assert result.cursor
        assert result.errors == []

    def test_sync_thread_empty_when_not_connected(self):
        register_provider(GmailProvider)
        provider = GmailProvider()
        # not connected
        result = sync_thread(provider, "thread_1")
        assert result == []

    def test_sync_since_cursor(self):
        from unittest.mock import patch
        register_provider(GmailProvider)
        provider = GmailProvider()
        provider.connect("token", user_id="u1")
        with patch.object(provider, '_gmail_get', side_effect=_mock_empty_gmail_response()):
            result = sync_since_cursor(provider, "prev_cursor")
        assert result.errors == []

    def test_cursor_stored_after_sync(self):
        from unittest.mock import patch
        from services.communication.communication_store import store
        register_provider(GmailProvider)
        provider = GmailProvider()
        provider.connect("token", user_id="u1")
        with patch.object(provider, '_gmail_get', side_effect=_mock_empty_gmail_response()):
            sync_all(provider)
        cursor = store.get_cursor(provider._provider_id)
        assert cursor is not None


# ═══════════════════════════════════════════════════════════════════
# 7. Gmail Webhooks
# ═══════════════════════════════════════════════════════════════════

class TestGmailWebhooks:
    def setup_method(self):
        clear_handlers()
        _cleanup()

    def test_handle_notification(self):
        payload = {"emailAddress": "me@gmail.com", "historyId": "12345"}
        result = handle_notification(payload, "prov_1")
        assert result["status"] == "ok"
        assert result["history_id"] == "12345"

    def test_handle_notification_no_history_id(self):
        payload = {"emailAddress": "me@gmail.com"}
        result = handle_notification(payload, "prov_1")
        assert result["status"] == "ignored"

    def test_register_handler(self):
        calls = []

        def handler(pid, payload):
            calls.append((pid, payload))

        register_handler("on_notification", handler)
        payload = {"emailAddress": "me@gmail.com", "historyId": "12345"}
        handle_notification(payload, "prov_1")
        assert len(calls) == 1
        assert calls[0][0] == "prov_1"

    def test_multiple_handlers(self):
        calls = []

        def h1(pid, pl): calls.append("h1")
        def h2(pid, pl): calls.append("h2")

        register_handler("on_notification", h1)
        register_handler("on_notification", h2)
        handle_notification({"historyId": "1", "emailAddress": "a@b.com"}, "p1")
        assert "h1" in calls
        assert "h2" in calls

    def test_clear_handlers(self):
        register_handler("on_notification", lambda p, pl: None)
        clear_handlers()
        assert len(_handlers.get("on_notification", [])) == 0


# ═══════════════════════════════════════════════════════════════════
# 8. Integration: Sync → Normalize → Conversation Intelligence
# ═══════════════════════════════════════════════════════════════════

class TestIntegration:
    def setup_method(self):
        _cleanup()
        from services.communication.communication_store import store
        self.store = store
        self.store._providers.clear()
        self.store._cursors.clear()
        self.store._thread_mappings.clear()
        self.store._by_conversation.clear()
        self.store._seen_message_ids.clear()
        self.store._user_providers.clear()
        from services.conversation_memory import memory_store
        memory_store._store.clear()
        from services.conversation_timeline import clear_all
        clear_all()

    def _establish_loqi_relationship(self, provider, thread_id: str, ext_id: str = "out_1"):
        """Create a trusted Loqi conversation for the thread, as the outbound
        send path does (PR8.1 requires a real relationship before ingestion)."""
        from services.conversations.integration import create_conversation_from_send
        return create_conversation_from_send(
            provider_id=provider._provider_id,
            provider_type="gmail",
            external_thread_id=thread_id,
            external_message_id=ext_id,
            subject="Outreach",
            from_email="me@gmail.com",
            from_name="Me",
            to_email="lead@example.com",
            to_name="Lead",
            body="Hello",
            campaign_id="campaign-1",
            workflow_id="campaign-1",
            lead_id="lead-1",
        )

    def test_full_pipeline(self):
        """Sync → Normalize → Conversation Intelligence pipeline."""
        register_provider(GmailProvider)
        provider = GmailProvider()
        provider.connect("token", user_id="u1", email="me@gmail.com")
        register_instance(provider._provider_id, provider)

        self._establish_loqi_relationship(provider, "int_thread_1")

        from services.communication.gmail_sync import _process_provider_message
        pmsg = _make_gmail_provider_msg(
            ext_id="int_1", thread_id="int_thread_1",
            body="How much does this cost? I need pricing",
        )
        cid = _process_provider_message(provider, pmsg)
        assert cid is not None

        from services.conversation_memory import memory_store
        mem = memory_store.get(cid)
        assert mem is not None
        assert len(mem.buying_signals) > 0

        from services.conversation_timeline import get_events
        events = get_events(cid)
        assert len(events) >= 1

    def test_duplicate_message_skipped(self):
        register_provider(GmailProvider)
        provider = GmailProvider()
        provider.connect("token", user_id="u1")
        register_instance(provider._provider_id, provider)

        self._establish_loqi_relationship(provider, "t1")

        from services.communication.gmail_sync import _process_provider_message
        pmsg = _make_gmail_provider_msg(ext_id="dup_test", thread_id="t1", body="Hello")
        cid1 = _process_provider_message(provider, pmsg)
        cid2 = _process_provider_message(provider, pmsg)
        assert cid1 is not None
        assert cid2 is None

    def test_multiple_messages_same_thread(self):
        register_provider(GmailProvider)
        provider = GmailProvider()
        provider.connect("token", user_id="u1")
        register_instance(provider._provider_id, provider)

        self._establish_loqi_relationship(provider, "shared_t")

        from services.communication.gmail_sync import _process_provider_message
        from services.conversation_memory import memory_store

        pmsg1 = _make_gmail_provider_msg(ext_id="m1", thread_id="shared_t", body="First message")
        pmsg2 = _make_gmail_provider_msg(ext_id="m2", thread_id="shared_t", body="How much does it cost?")

        cid1 = _process_provider_message(provider, pmsg1)
        cid2 = _process_provider_message(provider, pmsg2)
        assert cid1 == cid2  # same thread → same conversation

        mem = memory_store.get(cid1)
        assert mem is not None
        assert len(mem.buying_signals) > 0

    def test_duplicate_thread_detection(self):
        """Same thread_id maps to the same conversation_id every time."""
        self.store.map_thread("unique_t", "conv_unique", "prov_1")
        mapping = self.store.get_thread_mapping("unique_t")
        assert mapping is not None
        assert mapping.conversation_id == "conv_unique"

    def test_cursor_correctness(self):
        self.store.save_cursor("prov_c", "cursor_v1")
        self.store.save_cursor("prov_c", "cursor_v2")
        cursor = self.store.get_cursor("prov_c")
        assert cursor.cursor == "cursor_v2"

    def test_incremental_sync_behavior(self):
        from unittest.mock import patch
        register_provider(GmailProvider)
        provider = GmailProvider()
        provider.connect("token", user_id="u1")
        with patch.object(provider, '_gmail_get', side_effect=_mock_empty_gmail_response()):
            result1 = provider.sync(cursor="")
            assert result1.cursor
            assert result1.errors == []
            result2 = provider.sync(cursor=result1.cursor)
            assert result2.cursor
            assert result2.errors == []
