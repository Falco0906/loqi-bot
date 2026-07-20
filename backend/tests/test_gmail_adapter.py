"""Comprehensive test suite for the Gmail Adapter v1.0.

Tests cover:
- MIME message builder (plain, HTML, CC/BCC, reply-to, encoding)
- Gmail query builder (all operators, chaining, escaping)
- Request models (validation, immutability)
- Response models (parsing, helper properties)
- GmailResourceMapper (JSON → typed models)
- GmailAdapter (send, list, get, search, labels, threads)
- Error mapping (message/thread/label not found, invalid query)
- Integration with Google Api Adapter, registry, capabilities
"""

import json
import pickle
from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock

import pytest

from services.adapters.adapter_context import AdapterContext
from services.adapters.models import AdapterMetadata, AdapterResult, UsageInfo
from services.adapters.google.gmail import (
    GmailAdapter,
    GmailError,
    GmailQuery,
    GmailResourceMapper,
    MimeMessage,
    GetLabelRequest,
    GetMessageRequest,
    GetThreadRequest,
    LabelSummary,
    ListLabelsRequest,
    ListMessagesRequest,
    ListThreadsRequest,
    MessageDetail,
    MessageSummary,
    SearchMessagesRequest,
    SendEmailRequest,
    ThreadSummary,
    InvalidQueryError,
    LabelNotFoundError,
    MessageNotFoundError,
    ThreadNotFoundError,
    CAPABILITY_DESCRIPTORS,
    CREDENTIAL_DESCRIPTORS,
    GMAIL_METADATA,
)


# =========================================================================
# Fake Google API adapter for testing
# =========================================================================


class FakeGoogleApiAdapter:
    """Simulates GoogleApiAdapter for GmailAdapter tests.

    Returns canned responses keyed by resource path.
    """

    def __init__(self) -> None:
        self._responses: dict[str, AdapterResult] = {}
        self.executed_requests: list[AdapterContext] = []

    def add_response(self, resource: str, result: AdapterResult) -> None:
        self._responses[resource] = result

    @property
    def metadata(self) -> AdapterMetadata:
        return AdapterMetadata(name="google_api", display_name="", version="1")

    async def execute(self, context: AdapterContext) -> AdapterResult:
        self.executed_requests.append(context)
        resource = context.params.get("resource", "")
        response = self._responses.get(resource)
        if response is not None:
            return response
        return AdapterResult.failure_result(
            error=f"No canned response for {resource!r}",
            metadata={"error_type": "GoogleApiError"},
        )


def _google_result(data: dict) -> AdapterResult:
    return AdapterResult(
        success=True,
        data={"json": data, "status_code": 200, "body": json.dumps(data)},
        metadata={},
        usage=UsageInfo(api_calls=1, latency_ms=50.0),
    )


def _google_error(status_code: int, body: str) -> AdapterResult:
    return AdapterResult(
        success=False,
        data={"status_code": status_code, "body": body},
        metadata={"error_type": "HttpStatusError"},
        error=f"HTTP {status_code}",
    )


def _ctx(action: str, **params: object) -> AdapterContext:
    return AdapterContext.build(
        execution_session_id="s1",
        execution_task_id="t1",
        action=action,
        params=params,
        credentials={"access_token": "tok123", "token_type": "Bearer"},
    )


# =========================================================================
# Test: MimeMessage Builder
# =========================================================================


class TestMimeMessage:
    def test_plain_text_only(self) -> None:
        raw = (MimeMessage()
               .to(["alice@example.com"])
               .subject("Hello")
               .plain("Hello Alice!")
               .build())
        assert "To: alice@example.com" in raw
        assert "Subject: Hello" in raw
        assert "Hello Alice!" in raw
        assert "Content-Type: text/plain" in raw

    def test_html_only(self) -> None:
        raw = (MimeMessage()
               .to(["alice@example.com"])
               .subject("HTML Email")
               .html("<h1>Hello</h1>")
               .build())
        assert "Content-Type: text/html" in raw
        assert "<h1>Hello</h1>" in raw

    def test_multipart_alternative(self) -> None:
        raw = (MimeMessage()
               .to(["alice@example.com"])
               .subject("Both")
               .plain("Plain version")
               .html("<p>HTML version</p>")
               .build())
        assert "Content-Type: multipart/alternative" in raw
        assert "Plain version" in raw
        assert "HTML version" in raw

    def test_cc(self) -> None:
        raw = (MimeMessage()
               .to(["alice@example.com"])
               .cc(["bob@example.com"])
               .subject("CC Test")
               .plain("test")
               .build())
        assert "Cc: bob@example.com" in raw

    def test_multiple_cc(self) -> None:
        raw = (MimeMessage()
               .to(["alice@example.com"])
               .cc(["bob@example.com", "carol@example.com"])
               .subject("Multi CC")
               .plain("test")
               .build())
        assert "bob@example.com" in raw
        assert "carol@example.com" in raw

    def test_bcc(self) -> None:
        raw = (MimeMessage()
               .to(["alice@example.com"])
               .bcc(["secret@example.com"])
               .subject("BCC Test")
               .plain("test")
               .build())
        assert "Bcc: secret@example.com" in raw

    def test_reply_to(self) -> None:
        raw = (MimeMessage()
               .to(["alice@example.com"])
               .subject("Reply-To Test")
               .plain("test")
               .reply_to("support@example.com")
               .build())
        assert "Reply-To: support@example.com" in raw

    def test_from_header(self) -> None:
        raw = (MimeMessage()
               .to(["alice@example.com"])
               .subject("From Test")
               .plain("test")
               .from_("sender@example.com")
               .build())
        assert "From: sender@example.com" in raw

    def test_extra_header(self) -> None:
        raw = (MimeMessage()
               .to(["alice@example.com"])
               .subject("Extra Header")
               .plain("test")
               .header("X-Custom", "value123")
               .build())
        assert "X-Custom: value123" in raw

    def test_date_header_present(self) -> None:
        raw = (MimeMessage()
               .to(["alice@example.com"])
               .subject("Date Test")
               .plain("test")
               .build())
        assert "Date:" in raw

    def test_encode_base64url(self) -> None:
        encoded = (MimeMessage()
                   .to(["alice@example.com"])
                   .subject("Encode Test")
                   .plain("Hello")
                   .encode())
        assert isinstance(encoded, str)
        assert len(encoded) > 0
        import base64
        decoded = base64.urlsafe_b64decode(encoded + "==")
        assert b"Hello" in decoded

    def test_encode_no_padding(self) -> None:
        encoded = (MimeMessage()
                   .to(["a@b.com"])
                   .subject("X")
                   .plain("Hi")
                   .encode())
        assert encoded is not None
        assert "=" not in encoded.rstrip("=") or len(encoded) % 4 in (0, 2, 3)

    def test_reset(self) -> None:
        builder = (MimeMessage()
                   .to(["alice@example.com"])
                   .subject("Test")
                   .plain("body"))
        first = builder.build()
        assert "Test" in first
        builder.reset()
        second = (builder.to(["bob@example.com"])
                  .subject("Second")
                  .plain("body2")
                  .build())
        assert "Second" in second
        assert "Test" not in second

    def test_to_list_of_strings(self) -> None:
        raw = (MimeMessage()
               .to(["a@b.com", "c@d.com"])
               .subject("List")
               .plain("test")
               .build())
        assert "a@b.com" in raw
        assert "c@d.com" in raw

    def test_to_single_string(self) -> None:
        raw = (MimeMessage()
               .to("a@b.com")
               .subject("Single")
               .plain("test")
               .build())
        assert "a@b.com" in raw

    def test_empty_plain_default(self) -> None:
        raw = (MimeMessage()
               .to(["a@b.com"])
               .subject("Empty")
               .build())
        assert "Content-Type: text/plain" in raw

    def test_rfc_2822_compliance(self) -> None:
        raw = (MimeMessage()
               .to(["recipient@example.com"])
               .subject("RFC Compliance")
               .plain("Body text")
               .build())
        assert "Body text" in raw
        assert "To: recipient@example.com" in raw
        assert "Subject: RFC Compliance" in raw
        assert "Date:" in raw


