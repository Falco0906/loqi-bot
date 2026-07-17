"""Comprehensive tests for the Outbound Communication Engine."""
import json
from unittest.mock import patch, MagicMock
import pytest
from pydantic import ValidationError

from services.outbound.outbound_models import (
    DraftMessage, SendRequest, SendResult, ScheduledMessage,
    DraftStatus, ApprovalState, DeliveryStatus, Recipient,
    Attachment, OutboundMessage, DraftVersion, DraftListResult,
    SendHistoryItem, OutboundMetadata,
)
from services.outbound.draft_store import draft_store, DraftStore
from services.outbound.outbound_persistence import outbound_persistence, OutboundPersistence
from services.outbound.outbound_events import (
    emit_event, get_events, get_all_events, clear_events,
    reset_events, OutboundEventType, latest_sequence,
)
from services.outbound.outbound_registry import (
    register_outbound_provider, get_provider_class, get_provider,
    register_instance, remove_instance, list_providers,
    list_registered_types,
)
from services.outbound.outbound_executor import OutboundExecutor


# ── Fixtures ──

@pytest.fixture(autouse=True)
def clean_state():
    draft_store.clear()
    outbound_persistence.clear()
    reset_events()
    yield


def make_draft(**overrides) -> DraftMessage:
    params = dict(
        provider_id="test_provider",
        conversation_id="conv_1",
        thread_id="thread_1",
        workflow_id="wf_1",
        subject="Test Subject",
        body="Test body content",
        recipient=Recipient(email="lead@example.com", name="Lead"),
        sender=Recipient(email="me@example.com", name="Me"),
    )
    params.update(overrides)
    return DraftMessage(**params)


# ── Model Tests ──

class TestOutboundModels:
    def test_draft_message_defaults(self):
        d = make_draft()
        assert d.id
        assert d.status == DraftStatus.DRAFT
        assert d.approval_state == ApprovalState.PENDING
        assert d.version == 1
        assert d.created_at
        assert d.updated_at

    def test_draft_message_auto_id(self):
        d = make_draft()
        assert len(d.id) == 12

    def test_send_request_creation(self):
        s = SendRequest(
            provider_id="p1",
            subject="Hello",
            body="World",
            recipient=Recipient(email="a@b.com"),
            sender=Recipient(email="me@me.com"),
        )
        assert s.provider_id == "p1"

    def test_send_result_defaults(self):
        r = SendResult(provider_id="p1")
        assert r.status == DeliveryStatus.PENDING
        assert r.id
        assert r.sent_at

    def test_recipient_optional_name(self):
        r = Recipient(email="a@b.com")
        assert r.name == ""

    def test_attachment_model(self):
        a = Attachment(filename="test.pdf", content_type="application/pdf", data="base64data", size=100)
        assert a.filename == "test.pdf"

    def test_scheduled_message(self):
        s = ScheduledMessage(
            provider_id="p1",
            subject="Scheduled",
            body="Later",
            recipient=Recipient(email="a@b.com"),
            sender=Recipient(email="me@me.com"),
            send_at="2026-07-20T12:00:00Z",
        )
        assert s.status == DeliveryStatus.SCHEDULED
        assert s.id

    def test_draft_version_auto_timestamp(self):
        v = DraftVersion(draft_id="d1", version=1, subject="S", body="B")
        assert v.edited_at

    def test_recipient_accepts_empty_email(self):
        r = Recipient(email="")
        assert r.email == ""

    def test_draft_list_result(self):
        dr = DraftListResult()
        assert dr.total == 0
        assert dr.drafts == []


# ── Draft Store Tests ──

