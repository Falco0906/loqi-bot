from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


TimeUnit = Literal["d", "day", "days", "m", "month", "months", "y", "year", "years"]


@dataclass
class GmailQuery:
    """Type-safe Gmail search query builder.

    Produces Gmail search strings compatible with the Gmail API ``q`` parameter.

    Usage::

        query = (GmailQuery()
                 .from_("alice@example.com")
                 .label("INBOX")
                 .is_unread()
                 .build())
        # → "from:alice@example.com label:INBOX is:unread"
    """

    _parts: list[str] = field(default_factory=list)

    def from_(self, address: str) -> GmailQuery:
        self._parts.append(f"from:{_escape(address)}")
        return self

    def to(self, address: str) -> GmailQuery:
        self._parts.append(f"to:{_escape(address)}")
        return self

    def subject(self, text: str) -> GmailQuery:
        self._parts.append(f"subject:{_escape(text)}")
        return self

    def label(self, name: str) -> GmailQuery:
        self._parts.append(f"label:{_escape(name)}")
        return self

    def has_attachment(self) -> GmailQuery:
        self._parts.append("has:attachment")
        return self

    def is_unread(self) -> GmailQuery:
        self._parts.append("is:unread")
        return self

    def is_read(self) -> GmailQuery:
        self._parts.append("is:read")
        return self

    def is_starred(self) -> GmailQuery:
        self._parts.append("is:starred")
        return self

    def is_important(self) -> GmailQuery:
        self._parts.append("is:important")
        return self

    def in_(self, folder: str) -> GmailQuery:
        self._parts.append(f"in:{_escape(folder)}")
        return self

    def after(self, date: str) -> GmailQuery:
        self._parts.append(f"after:{_escape(date)}")
        return self

    def before(self, date: str) -> GmailQuery:
        self._parts.append(f"before:{_escape(date)}")
        return self

    def newer_than(self, n: int, unit: TimeUnit = "d") -> GmailQuery:
        self._parts.append(f"newer_than:{n}{unit}")
        return self

    def older_than(self, n: int, unit: TimeUnit = "d") -> GmailQuery:
        self._parts.append(f"older_than:{n}{unit}")
        return self

    def cc(self, address: str) -> GmailQuery:
        self._parts.append(f"cc:{_escape(address)}")
        return self

    def bcc(self, address: str) -> GmailQuery:
        self._parts.append(f"bcc:{_escape(address)}")
        return self

    def has(self, field: str) -> GmailQuery:
        self._parts.append(f"has:{_escape(field)}")
        return self

    def list(self, list_name: str) -> GmailQuery:
        self._parts.append(f"list:{_escape(list_name)}")
        return self

    def filename(self, name: str) -> GmailQuery:
        self._parts.append(f"filename:{_escape(name)}")
        return self

    def size(self, operator: str, bytes_: int) -> GmailQuery:
        self._parts.append(f"size:{operator}{bytes_}")
        return self

    def larger(self, bytes_: int) -> GmailQuery:
        self._parts.append(f"larger:{bytes_}")
        return self

    def smaller(self, bytes_: int) -> GmailQuery:
        self._parts.append(f"smaller:{bytes_}")
        return self

    def in_anywhere(self) -> GmailQuery:
        self._parts.append("in:anywhere")
        return self

    def in_inbox(self) -> GmailQuery:
        self._parts.append("in:inbox")
        return self

    def in_sent(self) -> GmailQuery:
        self._parts.append("in:sent")
        return self

    def in_drafts(self) -> GmailQuery:
        self._parts.append("in:drafts")
        return self

    def in_trash(self) -> GmailQuery:
        self._parts.append("in:trash")
        return self

    def in_spam(self) -> GmailQuery:
        self._parts.append("in:spam")
        return self

    def raw(self, text: str) -> GmailQuery:
        self._parts.append(text)
        return self

    def build(self) -> str:
        return " ".join(self._parts)

    def __str__(self) -> str:
        return self.build()

    def __bool__(self) -> bool:
        return bool(self._parts)


def _escape(value: str) -> str:
    if " " in value or '"' in value:
        value = value.replace('"', '\\"')
        return f'"{value}"'
    return value