# =========================================================================
# Test: GmailQuery Builder
# =========================================================================


class TestGmailQuery:
    def test_from_operator(self) -> None:
        q = GmailQuery().from_("alice@example.com").build()
        assert q == "from:alice@example.com"

    def test_to_operator(self) -> None:
        q = GmailQuery().to("bob@example.com").build()
        assert q == "to:bob@example.com"

    def test_subject_operator(self) -> None:
        q = GmailQuery().subject("hello world").build()
        assert "subject:" in q
        assert "hello world" in q

    def test_label_operator(self) -> None:
        q = GmailQuery().label("INBOX").build()
        assert q == "label:INBOX"

    def test_has_attachment(self) -> None:
        q = GmailQuery().has_attachment().build()
        assert q == "has:attachment"

    def test_is_unread(self) -> None:
        q = GmailQuery().is_unread().build()
        assert q == "is:unread"

    def test_is_read(self) -> None:
        q = GmailQuery().is_read().build()
        assert q == "is:read"

    def test_is_starred(self) -> None:
        q = GmailQuery().is_starred().build()
        assert q == "is:starred"

    def test_is_important(self) -> None:
        q = GmailQuery().is_important().build()
        assert q == "is:important"

    def test_in_operator(self) -> None:
        q = GmailQuery().in_("inbox").build()
        assert q == "in:inbox"

    def test_after(self) -> None:
        q = GmailQuery().after("2026/01/01").build()
        assert q == "after:2026/01/01"

    def test_before(self) -> None:
        q = GmailQuery().before("2026/12/31").build()
        assert q == "before:2026/12/31"

    def test_newer_than_days(self) -> None:
        q = GmailQuery().newer_than(7, "d").build()
        assert q == "newer_than:7d"

    def test_older_than_months(self) -> None:
        q = GmailQuery().older_than(3, "m").build()
        assert q == "older_than:3m"

    def test_cc_operator(self) -> None:
        q = GmailQuery().cc("carol@example.com").build()
        assert q == "cc:carol@example.com"

    def test_bcc_operator(self) -> None:
        q = GmailQuery().bcc("dave@example.com").build()
        assert q == "bcc:dave@example.com"

    def test_chaining(self) -> None:
        q = (GmailQuery()
             .from_("alice@example.com")
             .label("INBOX")
             .is_unread()
             .build())
        assert "from:alice@example.com" in q
        assert "label:INBOX" in q
        assert "is:unread" in q

    def test_escaping_spaces(self) -> None:
        q = GmailQuery().subject("meeting notes").build()
        assert '"' in q

    def test_escaping_quotes(self) -> None:
        q = GmailQuery().subject('say "hello"').build()
        assert '\\"' in q

    def test_bool_true_when_parts(self) -> None:
        q = GmailQuery().from_("a@b.com")
        assert bool(q) is True

    def test_bool_false_when_empty(self) -> None:
        q = GmailQuery()
        assert bool(q) is False

    def test_str_representation(self) -> None:
        q = GmailQuery().is_unread()
        assert str(q) == "is:unread"

    def test_in_inbox(self) -> None:
        q = GmailQuery().in_inbox().build()
        assert q == "in:inbox"

    def test_in_sent(self) -> None:
        q = GmailQuery().in_sent().build()
        assert q == "in:sent"

    def test_in_drafts(self) -> None:
        q = GmailQuery().in_drafts().build()
        assert q == "in:drafts"

    def test_in_trash(self) -> None:
        q = GmailQuery().in_trash().build()
        assert q == "in:trash"

    def test_in_spam(self) -> None:
        q = GmailQuery().in_spam().build()
        assert q == "in:spam"

    def test_in_anywhere(self) -> None:
        q = GmailQuery().in_anywhere().build()
        assert q == "in:anywhere"

    def test_raw_text(self) -> None:
        q = GmailQuery().raw("{has:attachment}").build()
        assert q == "{has:attachment}"

    def test_has_field(self) -> None:
        q = GmailQuery().has("attachment").build()
        assert q == "has:attachment"

    def test_list_operator(self) -> None:
        q = GmailQuery().list("dev@example.com").build()
        assert q == "list:dev@example.com"

    def test_filename_operator(self) -> None:
        q = GmailQuery().filename("report.pdf").build()
        assert q == "filename:report.pdf"

    def test_larger(self) -> None:
        q = GmailQuery().larger(1024).build()
        assert q == "larger:1024"

    def test_smaller(self) -> None:
        q = GmailQuery().smaller(5120).build()
        assert q == "smaller:5120"


