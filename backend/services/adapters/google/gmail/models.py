from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote


# ── Request Models ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SendEmailRequest:
    to: list[str]
    subject: str
    body_plain: str = ""
    body_html: str = ""
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    reply_to: str = ""
    thread_id: str = ""
    in_reply_to_message_id: str = ""

    def __post_init__(self) -> None:
        if not self.to and not self.cc and not self.bcc:
            raise ValueError("At least one of to, cc, or bcc is required")
        if not self.subject:
            raise ValueError("subject is required")
        if not self.body_plain and not self.body_html:
            raise ValueError("At least one of body_plain or body_html is required")
        for addr in self.to:
            _validate_email(addr)
        for addr in self.cc:
            _validate_email(addr)
        for addr in self.bcc:
            _validate_email(addr)
        if self.reply_to:
            _validate_email(self.reply_to)


@dataclass(frozen=True)
class ListMessagesRequest:
    max_results: int = 100
    label_ids: tuple[str, ...] = ()
    query: str = ""
    include_spam_trash: bool = False

    def __post_init__(self) -> None:
        if self.max_results < 1 or self.max_results > 500:
            raise ValueError("max_results must be between 1 and 500")


@dataclass(frozen=True)
class GetMessageRequest:
    message_id: str
    format: str = "full"

    def __post_init__(self) -> None:
        valid = ("minimal", "full", "metadata", "raw")
        if self.format not in valid:
            raise ValueError(f"format must be one of {valid}")


@dataclass(frozen=True)
class SearchMessagesRequest:
    query: str
    max_results: int = 100
    label_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.query:
            raise ValueError("query is required")
        if self.max_results < 1 or self.max_results > 500:
            raise ValueError("max_results must be between 1 and 500")


@dataclass(frozen=True)
class ListLabelsRequest:
    pass


@dataclass(frozen=True)
class GetLabelRequest:
    label_id: str

    def __post_init__(self) -> None:
        if not self.label_id:
            raise ValueError("label_id is required")


@dataclass(frozen=True)
class ListThreadsRequest:
    max_results: int = 100
    label_ids: tuple[str, ...] = ()
    query: str = ""

    def __post_init__(self) -> None:
        if self.max_results < 1 or self.max_results > 500:
            raise ValueError("max_results must be between 1 and 500")


@dataclass(frozen=True)
class GetThreadRequest:
    thread_id: str
    format: str = "full"

    def __post_init__(self) -> None:
        valid = ("minimal", "full", "metadata", "raw")
        if self.format not in valid:
            raise ValueError(f"format must be one of {valid}")
        if not self.thread_id:
            raise ValueError("thread_id is required")


# ── Response Models ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MessageSummary:
    id: str
    thread_id: str
    snippet: str
    from_: str = ""
    to: str = ""
    subject: str = ""
    date: str = ""
    label_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MessageDetail:
    id: str
    thread_id: str
    snippet: str
    from_: str = ""
    to: str = ""
    subject: str = ""
    date: str = ""
    label_ids: tuple[str, ...] = ()
    body_plain: str = ""
    body_html: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    size_estimate: int = 0
    history_id: str = ""
    internal_date: str = ""


@dataclass(frozen=True)
class ThreadSummary:
    id: str
    snippet: str
    history_id: str = ""
    messages: tuple[MessageSummary, ...] = ()


@dataclass(frozen=True)
class LabelSummary:
    id: str
    name: str
    type: str = ""
    color: dict[str, str] = field(default_factory=dict)
    message_list_visibility: str = ""
    label_list_visibility: str = ""
    messages_total: int = 0
    messages_unread: int = 0
    threads_total: int = 0
    threads_unread: int = 0


# ── Resource Mapper ─────────────────────────────────────────────────────────