class TestDraftStore:
    def test_create_draft(self):
        d = make_draft()
        result = draft_store.create(d)
        assert result.id == d.id
        assert result.version == 1
        assert draft_store.count() == 1

    def test_get_draft(self):
        d = make_draft()
        draft_store.create(d)
        fetched = draft_store.get(d.id)
        assert fetched is not None
        assert fetched.subject == "Test Subject"

    def test_get_nonexistent(self):
        assert draft_store.get("nonexistent") is None

    def test_update_draft(self):
        d = make_draft()
        draft_store.create(d)
        d.body = "Updated body"
        updated = draft_store.update(d)
        assert updated is not None
        assert updated.version == 2
        assert updated.body == "Updated body"

    def test_update_nonexistent(self):
        d = make_draft()
        assert draft_store.update(d) is None

    def test_delete_draft(self):
        d = make_draft()
        draft_store.create(d)
        assert draft_store.delete(d.id) is True
        assert draft_store.get(d.id) is None
        assert draft_store.count() == 0

    def test_delete_nonexistent(self):
        assert draft_store.delete("nonexistent") is False

    def test_approve_draft(self):
        d = make_draft()
        draft_store.create(d)
        result = draft_store.approve(d.id)
        assert result is not None
        assert result.approval_state == ApprovalState.APPROVED
        assert result.status == DraftStatus.APPROVED

    def test_auto_approve_draft(self):
        d = make_draft()
        draft_store.create(d)
        result = draft_store.approve(d.id, auto=True)
        assert result.approval_state == ApprovalState.AUTO_APPROVED

    def test_reject_draft(self):
        d = make_draft()
        draft_store.create(d)
        result = draft_store.reject(d.id)
        assert result.approval_state == ApprovalState.REJECTED

    def test_mark_sent(self):
        d = make_draft()
        draft_store.create(d)
        result = draft_store.mark_sent(d.id)
        assert result.status == DraftStatus.SENT

    def test_archive_draft(self):
        d = make_draft()
        draft_store.create(d)
        assert draft_store.archive(d.id) is True
        fetched = draft_store.get(d.id)
        assert fetched.status == DraftStatus.ARCHIVED

    def test_list_by_provider(self):
        draft_store.create(make_draft(provider_id="p1"))
        draft_store.create(make_draft(provider_id="p1"))
        draft_store.create(make_draft(provider_id="p2"))
        result = draft_store.list_by_provider("p1")
        assert result.total == 2
        result = draft_store.list_by_provider("p2")
        assert result.total == 1

    def test_list_by_conversation(self):
        draft_store.create(make_draft(conversation_id="c1"))
        draft_store.create(make_draft(conversation_id="c1"))
        result = draft_store.list_by_conversation("c1")
        assert result.total == 2

    def test_list_by_workflow(self):
        draft_store.create(make_draft(workflow_id="w1"))
        result = draft_store.list_by_workflow("w1")
        assert result.total == 1

    def test_list_all(self):
        draft_store.create(make_draft())
        draft_store.create(make_draft())
        result = draft_store.list_all()
        assert result.total == 2

    def test_version_history(self):
        d = make_draft()
        draft_store.create(d)
        d.body = "v2"
        draft_store.update(d)
        d.body = "v3"
        draft_store.update(d)
        versions = draft_store.get_versions(d.id)
        assert len(versions) == 3
        assert versions[0].version == 1
        assert versions[2].version == 3

    def test_approve_nonexistent(self):
        assert draft_store.approve("nonexistent") is None

    def test_reject_nonexistent(self):
        assert draft_store.reject("nonexistent") is None


# ── Persistence Tests ──

class TestOutboundPersistence:
    def test_record_send(self):
        result = SendResult(provider_id="p1", external_message_id="ext_1", status=DeliveryStatus.SENT)
        item = outbound_persistence.record_send(result, subject="Test", recipient_email="a@b.com")
        assert item is not None
        assert item.status == DeliveryStatus.SENT
        assert len(outbound_persistence.get_history()) == 1

    def test_record_send_failure(self):
        result = SendResult(provider_id="p1", status=DeliveryStatus.FAILED, error="SMTP error")
        item = outbound_persistence.record_send(result, subject="Fail")
        assert item.status == DeliveryStatus.FAILED

    def test_delivery_update(self):
        result = SendResult(provider_id="p1", status=DeliveryStatus.SENT)
        outbound_persistence.record_send(result, subject="Test")
        assert outbound_persistence.record_delivery_update(result.id, DeliveryStatus.DELIVERED) is True
        updated = outbound_persistence.get_send_result(result.id)
        assert updated.status == DeliveryStatus.DELIVERED

    def test_get_history_filtered(self):
        outbound_persistence.record_send(SendResult(provider_id="p1", status=DeliveryStatus.SENT), subject="A")
        outbound_persistence.record_send(SendResult(provider_id="p2", status=DeliveryStatus.SENT), subject="B")
        assert len(outbound_persistence.get_history(provider_id="p1")) == 1
        assert len(outbound_persistence.get_history(provider_id="p2")) == 1

    def test_get_send_result_nonexistent(self):
        assert outbound_persistence.get_send_result("nonexistent") is None


# ── Events Tests ──