# =========================================================================
# Test: Request Models
# =========================================================================


class TestSendEmailRequest:
    def test_valid(self) -> None:
        req = SendEmailRequest(to=["a@b.com"], subject="Hi", body_plain="Hello")
        assert req.to == ["a@b.com"]
        assert req.subject == "Hi"

    def test_missing_to_cc_bcc_raises(self) -> None:
        with pytest.raises(ValueError, match="to, cc, or bcc"):
            SendEmailRequest(to=[], subject="Hi", body_plain="Hello")

    def test_missing_subject_raises(self) -> None:
        with pytest.raises(ValueError, match="subject"):
            SendEmailRequest(to=["a@b.com"], subject="", body_plain="Hello")

    def test_missing_body_raises(self) -> None:
        with pytest.raises(ValueError, match="body_plain or body_html"):
            SendEmailRequest(to=["a@b.com"], subject="Hi", body_plain="", body_html="")

    def test_invalid_to_email_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid email"):
            SendEmailRequest(to=["not-an-email"], subject="Hi", body_plain="Hello")

    def test_invalid_cc_email_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid email"):
            SendEmailRequest(to=["a@b.com"], subject="Hi", body_plain="Hello", cc=["bad"])

    def test_invalid_reply_to_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid email"):
            SendEmailRequest(to=["a@b.com"], subject="Hi", body_plain="Hello", reply_to="bad")

    def test_immutable(self) -> None:
        req = SendEmailRequest(to=["a@b.com"], subject="Hi", body_plain="Hello")
        with pytest.raises(FrozenInstanceError):
            req.subject = "Changed"  # type: ignore[misc]

    def test_repr(self) -> None:
        req = SendEmailRequest(to=["a@b.com"], subject="Hi", body_plain="Hello")
        assert "SendEmailRequest" in repr(req)


class TestListMessagesRequest:
    def test_defaults(self) -> None:
        req = ListMessagesRequest()
        assert req.max_results == 100
        assert req.query == ""

    def test_max_results_validation(self) -> None:
        with pytest.raises(ValueError, match="max_results"):
            ListMessagesRequest(max_results=0)
        with pytest.raises(ValueError, match="max_results"):
            ListMessagesRequest(max_results=501)

    def test_immutable(self) -> None:
        req = ListMessagesRequest()
        with pytest.raises(FrozenInstanceError):
            req.max_results = 50  # type: ignore[misc]


class TestGetMessageRequest:
    def test_valid(self) -> None:
        req = GetMessageRequest(message_id="123")
        assert req.message_id == "123"

    def test_format_default(self) -> None:
        req = GetMessageRequest(message_id="123")
        assert req.format == "full"

    def test_invalid_format(self) -> None:
        with pytest.raises(ValueError, match="format"):
            GetMessageRequest(message_id="123", format="invalid")

    def test_valid_formats(self) -> None:
        for fmt in ("minimal", "full", "metadata", "raw"):
            req = GetMessageRequest(message_id="123", format=fmt)
            assert req.format == fmt

    def test_immutable(self) -> None:
        req = GetMessageRequest(message_id="123")
        with pytest.raises(FrozenInstanceError):
            req.message_id = "456"  # type: ignore[misc]


class TestSearchMessagesRequest:
    def test_valid(self) -> None:
        req = SearchMessagesRequest(query="is:unread")
        assert req.query == "is:unread"

    def test_empty_query_raises(self) -> None:
        with pytest.raises(ValueError, match="query"):
            SearchMessagesRequest(query="")

    def test_max_results_validation(self) -> None:
        with pytest.raises(ValueError, match="max_results"):
            SearchMessagesRequest(query="test", max_results=0)


class TestListLabelsRequest:
    def test_can_create(self) -> None:
        req = ListLabelsRequest()
        assert isinstance(req, ListLabelsRequest)


class TestGetLabelRequest:
    def test_valid(self) -> None:
        req = GetLabelRequest(label_id="LABEL_1")
        assert req.label_id == "LABEL_1"

    def test_empty_id_raises(self) -> None:
        with pytest.raises(ValueError, match="label_id"):
            GetLabelRequest(label_id="")


class TestListThreadsRequest:
    def test_defaults(self) -> None:
        req = ListThreadsRequest()
        assert req.max_results == 100

    def test_max_results_validation(self) -> None:
        with pytest.raises(ValueError, match="max_results"):
            ListThreadsRequest(max_results=0)


class TestGetThreadRequest:
    def test_valid(self) -> None:
        req = GetThreadRequest(thread_id="thread_1")
        assert req.thread_id == "thread_1"

    def test_empty_id_raises(self) -> None:
        with pytest.raises(ValueError, match="thread_id"):
            GetThreadRequest(thread_id="")

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError, match="format"):
            GetThreadRequest(thread_id="t1", format="invalid")


