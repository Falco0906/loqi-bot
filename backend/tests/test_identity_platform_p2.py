"""Tests for M1.1 — Identity Core Foundation (Part 2: Services & Repositories)."""

import pytest

from services.identity.config import IDENTITY_CONFIG
from services.identity.exceptions import (
    InvalidCredentialsException,
    InvalidVerificationTokenException,
    PasswordPolicyViolationException,
    SessionLimitExceededException,
    SessionRevokedException,
    RefreshTokenExpiredException,
    InvitationNotFoundException,
    InvitationExpiredException,
)
from services.identity.models import (
    ExternalIdentity,
    MembershipStatus,
    VerificationTokenPurpose,
    InvitationStatus,
)
from services.identity.services import (
    InvitationService,
    MembershipService,
    OrganizationService,
    PasswordService,
    SessionService,
    TokenService,
    UserService,
    VerificationService,
)
from services.identity.repositories import (
    InMemoryEmailIdentityRepository,
    InMemoryExternalIdentityRepository,
    InMemoryInvitationRepository,
    InMemoryMembershipRepository,
    InMemoryOrganizationRepository,
    InMemoryPasswordCredentialRepository,
    InMemoryPasswordResetRepository,
    InMemoryRefreshTokenRepository,
    InMemorySessionRepository,
    InMemoryUserRepository,
    InMemoryVerificationTokenRepository,
)
from services.identity.types import PasswordHash
from services.security.crypto import (
    InMemoryCryptoService,
    set_crypto_service,
    reset_crypto_service,
)


# ─── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset():
    reset_crypto_service()
    yield
    reset_crypto_service()


@pytest.fixture
def crypto():
    svc = InMemoryCryptoService()
    set_crypto_service(svc)
    return svc


@pytest.fixture
def repos():
    return {
        "user": InMemoryUserRepository(),
        "email_identity": InMemoryEmailIdentityRepository(),
        "password_credential": InMemoryPasswordCredentialRepository(),
        "org": InMemoryOrganizationRepository(),
        "membership": InMemoryMembershipRepository(),
        "session": InMemorySessionRepository(),
        "refresh_token": InMemoryRefreshTokenRepository(),
        "verification_token": InMemoryVerificationTokenRepository(),
        "password_reset": InMemoryPasswordResetRepository(),
        "invitation": InMemoryInvitationRepository(),
    }


@pytest.fixture
def svc(repos, crypto):
    return {
        "user": UserService(repos["user"], repos["email_identity"]),
        "org": OrganizationService(repos["org"], repos["membership"]),
        "membership": MembershipService(repos["membership"], repos["user"], repos["org"]),
        "verification": VerificationService(repos["verification_token"], repos["email_identity"], crypto),
        "password": PasswordService(repos["password_credential"], repos["user"], crypto),
        "session": SessionService(repos["session"], repos["refresh_token"]),
        "token": TokenService(repos["refresh_token"], repos["session"], crypto),
        "invitation": InvitationService(repos["invitation"], repos["membership"], repos["org"], repos["user"], crypto),
    }


# ═══════════════════════════════════════════════════════════════════════
# 8. Repository Tests
# ═══════════════════════════════════════════════════════════════════════

class TestUserRepository:
    @pytest.mark.asyncio
    async def test_save_and_get(self):
        repo = InMemoryUserRepository()
        user = await repo.save(await _make_user(repo))
        fetched = await repo.get(user.id)
        assert fetched is not None
        assert fetched.id == user.id

    @pytest.mark.asyncio
    async def test_delete(self):
        repo = InMemoryUserRepository()
        user = await repo.save(await _make_user(repo))
        assert await repo.delete(user.id)
        assert await repo.get(user.id) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self):
        repo = InMemoryUserRepository()
        assert not await repo.delete("nonexistent")


