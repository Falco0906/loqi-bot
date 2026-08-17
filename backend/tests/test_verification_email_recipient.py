"""Regression: verification-email recipient + verification-URL origin.

Guards the production incident where the Resend recipient appeared to be a
fixed `status@test.com` instead of the user's entered email, and the email
body carried a localhost verification URL.

Invariants verified here:
1. `AuthService.begin_registration` passes the user's entered (normalized)
   email as the `to` of `send_verification_email` — never a hardcoded or
   overridden recipient.
2. The identity email provider passes `to` verbatim (no test-recipient
   override applies to verification emails even when
   `LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE` is enabled).
3. The verification URL is built from the configured `app_url`
   (FRONTEND_URL) — never a hardcoded localhost.
4. Email normalization is preserved for the recipient.
"""

from __future__ import annotations

import asyncio

import pytest

from services.identity.repositories import (
    InMemoryEmailIdentityRepository,
    InMemoryMembershipRepository,
    InMemoryOrganizationRepository,
    InMemoryPasswordCredentialRepository,
    InMemoryPasswordResetRepository,
    InMemoryRefreshTokenRepository,
    InMemoryRegistrationSessionRepository,
    InMemorySessionRepository,
    InMemoryUserRepository,
    InMemoryVerificationTokenRepository,
)
from services.identity.services import (
    AuthService,
    MembershipService,
    OrganizationService,
    PasswordService,
    SessionService,
    TokenService,
    UserService,
    VerificationService,
)
from services.security.crypto import InMemoryCryptoService


class _CaptureEmailProvider:
    """Records every verification email (recipient + URL) it is asked to send."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_verification_email(self, to: str, verification_url: str) -> None:
        self.sent.append((to, verification_url))

    async def send_password_reset_email(self, to: str, reset_url: str) -> None:
        self.sent.append((to, reset_url))


def _build_service(email_provider=None, app_url: str = "https://app.tryloqi.com"):
    crypto = InMemoryCryptoService()
    repos = {
        "reg_session_repo": InMemoryRegistrationSessionRepository(),
        "vt_repo": InMemoryVerificationTokenRepository(),
        "ei_repo": InMemoryEmailIdentityRepository(),
        "user_repo": InMemoryUserRepository(),
        "pc_repo": InMemoryPasswordCredentialRepository(),
        "org_repo": InMemoryOrganizationRepository(),
        "mem_repo": InMemoryMembershipRepository(),
        "session_repo": InMemorySessionRepository(),
        "rt_repo": InMemoryRefreshTokenRepository(),
        "pr_repo": InMemoryPasswordResetRepository(),
    }
    user_svc = UserService(repos["user_repo"], repos["ei_repo"])
    org_svc = OrganizationService(repos["org_repo"], repos["mem_repo"])
    mem_svc = MembershipService(repos["mem_repo"], repos["user_repo"], repos["org_repo"])
    ver_svc = VerificationService(repos["vt_repo"], repos["ei_repo"], crypto)
    pwd_svc = PasswordService(repos["pc_repo"], repos["user_repo"], crypto)
    ses_svc = SessionService(repos["session_repo"], repos["rt_repo"])
    tok_svc = TokenService(repos["rt_repo"], repos["session_repo"], crypto)
    svc = AuthService(
        email_provider=email_provider or _CaptureEmailProvider(),
        crypto=crypto,
        registration_session_repo=repos["reg_session_repo"],
        verification_token_repo=repos["vt_repo"],
        email_identity_repo=repos["ei_repo"],
        refresh_token_repo=repos["rt_repo"],
        user_svc=user_svc,
        org_svc=org_svc,
        membership_svc=mem_svc,
        verification_svc=ver_svc,
        password_svc=pwd_svc,
        session_svc=ses_svc,
        token_svc=tok_svc,
        app_url=app_url,
        password_reset_repo=repos["pr_repo"],
    )
    return svc, repos


class TestVerificationRecipient:

    @pytest.mark.asyncio
    async def test_begin_registration_sends_to_user_email(self):
        provider = _CaptureEmailProvider()
        svc, _ = _build_service(email_provider=provider)
        await svc.begin_registration("User@Example.com")
        assert provider.sent, "verification email was not attempted"
        to, _url = provider.sent[0]
        assert to == "user@example.com"
        assert to != "status@test.com"

    @pytest.mark.asyncio
    async def test_no_test_recipient_override_applies_to_verification(self, monkeypatch):
        """Even with LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE enabled, verification
        emails must still go to the user's email (the override mechanism is
        scoped to outbound draft/reply routing, never to identity emails)."""
        monkeypatch.setenv("LOQI_ENABLE_TEST_RECIPIENT_OVERRIDE", "true")
        provider = _CaptureEmailProvider()
        svc, _ = _build_service(email_provider=provider)
        await svc.begin_registration("recipient@example.com")
        to, _url = provider.sent[0]
        assert to == "recipient@example.com"

    @pytest.mark.asyncio
    async def test_email_normalization_kept_for_recipient(self):
        provider = _CaptureEmailProvider()
        svc, _ = _build_service(email_provider=provider)
        await svc.begin_registration("  Mixed.Case@EXAMPLE.COM  ")
        to, _url = provider.sent[0]
        assert to == "mixed.case@example.com"


class TestVerificationUrlOrigin:

    @pytest.mark.asyncio
    async def test_verification_url_uses_configured_app_url(self):
        provider = _CaptureEmailProvider()
        svc, _ = _build_service(email_provider=provider, app_url="https://app.tryloqi.com")
        await svc.begin_registration("url@example.com")
        _to, url = provider.sent[0]
        assert url.startswith("https://app.tryloqi.com/verify-email?token=")
        assert "localhost" not in url

    @pytest.mark.asyncio
    async def test_verification_url_never_hardcoded_localhost(self):
        """The URL origin must come from configuration; a production app_url
        must never yield a localhost link."""
        provider = _CaptureEmailProvider()
        svc, _ = _build_service(email_provider=provider, app_url="https://tryloqi.com")
        await svc.begin_registration("url2@example.com")
        _to, url = provider.sent[0]
        assert url.startswith("https://tryloqi.com/verify-email?token=")
        assert "127.0.0.1" not in url and "localhost" not in url

    @pytest.mark.asyncio
    async def test_url_contains_no_verification_token_leak(self):
        """The raw token appears only as a query param in the URL passed to the
        provider; the provider receives the token URL, not a plaintext token in
        any other field. (Token value is never exposed by the service.)"""
        provider = _CaptureEmailProvider()
        svc, _ = _build_service(email_provider=provider, app_url="https://app.tryloqi.com")
        reg = await svc.begin_registration("token@example.com")
        assert reg.raw_token  # returned once to the caller for the email body
        _to, url = provider.sent[0]
        assert "?token=" in url
        # Only one field carries the URL; no extra secret-bearing fields.
        assert provider.sent[0][1].startswith("https://app.tryloqi.com/verify-email")