class TestOutboundEvents:
    def test_event_emission(self):
        e = emit_event(OutboundEventType.DRAFT_CREATED, "p1", "Draft created")
        assert e.event_type == OutboundEventType.DRAFT_CREATED
        assert e.provider_id == "p1"
        assert e.sequence > 0

    def test_event_ordering(self):
        e1 = emit_event(OutboundEventType.DRAFT_CREATED, "p1")
        e2 = emit_event(OutboundEventType.DRAFT_UPDATED, "p1")
        assert e2.sequence > e1.sequence

    def test_get_events_by_provider(self):
        emit_event(OutboundEventType.DRAFT_CREATED, "p1")
        emit_event(OutboundEventType.DRAFT_CREATED, "p2")
        events = get_events(provider_id="p1")
        assert len(events) == 1

    def test_get_events_after_sequence(self):
        e1 = emit_event(OutboundEventType.DRAFT_CREATED, "p1")
        emit_event(OutboundEventType.DRAFT_UPDATED, "p1")
        events = get_events(after_sequence=e1.sequence)
        assert len(events) == 1

    def test_get_all_events(self):
        emit_event(OutboundEventType.DRAFT_CREATED, "p1")
        emit_event(OutboundEventType.MESSAGE_SENT, "p1")
        assert len(get_all_events()) == 2

    def test_clear_events_all(self):
        emit_event(OutboundEventType.DRAFT_CREATED, "p1")
        clear_events()
        assert len(get_all_events()) == 0

    def test_clear_events_by_provider(self):
        emit_event(OutboundEventType.DRAFT_CREATED, "p1")
        emit_event(OutboundEventType.DRAFT_CREATED, "p2")
        clear_events(provider_id="p1")
        assert len(get_all_events()) == 1

    def test_latest_sequence(self):
        emit_event(OutboundEventType.DRAFT_CREATED, "p1")
        seq = latest_sequence()
        assert seq > 0

    def test_latest_sequence_empty(self):
        assert latest_sequence() == 0

    def test_all_event_types(self):
        for et in OutboundEventType:
            e = emit_event(et, "p1", f"Testing {et.value}")
            assert e.event_type == et


# ── Registry Tests ──

class TestOutboundRegistry:
    def test_register_and_get_class(self):
        from services.outbound.outbound_base import OutboundProviderBase
        class MockOutbound(OutboundProviderBase):
            provider_type = "mock_test"
            def create_draft(self, draft): return draft
            def update_draft(self, draft): return draft
            def delete_draft(self, draft_id): return True
            def send(self, request): return SendResult(provider_id=request.provider_id)
            def schedule(self, draft, send_at): return ScheduledMessage(
                provider_id="p1", subject="", body="",
                recipient=Recipient(email="a@b.com"), sender=Recipient(email="b@b.com"),
                send_at=send_at)
            def cancel_schedule(self, schedule_id): return True
            def get_status(self, message_id): return "sent"
            def fetch_draft(self, draft_id): return None
            def list_drafts(self): return DraftListResult()
        register_outbound_provider(MockOutbound)
        cls = get_provider_class("mock_test")
        assert cls is MockOutbound
        assert "mock_test" in list_registered_types()

    def test_instance_lifecycle(self):
        from services.outbound.outbound_base import OutboundProviderBase
        class SimpleOutbound(OutboundProviderBase):
            provider_type = "simple"
            def create_draft(self, draft): return draft
            def update_draft(self, draft): return draft
            def delete_draft(self, draft_id): return True
            def send(self, request): return SendResult(provider_id=request.provider_id)
            def schedule(self, draft, send_at): return ScheduledMessage(
                provider_id="p1", subject="", body="",
                recipient=Recipient(email="a@b.com"), sender=Recipient(email="b@b.com"),
                send_at=send_at)
            def cancel_schedule(self, schedule_id): return True
            def get_status(self, message_id): return "sent"
            def fetch_draft(self, draft_id): return None
            def list_drafts(self): return DraftListResult()
        register_outbound_provider(SimpleOutbound)
        instance = SimpleOutbound()
        register_instance("inst_1", instance)
        assert get_provider("inst_1") is instance
        assert "inst_1" in list_providers()
        remove_instance("inst_1")
        assert get_provider("inst_1") is None


# ── Executor Tests ──

