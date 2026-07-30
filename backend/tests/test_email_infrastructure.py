from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest

from services.email.config import EmailConfig
from services.email.transactional_templates import (
    render_billing_receipt_email,
    render_invitation_email,
    render_password_reset_email,
    render_subscription_cancelled_email,
    render_subscription_renewed_email,
    render_verification_email,
    render_welcome_email,
)
from services.identity.providers.email_provider import (
    ConsoleEmailProvider,
    EmailProvider,
)


def _make_mock_resend():
    mock = types.ModuleType("resend")
    mock.api_key = ""

    class Emails:
        send = MagicMock(return_value={"id": "email_mock_123"})

    mock.Emails = Emails
    return mock


# ─── Template Tests ─────────────────────────────────────────────────


class TestEmailTemplates:

    def test_verification_email_contains_link(self):
        result = render_verification_email(
            "https://loqi.ai/verify?token=abc123",
        )
        assert "Verify your email" in result.subject
        assert "https://loqi.ai/verify?token=abc123" in result.html
        assert "https://loqi.ai/verify?token=abc123" in result.plain_text
        assert "<!DOCTYPE html>" in result.html

    def test_password_reset_email_contains_link(self):
        result = render_password_reset_email(
            "https://loqi.ai/reset?token=abc123",
        )
        assert "Reset your password" in result.subject
        assert "https://loqi.ai/reset?token=abc123" in result.html
        assert "https://loqi.ai/reset?token=abc123" in result.plain_text

    def test_invitation_email_contains_details(self):
        result = render_invitation_email(
            "Alice", "Acme Corp", "https://loqi.ai/accept?token=xyz",
        )
        assert "invited to" in result.subject
        assert "Alice" in result.html
        assert "Acme Corp" in result.html
        assert "Alice" in result.plain_text
        assert "Acme Corp" in result.plain_text

    def test_welcome_email_contains_name(self):
        result = render_welcome_email("Bob")
        assert "Welcome to Loqi" in result.subject or "Welcome to Loqi" in result.html
        assert "Bob" in result.html
        assert "Bob" in result.plain_text

    def test_billing_receipt_contains_amount(self):
        result = render_billing_receipt_email(
            "Bob", "$79.00", "Pro Monthly", "https://loqi.ai/invoice/1",
        )
        assert "receipt" in result.subject.lower()
        assert "$79.00" in result.html
        assert "Pro Monthly" in result.plain_text

    def test_subscription_cancelled_contains_plan(self):
        result = render_subscription_cancelled_email(
            "Bob", "Pro Monthly", "June 15, 2026",
        )
        assert "cancelled" in result.subject.lower()
        assert "Pro Monthly" in result.html
        assert "June 15, 2026" in result.plain_text

    def test_subscription_renewed_contains_details(self):
        result = render_subscription_renewed_email(
            "Bob", "Pro Monthly", "$79.00", "July 15, 2026",
        )
        assert "renewed" in result.subject.lower()
        assert "$79.00" in result.html
        assert "July 15, 2026" in result.plain_text

    def test_custom_company_name(self):
        result = render_verification_email(
            "https://example.com/verify",
            company_name="MyApp",
        )
        assert "MyApp" in result.subject
        assert "MyApp" in result.html


# ─── ConsoleEmailProvider Tests ──────────────────────────────────────