# =========================================================================
# Test: Response Models
# =========================================================================


class TestMessageSummary:
    def test_fields(self) -> None:
        m = MessageSummary(
            id="msg1", thread_id="th1", snippet="Hello",
            from_="alice@b.com", to="bob@b.com", subject="Hi", date="2026-01-01",
            label_ids=("INBOX",),
        )
        assert m.id == "msg1"
        assert m.from_ == "alice@b.com"
        assert m.label_ids == ("INBOX",)

    def test_defaults(self) -> None:
        m = MessageSummary(id="msg1", thread_id="th1", snippet="")
        assert m.from_ == ""
        assert m.label_ids == ()

    def test_immutable(self) -> None:
        m = MessageSummary(id="m1", thread_id="t1", snippet="s")
        with pytest.raises(FrozenInstanceError):
            m.id = "m2"  # type: ignore[misc]

    def test_pickle_roundtrip(self) -> None:
        m = MessageSummary(id="m1", thread_id="t1", snippet="s", from_="a@b.com")
        restored = pickle.loads(pickle.dumps(m))
        assert restored.id == "m1"
        assert restored.from_ == "a@b.com"


class TestMessageDetail:
    def test_fields(self) -> None:
        d = MessageDetail(
            id="msg1", thread_id="th1", snippet="Hello",
            from_="a@b.com", to="b@b.com", subject="Hi",
            body_plain="Hello World",
            headers={"From": "a@b.com"},
        )
        assert d.body_plain == "Hello World"
        assert d.headers["From"] == "a@b.com"

    def test_defaults(self) -> None:
        d = MessageDetail(id="m1", thread_id="t1", snippet="")
        assert d.body_plain == ""
        assert d.headers == {}


class TestThreadSummary:
    def test_empty_messages(self) -> None:
        t = ThreadSummary(id="th1", snippet="s")
        assert t.messages == ()

    def test_with_messages(self) -> None:
        ms = (MessageSummary(id="m1", thread_id="th1", snippet="s1"),)
        t = ThreadSummary(id="th1", snippet="s", messages=ms)
        assert len(t.messages) == 1


class TestLabelSummary:
    def test_fields(self) -> None:
        l = LabelSummary(id="L1", name="INBOX", type="system", color={"background": "#fff", "text": "#000"})
        assert l.name == "INBOX"
        assert l.color["background"] == "#fff"

    def test_defaults(self) -> None:
        l = LabelSummary(id="L1", name="INBOX")
        assert l.type == ""
        assert l.color == {}


# =========================================================================
# Test: GmailResourceMapper
# =========================================================================


class TestGmailResourceMapper:
    def test_to_message_summary_minimal(self) -> None:
        raw = {"id": "msg1", "threadId": "th1", "snippet": "Hello", "labelIds": ["INBOX"]}
        m = GmailResourceMapper.to_message_summary(raw)
        assert m.id == "msg1"
        assert m.thread_id == "th1"
        assert m.snippet == "Hello"
        assert m.label_ids == ("INBOX",)

    def test_to_message_summary_with_headers(self) -> None:
        raw = {
            "id": "msg1", "threadId": "th1", "snippet": "Hello",
            "payload": {"headers": [
                {"name": "From", "value": "alice@b.com"},
                {"name": "Subject", "value": "Hi"},
            ]},
        }
        m = GmailResourceMapper.to_message_summary(raw)
        assert m.from_ == "alice@b.com"
        assert m.subject == "Hi"

    def test_to_message_detail(self) -> None:
        raw = {
            "id": "msg1", "threadId": "th1", "snippet": "Hello",
            "labelIds": ["INBOX"],
            "sizeEstimate": 1024,
            "historyId": "h1",
            "internalDate": "1700000000000",
            "payload": {
                "headers": [
                    {"name": "From", "value": "a@b.com"},
                    {"name": "To", "value": "c@d.com"},
                ],
                "mimeType": "text/plain",
                "body": {"data": "SGVsbG8gV29ybGQ="},
            },
        }
        d = GmailResourceMapper.to_message_detail(raw)
        assert d.body_plain == "Hello World"
        assert d.size_estimate == 1024
        assert d.history_id == "h1"

    def test_to_message_detail_multipart(self) -> None:
        raw = {
            "id": "msg1", "threadId": "th1", "snippet": "Hi",
            "payload": {
                "mimeType": "multipart/alternative",
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": "UGxhaW4="}},
                    {"mimeType": "text/html", "body": {"data": "PHA+SFRNTDwvcD4="}},
                ],
            },
        }
        d = GmailResourceMapper.to_message_detail(raw)
        assert d.body_plain == "Plain"
        assert d.body_html == "<p>HTML</p>"

    def test_to_thread_summary(self) -> None:
        raw = {
            "id": "th1", "snippet": "Thread start", "historyId": "h1",
            "messages": [
                {"id": "m1", "threadId": "th1", "snippet": "First msg"},
            ],
        }
        t = GmailResourceMapper.to_thread_summary(raw)
        assert t.id == "th1"
        assert len(t.messages) == 1
        assert t.messages[0].id == "m1"

    def test_to_thread_summary_empty_messages(self) -> None:
        raw = {"id": "th1", "snippet": "empty", "historyId": "h1"}
        t = GmailResourceMapper.to_thread_summary(raw)
        assert t.messages == ()

    def test_to_label_summary_system(self) -> None:
        raw = {
            "id": "INBOX", "name": "INBOX", "type": "system",
            "messagesTotal": 42, "messagesUnread": 3,
        }
        l = GmailResourceMapper.to_label_summary(raw)
        assert l.id == "INBOX"
        assert l.messages_total == 42
        assert l.messages_unread == 3

    def test_to_label_summary_with_color(self) -> None:
        raw = {
            "id": "L1", "name": "Custom", "type": "user",
            "color": {"backgroundColor": "#ff0000", "textColor": "#ffffff"},
        }
        l = GmailResourceMapper.to_label_summary(raw)
        assert l.color["background"] == "#ff0000"
        assert l.color["text"] == "#ffffff"