class TestOutboundExecutor:
    @pytest.fixture(autouse=True)
    def setup_mock_provider(self):
        from services.outbound.outbound_base import OutboundProviderBase
        from services.outbound.outbound_registry import (
            register_outbound_provider, register_instance, remove_instance,
        )
        class MockOutboundForExec(OutboundProviderBase):
            provider_type = "mock_exec"
            def create_draft(self, draft): return draft
            def update_draft(self, draft): return draft
            def delete_draft(self, draft_id): return True
            def send(self, request): return SendResult(provider_id=request.provider_id, external_message_id="ext_1", status=DeliveryStatus.SENT)
            def schedule(self, draft, send_at): return ScheduledMessage(
                provider_id="mock_exec", subject=draft.subject, body=draft.body,
                recipient=draft.recipient, sender=draft.sender, send_at=send_at,
                draft_id=draft.id)
            def cancel_schedule(self, schedule_id): return True
            def get_status(self, message_id): return "sent"
            def fetch_draft(self, draft_id): return None
            def list_drafts(self): return DraftListResult()
        register_outbound_provider(MockOutboundForExec)
        inst = MockOutboundForExec()
        register_instance("p1", inst)
        register_instance("mock_exec", inst)
        yield
        remove_instance("p1")
        remove_instance("mock_exec")

    def test_execute_unknown_action(self):
        ex = OutboundExecutor()
        result = ex.execute("nonexistent", {})
        assert result["ok"] is False
        assert "Unknown" in result["error"]

    def test_execute_create_draft(self):
        draft_store.clear()
        ex = OutboundExecutor()
        result = ex.execute("create_reply_draft", {
            "provider_id": "p1",
            "conversation_id": "conv_1",
            "subject": "Hello",
            "body": "World",
            "recipient": {"email": "a@b.com", "name": "A"},
            "sender": {"email": "me@me.com", "name": "Me"},
            "cc": [],
            "bcc": [],
        })
        assert result["ok"] is True
        assert result["draft_id"]
        assert draft_store.count() == 1

    def test_execute_send_no_draft(self):
        ex = OutboundExecutor()
        result = ex.execute("send_reply", {
            "provider_id": "p1",
            "subject": "Hello",
            "body": "World",
            "recipient": {"email": "a@b.com"},
            "sender": {"email": "me@me.com"},
        })
        assert result["ok"] is True

    def test_execute_delete_draft_nonexistent(self):
        ex = OutboundExecutor()
        result = ex.execute("delete_draft", {
            "provider_id": "p1",
            "draft_id": "nonexistent",
        })
        assert result["ok"] is False

    def test_execute_delete_draft(self):
        draft_store.create(make_draft())
        drafts = draft_store.list_all()
        assert drafts.total == 1
        did = drafts.drafts[0].id
        ex = OutboundExecutor()
        result = ex.execute("delete_draft", {
            "provider_id": "p1",
            "draft_id": did,
        })
        assert result["ok"] is True
        assert draft_store.count() == 0

    def test_execute_schedule(self):
        draft_store.create(make_draft(provider_id="mock_exec"))
        did = draft_store.list_all().drafts[0].id
        ex = OutboundExecutor()
        result = ex.execute("schedule_reply", {
            "provider_id": "mock_exec",
            "draft_id": did,
            "send_at": "2026-07-20T12:00:00Z",
        })
        assert result["ok"] is True

    def test_execute_schedule_nonexistent(self):
        ex = OutboundExecutor()
        result = ex.execute("schedule_reply", {
            "provider_id": "p1",
            "draft_id": "nonexistent",
            "send_at": "2026-07-20T12:00:00Z",
        })
        assert result["ok"] is False


# ── Approval Lifecycle ──

class TestApprovalLifecycle:
    def test_full_approval_flow(self):
        d = make_draft()
        draft_store.create(d)
        assert d.approval_state == ApprovalState.PENDING
        draft_store.approve(d.id)
        assert draft_store.get(d.id).approval_state == ApprovalState.APPROVED
        draft_store.reject(d.id)
        assert draft_store.get(d.id).approval_state == ApprovalState.REJECTED

    def test_auto_approve(self):
        d = make_draft()
        draft_store.create(d)
        draft_store.approve(d.id, auto=True)
        assert draft_store.get(d.id).approval_state == ApprovalState.AUTO_APPROVED

    def test_send_after_approval(self):
        d = make_draft()
        draft_store.create(d)
        draft_store.approve(d.id)
        draft_store.mark_sent(d.id)
        assert draft_store.get(d.id).status == DraftStatus.SENT

    def test_reject_after_approve(self):
        d = make_draft()
        draft_store.create(d)
        draft_store.approve(d.id)
        draft_store.reject(d.id)
        assert draft_store.get(d.id).approval_state == ApprovalState.REJECTED


# ── Scheduling Lifecycle ──

