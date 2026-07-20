from __future__ import annotations

from typing import Any

from services.adapters.base_adapter import ExecutionAdapter
from services.adapters.adapter_context import AdapterContext
from services.adapters.models import AdapterMetadata, AdapterResult
from services.adapters.google.google_api_adapter import GoogleApiAdapter
from services.adapters.http.http_adapter import HttpAdapter
from services.adapters.http.transport import HttpTransport
from services.adapters.google.gmail.models import (
    GmailResourceMapper,
    SendEmailRequest,
    ListMessagesRequest,
    GetMessageRequest,
    SearchMessagesRequest,
    ListLabelsRequest,
    GetLabelRequest,
    ListThreadsRequest,
    GetThreadRequest,
    MessageSummary,
    MessageDetail,
    ThreadSummary,
    LabelSummary,
)
from services.adapters.google.gmail.errors import (
    GmailError,
    MessageNotFoundError,
    ThreadNotFoundError,
    LabelNotFoundError,
    InvalidQueryError,
)
from services.adapters.google.gmail.queries import GmailQuery
from services.adapters.google.gmail.mime import MimeMessage


GMAIL_METADATA = AdapterMetadata(
    name="gmail",
    display_name="Gmail Adapter",
    version="1.0.0",
    description="Google Gmail Adapter — send, list, search, and manage "
    "Gmail messages, threads, and labels. "
    "Built on the Google API Base Adapter.",
    author="Loqi",
    supported_operations=(
        "gmail_send_email",
        "gmail_list_messages",
        "gmail_get_message",
        "gmail_search_messages",
        "gmail_list_labels",
        "gmail_get_label",
        "gmail_list_threads",
        "gmail_get_thread",
    ),
    requires_auth=True,
    supports_streaming=False,
    supports_batch=False,
    supports_retry=True,
    tags=("gmail", "email", "google", "workspace"),
)

CAPABILITY_DESCRIPTORS: list[dict[str, Any]] = [
    {
        "name": "gmail_send_email",
        "display_name": "Send Email",
        "description": "Send an email via Gmail",
        "category": "communication",
        "version": "1.0.0",
        "requires_auth": True,
    },
    {
        "name": "gmail_list_messages",
        "display_name": "List Messages",
        "description": "List Gmail messages with optional filters",
        "category": "communication",
        "version": "1.0.0",
        "requires_auth": True,
    },
    {
        "name": "gmail_get_message",
        "display_name": "Get Message",
        "description": "Retrieve a single Gmail message by ID",
        "category": "communication",
        "version": "1.0.0",
        "requires_auth": True,
    },
    {
        "name": "gmail_search_messages",
        "display_name": "Search Messages",
        "description": "Search Gmail messages using Gmail search syntax",
        "category": "communication",
        "version": "1.0.0",
        "requires_auth": True,
    },
    {
        "name": "gmail_list_labels",
        "display_name": "List Labels",
        "description": "List all Gmail labels for the authenticated user",
        "category": "communication",
        "version": "1.0.0",
        "requires_auth": True,
    },
    {
        "name": "gmail_get_label",
        "display_name": "Get Label",
        "description": "Retrieve a single Gmail label by ID",
        "category": "communication",
        "version": "1.0.0",
        "requires_auth": True,
    },
    {
        "name": "gmail_list_threads",
        "display_name": "List Threads",
        "description": "List Gmail threads with optional filters",
        "category": "communication",
        "version": "1.0.0",
        "requires_auth": True,
    },
    {
        "name": "gmail_get_thread",
        "display_name": "Get Thread",
        "description": "Retrieve a single Gmail thread by ID",
        "category": "communication",
        "version": "1.0.0",
        "requires_auth": True,
    },
]

CREDENTIAL_DESCRIPTORS: list[dict[str, Any]] = [
    {
        "name": "google_oauth2",
        "display_name": "Google OAuth2",
        "description": "OAuth2 access token for Gmail API authentication",
        "auth_type": "oauth2",
    },
]


