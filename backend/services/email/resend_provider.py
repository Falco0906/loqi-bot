from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from services.email.config import EmailConfig
from services.email.delivery_log import log_email_failed, log_email_sent
from services.email.transactional_templates import (
    TEMPLATE_RENDERERS,
    render_billing_receipt_email,
    render_invitation_email,
    render_password_reset_email,
    render_subscription_cancelled_email,
    render_subscription_renewed_email,
    render_verification_email,
    render_welcome_email,
)
from services.identity.providers.email_provider import EmailProvider

log = logging.getLogger("loqi.email")


class ResendEmailProvider(EmailProvider):

    def __init__(self, config: EmailConfig) -> None:
        self._config = config
        self._resend = None

    def _get_resend(self):
        if self._resend is not None:
            return self._resend
        try:
            import resend
            resend.api_key = self._config.api_key
            self._resend = resend
            return resend
        except ImportError as exc:
            raise RuntimeError(
                "Resend SDK not installed. Add 'resend' to requirements.txt"
            ) from exc

    async def _send_async(
        self,
        to: str,
        subject: str,
        html: str,
        plain_text: str,
        template_name: str = "",
        tags: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        loop = asyncio.get_event_loop()
        start = time.monotonic()

        params: dict[str, Any] = {
            "from": f"{self._config.from_name} <{self._config.from_email}>",
            "to": [to],
            "subject": subject,
            "html": html,
            "text": plain_text,
        }

        if self._config.reply_to:
            params["reply_to"] = [self._config.reply_to]

        if tags:
            params["tags"] = tags

        def _send():
            resend = self._get_resend()
            return resend.Emails.send(params)

        try:
            result = await loop.run_in_executor(None, _send)
            duration = (time.monotonic() - start) * 1000
            log_email_sent(
                request_id="",
                recipient=to,
                template=template_name,
                provider="resend",
                status="sent",
                duration_ms=duration,
            )
            return {"id": result.get("id", "")}
        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            log_email_failed(
                request_id="",
                recipient=to,
                template=template_name,
                provider="resend",
                error=str(exc),
                duration_ms=duration,
            )
            raise

    async def send_verification_email(
        self, to: str, verification_url: str,
    ) -> None:
        result = render_verification_email(
            verification_url,
            company_name=self._config.company_name,
        )
        await self._send_async(
            to=to,
            subject=result.subject,
            html=result.html,
            plain_text=result.plain_text,
            template_name="verification",
            tags=[{"name": "template", "value": "verification"}],
        )

    async def send_password_reset_email(
        self, to: str, reset_url: str,
    ) -> None:
        result = render_password_reset_email(
            reset_url,
            company_name=self._config.company_name,
        )
        await self._send_async(
            to=to,
            subject=result.subject,
            html=result.html,
            plain_text=result.plain_text,
            template_name="password_reset",
            tags=[{"name": "template", "value": "password_reset"}],
        )

    async def send_organization_invitation(
        self,
        to: str,
        inviter_name: str,
        organization_name: str,
        accept_url: str,
    ) -> None:
        result = render_invitation_email(
            inviter_name,
            organization_name,
            accept_url,
            company_name=self._config.company_name,
        )
        await self._send_async(
            to=to,
            subject=result.subject,
            html=result.html,
            plain_text=result.plain_text,
            template_name="invitation",
            tags=[{"name": "template", "value": "invitation"}],
        )

    async def send_welcome_email(
        self,
        to: str,
        name: str,
    ) -> None:
        result = render_welcome_email(
            name,
            company_name=self._config.company_name,
        )
        await self._send_async(
            to=to,
            subject=result.subject,
            html=result.html,
            plain_text=result.plain_text,
            template_name="welcome",
            tags=[{"name": "template", "value": "welcome"}],
        )

    async def send_billing_receipt(
        self,
        to: str,
        recipient_name: str,
        amount: str,
        plan_name: str,
        invoice_url: str,
    ) -> None:
        result = render_billing_receipt_email(
            recipient_name,
            amount,
            plan_name,
            invoice_url,
            company_name=self._config.company_name,
        )
        await self._send_async(
            to=to,
            subject=result.subject,
            html=result.html,
            plain_text=result.plain_text,
            template_name="billing_receipt",
            tags=[{"name": "template", "value": "billing_receipt"}],
        )

    async def send_subscription_cancelled(
        self,
        to: str,
        recipient_name: str,
        plan_name: str,
        effective_date: str,
    ) -> None:
        result = render_subscription_cancelled_email(
            recipient_name,
            plan_name,
            effective_date,
            company_name=self._config.company_name,
        )
        await self._send_async(
            to=to,
            subject=result.subject,
            html=result.html,
            plain_text=result.plain_text,
            template_name="subscription_cancelled",
            tags=[{"name": "template", "value": "subscription_cancelled"}],
        )

    async def send_subscription_renewed(
        self,
        to: str,
        recipient_name: str,
        plan_name: str,
        amount: str,
        next_billing_date: str,
    ) -> None:
        result = render_subscription_renewed_email(
            recipient_name,
            plan_name,
            amount,
            next_billing_date,
            company_name=self._config.company_name,
        )
        await self._send_async(
            to=to,
            subject=result.subject,
            html=result.html,
            plain_text=result.plain_text,
            template_name="subscription_renewed",
            tags=[{"name": "template", "value": "subscription_renewed"}],
        )