class TestSchedulingLifecycle:
    @pytest.fixture(autouse=True)
    def setup_mock_provider(self):
        from services.outbound.outbound_base import OutboundProviderBase
        from services.outbound.outbound_registry import (
            register_outbound_provider, register_instance, remove_instance,
        )
        class MockOutboundSchedule(OutboundProviderBase):
            provider_type = "mock_sched"
            def create_draft(self, draft): return draft
            def update_draft(self, draft): return draft
            def delete_draft(self, draft_id): return True
            def send(self, request): return SendResult(provider_id=request.provider_id, external_message_id="ext_1", status=DeliveryStatus.SENT)
            def schedule(self, draft, send_at): return ScheduledMessage(
                provider_id="mock_sched", subject=draft.subject, body=draft.body,
                recipient=draft.recipient, sender=draft.sender, send_at=send_at,
                draft_id=draft.id)
            def cancel_schedule(self, schedule_id): return True
            def get_status(self, message_id): return "sent"
            def fetch_draft(self, draft_id): return None
            def list_drafts(self): return DraftListResult()
        register_outbound_provider(MockOutboundSchedule)
        inst = MockOutboundSchedule()
        register_instance("p1", inst)
        yield
        remove_instance("p1")

    def test_schedule_creates_event(self):
        reset_events()
        d = make_draft()
        draft_store.create(d)
        from services.outbound.outbound_registry import schedule as reg_schedule
        s = reg_schedule("p1", d, "2026-07-20T12:00:00Z")
        assert s is not None
        assert s.status == DeliveryStatus.SCHEDULED
        # Actually calls through to provider — this test will use registry
        # In practice the Gmail provider creates the ScheduledMessage

    def test_cancel_schedule(self):
        from services.outbound.outbound_registry import cancel_schedule
        result = cancel_schedule("p1", "sched_1")
        # Provider returns True generically
        assert result is not False


# ── Draft Provider Relationship ──

class TestDraftProviderRelationship:
    def test_draft_linked_to_provider(self):
        d = make_draft(provider_id="gmail_provider")
        draft_store.create(d)
        result = draft_store.list_by_provider("gmail_provider")
        assert result.total == 1

    def test_draft_linked_to_conversation(self):
        d = make_draft(conversation_id="conv_abc")
        draft_store.create(d)
        result = draft_store.list_by_conversation("conv_abc")
        assert result.total == 1

    def test_draft_linked_to_workflow(self):
        d = make_draft(workflow_id="wf_xyz")
        draft_store.create(d)
        result = draft_store.list_by_workflow("wf_xyz")
        assert result.total == 1

    def test_draft_multiple_links(self):
        d = make_draft(
            provider_id="p1",
            conversation_id="c1",
            workflow_id="w1",
        )
        draft_store.create(d)
        assert draft_store.list_by_provider("p1").total == 1
        assert draft_store.list_by_conversation("c1").total == 1
        assert draft_store.list_by_workflow("w1").total == 1


# ── Gmail Outbound Provider Tests (mocked) ──

class TestGmailOutboundProvider:
    @pytest.fixture
    def provider(self):
        from services.outbound.gmail_outbound import GmailOutboundProvider
        p = GmailOutboundProvider()
        p.configure(
            provider_id="gmail_test",
            access_token="fake_token",
            refresh_token="fake_refresh",
            client_id="fake_client",
            client_secret="fake_secret",
            token_expiry=9999999999,
        )
        return p

    def test_create_draft(self, provider):
        with patch.object(provider, '_headers', return_value={"Authorization": "Bearer fake"}):
            with patch('requests.post') as mock_post:
                mock_post.return_value.status_code = 200
                mock_post.return_value.json.return_value = {"id": "ext_draft_1"}
                draft = make_draft(provider_id="gmail_test")
                result = provider.create_draft(draft)
                assert result.external_draft_id == "ext_draft_1"

    def test_send_success(self, provider):
        with patch.object(provider, '_headers', return_value={"Authorization": "Bearer fake"}):
            with patch('requests.post') as mock_post:
                mock_post.return_value.status_code = 200
                mock_post.return_value.json.return_value = {"id": "ext_msg_1", "threadId": "thread_1"}
                request = SendRequest(
                    provider_id="gmail_test",
                    subject="Test",
                    body="Body",
                    recipient=Recipient(email="a@b.com"),
                    sender=Recipient(email="me@me.com"),
                )
                result = provider.send(request)
                assert result.status == DeliveryStatus.SENT
                assert result.external_message_id == "ext_msg_1"

    def test_send_failure(self, provider):
        with patch.object(provider, '_headers', return_value={"Authorization": "Bearer fake"}):
            with patch('requests.post') as mock_post:
                mock_post.return_value.status_code = 400
                mock_post.return_value.text = "Bad request"
                request = SendRequest(
                    provider_id="gmail_test",
                    subject="Test",
                    body="Body",
                    recipient=Recipient(email="a@b.com"),
                    sender=Recipient(email="me@me.com"),
                )
                result = provider.send(request)
                assert result.status == DeliveryStatus.FAILED
                assert result.error

    def test_delete_draft_success(self, provider):
        with patch.object(provider, '_headers', return_value={"Authorization": "Bearer fake"}):
            with patch('requests.delete') as mock_delete:
                mock_delete.return_value.status_code = 204
                assert provider.delete_draft("draft_1") is True

    def test_delete_draft_failure(self, provider):
        with patch.object(provider, '_headers', return_value={"Authorization": "Bearer fake"}):
            with patch('requests.delete') as mock_delete:
                mock_delete.return_value.status_code = 404
                assert provider.delete_draft("draft_1") is False

    def test_schedule(self, provider):
        draft = make_draft()
        result = provider.schedule(draft, "2026-07-20T12:00:00Z")
        assert result.send_at == "2026-07-20T12:00:00Z"
        assert result.status == DeliveryStatus.SCHEDULED

    def test_cancel_schedule(self, provider):
        assert provider.cancel_schedule("sched_1") is True

    def test_get_status(self, provider):
        with patch.object(provider, '_headers', return_value={"Authorization": "Bearer fake"}):
            with patch('requests.get') as mock_get:
                mock_get.return_value.status_code = 200
                assert provider.get_status("msg_1") == "sent"

    def test_list_drafts(self, provider):
        with patch.object(provider, '_headers', return_value={"Authorization": "Bearer fake"}):
            with patch('requests.get') as mock_get:
                mock_get.return_value.status_code = 200
                mock_get.return_value.json.return_value = {"drafts": [{"id": "d1"}, {"id": "d2"}]}
                result = provider.list_drafts()
                assert result.total == 2

    def test_update_draft_requires_external_id(self, provider):
        draft = make_draft(provider_id="gmail_test")
        with pytest.raises(Exception, match="external_draft_id"):
            provider.update_draft(draft)