class GmailAdapter(ExecutionAdapter):
    """Gmail adapter — thin domain layer on top of GoogleApiAdapter.

    Translates Gmail concepts into Google API requests, maps responses
    into typed domain models, and provides Gmail-specific error handling.
    All HTTP execution flows through ``GoogleApiAdapter`` — no HTTP logic
    is duplicated.
    """

    def __init__(
        self,
        google_adapter: GoogleApiAdapter | None = None,
        http_adapter: HttpAdapter | None = None,
        transport: HttpTransport | None = None,
    ) -> None:
        self._google = google_adapter or GoogleApiAdapter(
            http_adapter=http_adapter, transport=transport
        )
        self._mapper = GmailResourceMapper()

    @property
    def metadata(self) -> AdapterMetadata:
        return GMAIL_METADATA

    async def execute(self, context: AdapterContext) -> AdapterResult:
        action = context.action
        params = context.params

        dispatch = {
            "gmail_send_email": self._send_email,
            "gmail_list_messages": self._list_messages,
            "gmail_get_message": self._get_message,
            "gmail_search_messages": self._search_messages,
            "gmail_list_labels": self._list_labels,
            "gmail_get_label": self._get_label,
            "gmail_list_threads": self._list_threads,
            "gmail_get_thread": self._get_thread,
        }

        handler = dispatch.get(action)
        if handler is None:
            return AdapterResult.failure_result(
                error=f"Unknown Gmail action: {action!r}",
                metadata={"error_type": "GmailError"},
            )

        return await handler(context)

    # ── Operation handlers ──────────────────────────────────────────────

    async def _send_email(self, context: AdapterContext) -> AdapterResult:
        req = _build_send_request(context.params)
        mime = MimeMessage()
        mime.to(req.to).subject(req.subject)

        if req.cc:
            mime.cc(req.cc)
        if req.bcc:
            mime.bcc(req.bcc)
        if req.reply_to:
            mime.reply_to(req.reply_to)
        if req.body_plain:
            mime.plain(req.body_plain)
        if req.body_html:
            mime.html(req.body_html)

        # Thread-aware reply: set In-Reply-To / References headers and
        # attach the message to the existing Gmail thread.
        if req.in_reply_to_message_id:
            mime.header("In-Reply-To", req.in_reply_to_message_id)
            mime.header("References", req.in_reply_to_message_id)

        raw = mime.encode()

        body: dict[str, Any] = {"raw": raw}
        if req.thread_id:
            body["threadId"] = req.thread_id

        gc = _google_context(
            context=context,
            action="google_request",
            service="gmail",
            resource="users/me/messages/send",
            method="POST",
            body=body,
        )
        result = await self._google.execute(gc)
        return _map_send_result(result, self._mapper)

    async def _list_messages(self, context: AdapterContext) -> AdapterResult:
        req = _build_list_messages_request(context.params)
        query: dict[str, str] = {"maxResults": str(req.max_results)}
        if req.query:
            query["q"] = req.query
        if req.label_ids:
            query["labelIds"] = ",".join(req.label_ids)
        if req.include_spam_trash:
            query["includeSpamTrash"] = "true"

        gc = _google_context(
            context=context,
            action="google_request",
            service="gmail",
            resource="users/me/messages",
            query=query,
        )
        result = await self._google.execute(gc)
        return _map_list_result(result, self._mapper)

    async def _get_message(self, context: AdapterContext) -> AdapterResult:
        req = _build_get_message_request(context.params)

        gc = _google_context(
            context=context,
            action="google_request",
            service="gmail",
            resource=f"users/me/messages/{req.message_id}",
            query={"format": req.format},
        )
        result = await self._google.execute(gc)
        return _map_get_message_result(result, self._mapper)

    async def _search_messages(self, context: AdapterContext) -> AdapterResult:
        req = _build_search_messages_request(context.params)
        query: dict[str, str] = {"q": req.query, "maxResults": str(req.max_results)}
        if req.label_ids:
            query["labelIds"] = ",".join(req.label_ids)

        gc = _google_context(
            context=context,
            action="google_request",
            service="gmail",
            resource="users/me/messages",
            query=query,
        )
        result = await self._google.execute(gc)
        return _map_list_result(result, self._mapper)

    async def _list_labels(self, context: AdapterContext) -> AdapterResult:
        gc = _google_context(
            context=context,
            action="google_request",
            service="gmail",
            resource="users/me/labels",
        )
        result = await self._google.execute(gc)
        return _map_labels_result(result, self._mapper)

    async def _get_label(self, context: AdapterContext) -> AdapterResult:
        req = _build_get_label_request(context.params)

        gc = _google_context(
            context=context,
            action="google_request",
            service="gmail",
            resource=f"users/me/labels/{req.label_id}",
        )
        result = await self._google.execute(gc)
        return _map_label_result(result, self._mapper)

    async def _list_threads(self, context: AdapterContext) -> AdapterResult:
        req = _build_list_threads_request(context.params)
        query: dict[str, str] = {"maxResults": str(req.max_results)}
        if req.query:
            query["q"] = req.query
        if req.label_ids:
            query["labelIds"] = ",".join(req.label_ids)

        gc = _google_context(
            context=context,
            action="google_request",
            service="gmail",
            resource="users/me/threads",
            query=query,
        )
        result = await self._google.execute(gc)
        return _map_threads_list_result(result, self._mapper)

    async def _get_thread(self, context: AdapterContext) -> AdapterResult:
        req = _build_get_thread_request(context.params)

        gc = _google_context(
            context=context,
            action="google_request",
            service="gmail",
            resource=f"users/me/threads/{req.thread_id}",
            query={"format": req.format},
        )
        result = await self._google.execute(gc)
        return _map_get_thread_result(result, self._mapper)