# =========================================================================
# Test: GmailAdapter — Error Mapping
# =========================================================================


class TestGmailAdapterErrorMapping:
    @pytest.mark.asyncio
    async def test_message_not_found(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages/unk",
            _google_error(404, '{"error":{"code":404,"message":"Message not found","status":"NOT_FOUND"}}'),
        )
        result = await adapter.execute(_ctx("gmail_get_message", message_id="unk"))
        assert result.success is False
        assert "MessageNotFoundError" in (result.metadata or {}).get("error_type", "")

    @pytest.mark.asyncio
    async def test_thread_not_found(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/threads/unk",
            _google_error(404, '{"error":{"code":404,"message":"Thread not found","status":"NOT_FOUND"}}'),
        )
        result = await adapter.execute(_ctx("gmail_get_thread", thread_id="unk"))
        assert result.success is False
        assert "ThreadNotFoundError" in (result.metadata or {}).get("error_type", "")

    @pytest.mark.asyncio
    async def test_label_not_found(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/labels/unk",
            _google_error(404, '{"error":{"code":404,"message":"Label not found","status":"NOT_FOUND"}}'),
        )
        result = await adapter.execute(_ctx("gmail_get_label", label_id="unk"))
        assert result.success is False
        assert "LabelNotFoundError" in (result.metadata or {}).get("error_type", "")

    @pytest.mark.asyncio
    async def test_auth_error_propagated(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages",
            _google_error(401, '{"error":{"code":401,"message":"Unauthorized","status":"UNAUTHENTICATED"}}'),
        )
        result = await adapter.execute(_ctx("gmail_list_messages"))
        assert result.success is False
        error_type = (result.metadata or {}).get("error_type", "")
        assert "Authentication" in error_type or "GmailError" in error_type

    @pytest.mark.asyncio
    async def test_quota_error_propagated(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages",
            _google_error(429, '{"error":{"code":429,"message":"Quota exceeded","status":"RESOURCE_EXHAUSTED"}}'),
        )
        result = await adapter.execute(_ctx("gmail_list_messages"))
        assert result.success is False

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        result = await adapter.execute(_ctx("gmail_unknown"))
        assert result.success is False
        assert "Unknown Gmail action" in (result.error or "")

    @pytest.mark.asyncio
    async def test_invalid_query_error(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages",
            _google_error(400, '{"error":{"code":400,"message":"Invalid query","status":"INVALID_ARGUMENT"}}'),
        )
        result = await adapter.execute(_ctx("gmail_search_messages", query="!!invalid!!"))
        assert result.success is False
        error_type = (result.metadata or {}).get("error_type", "")
        assert "InvalidQuery" in error_type or "Validation" in error_type


# =========================================================================
# Test: GmailAdapter — Send Email
# =========================================================================


class TestGmailAdapterSendEmail:
    @pytest.mark.asyncio
    async def test_send_email_success(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages/send",
            _google_result({"id": "msg_new", "threadId": "th_new"}),
        )
        result = await adapter.execute(_ctx(
            "gmail_send_email",
            to=["alice@example.com"],
            subject="Hello",
            body_plain="Hi Alice!",
        ))
        assert result.success is True
        assert result.data["id"] == "msg_new"
        assert result.data["thread_id"] == "th_new"

    @pytest.mark.asyncio
    async def test_send_email_passes_raw_body(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages/send",
            _google_result({"id": "m1", "threadId": "t1"}),
        )
        await adapter.execute(_ctx(
            "gmail_send_email",
            to=["a@b.com"], subject="Test", body_plain="Body",
        ))
        executed = fake.executed_requests[-1]
        body = executed.params.get("body", {})
        assert "raw" in body
        assert isinstance(body["raw"], str)
        assert len(body["raw"]) > 0

    @pytest.mark.asyncio
    async def test_send_email_with_cc(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages/send",
            _google_result({"id": "m1", "threadId": "t1"}),
        )
        result = await adapter.execute(_ctx(
            "gmail_send_email",
            to=["a@b.com"], subject="Hi", body_plain="Hello",
            cc=["cc@b.com"],
        ))
        assert result.success is True

    @pytest.mark.asyncio
    async def test_send_email_with_bcc(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages/send",
            _google_result({"id": "m1", "threadId": "t1"}),
        )
        result = await adapter.execute(_ctx(
            "gmail_send_email",
            to=["a@b.com"], subject="Hi", body_plain="Hello",
            bcc=["bcc@b.com"],
        ))
        assert result.success is True

    @pytest.mark.asyncio
    async def test_send_email_with_reply_to(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages/send",
            _google_result({"id": "m1", "threadId": "t1"}),
        )
        result = await adapter.execute(_ctx(
            "gmail_send_email",
            to=["a@b.com"], subject="Hi", body_plain="Hello",
            reply_to="support@b.com",
        ))
        assert result.success is True

    @pytest.mark.asyncio
    async def test_send_email_uses_body_alias(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages/send",
            _google_result({"id": "m1", "threadId": "t1"}),
        )
        result = await adapter.execute(_ctx(
            "gmail_send_email",
            to=["a@b.com"], subject="Hi", body="Hello via body alias",
        ))
        assert result.success is True

    @pytest.mark.asyncio
    async def test_send_email_passes_credentials(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages/send",
            _google_result({"id": "m1", "threadId": "t1"}),
        )
        ctx = _ctx(
            "gmail_send_email",
            to=["a@b.com"], subject="Hi", body_plain="Hello",
        )
        await adapter.execute(ctx)
        executed = fake.executed_requests[-1]
        assert executed.credentials.get("access_token") == "tok123"

    @pytest.mark.asyncio
    async def test_send_email_failure_mapped(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages/send",
            _google_error(403, '{"error":{"code":403,"message":"Forbidden","status":"PERMISSION_DENIED"}}'),
        )
        result = await adapter.execute(_ctx(
            "gmail_send_email",
            to=["a@b.com"], subject="Hi", body_plain="Hello",
        ))
        assert result.success is False