# ── Integration Tests — Phase 3.5.3A.1 ──

class TestDraftStatusLifecycle:
    def test_sending_status(self):
        d = make_draft()
        draft_store.create(d)
        result = draft_store.mark_sending(d.id)
        assert result is not None
        assert result.status == DraftStatus.SENDING
        assert draft_store.get(d.id).status == DraftStatus.SENDING

    def test_failed_status(self):
        d = make_draft()
        draft_store.create(d)
        result = draft_store.mark_failed(d.id, "Connection error")
        assert result.status == DraftStatus.FAILED
        fetched = draft_store.get(d.id)
        assert fetched.status == DraftStatus.FAILED

    def test_cancelled_status(self):
        d = make_draft()
        draft_store.create(d)
        result = draft_store.mark_cancelled(d.id)
        assert result.status == DraftStatus.CANCELLED

    def test_status_transitions(self):
        d = make_draft()
        draft_store.create(d)
        assert d.status == DraftStatus.DRAFT
        draft_store.approve(d.id)
        assert draft_store.get(d.id).status == DraftStatus.APPROVED
        draft_store.mark_sending(d.id)
        assert draft_store.get(d.id).status == DraftStatus.SENDING
        draft_store.mark_sent(d.id)
        assert draft_store.get(d.id).status == DraftStatus.SENT

    def test_failed_transition_from_approved(self):
        d = make_draft()
        draft_store.create(d)
        draft_store.approve(d.id)
        draft_store.mark_failed(d.id, "API error")
        assert draft_store.get(d.id).status == DraftStatus.FAILED


class TestGmailMetadata:
    def test_gmail_fields_on_draft(self):
        d = make_draft()
        d.external_draft_id = "ext_123"
        d.gmail_message_id = "msg_456"
        d.gmail_thread_id = "thread_789"
        draft_store.create(d)
        fetched = draft_store.get(d.id)
        assert fetched.external_draft_id == "ext_123"
        assert fetched.gmail_message_id == "msg_456"
        assert fetched.gmail_thread_id == "thread_789"

    def test_gmail_fields_update_after_send(self):
        d = make_draft()
        draft_store.create(d)
        d.external_draft_id = "ext_999"
        draft_store.update(d)
        assert draft_store.get(d.id).external_draft_id == "ext_999"