# ── Request builders ────────────────────────────────────────────────────────


def _build_send_request(params: dict[str, Any]) -> SendEmailRequest:
    return SendEmailRequest(
        to=_ensure_list(params.get("to", [])),
        subject=params.get("subject", ""),
        body_plain=params.get("body_plain", params.get("body", "")),
        body_html=params.get("body_html", ""),
        cc=_ensure_list(params.get("cc", [])),
        bcc=_ensure_list(params.get("bcc", [])),
        reply_to=params.get("reply_to", ""),
        thread_id=params.get("thread_id", ""),
        in_reply_to_message_id=params.get("in_reply_to_message_id", ""),
    )


def _build_list_messages_request(params: dict[str, Any]) -> ListMessagesRequest:
    return ListMessagesRequest(
        max_results=params.get("max_results", 100),
        label_ids=tuple(params.get("label_ids", params.get("labelIds", []))),
        query=params.get("query", params.get("q", "")),
        include_spam_trash=params.get("include_spam_trash", False),
    )


def _build_get_message_request(params: dict[str, Any]) -> GetMessageRequest:
    return GetMessageRequest(
        message_id=params.get("message_id", params.get("id", "")),
        format=params.get("format", "full"),
    )


def _build_search_messages_request(params: dict[str, Any]) -> SearchMessagesRequest:
    return SearchMessagesRequest(
        query=params.get("query", params.get("q", "")),
        max_results=params.get("max_results", 100),
        label_ids=tuple(params.get("label_ids", params.get("labelIds", []))),
    )


def _build_get_label_request(params: dict[str, Any]) -> GetLabelRequest:
    return GetLabelRequest(
        label_id=params.get("label_id", params.get("id", "")),
    )


def _build_list_threads_request(params: dict[str, Any]) -> ListThreadsRequest:
    return ListThreadsRequest(
        max_results=params.get("max_results", 100),
        label_ids=tuple(params.get("label_ids", params.get("labelIds", []))),
        query=params.get("query", params.get("q", "")),
    )


def _build_get_thread_request(params: dict[str, Any]) -> GetThreadRequest:
    return GetThreadRequest(
        thread_id=params.get("thread_id", params.get("id", "")),
        format=params.get("format", "full"),
    )


# ── Context builder ─────────────────────────────────────────────────────────


def _google_context(
    context: AdapterContext,
    action: str,
    service: str,
    resource: str,
    method: str = "GET",
    query: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
) -> AdapterContext:
    params: dict[str, Any] = {
        "service": service,
        "resource": resource,
        "method": method,
        "timeout": context.params.get("timeout", 30.0),
    }
    if query:
        params["query"] = query
    if body is not None:
        params["body"] = body
        if "content_type" not in params:
            params["content_type"] = "application/json"

    return AdapterContext.build(
        execution_session_id=context.execution_session_id,
        execution_task_id=context.execution_task_id,
        action=action,
        params=params,
        config=context.config,
        credentials=context.credentials,
        logger=context.logger,
    )


# ── Result mappers ──────────────────────────────────────────────────────────