@pytest.mark.asyncio
class TestConsoleEmailProvider:

    @pytest.fixture
    def provider(self) -> ConsoleEmailProvider:
        return ConsoleEmailProvider()

    def test_is_email_provider(self, provider):
        assert isinstance(provider, EmailProvider)

    async def test_send_verification_email(self, provider, capsys):
        await provider.send_verification_email("test@example.com", "https://verify")
        captured = capsys.readouterr()
        assert "test@example.com" in captured.out
        assert "Verification URL" in captured.out

    async def test_send_password_reset_email(self, provider, capsys):
        await provider.send_password_reset_email("test@example.com", "https://reset")
        captured = capsys.readouterr()
        assert "test@example.com" in captured.out
        assert "Password Reset URL" in captured.out

    async def test_send_organization_invitation(self, provider, capsys):
        await provider.send_organization_invitation(
            "invited@example.com", "Alice", "Acme Corp", "https://accept",
        )
        captured = capsys.readouterr()
        assert "invited@example.com" in captured.out
        assert "Alice" in captured.out
        assert "Acme Corp" in captured.out

    async def test_send_welcome_email(self, provider, capsys):
        await provider.send_welcome_email("welcome@example.com", "Bob")
        captured = capsys.readouterr()
        assert "welcome@example.com" in captured.out
        assert "Bob" in captured.out

    async def test_send_billing_receipt(self, provider, capsys):
        await provider.send_billing_receipt("bill@example.com", "Bob", "$79", "Pro", "https://inv")
        captured = capsys.readouterr()
        assert "bill@example.com" in captured.out
        assert "Pro" in captured.out
        assert "$79" in captured.out

    async def test_send_subscription_cancelled(self, provider, capsys):
        await provider.send_subscription_cancelled("sub@example.com", "Bob", "Pro", "June 1")
        captured = capsys.readouterr()
        assert "sub@example.com" in captured.out
        assert "Pro" in captured.out

    async def test_send_subscription_renewed(self, provider, capsys):
        await provider.send_subscription_renewed("sub@example.com", "Bob", "Pro", "$79", "July 1")
        captured = capsys.readouterr()
        assert "sub@example.com" in captured.out
        assert "$79" in captured.out


# ─── ResendEmailProvider Tests (mocked SDK) ──────────────────────────


@pytest.mark.asyncio
class TestResendEmailProvider:

    @pytest.fixture
    def email_config(self) -> EmailConfig:
        return EmailConfig(
            provider="resend",
            api_key="re_test_key",
            from_email="noreply@loqi.ai",
            from_name="Loqi",
            reply_to="support@loqi.ai",
            app_url="https://loqi.ai",
        )

    @pytest.fixture
    def patch_resend(self):
        mock = _make_mock_resend()
        with patch.dict("sys.modules", {"resend": mock}):
            from services.email.resend_provider import ResendEmailProvider
            yield ResendEmailProvider, mock

    async def test_send_verification_email(self, email_config, patch_resend):
        RSP, mock_resend = patch_resend
        provider = RSP(email_config)
        await provider.send_verification_email("test@example.com", "https://verify")
        mock_resend.Emails.send.assert_called_once()
        call_kwargs = mock_resend.Emails.send.call_args[0][0]
        assert call_kwargs["to"] == ["test@example.com"]
        assert "Verify your email" in call_kwargs["subject"]
        assert "https://verify" in call_kwargs["html"]

    async def test_send_password_reset_email(self, email_config, patch_resend):
        RSP, mock_resend = patch_resend
        provider = RSP(email_config)
        await provider.send_password_reset_email("test@example.com", "https://reset")
        mock_resend.Emails.send.assert_called_once()
        call_kwargs = mock_resend.Emails.send.call_args[0][0]
        assert "Reset your password" in call_kwargs["subject"]

    async def test_send_organization_invitation(self, email_config, patch_resend):
        RSP, mock_resend = patch_resend
        provider = RSP(email_config)
        await provider.send_organization_invitation(
            "invited@example.com", "Alice", "Acme Corp", "https://accept",
        )
        mock_resend.Emails.send.assert_called_once()
        call_kwargs = mock_resend.Emails.send.call_args[0][0]
        assert "Alice" in call_kwargs["html"]
        assert "Acme Corp" in call_kwargs["html"]

    async def test_send_welcome_email(self, email_config, patch_resend):
        RSP, mock_resend = patch_resend
        provider = RSP(email_config)
        await provider.send_welcome_email("test@example.com", "Bob")
        mock_resend.Emails.send.assert_called_once()
        call_kwargs = mock_resend.Emails.send.call_args[0][0]
        assert "Bob" in call_kwargs["html"]

    async def test_send_billing_receipt(self, email_config, patch_resend):
        RSP, mock_resend = patch_resend
        provider = RSP(email_config)
        await provider.send_billing_receipt("test@example.com", "Bob", "$79.00", "Pro", "https://inv")
        mock_resend.Emails.send.assert_called_once()
        call_kwargs = mock_resend.Emails.send.call_args[0][0]
        assert "$79.00" in call_kwargs["html"]

    async def test_send_subscription_cancelled(self, email_config, patch_resend):
        RSP, mock_resend = patch_resend
        provider = RSP(email_config)
        await provider.send_subscription_cancelled("test@example.com", "Bob", "Pro", "June 15")
        mock_resend.Emails.send.assert_called_once()
        call_kwargs = mock_resend.Emails.send.call_args[0][0]
        assert "cancelled" in call_kwargs["subject"].lower()

    async def test_send_subscription_renewed(self, email_config, patch_resend):
        RSP, mock_resend = patch_resend
        provider = RSP(email_config)
        await provider.send_subscription_renewed("test@example.com", "Bob", "Pro", "$79", "July 1")
        mock_resend.Emails.send.assert_called_once()

    async def test_uses_from_address(self, email_config, patch_resend):
        RSP, mock_resend = patch_resend
        provider = RSP(email_config)
        await provider.send_verification_email("test@example.com", "https://verify")
        call_kwargs = mock_resend.Emails.send.call_args[0][0]
        assert "Loqi" in call_kwargs["from"]
        assert "noreply@loqi.ai" in call_kwargs["from"]

    async def test_uses_reply_to(self, email_config, patch_resend):
        RSP, mock_resend = patch_resend
        provider = RSP(email_config)
        await provider.send_verification_email("test@example.com", "https://verify")
        call_kwargs = mock_resend.Emails.send.call_args[0][0]
        assert call_kwargs["reply_to"] == ["support@loqi.ai"]

    async def test_includes_html_and_plain_text(self, email_config, patch_resend):
        RSP, mock_resend = patch_resend
        provider = RSP(email_config)
        await provider.send_verification_email("test@example.com", "https://verify")
        call_kwargs = mock_resend.Emails.send.call_args[0][0]
        assert call_kwargs["html"]
        assert call_kwargs["text"]

    async def test_includes_tags(self, email_config, patch_resend):
        RSP, mock_resend = patch_resend
        provider = RSP(email_config)
        await provider.send_verification_email("test@example.com", "https://verify")
        call_kwargs = mock_resend.Emails.send.call_args[0][0]
        assert "tags" in call_kwargs
        assert {"name": "template", "value": "verification"} in call_kwargs["tags"]

    async def test_send_failure_raises_error(self, email_config, patch_resend):
        RSP, mock_resend = patch_resend
        mock_resend.Emails.send.side_effect = Exception("API error")
        provider = RSP(email_config)
        with pytest.raises(Exception, match="API error"):
            await provider.send_verification_email("test@example.com", "https://verify")