class TestOutboundScheduler:
    @pytest.fixture(autouse=True)
    def setup_provider(self):
        from services.outbound.outbound_base import OutboundProviderBase
        from services.outbound.outbound_registry import (
            register_outbound_provider, register_instance, remove_instance,
        )
        class MockSchedProvider(OutboundProviderBase):
            provider_type = "mock_sched_int"
            def create_draft(self, draft): return draft
            def update_draft(self, draft): return draft
            def delete_draft(self, draft_id): return True
            def send(self, request): return SendResult(
                provider_id=request.provider_id,
                external_message_id="ext_sent_1",
                status=DeliveryStatus.SENT,
                draft_id=request.draft_id,
            )
            def schedule(self, draft, send_at): return ScheduledMessage(
                provider_id="mock_sched_int", subject=draft.subject, body=draft.body,
                recipient=draft.recipient, sender=draft.sender, send_at=send_at,
                draft_id=draft.id)
            def cancel_schedule(self, schedule_id): return True
            def get_status(self, message_id): return "sent"
            def fetch_draft(self, draft_id): return None
            def list_drafts(self): return DraftListResult()
        register_outbound_provider(MockSchedProvider)
        inst = MockSchedProvider()
        register_instance("p1", inst)
        yield
        remove_instance("p1")

    def test_scheduler_schedule(self):
        from services.outbound.outbound_scheduler import outbound_scheduler
        d = make_draft(provider_id="p1")
        draft_store.create(d)
        result = outbound_scheduler.schedule(d.id, "p1", "2099-01-01T00:00:00Z")
        assert result["ok"] is True
        fetched = draft_store.get(d.id)
        assert fetched.status == DraftStatus.SCHEDULED

    def test_scheduler_cancel_schedule(self):
        from services.outbound.outbound_scheduler import outbound_scheduler
        d = make_draft(provider_id="p1")
        draft_store.create(d)
        outbound_scheduler.schedule(d.id, "p1", "2099-01-01T00:00:00Z")
        cancel = outbound_scheduler.cancel_schedule(d.id, "p1")
        assert cancel["ok"] is True
        fetched = draft_store.get(d.id)
        assert fetched.status == DraftStatus.DRAFT

    def test_scheduler_cancel_nonexistent(self):
        from services.outbound.outbound_scheduler import outbound_scheduler
        result = outbound_scheduler.cancel_schedule("nonexistent", "p1")
        assert result["ok"] is False

    def test_scheduler_cancel_not_scheduled(self):
        from services.outbound.outbound_scheduler import outbound_scheduler
        d = make_draft()
        draft_store.create(d)
        result = outbound_scheduler.cancel_schedule(d.id, "p1")
        assert result["ok"] is False

    def test_scheduler_executes_due_message(self):
        from services.outbound.outbound_scheduler import outbound_scheduler
        past_time = "2020-01-01T00:00:00Z"
        d = make_draft(provider_id="p1")
        draft_store.create(d)
        outbound_scheduler.schedule(d.id, "p1", past_time)
        outbound_scheduler._tick()
        fetched = draft_store.get(d.id)
        assert fetched.status == DraftStatus.SENT

    def test_scheduler_does_not_execute_future_message(self):
        from services.outbound.outbound_scheduler import outbound_scheduler
        future_time = "2099-01-01T00:00:00Z"
        d = make_draft(provider_id="p1")
        draft_store.create(d)
        outbound_scheduler.schedule(d.id, "p1", future_time)
        outbound_scheduler._tick()
        fetched = draft_store.get(d.id)
        assert fetched.status == DraftStatus.SCHEDULED