def _map_send_result(result: AdapterResult, mapper: GmailResourceMapper) -> AdapterResult:
    if not result.success:
        return _with_gmail_error(result)
    data = _json(result)
    return AdapterResult(
        success=True,
        data={"id": data.get("id", ""), "thread_id": data.get("threadId", "")},
        metadata=result.metadata,
        usage=result.usage,
    )


def _map_list_result(result: AdapterResult, mapper: GmailResourceMapper) -> AdapterResult:
    if not result.success:
        return _with_gmail_error(result)
    data = _json(result)
    raw_messages = data.get("messages", [])
    summaries = [mapper.to_message_summary(m) for m in raw_messages]
    return AdapterResult(
        success=True,
        data={
            "messages": summaries,
            "result_size_estimate": data.get("resultSizeEstimate", 0),
            "next_page_token": data.get("nextPageToken", ""),
        },
        metadata=result.metadata,
        usage=result.usage,
    )


def _map_get_message_result(result: AdapterResult, mapper: GmailResourceMapper) -> AdapterResult:
    if not result.success:
        return _with_gmail_error(result, resource_type="message")
    data = _json(result)
    detail = mapper.to_message_detail(data)
    return AdapterResult(
        success=True,
        data={"message": detail},
        metadata=result.metadata,
        usage=result.usage,
    )


def _map_labels_result(result: AdapterResult, mapper: GmailResourceMapper) -> AdapterResult:
    if not result.success:
        return _with_gmail_error(result)
    data = _json(result)
    raw_labels = data.get("labels", [])
    summaries = [mapper.to_label_summary(l) for l in raw_labels]
    return AdapterResult(
        success=True,
        data={"labels": summaries},
        metadata=result.metadata,
        usage=result.usage,
    )


def _map_label_result(result: AdapterResult, mapper: GmailResourceMapper) -> AdapterResult:
    if not result.success:
        return _with_gmail_error(result, resource_type="label")
    data = _json(result)
    summary = mapper.to_label_summary(data)
    return AdapterResult(
        success=True,
        data={"label": summary},
        metadata=result.metadata,
        usage=result.usage,
    )


def _map_threads_list_result(result: AdapterResult, mapper: GmailResourceMapper) -> AdapterResult:
    if not result.success:
        return _with_gmail_error(result)
    data = _json(result)
    raw_threads = data.get("threads", [])
    summaries = [mapper.to_thread_summary(t) for t in raw_threads]
    return AdapterResult(
        success=True,
        data={
            "threads": summaries,
            "result_size_estimate": data.get("resultSizeEstimate", 0),
            "next_page_token": data.get("nextPageToken", ""),
        },
        metadata=result.metadata,
        usage=result.usage,
    )


def _map_get_thread_result(result: AdapterResult, mapper: GmailResourceMapper) -> AdapterResult:
    if not result.success:
        return _with_gmail_error(result, resource_type="thread")
    data = _json(result)
    summary = mapper.to_thread_summary(data)
    return AdapterResult(
        success=True,
        data={"thread": summary},
        metadata=result.metadata,
        usage=result.usage,
    )


# ── Helpers ─────────────────────────────────────────────────────────────────


def _json(result: AdapterResult) -> dict[str, Any]:
    data = result.data or {}
    json_data = data.get("json", {})
    if isinstance(json_data, dict):
        return json_data
    return {}


def _with_gmail_error(
    result: AdapterResult,
    resource_type: str = "",
) -> AdapterResult:
    error_msg = result.error or ""
    status_code = _status_code(result)

    if status_code == 404:
        if resource_type == "message":
            exc = MessageNotFoundError(error_msg)
        elif resource_type == "thread":
            exc = ThreadNotFoundError(error_msg)
        elif resource_type == "label":
            exc = LabelNotFoundError(error_msg)
        else:
            exc = GmailError(error_msg)
    elif status_code == 400:
        exc = InvalidQueryError(error_msg)
    else:
        exc = GmailError(error_msg)

    metadata = dict(result.metadata or {})
    metadata["error_type"] = type(exc).__name__
    return AdapterResult(
        success=False,
        error=str(exc),
        data=result.data,
        metadata=metadata,
        warnings=result.warnings or [],
        usage=result.usage,
    )


def _status_code(result: AdapterResult) -> int:
    data = result.data or {}
    return data.get("status_code", 0)


def _ensure_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    return list(value)