class GmailResourceMapper:
    """Converts raw Gmail API JSON responses into typed domain models.

    Keeps GmailAdapter focused on orchestration while making
    response transformation independently testable.
    """

    @staticmethod
    def to_message_summary(raw: dict[str, Any]) -> MessageSummary:
        payload = raw.get("payload", {})
        headers = _extract_headers(payload.get("headers", []))
        return MessageSummary(
            id=raw.get("id", ""),
            thread_id=raw.get("threadId", ""),
            snippet=raw.get("snippet", ""),
            from_=headers.get("From", ""),
            to=headers.get("To", ""),
            subject=headers.get("Subject", ""),
            date=headers.get("Date", ""),
            label_ids=tuple(raw.get("labelIds", [])),
        )

    @staticmethod
    def to_message_detail(raw: dict[str, Any]) -> MessageDetail:
        payload = raw.get("payload", {})
        headers = _extract_headers(payload.get("headers", []))
        body_parts = _extract_body_parts(payload)
        return MessageDetail(
            id=raw.get("id", ""),
            thread_id=raw.get("threadId", ""),
            snippet=raw.get("snippet", ""),
            from_=headers.get("From", ""),
            to=headers.get("To", ""),
            subject=headers.get("Subject", ""),
            date=headers.get("Date", ""),
            label_ids=tuple(raw.get("labelIds", [])),
            body_plain=body_parts.get("text/plain", ""),
            body_html=body_parts.get("text/html", ""),
            headers=headers,
            size_estimate=raw.get("sizeEstimate", 0),
            history_id=raw.get("historyId", ""),
            internal_date=raw.get("internalDate", ""),
        )

    @staticmethod
    def to_thread_summary(raw: dict[str, Any]) -> ThreadSummary:
        raw_messages = raw.get("messages", [])
        messages = tuple(GmailResourceMapper.to_message_summary(m) for m in raw_messages)
        snippet = raw.get("snippet", "")
        if not snippet and messages:
            snippet = messages[0].snippet
        return ThreadSummary(
            id=raw.get("id", ""),
            snippet=snippet,
            history_id=raw.get("historyId", ""),
            messages=messages,
        )

    @staticmethod
    def to_label_summary(raw: dict[str, Any]) -> LabelSummary:
        color_raw = raw.get("color", {})
        return LabelSummary(
            id=raw.get("id", ""),
            name=raw.get("name", ""),
            type=raw.get("type", ""),
            color={"background": color_raw.get("backgroundColor", ""), "text": color_raw.get("textColor", "")},
            message_list_visibility=raw.get("messageListVisibility", ""),
            label_list_visibility=raw.get("labelListVisibility", ""),
            messages_total=raw.get("messagesTotal", 0),
            messages_unread=raw.get("messagesUnread", 0),
            threads_total=raw.get("threadsTotal", 0),
            threads_unread=raw.get("threadsUnread", 0),
        )


# ── Internal helpers ────────────────────────────────────────────────────────


def _validate_email(addr: str) -> None:
    if not addr or "@" not in addr:
        raise ValueError(f"Invalid email address: {addr!r}")


def _extract_headers(header_list: list[dict[str, str]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for h in header_list:
        name = h.get("name", "")
        value = h.get("value", "")
        if name and value:
            result[name] = value
    return result


def _extract_body_parts(payload: dict[str, Any]) -> dict[str, str]:
    parts: dict[str, str] = {}
    _walk_parts(payload, parts)
    body_data = payload.get("body", {})
    mime_type = payload.get("mimeType", "")
    if mime_type in ("text/plain", "text/html") and body_data:
        raw_data = body_data.get("data", "")
        if raw_data:
            parts[mime_type] = _decode_base64url(raw_data)
    return parts


def _walk_parts(part: dict[str, Any], acc: dict[str, str]) -> None:
    mime = part.get("mimeType", "")
    body = part.get("body", {})
    data = body.get("data", "")
    if data:
        if mime == "text/plain":
            acc["text/plain"] = acc.get("text/plain", "") + _decode_base64url(data)
        elif mime == "text/html":
            acc["text/html"] = acc.get("text/html", "") + _decode_base64url(data)
    for sub in part.get("parts", []):
        _walk_parts(sub, acc)


def _decode_base64url(data: str) -> str:
    import base64
    try:
        padded = data + "=" * (4 - len(data) % 4) if len(data) % 4 else data
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except Exception:
        return ""


def quote_param(value: str) -> str:
    return quote(value, safe="")
