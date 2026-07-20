from __future__ import annotations

from typing import Any

from services.email.models import EmailDraft, TemplateName
from services.email.exceptions import (
    RenderingError,
    UnknownTemplateError,
)
from services.email.templates import (
    TEMPLATE_FUNCTIONS,
    _brand_style,
)


class EmailRenderer:
    def render(self, draft: EmailDraft) -> EmailDraft:
        rendered_html = self._render_html(draft)
        footer = self._resolve_footer(draft)
        return EmailDraft(
            subject=draft.subject,
            body_plain=draft.body_plain,
            body_html=rendered_html,
            preview_text=draft.preview_text,
            to=draft.to,
            cc=draft.cc,
            bcc=draft.bcc,
            reply_to=draft.reply_to,
            attachments=draft.attachments,
            mailbox=draft.mailbox,
            brand_kit=draft.brand_kit,
            template_name=draft.template_name,
            metadata=draft.metadata,
            footer=footer,
        )

    def _render_html(self, draft: EmailDraft) -> str:
        template_name = draft.template_name.value if isinstance(draft.template_name, TemplateName) else draft.template_name
        fn = TEMPLATE_FUNCTIONS.get(template_name)
        if fn is None:
            raise UnknownTemplateError(
                f"Unknown template: {template_name!r}. "
                f"Available: {list(TEMPLATE_FUNCTIONS)}"
            )
        brand = draft.brand_kit
        preview = draft.preview_text
        footer = self._resolve_footer(draft)
        try:
            result = fn(
                body_html=draft.body_html,
                body_plain=draft.body_plain,
                preview_text=preview,
                branding=brand,
                footer=footer,
            )
            return result
        except Exception as exc:
            raise RenderingError(
                f"Failed to render template {template_name!r}: {exc}"
            ) from exc

    def _resolve_footer(self, draft: EmailDraft) -> str:
        return draft.footer or ""

    def inject_branding(
        self,
        draft: EmailDraft,
    ) -> EmailDraft:
        return self.render(draft)

    @staticmethod
    def brand_style(branding: Any = None) -> dict[str, str]:
        return _brand_style(branding)