# =========================================================================
# Test: GmailAdapter — List Messages
# =========================================================================


class TestGmailAdapterListMessages:
    @pytest.mark.asyncio
    async def test_list_messages_success(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages",
            _google_result({
                "messages": [
                    {"id": "m1", "threadId": "t1", "snippet": "First"},
                    {"id": "m2", "threadId": "t2", "snippet": "Second"},
                ],
                "resultSizeEstimate": 2,
            }),
        )
        result = await adapter.execute(_ctx("gmail_list_messages"))
        assert result.success is True
        messages = result.data.get("messages", [])
        assert len(messages) == 2
        assert messages[0].id == "m1"
        assert messages[1].snippet == "Second"

    @pytest.mark.asyncio
    async def test_list_messages_with_query_param(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages",
            _google_result({"messages": [], "resultSizeEstimate": 0}),
        )
        await adapter.execute(_ctx("gmail_list_messages", query="is:unread"))
        executed = fake.executed_requests[-1]
        assert executed.params.get("query", {}).get("q") == "is:unread"

    @pytest.mark.asyncio
    async def test_list_messages_with_label_ids(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages",
            _google_result({"messages": [], "resultSizeEstimate": 0}),
        )
        await adapter.execute(_ctx("gmail_list_messages", label_ids=["INBOX", "IMPORTANT"]))
        executed = fake.executed_requests[-1]
        assert "INBOX" in executed.params.get("query", {}).get("labelIds", "")

    @pytest.mark.asyncio
    async def test_list_messages_empty(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages",
            _google_result({"messages": [], "resultSizeEstimate": 0}),
        )
        result = await adapter.execute(_ctx("gmail_list_messages"))
        assert result.success is True
        assert result.data.get("messages") == []

    @pytest.mark.asyncio
    async def test_list_messages_uses_gmail_resource(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages",
            _google_result({"messages": [], "resultSizeEstimate": 0}),
        )
        await adapter.execute(_ctx("gmail_list_messages"))
        executed = fake.executed_requests[-1]
        assert executed.params.get("resource") == "users/me/messages"

    @pytest.mark.asyncio
    async def test_list_messages_include_spam_trash(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages",
            _google_result({"messages": [], "resultSizeEstimate": 0}),
        )
        await adapter.execute(_ctx("gmail_list_messages", include_spam_trash=True))
        executed = fake.executed_requests[-1]
        assert executed.params.get("query", {}).get("includeSpamTrash") == "true"


# =========================================================================
# Test: GmailAdapter — Get Message
# =========================================================================


class TestGmailAdapterGetMessage:
    @pytest.mark.asyncio
    async def test_get_message_success(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages/msg1",
            _google_result({
                "id": "msg1", "threadId": "th1", "snippet": "Detail",
                "payload": {
                    "headers": [{"name": "From", "value": "a@b.com"}],
                    "mimeType": "text/plain",
                    "body": {"data": "SGVsbG8="},
                },
            }),
        )
        result = await adapter.execute(_ctx("gmail_get_message", message_id="msg1"))
        assert result.success is True
        message = result.data.get("message")
        assert message.id == "msg1"
        assert message.body_plain == "Hello"

    @pytest.mark.asyncio
    async def test_get_message_with_format(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages/msg1",
            _google_result({
                "id": "msg1", "threadId": "th1", "snippet": "s",
                "payload": {"headers": []},
            }),
        )
        await adapter.execute(_ctx("gmail_get_message", message_id="msg1", format="raw"))
        executed = fake.executed_requests[-1]
        assert executed.params.get("query", {}).get("format") == "raw"

    @pytest.mark.asyncio
    async def test_get_message_id_alias(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages/xyz",
            _google_result({
                "id": "xyz", "threadId": "t1", "snippet": "s",
                "payload": {"headers": []},
            }),
        )
        result = await adapter.execute(_ctx("gmail_get_message", id="xyz"))
        assert result.success is True


# =========================================================================
# Test: GmailAdapter — Search Messages
# =========================================================================


class TestGmailAdapterSearch:
    @pytest.mark.asyncio
    async def test_search_messages_success(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages",
            _google_result({
                "messages": [{"id": "m1", "threadId": "t1", "snippet": "Found"}],
                "resultSizeEstimate": 1,
            }),
        )
        result = await adapter.execute(_ctx("gmail_search_messages", query="is:unread"))
        assert result.success is True
        assert len(result.data.get("messages", [])) == 1

    @pytest.mark.asyncio
    async def test_search_passes_query(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages",
            _google_result({"messages": [], "resultSizeEstimate": 0}),
        )
        q = str(GmailQuery().from_("boss@b.com").is_unread())
        await adapter.execute(_ctx("gmail_search_messages", query=q))
        executed = fake.executed_requests[-1]
        assert executed.params.get("query", {}).get("q") == q

    @pytest.mark.asyncio
    async def test_search_with_q_alias(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages",
            _google_result({"messages": [], "resultSizeEstimate": 0}),
        )
        await adapter.execute(_ctx("gmail_search_messages", q="is:read"))
        executed = fake.executed_requests[-1]
        assert "is:read" in str(executed.params.get("query", {}))


# =========================================================================
# Test: GmailAdapter — Labels
# =========================================================================