class TestApprovalCreatesGmailDraft:
    @pytest.fixture(autouse=True)
    def setup_provider(self):
        from services.outbound.outbound_base import OutboundProviderBase
        from services.outbound.outbound_registry import (
            register_outbound_provider, register_instance, remove_instance,
        )
        class MockApprovalProvider(OutboundProviderBase):
            provider_type = "mock_approve_gmail"
            def create_draft(self, draft):
                draft.external_draft_id = "gmail_draft_" + draft.id
                draft.gmail_thread_id = "thread_" + draft.id
                return draft
            def update_draft(self, draft): return draft
            def delete_draft(self, draft_id): return True
            def send(self, request): return SendResult(
                provider_id=request.provider_id,
                external_message_id="msg_" + request.draft_id,
                thread_id="thread_" + request.draft_id,
                status=DeliveryStatus.SENT,
                draft_id=request.draft_id,
            )
            def schedule(self, draft, send_at): return ScheduledMessage(
                provider_id="mock_approve_gmail", subject=draft.subject, body=draft.body,
                recipient=draft.recipient, sender=draft.sender, send_at=send_at,
                draft_id=draft.id)
            def cancel_schedule(self, schedule_id): return True
            def get_status(self, message_id): return "sent"
            def fetch_draft(self, draft_id): return None
            def list_drafts(self): return DraftListResult()
        register_outbound_provider(MockApprovalProvider)
        inst = MockApprovalProvider()
        register_instance("p1", inst)
        yield
        remove_instance("p1")

    def test_approval_creates_gmail_draft(self):
        draft_store.clear()
        reset_events()
        from services.outbound.outbound_registry import create_draft as reg_create_draft
        d = make_draft(provider_id="p1")
        draft_store.create(d)
        draft_store.approve(d.id)
        result = reg_create_draft("p1", d)
        assert result is not None
        assert result.external_draft_id == "gmail_draft_" + d.id
        updated = draft_store.get(d.id)
        if updated:
            updated.external_draft_id = result.external_draft_id
            updated.gmail_thread_id = result.gmail_thread_id
            draft_store.update(updated)
        fetched = draft_store.get(d.id)
        assert fetched.external_draft_id == "gmail_draft_" + d.id

    def test_approve_all_with_mocks(self):
        draft_store.clear()
        reset_events()
        draft_store.create(make_draft(provider_id="p1", subject="Draft 1"))
        draft_store.create(make_draft(provider_id="p1", subject="Draft 2"))
        draft_store.create(make_draft(provider_id="p1", subject="Draft 3"))
        pending = draft_store.list_all()
        assert pending.total == 3
        from services.outbound.outbound_registry import create_draft as reg_create_draft
        results = []
        for d in pending.drafts:
            draft_store.approve(d.id)
            provider_result = reg_create_draft("p1", d)
            if provider_result and provider_result.external_draft_id:
                updated = draft_store.get(d.id)
                if updated:
                    updated.external_draft_id = provider_result.external_draft_id
                    draft_store.update(updated)
                results.append({"draft_id": d.id, "ok": True})
            else:
                results.append({"draft_id": d.id, "ok": False})
        assert len(results) == 3
        assert all(r["ok"] for r in results)
        assert all(draft_store.get(r["draft_id"]).external_draft_id.startswith("gmail_draft_") for r in results)

    def test_send_now_after_approval(self):
        draft_store.clear()
        reset_events()
        from services.outbound.outbound_registry import send as reg_send
        from services.outbound.outbound_executor import OutboundExecutor
        d = make_draft(provider_id="p1")
        draft_store.create(d)
        draft_store.approve(d.id)
        d2 = draft_store.get(d.id)
        from services.outbound.outbound_models import SendRequest
        req = SendRequest(
            provider_id="p1",
            draft_id=d2.id,
            conversation_id=d2.conversation_id,
            thread_id=d2.thread_id,
            workflow_id=d2.workflow_id,
            subject=d2.subject,
            body=d2.body,
            recipient=d2.recipient,
            sender=d2.sender,
            cc=[],
            bcc=[],
        )
        result = reg_send("p1", req)
        assert result is not None
        assert result.status == DeliveryStatus.SENT
        assert result.external_message_id == "msg_" + d.id


class TestFailuresAndErrors:
    @pytest.fixture(autouse=True)
    def setup_provider(self):
        from services.outbound.outbound_base import OutboundProviderBase
        from services.outbound.outbound_registry import (
            register_outbound_provider, register_instance, remove_instance,
        )
        class FailingProvider(OutboundProviderBase):
            provider_type = "failing"
            def create_draft(self, draft):
                raise Exception("Gmail API unavailable")
            def update_draft(self, draft): return draft
            def delete_draft(self, draft_id): return True
            def send(self, request):
                return SendResult(
                    provider_id=request.provider_id,
                    status=DeliveryStatus.FAILED,
                    error="Gmail send rejected",
                )
            def schedule(self, draft, send_at): return ScheduledMessage(
                provider_id="failing", subject="", body="",
                recipient=Recipient(email="a@b.com"), sender=Recipient(email="b@b.com"),
                send_at=send_at)
            def cancel_schedule(self, schedule_id): return True
            def get_status(self, message_id): return "unknown"
            def fetch_draft(self, draft_id): return None
            def list_drafts(self): return DraftListResult()
        register_outbound_provider(FailingProvider)
        inst = FailingProvider()
        register_instance("fail_p1", inst)
        yield
        remove_instance("fail_p1")

    def test_create_draft_failure(self):
        from services.outbound.outbound_registry import create_draft as reg_create_draft
        d = make_draft(provider_id="fail_p1")
        with pytest.raises(Exception, match="Gmail API unavailable"):
            reg_create_draft("fail_p1", d)

    def test_send_failure_persisted(self):
        from services.outbound.outbound_registry import send as reg_send
        from services.outbound.outbound_models import SendRequest
        req = SendRequest(
            provider_id="fail_p1", subject="Fail", body="Fail",
            recipient=Recipient(email="a@b.com"), sender=Recipient(email="b@b.com"),
        )
        result = reg_send("fail_p1", req)
        assert result.status == DeliveryStatus.FAILED
        assert "Gmail send rejected" in result.error
        from services.outbound.outbound_persistence import outbound_persistence
        item = outbound_persistence.record_send(result, subject="Fail", recipient_email="a@b.com")
        assert item.status == DeliveryStatus.FAILED
        assert item.error == "Gmail send rejected"
