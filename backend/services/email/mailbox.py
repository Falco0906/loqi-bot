from __future__ import annotations

from services.email.models import CompanyMailbox
from services.email.exceptions import MailboxNotFoundError


class MailboxManager:
    def __init__(self) -> None:
        self._mailboxes: dict[str, CompanyMailbox] = {}
        self._default_id: str | None = None

    def register(self, mailbox: CompanyMailbox) -> str:
        self._mailboxes[mailbox.id] = mailbox
        if mailbox.default or self._default_id is None:
            self._default_id = mailbox.id
        return mailbox.id

    def get(self, mailbox_id: str) -> CompanyMailbox:
        mailbox = self._mailboxes.get(mailbox_id)
        if mailbox is None:
            raise MailboxNotFoundError(f"Mailbox not found: {mailbox_id!r}")
        return mailbox

    def set_default(self, mailbox_id: str) -> None:
        if mailbox_id not in self._mailboxes:
            raise MailboxNotFoundError(f"Mailbox not found: {mailbox_id!r}")
        self._default_id = mailbox_id

    @property
    def default(self) -> CompanyMailbox | None:
        if self._default_id is None:
            return None
        return self._mailboxes.get(self._default_id)

    def remove(self, mailbox_id: str) -> None:
        self._mailboxes.pop(mailbox_id, None)
        if self._default_id == mailbox_id:
            self._default_id = next(iter(self._mailboxes)) if self._mailboxes else None

    def list(self) -> dict[str, CompanyMailbox]:
        return dict(self._mailboxes)

    def has(self, mailbox_id: str) -> bool:
        return mailbox_id in self._mailboxes

    def select_sender(self, preferred: str = "") -> CompanyMailbox:
        if preferred:
            return self.get(preferred)
        if self._default_id:
            return self._mailboxes[self._default_id]
        raise MailboxNotFoundError("No mailboxes registered")