# ─── Provider Factory Tests ────────────────────────────────────


class TestEmailProviderFactory:

    def test_create_console_provider(self):
        from services.identity.api import _create_email_provider
        config = EmailConfig(provider="console")
        provider = _create_email_provider(config)
        assert isinstance(provider, ConsoleEmailProvider)

    def test_create_resend_provider(self):
        mock = _make_mock_resend()
        with patch.dict("sys.modules", {"resend": mock}):
            from services.identity.api import _create_email_provider
            from services.email.resend_provider import ResendEmailProvider
            config = EmailConfig(provider="resend", api_key="re_key", from_email="test@test.com")
            provider = _create_email_provider(config)
            assert isinstance(provider, ResendEmailProvider)

    def test_default_provider_is_console(self):
        from services.identity.api import _create_email_provider
        provider = _create_email_provider()
        assert isinstance(provider, ConsoleEmailProvider)


# ─── EmailConfig Tests ───────────────────────────────────────────────


class TestEmailConfig:

    def test_default_values(self):
        config = EmailConfig()
        assert config.provider == "console"
        assert config.from_email == "noreply@loqi.ai"
        assert config.app_url == "http://localhost:3000"

    def test_custom_values(self):
        config = EmailConfig(
            provider="resend",
            api_key="re_key",
            from_email="hello@example.com",
            app_url="https://app.example.com",
        )
        assert config.provider == "resend"
        assert config.api_key == "re_key"
        assert config.from_email == "hello@example.com"
        assert config.app_url == "https://app.example.com"
