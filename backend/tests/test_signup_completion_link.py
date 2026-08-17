"""Regression: signup-completion email-identity linking + atomicity + retry.

Guards the production failure `duplicate key value violates unique constraint
"email_identities_email_uidx"` in POST /api/v1/auth/signup/email/complete:

- TEST A: an existing verified email identity (created at verification and
  referenced by registration_sessions.email_identity_id) is reused/linked, not
  recreated.
- TEST B: a failed completion rolls back — no orphan identity_user, no partial
  org/credential/session, email identity not mislinked, session stays VERIFIED.
- TEST C: retry after a rolled-back failure succeeds and creates exactly one
  user + one email identity.
- TEST D: repeating a successful completion does not create another user or
  email identity (idempotent recovery).
"""

from __future__ import annotations

import asyncio

import pytest

from services.identity.models import RegistrationSessionStatus
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


class _DummyEmail:
    async def send_verification_email(self, to, verification_url):
        pass

    async def send_password_reset_email(self, to, reset_url):
        pass


def _build_service():
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
        email_provider=_DummyEmail(),
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
        password_reset_repo=repos["pr_repo"],
    )
    return svc, repos


async def _setup_verified(svc, email: str):
    """begin_registration + verify_email => a VERIFIED session with an
    existing verified email_identity whose id is stored on the session."""
    reg = await svc.begin_registration(email)
    await svc.verify_email(reg.raw_token)
    rs = await svc._reg_session_repo.get(reg.registration_session.id)
    assert rs.status == RegistrationSessionStatus.VERIFIED
    assert rs.email_identity_id
    return rs


class TestCompletionLinksExistingIdentity:

    @pytest.mark.asyncio
    async def test_a_reuses_existing_verified_email_identity(self):
        svc, repos = _build_service()
        rs = await _setup_verified(svc, "link@example.com")
        before_ei = len(repos["ei_repo"]._all())

        result = await svc.complete_registration(
            rs.id, "Link", "StrongPass123!", "Link Org",
        )

        assert result.user is not None and result.session is not None
        # Exactly one email identity for this email (no duplicate created).
        identities = [ei for ei in repos["ei_repo"]._all() if str(ei.email) == "link@example.com"]
        assert len(identities) == 1
        assert len(repos["ei_repo"]._all()) == before_ei
        # The pre-existing identity is linked to the new user.
        ei = identities[0]
        assert ei.user_id == result.user.id
        assert ei.is_verified is True
        assert ei.is_primary is True
        assert ei.verified_at is not None
        # Session completed; all expected records exist.
        rs_after = await repos["reg_session_repo"].get(rs.id)
        assert rs_after.status == RegistrationSessionStatus.COMPLETED
        assert len(repos["user_repo"]._all()) == 1
        assert len(repos["pc_repo"]._all()) == 1
        assert len(repos["org_repo"]._all()) == 1
        assert len(repos["session_repo"]._all()) == 1

    @pytest.mark.asyncio
    async def test_b_failed_completion_rolls_back(self, monkeypatch):
        svc, repos = _build_service()
        rs = await _setup_verified(svc, "rollback@example.com")

        orig = svc._token.create_refresh_token
        async def _boom(session_id):
            raise RuntimeError("injected failure")
        monkeypatch.setattr(svc._token, "create_refresh_token", _boom)

        with pytest.raises(RuntimeError):
            await svc.complete_registration(rs.id, "RB", "StrongPass123!", "RB Org")

        # No orphan identity_user; no partial credential/org/membership/session.
        assert len(repos["user_repo"]._all()) == 0
        assert len(repos["pc_repo"]._all()) == 0
        assert len(repos["org_repo"]._all()) == 0
        assert len(repos["mem_repo"]._all()) == 0
        assert len(repos["session_repo"]._all()) == 0
        # Email identity exists but is NOT linked to a (now deleted) user.
        identities = [ei for ei in repos["ei_repo"]._all() if str(ei.email) == "rollback@example.com"]
        assert len(identities) == 1
        assert identities[0].user_id == ""
        # Registration session remains retryable VERIFIED.
        rs_after = await repos["reg_session_repo"].get(rs.id)
        assert rs_after.status == RegistrationSessionStatus.VERIFIED

    @pytest.mark.asyncio
    async def test_c_retry_after_failure_succeeds(self, monkeypatch):
        svc, repos = _build_service()
        rs = await _setup_verified(svc, "retry@example.com")

        orig = svc._token.create_refresh_token
        async def _boom(session_id):
            raise RuntimeError("injected failure")
        monkeypatch.setattr(svc._token, "create_refresh_token", _boom)
        with pytest.raises(RuntimeError):
            await svc.complete_registration(rs.id, "Retry", "StrongPass123!", "Retry Org")

        # Restore and retry — must succeed, exactly one user + one email identity.
        monkeypatch.setattr(svc._token, "create_refresh_token", orig)
        result = await svc.complete_registration(rs.id, "Retry", "StrongPass123!", "Retry Org")

        assert result.user is not None
        assert len(repos["user_repo"]._all()) == 1
        identities = [ei for ei in repos["ei_repo"]._all() if str(ei.email) == "retry@example.com"]
        assert len(identities) == 1
        assert identities[0].user_id == result.user.id
        rs_after = await repos["reg_session_repo"].get(rs.id)
        assert rs_after.status == RegistrationSessionStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_d_repeat_successful_completion_no_duplicate(self):
        svc, repos = _build_service()
        rs = await _setup_verified(svc, "repeat@example.com")

        first = await svc.complete_registration(rs.id, "Repeat", "StrongPass123!", "Repeat Org")
        assert len(repos["user_repo"]._all()) == 1
        assert len(repos["ei_repo"]._all()) == 1

        # Second completion on an already-COMPLETED session must not create a
        # second user or email identity; it recovers with a fresh session.
        second = await svc.complete_registration(rs.id, "Repeat", "StrongPass123!", "Repeat Org")
        assert second.user.id == first.user.id
        assert len(repos["user_repo"]._all()) == 1
        identities = [ei for ei in repos["ei_repo"]._all() if str(ei.email) == "repeat@example.com"]
        assert len(identities) == 1
        # One session from completion + one from the recovery login.
        assert len(repos["session_repo"]._all()) == 2