class TestEmailIdentityRepository:
    @pytest.mark.asyncio
    async def test_find_by_email(self):
        repo = InMemoryEmailIdentityRepository()
        from services.identity.models import EmailIdentity
        ei = EmailIdentity(email="test@example.com", user_id="u1")
        await repo.save(ei)
        found = await repo.find_by_email("test@example.com")
        assert found is not None
        assert found.user_id == "u1"

    @pytest.mark.asyncio
    async def test_find_primary_by_user_id(self):
        repo = InMemoryEmailIdentityRepository()
        from services.identity.models import EmailIdentity
        ei1 = EmailIdentity(email="a@b.com", user_id="u1", is_primary=True)
        ei2 = EmailIdentity(email="c@d.com", user_id="u1", is_primary=False)
        await repo.save(ei1)
        await repo.save(ei2)
        primary = await repo.find_primary_by_user_id("u1")
        assert primary is not None
        assert str(primary.email) == "a@b.com"

    @pytest.mark.asyncio
    async def test_find_by_user_id(self):
        repo = InMemoryEmailIdentityRepository()
        from services.identity.models import EmailIdentity
        await repo.save(EmailIdentity(email="a@b.com", user_id="u1"))
        await repo.save(EmailIdentity(email="c@d.com", user_id="u1"))
        results = await repo.find_by_user_id("u1")
        assert len(results) == 2


class TestSessionRepository:
    @pytest.mark.asyncio
    async def test_count_active(self):
        repo = InMemorySessionRepository()
        from services.identity.models import Session
        from datetime import datetime, timezone, timedelta
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        await repo.save(Session(user_id="u1", expires_at=future))
        await repo.save(Session(user_id="u1", expires_at=future))
        assert await repo.count_active_by_user_id("u1") == 2

    @pytest.mark.asyncio
    async def test_revoke_all_for_user(self):
        repo = InMemorySessionRepository()
        from services.identity.models import Session
        from datetime import datetime, timezone, timedelta
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        s1 = Session(user_id="u1", expires_at=future)
        s2 = Session(user_id="u1", expires_at=future)
        await repo.save(s1)
        await repo.save(s2)
        count = await repo.revoke_all_for_user("u1")
        assert count == 2
        assert s1.is_revoked


class TestRefreshTokenRepository:
    @pytest.mark.asyncio
    async def test_find_active_by_session_id(self):
        repo = InMemoryRefreshTokenRepository()
        from services.identity.models import RefreshToken
        from datetime import datetime, timezone, timedelta
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        rt = RefreshToken(session_id="s1", family="f1", expires_at=future)
        await repo.save(rt)
        found = await repo.find_active_by_session_id("s1")
        assert found is not None

    @pytest.mark.asyncio
    async def test_revoke_family(self):
        repo = InMemoryRefreshTokenRepository()
        from services.identity.models import RefreshToken
        from datetime import datetime, timezone, timedelta
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        rt1 = RefreshToken(session_id="s1", family="f1", expires_at=future)
        rt2 = RefreshToken(session_id="s2", family="f1", expires_at=future)
        await repo.save(rt1)
        await repo.save(rt2)
        count = await repo.revoke_family("f1")
        assert count == 2
        assert rt1.is_revoked


class TestInvitationRepository:
    @pytest.mark.asyncio
    async def test_find_pending_by_email(self):
        repo = InMemoryInvitationRepository()
        from services.identity.models import Invitation
        from datetime import datetime, timezone, timedelta
        future = datetime.now(timezone.utc) + timedelta(days=7)
        inv = Invitation(organization_id="o1", invitee_email="a@b.com", expires_at=future)
        await repo.save(inv)
        found = await repo.find_pending_by_email("a@b.com")
        assert len(found) == 1

    @pytest.mark.asyncio
    async def test_expire_old(self):
        repo = InMemoryInvitationRepository()
        from services.identity.models import Invitation
        from datetime import datetime, timezone, timedelta
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        inv = Invitation(organization_id="o1", invitee_email="a@b.com", expires_at=past)
        await repo.save(inv)
        count = await repo.expire_old_invitations()
        assert count == 1
        assert inv.status == InvitationStatus.EXPIRED


