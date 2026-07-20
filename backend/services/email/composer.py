from __future__ import annotations

from typing import Any

from services.email.models import (
    Attachment,
    BrandKit,
    CompanyMailbox,
    EmailDraft,
    TemplateName,
)
from services.email.renderer import EmailRenderer
from services.email.draft import DraftBuilder
from services.email.branding import BrandingManager
from services.email.mailbox import MailboxManager
from services.email.attachments import AttachmentProcessor
from services.email.template_registry import TemplateRegistry


class EmailComposer:
    def __init__(
        self,
        renderer: EmailRenderer | None = None,
        branding_manager: BrandingManager | None = None,
        mailbox_manager: MailboxManager | None = None,
        attachment_processor: AttachmentProcessor | None = None,
        template_registry: TemplateRegistry | None = None,
    ) -> None:
        self.renderer = renderer or EmailRenderer()
        self.branding = branding_manager or BrandingManager()
        self.mailboxes = mailbox_manager or MailboxManager()
        self.attachments = attachment_processor or AttachmentProcessor()
        self.templates = template_registry or TemplateRegistry()

    def compose(
        self,
        *,
        subject: str,
        body_text: str = "",
        body_html: str = "",
        preview_text: str = "",
        to: str | list[str] | None = None,
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
        reply_to: str = "",
        attachments: list[Attachment] | None = None,
        mailbox: CompanyMailbox | str | None = None,
        brand_kit: BrandKit | str | None = None,
        template_name: TemplateName | str = TemplateName.PLAIN,
        footer: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> EmailDraft:
        output = DraftBuilder()
        output.subject(subject)

        if body_text:
            output.body_plain(body_text)
        if body_html:
            output.body_html(body_html)
        if preview_text:
            output.preview_text(preview_text)

        if to:
            output.to(to)
        if cc:
            output.cc(cc)
        if bcc:
            output.bcc(bcc)
        if reply_to:
            output.reply_to(reply_to)

        if template_name:
            output.template_name(template_name)

        if footer:
            output.footer(footer)

        if metadata:
            output.metadata(metadata)

        mailbox_obj = self._resolve_mailbox(mailbox)
        if mailbox_obj:
            output.mailbox(mailbox_obj)

        brand_obj = self._resolve_brand(brand_kit)
        if brand_obj:
            output.brand_kit(brand_obj)

        if attachments:
            self.attachments.validate_batch(tuple(attachments))
            for a in attachments:
                output.add_attachment(a)

        draft = output.build()

        rendered = self.renderer.render(draft)

        return rendered

    def compose_from_ai(
        self,
        ai_output: dict[str, Any],
        *,
        mailbox: CompanyMailbox | str | None = None,
        brand_kit: BrandKit | str | None = None,
        template_name: TemplateName | str = TemplateName.PROFESSIONAL,
        footer: str = "",
    ) -> EmailDraft:
        return self.compose(
            subject=ai_output.get("subject", ""),
            body_text=ai_output.get("body_text", ai_output.get("body_plain", "")),
            body_html=ai_output.get("body_html", ""),
            preview_text=ai_output.get("preview_text", ""),
            to=ai_output.get("to"),
            cc=ai_output.get("cc"),
            bcc=ai_output.get("bcc"),
            reply_to=ai_output.get("reply_to", ""),
            attachments=ai_output.get("attachments"),
            mailbox=mailbox,
            brand_kit=brand_kit,
            template_name=template_name,
            footer=footer,
            metadata=ai_output.get("metadata"),
        )

    def _resolve_mailbox(
        self,
        mailbox: CompanyMailbox | str | None,
    ) -> CompanyMailbox | None:
        if mailbox is None:
            return self.mailboxes.default
        if isinstance(mailbox, CompanyMailbox):
            return mailbox
        return self.mailboxes.get(mailbox)

    def _resolve_brand(
        self,
        brand_kit: BrandKit | str | None,
    ) -> BrandKit | None:
        if brand_kit is None:
            return self.branding.default
        if isinstance(brand_kit, BrandKit):
            return brand_kit
        return self.branding.get(brand_kit)
