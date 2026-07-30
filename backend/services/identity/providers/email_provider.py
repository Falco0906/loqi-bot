from __future__ import annotations

import asyncio
import os
import resend

from abc import ABC, abstractmethod
from typing import Any


class EmailProvider(ABC):

    @abstractmethod
    async def send_verification_email(
        self, to: str, verification_url: str,
    ) -> None:
        ...

    @abstractmethod
    async def send_password_reset_email(
        self, to: str, reset_url: str,
    ) -> None:
        ...

    async def send_organization_invitation(
        self,
        to: str,
        inviter_name: str,
        organization_name: str,
        accept_url: str,
    ) -> None:
        raise NotImplementedError

    async def send_welcome_email(
        self,
        to: str,
        name: str,
    ) -> None:
        raise NotImplementedError

    async def send_billing_receipt(
        self,
        to: str,
        recipient_name: str,
        amount: str,
        plan_name: str,
        invoice_url: str,
    ) -> None:
        raise NotImplementedError

    async def send_subscription_cancelled(
        self,
        to: str,
        recipient_name: str,
        plan_name: str,
        effective_date: str,
    ) -> None:
        raise NotImplementedError

    async def send_subscription_renewed(
        self,
        to: str,
        recipient_name: str,
        plan_name: str,
        amount: str,
        next_billing_date: str,
    ) -> None:
        raise NotImplementedError


class ConsoleEmailProvider(EmailProvider):
    """Logs emails to console. Suitable for development/testing."""

    async def send_verification_email(
        self, to: str, verification_url: str,
    ) -> None:
        print(f"[ConsoleEmailProvider] To: {to}")
        print(f"[ConsoleEmailProvider] Verification URL: {verification_url}")

    async def send_password_reset_email(
        self, to: str, reset_url: str,
    ) -> None:
        print(f"[ConsoleEmailProvider] To: {to}")
        print(f"[ConsoleEmailProvider] Password Reset URL: {reset_url}")

    async def send_organization_invitation(
        self,
        to: str,
        inviter_name: str,
        organization_name: str,
        accept_url: str,
    ) -> None:
        print(f"[ConsoleEmailProvider] To: {to}")
        print(f"[ConsoleEmailProvider] Invitation: {inviter_name} invited you to {organization_name}")
        print(f"[ConsoleEmailProvider] Accept URL: {accept_url}")

    async def send_welcome_email(
        self,
        to: str,
        name: str,
    ) -> None:
        print(f"[ConsoleEmailProvider] To: {to}")
        print(f"[ConsoleEmailProvider] Welcome email for: {name}")

    async def send_billing_receipt(
        self,
        to: str,
        recipient_name: str,
        amount: str,
        plan_name: str,
        invoice_url: str,
    ) -> None:
        print(f"[ConsoleEmailProvider] To: {to}")
        print(f"[ConsoleEmailProvider] Receipt: {plan_name} {amount}")
        print(f"[ConsoleEmailProvider] Invoice URL: {invoice_url}")

    async def send_subscription_cancelled(
        self,
        to: str,
        recipient_name: str,
        plan_name: str,
        effective_date: str,
    ) -> None:
        print(f"[ConsoleEmailProvider] To: {to}")
        print(f"[ConsoleEmailProvider] Subscription cancelled: {plan_name}")


class ResendEmailProvider(EmailProvider):
    def __init__(self, api_key: str, from_email: str) -> None:
        self.api_key = api_key
        self.from_email = from_email
        resend.api_key = self.api_key

    async def _send(self, to: str, subject: str, html: str) -> None:
        await asyncio.to_thread(
            resend.Emails.send,
            {
                "from": self.from_email,
                "to": to,
                "subject": subject,
                "html": html,
            },
        )

    async def send_verification_email(self, to: str, verification_url: str) -> None:
        await self._send(to, "Verify your email", f'<p>Click <a href="{verification_url}">here</a> to verify your email.</p>')

    async def send_password_reset_email(self, to: str, reset_url: str) -> None:
        await self._send(to, "Password reset", f'<p>Click <a href="{reset_url}">here</a> to reset your password.</p>')

    async def send_organization_invitation(self, to: str, inviter_name: str, organization_name: str, accept_url: str) -> None:
        await self._send(to, "Organization Invitation", f'<p>{inviter_name} invited you to {organization_name}. Click <a href="{accept_url}">here</a> to accept.</p>')

    async def send_welcome_email(self, to: str, name: str) -> None:
        await self._send(to, "Welcome!", f'<p>Welcome, {name}!</p>')

    async def send_billing_receipt(self, to: str, recipient_name: str, amount: str, plan_name: str, invoice_url: str) -> None:
        await self._send(to, "Billing Receipt", f'<p>Receipt for {plan_name}: {amount}. <a href="{invoice_url}">View Invoice</a></p>')

    async def send_subscription_cancelled(self, to: str, recipient_name: str, plan_name: str, effective_date: str) -> None:
        await self._send(to, "Subscription Cancelled", f'<p>Subscription for {plan_name} cancelled. Effective {effective_date}.</p>')

    async def send_subscription_renewed(self, to: str, recipient_name: str, plan_name: str, amount: str, next_billing_date: str) -> None:
        await self._send(to, "Subscription Renewed", f'<p>Subscription for {plan_name} renewed. {amount}. Next billing: {next_billing_date}.</p>')