class TestExternalIdentityRepository:
    @pytest.mark.asyncio
    async def test_save_and_get(self):
        repo = InMemoryExternalIdentityRepository()
        ei = ExternalIdentity(user_id="u1", provider_type="google", provider_subject="sub_123")
        saved = await repo.save(ei)
        fetched = await repo.get(saved.id)
        assert fetched is not None
        assert fetched.id == ei.id
        assert fetched.provider_type == "google"

    @pytest.mark.asyncio
    async def test_find_by_user_id(self):
        repo = InMemoryExternalIdentityRepository()
        await repo.save(ExternalIdentity(user_id="u1", provider_type="google", provider_subject="g1"))
        await repo.save(ExternalIdentity(user_id="u1", provider_type="github", provider_subject="gh1"))
        await repo.save(ExternalIdentity(user_id="u2", provider_type="google", provider_subject="g2"))
        results = await repo.find_by_user_id("u1")
        assert len(results) == 2
        assert all(ei.user_id == "u1" for ei in results)

    @pytest.mark.asyncio
    async def test_find_by_provider(self):
        repo = InMemoryExternalIdentityRepository()
        await repo.save(ExternalIdentity(user_id="u1", provider_type="google", provider_subject="sub_abc"))
        found = await repo.find_by_provider("google", "sub_abc")
        assert found is not None
        assert found.user_id == "u1"

    @pytest.mark.asyncio
    async def test_find_by_provider_not_found(self):
        repo = InMemoryExternalIdentityRepository()
        result = await repo.find_by_provider("google", "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_by_email(self):
        repo = InMemoryExternalIdentityRepository()
        await repo.save(ExternalIdentity(
            user_id="u1", provider_type="google", provider_subject="123",
            email="ext@test.com",
        ))
        results = await repo.find_by_email("ext@test.com")
        assert len(results) == 1
        assert results[0].user_id == "u1"

    @pytest.mark.asyncio
    async def test_delete(self):
        repo = InMemoryExternalIdentityRepository()
        ei = await repo.save(ExternalIdentity(user_id="u1", provider_type="google", provider_subject="123"))
        assert await repo.delete(ei.id)
        assert await repo.get(ei.id) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self):
        repo = InMemoryExternalIdentityRepository()
        assert not await repo.delete("nonexistent")


# ═══════════════════════════════════════════════════════════════════════
# 9. Service Tests
# ═══════════════════════════════════════════════════════════════════════

class TestUserService:
    @pytest.mark.asyncio
    async def test_create_user(self, svc):
        user, email_identity, event = await svc["user"].create_user("Alice", "alice@test.com")
        assert user.display_name == "Alice"
        assert email_identity.user_id == user.id
        assert event.event_type.value == "user.created"

    @pytest.mark.asyncio
    async def test_get_user_not_found(self, svc):
        with pytest.raises(Exception):
            await svc["user"].get_user("nonexistent")

    @pytest.mark.asyncio
    async def test_get_user_by_email(self, svc):
        user, _, _ = await svc["user"].create_user("Bob", "bob@test.com")
        found = await svc["user"].get_user_by_email("bob@test.com")
        assert found is not None
        assert found.id == user.id

    @pytest.mark.asyncio
    async def test_update_user(self, svc):
        user, _, _ = await svc["user"].create_user("Charlie", "c@test.com")
        updated = await svc["user"].update_user(user.id, display_name="Charlie Updated")
        assert updated.display_name == "Charlie Updated"

    @pytest.mark.asyncio
    async def test_soft_delete_user(self, svc):
        user, _, _ = await svc["user"].create_user("Dave", "d@test.com")
        await svc["user"].soft_delete_user(user.id)
        fetched = await svc["user"].get_user(user.id)
        assert fetched.is_deleted


class TestOrganizationService:
    @pytest.mark.asyncio
    async def test_create_organization(self, svc):
        user, _, _ = await svc["user"].create_user("Owner", "owner@test.com")
        org, membership, event = await svc["org"].create_organization("Acme Corp", user.id)
        assert org.name == "Acme Corp"
        assert org.slug == "acme-corp"
        assert membership.role == "owner"
        assert membership.is_active

    @pytest.mark.asyncio
    async def test_get_organization_not_found(self, svc):
        with pytest.raises(Exception):
            await svc["org"].get_organization("nonexistent")

    @pytest.mark.asyncio
    async def test_find_by_slug(self, svc):
        user, _, _ = await svc["user"].create_user("O", "o@test.com")
        org, _, _ = await svc["org"].create_organization("My Org", user.id)
        found = await svc["org"].find_by_slug("my-org")
        assert found is not None
        assert found.id == org.id

    @pytest.mark.asyncio
    async def test_list_organizations_for_user(self, svc):
        user, _, _ = await svc["user"].create_user("Multi", "m@test.com")
        await svc["org"].create_organization("Org1", user.id)
        await svc["org"].create_organization("Org2", user.id)
        orgs = await svc["org"].list_organizations_for_user(user.id)
        assert len(orgs) == 2