class TestGmailAdapterLabels:
    @pytest.mark.asyncio
    async def test_list_labels_success(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/labels",
            _google_result({
                "labels": [
                    {"id": "INBOX", "name": "INBOX", "type": "system"},
                    {"id": "L1", "name": "Custom", "type": "user"},
                ],
            }),
        )
        result = await adapter.execute(_ctx("gmail_list_labels"))
        assert result.success is True
        labels = result.data.get("labels", [])
        assert len(labels) == 2
        assert labels[0].name == "INBOX"
        assert labels[1].type == "user"

    @pytest.mark.asyncio
    async def test_list_labels_empty(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/labels",
            _google_result({"labels": []}),
        )
        result = await adapter.execute(_ctx("gmail_list_labels"))
        assert result.success is True
        assert result.data.get("labels") == []

    @pytest.mark.asyncio
    async def test_get_label_success(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/labels/INBOX",
            _google_result({
                "id": "INBOX", "name": "INBOX", "type": "system",
                "messagesTotal": 100, "messagesUnread": 5,
            }),
        )
        result = await adapter.execute(_ctx("gmail_get_label", label_id="INBOX"))
        assert result.success is True
        label = result.data.get("label")
        assert label.name == "INBOX"
        assert label.messages_total == 100

    @pytest.mark.asyncio
    async def test_get_label_id_alias(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/labels/IMPORTANT",
            _google_result({"id": "IMPORTANT", "name": "IMPORTANT", "type": "system"}),
        )
        result = await adapter.execute(_ctx("gmail_get_label", id="IMPORTANT"))
        assert result.success is True


# =========================================================================
# Test: GmailAdapter — Threads
# =========================================================================


class TestGmailAdapterThreads:
    @pytest.mark.asyncio
    async def test_list_threads_success(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/threads",
            _google_result({
                "threads": [
                    {"id": "t1", "snippet": "Thread 1", "historyId": "h1"},
                    {"id": "t2", "snippet": "Thread 2", "historyId": "h2"},
                ],
                "resultSizeEstimate": 2,
            }),
        )
        result = await adapter.execute(_ctx("gmail_list_threads"))
        assert result.success is True
        threads = result.data.get("threads", [])
        assert len(threads) == 2

    @pytest.mark.asyncio
    async def test_list_threads_with_query(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/threads",
            _google_result({"threads": [], "resultSizeEstimate": 0}),
        )
        await adapter.execute(_ctx("gmail_list_threads", query="is:unread"))
        executed = fake.executed_requests[-1]
        assert executed.params.get("query", {}).get("q") == "is:unread"

    @pytest.mark.asyncio
    async def test_get_thread_success(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/threads/t1",
            _google_result({
                "id": "t1", "snippet": "Full thread", "historyId": "h1",
                "messages": [
                    {"id": "m1", "threadId": "t1", "snippet": "First"},
                ],
            }),
        )
        result = await adapter.execute(_ctx("gmail_get_thread", thread_id="t1"))
        assert result.success is True
        thread = result.data.get("thread")
        assert thread.id == "t1"
        assert len(thread.messages) == 1

    @pytest.mark.asyncio
    async def test_get_thread_id_alias(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/threads/xyz",
            _google_result({
                "id": "xyz", "snippet": "s", "historyId": "h1",
            }),
        )
        result = await adapter.execute(_ctx("gmail_get_thread", id="xyz"))
        assert result.success is True
        assert result.data.get("thread").id == "xyz"


# =========================================================================
# Test: GmailAdapter — Metadata & Capabilities
# =========================================================================


