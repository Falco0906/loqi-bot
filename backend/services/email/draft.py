from __future__ import annotations

from typing import Any

from services.email.models import (
    Attachment,
    BrandKit,
    CompanyMailbox,
    EmailDraft,
    TemplateName,
)
from services.email.exceptions import DraftValidationError


class DraftBuilder:
    def __init__(self) -> None:
        self._subject: str = ""
        self._body_plain: str = ""
        self._body_html: str = ""
        self._preview_text: str = ""
        self._to: list[str] = []
        self._cc: list[str] = []
        self._bcc: list[str] = []
        self._reply_to: str = ""
        self._attachments: list[Attachment] = []
        self._mailbox: CompanyMailbox | None = None
        self._brand_kit: BrandKit | None = None
        self._template_name: TemplateName = TemplateName.PLAIN
        self._metadata: dict[str, Any] = {}
        self._footer: str = ""

    def subject(self, value: str) -> DraftBuilder:
        self._subject = value
        return self

    def body_plain(self, value: str) -> DraftBuilder:
        self._body_plain = value
        return self

    def body_html(self, value: str) -> DraftBuilder:
        self._body_html = value
        return self

    def preview_text(self, value: str) -> DraftBuilder:
        self._preview_text = value
        return self

    def to(self, recipients: str | list[str]) -> DraftBuilder:
        if isinstance(recipients, str):
            recipients = [recipients]
        self._to = list(recipients)
        return self

    def cc(self, recipients: str | list[str]) -> DraftBuilder:
        if isinstance(recipients, str):
            recipients = [recipients]
        self._cc = list(recipients)
        return self

    def bcc(self, recipients: str | list[str]) -> DraftBuilder:
        if isinstance(recipients, str):
            recipients = [recipients]
        self._bcc = list(recipients)
        return self

    def reply_to(self, value: str) -> DraftBuilder:
        self._reply_to = value
        return self

    def add_attachment(self, attachment: Attachment) -> DraftBuilder:
        self._attachments.append(attachment)
        return self

    def mailbox(self, value: CompanyMailbox) -> DraftBuilder:
        self._mailbox = value
        return self

    def brand_kit(self, value: BrandKit) -> DraftBuilder:
        self._brand_kit = value
        return self

    def template_name(self, value: TemplateName | str) -> DraftBuilder:
        if isinstance(value, str):
            value = TemplateName(value)
        self._template_name = value
        return self

    def metadata(self, value: dict[str, Any]) -> DraftBuilder:
        self._metadata = dict(value)
        return self

    def footer(self, value: str) -> DraftBuilder:
        self._footer = value
        return self

    def build(self) -> EmailDraft:
        if not self._subject:
            raise DraftValidationError("subject is required")
        return EmailDraft(
            subject=self._subject,
            body_plain=self._body_plain,
            body_html=self._body_html,
            preview_text=self._preview_text,
            to=tuple(self._to),
            cc=tuple(self._cc),
            bcc=tuple(self._bcc),
            reply_to=self._reply_to,
            attachments=tuple(self._attachments),
            mailbox=self._mailbox,
            brand_kit=self._brand_kit,
            template_name=self._template_name,
            metadata=dict(self._metadata),
            footer=self._footer,
        )

    def reset(self) -> DraftBuilder:
        self._subject = ""
        self._body_plain = ""
        self._body_html = ""
        self._preview_text = ""
        self._to = []
        self._cc = []
        self._bcc = []
        self._reply_to = ""
        self._attachments = []
        self._mailbox = None
        self._brand_kit = None
        self._template_name = TemplateName.PLAIN
        self._metadata = {}
        self._footer = ""
        return self


def draft_to_gmail_params(draft: EmailDraft) -> dict[str, Any]:
    params: dict[str, Any] = {
        "to": list(draft.to),
        "subject": draft.subject,
        "body_plain": draft.body_plain,
        "body_html": draft.body_html,
    }
    if draft.cc:
        params["cc"] = list(draft.cc)
    if draft.bcc:
        params["bcc"] = list(draft.bcc)
    if draft.reply_to:
        params["reply_to"] = draft.reply_to
    return params