class TestMembershipService:
    @pytest.mark.asyncio
    async def test_add_and_activate_member(self, svc, repos):
        user1, _, _ = await svc["user"].create_user("Owner", "o@test.com")
        user2, _, _ = await svc["user"].create_user("Member", "m@test.com")
        org, _, _ = await svc["org"].create_organization("Test Org", user1.id)

        membership = await svc["membership"].add_member(
            user2.id, org.id, role="member", invited_by=user1.id,
        )
        assert membership.user_id == user2.id
        assert membership.status == MembershipStatus.ACTIVE

        is_member = await svc["membership"].is_member_of(user2.id, org.id)
        assert is_member

    @pytest.mark.asyncio
    async def test_change_role(self, svc):
        owner, _, _ = await svc["user"].create_user("Owner", "o@test.com")
        member, _, _ = await svc["user"].create_user("Member", "m@test.com")
        org, _, _ = await svc["org"].create_organization("Org", owner.id)
        ms = await svc["membership"].add_member(member.id, org.id)
        updated = await svc["membership"].change_role(ms.id, "admin")
        assert updated.role == "admin"


class TestVerificationService:
    @pytest.mark.asyncio
    async def test_create_and_verify_email(self, svc, repos):
        _, email_identity, _ = await svc["user"].create_user("Test", "verify@test.com")
        token, raw = await svc["verification"].create_verification_token(
            "verify@test.com", VerificationTokenPurpose.VERIFY_EMAIL,
        )
        assert raw is not None
        verified, event = await svc["verification"].verify_email("verify@test.com", raw)
        assert verified.is_verified
        assert event.event_type.value == "email.verified"

    @pytest.mark.asyncio
    async def test_verify_invalid_token(self, svc):
        with pytest.raises(InvalidVerificationTokenException):
            await svc["verification"].verify_email("nonexistent@test.com", "bad-token")

    @pytest.mark.asyncio
    async def test_verify_wrong_token(self, svc):
        _, _, _ = await svc["user"].create_user("Test", "wrong@test.com")
        _, raw = await svc["verification"].create_verification_token(
            "wrong@test.com", VerificationTokenPurpose.VERIFY_EMAIL,
        )
        with pytest.raises(InvalidVerificationTokenException):
            await svc["verification"].verify_email("wrong@test.com", "wrong-" + raw)


class TestPasswordService:
    @pytest.mark.asyncio
    async def test_set_and_verify_password(self, svc):
        user, _, _ = await svc["user"].create_user("PwdUser", "pwd@test.com")
        _, event = await svc["password"].set_password(user.id, "SecurePass123!")
        assert event.event_type.value == "password.set"
        assert await svc["password"].verify_password(user.id, "SecurePass123!")
        assert not await svc["password"].verify_password(user.id, "wrong")

    @pytest.mark.asyncio
    async def test_password_policy_too_short(self, svc):
        user, _, _ = await svc["user"].create_user("Weak", "weak@test.com")
        with pytest.raises(PasswordPolicyViolationException, match="at least 12"):
            await svc["password"].set_password(user.id, "Short1!")

    @pytest.mark.asyncio
    async def test_password_policy_no_upper(self, svc):
        user, _, _ = await svc["user"].create_user("NoUpper", "noupper@test.com")
        with pytest.raises(PasswordPolicyViolationException, match="uppercase"):
            await svc["password"].set_password(user.id, "alllowercase1!")

    @pytest.mark.asyncio
    async def test_password_policy_no_digit(self, svc):
        user, _, _ = await svc["user"].create_user("NoDigit", "nodigit@test.com")
        with pytest.raises(PasswordPolicyViolationException, match="digit"):
            await svc["password"].set_password(user.id, "NoDigitsHere!!")

    @pytest.mark.asyncio
    async def test_change_password(self, svc):
        user, _, _ = await svc["user"].create_user("Changer", "change@test.com")
        await svc["password"].set_password(user.id, "OldPass123456!")
        _, event = await svc["password"].change_password(
            user.id, "OldPass123456!", "NewPass789012!",
        )
        assert event.event_type.value == "password.changed"
        assert await svc["password"].verify_password(user.id, "NewPass789012!")

    @pytest.mark.asyncio
    async def test_change_password_wrong_current(self, svc):
        user, _, _ = await svc["user"].create_user("Changer2", "c2@test.com")
        await svc["password"].set_password(user.id, "RealPass12345!")
        with pytest.raises(InvalidCredentialsException):
            await svc["password"].change_password(user.id, "WrongPass123!", "NewPass456789!")

    @pytest.mark.asyncio
    async def test_has_password(self, svc):
        user, _, _ = await svc["user"].create_user("Has", "has@test.com")
        assert not await svc["password"].has_password(user.id)
        await svc["password"].set_password(user.id, "NowHasPass123!")
        assert await svc["password"].has_password(user.id)


