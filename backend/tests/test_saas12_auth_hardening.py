"""SaaS-1.2 — authentication lifecycle hardening tests.

Focused regression tests for the lifecycle issues found in the SaaS-1.2 audit:

- email canonicalization (case-insensitive signup/login, no case-duplicate)
- refresh-token family integrity (concurrent-rotation race guard)
- durable repository wiring under the SUPABASE provider
- safe error paths (no secret/raw-token leakage)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from services.identity.api import (
    _make_identity_repositories,
    reset_auth_service,
    set_auth_service,
)
from services.identity.exceptions import (
    EmailAlreadyExistsException,
    InvalidCredentialsException,
    RefreshTokenRevokedException,
)
from services.identity.models import RegistrationSession, RefreshToken
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
from services.identity.services.token_service import _is_unique_violation
from services.security.crypto import (
    InMemoryCryptoService,
    reset_crypto_service,
    set_crypto_service,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_crypto_service()
    reset_auth_service()


def _build_service():
    crypto = InMemoryCryptoService()
    set_crypto_service(crypto)
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
        email_provider=_DummyEmailProvider(),
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
    set_auth_service(svc)
    return svc, repos


class _DummyEmailProvider:
    async def send_verification_email(self, to, verification_url):
        pass

    async def send_password_reset_email(self, to, reset_url):
        pass


async def _register_user(svc, email):
    reg = await svc.begin_registration(email)
    await svc.verify_email(reg.raw_token)
    return await svc.complete_registration(
        reg.registration_session.id, email.split("@")[0], "StrongPass123!",
        f"{email.split('@')[0]} Org",
    )


# ─── 1. Email canonicalization ────────────────────────────────────────


class TestEmailNormalization:

    @pytest.mark.asyncio
    async def test_signup_normalizes_email(self):
        svc, repos = _build_service()
        await _register_user(svc, "MixedCase@Example.COM")
        stored = await repos["ei_repo"].find_by_email("mixedcase@example.com")
        assert stored is not None
        assert str(stored.email) == "mixedcase@example.com"

    @pytest.mark.asyncio
    async def test_case_variant_duplicate_rejected(self):
        svc, _ = _build_service()
        await _register_user(svc, "dupcase@example.com")
        with pytest.raises(EmailAlreadyExistsException):
            await svc.begin_registration("DupCase@Example.com")

    @pytest.mark.asyncio
    async def test_login_case_insensitive(self):
        svc, _ = _build_service()
        await _register_user(svc, "login-case@example.com")
        result = await svc.login("LOGIN-CASE@EXAMPLE.COM", "StrongPass123!")
        assert result.session is not None

    @pytest.mark.asyncio
    async def test_second_signup_session_reuses_email_identity(self):
        """When a second pending signup exists for an already-verified address
        (possible via a signup race), verification must reuse the existing
        email identity instead of inserting a duplicate (migration 022 unique
        index would reject the second row in production)."""
        svc, repos = _build_service()
        reg1 = await svc.begin_registration("reuse@example.com")
        await svc.verify_email(reg1.raw_token)

        # Simulate the racy second signup session, bypassing begin_registration's
        # duplicate guards (which are the primary protection).
        token2, raw2 = await svc._verification.create_verification_token(
            "reuse@example.com", "verify_email",
        )
        reg2 = await repos["reg_session_repo"].save(RegistrationSession(
            email="reuse@example.com",
            verification_token_id=token2.id,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        ))
        await svc.verify_email(raw2)

        identities = [
            ei for ei in repos["ei_repo"]._all() if str(ei.email) == "reuse@example.com"
        ]
        assert len(identities) == 1

        completed = await svc.complete_registration(
            reg2.id, "Reuse", "StrongPass123!", "Reuse Org",
        )
        assert completed.user is not None


# ─── 2. Refresh-token family integrity ────────────────────────────────


class TestRefreshFamilyIntegrity:

    @pytest.mark.asyncio
    async def test_concurrent_rotation_detected_as_replay(self):
        svc, repos = _build_service()
        await _register_user(svc, "race@example.com")
        login = await svc.login("race@example.com", "StrongPass123!")

        current = await repos["rt_repo"].find_by_hash(
            str(svc._crypto.hash_token(login.refresh_token)),
        )
        # Simulate a concurrent rotation that already minted an active sibling
        # token in the same family.
        sibling = RefreshToken(
            session_id=current.session_id,
            token_hash=svc._crypto.hash_token("sibling-token"),
            family=current.family,
            sequence=current.sequence + 1,
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        await repos["rt_repo"].save(sibling)

        with pytest.raises(RefreshTokenRevokedException):
            await svc.refresh(login.refresh_token)

        # The whole family and the session are revoked.
        for token in await repos["rt_repo"].find_by_family(current.family):
            assert token.is_revoked
        session = await repos["session_repo"].get(current.session_id)
        assert session is not None and session.is_revoked

    def test_unique_violation_detection(self):
        class _Err(Exception):
            def __init__(self, code, message):
                self.code = code
                self.message = message
                super().__init__(message)

        assert _is_unique_violation(_Err("23505", "duplicate key value"))
        assert _is_unique_violation(Exception("duplicate key value violates unique constraint"))
        assert not _is_unique_violation(Exception("connection reset"))


# ─── 3. Durable repository wiring (SUPABASE provider) ─────────────────


class TestDurableWiring:

    def test_supabase_provider_wires_durable_auth_repos(self, monkeypatch):
        from services.persistence import RepositoryProvider
        from services.persistence.repositories import (
            SupabaseEmailIdentityRepository,
            SupabasePasswordCredentialRepository,
            SupabaseRegistrationSessionRepository,
            SupabaseVerificationTokenRepository,
        )

        import services.identity.api as api_module
        monkeypatch.setattr(api_module, "REPOSITORY_PROVIDER", RepositoryProvider.SUPABASE)
        repos = api_module._make_identity_repositories()
        assert isinstance(repos["ei_repo"], SupabaseEmailIdentityRepository)
        assert isinstance(repos["pc_repo"], SupabasePasswordCredentialRepository)
        assert isinstance(repos["reg_session_repo"], SupabaseRegistrationSessionRepository)
        assert isinstance(repos["vt_repo"], SupabaseVerificationTokenRepository)

        monkeypatch.setattr(api_module, "REPOSITORY_PROVIDER", RepositoryProvider.IN_MEMORY)
        repos = api_module._make_identity_repositories()
        assert isinstance(repos["ei_repo"], InMemoryEmailIdentityRepository)

    def test_in_memory_provider_keeps_legacy_repos(self):
        from services.persistence import RepositoryProvider
        import services.identity.api as api_module
        import services.identity.repositories as id_repos
        from services.persistence.repositories import SupabaseUserRepository

        from services.identity.api import _make_identity_repositories as _m
        original = api_module.REPOSITORY_PROVIDER
        try:
            api_module.REPOSITORY_PROVIDER = RepositoryProvider.IN_MEMORY
            repos = _m()
        finally:
            api_module.REPOSITORY_PROVIDER = original
        assert isinstance(repos["user_repo"], SupabaseUserRepository)
        assert isinstance(repos["ei_repo"], id_repos.InMemoryEmailIdentityRepository)


# ─── 4. Safe error paths / no leakage ─────────────────────────────────


class TestNoLeakage:

    @pytest.mark.asyncio
    async def test_invalid_credentials_do_not_leak_account_state(self):
        svc, _ = _build_service()
        await _register_user(svc, "alice_leak@example.com")
        # Unknown email and wrong password produce identical messages.
        m1 = "Invalid email or password"
        with pytest.raises(InvalidCredentialsException) as e1:
            await svc.login("nobody@example.com", "WrongPass123!")
        with pytest.raises(InvalidCredentialsException) as e2:
            await svc.login("alice_leak@example.com", "WrongPass123!")
        assert e1.value.message == m1 and e2.value.message == m1

    @pytest.mark.asyncio
    async def test_raw_refresh_token_never_stored(self):
        svc, repos = _build_service()
        await _register_user(svc, "rawtok@example.com")
        login = await svc.login("rawtok@example.com", "StrongPass123!")
        raw = login.refresh_token
        assert raw not in {str(t.token_hash) for t in repos["rt_repo"]._all()}
        # Only the SHA-256 hash is persisted.
        stored_hashes = [str(t.token_hash) for t in repos["rt_repo"]._all()]
        assert str(svc._crypto.hash_token(raw)) in stored_hashes