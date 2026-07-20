"""Tests for M1.1 — Identity Core Foundation (Part 1)."""

import pytest
from datetime import datetime, timezone, timedelta
from uuid import UUID

from services.identity.config import IDENTITY_CONFIG
from services.identity.contracts import (
    IdentityContext,
    ProviderType,
    AuthRequest,
    ExternalIdentity,
)
from services.identity.events import IdentityEvent, IdentityEventType
from services.identity.exceptions import (
    IdentityException,
    AuthenticationException,
    InvalidCredentialsException,
    EmailAlreadyExistsException,
    EmailNotVerifiedException,
    InvalidVerificationTokenException,
    VerificationTokenExpiredException,
    UserNotFoundException,
    OrganizationNotFoundException,
    MembershipNotFoundException,
    SessionNotFoundException,
    SessionRevokedException,
    RefreshTokenExpiredException,
    RefreshTokenRevokedException,
    PasswordPolicyViolationException,
    InvitationNotFoundException,
    SessionLimitExceededException,
)
from services.identity.models import (
    User,
    EmailIdentity,
    ExternalIdentity as ExternalIdentityModel,
    PasswordCredential,
    Organization,
    Membership,
    MembershipStatus,
    Session,
    RefreshToken,
    VerificationToken,
    VerificationTokenPurpose,
    Invitation,
    InvitationStatus,
    PasswordResetRequest,
)
from services.identity.repositories import (
    InMemoryEmailIdentityRepository,
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
from services.identity.types import (
    EmailAddress,
    PasswordHash,
    TokenHash,
    UserId,
    OrganizationId,
    SessionId,
)
from services.security.crypto import (
    InMemoryCryptoService,
    set_crypto_service,
    reset_crypto_service,
)


@pytest.fixture(autouse=True)
def _reset_services():
    reset_crypto_service()
    yield
    reset_crypto_service()


@pytest.fixture
def crypto() -> InMemoryCryptoService:
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
def services(repos, crypto):
    return {
        "user": UserService(repos["user"], repos["email_identity"]),
        "org": OrganizationService(repos["org"], repos["membership"]),
        "membership": MembershipService(
            repos["membership"], repos["user"], repos["org"],
        ),
        "verification": VerificationService(
            repos["verification_token"], repos["email_identity"], crypto,
        ),
        "password": PasswordService(
            repos["password_credential"], repos["user"], crypto,
        ),
        "session": SessionService(repos["session"], repos["refresh_token"]),
        "token": TokenService(
            repos["refresh_token"], repos["session"], crypto,
        ),
        "invitation": InvitationService(
            repos["invitation"], repos["membership"], repos["org"],
            repos["user"], crypto,
        ),
    }


class TestValueTypes:
    def test_email_address_valid(self):
        email = EmailAddress("user@example.com")
        assert str(email) == "user@example.com"

    def test_email_address_invalid(self):
        with pytest.raises(ValueError, match="Invalid email"):
            EmailAddress("not-an-email")

    def test_email_address_frozen(self):
        email = EmailAddress("a@b.com")
        with pytest.raises(AttributeError):
            email.value = "other@b.com"

    def test_password_hash(self):
        ph = PasswordHash("$argon2id$v=19$...")
        assert str(ph) == "$argon2id$v=19$..."

    def test_token_hash(self):
        th = TokenHash("abc123def456")
        assert str(th) == "abc123def456"

    def test_user_id_newtype(self):
        uid = UserId("u1")
        assert isinstance(uid, str)

    def test_organization_id_newtype(self):
        oid = OrganizationId("o1")
        assert isinstance(oid, str)

    def test_session_id_newtype(self):
        sid = SessionId("s1")
        assert isinstance(sid, str)


class TestExceptions:
    def test_base_exception(self):
        exc = IdentityException("base error")
        assert str(exc) == "base error"
        assert isinstance(exc, Exception)

    def test_authentication_exception(self):
        exc = AuthenticationException()
        assert isinstance(exc, IdentityException)

    def test_invalid_credentials(self):
        exc = InvalidCredentialsException()
        assert isinstance(exc, AuthenticationException)

    def test_email_already_exists(self):
        exc = EmailAlreadyExistsException("a@b.com")
        assert exc.email == "a@b.com"
        assert "a@b.com" in str(exc)

    def test_user_not_found(self):
        exc = UserNotFoundException("u1")
        assert exc.user_id == "u1"

    def test_organization_not_found(self):
        exc = OrganizationNotFoundException("o1")
        assert exc.organization_id == "o1"

    def test_session_limit_exceeded(self):
        exc = SessionLimitExceededException(25)
        assert exc.max_sessions == 25

    def test_password_policy(self):
        exc = PasswordPolicyViolationException("too weak")
        assert "too weak" in str(exc)

    def test_refresh_token_revoked_message(self):
        exc = RefreshTokenRevokedException()
        assert "revoked" in str(exc)


class TestDomainEvents:
    def test_user_created_event(self):
        event = IdentityEvent.user_created("u1", "a@b.com")
        assert event.event_type == IdentityEventType.USER_CREATED
        assert event.entity_id == "u1"
        assert event.data["email"] == "a@b.com"

    def test_email_verified_event(self):
        event = IdentityEvent.email_verified("u1", "a@b.com")
        assert event.event_type == IdentityEventType.EMAIL_VERIFIED

    def test_organization_created_event(self):
        event = IdentityEvent.organization_created("o1", "u1", "My Org")
        assert event.event_type == IdentityEventType.ORGANIZATION_CREATED
        assert event.actor_id == "u1"
        assert event.data["name"] == "My Org"

    def test_session_created_event(self):
        event = IdentityEvent.session_created("s1", "u1")
        assert event.event_type == IdentityEventType.SESSION_CREATED

    def test_session_revoked_event(self):
        event = IdentityEvent.session_revoked("s1", "u1")
        assert event.event_type == IdentityEventType.SESSION_REVOKED

    def test_password_reset_requested(self):
        event = IdentityEvent.password_reset_requested("u1")
        assert event.event_type == IdentityEventType.PASSWORD_RESET_REQUESTED

    def test_password_reset_completed(self):
        event = IdentityEvent.password_reset_completed("u1")
        assert event.event_type == IdentityEventType.PASSWORD_RESET_COMPLETED

    def test_member_invited(self):
        event = IdentityEvent.member_invited("o1", "u1", "invitee@b.com")
        assert event.event_type == IdentityEventType.MEMBER_INVITED
        assert event.data["invitee_email"] == "invitee@b.com"

    def test_member_joined(self):
        event = IdentityEvent.member_joined("o1", "u1")
        assert event.event_type == IdentityEventType.MEMBER_JOINED

    def test_password_set(self):
        event = IdentityEvent.password_set("u1")
        assert event.event_type == IdentityEventType.PASSWORD_SET

    def test_password_changed(self):
        event = IdentityEvent.password_changed("u1")
        assert event.event_type == IdentityEventType.PASSWORD_CHANGED

    def test_event_has_timestamp(self):
        event = IdentityEvent.user_created("u1", "a@b.com")
        assert event.timestamp is not None

    def test_event_enum_values(self):
        assert IdentityEventType.USER_CREATED.value == "user.created"
        assert IdentityEventType.EMAIL_VERIFIED.value == "email.verified"
        assert IdentityEventType.SESSION_REVOKED.value == "session.revoked"


class TestContracts:
    def test_identity_context_defaults(self):
        ctx = IdentityContext()
        assert ctx.user_id == ""
        assert ctx.org_id == ""
        assert not ctx.is_authenticated

    def test_identity_context_authenticated(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        ctx = IdentityContext(
            user_id="u1", org_id="o1", session_id="s1",
            expires_at=future,
        )
        assert ctx.is_authenticated
        assert not ctx.is_expired

    def test_identity_context_expired(self):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        ctx = IdentityContext(expires_at=past)
        assert ctx.is_expired

    def test_provider_type_values(self):
        assert ProviderType.EMAIL.value == "email"
        assert ProviderType.GOOGLE.value == "google"
        assert ProviderType.SAML.value == "saml"

    def test_auth_request_defaults(self):
        req = AuthRequest()
        assert req.authorize_url == ""

    def test_external_identity_defaults(self):
        ext = ExternalIdentity()
        assert ext.provider == ProviderType.EMAIL


class TestUserModel:
    def test_create_user(self):
        user = User(display_name="Alice", locale="en")
        assert user.display_name == "Alice"
        assert user.locale == "en"
        assert not user.is_deleted
        assert UUID(user.id)

    def test_soft_delete(self):
        user = User()
        assert not user.is_deleted
        user.soft_delete()
        assert user.is_deleted
        assert user.deleted_at is not None

    def test_updated_on_delete(self):
        user = User()
        old_updated = user.updated_at
        user.soft_delete()
        assert user.updated_at >= old_updated


class TestEmailIdentityModel:
    def test_create_email_identity(self):
        ei = EmailIdentity(email="a@b.com", user_id="u1")
        assert str(ei.email) == "a@b.com"
        assert not ei.is_verified
        assert ei.is_primary is False

    def test_verify(self):
        ei = EmailIdentity(email="a@b.com")
        assert not ei.is_verified
        ei.verify()
        assert ei.is_verified
        assert ei.verified_at is not None


class TestPasswordCredentialModel:
    def test_create_credential(self):
        pc = PasswordCredential(user_id="u1", password_hash="$hash$value")
        assert pc.user_id == "u1"

    def test_update_hash(self):
        pc = PasswordCredential(user_id="u1", password_hash="$old")
        old_time = pc.last_changed_at
        pc.update_hash(PasswordHash("$new"))
        assert str(pc.password_hash) == "$new"
        assert pc.last_changed_at >= old_time


class TestOrganizationModel:
    def test_create_organization(self):
        org = Organization(name="Acme Corp", slug="acme-corp", owner_id="u1")
        assert org.name == "Acme Corp"
        assert not org.is_deleted

    def test_soft_delete(self):
        org = Organization(name="Test")
        org.soft_delete()
        assert org.is_deleted


class TestMembershipModel:
    def test_create_membership(self):
        m = Membership(user_id="u1", organization_id="o1", role="admin")
        assert m.is_active
        assert m.role == "admin"

    def test_suspend(self):
        m = Membership(user_id="u1", organization_id="o1")
        assert m.is_active
        m.suspend()
        assert not m.is_active
        assert m.status == MembershipStatus.SUSPENDED

    def test_activate(self):
        m = Membership(
            user_id="u1", organization_id="o1", status=MembershipStatus.INVITED,
        )
        m.activate()
        assert m.is_active
        assert m.accepted_at is not None


class TestSessionModel:
    def test_create_session(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        s = Session(user_id="u1", expires_at=future)
        assert s.is_active
        assert not s.is_revoked

    def test_expired_session(self):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        s = Session(user_id="u1", expires_at=past)
        assert s.is_expired
        assert not s.is_active

    def test_revoked_session(self):
        s = Session(user_id="u1")
        s.revoke()
        assert s.is_revoked
        assert not s.is_active

    def test_touch_updates_activity(self):
        s = Session(user_id="u1")
        old = s.last_activity_at
        s.touch()
        assert s.last_activity_at >= old


class TestRefreshTokenModel:
    def test_create_refresh_token(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        rt = RefreshToken(session_id="s1", family="f1", expires_at=future)
        assert rt.sequence == 1
        assert rt.is_active

    def test_revoke(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        rt = RefreshToken(session_id="s1", expires_at=future)
        rt.revoke()
        assert rt.is_revoked

    def test_sequence_increment(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        rt = RefreshToken(session_id="s1", family="f1", sequence=5, expires_at=future)
        assert rt.sequence == 5


class TestVerificationTokenModel:
    def test_create_verification_token(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        vt = VerificationToken(
            target="a@b.com", purpose=VerificationTokenPurpose.VERIFY_EMAIL,
            expires_at=future,
        )
        assert vt.is_valid
        assert not vt.is_used

    def test_mark_used(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        vt = VerificationToken(target="a@b.com", expires_at=future)
        vt.mark_used()
        assert vt.is_used
        assert not vt.is_valid

    def test_expired_token(self):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        vt = VerificationToken(target="a@b.com", expires_at=past)
        assert vt.is_expired
        assert not vt.is_valid


class TestInvitationModel:
    def test_create_invitation(self):
        future = datetime.now(timezone.utc) + timedelta(days=7)
        inv = Invitation(
            organization_id="o1", invitee_email="a@b.com", expires_at=future,
        )
        assert inv.is_pending

    def test_accept(self):
        future = datetime.now(timezone.utc) + timedelta(days=7)
        inv = Invitation(
            organization_id="o1", invitee_email="a@b.com", expires_at=future,
        )
        inv.accept()
        assert inv.status == InvitationStatus.ACCEPTED
        assert inv.accepted_at is not None

    def test_revoke(self):
        inv = Invitation(organization_id="o1", invitee_email="a@b.com")
        inv.revoke()
        assert inv.status == InvitationStatus.REVOKED


class TestPasswordResetRequestModel:
    def test_create_reset_request(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        pr = PasswordResetRequest(user_id="u1", expires_at=future)
        assert pr.is_valid

    def test_mark_used(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        pr = PasswordResetRequest(user_id="u1", expires_at=future)
        pr.mark_used()
        assert pr.is_used

    def test_expired(self):
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        pr = PasswordResetRequest(user_id="u1", expires_at=past)
        assert pr.is_expired

    def test_invalid_when_used(self):
        pr = PasswordResetRequest(user_id="u1")
        pr.mark_used()
        assert not pr.is_valid


class TestExternalIdentityModel:
    def test_create_external_identity(self):
        ei = ExternalIdentityModel(
            user_id="u1", provider_type="google", provider_subject="12345",
        )
        assert ei.user_id == "u1"
        assert ei.provider_type == "google"
        assert ei.provider_subject == "12345"
        assert ei.linked_at is not None
        assert ei.last_login_at is not None

    def test_with_full_details(self):
        ei = ExternalIdentityModel(
            user_id="u1",
            provider_type="github",
            provider_subject="gh_user",
            email="gh@test.com",
            display_name="GH User",
            avatar_url="https://avatars.example.com/gh_user",
            provider_metadata={"login": "gh_user", "org": "loqi"},
        )
        assert ei.email == "gh@test.com"
        assert ei.display_name == "GH User"
        assert ei.avatar_url.startswith("https://")
        assert ei.provider_metadata["login"] == "gh_user"

    def test_auto_id(self):
        ei = ExternalIdentityModel(user_id="u1", provider_type="microsoft", provider_subject="456")
        from uuid import UUID
        assert UUID(ei.id)


class TestConfig:
    def test_default_config(self):
        assert IDENTITY_CONFIG.argon2.memory_cost == 65536
        assert IDENTITY_CONFIG.tokens.verification_token_ttl_seconds == 900
        assert IDENTITY_CONFIG.tokens.session_ttl_seconds == 900
        assert IDENTITY_CONFIG.tokens.refresh_token_ttl_seconds == 2592000
        assert IDENTITY_CONFIG.password.min_length == 12
        assert IDENTITY_CONFIG.sessions.max_active_sessions_per_user == 25

    def test_password_config_requirements(self):
        cfg = IDENTITY_CONFIG.password
        assert cfg.require_uppercase
        assert cfg.require_lowercase
        assert cfg.require_digit
        assert cfg.require_special

    def test_token_config_bytes(self):
        assert IDENTITY_CONFIG.tokens.verification_token_bytes == 32
        assert IDENTITY_CONFIG.tokens.refresh_token_bytes == 32


class TestInMemoryCryptoService:
    def test_hash_and_verify_password(self):
        svc = InMemoryCryptoService()
        hashed = svc.hash_password("secure_password")
        assert svc.verify_password("secure_password", hashed)
        assert not svc.verify_password("wrong_password", hashed)

    def test_random_token_generation(self):
        svc = InMemoryCryptoService()
        token = svc.random_token(32)
        assert len(token) > 20
        assert token.startswith("tok_")

    def test_token_hash_is_deterministic(self):
        svc = InMemoryCryptoService()
        h1 = svc.hash_token("abc")
        h2 = svc.hash_token("abc")
        assert str(h1) == str(h2)

    def test_encrypt_decrypt(self):
        svc = InMemoryCryptoService()
        encrypted = svc.encrypt("secret_data", "user_context")
        decrypted = svc.decrypt(encrypted, "user_context")
        assert decrypted == "secret_data"

    def test_encrypt_decrypt_wrong_context_fails(self):
        svc = InMemoryCryptoService()
        encrypted = svc.encrypt("secret", "ctx1")
        with pytest.raises(ValueError):
            svc.decrypt(encrypted, "wrong_ctx")

    def test_sign_and_verify(self):
        svc = InMemoryCryptoService()
        sig = svc.sign("important_data", "key1")
        assert svc.verify("important_data", sig, "key1")
        assert not svc.verify("tampered_data", sig, "key1")