class TestSessionService:
    @pytest.mark.asyncio
    async def test_create_session(self, svc):
        session, event = await svc["session"].create_session(
            user_id="u1", organization_id="o1",
            provider_type="email", device_info="test-device",
        )
        assert session.user_id == "u1"
        assert session.is_active
        assert event.event_type.value == "session.created"

    @pytest.mark.asyncio
    async def test_session_limit(self, svc):
        from datetime import datetime, timezone, timedelta
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        for _ in range(IDENTITY_CONFIG.sessions.max_active_sessions_per_user):
            await svc["session"].create_session(
                user_id="limited", organization_id="o1",
            )
        with pytest.raises(SessionLimitExceededException):
            await svc["session"].create_session(
                user_id="limited", organization_id="o1",
            )

    @pytest.mark.asyncio
    async def test_validate_session(self, svc):
        session, _ = await svc["session"].create_session(
            user_id="u1", organization_id="o1",
        )
        validated = await svc["session"].validate_session(session.id)
        assert validated.id == session.id

    @pytest.mark.asyncio
    async def test_validate_revoked_session(self, svc):
        session, _ = await svc["session"].create_session(
            user_id="u2", organization_id="o1",
        )
        await svc["session"].revoke_session(session.id)
        with pytest.raises(SessionRevokedException):
            await svc["session"].validate_session(session.id)


class TestTokenService:
    @pytest.mark.asyncio
    async def test_create_refresh_token(self, svc):
        session, _ = await svc["session"].create_session(
            user_id="u1", organization_id="o1",
        )
        token, raw = await svc["token"].create_refresh_token(session.id)
        assert token.session_id == session.id
        assert token.sequence == 1
        assert token.family is not None
        assert raw is not None

    @pytest.mark.asyncio
    async def test_rotate_refresh_token(self, svc):
        session, _ = await svc["session"].create_session(
            user_id="u1", organization_id="o1",
        )
        token, raw = await svc["token"].create_refresh_token(session.id)
        new_token, new_raw = await svc["token"].rotate_refresh_token(raw)
        assert new_token.sequence == 2
        assert new_token.family == token.family
        assert new_raw is not None

    @pytest.mark.asyncio
    async def test_rotate_revoked_token(self, svc):
        session, _ = await svc["session"].create_session(
            user_id="u1", organization_id="o1",
        )
        token, raw = await svc["token"].create_refresh_token(session.id)
        # First rotation succeeds
        await svc["token"].rotate_refresh_token(raw)
        # Second rotation with same raw should detect theft
        with pytest.raises(Exception):
            await svc["token"].rotate_refresh_token(raw)

    @pytest.mark.asyncio
    async def test_revoke_all_for_session(self, svc):
        session, _ = await svc["session"].create_session(
            user_id="u1", organization_id="o1",
        )
        await svc["token"].create_refresh_token(session.id)
        count = await svc["token"].revoke_all_for_session(session.id)
        assert count == 1