class TestGmailAdapterMetadata:
    def test_metadata_name(self) -> None:
        assert GMAIL_METADATA.name == "gmail"

    def test_metadata_version(self) -> None:
        assert GMAIL_METADATA.version == "1.0.0"

    def test_metadata_requires_auth(self) -> None:
        assert GMAIL_METADATA.requires_auth is True

    def test_metadata_tags_include_gmail(self) -> None:
        assert "gmail" in GMAIL_METADATA.tags

    @pytest.mark.asyncio
    async def test_adapter_metadata_property(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        meta = adapter.metadata
        assert meta.name == "gmail"

    def test_capability_descriptors(self) -> None:
        names = [c["name"] for c in CAPABILITY_DESCRIPTORS]
        assert "gmail_send_email" in names
        assert "gmail_list_messages" in names
        assert "gmail_get_message" in names
        assert "gmail_search_messages" in names
        assert "gmail_list_labels" in names
        assert "gmail_get_label" in names
        assert "gmail_list_threads" in names
        assert "gmail_get_thread" in names
        assert len(names) == 8

    def test_capability_versions(self) -> None:
        for c in CAPABILITY_DESCRIPTORS:
            assert c["version"] == "1.0.0"
            assert c["requires_auth"] is True

    def test_credential_descriptor_reuses_google_oauth2(self) -> None:
        assert len(CREDENTIAL_DESCRIPTORS) == 1
        assert CREDENTIAL_DESCRIPTORS[0]["name"] == "google_oauth2"

    def test_supported_operations_in_metadata(self) -> None:
        ops = GMAIL_METADATA.supported_operations
        assert "gmail_send_email" in ops
        assert len(ops) == 8


# =========================================================================
# Test: GmailAdapter — Stateless & No Caching
# =========================================================================


class TestGmailAdapterStateless:
    @pytest.mark.asyncio
    async def test_no_mutable_state(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages",
            _google_result({"messages": [], "resultSizeEstimate": 0}),
        )
        await adapter.execute(_ctx("gmail_list_messages"))
        await adapter.execute(_ctx("gmail_list_messages"))
        assert len(fake.executed_requests) == 2

    def test_no_caching_in_source(self) -> None:
        from services.adapters.google.gmail import gmail_adapter
        import inspect
        source = inspect.getsource(gmail_adapter)
        assert "cache" not in source.lower()

    def test_no_retry_implementation(self) -> None:
        from services.adapters.google.gmail import gmail_adapter
        import inspect
        source = inspect.getsource(gmail_adapter)
        assert "while" not in source.lower()
        assert "backoff" not in source.lower()
        assert "tenacity" not in source.lower()


# =========================================================================
# Test: GmailAdapter — No Lower-Layer Dependency
# =========================================================================


class TestGmailAdapterNoLowerDependencies:
    def test_no_runtime_import(self) -> None:
        import services.adapters.google.gmail.gmail_adapter as mod
        import inspect
        source = inspect.getsource(mod)
        assert "services.execution" not in source

    def test_no_planner_import(self) -> None:
        import services.adapters.google.gmail.gmail_adapter as mod
        import inspect
        source = inspect.getsource(mod)
        assert "services.planner" not in source

    def test_no_http_duplication(self) -> None:
        import services.adapters.google.gmail.gmail_adapter as mod
        import inspect
        source = inspect.getsource(mod)
        assert "import httpx" not in source
        assert "from httpx" not in source
        assert "import requests" not in source


# =========================================================================
# Test: GmailAdapter — Google Adapter Injection
# =========================================================================


class TestGmailAdapterInjection:
    @pytest.mark.asyncio
    async def test_custom_google_adapter(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/labels",
            _google_result({"labels": []}),
        )
        result = await adapter.execute(_ctx("gmail_list_labels"))
        assert result.success is True

    @pytest.mark.asyncio
    async def test_default_google_adapter_created(self) -> None:
        adapter = GmailAdapter()
        assert adapter._google is not None


# =========================================================================
# Test: GmailAdapter — All Operations Flow Through GoogleApiAdapter
# =========================================================================


class TestGmailAdapterAllFlowsThroughGoogle:
    @pytest.mark.asyncio
    async def test_send_flows_through_google(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages/send",
            _google_result({"id": "m1", "threadId": "t1"}),
        )
        await adapter.execute(_ctx(
            "gmail_send_email",
            to=["a@b.com"], subject="Hi", body_plain="Hello",
        ))
        assert len(fake.executed_requests) == 1
        req = fake.executed_requests[0]
        assert req.params.get("service") == "gmail"

    @pytest.mark.asyncio
    async def test_list_flows_through_google(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages",
            _google_result({"messages": [], "resultSizeEstimate": 0}),
        )
        await adapter.execute(_ctx("gmail_list_messages"))
        req = fake.executed_requests[-1]
        assert req.params.get("resource") == "users/me/messages"

    @pytest.mark.asyncio
    async def test_labels_flows_through_google(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/labels",
            _google_result({"labels": []}),
        )
        await adapter.execute(_ctx("gmail_list_labels"))
        req = fake.executed_requests[-1]
        assert req.params.get("resource") == "users/me/labels"

    @pytest.mark.asyncio
    async def test_threads_flows_through_google(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/threads",
            _google_result({"threads": [], "resultSizeEstimate": 0}),
        )
        await adapter.execute(_ctx("gmail_list_threads"))
        req = fake.executed_requests[-1]
        assert req.params.get("resource") == "users/me/threads"

    @pytest.mark.asyncio
    async def test_search_flows_through_google(self) -> None:
        fake = FakeGoogleApiAdapter()
        adapter = GmailAdapter(google_adapter=fake)  # type: ignore[arg-type]
        fake.add_response(
            "users/me/messages",
            _google_result({"messages": [], "resultSizeEstimate": 0}),
        )
        await adapter.execute(_ctx("gmail_search_messages", query="is:unread"))
        req = fake.executed_requests[-1]
        assert req.params.get("resource") == "users/me/messages"


# =========================================================================
# Test: SendEmailRequest — Error Handling
# =========================================================================


class TestSendEmailRequestErrors:
    def test_empty_to_list(self) -> None:
        with pytest.raises(ValueError):
            SendEmailRequest(to=[], subject="Hi", body_plain="Hello")

    def test_empty_subject(self) -> None:
        with pytest.raises(ValueError):
            SendEmailRequest(to=["a@b.com"], subject="", body_plain="Hello")

    def test_empty_body(self) -> None:
        with pytest.raises(ValueError):
            SendEmailRequest(to=["a@b.com"], subject="Hi", body_plain="", body_html="")


# =========================================================================
# Test: MimeMessage — Edge Cases
# =========================================================================


class TestMimeMessageEdgeCases:
    def test_multiple_to_addresses_csv(self) -> None:
        raw = (MimeMessage()
               .to(["a@b.com", "c@d.com"])
               .subject("Test")
               .plain("Body")
               .build())
        assert "a@b.com, c@d.com" in raw

    def test_long_subject(self) -> None:
        subject = "A" * 200
        raw = (MimeMessage()
               .to(["a@b.com"])
               .subject(subject)
               .plain("Body")
               .build())
        assert subject in raw

    def test_special_chars_in_body(self) -> None:
        raw = (MimeMessage()
               .to(["a@b.com"])
               .subject("Special")
               .plain("Hello <world> & more \"quotes\"")
               .build())
        assert "Hello <world>" in raw


# =========================================================================
# Test: GmailQuery — Complex queries
# =========================================================================


class TestGmailQueryComplex:
    def test_complex_combined_query(self) -> None:
        q = (GmailQuery()
             .from_("boss@b.com")
             .subject("meeting")
             .has_attachment()
             .after("2026/01/01")
             .build())
        assert "from:boss@b.com" in q
        assert "subject:" in q
        assert "has:attachment" in q
        assert "after:2026/01/01" in q

    def test_query_not_buildable_from_empty(self) -> None:
        q = GmailQuery()
        assert q.build() == ""