class TestInvitationService:
    @pytest.mark.asyncio
    async def test_create_invitation(self, svc):
        owner, _, _ = await svc["user"].create_user("Owner", "o@test.com")
        org, _, _ = await svc["org"].create_organization("Org", owner.id)
        invitation, event = await svc["invitation"].create_invitation(
            org.id, owner.id, "invitee@test.com",
        )
        assert invitation.organization_id == org.id
        assert invitation.is_pending
        assert event.event_type.value == "member.invited"

    @pytest.mark.asyncio
    async def test_accept_invitation(self, svc):
        owner, _, _ = await svc["user"].create_user("Owner", "o@test.com")
        invitee, _, _ = await svc["user"].create_user("Invitee", "i@test.com")
        org, _, _ = await svc["org"].create_organization("Org", owner.id)
        invitation, _ = await svc["invitation"].create_invitation(
            org.id, owner.id, "i@test.com",
        )
        accepted = await svc["invitation"].accept_invitation(invitation.id, invitee.id)
        assert accepted.status == InvitationStatus.ACCEPTED

        is_member = await svc["membership"].is_member_of(invitee.id, org.id)
        assert is_member

    @pytest.mark.asyncio
    async def test_revoke_invitation(self, svc):
        owner, _, _ = await svc["user"].create_user("Owner", "o@test.com")
        org, _, _ = await svc["org"].create_organization("Org", owner.id)
        invitation, _ = await svc["invitation"].create_invitation(
            org.id, owner.id, "r@test.com",
        )
        revoked = await svc["invitation"].revoke_invitation(invitation.id)
        assert revoked.status == InvitationStatus.REVOKED

    @pytest.mark.asyncio
    async def test_get_invitation_not_found(self, svc):
        with pytest.raises(InvitationNotFoundException):
            await svc["invitation"].get_invitation("nonexistent")


# ═══════════════════════════════════════════════════════════════════════
# 10. Integration: Complete Lifecycle
# ═══════════════════════════════════════════════════════════════════════

class TestUserRegistrationLifecycle:
    @pytest.mark.asyncio
    async def test_complete_registration(self, svc):
        """User: create → verify email → set password → create org → session."""
        user, email_id, _ = await svc["user"].create_user("Alice", "alice@test.com")

        token, raw = await svc["verification"].create_verification_token(
            "alice@test.com", VerificationTokenPurpose.VERIFY_EMAIL,
        )
        verified, _ = await svc["verification"].verify_email("alice@test.com", raw)
        assert verified.is_verified

        cred, _ = await svc["password"].set_password(user.id, "SecurePass12345!")
        assert cred.user_id == user.id

        org, membership, _ = await svc["org"].create_organization("Alice Corp", user.id)
        assert membership.is_active

        session, _ = await svc["session"].create_session(
            user_id=user.id, organization_id=org.id,
        )
        assert session.is_active

        assert await svc["password"].verify_password(user.id, "SecurePass12345!")
        assert await svc["membership"].is_member_of(user.id, org.id)
        sessions = await svc["session"].list_active_sessions(user.id)
        assert len(sessions) >= 1


class TestSessionLifecycle:
    @pytest.mark.asyncio
    async def test_full_session_lifecycle(self, svc):
        session, _ = await svc["session"].create_session(
            user_id="u1", organization_id="o1",
        )

        validated = await svc["session"].validate_session(session.id)
        assert validated.is_active

        token, raw = await svc["token"].create_refresh_token(session.id)
        new_token, new_raw = await svc["token"].rotate_refresh_token(raw)
        assert new_token.sequence == 2

        await svc["session"].revoke_session(session.id)
        with pytest.raises(SessionRevokedException):
            await svc["session"].validate_session(session.id)


class TestInvitationLifecycle:
    @pytest.mark.asyncio
    async def test_full_invitation_lifecycle(self, svc):
        owner, _, _ = await svc["user"].create_user("Owner", "owner@org.com")
        invitee, _, _ = await svc["user"].create_user("Invitee", "inv@org.com")
        org, _, _ = await svc["org"].create_organization("Org", owner.id)

        invitation, _ = await svc["invitation"].create_invitation(
            org.id, owner.id, "inv@org.com",
        )
        assert invitation.is_pending

        await svc["invitation"].accept_invitation(invitation.id, invitee.id)

        assert await svc["membership"].is_member_of(invitee.id, org.id)
        members = await svc["membership"].list_members(org.id)
        assert len(members) == 2


# ═══════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════

async def _make_user(repo):
    from services.identity.models import User
    u = User(display_name="Test User")
    return await repo.save(u)
